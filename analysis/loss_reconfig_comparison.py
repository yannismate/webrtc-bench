import argparse
import os
from collections import defaultdict
from typing import List, Tuple, Dict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from loaders.measurement import Measurement


def extract_type(folder_path: str) -> str:
    base = os.path.basename(os.path.normpath(folder_path))
    if base.startswith("video-"):
        base = base[len("video-"):]
    parts = base.split("-")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    t = "-".join(parts).strip()
    return t or base


def resolve_measurement_folders(paths: List[str]) -> List[str]:
    if len(paths) == 1 and os.path.isdir(paths[0]):
        root = paths[0]
        try:
            potential = [os.path.join(root, name) for name in os.listdir(root)]
            dirs = sorted([p for p in potential if os.path.isdir(p)])
            measurements = [d for d in dirs if os.path.basename(d).startswith(("video-", "bandwidth_measurement-"))]
            if measurements:
                return measurements
            if dirs:
                return dirs
        except Exception:
            pass
    return paths


def compute_loss_samples(parquet_data, resample_ms: int) -> pd.DataFrame:
    required_cols = {"InboundRTP.PacketsLost", "InboundRTP.PacketsReceived"}
    missing = required_cols - set(parquet_data.data.columns)
    if missing:
        raise ValueError(f"Missing required parquet columns: {', '.join(sorted(missing))}")

    freq = f"{resample_ms}ms"
    lost = parquet_data.data["InboundRTP.PacketsLost"].resample(freq).max().diff().fillna(0).clip(lower=0)
    received = parquet_data.data["InboundRTP.PacketsReceived"].resample(freq).max().diff().fillna(0).clip(lower=0)
    counts = pd.DataFrame({
        "lost_packets": lost,
        "received_packets": received,
    })
    counts["total_packets"] = counts["lost_packets"] + counts["received_packets"]
    counts = counts[counts["total_packets"] > 0]
    return counts


def build_reconfig_windows(measurement: Measurement, window_seconds: float) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    if measurement.data_dishy_sender is None and measurement.data_dishy_receiver is None:
        return []
    delta = pd.Timedelta(seconds=window_seconds)
    return [(ts - delta, ts + delta) for _, ts in measurement.get_handover_times()]


def filter_df_by_windows(df: pd.DataFrame, windows: List[Tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    if not windows:
        return df.iloc[0:0]
    idx = df.index
    mask = np.zeros(len(df), dtype=bool)
    for start, end in windows:
        mask |= (idx >= start) & (idx <= end)
    return df[mask]


def aggregate_measurement(folder: str, resample_ms: int, window_seconds: float) -> Dict:
    measurement = Measurement(folder)
    measurement.load_files(only=["parquet", "dishy"])

    if measurement.data_parquet_receiver is None:
        raise ValueError(f"{folder}: missing receiver parquet data; skipping")

    samples = compute_loss_samples(measurement.data_parquet_receiver, resample_ms)
    if samples.empty:
        raise ValueError(f"{folder}: no usable loss samples")

    total_packets = samples["total_packets"].sum()
    lost_packets = samples["lost_packets"].sum()

    reconfig_windows = build_reconfig_windows(measurement, window_seconds)
    reconfig_samples = filter_df_by_windows(samples, reconfig_windows)
    reconfig_total_packets = reconfig_samples["total_packets"].sum()
    reconfig_lost_packets = reconfig_samples["lost_packets"].sum()

    parent = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    base = os.path.basename(os.path.normpath(folder))
    name = f"{parent}/{base}" if parent else base

    return {
        "folder": folder,
        "name": name,
        "type": extract_type(folder),
        "total_packets": float(total_packets),
        "lost_packets": float(lost_packets),
        "reconfig_total_packets": float(reconfig_total_packets),
        "reconfig_lost_packets": float(reconfig_lost_packets),
        "had_reconfigs": bool(reconfig_windows),
    }


def summarize_by_type(records: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    grouped = df.groupby("type", as_index=False).sum(numeric_only=True)
    grouped["overall_loss_pct"] = np.where(
        grouped["total_packets"] > 0,
        (grouped["lost_packets"] / grouped["total_packets"]) * 100,
        np.nan,
    )
    grouped["reconfig_loss_pct"] = np.where(
        grouped["reconfig_total_packets"] > 0,
        (grouped["reconfig_lost_packets"] / grouped["reconfig_total_packets"]) * 100,
        np.nan,
    )
    grouped.sort_values("type", inplace=True)
    return grouped


def print_summary_table(df: pd.DataFrame):
    cols = [
        ("Type", 30),
        ("Packets", 12),
        ("Lost", 12),
        ("Loss %", 10),
        ("Reconfig Packets", 18),
        ("Reconfig Lost", 16),
        ("Reconfig Loss %", 18),
    ]
    header = " ".join(title.ljust(width) for title, width in cols)
    print("\n" + header)
    print("-" * len(header))
    for _, row in df.iterrows():
        values = [
            str(row["type"]).ljust(30),
            f"{int(row['total_packets']):,}".ljust(12),
            f"{int(row['lost_packets']):,}".ljust(12),
            (f"{row['overall_loss_pct']:.2f}%" if pd.notna(row['overall_loss_pct']) else "N/A").ljust(10),
            f"{int(row['reconfig_total_packets']):,}".ljust(18),
            f"{int(row['reconfig_lost_packets']):,}".ljust(16),
            (f"{row['reconfig_loss_pct']:.2f}%" if pd.notna(row['reconfig_loss_pct']) else "N/A").ljust(18),
        ]
        print(" ".join(values))


def plot_loss_bars(df: pd.DataFrame, window_seconds: float):
    if df.empty:
        print("No aggregated data available for plotting.")
        return

    labels = df["type"].tolist()
    overall = df["overall_loss_pct"].to_numpy()
    reconfig = df["reconfig_loss_pct"].to_numpy()

    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.5), 5))
    overall_bars = ax.bar(x - width / 2, overall, width, label="Overall")
    reconfig_bars = ax.bar(x + width / 2, np.nan_to_num(reconfig, nan=0.0), width,
                           label=f"Reconfig ±{window_seconds:.1f}s")

    def annotate_bars(bars, values):
        for bar, value in zip(bars, values):
            if pd.isna(value):
                ax.annotate("N/A", xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8)
            else:
                ax.annotate(f"{value:.2f}%", xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8)

    annotate_bars(overall_bars, overall)
    annotate_bars(reconfig_bars, reconfig)

    ax.set_ylabel("Loss Percentage")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylim(0, max(np.nanmax(overall), np.nanmax(np.nan_to_num(reconfig, nan=0))) * 1.2 if labels else 1)
    ax.set_title("Packet Loss vs. Reconfiguration Windows")
    ax.legend()
    fig.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Compare total packet loss percentages per type overall vs. Dishy reconfiguration windows (parquet data only)."
    )
    parser.add_argument("paths", nargs="+", help="Measurement folders or a directory containing them")
    parser.add_argument("--resample-ms", type=int, default=200,
                        help="Resample interval for packet counters (default: 200ms)")
    parser.add_argument("--window-seconds", type=float, default=2.0,
                        help="Half-width of the window around each reconfiguration (default: ±2s)")
    args = parser.parse_args()

    folders = resolve_measurement_folders(args.paths)

    records: List[Dict] = []
    for folder in folders:
        if not os.path.isdir(folder):
            print(f"Skipping non-directory path: {folder}")
            continue
        try:
            records.append(aggregate_measurement(folder, args.resample_ms, args.window_seconds))
        except Exception as exc:
            print(f"Warning: {exc}")

    if not records:
        raise SystemExit("No valid measurements to analyze.")

    summary = summarize_by_type(records)
    print_summary_table(summary)
    plot_loss_bars(summary, args.window_seconds)


if __name__ == "__main__":
    main()
