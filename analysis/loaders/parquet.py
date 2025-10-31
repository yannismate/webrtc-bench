import os
import pyarrow.parquet as pq
import pandas as pd

class ParquetData:
    data: pd.DataFrame
    has_gcc_stats: bool = False
    has_scream_stats: bool = False

    def __init__(self, df: pd.DataFrame):
        df = pd.json_normalize(df.to_dict(orient='records'))

        for key in df.columns.values:
            if df[key].dtype == object and not "." in key:
                df.drop(key, axis='columns', inplace=True)

        # Ensure Timestamp column is tz-aware UTC
        if "Timestamp" in df.columns:
            df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True)

        # Remove odd lines at beginning of recording with old timestamps
        one_year_ago = (pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1))
        df = df[df["Timestamp"] >= one_year_ago]

        # Drop rows at the beginning with 0 packets sent/received
        if "OutboundRTP.PacketsSent" in df.columns:
            df = df.loc[df["OutboundRTP.PacketsSent"].ne(0).cummax()]
        if "InboundRTP.PacketsReceived" in df.columns:
            df = df.loc[df["InboundRTP.PacketsReceived"].ne(0).cummax()]

        # Remove duplicate stat rows with same timestamp
        df.drop_duplicates(subset=['Timestamp'], keep='first', inplace=True)
        df.set_index("Timestamp", inplace=True)
        df.sort_index(inplace=True)
        self.data = df
        self.has_gcc_stats = 'GCCStats.State' in df
        self.has_scream_stats = 'ScreamStats.TargetBitrate' in df

    def get_send_bitrate_kbps(self, resample_ms: int = 200) -> pd.Series | None:
        if "OutboundRTP.BytesSent" not in self.data:
            return None
        sender_rate = self.data["OutboundRTP.BytesSent"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
        sender_rate = (sender_rate / 1000) * 8 * (1000/resample_ms)
        sender_rate.index.name = 'Timestamp'
        sender_rate.name = "send_kbps"
        return sender_rate

    def get_recv_bitrate_kbps(self, resample_ms: int = 200) -> pd.Series | None:
        if "InboundRTP.BytesReceived" not in self.data:
            return None
        receiver_rate = self.data["InboundRTP.BytesReceived"].resample(f"{resample_ms}ms").max().diff().fillna(0).clip(lower=0)
        receiver_rate = (receiver_rate / 1000) * 8 * (1000/resample_ms)
        receiver_rate.index.name = 'Timestamp'
        receiver_rate.name = "recv_kbps"
        return receiver_rate

    def get_loss_rate(self) -> pd.Series | None:
        if "InboundRTP.PacketsLost" in self.data and "InboundRTP.PacketsReceived" in self.data:
            packets_lost = self.data["InboundRTP.PacketsLost"].resample("200ms").max().diff().fillna(0).clip(lower=0)
            packets_received = self.data["InboundRTP.PacketsReceived"].resample("200ms").max().diff().fillna(0).clip(lower=0)
            total_packets = packets_lost + packets_received
            loss_rate = (packets_lost / total_packets).replace([float('inf'), -float('inf')], float('nan')).fillna(0)
            loss_rate.index.name = 'Timestamp'
            loss_rate.name = "loss_rate"
            return loss_rate
        return None

    def get_rtt_ms(self) -> pd.Series | None:
        if "OutboundRTP.RoundTripTime" in self.data:
            rtt_series = self.data["OutboundRTP.RoundTripTime"] * 1000
            if not (rtt_series == 0).all():
                rtt_series.index.name = 'Timestamp'
                rtt_series.name = "rtt_ms"
                return rtt_series
        print("Available columns in Parquet data:", self.data.columns.tolist())
        return None

    def get_jitter_ms(self) -> pd.Series | None:
        if "InboundRTP.Jitter" in self.data:
            jitter_series = self.data["InboundRTP.Jitter"] * 1000
            if not (jitter_series == 0).all():
                jitter_series.index.name = 'Timestamp'
                jitter_series.name = "jitter_ms"
                return jitter_series
        return None

    def get_congestion_bitrates(self) -> pd.DataFrame | None:
        if self.data.empty or not all(
                col in self.data for col in ['GCCStats.LossTargetBitrate', 'GCCStats.DelayTargetBitrate']):
            return None
        df = self.data[['GCCStats.LossTargetBitrate', 'GCCStats.DelayTargetBitrate']]
        df = df / 1000
        df.index.name = 'Timestamp'
        return df

    def get_delay_estimate(self) -> pd.Series | None:
        if "GCCStats.DelayEstimate" in self.data:
            delay_estimate_series = self.data["GCCStats.DelayEstimate"]
            if not (delay_estimate_series == 0).all():
                delay_estimate_series.index.name = 'Timestamp'
                delay_estimate_series.name = "delay_estimate_ms"
                return delay_estimate_series
        return None

    def get_feedback_interval_ms(self) -> pd.Series | None:
        if "GCCStats.MsSinceLastReport" in self.data:
            delay_estimate_series = self.data["GCCStats.MsSinceLastReport"]
            if not (delay_estimate_series == 0).all():
                delay_estimate_series.index.name = 'Timestamp'
                delay_estimate_series.name = "feedback_interval_ms"
                return delay_estimate_series
        return None

    def get_congestion_states(self) -> pd.DataFrame | None:
        state_columns = [col for col in ['GCCStats.Usage', 'GCCStats.State', 'GCCStats.DetectedReconfiguration', 'GCCStats.GuardState'] if col in self.data]
        if state_columns:
            df = self.data[state_columns].copy()
            df.index.name = 'Timestamp'
            return df
        return None

    def get_timestamp_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.data.index.min(), self.data.index.max()

    def get_send_fps(self) -> pd.Series | None:
        if "OutboundRTP.FramesSent" not in self.data:
            return None
        fps = self.data["OutboundRTP.FramesSent"].resample("1s").max().diff().fillna(0).clip(lower=0)
        fps.index.name = 'Timestamp'
        fps.name = "send_fps"
        return fps

    def get_recv_fps(self) -> pd.Series | None:
        if "InboundRTP.FramesReceived" not in self.data:
            return None
        fps = self.data["InboundRTP.FramesReceived"].resample("1s").max().diff().fillna(0).clip(lower=0)
        fps.index.name = 'Timestamp'
        fps.name = "recv_fps"
        return fps

    def get_freeze_times(self) -> pd.Series | None:
        if "InboundRTP.FreezeCount" not in self.data:
            return None
        freezes = self.data["InboundRTP.FreezeCount"].diff().fillna(0)
        freeze_times = freezes[freezes > 0]
        freeze_times.index.name = 'Timestamp'
        freeze_times.name = "freeze_count"
        return freeze_times

    def get_total_freeze_duration(self) -> float | None:
        if "InboundRTP.TotalFreezesDuration" not in self.data:
            return None
        # Ignore freezes during the first 30 seconds of the call during startup
        first_ts = self.data.index[0]
        startup_end = first_ts + pd.Timedelta(seconds=30)
        startup_freeze = self.data[self.data.index <= startup_end]['InboundRTP.TotalFreezesDuration'].iloc[-1]
        return self.data['InboundRTP.TotalFreezesDuration'].iloc[-1] - startup_freeze

def parquet_from_file(file_path: str) -> ParquetData | None:
    print("Loading Parquet data from file:", file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    df = pq.read_pandas(file_path).to_pandas()
    if len(df) == 0:
        return None

    return ParquetData(df)