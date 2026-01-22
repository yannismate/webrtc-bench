import math
import json
import os
import pandas as pd

class DishyData:
    positions: pd.DataFrame
    switch_timestamps: list[pd.Timestamp]
    num_rows: int
    num_columns: int

    def __init__(self, data):
        num_rows = data["NumRows"]

        def get_row_col(index) -> tuple[int, int]:
            r = index // num_rows
            c = index % num_rows
            return r, c

        def get_distance(xa, ya, xb, yb) -> float:
            return math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)

        switch_timestamps = []
        known_snr = []
        latest_location_row = 0
        latest_location_col = 0
        latest_switch_row_before = 0
        latest_switch_col_before = 0
        positions = []
        self.num_rows = data["NumRows"]
        self.num_columns = data["NumColumns"]

        for obstruction_entry in data["ObstructionData"]:
            ts = pd.to_datetime(obstruction_entry["Time"], utc=True)
            for snr in (obstruction_entry["SNR"] or []):
                snr_idx = snr["Index"]
                if snr_idx in known_snr:
                    continue
                known_snr.append(snr_idx)
                known_snr = known_snr[-20:]
                row, col = get_row_col(snr_idx)
                positions.append({"time": ts, "row": row, "col": col})
                distance = get_distance(latest_location_row, latest_location_col, row, col)
                if distance > 3:
                    if get_distance(latest_switch_row_before, latest_switch_col_before, row, col) < 3:
                        continue
                    switch_timestamps.append(ts)
                    latest_switch_row_before = latest_location_row
                    latest_switch_col_before = latest_location_col
                latest_location_row = row
                latest_location_col = col

        positions_df = pd.DataFrame(positions)
        positions_df = positions_df.sort_values("time").reset_index(drop=True)
        self.positions = positions_df

        self.switch_timestamps = switch_timestamps[1:]


def dishy_from_file(file_path: str) -> DishyData:
    print("Loading Dishy data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    with open(file_path, 'r') as file:
        data = json.load(file)

    return DishyData(data)