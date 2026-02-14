import argparse
import os
from dataclasses import dataclass

import pandas as pd

from loaders.measurement import Measurement


def _duration_minutes_from_dishy(measurement: Measurement) -> float | None:
    timestamps: list[pd.Timestamp] = []

    for dishy in (measurement.data_dishy_sender, measurement.data_dishy_receiver):
        if dishy is None:
            continue
        if getattr(dishy, "positions", None) is not None and not dishy.positions.empty:
            timestamps.append(dishy.positions["time"].min())
            timestamps.append(dishy.positions["time"].max())
        timestamps.extend(dishy.switch_timestamps or [])

    if not timestamps:
        return None

    min_ts = min(timestamps)
    max_ts = max(timestamps)
    if min_ts == max_ts:
        return None

    return (max_ts - min_ts).total_seconds() / 60.0


@dataclass
class MeasurementStats:
    name: str
    measurement_type: str
    reconfig_count: int
    duration_minutes: float

    @property
    def rate(self) -> float:
        return self.reconfig_count / self.duration_minutes if self.duration_minutes > 0 else 0.0


def collect_measurement_stats(root_path: str) -> list[MeasurementStats]:
    stats: list[MeasurementStats] = []

    for dir_path, dir_names, _ in os.walk(root_path):
        for dir_name in dir_names:
            measurement_path = os.path.join(dir_path, dir_name)
            try:
                ms = Measurement(measurement_path)
                ms.load_files(only=["dishy"])
            except Exception as exc:
                print(f"Skipping {measurement_path}: {exc}")
                continue

            duration_minutes = _duration_minutes_from_dishy(ms)
            if duration_minutes is None:
                print(f"Skipping {measurement_path}: unable to determine Dishy duration")
                continue

            reconfig_times = ms.get_handover_times() or []
            stats.append(
                MeasurementStats(
                    name=ms.name,
                    measurement_type=ms.type.value,
                    reconfig_count=len(reconfig_times),
                    duration_minutes=duration_minutes,
                )
            )

    return stats


def print_report(stats: list[MeasurementStats]):
    if not stats:
        print("No valid measurements found.")
        return

    total_minutes = sum(item.duration_minutes for item in stats)
    total_reconfigs = sum(item.reconfig_count for item in stats)
    avg_rate = total_reconfigs / total_minutes if total_minutes > 0 else 0.0

    print("=== Reconfiguration Density Report ===")
    print(f"Measurements analyzed : {len(stats)}")
    print(f"Total duration         : {total_minutes:.2f} minutes")
    print(f"Total reconfigurations : {total_reconfigs}")
    print(f"Average reconfigs/min  : {avg_rate:.4f}")

    stats_sorted = sorted(stats, key=lambda item: item.rate, reverse=True)
    top_n = stats_sorted[:5]
    print("\nTop measurements by reconfigs/min:")
    for entry in top_n:
        print(
            f"- {entry.name} ({entry.measurement_type}): "
            f"{entry.reconfig_count} reconfigs over {entry.duration_minutes:.2f} min => {entry.rate:.4f}/min"
        )

    zero_reconfig = sum(1 for item in stats if item.reconfig_count == 0)
    print(f"\nMeasurements with zero reconfigs: {zero_reconfig}")


def main():
    parser = argparse.ArgumentParser(
        description="Compute the average number of reconfigurations per minute across measurements."
    )
    parser.add_argument("path", help="Path to the directory containing measurement folders")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        raise SystemExit(f"Provided path '{args.path}' is not a directory.")

    stats = collect_measurement_stats(args.path)
    print_report(stats)


if __name__ == "__main__":
    main()
