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

def compute_bitrate(df):
    # Ensure InboundRTP.BytesReceived exists
    if "InboundRTP.BytesReceived" not in df.columns:
        return None
    # Resample to 1s windows, taking the last value in each window
    bytes_received = df["InboundRTP.BytesReceived"].resample("1s").last()
    # Drop NaNs that may appear due to empty windows
    bytes_received = bytes_received.dropna()
    delta_bytes = bytes_received.diff()
    delta_time = bytes_received.index.to_series().diff().dt.total_seconds()
    # Calculate bitrate (bits per second) for each 1s window
    bitrate = (delta_bytes * 8) / delta_time
    bitrate = bitrate.replace([float('inf'), -float('inf')], pd.NA).dropna()
    return bitrate

def find_receiver_parquets(root_path):
    parquet_files = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        for filename in filenames:
            if filename == "receiver.parquet":
                parquet_files.append(os.path.join(dirpath, filename))
    return parquet_files

def extract_test_type_and_instance(parquet_path, base_path):
    rel_path = os.path.relpath(parquet_path, base_path)
    parts = rel_path.split(os.sep)
    if len(parts) >= 2:
        test_type = parts[0].removeprefix("10k_")
        test_type = " ".join(test_type.split('-'))
        test_instance = parts[1]
        test_instance = " ".join(test_instance.split('-')[1:3])
        return test_type, test_instance
    return "unknown", "unknown"

base_path = results_folder_path
parquet_files = find_receiver_parquets(base_path)
results = []

for parquet_path in parquet_files:
    test_type, test_instance = extract_test_type_and_instance(parquet_path, base_path)
    df = load_parquet(parquet_path)
    bitrate = compute_bitrate(df)
    if bitrate is not None and not bitrate.empty:
        mean_rate = bitrate.mean()
        std_rate = bitrate.std()
        results.append({
            "Test Type": test_type,
            "Test Instance": test_instance,
            "Avg (kbps)": round(mean_rate / 1000, 2),
            "StdDev (kbps)": round(std_rate / 1000, 2)
        })
results_df = pd.DataFrame(results)

# Sort for nicer display
results_df.sort_values(by=["Test Type", "Test Instance"], inplace=True)

# Pivot the table: rows = Test Instance, columns = Test Type, values = "Avg<br>StdDev"
results_df["Avg/StdDev (kbps)"] = results_df.apply(
    lambda row: f"{row['Avg (kbps)']}<br>{row['StdDev (kbps)']}", axis=1
)
pivot_df = results_df.pivot(index="Test Instance", columns="Test Type", values="Avg/StdDev (kbps)")
pivot_df = pivot_df.fillna("")

# For coloring: create a matrix of avg values (same shape as pivot_df)
avg_matrix = results_df.pivot(index="Test Instance", columns="Test Type", values="Avg (kbps)").reindex(index=pivot_df.index, columns=pivot_df.columns)
# Flatten all avg values, ignoring NaN/empty
all_avg_values = avg_matrix.values.flatten()
all_avg_values = [v for v in all_avg_values if pd.notnull(v)]
if all_avg_values:
    min_avg = min(all_avg_values)
    max_avg = max(all_avg_values)
else:
    min_avg = max_avg = 0

def color_for_value(val):
    if pd.isnull(val):
        return "lavender"
    # Normalize between 0 and 1
    if max_avg == min_avg:
        norm = 0.5
    else:
        norm = (val - min_avg) / (max_avg - min_avg)
    # Interpolate from red (low) to green (high)
    r = int(255 * (1 - norm))
    g = int(180 * norm + 50 * (1 - norm))  # more green, less black
    b = int(80 * (1 - norm))
    return f"rgb({r},{g},{b})"

# Prepare cell colors: first column paleturquoise, others colored by avg bitrate
n_rows = len(pivot_df)
n_cols = len(pivot_df.columns) + 1  # +1 for the index column
cell_colors = []
# First column: paleturquoise
cell_colors.append(['paleturquoise'] * n_rows)
# Data columns: color by avg bitrate
for col in pivot_df.columns:
    col_colors = []
    for idx in range(n_rows):
        avg_val = avg_matrix.iloc[idx][col]
        col_colors.append(color_for_value(avg_val))
    cell_colors.append(col_colors)

# Display as Plotly table with test type on x-axis and test instance on y-axis
fig = go.Figure(data=[go.Table(
    header=dict(
        values=[""] + list(pivot_df.columns),
        fill_color='paleturquoise',
        align='left'
    ),
    cells=dict(
        values=[pivot_df.index] + [pivot_df[col] for col in pivot_df.columns],
        fill_color=cell_colors,
        align='left',
        format=[None] + [None]*len(pivot_df.columns),
        height=30
    )
)])

fig.update_layout(title="Bitrate Statistics (Avg / StdDev in kbps) per Test Instance and Type")
fig.show()