import os
import pandas as pd
import pyarrow.parquet as pq
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import argparse
import numpy as np
from scipy.signal import find_peaks
from statsmodels.tsa.stattools import acf

parser = argparse.ArgumentParser(description="Analyze WebRTC GCC patterns using autocorrelation.")
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

sender_df = load_parquet(os.path.join(results_folder_path, "sender.parquet"))

if 'GCCStats.DelayEstimate' not in sender_df:
    print("Parquet file does not contain GCC stats")
    exit(0)

# Use the original time series without resampling
# Drop NaN values and get the signal
signal = sender_df["GCCStats.DelayEstimate"].dropna().values
timestamps = sender_df["GCCStats.DelayEstimate"].dropna().index

# Calculate the actual sampling rate from the data
time_diffs = np.diff(timestamps.astype(np.int64) / 1e9)  # Convert to seconds
avg_time_diff = np.median(time_diffs)  # Use median to avoid outliers
sampling_rate = 1.0 / avg_time_diff

print(f"Original sampling rate: {sampling_rate:.2f} Hz (average interval: {avg_time_diff:.3f} seconds)")

# Calculate autocorrelation with lags up to 90 seconds
max_lag = int(90 * sampling_rate)
min_lag = int(10 * sampling_rate)

# Ensure we don't exceed the signal length
max_lag = min(max_lag, len(signal) - 1)

# Compute autocorrelation
autocorr = acf(signal, nlags=max_lag, fft=True)

# Find peaks in autocorrelation within 10-90 second range
peaks, properties = find_peaks(
    autocorr[min_lag:max_lag+1],
    prominence=0.2,
    distance=int(2 * sampling_rate)  # Minimum 2 seconds between peaks (reduced from 5)
)

# Adjust peak indices to match original lag values
peaks += min_lag

# Convert peak lags to seconds
peak_intervals = peaks / sampling_rate

# Create visualization
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=False,
    vertical_spacing=0.08,
    subplot_titles=(
        "GCC Delay Estimate",
        "Autocorrelation Function",
        "Detected Periodic Intervals"
    )
)

fig.update_layout(
    title_text=f"WebRTC GCC Autocorrelation Analysis - {results_folder_path}",
    height=900
)

# Plot original signal
fig.add_trace(
    go.Scatter(
        x=timestamps,
        y=signal,
        mode="lines",
        name="GCC Delay Estimate (ms)",
        line=dict(color="black"),
    ),
    row=1,
    col=1,
)

# Plot autocorrelation
lags = np.arange(len(autocorr)) / sampling_rate
fig.add_trace(
    go.Scatter(
        x=lags,
        y=autocorr,
        mode="lines",
        name="Autocorrelation",
        line=dict(color="blue"),
    ),
    row=2,
    col=1,
)

# Add vertical lines for 10 and 90 second boundaries
fig.add_vline(x=10, line_dash="dash", line_color="gray", row=2, col=1)
fig.add_vline(x=90, line_dash="dash", line_color="gray", row=2, col=1)

# Mark detected peaks
if len(peaks) > 0:
    fig.add_trace(
        go.Scatter(
            x=peak_intervals,
            y=autocorr[peaks],
            mode="markers",
            name="Detected Periods",
            marker=dict(color="red", size=10, symbol="star"),
        ),
        row=2,
        col=1,
    )

# Plot detected intervals as bar chart
if len(peak_intervals) > 0:
    fig.add_trace(
        go.Bar(
            x=peak_intervals,
            y=autocorr[peaks],
            name="Period Strength",
            text=[f"{interval:.1f}s" for interval in peak_intervals],
            textposition="outside",
        ),
        row=3,
        col=1,
    )

# Update axes
fig.update_xaxes(title_text="Time", row=1, col=1)
fig.update_yaxes(title_text="Delay (ms)", row=1, col=1)

fig.update_xaxes(title_text="Lag (seconds)", range=[0, 70], row=2, col=1)
fig.update_yaxes(title_text="Correlation", range=[-0.2, 1.1], row=2, col=1)

fig.update_xaxes(title_text="Period (seconds)", range=[5, 65], row=3, col=1)
fig.update_yaxes(title_text="Correlation Strength", range=[0, 1.1], row=3, col=1)

# Print detected periods
print("\nDetected periodic intervals:")
for i, (interval, correlation) in enumerate(zip(peak_intervals, autocorr[peaks])):
    print(f"  Period: {interval:.1f} seconds, Correlation: {correlation:.3f}")

if len(peak_intervals) == 0:
    print("  No significant periodic patterns found in 10-90 second range")
else:
    # Additional analysis: check for sub-patterns
    strongest_peak_idx = np.argmax(autocorr[peaks])
    strongest_period = peak_intervals[strongest_peak_idx]
    print(f"\nStrongest periodicity: {strongest_period:.1f} seconds")

    # Look for harmonics/subharmonics
    for harmonic in [0.5, 2.0, 3.0]:
        harmonic_period = strongest_period * harmonic
        if 10 <= harmonic_period <= 90:
            harmonic_lag = int(harmonic_period * sampling_rate)
            if harmonic_lag < len(autocorr):
                print(f"  Harmonic at {harmonic_period:.1f}s: correlation = {autocorr[harmonic_lag]:.3f}")

fig.show()
