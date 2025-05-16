import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib.pyplot as plt

parquet_file_path = sys.argv[1]
window_sec = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

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

df.set_index("Timestamp", inplace=True)
period = f"{int(window_sec * 1000)}ms"
binned = df.resample(period).last()

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

fig, ax1 = plt.subplots()
ax2 = ax1.twinx()

ax1.plot(binned.index, binned["Sent_Bps"] * 8 / 1000, label="Throughput Sent", color="orange", linestyle=":")
ax1.plot(binned.index, binned["Recv_Bps"] * 8 / 1000, label="Throughput Received", color="green", linestyle=":")
ax1.plot(binned.index, binned["Sent_Good_Bps"] * 8 / 1000, label="Goodput Sent", color="orange", linestyle="-")
ax1.plot(binned.index, binned["Recv_Good_Bps"] * 8 / 1000, label="Goodput Received", color="green", linestyle="-")
ax1.set_xlabel(f"Time (aggregated every {window_sec}s)")
ax1.set_ylabel("Kbit/s")

ax2.plot(binned.index, binned["PacketLossRate"] * 100, label="Packet Loss", color="red", linestyle="-")
ax2.set_ylabel("%")

plt.legend()
plt.tight_layout()
plt.show()
