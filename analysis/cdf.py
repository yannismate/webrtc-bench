import os
import argparse
from typing import List, Tuple, Optional, Dict

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
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


def extract_type(folder_path: str) -> str:
    base = os.path.basename(os.path.normpath(folder_path))
    if base.startswith("video-"):
        base = base[len("video-"):]
    parts = base.split("-")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    t = "-".join(parts).strip()
    return t or base


def gather_measurement(folder: str, resample_ms: int, reconfig_window: bool = False,
                       window_seconds: float = 2.0) -> Dict:
    m = Measurement(folder)
    m.load_files()

    reconfig_windows: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    if reconfig_window:
        if m.data_dishy_sender is None and m.data_dishy_receiver is None:
            raise ValueError(f"{folder}: --reconfig-window requires Dishy data; skipping measurement.")
        window_delta = pd.Timedelta(seconds=window_seconds)
        reconfig_times = m.get_reconfiguration_times()
        reconfig_windows = [(ts - window_delta, ts + window_delta) for _, ts in reconfig_times]
        if not reconfig_windows:
            print(f"Warning: {folder} has --reconfig-window enabled but no reconfiguration events were detected.")

    def apply_reconfig_window(series):
        if not reconfig_window or series is None:
            return series
        if series.empty:
            return series
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError(f"{folder}: Cannot apply --reconfig-window because series index is not datetime based.")
        mask = np.zeros(len(series), dtype=bool)
        idx = series.index
        for start, end in reconfig_windows:
            mask |= (idx >= start) & (idx <= end)
        return series[mask]

    def series_to_list(series, scale: float = 1.0) -> List[float]:
        if series is None:
            return []
        filtered = apply_reconfig_window(series)
        if filtered is None or filtered.empty:
            return []
        return (filtered.to_numpy() * scale).tolist()

    bitrate_values_mbps: List[float] = []
    rtt_values_ms: List[float] = []
    jitter_values_ms: List[float] = []
    source_used: Optional[str] = None

    # Bitrate preference mirrors old script intent (receiver preferred)
    if m.data_iperf_receiver is not None:
        recv_vals = series_to_list(m.get_recv_bitrate_kbps(resample_ms), scale=0.001)
        if recv_vals:
            bitrate_values_mbps = recv_vals
            source_used = "iperf (receiver)"
    elif m.data_iperf_sender is not None:
        send_vals = series_to_list(m.get_send_bitrate_kbps(resample_ms), scale=0.001)
        if send_vals:
            bitrate_values_mbps = send_vals
            source_used = "iperf (sender)"
    elif m.data_parquet_receiver is not None:
        recv_vals = series_to_list(m.get_recv_bitrate_kbps(resample_ms), scale=0.001)
        if recv_vals:
            bitrate_values_mbps = recv_vals
            source_used = "parquet (receiver)"
    elif m.data_parquet_sender is not None:
        send_vals = series_to_list(m.get_send_bitrate_kbps(resample_ms), scale=0.001)
        if send_vals:
            bitrate_values_mbps = send_vals
            source_used = "parquet (sender)"

    rtt = series_to_list(m.get_rtt_ms())
    if rtt:
        rtt_values_ms = rtt
        source_used = source_used or "rtt"

    jitter = series_to_list(m.get_jitter_ms())
    if jitter:
        jitter_values_ms = jitter
        source_used = source_used or "jitter"

    base = os.path.basename(os.path.normpath(folder))
    parent = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    name = f"{parent}/{base}" if parent else base

    return {
        "folder": folder,
        "name": name,
        "type": extract_type(folder),
        "bitrate": [v for v in bitrate_values_mbps if np.isfinite(v) and v >= 0],
        "rtt": [v for v in rtt_values_ms if np.isfinite(v) and v >= 0],
        "jitter": [v for v in jitter_values_ms if np.isfinite(v) and v >= 0],
        "source": source_used or "unknown",
    }


def main():
    parser = argparse.ArgumentParser(description="Plot CDFs for Bitrate, RTT, and Jitter from one or more measurement folders (iperf or parquet) using shared loader.")
    parser.add_argument("paths", nargs="+", help="One or more paths to measurement folders or a root folder containing them")
    parser.add_argument("--resample-ms", type=int, default=100, help="Resample interval for rate calculations in ms (default: 100)")
    parser.add_argument("--combined-only", action="store_true", help="Show only one aggregated CDF per category (type) and hide individual measurements")
    parser.add_argument("--reconfig-window", action="store_true",
                        help="Limit samples to ±1s around each Dishy reconfiguration event (measurements without Dishy data are skipped)")
    args = parser.parse_args()

    folders: List[str] = args.paths
    resample_ms: int = args.resample_ms
    combined_only: bool = args.combined_only
    use_reconfig_window: bool = args.reconfig_window

    if len(folders) == 1 and os.path.isdir(folders[0]):
        root = folders[0]
        try:
            children = [os.path.join(root, n) for n in os.listdir(root)]
            child_dirs = sorted([p for p in children if os.path.isdir(p)])
            # Heuristic: if root itself likely container, use its subdirs
            if child_dirs:
                # Filter to measurement-like folder names
                meas_dirs = [d for d in child_dirs if os.path.basename(d).startswith(("video-", "bandwidth_measurement-"))]
                if meas_dirs:
                    folders = meas_dirs
                else:
                    folders = child_dirs
        except Exception:
            pass

    datasets = []
    for folder in folders:
        if not os.path.isdir(folder):
            print(f"Warning: Skipping non-directory path: {folder}")
            continue
        try:
            datasets.append(gather_measurement(folder, resample_ms, use_reconfig_window))
        except Exception as e:
            print(f"Warning: {e}")

    if not datasets:
        raise SystemExit("No valid folders to analyze.")

    # Pre-compute type groups early to avoid NameError if later refactors move code
    from collections import defaultdict
    groups = defaultdict(list)
    for d in datasets:
        groups[d["type"].strip()].append(d)

    any_bit = any(len(d["bitrate"]) > 0 for d in datasets)
    any_rtt = any(len(d["rtt"]) > 0 for d in datasets)
    any_jit = any(len(d["jitter"]) > 0 for d in datasets)

    rows = 3
    fig, axes = plt.subplots(rows, 1, figsize=(8, 12))
    ax_bit, ax_rtt, ax_jit = axes

    sns.set_style("whitegrid")

    palette = sns.color_palette("tab10")
    types_in_order: List[str] = []
    for d in datasets:
        if d["type"] not in types_in_order:
            types_in_order.append(d["type"])
    type_to_color = {t: palette[i % len(palette)] for i, t in enumerate(types_in_order)}

    shown_labels = set()

    window_suffix = " (±1s around Dishy reconfigurations)" if use_reconfig_window else ""

    def plot_metric(ax, metric_key: str, x_label: str, title: str, has_data: bool):
        if not has_data:
            ax.set_title(f"{title} (no data)")
            ax.set_xticks([])
            ax.set_yticks([])
            return
        ax.set_title(f"{title}{window_suffix}")
        if combined_only:
            ax.set_xlabel(x_label)
            ax.set_ylabel("Probability")
            ax.set_ylim(0, 1)
            return
        for d in datasets:
            vals = d[metric_key]
            x, y = compute_cdf(vals)
            if x.size == 0:
                continue
            lbl = d["name"] if d["name"] not in shown_labels else None
            ax.plot(x, y, label=lbl, color=type_to_color[d["type"]], linewidth=1.2)
            if lbl:
                shown_labels.add(d["name"])
        ax.set_xlabel(x_label)
        ax.set_ylabel("Probability")
        ax.set_ylim(0, 1)

    plot_metric(ax_bit, "bitrate", "Mbps", "Bitrate CDF", any_bit)
    plot_metric(ax_rtt, "rtt", "ms", "RTT CDF", any_rtt)
    plot_metric(ax_jit, "jitter", "ms", "Jitter CDF", any_jit)

    type_label_added = set()
    for t, items in groups.items():
        if not combined_only and len(items) < 2:
            continue
        color = type_to_color[t]
        bit_all = [v for it in items for v in it["bitrate"]]
        rtt_all = [v for it in items for v in it["rtt"]]
        jit_all = [v for it in items for v in it["jitter"]]
        base_label = t if combined_only else f"{t} (all)"
        label_for_bit = base_label if t not in type_label_added else None
        if any_bit:
            x, y = compute_cdf(bit_all)
            if x.size:
                ax_bit.plot(x, y, linestyle="--", linewidth=2, color=color, label=label_for_bit)
                if label_for_bit:
                    type_label_added.add(t)
        if any_rtt:
            x, y = compute_cdf(rtt_all)
            if x.size:
                lab = None if t in type_label_added else base_label
                ax_rtt.plot(x, y, linestyle="--", linewidth=2, color=color, label=lab)
                if lab:
                    type_label_added.add(t)
        if any_jit:
            x, y = compute_cdf(jit_all)
            if x.size:
                lab = None if t in type_label_added else base_label
                ax_jit.plot(x, y, linestyle="--", linewidth=2, color=color, label=lab)
                if lab:
                    type_label_added.add(t)

    # Consolidate legend on first axis with any data
    first_axis_with_data: Optional[plt.Axes] = None
    for ax, flag in [(ax_bit, any_bit), (ax_rtt, any_rtt), (ax_jit, any_jit)]:
        if flag and first_axis_with_data is None:
            first_axis_with_data = ax
    if first_axis_with_data is not None:
        first_axis_with_data.legend(loc="lower right", fontsize="small")

    names_for_title = ", ".join(d["name"] for d in datasets)
    title_mode = "Combined" if combined_only else "Individual + Combined"
    fig.suptitle(f"{title_mode} CDFs for Bitrate, RTT, Jitter | Folders: {names_for_title}{window_suffix}", fontsize=14)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    plt.show()


if __name__ == "__main__":
    main()
