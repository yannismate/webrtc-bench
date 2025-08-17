import os
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import plotly.figure_factory as ff
import argparse
import json
from datetime import datetime

parser = argparse.ArgumentParser(description="Analyze and graph 24hr stats from a results folder.")
parser.add_argument("path", help="Path to the results")
parser.add_argument("--resample-ms", type=int, default=200, help="Interval for resampling rate graphs in ms")
args = parser.parse_args()

quantile_parts = [0.01, 0.25, 0.5, 0.75, 0.99]

def load_parquet(parquet_file_path):
    print(f"Loading parquet {parquet_file_path}")
    table = pq.read_pandas(parquet_file_path)
    df = table.to_pandas()
    df = pd.json_normalize(df.to_dict(orient='records'))

    for key in df.columns.values:
        if df[key].dtype == object and not "." in key:
            df.drop(key, axis='columns', inplace=True)

    one_year_ago = (pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1))
    df = df[df["Timestamp"] >= one_year_ago]

    if "OutboundRTP.PacketsSent" in df.columns:
        df = df.loc[df["OutboundRTP.PacketsSent"].ne(0).cummax()]
    if "InboundRTP.PacketsReceived" in df.columns:
        df = df.loc[df["InboundRTP.PacketsReceived"].ne(0).cummax()]

    # Remove duplicate stat rows with same timestamp
    df.drop_duplicates(subset=['Timestamp'], keep='first', inplace=True)
    df.set_index("Timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df

def load_iperf_json(json_path):
    print(f"Loading JSON {json_path}")
    with open(json_path) as json_file:
        data = json.load(json_file)
        intervals = data.get('intervals', [])
        extracted_data = [
            {
                'bits_per_second': interval['sum']['bits_per_second'],
                'jitter_ms': interval['sum']['jitter_ms'],
                'lost_percent': interval['sum']['lost_percent']
            }
            for interval in intervals
        ]
        return pd.DataFrame(extracted_data)

def extract_iperf_quantiles(iperf_df):
    quantiles = {}

    q = iperf_df['bits_per_second'].quantile(quantile_parts)
    quantiles['throughput'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    q = iperf_df['jitter_ms'].quantile(quantile_parts)
    quantiles['jitter'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    loss_decimal = iperf_df['lost_percent'] / 100
    q = loss_decimal.quantile(quantile_parts)
    quantiles['loss'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    return quantiles

def extract_parquet_quantiles(receiver_df, resample_ms):
    quantiles = {}
    resampling_multiplier = 1000 / resample_ms

    receiver_rate = receiver_df["InboundRTP.BytesReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
    receiver_rate = (receiver_rate / 1000) * 8 * resampling_multiplier

    q = receiver_rate.quantile(quantile_parts)
    quantiles['throughput'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    jitter_ms = receiver_df['InboundRTP.Jitter'] * 1000
    q = jitter_ms.quantile(quantile_parts)
    quantiles['jitter'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    packets_receive_rate = receiver_df["InboundRTP.PacketsReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
    packets_lost_rate = receiver_df["InboundRTP.PacketsLost"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
    loss_rate = packets_lost_rate / (packets_receive_rate + packets_lost_rate)
    loss_rate = loss_rate.fillna(0)

    q = loss_rate.quantile(quantile_parts)
    quantiles['loss'] = {
        'min': q[0.01],
        'q1': q[0.25],
        'median': q[0.5],
        'q3': q[0.75],
        'max': q[0.99]
    }

    return quantiles


def load_results_grouped_by_hour(folder_path):
    result_by_hour = {}
    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split('-')
            measurement_type = parts[0]
            measurement_timestamp = parts[-1]
            advanced_name = '-'.join(parts[1:-1])
            #if int(measurement_timestamp) < 1753909140:
            #    print("DELETE", dir_name)
            parsed_ts = datetime.fromtimestamp(int(measurement_timestamp))
            parsed_ts = parsed_ts.replace(second=0, microsecond=0, minute=0, hour=parsed_ts.hour)
            if parsed_ts.timestamp() not in result_by_hour:
                result_by_hour[parsed_ts.timestamp()] = {}
            if measurement_type == "bandwidth_measurement":
                json_path = os.path.join(dir_path, dir_name, 'iperf-receiver.json')
                if os.path.exists(json_path):
                    try:
                        result_by_hour[parsed_ts.timestamp()][advanced_name] = extract_iperf_quantiles(load_iperf_json(json_path))
                    except Exception as e:
                        print("Error while loading data from iperf file", e)
            else:
                result_by_hour[parsed_ts.timestamp()][advanced_name] = {}
                receiver_path = os.path.join(dir_path, dir_name, 'receiver.parquet')
                if os.path.exists(receiver_path):
                    try:
                        result_by_hour[parsed_ts.timestamp()][advanced_name] = extract_parquet_quantiles(load_parquet(receiver_path), args.resample_ms)
                    except Exception as e:
                        print("Error while loading parquet data", e)
    return result_by_hour

data = load_results_grouped_by_hour(args.path)

desired_order = ['iperf1', 'LibWebRTC-GCC', 'iperf2', 'LibWebRTC-GCC-improved', 'iperf3', 'Pion-NoCC', 'iperf4']
all_advanced_names = set()
for timestamp_data in data.values():
    all_advanced_names.update(timestamp_data.keys())
all_advanced_names = sorted(list(all_advanced_names))

ordered_advanced_names = [name for name in desired_order if name in all_advanced_names]
for name in all_advanced_names:
    if name not in ordered_advanced_names:
        ordered_advanced_names.append(name)

metrics = ['throughput', 'loss', 'jitter']

# Build subplot titles in metric-major order
subplot_titles = []
for metric in metrics:
    for name in ordered_advanced_names:
        subplot_titles.append(f"{metric} - {name}")

# Dynamically compute rows based on the number of advanced names and metrics
num_advanced = len(ordered_advanced_names)
num_metrics = len(metrics)
num_rows = num_metrics * num_advanced if num_advanced > 0 else 0

fig = make_subplots(
    rows=num_rows, cols=1,
    vertical_spacing=0.5 * (1 / num_rows),
    subplot_titles=subplot_titles,
    shared_xaxes=False
)

timestamps = sorted(data.keys())
datetime_labels = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') for ts in timestamps]

advanced_name_num = 0
for advanced_name in ordered_advanced_names:
    metric_num = 0
    for metric in metrics:
        x_values = []
        y_values = []

        for timestamp in timestamps:
            if advanced_name in data[timestamp] and metric in data[timestamp][advanced_name]:
                quantile_data = data[timestamp][advanced_name][metric]

                x_label = datetime.fromtimestamp(timestamp).strftime('%H:%M')
                x_values.append(x_label)

                synthetic_data = [
                    quantile_data['min'],
                    quantile_data['q1'],
                    quantile_data['median'],
                    quantile_data['q3'],
                    quantile_data['max']
                ]
                y_values.extend(synthetic_data)
                x_values.extend([x_label] * (len(synthetic_data) - 1))

        if x_values and num_rows > 0:
            fig.add_trace(
                go.Box(
                    x=x_values,
                    y=y_values,
                    name=f"{advanced_name} - {metric}",
                    boxpoints=False,
                    showlegend=False,
                    pointpos=0
                ),
                row=1 + advanced_name_num + metric_num * num_advanced, col=1
            )
        metric_num += 1

    advanced_name_num += 1

# Scale figure height with the number of rows (fallback to a minimum height)
per_row_height = 220
fig.update_layout(
    height=max(400, per_row_height * max(1, num_rows)),
    title_text="24-Hour Performance Analysis " + args.path,
    showlegend=False
)

for row in range(1, num_rows + 1):
    row_advanced_name = ordered_advanced_names[(row - 1) % num_advanced] if num_advanced else ''
    row_metric = metrics[(row - 1) // num_advanced] if num_advanced else ''

    if row_metric == 'throughput':
        y_title = "Throughput (kbps)"
    elif row_metric == 'loss':
        y_title = "Loss Rate"
    else:
        y_title = "Jitter (ms)"

    fig.update_yaxes(title_text=y_title, row=row, col=1)
    fig.update_xaxes(title_text="Time (Hour)", row=row, col=1)

# fig.write_html(f"{args.path}_analysis.html")
# print(f"Analysis saved to {args.path}_analysis.html")

advanced_groups = {}
for name in ordered_advanced_names:
    group_key = "iperf" if name.startswith("iperf") else name
    if group_key not in advanced_groups:
        advanced_groups[group_key] = {"throughput": [], "loss": []}

    for value_arr in data.values():
        if name not in value_arr:
            continue
        for metric, values in value_arr[name].items():
            if metric == "throughput":
                advanced_groups[group_key]["throughput"].append(values["median"])
            elif metric == "loss":
                advanced_groups[group_key]["loss"].append(values["median"])

averages = {}
for group, dta in advanced_groups.items():
    avg_throughput = sum(dta["throughput"]) / len(dta["throughput"]) if dta["throughput"] else 0
    avg_loss = sum(dta["loss"]) / len(dta["loss"]) if dta["loss"] else 0
    averages[group] = {"throughput": avg_throughput, "loss": avg_loss}

for group, avg in averages.items():
    print(f"Group: {group}, Average Throughput: {avg['throughput']:.2f} kbps, Average Loss Rate: {avg['loss']:.2f}")

fig.show()

fig.write_html(os.path.join(args.path, "graph.html"))