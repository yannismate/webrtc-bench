import os
import argparse
import pandas as pd
from loaders.measurement import Measurement


def find_major_bitrate_drop(
    bitrate: pd.Series,
    reconfig_times: list[tuple[str, pd.Timestamp]],
    drop_threshold: float = 0.5,
    window_seconds: float = 2.0,
    min_distance_seconds: float = 10.0
) -> pd.Timestamp | None:
    """
    Find a major bitrate drop (>= drop_threshold reduction within window_seconds)
    that occurs at least min_distance_seconds away from any reconfiguration.

    Returns the timestamp of the first matching drop, or None if not found.
    """
    if bitrate is None or bitrate.empty:
        return None

    # Extract just the timestamps from reconfiguration times
    reconfig_ts = [ts for _, ts in reconfig_times] if reconfig_times else []

    # Convert to numeric for rolling calculations
    bitrate_sorted = bitrate.sort_index()

    # Resample to 1-second intervals for consistent analysis
    bitrate_resampled = bitrate_sorted.resample('1s').mean().dropna()
    if len(bitrate_resampled) < 3:
        return None

    # Smooth over 3 seconds to prevent false positives
    bitrate_resampled = bitrate_resampled.rolling(window=3, center=True, min_periods=1).mean()

    # Look for drops: compare each point to the max in the previous window
    window_size = int(window_seconds)

    for i in range(window_size, len(bitrate_resampled)):
        current_val = bitrate_resampled.iloc[i]
        # Get max value in the window before this point
        window_start = max(0, i - window_size)
        prev_max = bitrate_resampled.iloc[window_start:i].max()

        if prev_max <= 0:
            continue

        # Check if drop is significant (at least drop_threshold reduction)
        drop_ratio = (prev_max - current_val) / prev_max
        if drop_ratio >= drop_threshold:
            drop_time = bitrate_resampled.index[i]

            # Check distance from all reconfigurations
            is_far_from_reconfig = True
            for reconfig_time in reconfig_ts:
                time_diff = abs((drop_time - reconfig_time).total_seconds())
                if time_diff < min_distance_seconds:
                    is_far_from_reconfig = False
                    break

            if is_far_from_reconfig:
                return drop_time

    return None


def analyze_folder(folder_path: str, drop_threshold: float, window_seconds: float, min_distance_seconds: float):
    """Analyze all measurements in a folder for major bitrate drops."""
    matches = []

    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split('-')
            if len(parts) < 2:
                continue

            subfolder = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(subfolder)
                # Only load what we need: parquet for bitrate, dishy for reconfigurations
                ms.load_files(only=['dishy', 'parquet', 'iperf'])

                # Get receive bitrate and reconfiguration times
                recv_br = ms.get_recv_bitrate_kbps()
                reconfig_times = ms.get_reconfiguration_times()

                # Find major drop
                drop_time = find_major_bitrate_drop(
                    recv_br,
                    reconfig_times,
                    drop_threshold=drop_threshold,
                    window_seconds=window_seconds,
                    min_distance_seconds=min_distance_seconds
                )

                if drop_time is not None:
                    matches.append((subfolder, drop_time))

            except Exception as e:
                # Skip folders that can't be loaded as measurements
                pass

    return matches


def main():
    parser = argparse.ArgumentParser(
        description="Find major bitrate drops that occur away from reconfigurations."
    )
    parser.add_argument("path", help="Path to the results folder")
    parser.add_argument(
        "--drop-threshold", type=float, default=0.5,
        help="Minimum drop ratio to consider (0.5 = 50%% drop, default: 0.5)"
    )
    parser.add_argument(
        "--window-seconds", type=float, default=2.0,
        help="Time window in seconds to measure drop (default: 2.0)"
    )
    parser.add_argument(
        "--min-distance", type=float, default=10.0,
        help="Minimum distance in seconds from any reconfiguration (default: 10.0)"
    )
    args = parser.parse_args()

    print(f"Searching for bitrate drops >= {args.drop_threshold*100:.0f}% within {args.window_seconds}s")
    print(f"Minimum distance from reconfiguration: {args.min_distance}s")
    print("-" * 60)

    matches = analyze_folder(
        args.path,
        drop_threshold=args.drop_threshold,
        window_seconds=args.window_seconds,
        min_distance_seconds=args.min_distance
    )

    if matches:
        print(f"\nFound {len(matches)} measurement(s) with matching bitrate drops:\n")
        for path, timestamp in matches:
            print(f"  Path: {path}")
            print(f"  Drop at: {timestamp}")
            print()
    else:
        print("\nNo matching bitrate drops found.")


if __name__ == "__main__":
    main()

