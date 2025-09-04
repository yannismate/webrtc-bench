import os
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from loaders.measurement import Measurement

# Quantile parts for boxplot statistics
QUANTILE_PARTS = [0.01, 0.25, 0.5, 0.75, 0.99]
METRICS = ['throughput', 'loss', 'jitter']
DESIRED_ORDER = ['iperf1', 'LibWebRTC-GCC', 'iperf2', 'LibWebRTC-GCC-improved', 'iperf3', 'Pion-NoCC', 'iperf4']


def extract_quantiles(measurement: Measurement, resample_ms: int) -> dict:
    quantiles = {}
    # Throughput (kbps)
    recv_br = measurement.get_recv_bitrate_kbps(resample_ms)
    if recv_br is not None and not recv_br.empty:
        q = recv_br.quantile(QUANTILE_PARTS)
        quantiles['throughput'] = {
            'min': q[0.01], 'q1': q[0.25], 'median': q[0.5], 'q3': q[0.75], 'max': q[0.99]
        }
    # Jitter (ms)
    jitter = measurement.get_jitter_ms()
    if jitter is not None and not jitter.empty:
        q = jitter.quantile(QUANTILE_PARTS)
        quantiles['jitter'] = {
            'min': q[0.01], 'q1': q[0.25], 'median': q[0.5], 'q3': q[0.75], 'max': q[0.99]
        }
    # Loss (fraction)
    loss = measurement.get_loss_rate()
    if loss is not None and not loss.empty:
        q = loss.quantile(QUANTILE_PARTS)
        quantiles['loss'] = {
            'min': q[0.01], 'q1': q[0.25], 'median': q[0.5], 'q3': q[0.75], 'max': q[0.99]
        }
    return quantiles


def load_results_grouped_by_hour(folder_path: str, resample_ms: int):
    result_by_hour = {}
    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split('-')
            if len(parts) < 2:
                continue
            measurement_type = parts[0]
            measurement_timestamp = parts[-1]
            advanced_name = '-'.join(parts[1:-1])
            try:
                parsed_ts = datetime.fromtimestamp(int(measurement_timestamp))
            except Exception:
                continue
            parsed_ts = parsed_ts.replace(second=0, microsecond=0, minute=0, hour=parsed_ts.hour)
            ts_key = parsed_ts.timestamp()
            if ts_key not in result_by_hour:
                result_by_hour[ts_key] = {}
            subfolder = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(subfolder)
                ms.load_files()
                quantiles = extract_quantiles(ms, resample_ms)
                result_by_hour[ts_key][advanced_name] = quantiles
            except Exception as e:
                print(f"Error loading {subfolder}: {e}")
    return result_by_hour


def main():
    parser = argparse.ArgumentParser(description="Analyze and graph 24hr stats from a results folder.")
    parser.add_argument("path", help="Path to the results")
    parser.add_argument("--resample-ms", type=int, default=200, help="Interval for resampling rate graphs in ms")
    args = parser.parse_args()

    data = load_results_grouped_by_hour(args.path, args.resample_ms)

    # Collect all advanced names
    all_advanced_names = set()
    for timestamp_data in data.values():
        all_advanced_names.update(timestamp_data.keys())
    all_advanced_names = sorted(list(all_advanced_names))
    ordered_advanced_names = [name for name in DESIRED_ORDER if name in all_advanced_names]
    for name in all_advanced_names:
        if name not in ordered_advanced_names:
            ordered_advanced_names.append(name)

    timestamps = sorted(data.keys())
    datetime_labels = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') for ts in timestamps]

    # Prepare data for boxplots
    boxplot_data = {metric: {name: [] for name in ordered_advanced_names} for metric in METRICS}
    for ts in timestamps:
        for name in ordered_advanced_names:
            quantiles = data.get(ts, {}).get(name, {})
            for metric in METRICS:
                if metric in quantiles:
                    q = quantiles[metric]
                    # Synthetic boxplot data: min, q1, median, q3, max
                    boxplot_data[metric][name].append([
                        q['min'], q['q1'], q['median'], q['q3'], q['max']
                    ])

    # Plotting
    num_metrics = len(METRICS)
    num_advanced = len(ordered_advanced_names)
    fig, axes = plt.subplots(num_metrics, num_advanced, figsize=(4*num_advanced, 4*num_metrics), sharex=False)
    if num_metrics == 1 and num_advanced == 1:
        axes = np.array([[axes]])
    elif num_metrics == 1:
        axes = axes[np.newaxis, :]
    elif num_advanced == 1:
        axes = axes[:, np.newaxis]

    for i, metric in enumerate(METRICS):
        for j, name in enumerate(ordered_advanced_names):
            ax = axes[i, j]
            # Flatten synthetic boxplot data for seaborn
            values = boxplot_data[metric][name]
            if not values:
                ax.set_visible(False)
                continue
            # Each value is [min, q1, median, q3, max] for a timestamp
            # For seaborn boxplot, we need a list of all values
            # We'll plot as a boxplot per timestamp
            plot_vals = np.array(values)
            # Use median as the central value, but show spread
            # For each timestamp, create a boxplot
            # We'll plot as a boxplot with x = timestamp
            df = pd.DataFrame({
                'Time': [datetime_labels[k] for k in range(len(plot_vals)) for _ in range(5)],
                'Value': plot_vals.flatten(),
                'Quantile': ['min', 'q1', 'median', 'q3', 'max'] * len(plot_vals)
            })
            # Pivot so each timestamp is a box
            # Use seaborn boxplot with x=Time, y=Value
            sns.boxplot(x='Time', y='Value', data=df, ax=ax, showfliers=False)
            ax.set_title(f"{metric} - {name}")
            ax.set_xlabel("Time (Hour)")
            if metric == 'throughput':
                ax.set_ylabel("Throughput (kbps)")
            elif metric == 'loss':
                ax.set_ylabel("Loss Rate")
            else:
                ax.set_ylabel("Jitter (ms)")
            ax.tick_params(axis='x', rotation=45)
    plt.tight_layout()
    plt.suptitle(f"24-Hour Performance Analysis {args.path}", y=1.02)
    plt.subplots_adjust(top=0.90)
    plt.savefig(os.path.join(args.path, "graph.png"), bbox_inches='tight')
    print(f"Analysis saved to {os.path.join(args.path, 'graph.png')}")
    plt.show()

if __name__ == "__main__":
    main()
