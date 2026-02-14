import argparse
import os
from pathlib import Path
import pandas as pd

from loaders.measurement import Measurement


def to_utc_timestamp(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def series_to_timestamps(series: pd.Series | None) -> list[pd.Timestamp]:
    if series is None or series.empty:
        return []
    values = pd.to_datetime(series, utc=True)
    return [to_utc_timestamp(ts) for ts in values]


def handover_to_timestamps(
    handover_times: list[tuple[str, pd.Timestamp]] | None,
) -> list[pd.Timestamp]:
    if not handover_times:
        return []
    return [to_utc_timestamp(ts) for _, ts in handover_times]


def generate_periodic_reconfigs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    offsets: list[int],
) -> list[pd.Timestamp]:
    start_utc = to_utc_timestamp(start)
    end_utc = to_utc_timestamp(end)
    if end_utc <= start_utc:
        return []
    reconfigs: list[pd.Timestamp] = []
    current_minute = start_utc.floor("min")
    while current_minute <= end_utc:
        for offset in offsets:
            ts = current_minute + pd.Timedelta(seconds=offset)
            if start_utc <= ts <= end_utc:
                reconfigs.append(ts)
        current_minute += pd.Timedelta(minutes=1)
    return reconfigs


def count_true_false_positives(
    guard_triggers: list[pd.Timestamp],
    events: list[pd.Timestamp],
    window_ms: int,
) -> tuple[int, int]:
    if not guard_triggers:
        return 0, 0
    if not events:
        return 0, len(guard_triggers)
    window = pd.Timedelta(milliseconds=window_ms)
    true_pos = 0
    false_pos = 0
    for guard_ts in guard_triggers:
        if any(abs(guard_ts - evt) <= window for evt in events):
            true_pos += 1
        else:
            false_pos += 1
    return true_pos, false_pos


def merge_events(events: list[pd.Timestamp], merge_ms: int) -> list[list[pd.Timestamp]]:
    if not events:
        return []
    sorted_events = sorted(events)
    merged: list[list[pd.Timestamp]] = [[sorted_events[0]]]
    threshold = pd.Timedelta(milliseconds=merge_ms)
    for ts in sorted_events[1:]:
        if ts - merged[-1][-1] <= threshold:
            merged[-1].append(ts)
        else:
            merged.append([ts])
    return merged


def count_false_negatives(
    guard_triggers: list[pd.Timestamp],
    events: list[pd.Timestamp],
    window_ms: int,
    merge_ms: int,
) -> int:
    if not events:
        return 0
    merged = merge_events(events, merge_ms)
    if not guard_triggers:
        return len(merged)
    window = pd.Timedelta(milliseconds=window_ms)
    false_neg = 0
    for cluster in merged:
        if not any(abs(guard_ts - evt) <= window for evt in cluster for guard_ts in guard_triggers):
            false_neg += 1
    return false_neg


def is_measurement_folder(path: Path) -> bool:
    name = path.name
    return name.startswith("video") and ("reactive" in name or "guard" in name)


def count_handovers_near_reconfigs(
    handovers: list[pd.Timestamp],
    reconfigs: list[pd.Timestamp],
    window_seconds: float = 1.0,
) -> int:
    if not handovers or not reconfigs:
        return 0
    window = pd.Timedelta(seconds=window_seconds)
    return sum(1 for handover in handovers if any(abs(handover - rcfg) <= window for rcfg in reconfigs))


def compute_time_range(
    measurement: Measurement,
    handovers: list[pd.Timestamp],
    guard_triggers: list[pd.Timestamp],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    min_ts, max_ts = measurement.get_timestamp_range()
    if min_ts == pd.Timestamp.min.tz_localize("UTC") and max_ts == pd.Timestamp.max.tz_localize("UTC"):
        candidates = handovers + guard_triggers
        if not candidates:
            raise RuntimeError("No timestamps available to infer measurement duration.")
        min_ts = min(candidates)
        max_ts = max(candidates)
    return min_ts, max_ts


def evaluate_measurement(path: Path, window_ms: int, merge_ms: int) -> dict[str, int | float]:
    measurement = Measurement(str(path))
    measurement.load_files(only=["dishy", "guard_triggers", "iperf"])

    guard_triggers = series_to_timestamps(measurement.get_guard_trigger_timestamps())
    handovers = handover_to_timestamps(measurement.get_handover_times())
    start_ts, end_ts = compute_time_range(measurement, handovers, guard_triggers)
    reconfigs = generate_periodic_reconfigs(start_ts, end_ts, [12, 27, 42, 57])
    duration_seconds = max(0.0, (to_utc_timestamp(end_ts) - to_utc_timestamp(start_ts)).total_seconds())
    handovers_near_reconfigs = count_handovers_near_reconfigs(handovers, reconfigs)

    events = reconfigs + handovers
    true_pos, false_pos = count_true_false_positives(guard_triggers, events, window_ms)
    false_neg = count_false_negatives(guard_triggers, events, window_ms, merge_ms)

    return {
        "guard_triggers": len(guard_triggers),
        "reconfigs": len(reconfigs),
        "handovers": len(handovers),
        "event_clusters": len(merge_events(events, merge_ms)),
        "true_positives": true_pos,
        "false_positives": false_pos,
        "false_negatives": false_neg,
        "duration_seconds": duration_seconds,
        "handovers_near_reconfigs": handovers_near_reconfigs,
    }


def iter_measurement_paths(root: Path, recursive: bool) -> list[Path]:
    if is_measurement_folder(root):
        return [root]
    if not recursive:
        child_paths = [p for p in root.iterdir() if p.is_dir() and is_measurement_folder(p)]
        if child_paths:
            return child_paths
        return [root]
    paths: list[Path] = []
    for dir_path, dir_names, _ in os.walk(root):
        for dir_name in dir_names:
            if dir_name.startswith("video") or dir_name.startswith("bandwidth_measurement"):
                paths.append(Path(dir_path) / dir_name)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Count guard-trigger true/false positives against periodic reconfig timestamps and "
            "handover timestamps, plus false negatives with merged event windows."
        )
    )
    parser.add_argument("path", help="Measurement folder or results root")
    parser.add_argument("--window-ms", type=int, default=300, help="Match window in milliseconds")
    parser.add_argument(
        "--merge-ms",
        type=int,
        default=800,
        help="Merge reconfig/handover events within this window for false negatives",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan subfolders for measurement runs",
    )
    args = parser.parse_args()

    root = Path(args.path).resolve()
    paths = iter_measurement_paths(root, args.recursive)
    if not paths:
        raise SystemExit(f"No measurement paths found under {root}")

    totals = {
        "guard_triggers": 0,
        "reconfigs": 0,
        "handovers": 0,
        "event_clusters": 0,
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "duration_seconds": 0.0,
        "handovers_near_reconfigs": 0,
    }

    for path in paths:
        try:
            result = evaluate_measurement(path, args.window_ms, args.merge_ms)
        except Exception as exc:
            print(f"Skipping {path}: {exc}")
            continue

        duration_minutes = result["duration_seconds"] / 60.0
        print(f"\nMeasurement: {path}")
        print(f"  Guard triggers: {result['guard_triggers']}")
        print(f"  Reconfigs (periodic): {result['reconfigs']}")
        print(f"  Handovers (get_handover_times): {result['handovers']}")
        print(f"  Handovers within 1s of reconfig: {result['handovers_near_reconfigs']}")
        print(f"  Event clusters: {result['event_clusters']}")
        print(f"  True positives: {result['true_positives']}")
        print(f"  False positives: {result['false_positives']}")
        print(f"  False negatives: {result['false_negatives']}")
        print(f"  Duration (s): {result['duration_seconds']:.1f}")
        print(f"  Duration (min): {duration_minutes:.2f}")

        for key in totals:
            totals[key] += result[key]

    if len(paths) > 1:
        print("\nTotals")
        print(f"  Guard triggers: {totals['guard_triggers']}")
        print(f"  Reconfigs (periodic): {totals['reconfigs']}")
        print(f"  Handovers (get_handover_times): {totals['handovers']}")
        print(f"  Handovers within 1s of reconfig: {totals['handovers_near_reconfigs']}")
        print(f"  Event clusters: {totals['event_clusters']}")
        print(f"  True positives: {totals['true_positives']}")
        print(f"  False positives: {totals['false_positives']}")
        print(f"  False negatives: {totals['false_negatives']}")
        print(f"  Duration (s): {totals['duration_seconds']:.1f}")
        print(f"  Duration (min): {totals['duration_seconds'] / 60.0:.2f}")


if __name__ == "__main__":
    main()
