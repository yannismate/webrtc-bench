import os
import json
import argparse
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px


def compute_cdf(values: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return np.array([]), np.array([])
    arr = np.sort(arr)
    y = np.arange(1, arr.size + 1) / arr.size
    return arr, y


def load_parquet_df(parquet_file_path: str) -> pd.DataFrame:
    table = pq.read_pandas(parquet_file_path)
    df = table.to_pandas()
    # Flatten any nested structs
    df = pd.json_normalize(df.to_dict(orient="records"))

    # Drop non-struct object columns (metadata) to keep a clean numeric table
    for key in list(df.columns.values):
        if df[key].dtype == object and "." not in key:
            df.drop(key, axis="columns", inplace=True)

    # Remove odd lines at beginning of recording with old timestamps
    one_year_ago = (pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1))
    df = df[df["Timestamp"] >= one_year_ago]

    # Drop rows at the beginning with 0 packets sent/received
    if "OutboundRTP.PacketsSent" in df.columns:
        df = df.loc[df["OutboundRTP.PacketsSent"].ne(0).cummax()]
    if "InboundRTP.PacketsReceived" in df.columns:
        df = df.loc[df["InboundRTP.PacketsReceived"].ne(0).cummax()]

    # Remove duplicate stat rows with same timestamp
    df.drop_duplicates(subset=["Timestamp"], keep="first", inplace=True)
    df.set_index("Timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df


def load_iperf_bitrate_and_jitter(iperf_receiver_json: str) -> Tuple[List[float], List[float]]:
    with open(iperf_receiver_json, "r") as f:
        data = json.load(f)
    bitrate_mbps: List[float] = []
    jitter_ms: List[float] = []

    intervals = data.get("intervals", [])
    for it in intervals:
        sm = it.get("sum") or {}
        bps = sm.get("bits_per_second")
        jit = sm.get("jitter_ms")
        if isinstance(bps, (int, float)):
            bitrate_mbps.append(bps / 1e6)
        if isinstance(jit, (int, float)):
            jitter_ms.append(float(jit))
    return bitrate_mbps, jitter_ms


def load_irtt_rtts(irtt_sender_json: str) -> List[float]:
    with open(irtt_sender_json, "r") as f:
        data = json.load(f)
    rtts_ms: List[float] = []
    rts = data.get("round_trips", [])
    for rt in rts:
        lost = rt.get("lost")
        if isinstance(lost, str) and lost.lower() == "true":
            continue
        delay = rt.get("delay") or {}
        rtt_ns = delay.get("rtt")
        if isinstance(rtt_ns, (int, float)):
            rtts_ms.append(float(rtt_ns) / 1e6)
    return rtts_ms


# ----------------------
# Helpers
# ----------------------

def analyze_folder(folder: str, resample_ms: int) -> Tuple[str, dict]:
    if not os.path.isdir(folder):
        raise ValueError(f"Given path is not a folder: {folder}")

    # Detect available sources
    iperf_receiver_path = os.path.join(folder, "iperf-receiver.json")
    iperf_sender_path = os.path.join(folder, "iperf-sender.json")
    irtt_sender_path = os.path.join(folder, "irtt-sender.json")

    sender_parquet_path = os.path.join(folder, "sender.parquet")
    receiver_parquet_path = os.path.join(folder, "receiver.parquet")

    has_iperf = os.path.exists(iperf_receiver_path) or os.path.exists(iperf_sender_path)
    has_parquet = os.path.exists(sender_parquet_path) and os.path.exists(receiver_parquet_path)

    bitrate_values_mbps: List[float] = []
    rtt_values_ms: List[float] = []
    jitter_values_ms: List[float] = []

    source_used: Optional[str] = None

    if has_iperf:
        # Prefer receiver iperf for actual received bitrate and jitter
        if os.path.exists(iperf_receiver_path):
            br, jit = load_iperf_bitrate_and_jitter(iperf_receiver_path)
            bitrate_values_mbps.extend(br)
            jitter_values_ms.extend(jit)
            source_used = "iperf (receiver)"
        elif os.path.exists(iperf_sender_path):
            # Fallback to sender iperf bitrate; no jitter available at sender
            with open(iperf_sender_path, "r") as f:
                data = json.load(f)
            for it in data.get("intervals", []):
                sm = it.get("sum") or {}
                bps = sm.get("bits_per_second")
                if isinstance(bps, (int, float)):
                    bitrate_values_mbps.append(bps / 1e6)
            source_used = "iperf (sender)"
        # RTT from IRTT if present
        if os.path.exists(irtt_sender_path):
            rtt_values_ms.extend(load_irtt_rtts(irtt_sender_path))
        else:
            pass

    if not has_iperf and has_parquet:
        # Use parquet stats
        sender_df = load_parquet_df(sender_parquet_path)
        receiver_df = load_parquet_df(receiver_parquet_path)

        # Bitrate from receiver bytes received, resampled
        if "InboundRTP.BytesReceived" in receiver_df.columns:
            delta_bytes = (
                receiver_df["InboundRTP.BytesReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
            )
            bitrate_values_mbps = (delta_bytes * 8.0 / (resample_ms / 1000.0) / 1e6).to_numpy().tolist()
        # RTT from sender stats (seconds -> ms)
        if "OutboundRTP.RoundTripTime" in sender_df.columns:
            rtt_values_ms = (sender_df["OutboundRTP.RoundTripTime"] * 1000.0).dropna().to_numpy().tolist()
        # Jitter from receiver stats (seconds -> ms)
        if "InboundRTP.Jitter" in receiver_df.columns:
            jitter_values_ms = (receiver_df["InboundRTP.Jitter"] * 1000.0).dropna().to_numpy().tolist()
        source_used = "parquet"

    if not has_iperf and not has_parquet:
        raise ValueError("No iperf or parquet data found in the provided folder.")

    # Build a compact label based on folder path
    base = os.path.basename(os.path.normpath(folder))
    parent = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    name = f"{parent}/{base}" if parent else base

    return name, {
        "folder": folder,
        "bitrate": [v for v in bitrate_values_mbps if np.isfinite(v) and v >= 0],
        "rtt": [v for v in rtt_values_ms if np.isfinite(v) and v >= 0],
        "jitter": [v for v in jitter_values_ms if np.isfinite(v) and v >= 0],
        "source": source_used or "unknown",
    }


# ----------------------
# Main logic
# ----------------------

def main():
    parser = argparse.ArgumentParser(description="Plot CDFs for Bitrate, RTT, and Jitter from one or more measurement folders (iperf or parquet).")
    parser.add_argument("paths", nargs="+", help="One or more paths to measurement folders to analyze")
    parser.add_argument("--resample-ms", type=int, default=100, help="Resample interval for rate calculations in ms (default: 100)")
    args = parser.parse_args()

    folders: List[str] = args.paths
    resample_ms: int = args.resample_ms

    if len(folders) == 1 and os.path.isdir(folders[0]):
        root = folders[0]

        try:
            children = [os.path.join(root, name) for name in os.listdir(root)]
            child_files = [p for p in children if os.path.isfile(p)]
            child_dirs = sorted([p for p in children if os.path.isdir(p)])
            if len(child_files) == 0 and len(child_dirs) > 0:
                folders = child_dirs
        except Exception:
            pass

    datasets = []
    for folder in folders:
        try:
            name, data = analyze_folder(folder, resample_ms)
            data["name"] = name
            datasets.append(data)
        except ValueError as e:
            print(f"Warning: {e}")
            continue

    if not datasets:
        raise SystemExit("No valid folders to analyze.")

    # Determine which plots have any data
    any_bit = any(len(d["bitrate"]) > 0 for d in datasets)
    any_rtt = any(len(d["rtt"]) > 0 for d in datasets)
    any_jit = any(len(d["jitter"]) > 0 for d in datasets)

    # Derive a type from the folder basename (e.g., video-LibWebRTC-GCC-improved-123 -> LibWebRTC-GCC-improved)
    def extract_type(folder_path: str) -> str:
        base = os.path.basename(os.path.normpath(folder_path))
        if base.startswith("video-"):
            base = base[len("video-"):]
        parts = base.split("-")
        if parts and parts[-1].isdigit():
            parts = parts[:-1]
        t = "-".join(parts).strip()
        return t or base

    for d in datasets:
        d["type"] = extract_type(d["folder"])  # add type for coloring/grouping

    # Build Plotly figure with three rows
    rows = 3
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.06,
        subplot_titles=(
            "Bitrate CDF (Mbps)" if any_bit else "Bitrate CDF (no data)",
            "RTT CDF (ms)" if any_rtt else "RTT CDF (no data)",
            "Jitter CDF (ms)" if any_jit else "Jitter CDF (no data)",
        ),
    )

    # Color mapping per type for consistent colors across datasets and subplots
    palette = px.colors.qualitative.Plotly
    types_in_order = []
    for d in datasets:
        if d["type"] not in types_in_order:
            types_in_order.append(d["type"])
    type_to_color = {t: palette[i % len(palette)] for i, t in enumerate(types_in_order)}

    # Plot individual dataset lines colored by type
    for idx, d in enumerate(datasets):
        color = type_to_color[d["type"]]
        name = d["name"]
        legendgroup = name
        legend_shown = False

        bit_x, bit_y = compute_cdf(d["bitrate"]) if any_bit else (np.array([]), np.array([]))
        rtt_x, rtt_y = compute_cdf(d["rtt"]) if any_rtt else (np.array([]), np.array([]))
        jit_x, jit_y = compute_cdf(d["jitter"]) if any_jit else (np.array([]), np.array([]))

        if bit_x.size:
            fig.add_trace(
                go.Scatter(
                    x=bit_x,
                    y=bit_y,
                    mode="lines",
                    name=name,
                    legendgroup=legendgroup,
                    line=dict(color=color),
                    showlegend=not legend_shown,
                ),
                row=1,
                col=1,
            )
            legend_shown = True
        if rtt_x.size:
            fig.add_trace(
                go.Scatter(
                    x=rtt_x,
                    y=rtt_y,
                    mode="lines",
                    name=name,
                    legendgroup=legendgroup,
                    line=dict(color=color),
                    showlegend=not legend_shown,
                ),
                row=2,
                col=1,
            )
            legend_shown = True
        if jit_x.size:
            fig.add_trace(
                go.Scatter(
                    x=jit_x,
                    y=jit_y,
                    mode="lines",
                    name=name,
                    legendgroup=legendgroup,
                    line=dict(color=color),
                    showlegend=not legend_shown,
                ),
                row=3,
                col=1,
            )
            legend_shown = True

    # Aggregated lines per type (if multiple datasets share the same type)
    from collections import defaultdict

    type_groups = defaultdict(list)
    for d in datasets:
        type_groups[d["type"]].append(d)

    shown_agg_in_legend = set()

    for t, items in type_groups.items():
        if len(items) < 2:
            continue
        color = type_to_color[t]
        agg_name = f"{t} (all)"
        # Concatenate values across datasets for each metric
        bit_all = [v for it in items for v in it["bitrate"]]
        rtt_all = [v for it in items for v in it["rtt"]]
        jit_all = [v for it in items for v in it["jitter"]]

        if any_bit:
            x, y = compute_cdf(bit_all)
            if x.size:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        mode="lines",
                        name=agg_name,
                        legendgroup=f"agg-{t}",
                        line=dict(color=color, dash="dot", width=3),
                        showlegend=(t not in shown_agg_in_legend),
                    ),
                    row=1,
                    col=1,
                )
                shown_agg_in_legend.add(t)
        if any_rtt:
            x, y = compute_cdf(rtt_all)
            if x.size:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        mode="lines",
                        name=agg_name,
                        legendgroup=f"agg-{t}",
                        line=dict(color=color, dash="dot", width=3),
                        showlegend=False,
                    ),
                    row=2,
                    col=1,
                )
        if any_jit:
            x, y = compute_cdf(jit_all)
            if x.size:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        mode="lines",
                        name=agg_name,
                        legendgroup=f"agg-{t}",
                        line=dict(color=color, dash="dot", width=3),
                        showlegend=False,
                    ),
                    row=3,
                    col=1,
                )

    # Axes
    fig.update_xaxes(title_text="Mbps", row=1, col=1)
    fig.update_yaxes(title_text="Probability", row=1, col=1, range=[0, 1])

    fig.update_xaxes(title_text="ms", row=2, col=1)
    fig.update_yaxes(title_text="Probability", row=2, col=1, range=[0, 1])

    fig.update_xaxes(title_text="ms", row=3, col=1)
    fig.update_yaxes(title_text="Probability", row=3, col=1, range=[0, 1])

    # Title
    names_for_title = ", ".join(d["name"] for d in datasets)
    fig.update_layout(
        title_text=f"CDFs for Bitrate, RTT, Jitter | Folders: {names_for_title}",
        height=900,
        showlegend=True,
    )

    fig.show()


if __name__ == "__main__":
    main()
