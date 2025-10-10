import json
import pandas as pd

class IcmpPingData:
    pings: pd.DataFrame

    def __init__(self, json_data):
        ping_entries = json_data.get("Pings", []) or []
        rows = []
        for ping in ping_entries:
            if not isinstance(ping, dict):
                continue
            ts_raw = ping.get("ReplyRecvTime")
            if ts_raw is None:
                continue
            ts = pd.to_datetime(ts_raw, utc=True)
            rtt_ns = ping.get("Rtt")
            rtt_ms = (rtt_ns / 1e6) if isinstance(rtt_ns, (int, float)) else None
            rows.append({
                "timestamp": ts,
                "rtt_ms": rtt_ms,
                "seq": ping.get("Seq"),
                "ttl": ping.get("Ttl"),
            })
        self.pings = pd.DataFrame(rows)
        if not self.pings.empty:
            self.pings = self.pings.sort_values("timestamp").reset_index(drop=True)

    def get_icmp_pings(self) -> pd.Series:
        series = self.pings.set_index('timestamp').sort_index()['rtt_ms']
        series.index.name = 'Timestamp'
        series.name = "icmp_ping"
        return series

def icmp_ping_from_json(json_path):
    print("Loading ICMP ping data from json file:", json_path)
    with open(json_path) as json_file:
        data = json.load(json_file)
    return IcmpPingData(data)