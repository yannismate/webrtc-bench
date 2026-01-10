import os
import argparse
from typing import List, Tuple, Optional, Dict

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

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


def gather_measurement(folder: str) -> Dict:
    m = Measurement(folder)
    # Load irtt explicitly. icmp_ping is lazy loaded by get_icmp_pings().
    m.load_files(only=['irtt'])

    icmp_values: List[float] = []
    # This triggers loading icmp files if present
    icmp_series = m.get_icmp_pings()
    if icmp_series is not None:
        icmp_values = icmp_series.to_numpy().tolist()

    irtt_values: List[float] = []
    if m.data_irtt is not None:
        # Access irtt directly to ensure we get IRTT data regardless of preference logic in get_rtt_ms
        ser = m.data_irtt.get_rtt_ms()
        if ser is not None:
            irtt_values = ser.to_numpy().tolist()

    base = os.path.basename(os.path.normpath(folder))
    parent = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    name = f"{parent}/{base}" if parent else base

    return {
        "folder": folder,
        "name": name,
        "type": extract_type(folder),
        "icmp": [v for v in icmp_values if np.isfinite(v) and v >= 0],
        "irtt": [v for v in irtt_values if np.isfinite(v) and v >= 0],
    }


def main():
    parser = argparse.ArgumentParser(description="Plot CDFs for ICMP Ping RTT and IRTT RTT from measurement folders.")
    parser.add_argument("paths", nargs="+", help="One or more paths to measurement folders or a root folder containing them")
    parser.add_argument("--combined-only", action="store_true", help="Show only one aggregated CDF per category (type) and hide individual measurements")
    args = parser.parse_args()

    folders: List[str] = args.paths
    combined_only: bool = args.combined_only

    if len(folders) == 1 and os.path.isdir(folders[0]):
        root = folders[0]
        try:
            children = [os.path.join(root, n) for n in os.listdir(root)]
            child_dirs = sorted([p for p in children if os.path.isdir(p)])
            if child_dirs:
                # Filter to measurement-like folder names if possible, but keep it broad
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
            datasets.append(gather_measurement(folder))
        except Exception as e:
            print(f"Warning processing {folder}: {e}")

    if not datasets:
        raise SystemExit("No valid folders to analyze.")

    from collections import defaultdict
    groups = defaultdict(list)
    for d in datasets:
        groups[d["type"]].append(d)

    any_icmp = any(len(d["icmp"]) > 0 for d in datasets)
    any_irtt = any(len(d["irtt"]) > 0 for d in datasets)

    rows = 2
    fig, axes = plt.subplots(rows, 1, figsize=(8, 8))
    # axes is an array of Axes objects
    ax_icmp, ax_irtt = axes

    sns.set_style("whitegrid")
    palette = sns.color_palette("tab10")
    
    # Determine types order for consistent coloring
    types_in_order: List[str] = []
    for d in datasets:
        if d["type"] not in types_in_order:
            types_in_order.append(d["type"])
    type_to_color = {t: palette[i % len(palette)] for i, t in enumerate(types_in_order)}

    shown_labels = set()

    def plot_metric(ax, metric_key: str, x_label: str, title: str, has_data: bool):
        if not has_data:
            ax.set_title(f"{title} (no data)")
            ax.set_xticks([])
            ax.set_yticks([])
            return
        ax.set_title(title)
        
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
            # Only label in the first plot accessed, handled via shown_labels check
            ax.plot(x, y, label=lbl, color=type_to_color[d["type"]], linewidth=1.2, alpha=0.6)
            if lbl:
                shown_labels.add(d["name"])
        
        ax.set_xlabel(x_label)
        ax.set_ylabel("Probability")
        ax.set_ylim(0, 1)

    plot_metric(ax_icmp, "icmp", "RTT (ms)", "ICMP Ping RTT", any_icmp)
    plot_metric(ax_irtt, "irtt", "RTT (ms)", "IRTT RTT", any_irtt)

    type_label_added = set()
    for t, items in groups.items():
        if not combined_only and len(items) < 2:
            continue

        color = type_to_color[t]
        icmp_all = [v for it in items for v in it["icmp"]]
        irtt_all = [v for it in items for v in it["irtt"]]

        base_label = t if combined_only else f"{t} (all)"
        
        # Plot ICMP aggregate
        if any_icmp:
            x, y = compute_cdf(icmp_all)
            if x.size:
                lbl = base_label if t not in type_label_added else None
                ax_icmp.plot(x, y, linestyle="--", linewidth=2, color=color, label=lbl)
                if lbl: type_label_added.add(t)

        # Plot IRTT aggregate
        if any_irtt:
            x, y = compute_cdf(irtt_all)
            if x.size:
                lbl = base_label if t not in type_label_added else None
                ax_irtt.plot(x, y, linestyle="--", linewidth=2, color=color, label=lbl)
                if lbl: type_label_added.add(t)

    # Legend on first populated axis
    first_axis_with_data: Optional[plt.Axes] = None
    for ax, flag in [(ax_icmp, any_icmp), (ax_irtt, any_irtt)]:
        if flag and first_axis_with_data is None:
            first_axis_with_data = ax
            
    if first_axis_with_data is not None:
        first_axis_with_data.legend(loc="lower right", fontsize="small")

    names_for_title = ", ".join(d["name"] for d in datasets)
    # truncate if too long
    if len(names_for_title) > 60:
         names_for_title = names_for_title[:60] + "..."

    title_mode = "Combined" if combined_only else "Individual + Combined"
    fig.suptitle(f"{title_mode} CDFs for ICMP & IRTT | {names_for_title}", fontsize=12)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    plt.show()

if __name__ == "__main__":
    main()

