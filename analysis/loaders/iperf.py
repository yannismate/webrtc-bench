import json
import os

import pandas as pd


class IPerfData:
    intervals: pd.DataFrame

    def __init__(self, data: dict):
        time_start_sec = data["start"]["timestamp"]["timesecs"]

        intervals = data.get("intervals", [])
        extracted_data = [
            {
                'timestamp': pd.to_datetime((time_start_sec + interval['sum']['start']), unit='s', utc=True),
                'bits_per_second': interval['sum']['bits_per_second'],
                'jitter_ms': interval['sum'].get('jitter_ms'),
                'lost_percent': interval['sum'].get('lost_percent')
            }

            for interval in intervals
        ]
        self.intervals = pd.DataFrame(extracted_data)

    def get_send_bitrate_kbps(self) -> pd.Series | None:
        if self.intervals.empty:
            return None
        series = self.intervals.set_index('timestamp').sort_index()['bits_per_second'] / 1000
        series.index.name = 'Timestamp'
        series.name = "send_kbps"
        return series

    def get_recv_bitrate_kbps(self) -> pd.Series | None:
        if self.intervals.empty:
            return None
        series = self.intervals.set_index('timestamp').sort_index()['bits_per_second'] / 1000
        series.index.name = 'Timestamp'
        series.name = "recv_kbps"
        return series

    def get_timestamp_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        min_timestamp = self.intervals['timestamp'].min()
        max_timestamp = self.intervals['timestamp'].max()
        return min_timestamp, max_timestamp

    def get_jitter_ms(self) -> pd.Series | None:
        if self.intervals.empty or 'jitter_ms' not in self.intervals:
            return None
        series = self.intervals.set_index('timestamp').sort_index()['jitter_ms']
        series.index.name = 'Timestamp'
        series.name = "jitter_ms"
        return series

def iperf_from_file(file_path: str) -> IPerfData:
    print("Loading iperf data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")
    with open(file_path) as json_file:
        data = json.load(json_file)
    return IPerfData(data)
