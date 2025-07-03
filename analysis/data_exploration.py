import os
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import plotly.figure_factory as ff
import argparse

parser = argparse.ArgumentParser(description="Analyze and graph WebRTC stats from a results folder.")
parser.add_argument("path", help="Path to the results")
parser.add_argument("--save", action="store_true", help="Save the graph as a PNG file instead of displaying it")
parser.add_argument("--resample-ms", type=int, default=1000, help="Interval for resampling rate graphs in ms")
args = parser.parse_args()

results_folder_path = args.path
save_graph = args.save
resample_ms = args.resample_ms
resampling_multiplier = 1000/resample_ms

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
receiver_df = load_parquet(os.path.join(results_folder_path, "receiver.parquet"))

has_gcc_stats = 'GCCStats.State' in sender_df
has_scream_stats = 'ScreamStats.TargetBitrate' in sender_df

num_rows = 3
if has_gcc_stats:
    num_rows = 6
if has_scream_stats:
    num_rows = 5

fig = make_subplots(rows=num_rows, cols=1, shared_xaxes=True, vertical_spacing=0.03)

fig.update_layout(title_text="WebRTC stats " + results_folder_path)

# Throughput (smoothed to seconds)
sender_rate = sender_df["OutboundRTP.BytesSent"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
sender_rate = (sender_rate / 1000)*8*resampling_multiplier

receiver_rate = receiver_df["InboundRTP.BytesReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
receiver_rate = (receiver_rate / 1000)*8*resampling_multiplier

packets_receive_rate = receiver_df["InboundRTP.PacketsReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
packets_receive_rate = packets_receive_rate

packets_lost_rate = receiver_df["InboundRTP.PacketsLost"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
packets_lost_rate = packets_lost_rate

loss_rate = packets_lost_rate / (packets_receive_rate + packets_lost_rate)

receiver_rate_rtx = receiver_df["InboundRTP.RetransmittedBytesReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
receiver_rate_rtx = (receiver_rate_rtx / 1000)*8*resampling_multiplier

fig.add_trace(
    go.Scatter(
        x=sender_rate.index,
        y=sender_rate,
        mode="lines",
        name="Outbound Kb/s",
        line=dict(color="blue"),
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=receiver_rate.index,
        y=receiver_rate,
        mode="lines",
        name="Inbound Kb/s",
        line=dict(color="green"),
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=receiver_rate_rtx.index,
        y=receiver_rate_rtx,
        mode="lines",
        name="Inbound RTX Kb/s",
        line=dict(color="yellow"),
    ),
    row=1,
    col=1,
)

# Loss
fig.add_trace(
    go.Scatter(
        x=loss_rate.index,
        y=loss_rate,
        mode="lines",
        name="Loss %",
        line=dict(color="red"),
    ),
    row=2,
    col=1,
)

# RTT/Jitter
fig.add_trace(
    go.Scatter(
        x=sender_df.index,
        y=sender_df["OutboundRTP.RoundTripTime"]*1000,
        mode="lines",
        name="RTT ms",
        line=dict(color="green"),
    ),
    row=3,
    col=1,
)

# GCC Stats
if 'GCCStats.State' in sender_df:
    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["GCCStats.LossTargetBitrate"]/1000,
            mode="lines",
            name="GCC Loss Target Bitrate KB/s",
            line=dict(color="orange"),
        ),
        row=4,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["GCCStats.DelayTargetBitrate"]/1000,
            mode="lines",
            name="GCC Delay Target Bitrate KB/s",
            line=dict(color="purple"),
        ),
        row=4,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["GCCStats.DelayEstimate"],
            mode="lines",
            name="GCC Delay Estimate ms",
            line=dict(color="black"),
        ),
        row=5,
        col=1,
    )

    # prepare color maps
    usage_states = sender_df["GCCStats.Usage"].dropna().unique()
    usage_colors = px.colors.qualitative.Plotly
    usage_color_map = {s: usage_colors[i % len(usage_colors)] for i, s in enumerate(usage_states)}
    state_states = sender_df["GCCStats.State"].dropna().unique()
    state_colors = px.colors.qualitative.Pastel
    state_color_map = {s: state_colors[i % len(state_colors)] for i, s in enumerate(state_states)}

    # build Gantt for GCCStats.Usage
    usage = sender_df["GCCStats.Usage"]
    df_usage_segments = []
    curr_state, curr_start = None, None
    for t, s in usage.items():
        if pd.isna(s): continue
        if s != curr_state:
            if curr_state is not None:
                df_usage_segments.append(dict(Task="Usage", Start=curr_start, Finish=t, Resource=curr_state))
            curr_state, curr_start = s, t
    if curr_state is not None:
        df_usage_segments.append(dict(Task="Usage", Start=curr_start, Finish=usage.index[-1], Resource=curr_state))

    # build Gantt for GCCStats.State
    state = sender_df["GCCStats.State"]
    df_state_segments = []
    curr_state, curr_start = None, None
    for t, s in state.items():
        if pd.isna(s): continue
        if s != curr_state:
            if curr_state is not None:
                df_state_segments.append(dict(Task="State", Start=curr_start, Finish=t, Resource=curr_state))
            curr_state, curr_start = s, t
    if curr_state is not None:
        df_state_segments.append(dict(Task="State", Start=curr_start, Finish=state.index[-1], Resource=curr_state))

    usage_gantt = ff.create_gantt(
        df_usage_segments + df_state_segments,
        group_tasks=True,
        colors=usage_color_map | state_color_map,
        index_col='Resource',
    )
    for trace in usage_gantt.data:
        fig.add_trace(trace, row=6, col=1)

# SCReAM Stats
if has_scream_stats:
    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["ScreamStats.CWND"],
            mode="lines",
            name="SCReAM CWND",
            line=dict(color="orange"),
        ),
        row=4,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["ScreamStats.BytesInFlightLog"],
            mode="lines",
            name="SCReAM Bytes in flight",
            line=dict(color="purple"),
        ),
        row=4,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=sender_df.index,
            y=sender_df["ScreamStats.QueueDelay"]*1000,
            mode="lines",
            name="SCReAM Queue Delay ms",
            line=dict(color="black"),
        ),
        row=5,
        col=1,
    )

fig.show()