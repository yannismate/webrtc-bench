import os
import argparse
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

from loaders.measurement import Measurement

WEATHER_FEATURES = [
    "global_solar_radiation_w_m2",
    "atmospheric_counter_radiation_w_m2",
    "longwave_outgoing_radiation_w_m2",
    "average_relative_humidity_percent",
    "current_precip_mm_per_min",
]
NETWORK_FEATURES = ["avg_throughput_kbps", "avg_jitter_ms", "avg_loss_rate"]


def _folder_to_hour_timestamp(folder_name: str) -> Tuple[float, str] | None:
    """Extract hour timestamp and advanced name from folder name.

    Expected pattern: <type>-<advanced-name>-<unix_ts>
    Returns (hour_epoch_seconds, advanced_name) or None if invalid.
    """
    parts = folder_name.split("-")
    if len(parts) < 3:
        return None
    ts_part = parts[-1]
    advanced_name = "-".join(parts[1:-1])
    try:
        parsed_ts = datetime.fromtimestamp(int(ts_part))
    except Exception:
        return None
    hour_ts = parsed_ts.replace(second=0, microsecond=0, minute=0).timestamp()
    return hour_ts, advanced_name


def _safe_mean(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    return float(series.mean())


def _process_measurement(folder_path: str, resample_ms: int) -> Tuple[Optional[float], Optional[float], Optional[float], object | None, str]:
    """Load a single measurement and return (avg_throughput_kbps, avg_jitter_ms, avg_loss_rate, weather_data, advanced_name)."""
    m = Measurement(folder_path)
    m.load_files()
    recv_br = m.get_recv_bitrate_kbps(resample_ms)
    jitter = m.get_jitter_ms()
    loss = m.get_loss_rate()
    return _safe_mean(recv_br), _safe_mean(jitter), _safe_mean(loss), m.weather_data, m.name


def build_hourly_dataset(root_path: str, resample_ms: int) -> pd.DataFrame:
    """Walk result folders; produce per hour & advanced-name averages + weather snapshot.

    Returns DataFrame with columns: hour_ts, advanced_name, WEATHER_FEATURES + NETWORK_FEATURES.
    Rows require weather present for that hour (weather shared across measurements in same hour).
    """
    hourly_weather: Dict[float, object] = {}
    entries: List[Dict[str, object]] = []

    for dir_path, dir_names, _ in os.walk(root_path):
        for dir_name in dir_names:
            parsed = _folder_to_hour_timestamp(dir_name)
            if parsed is None:
                continue
            hour_ts, _adv = parsed
            folder = os.path.join(dir_path, dir_name)
            try:
                avg_br, avg_jitter, avg_loss, weather, adv_name = _process_measurement(folder, resample_ms)
                if hour_ts not in hourly_weather and weather is not None:
                    hourly_weather[hour_ts] = weather
                # We'll create an entry; weather may come from a different measurement of same hour
                row: Dict[str, object] = {
                    "hour_ts": hour_ts,
                    "advanced_name": adv_name,
                    "avg_throughput_kbps": avg_br,
                    "avg_jitter_ms": avg_jitter,
                    "avg_loss_rate": avg_loss,
                }
                entries.append(row)
            except Exception as e:
                print(f"Skipping {folder}: {e}")

    # Attach weather snapshot (shared per hour) & filter rows lacking weather
    for row in entries:
        weather = hourly_weather.get(row["hour_ts"])
        if weather is None:
            # Mark for drop
            row["_drop"] = True
            continue
        for wf in WEATHER_FEATURES:
            row[wf] = getattr(weather, wf, None)

    df = pd.DataFrame(entries)
    if "_drop" in df.columns:
        df = df[df["_drop"] != True].drop(columns=["_drop"])
    return df


def compute_cross_correlation(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Pearson correlations between weather features and network metrics only (all data)."""
    subset = df.dropna(subset=WEATHER_FEATURES + NETWORK_FEATURES, how="any")
    if subset.empty:
        return pd.DataFrame(columns=NETWORK_FEATURES, index=WEATHER_FEATURES)
    corr_matrix = pd.DataFrame(index=WEATHER_FEATURES, columns=NETWORK_FEATURES, dtype=float)
    for w in WEATHER_FEATURES:
        for n in NETWORK_FEATURES:
            corr_matrix.loc[w, n] = subset[w].corr(subset[n])
    return corr_matrix


def compute_cross_correlation_per_advanced(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Return dict of advanced_name -> correlation matrix (weather vs network)."""
    result: Dict[str, pd.DataFrame] = {}
    for adv_name, group in df.groupby("advanced_name"):
        subset = group.dropna(subset=WEATHER_FEATURES + NETWORK_FEATURES, how="any")
        if subset.empty or len(subset) < 2:  # Need at least 2 rows for correlation
            continue
        corr_matrix = pd.DataFrame(index=WEATHER_FEATURES, columns=NETWORK_FEATURES, dtype=float)
        for w in WEATHER_FEATURES:
            for n in NETWORK_FEATURES:
                corr_matrix.loc[w, n] = subset[w].corr(subset[n])
        result[adv_name] = corr_matrix
    return result


def plot_heatmap(corr_df: pd.DataFrame, title: str):
    plt.figure(figsize=(10, 6))
    sns.heatmap(corr_df, annot=True, fmt=".2f", cmap="coolwarm", center=0)
    plt.title(title)
    plt.ylabel("Weather Features")
    plt.xlabel("Network Metrics")
    plt.tight_layout()


def main():
    parser = argparse.ArgumentParser(description="Correlate weather data with average loss, jitter, and bitrate.")
    parser.add_argument("path", help="Path to results root")
    parser.add_argument("--resample-ms", type=int, default=200, help="Resampling interval for bitrate series (ms)")
    parser.add_argument("--output-csv", default=None, help="Optional: save overall correlation matrix to CSV")
    parser.add_argument("--per-advanced", action="store_true", help="Generate heatmap per advanced-name")
    args = parser.parse_args()

    df = build_hourly_dataset(args.path, args.resample_ms)
    if df.empty:
        print("No combined weather/network data available for correlation.")
        return

    corr_df = compute_cross_correlation(df)
    if args.output_csv:
        csv_path = os.path.join(args.path, args.output_csv)
        corr_df.to_csv(csv_path)
        print(f"Correlation matrix CSV saved to {csv_path}")

    plot_heatmap(corr_df, "Weather vs Network Metric Correlation (All Data)")

    if args.per_advanced:
        per_adv = compute_cross_correlation_per_advanced(df)
        if not per_adv:
            print("No advanced-name specific correlations available (insufficient data).")
        else:
            for adv_name, cdf in per_adv.items():
                plot_heatmap(cdf, f"Correlation for {adv_name}")

    plt.show()


if __name__ == "__main__":
    main()
