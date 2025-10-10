import json
import os
import pandas as pd


class GuardTriggerData:
    guard_triggers: pd.DataFrame

    def __init__(self, timestamps: list[str]):
        self.probes = pd.DataFrame({'Time': timestamps})

    def get_guard_trigger_timestamps(self) -> pd.Series | None:
        if self.probes is not None and not self.probes.empty:
            return pd.to_datetime(self.probes['Time'], utc=True)
        return None

def guard_triggers_from_file(file_path: str) -> GuardTriggerData:
    print("Loading guard trigger data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    with open(file_path, 'r') as file:
        data = json.load(file)

    return GuardTriggerData(data)