import os
import json
import argparse
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
# Main logic
# ----------------------

def main():
    parser = argparse.ArgumentParser(description="Plot CDFs for Bitrate, RTT, and Jitter from a measurement folder (iperf or parquet).")
    parser.add_argument("path", help="Path to the measurement folder to analyze")
    parser.add_argument("--resample-ms", type=int, default=100, help="Resample interval for rate calculations in ms (default: 100)")
    args = parser.parse_args()

    folder = args.path
    resample_ms: int = args.resample_ms

    if not os.path.isdir(folder):
        raise SystemExit(f"Given path is not a folder: {folder}")

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

    source_used = None

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
            # No IRTT RTTs; leave RTT empty for iperf-only measurement
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
        raise SystemExit("No iperf or parquet data found in the provided folder.")

    # Compute CDFs
    bit_x, bit_y = compute_cdf([v for v in bitrate_values_mbps if np.isfinite(v) and v >= 0])
    rtt_x, rtt_y = compute_cdf([v for v in rtt_values_ms if np.isfinite(v) and v >= 0])
    jit_x, jit_y = compute_cdf([v for v in jitter_values_ms if np.isfinite(v) and v >= 0])

    # Build Plotly figure with three rows
    rows = 3
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=False, vertical_spacing=0.06,
                        subplot_titles=(
                            "Bitrate CDF (Mbps)" if bit_x.size else "Bitrate CDF (no data)",
                            "RTT CDF (ms)" if rtt_x.size else "RTT CDF (no data)",
                            "Jitter CDF (ms)" if jit_x.size else "Jitter CDF (no data)",
                        ))

    if bit_x.size:
        fig.add_trace(go.Scatter(x=bit_x, y=bit_y, mode="lines", name="Bitrate (Mbps)"), row=1, col=1)
        fig.update_xaxes(title_text="Mbps", row=1, col=1)
        fig.update_yaxes(title_text="Probability", row=1, col=1, range=[0, 1])

    if rtt_x.size:
        fig.add_trace(go.Scatter(x=rtt_x, y=rtt_y, mode="lines", name="RTT (ms)"), row=2, col=1)
        fig.update_xaxes(title_text="ms", row=2, col=1)
        fig.update_yaxes(title_text="Probability", row=2, col=1, range=[0, 1])

    if jit_x.size:
        fig.add_trace(go.Scatter(x=jit_x, y=jit_y, mode="lines", name="Jitter (ms)"), row=3, col=1)
        fig.update_xaxes(title_text="ms", row=3, col=1)
        fig.update_yaxes(title_text="Probability", row=3, col=1, range=[0, 1])

    title_src = f" | Source: {source_used}" if source_used else ""
    fig.update_layout(title_text=f"CDFs for Bitrate, RTT, Jitter{title_src}<br>{folder}", height=900, showlegend=False)

    fig.show()


if __name__ == "__main__":
    main()

