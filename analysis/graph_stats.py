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
        "OutboundRTP.BytesSent",
        "OutboundRTP.HeaderBytesSent",
    ],
)

df = table.to_pandas().rename(
    columns={
        "InboundRTP.BytesReceived": "BytesReceived",
        "InboundRTP.HeaderBytesReceived": "HeaderBytesReceived",
        "OutboundRTP.BytesSent": "BytesSent",
        "OutboundRTP.HeaderBytesSent": "HeaderBytesSent",
    }
)

print(df)

df.set_index("Timestamp", inplace=True)
period = f"{int(window_sec * 1000)}ms"
binned = df.resample(period).last()

binned["GoodBytesReceived"] = binned["BytesReceived"] - binned["HeaderBytesReceived"]
binned["GoodBytesSent"] = binned["BytesSent"] - binned["HeaderBytesSent"]

binned["Recv_Bps"] = binned["BytesReceived"].diff() / window_sec
binned["Sent_Bps"] = binned["BytesSent"].diff() / window_sec
binned["Recv_Good_Bps"] = binned["GoodBytesReceived"].diff() / window_sec
binned["Sent_Good_Bps"] = binned["GoodBytesSent"].diff() / window_sec
binned = binned.iloc[1:]

plt.figure(figsize=(10, 5))
plt.plot(binned.index, binned["Sent_Bps"] * 8 / 1000, label="Throughput Sent", color="orange", linestyle=":")
plt.plot(binned.index, binned["Recv_Bps"] * 8 / 1000, label="Throughput Received", color="green", linestyle=":")
plt.plot(binned.index, binned["Sent_Good_Bps"] * 8 / 1000, label="Goodput Sent", color="orange", linestyle="-")
plt.plot(binned.index, binned["Recv_Good_Bps"] * 8 / 1000, label="Goodput Received", color="green", linestyle="-")
plt.xlabel(f"Time (aggregated every {window_sec}s)")
plt.ylabel("Kbit/s")
plt.legend()
plt.tight_layout()
plt.show()
