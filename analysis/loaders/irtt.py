import json
import os
import pandas as pd


class IrttData:
    round_trips: pd.DataFrame
    __has_jitter: bool = False

    def __init__(self, data: any):
        round_trips = data.get("round_trips", [])

        send_ns_list = []
        rtt_ms_list = []
        jitter_ms_list = []

        for rt in round_trips:
            ts = (rt or {}).get("timestamps", {})
            client = ts.get("client", {})
            send_ns = (client.get("send") or {}).get("wall")
            recv_ns = (client.get("receive") or {}).get("wall")
            if send_ns is not None and recv_ns is not None:
                send_ns_list.append(send_ns)
                rtt_ms_list.append((recv_ns - send_ns) / 1e6)
            ipdv = (rt or {}).get("ipdv", {})
            if ipdv is not None:
                jitter_ms_list.append(ipdv.get("rtt", 0) / 1e6)

        self.round_trips = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(send_ns_list, unit="ns", utc=True),
                "rtt_ms": rtt_ms_list,
                "jitter_ms": jitter_ms_list,
            }
        ).sort_values("timestamp", ignore_index=True)

    def get_rtt_ms(self) -> pd.Series | None:
        if self.round_trips is not None and not self.round_trips.empty:
            return self.round_trips.set_index("timestamp")["rtt_ms"]
        return None

    def get_jitter_ms(self) -> pd.Series | None:
        if self.round_trips is not None and not self.round_trips.empty:
            return self.round_trips.set_index("timestamp")["jitter_ms"]
        return None


def irtt_from_file(file_path: str) -> IrttData:
    print("Loading IRTT data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    with open(file_path, 'r') as file:
        data = json.load(file)

    return IrttData(data)