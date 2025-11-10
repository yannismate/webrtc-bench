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
    freeze_durations = {}  # Track freeze durations per advanced_name
    weather_by_hour = {}   # Track weather per hour
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

                # Collect freeze duration data
                freeze_duration = ms.get_total_freeze_duration()
                if freeze_duration is not None:
                    if advanced_name not in freeze_durations:
                        freeze_durations[advanced_name] = []
                    freeze_durations[advanced_name].append(freeze_duration)

                # Record weather data (one snapshot per hour). Prefer first encountered.
                if ts_key not in weather_by_hour and ms.weather_data is not None:
                    weather_by_hour[ts_key] = ms.weather_data
            except Exception as e:
                print(f"Error loading {subfolder}: {e}")
    return result_by_hour, freeze_durations, weather_by_hour


def main():
    parser = argparse.ArgumentParser(description="Analyze and graph 24hr stats from a results folder.")
    parser.add_argument("path", help="Path to the results")
    parser.add_argument("--resample-ms", type=int, default=200, help="Interval for resampling rate graphs in ms")
    parser.add_argument("--show-freezes", action="store_true", help="Show freeze duration distribution graph")
    parser.add_argument("--show-weather", action="store_true", help="Show current weather metrics graph")
    args = parser.parse_args()

    data, freeze_durations, weather_by_hour = load_results_grouped_by_hour(args.path, args.resample_ms)

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

    # Create second figure for freeze duration distribution (before showing)
    if args.show_freezes and freeze_durations:
        fig2, ax2 = plt.subplots(figsize=(max(10, int(len(ordered_advanced_names) * 1.5)), 6))

        # Prepare data for boxplot
        freeze_data = []
        freeze_labels = []
        for name in ordered_advanced_names:
            if name in freeze_durations and freeze_durations[name]:
                freeze_data.append(freeze_durations[name])
                freeze_labels.append(name)

        if freeze_data:
            # Create boxplot
            bp = ax2.boxplot(freeze_data, tick_labels=freeze_labels, patch_artist=True)

            # Customize boxplot appearance
            for patch in bp['boxes']:
                patch.set_facecolor('lightblue')

            ax2.set_xlabel("Advanced Name", fontsize=12)
            ax2.set_ylabel("Total Freeze Duration (seconds)", fontsize=12)
            ax2.set_title("Distribution of Total Freeze Duration by Advanced Name", fontsize=14)
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(axis='y', alpha=0.3)

            plt.tight_layout()
            plt.savefig(os.path.join(args.path, "freeze_duration_graph.png"), bbox_inches='tight')
            print(f"Freeze duration analysis saved to {os.path.join(args.path, 'freeze_duration_graph.png')}")
        else:
            print("No freeze duration data available to plot.")

    # Weather metrics figure (third window) if requested
    if args.show_weather and weather_by_hour:
        # Sort timestamps
        w_ts = sorted(weather_by_hour.keys())
        w_dt_labels = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') for ts in w_ts]

        # Prepare data lists (skip None values)
        global_vals = [(weather_by_hour[ts].global_solar_radiation_w_m2, ts) for ts in w_ts]
        atmos_vals = [(weather_by_hour[ts].atmospheric_counter_radiation_w_m2, ts) for ts in w_ts]
        longwave_vals = [(weather_by_hour[ts].longwave_outgoing_radiation_w_m2, ts) for ts in w_ts]
        humidity_vals = [(weather_by_hour[ts].average_relative_humidity_percent, ts) for ts in w_ts]
        precip_vals = [(weather_by_hour[ts].current_precip_mm_per_min, ts) for ts in w_ts]

        metric_specs = [
            ("Global Solar Rad (W/m^2)", global_vals),
            ("Atmospheric Counter Rad (W/m^2)", atmos_vals),
            ("Longwave Outgoing Rad (W/m^2)", longwave_vals),
            ("Avg Relative Humidity (%)", humidity_vals),
            ("Current Precip (mm/min)", precip_vals),
        ]

        fig3, axes3 = plt.subplots(len(metric_specs), 1, figsize=(12, 3 * len(metric_specs)), sharex=True)
        if len(metric_specs) == 1:
            axes3 = [axes3]

        for ax, (title, values) in zip(axes3, metric_specs):
            filtered = [(val, ts) for val, ts in values if val is not None]
            if not filtered:
                ax.set_title(f"{title} (no data)")
                ax.set_visible(True)
                continue
            y = [v for v, _ in filtered]
            ts_list = [datetime.fromtimestamp(t) for _, t in filtered]
            ax.plot(ts_list, y, marker='o')
            ax.set_ylabel(title)
            ax.grid(alpha=0.3)
        axes3[-1].set_xlabel("Time (Hour)")
        fig3.autofmt_xdate(rotation=45)
        fig3.suptitle("Weather Metrics Over Time", y=0.98)

    # Show all figures at once
    plt.show()

if __name__ == "__main__":
    main()
