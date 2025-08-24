import os
import pandas as pd
import pyarrow.parquet as pq
import argparse
import numpy as np
import plotly.graph_objects as go

parser = argparse.ArgumentParser(description="Export GCC Delay Estimate resampled to 40Hz.")
parser.add_argument("path", help="Path to the results")
parser.add_argument("--plot", action="store_true", help="Generate interactive plot using plotly")
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

if 'GCCStats.DelayEstimate' not in sender_df:
    print("Parquet file does not contain GCC stats")
    exit(0)

# Get the delay estimate series and drop NaN values
delay_series = sender_df["GCCStats.DelayEstimate"].dropna()

# Create a regular 40Hz time index from start to end
start_time = delay_series.index[0]
end_time = delay_series.index[-1]
duration = (end_time - start_time).total_seconds()
num_samples = int(duration * 40)  # 40Hz

# Create regular timestamp index
regular_index = pd.date_range(start=start_time, periods=num_samples, freq='25ms')

# Reindex the series to the regular grid and interpolate
resampled = delay_series.reindex(delay_series.index.union(regular_index)).sort_index()
resampled = resampled.interpolate(method='linear', limit_direction='both')
resampled = resampled.reindex(regular_index)

# Fill any remaining NaN values (shouldn't be any, but just in case)
resampled = resampled.ffill().bfill()

# Export to text file
output_path = os.path.join(results_folder_path, "gcc_delay_estimate_40hz.txt")
with open(output_path, 'w') as f:
    for value in resampled.values:
        f.write(f"{value}\n")

print(f"Exported {len(resampled)} samples to {output_path}")
print(f"Duration: {(resampled.index[-1] - resampled.index[0]).total_seconds():.2f} seconds")
print(f"Sample rate: 40 Hz")
print(f"Original samples: {len(delay_series)}")
print(f"Any NaN values: {resampled.isna().any()}")

# Generate plot if requested
if args.plot:
    print("\nGenerating plot...")

    # Create time axis (40Hz sampling rate = 25ms intervals)
    num_samples = len(resampled)
    duration_seconds = (resampled.index[-1] - resampled.index[0]).total_seconds()
    time_axis = np.linspace(0, duration_seconds, num_samples)
    delay_values = resampled.values

    # Create the plot
    fig = go.Figure()

    # Add the main trace
    fig.add_trace(go.Scatter(
        x=time_axis,
        y=delay_values,
        mode='lines',
        name='GCC Delay Estimate',
        line=dict(color='blue', width=1),
        hovertemplate='Time: %{x:.2f}s<br>Delay: %{y:.2f}ms<extra></extra>'
    ))

    # Calculate statistics for display
    mean_delay = np.mean(delay_values)
    std_delay = np.std(delay_values)
    min_delay = np.min(delay_values)
    max_delay = np.max(delay_values)

    # Add horizontal lines for statistics
    fig.add_hline(y=mean_delay, line_dash="dash", line_color="red",
                  annotation_text=f"Mean: {mean_delay:.2f}ms")
    fig.add_hline(y=mean_delay + std_delay, line_dash="dot", line_color="orange",
                  annotation_text=f"+1σ: {mean_delay + std_delay:.2f}ms")
    fig.add_hline(y=mean_delay - std_delay, line_dash="dot", line_color="orange",
                  annotation_text=f"-1σ: {mean_delay - std_delay:.2f}ms")

    # Update layout
    fig.update_layout(
        title=dict(
            text=f"GCC Delay Estimate Trace<br><sub>Duration: {duration_seconds:.2f}s, Samples: {num_samples}, Rate: 40Hz</sub>",
            x=0.5
        ),
        xaxis_title="Time (seconds)",
        yaxis_title="Delay Estimate (ms)",
        hovermode='x unified',
        showlegend=True,
        width=1200,
        height=600,
d         template="plotly_white",
        xaxis=dict(
            dtick=15,  # Grid lines every 15 seconds
            showgrid=True,
            gridwidth=1,
            gridcolor="lightgray"
        )
    )

    # Add statistics annotation
    stats_text = f"""
    <b>Statistics:</b><br>
    Mean: {mean_delay:.2f} ms<br>
    Std Dev: {std_delay:.2f} ms<br>
    Min: {min_delay:.2f} ms<br>
    Max: {max_delay:.2f} ms<br>
    Range: {max_delay - min_delay:.2f} ms
    """

    fig.add_annotation(
        x=0.02, y=0.98,
        xref="paper", yref="paper",
        text=stats_text,
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="black",
        borderwidth=1
    )

    # Save the plot
    plot_output_path = os.path.join(results_folder_path, "gcc_delay_estimate_plot.html")
    fig.write_html(plot_output_path)
    print(f"Plot saved to: {plot_output_path}")

    fig.show()


    print(f"\nTrace Statistics:")
    print(f"Mean Delay: {mean_delay:.2f} ms")
    print(f"Std Deviation: {std_delay:.2f} ms")
    print(f"Min Delay: {min_delay:.2f} ms")
    print(f"Max Delay: {max_delay:.2f} ms")
    print(f"Delay Range: {max_delay - min_delay:.2f} ms")
