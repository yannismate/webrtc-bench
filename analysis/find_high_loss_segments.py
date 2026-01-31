import os
import argparse
from typing import Iterable
import pandas as pd
from loaders.measurement import Measurement


SEGMENT_SECONDS = 15
SEGMENT_START_OFFSETS = (12, 27, 42, 57)


def iter_segment_starts(min_ts: pd.Timestamp, max_ts: pd.Timestamp) -> Iterable[pd.Timestamp]:
    start_minute = min_ts.floor("min")
    end_minute = max_ts.ceil("min")
    for minute in pd.date_range(start=start_minute, end=end_minute, freq="min"):
        for offset in SEGMENT_START_OFFSETS:
            yield minute + pd.Timedelta(seconds=offset)


def find_high_loss_segments(
    loss_rate: pd.Series,
    threshold: float = 0.10,
) -> list[tuple[pd.Timestamp, float]]:
    if loss_rate is None or loss_rate.empty:
        return []

    loss_sorted = loss_rate.sort_index().dropna()
    if loss_sorted.empty:
        return []

    min_ts = loss_sorted.index.min()
    max_ts = loss_sorted.index.max()
    if pd.isna(min_ts) or pd.isna(max_ts):
        return []

    matches: list[tuple[pd.Timestamp, float]] = []
    for seg_start in iter_segment_starts(min_ts, max_ts):
        seg_end = seg_start + pd.Timedelta(seconds=SEGMENT_SECONDS)
        if seg_end <= min_ts or seg_start >= max_ts:
            continue

        window = loss_sorted[(loss_sorted.index >= seg_start) & (loss_sorted.index < seg_end)]
        if window.empty:
            continue

        avg_loss = float(window.mean())
        if avg_loss >= threshold:
            matches.append((seg_start, avg_loss))

    return matches


def analyze_folder(folder_path: str, threshold: float) -> list[tuple[str, pd.Timestamp, float]]:
    matches: list[tuple[str, pd.Timestamp, float]] = []

    for dir_path, dir_names, file_names in os.walk(folder_path):
        for dir_name in dir_names:
            parts = dir_name.split("-")
            if len(parts) < 2:
                continue

            subfolder = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(subfolder)
                ms.load_files(only=["parquet", "iperf"])

                loss_rate = ms.get_loss_rate()
                for seg_start, avg_loss in find_high_loss_segments(loss_rate, threshold=threshold):
                    matches.append((subfolder, seg_start, avg_loss))
            except Exception:
                pass

    return matches


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find measurements with 15s loss segments starting at absolute seconds 12/27/42/57."
        )
    )
    parser.add_argument("path", help="Path to the results folder")
    parser.add_argument(
        "--loss-threshold",
        type=float,
        default=0.10,
        help="Average loss rate threshold as a fraction (default: 0.10 = 10%%)",
    )
    args = parser.parse_args()

    print(
        "Searching for average loss >= "
        f"{args.loss_threshold * 100:.1f}% in {SEGMENT_SECONDS}s segments"
    )
    print("-" * 60)

    matches = analyze_folder(args.path, threshold=args.loss_threshold)

    if matches:
        print(f"\nFound {len(matches)} segment(s) with elevated loss:\n")
        for path, timestamp, avg_loss in matches:
            print(f"  Path: {path}")
            print(f"  Segment starts at: {timestamp}")
            print(f"  Avg loss: {avg_loss * 100:.2f}%")
            print()
    else:
        print("\nNo high-loss segments found.")


if __name__ == "__main__":
    main()
