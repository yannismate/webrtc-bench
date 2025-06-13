import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib.pyplot as plt
import argparse

parser = argparse.ArgumentParser(description="Analyze and graph WebRTC stats from a Parquet file.")
parser.add_argument("file", help="Path to the input Parquet file")
parser.add_argument("--aggr-window", type=float, default=1.0, help="Aggregation window in seconds")
parser.add_argument("--save", action="store_true", help="Save the graph as a PNG file instead of displaying it")
args = parser.parse_args()

parquet_file_path = args.file
window_sec = args.aggr_window
save_graph = args.save

table = pq.read_pandas(
    parquet_file_path,
    columns=[
        "Timestamp",
        "InboundRTP.BytesReceived",
        "InboundRTP.HeaderBytesReceived",
        "InboundRTP.PacketsReceived",
        "InboundRTP.PacketsLost",
        "OutboundRTP.BytesSent",
        "OutboundRTP.HeaderBytesSent",
    ],
)

df = table.to_pandas().rename(
    columns={
        "InboundRTP.BytesReceived": "BytesReceived",
        "InboundRTP.HeaderBytesReceived": "HeaderBytesReceived",
        "InboundRTP.PacketsReceived": "PacketsReceived",
        "InboundRTP.PacketsLost": "PacketsLost",
        "OutboundRTP.BytesSent": "BytesSent",
        "OutboundRTP.HeaderBytesSent": "HeaderBytesSent",
    }
)

# Filter rows with timestamps older than one year
one_year_ago = (pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1))
df = df[df["Timestamp"] >= one_year_ago]

df = df.drop_duplicates(subset=['Timestamp'], keep='first')

if "PacketsReceived" not in df or df["PacketsReceived"].isna().all() or (df["PacketsReceived"] == 0).all():
    graph_packet_loss = False
else:
    graph_packet_loss = True

df.set_index("Timestamp", inplace=True)
period = f"{int(window_sec * 1000)}ms"

# Convert Timestamp to datetime if not already and ensure timezone-naive
df.index = pd.to_datetime(df.index).tz_localize(None)

# Calculate seconds from test start
start_time = df.index[0]
df["SecondsFromStart"] = (df.index - start_time).total_seconds()

# Create a new column for grouping based on the aggregation window
df["TimeGroup"] = (df["SecondsFromStart"] // window_sec).astype(int)

# Aggregate using groupby and last
binned = df.groupby("TimeGroup").agg({
    "BytesReceived": "last",
    "HeaderBytesReceived": "last",
    "PacketsReceived": "last",
    "PacketsLost": "last",
    "BytesSent": "last",
    "HeaderBytesSent": "last"
})

# Reset index and convert TimeGroup to seconds from start
binned.index = binned.index * window_sec

binned["GoodBytesReceived"] = binned["BytesReceived"] - binned["HeaderBytesReceived"]
binned["GoodBytesSent"] = binned["BytesSent"] - binned["HeaderBytesSent"]
binned["PacketsLostPs"] = binned["PacketsLost"].diff() / window_sec
binned["PacketsReceivedPs"] = binned["PacketsReceived"].diff() / window_sec
binned["PacketLossRate"] = binned["PacketsLostPs"] / (binned["PacketsReceivedPs"] + binned["PacketsLostPs"])

binned["Recv_Bps"] = binned["BytesReceived"].diff() / window_sec
binned["Sent_Bps"] = binned["BytesSent"].diff() / window_sec
binned["Recv_Good_Bps"] = binned["GoodBytesReceived"].diff() / window_sec
binned["Sent_Good_Bps"] = binned["GoodBytesSent"].diff() / window_sec
binned = binned.iloc[1:]

if (binned["Recv_Bps"] == 0).all():
    exclude_recv_bps = True
else:
    exclude_recv_bps = False

if (binned["Sent_Bps"] == 0).all():
    exclude_sent_bps = True
else:
    exclude_sent_bps = False

fig, ax1 = plt.subplots()

if not exclude_sent_bps:
    ax1.plot(binned.index, binned["Sent_Bps"] * 8 / 1000, label="Throughput Sent", color="orange", linestyle=":")
    ax1.plot(binned.index, binned["Sent_Good_Bps"] * 8 / 1000, label="Goodput Sent", color="orange", linestyle="-")

if not exclude_recv_bps:
    ax1.plot(binned.index, binned["Recv_Bps"] * 8 / 1000, label="Throughput Received", color="green", linestyle=":")
    ax1.plot(binned.index, binned["Recv_Good_Bps"] * 8 / 1000, label="Goodput Received", color="green", linestyle="-")

ax1.set_xlabel(f"Time")
ax1.set_ylabel("Kbit/s")

if graph_packet_loss:
    ax2 = ax1.twinx()
    ax2.plot(binned.index, binned["PacketLossRate"] * 100, label="Packet Loss", color="red", linestyle="-")
    ax2.set_ylabel("%")
    ax2.set_ylim(0, 100)  # Ensure loss axis scale is always 0-100%

plt.legend()
plt.tight_layout()

if save_graph:
    output_path = parquet_file_path.replace(".parquet", ".png")
    plt.savefig(output_path)
else:
    plt.show()