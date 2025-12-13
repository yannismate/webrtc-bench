import os
import argparse
import pandas as pd
from loaders.measurement import Measurement


def find_zero_bitrate_period(
    bitrate: pd.Series,
    threshold_kbps: float = 100.0,
    min_duration_seconds: float = 10.0
) -> pd.Timestamp | None:
    """
    Find a period where bitrate drops to near-zero (< threshold_kbps)
    for at least min_duration_seconds consecutive seconds.

    Returns the timestamp of the start of the first matching period, or None if not found.
    """
    if bitrate is None or bitrate.empty:
        return None

    # Sort and resample to 1-second intervals for consistent analysis
    bitrate_sorted = bitrate.sort_index()
    bitrate_resampled = bitrate_sorted.resample('1s').mean().dropna()

    if len(bitrate_resampled) < min_duration_seconds:
        return None

    # Find periods where bitrate is below threshold
    below_threshold = bitrate_resampled < threshold_kbps

    # Track consecutive periods
    consecutive_start = None
    consecutive_count = 0

    for i, (timestamp, is_below) in enumerate(below_threshold.items()):
        if is_below:
            if consecutive_start is None:
                consecutive_start = timestamp
                consecutive_count = 1
            else:
                consecutive_count += 1

            # Check if we've reached the minimum duration
            if consecutive_count >= min_duration_seconds:
                return consecutive_start
        else:
            # Reset tracking
            consecutive_start = None
            consecutive_count = 0

    return None


def analyze_folder(folder_path: str, threshold_kbps: float, min_duration_seconds: float):
    """Analyze all measurements in a folder for zero bitrate periods."""
    matches = []

    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split('-')
            if len(parts) < 2:
                continue

            subfolder = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(subfolder)
                # Only load what we need: parquet for bitrate, iperf as fallback
                ms.load_files(only=['parquet', 'iperf'])

                # Get receive bitrate
                recv_br = ms.get_recv_bitrate_kbps()

                # Find zero bitrate period
                zero_start = find_zero_bitrate_period(
                    recv_br,
                    threshold_kbps=threshold_kbps,
                    min_duration_seconds=min_duration_seconds
                )

                if zero_start is not None:
                    matches.append((subfolder, zero_start))

            except Exception as e:
                # Skip folders that can't be loaded as measurements
                pass

    return matches


def main():
    parser = argparse.ArgumentParser(
        description="Find measurements where bitrate drops to near-zero for extended periods."
    )
    parser.add_argument("path", help="Path to the results folder")
    parser.add_argument(
        "--threshold", type=float, default=100.0,
        help="Bitrate threshold in kbps to consider as 'zero' (default: 100)"
    )
    parser.add_argument(
        "--min-duration", type=float, default=10.0,
        help="Minimum consecutive seconds below threshold (default: 10)"
    )
    args = parser.parse_args()

    print(f"Searching for bitrate < {args.threshold} kbps for >= {args.min_duration}s")
    print("-" * 60)

    matches = analyze_folder(
        args.path,
        threshold_kbps=args.threshold,
        min_duration_seconds=args.min_duration
    )

    if matches:
        print(f"\nFound {len(matches)} measurement(s) with zero bitrate periods:\n")
        for path, timestamp in matches:
            print(f"  Path: {path}")
            print(f"  Zero bitrate starts at: {timestamp}")
            print()
    else:
        print("\nNo matching zero bitrate periods found.")


if __name__ == "__main__":
    main()

