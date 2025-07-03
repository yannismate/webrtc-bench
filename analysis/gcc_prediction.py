import os
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import plotly.figure_factory as ff
import argparse
import numpy as np
from scipy.signal import find_peaks, peak_prominences

parser = argparse.ArgumentParser(description="Analyze and graph WebRTC stats from a results folder.")
parser.add_argument("path", help="Path to the results")
args = parser.parse_args()

results_folder_path = args.path

def load_parquet(parquet_file_path):
    table = pq.read_pandas(parquet_file_path)
    df = table.to_pandas()
    df = pd.json_normalize(df.to_dict(orient='records'))

    for key in df.columns.values:
        if df[key].dtype == object and not "." in key:
            df.drop(key, axis='columns', inplace=True)

    # Remove odd lines at beginning of recording with old timestamps
    one_year_ago = (pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1))
    df = df[df["Timestamp"] >= one_year_ago]

    # Drop rows at the beginning with 0 packets sent/received
    if "OutboundRTP.PacketsSent" in df.columns:
        df = df.loc[df["OutboundRTP.PacketsSent"].ne(0).cummax()]
    if "InboundRTP.PacketsReceived" in df.columns:
        df = df.loc[df["InboundRTP.PacketsReceived"].ne(0).cummax()]

    # Remove duplicate stat rows with same timestamp
    df.drop_duplicates(subset=['Timestamp'], keep='first', inplace=True)
    df.set_index("Timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df

sender_df = load_parquet(os.path.join(results_folder_path, "sender.parquet"))

if 'GCCStats.State' not in sender_df:
    print("Parquet file does not contain GCC stats")
    exit(0)

fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03)

fig.update_layout(title_text="WebRTC reconfiguration prediction " + results_folder_path)

fig.add_trace(
    go.Scatter(
        x=sender_df.index,
        y=sender_df["GCCStats.DelayEstimate"],
        mode="lines",
        name="GCC Delay Estimate ms",
        line=dict(color="black"),
    ),
    row=1,
    col=1,
)

def compute_intervals(peaks, time_array):
    if isinstance(time_array, pd.DatetimeIndex):
        times = time_array.astype(np.int64) / 1e9
    else:
        times = np.array(time_array)
    peak_times = times[peaks]
    intervals = np.diff(peak_times)
    print(intervals)
    if len(intervals) < 2:
        return None, 0  # Not enough data

    # Filter out intervals that are close to 2x the median interval (likely missed peaks)
    median = np.median(intervals)
    filtered_intervals = intervals[
        np.abs(intervals - median) < 0.5 * median
    ]
    if len(filtered_intervals) < 2:
        filtered_intervals = intervals

    mean_interval = np.mean(filtered_intervals)
    std_interval = np.std(filtered_intervals)

    confidence = max(0, 1 - (std_interval / mean_interval)) if mean_interval > 0 else 0
    return mean_interval, confidence

y = sender_df["GCCStats.DelayEstimate"].values
peaks, _ = find_peaks(y, prominence=0.04)

print(compute_intervals(peaks, sender_df.index))

fig.add_trace(
    go.Scatter(
        x=sender_df.index[peaks],
        y=y[peaks],
        mode="markers",
        name="DelayEstimate Peaks",
        marker=dict(color="red", size=6),
    ),
    row=1,
    col=1,
)

fig.show()