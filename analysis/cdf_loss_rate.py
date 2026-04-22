import argparse
import os
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from loaders.measurement import Measurement


def compute_cdf(values: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.array([]), np.array([])
    arr.sort()
    y = np.arange(1, arr.size + 1) / arr.size
    return arr, y


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


def build_reconfig_windows(measurement: Measurement, window_seconds: float) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    if measurement.data_dishy_sender is None and measurement.data_dishy_receiver is None:
        return []
    delta = pd.Timedelta(seconds=window_seconds)
    return [(ts - delta, ts + delta) for _, ts in measurement.get_handover_times()]


def compute_loss_rate_series(parquet_data, resample_ms: int) -> pd.Series:
    required_cols = {"InboundRTP.PacketsLost", "InboundRTP.PacketsReceived"}
    missing = required_cols - set(parquet_data.data.columns)
    if missing:
        raise ValueError(f"Missing required parquet columns: {', '.join(sorted(missing))}")

    freq = f"{resample_ms}ms"
    lost = parquet_data.data["InboundRTP.PacketsLost"].resample(freq).max().diff().fillna(0).clip(lower=0)
    received = parquet_data.data["InboundRTP.PacketsReceived"].resample(freq).max().diff().fillna(0).clip(lower=0)
    total = lost + received

    valid = total > 0
    loss_rate_pct = (lost[valid] / total[valid]) * 100
    loss_rate_pct = loss_rate_pct.replace([np.inf, -np.inf], np.nan).dropna()
    loss_rate_pct.name = "loss_rate_pct"
    return loss_rate_pct


def split_series_by_windows(series: pd.Series,
                            windows: List[Tuple[pd.Timestamp, pd.Timestamp]]) -> Tuple[pd.Series, pd.Series]:
    if series.empty:
        return series, series
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("loss rate series index is not datetime based")

    idx = series.index
    if not windows:
        return series.iloc[0:0], series

    in_window = np.zeros(len(series), dtype=bool)
    for start, end in windows:
        in_window |= (idx >= start) & (idx <= end)
    return series[in_window], series[~in_window]


def gather_loss_samples(folder: str, resample_ms: int, window_seconds: float) -> Tuple[List[float], List[float], List[float]]:
    measurement = Measurement(folder)
    measurement.load_files(only=["parquet", "dishy"])

    if measurement.data_parquet_receiver is None:
        raise ValueError(f"{folder}: missing receiver parquet data")

    loss_rate = compute_loss_rate_series(measurement.data_parquet_receiver, resample_ms)
    loss_rate = loss_rate[np.isfinite(loss_rate) & (loss_rate >= 0)]
    if loss_rate.empty:
        raise ValueError(f"{folder}: no usable loss rate samples")

    windows = build_reconfig_windows(measurement, window_seconds)
    in_window, out_window = split_series_by_windows(loss_rate, windows)

    all_vals = loss_rate.to_numpy(dtype=float).tolist()
    handover_vals = in_window.to_numpy(dtype=float).tolist()
    non_handover_vals = out_window.to_numpy(dtype=float).tolist()
    return all_vals, handover_vals, non_handover_vals


def main():
    parser = argparse.ArgumentParser(
        description="Plot aggregated loss rate CDF across measurements with and without handover windows."
    )
    parser.add_argument("paths", nargs="+", help="Measurement folders or a directory containing them")
    parser.add_argument("--resample-ms", type=int, default=1000,
                        help="Resample interval for packet counters (default: 200ms)")
    parser.add_argument("--window-seconds", type=float, default=2.0,
                        help="Half-width of the window around each handover (default: +/-2s)")
    args = parser.parse_args()

    folders = resolve_measurement_folders(args.paths)

    all_samples: List[float] = []
    handover_samples: List[float] = []
    non_handover_samples: List[float] = []

    used_folders = 0
    for folder in folders:
        if not os.path.isdir(folder):
            print(f"Skipping non-directory path: {folder}")
            continue
        try:
            all_vals, handover_vals, non_handover_vals = gather_loss_samples(folder, args.resample_ms, args.window_seconds)
            all_samples.extend(all_vals)
            handover_samples.extend(handover_vals)
            non_handover_samples.extend(non_handover_vals)
            used_folders += 1
        except Exception as exc:
            print(f"Warning: {exc}")

    if not all_samples:
        raise SystemExit("No valid loss rate samples to analyze.")

    x_all, y_all = compute_cdf(all_samples)
    x_handover, y_handover = compute_cdf(handover_samples)
    x_non_handover, y_non_handover = compute_cdf(non_handover_samples)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x_all, y_all, linewidth=2, color="tab:blue", label=f"All ({len(all_samples):,} samples)")

    if x_handover.size:
        ax.plot(
            x_handover,
            y_handover,
            linewidth=2,
            color="tab:orange",
            label=f"Handover +/-{args.window_seconds:.1f}s ({len(handover_samples):,} samples)",
        )
    else:
        print("Warning: No samples inside handover windows.")

    if x_non_handover.size:
        ax.plot(
            x_non_handover,
            y_non_handover,
            linewidth=2,
            color="tab:green",
            label=f"Outside handover windows ({len(non_handover_samples):,} samples)",
        )
    else:
        print("Warning: No samples outside handover windows.")

    ax.set_title("Aggregated Loss Rate CDF")
    ax.set_xlabel("Loss rate (%)")
    ax.set_ylabel("Probability")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")

    fig.suptitle(f"Folders used: {used_folders}", fontsize=10)
    fig.tight_layout(rect=(0, 0.03, 1, 0.98))
    plt.show()


if __name__ == "__main__":
    main()

