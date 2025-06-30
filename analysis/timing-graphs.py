import argparse
import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

parser = argparse.ArgumentParser(description="Load timing CSVs into pandas DataFrames.")
parser.add_argument("directory", help="Directory containing the CSV files")
args = parser.parse_args()

def find_csv_by_prefix(directory, prefix):
    for fname in os.listdir(directory):
        if fname.startswith(prefix) and fname.endswith('.csv'):
            return os.path.join(directory, fname)
    raise FileNotFoundError(f"No CSV file starting with '{prefix}' found in {directory}")

in_csv = find_csv_by_prefix(args.directory, "timing-in")
out_csv = find_csv_by_prefix(args.directory, "timing-out")

df_in = pd.read_csv(in_csv)
df_out = pd.read_csv(out_csv)

# Find the earliest timestamp across both DataFrames
min_ts = min(df_in['Timestamp'].min(), df_out['Timestamp'].min())

# Convert all timestamps to microseconds since test start
df_in['Timestamp'] = df_in['Timestamp'] - min_ts
df_out['Timestamp'] = df_out['Timestamp'] - min_ts

def compute_packetnr(seq, wrap=2**16):
    pkt = [0]
    for prev, curr in zip(seq[:-1], seq[1:]):
        if curr > prev:
            diff = curr - prev
        else:
            diff = curr + wrap - prev
        pkt.append(pkt[-1] + diff)
    return pkt

# compute PacketNr for out-going stream
df_out['PacketNr'] = compute_packetnr(df_out['SeqNum'].tolist())

df_in = df_in.merge(
    df_out[['SeqNum', 'PacketNr']],
    on='SeqNum',
    how='left'
)

df_out.set_index('PacketNr', inplace=True)
df_in.set_index('PacketNr', inplace=True)

# align send/recv on the new PacketNr index
merged = pd.merge(
    df_out[['Timestamp']],
    df_in[['Timestamp']],
    left_index=True,
    right_index=True,
    how='left',
    suffixes=('_out', '_in')
).reset_index().rename(columns={'index': 'PacketNr'})

merged['delay_us'] = merged['Timestamp_in']- merged['Timestamp_out']

# Identify lost packets (those with NaN in Timestamp_in)
received_mask = merged['Timestamp_in'].notna()
lost_mask = ~received_mask

# Print number of lost packets and their sequence numbers
lost_packets = merged.loc[lost_mask, 'PacketNr']
# PacketNr is the index of df_out, so select by index labels
lost_seqnums = df_out.loc[lost_packets, 'SeqNum']

# Filter out big outliers
if received_mask.any():
    filtered_received_mask = received_mask & (merged['delay_us'] >= -200000) & (merged['delay_us'] <= 1000000)
else:
    filtered_received_mask = received_mask

trace_received = go.Scatter(
    x=merged.loc[filtered_received_mask, 'Timestamp_out'] / 1000.0,
    y=merged.loc[filtered_received_mask, 'delay_us'],
    mode='lines+markers',
    name='Received',
    line=dict(color='blue'),
    marker=dict(color='blue')
)

# Prepare scatter markers for lost packets
lost_x = merged.loc[lost_mask, 'Timestamp_out'] / 1000.0

trace_lost_scatter = go.Scatter(
    x=lost_x,
    y=[1] * lost_x.shape[0],
    mode='markers',
    marker=dict(color='red', size=8, symbol='x'),
    name='Lost Packets',
    showlegend=False,
    hovertext=[f"Lost at {x:.3f} ms" for x in lost_x]
)

fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.7, 0.3],
    vertical_spacing=0.08,
    subplot_titles=['Packet Delay (us) by Out Timestamp', 'Lost Packets Timeline']
)

fig.add_trace(trace_received, row=1, col=1)
fig.add_trace(trace_lost_scatter, row=2, col=1)

fig.update_yaxes(title_text='Delay (us)', row=1, col=1)
fig.update_yaxes(title_text='Lost Packet', showticklabels=False, row=2, col=1, range=[0.5, 1.5])
fig.update_xaxes(title_text='Out Timestamp (ms since test start)', row=2, col=1)

fig.update_layout(
    height=600,
    legend=dict(x=0.01, y=0.99)
)

fig.show()
