import json
import os
import pandas as pd


class ProbeData:
    probes: pd.DataFrame

    def __init__(self, data: any):
        self.probes = pd.DataFrame(data)

    def get_probe_timestamps(self) -> pd.Series | None:
        if self.probes is not None and not self.probes.empty:
            return pd.to_datetime(self.probes['Time'], unit='ns', utc=True)
        return None

def probes_from_file(file_path: str) -> ProbeData:
    print("Loading probe data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    with open(file_path, 'r') as file:
        data = json.load(file)

    return ProbeData(data)