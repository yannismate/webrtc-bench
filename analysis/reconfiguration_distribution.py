import os
import argparse
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from collections import Counter
from loaders.measurement import Measurement


def load_reconfig_times(folder_path: str) -> list[tuple[str, pd.Timestamp]]:
    """Load all reconfiguration timestamps from measurements in a folder."""
    reconfig_times = []

    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split('-')
            if len(parts) < 2:
                continue

            subfolder = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(subfolder)
                ms.load_files(only=['dishy'])

                # Get reconfiguration times from the measurement
                times = ms.get_handover_times()
                if times is not None:
                    reconfig_times.extend(times)
            except Exception as e:
                print(f"Error loading {subfolder}: {e}")

    return reconfig_times


def main():
    parser = argparse.ArgumentParser(
        description="Analyze reconfiguration time distribution by second within a minute."
    )
    parser.add_argument("path", help="Path to the results folder")
    args = parser.parse_args()

    reconfig_times = load_reconfig_times(args.path)

    if not reconfig_times:
        print("No reconfiguration times found.")
        return

    # Extract second of each reconfiguration time (rounded)
    # Handle different timestamp formats: tuples (source, timestamp), pd.Timestamp, datetime
    seconds = []
    for item in reconfig_times:
        if isinstance(item, tuple):
            # (source, timestamp) format from get_handover_times()
            ts = item[1]
        else:
            ts = item
        # Handle pd.Timestamp, datetime, or any object with .second attribute
        if hasattr(ts, 'second'):
            seconds.append(ts.second)
        elif hasattr(ts, 'dt'):
            seconds.append(ts.dt.second)
        else:
            raise ValueError(f"Unknown timestamp type: {type(ts)}")

    # Count occurrences per second (0-59)
    second_counts = Counter(seconds)

    # Create arrays for all 60 seconds
    all_seconds = np.arange(60)
    counts = np.array([second_counts.get(s, 0) for s in all_seconds])

    # Calculate probability distribution
    total = counts.sum()
    probabilities = counts / total * 100  # As percentage

    # Plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # Bar chart showing probability distribution
    bars = ax1.bar(all_seconds, probabilities, color='steelblue', edgecolor='black', alpha=0.7)
    ax1.set_xlabel("Second within Minute", fontsize=12)
    ax1.set_ylabel("Probability (%)", fontsize=12)
    ax1.set_title("Reconfiguration Time Distribution by Second within Minute", fontsize=14)
    ax1.set_xticks(np.arange(0, 60, 5))
    ax1.set_xlim(-0.5, 59.5)
    ax1.grid(axis='y', alpha=0.3)

    # Add vertical lines at 15-second intervals (12, 27, 42, 57)
    for sec in [12, 27, 42, 57]:
        ax1.axvline(x=sec, color='red', linestyle='--', alpha=0.5, label=f'{sec}s' if sec == 12 else None)

    # Annotate top 5 seconds
    top_indices = np.argsort(probabilities)[-5:][::-1]
    for idx in top_indices:
        if probabilities[idx] > 0:
            ax1.annotate(f'{probabilities[idx]:.1f}%',
                         xy=(idx, probabilities[idx]),
                         ha='center', va='bottom', fontsize=8)

    # Histogram showing raw counts
    ax2.bar(all_seconds, counts, color='forestgreen', edgecolor='black', alpha=0.7)
    ax2.set_xlabel("Second within Minute", fontsize=12)
    ax2.set_ylabel("Count", fontsize=12)
    ax2.set_title(f"Reconfiguration Count by Second (Total: {total})", fontsize=14)
    ax2.set_xticks(np.arange(0, 60, 5))
    ax2.set_xlim(-0.5, 59.5)
    ax2.grid(axis='y', alpha=0.3)

    # Add vertical lines at 15-second intervals
    for sec in [12, 27, 42, 57]:
        ax2.axvline(x=sec, color='red', linestyle='--', alpha=0.5)

    plt.tight_layout()

    # Save and show
    output_path = os.path.join(args.path, "reconfig_distribution.png")
    plt.savefig(output_path, bbox_inches='tight', dpi=150)
    print(f"Distribution saved to {output_path}")

    # Print summary statistics
    print(f"\nTotal reconfigurations: {total}")
    print(f"Most common seconds: {[s for s, _ in second_counts.most_common(5)]}")

    plt.show()


if __name__ == "__main__":
    main()