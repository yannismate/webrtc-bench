import os
from enum import Enum
import pandas as pd

from loaders.dishy import dishy_from_file, DishyData
from loaders.guard_triggers import GuardTriggerData, guard_triggers_from_file
from loaders.icmp_ping import icmp_ping_from_json, IcmpPingData
from loaders.iperf import iperf_from_file, IPerfData
from loaders.irtt import IrttData, irtt_from_file
from loaders.parquet import ParquetData, parquet_from_file
from loaders.probes import ProbeData, probes_from_file
from loaders.weather import WeatherData, weather_data_from_file


class MeasurementType(Enum):
    BANDWIDTH_MEASUREMENT = "bandwidth_measurement"
    VIDEO = "video"

class Measurement:
    folder_path: str
    name: str
    timestamp: pd.Timestamp
    type: MeasurementType

    data_dishy_sender: DishyData | None = None
    data_dishy_receiver: DishyData | None = None
    data_iperf_sender: IPerfData | None = None
    data_iperf_receiver: IPerfData | None = None
    data_irtt: IrttData | None = None
    data_parquet_sender: ParquetData | None = None
    data_parquet_receiver: ParquetData | None = None
    data_icmp_sender: IcmpPingData | None = None
    data_probes_sender: ProbeData | None = None
    data_guard_triggers_sender: GuardTriggerData | None = None
    weather_data: WeatherData | None = None

    def __init__(self, folder_path: str = None):
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise ValueError(f"Folder '{folder_path}' does not exist.")

        folder_name = os.path.basename(os.path.normpath(folder_path))

        if folder_name.startswith("video"):
            measurement_type = MeasurementType.VIDEO
        elif folder_name.startswith("bandwidth_measurement"):
            measurement_type = MeasurementType.BANDWIDTH_MEASUREMENT
        else:
            raise ValueError(f"Folder name '{folder_name}' does not match any known measurement type.")

        name_parts = folder_name.split("-")
        if len(name_parts) < 3:
            raise ValueError(
                f"Folder name '{folder_name}' does not contain enough parts to extract name and timestamp.")

        name = "-".join(name_parts[1:-1])
        try:
            ts_int = int(name_parts[-1])
            timestamp = pd.to_datetime(ts_int, unit='s', utc=True)
        except Exception as e:
            raise ValueError(f"Folder name '{folder_name}' contains invalid timestamp '{name_parts[-1]}'.") from e

        self.folder_path = folder_path
        self.name = name
        self.timestamp = timestamp
        self.type = measurement_type


    def load_files(self, only: list[str] | None = None):
        """Load measurement files.

        Args:
            only: Optional list of data types to load. If None, loads all.
                  Valid values: 'dishy', 'iperf', 'irtt', 'parquet', 'probes',
                  'guard_triggers', 'weather'
        """
        load_all = only is None
        if load_all or 'dishy' in only:
            self.__load_dishy_files()
        if load_all or 'iperf' in only:
            self.__load_iperf_files()
        if load_all or 'irtt' in only:
            self.__load_irtt_files()
        if load_all or 'parquet' in only:
            self.__load_parquet_files()
        if load_all or 'probes' in only:
            self.__load_probes_files()
        if load_all or 'guard_triggers' in only:
            self.__load_guard_trigger_files()
        if load_all or 'weather' in only:
            self.__load_weather_data()

    def get_send_bitrate_kbps(self, resample_ms: int = 200) -> pd.Series | None:
        if self.data_parquet_sender is not None:
            return self.data_parquet_sender.get_send_bitrate_kbps(resample_ms)
        if self.data_iperf_sender is not None:
            return self.data_iperf_sender.get_send_bitrate_kbps()
        return None

    def get_recv_bitrate_kbps(self, resample_ms: int = 200) -> pd.Series | None:
        if self.data_parquet_receiver is not None:
            return self.data_parquet_receiver.get_recv_bitrate_kbps(resample_ms)
        if self.data_iperf_receiver is not None:
            return self.data_iperf_receiver.get_recv_bitrate_kbps()
        return None

    def get_parquet_rtt_ms(self) -> pd.Series | None:
        if self.data_parquet_sender is not None:
            rtt = self.data_parquet_sender.get_rtt_ms()
            if rtt is not None:
                return rtt
        if self.data_parquet_receiver is not None:
            rtt = self.data_parquet_receiver.get_rtt_ms()
            if rtt is not None:
                return rtt
        return None

    def get_irtt_rtt_ms(self) -> pd.Series | None:
        if self.data_irtt is not None:
            return self.data_irtt.get_rtt_ms()
        return None

    def get_rtt_ms(self) -> pd.Series | None:
        # Prefer explicit parquet RTT first, then fall back to IRTT for backwards compatibility
        parquet_rtt = self.get_parquet_rtt_ms()
        if parquet_rtt is not None:
            return parquet_rtt
        return self.get_irtt_rtt_ms()

    def get_jitter_ms(self) -> pd.Series | None:
        if self.data_parquet_receiver is not None:
            jitter = self.data_parquet_receiver.get_jitter_ms()
            if jitter is not None:
                return jitter

        if self.data_irtt is not None:
           return self.data_irtt.get_jitter_ms()

        if self.data_iperf_receiver is not None:
            jitter = self.data_iperf_receiver.get_jitter_ms()
            if jitter is not None:
                return jitter
        return None

    def get_loss_rate(self) -> pd.Series | None:
        if self.data_parquet_receiver is not None:
            loss = self.data_parquet_receiver.get_loss_rate()
            if loss is not None:
                return loss

        if self.data_iperf_receiver is not None:
            loss = self.data_iperf_receiver.get_loss_rate()
            if loss is not None:
                return loss
        return None

    def get_congestion_bitrates(self) -> pd.DataFrame | None:
        if self.data_parquet_sender is not None:
            cong = self.data_parquet_sender.get_congestion_bitrates()
            if cong is not None:
                return cong
        return None

    def get_delay_estimate_ms(self) -> pd.Series | None:
        if self.data_parquet_sender is not None:
            delay_estimate = self.data_parquet_sender.get_delay_estimate()
            if delay_estimate is not None:
                return delay_estimate
        return None

    def get_feedback_interval_ms(self) -> pd.Series | None:
        if self.data_parquet_sender is not None:
            feedback_interval = self.data_parquet_sender.get_feedback_interval_ms()
            if feedback_interval is not None:
                return feedback_interval
        return None

    def get_timestamp_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        min_timestamp = pd.Timestamp.max.tz_localize('UTC')
        max_timestamp = pd.Timestamp.min.tz_localize('UTC')
        if self.data_parquet_sender is not None:
            min_v, max_v = self.data_parquet_sender.get_timestamp_range()
            min_timestamp = min(min_timestamp, min_v)
            max_timestamp = max(max_timestamp, max_v)
        if self.data_parquet_receiver is not None:
            min_v, max_v = self.data_parquet_receiver.get_timestamp_range()
            min_timestamp = min(min_timestamp, min_v)
            max_timestamp = max(max_timestamp, max_v)
        if self.data_iperf_sender is not None:
            min_v, max_v = self.data_iperf_sender.get_timestamp_range()
            min_timestamp = min(min_timestamp, min_v)
            max_timestamp = max(max_timestamp, max_v)
        if self.data_iperf_receiver is not None:
            min_v, max_v = self.data_iperf_receiver.get_timestamp_range()
            min_timestamp = min(min_timestamp, min_v)
            max_timestamp = max(max_timestamp, max_v)

        # If no data was found, return full min/max range
        if min_timestamp == pd.Timestamp.max.tz_localize('UTC') or max_timestamp == pd.Timestamp.min.tz_localize('UTC'):
            min_timestamp = pd.Timestamp.min.tz_localize('UTC')
            max_timestamp = pd.Timestamp.max.tz_localize('UTC')

        return min_timestamp, max_timestamp

    def get_reconfiguration_times(self) -> list[tuple[str, pd.Timestamp]]:
        reconfig_times = []
        min_ts, max_ts = self.get_timestamp_range()

        if self.data_dishy_sender is not None:
            for t in self.data_dishy_sender.switch_timestamps:
                if t < min_ts or t > max_ts:
                    continue
                reconfig_times.append(("sender", t))
        if self.data_dishy_receiver is not None:
            for t in self.data_dishy_receiver.switch_timestamps:
                if t < min_ts or t > max_ts:
                    continue
                reconfig_times.append(("receiver", t))
        return reconfig_times

    def get_congestion_states(self) -> pd.DataFrame | None:
        if self.data_parquet_sender is not None:
            states = self.data_parquet_sender.get_congestion_states()
            if states is not None:
                return states
        return None

    def get_send_fps(self) -> pd.Series | None:
        if self.data_parquet_sender is not None:
            return self.data_parquet_sender.get_send_fps()
        return None

    def get_recv_fps(self) -> pd.Series | None:
        if self.data_parquet_receiver is not None:
            return self.data_parquet_receiver.get_recv_fps()
        return None

    def get_icmp_pings(self) -> pd.Series | None:
        if self.data_icmp_sender is None:
            self.__load_icmp_ping_files()
        if self.data_icmp_sender is not None:
            return self.data_icmp_sender.get_icmp_pings()
        return None

    def get_probe_timestamps(self) -> pd.Series | None:
        if self.data_probes_sender is not None:
            return self.data_probes_sender.get_probe_timestamps()
        return None

    def get_guard_trigger_timestamps(self) -> pd.Series | None:
        if self.data_guard_triggers_sender is not None:
            return self.data_guard_triggers_sender.get_guard_trigger_timestamps()
        return None

    def get_freeze_times(self) -> pd.Series | None:
        if self.data_parquet_receiver is not None:
            freeze_times = self.data_parquet_receiver.get_freeze_times()
            if freeze_times is not None:
                return freeze_times
        return None

    def get_total_freeze_duration(self) -> float | None:
        if self.data_parquet_receiver is not None:
            total_freeze = self.data_parquet_receiver.get_total_freeze_duration()
            if total_freeze is not None:
                return total_freeze
        return None

    def get_freeze_durations_seconds(self, fps_threshold: float = 0.5, min_freeze_duration_s: int = 1) -> list[float] | None:
        """Return a list of freeze durations (in seconds) based on recv FPS.

        A freeze is defined as one or more consecutive 1-second intervals where the receive FPS
        is less than or equal to fps_threshold. Each run of such intervals becomes one freeze event.
        Only freeze events with duration >= min_freeze_duration_s are returned.
        If no receive FPS is available, attempts to fall back to send FPS. Returns None if neither exists.
        """
        fps_series = self.get_recv_fps()
        if fps_series is None:
            fps_series = self.get_send_fps()
        if fps_series is None or fps_series.empty:
            return None

        durations: list[float] = []
        run_length = 0
        for _, fps in fps_series.items():
            if fps <= fps_threshold:
                run_length += 1
            else:
                if run_length >= min_freeze_duration_s:
                    durations.append(float(run_length))
                run_length = 0
        # Handle trailing freeze at end of series
        if run_length >= min_freeze_duration_s:
            durations.append(float(run_length))
        return durations

    def __load_dishy_files(self):
        sender_path = os.path.join(self.folder_path, "dishy_sender.json")
        receiver_path = os.path.join(self.folder_path, "dishy_receiver.json")
        if os.path.exists(sender_path):
            self.data_dishy_sender = dishy_from_file(sender_path)
        if os.path.exists(receiver_path):
            self.data_dishy_receiver = dishy_from_file(receiver_path)

    def __load_iperf_files(self):
        receiver_path = os.path.join(self.folder_path, "iperf-receiver.json")
        if os.path.exists(receiver_path):
            self.data_iperf_receiver = iperf_from_file(receiver_path)
        sender_path = os.path.join(self.folder_path, "iperf-sender.json")
        if os.path.exists(sender_path):
            self.data_iperf_sender = iperf_from_file(sender_path)

    def __load_irtt_files(self):
        path = os.path.join(self.folder_path, "irtt-sender.json")
        if os.path.exists(path):
            self.data_irtt = irtt_from_file(path)

    def __load_parquet_files(self):
        sender_path = os.path.join(self.folder_path, "sender.parquet")
        receiver_path = os.path.join(self.folder_path, "receiver.parquet")
        if os.path.exists(sender_path):
            self.data_parquet_sender = parquet_from_file(sender_path)
        if os.path.exists(receiver_path):
            self.data_parquet_receiver = parquet_from_file(receiver_path)

    def __load_icmp_ping_files(self):
        sender_path = os.path.join(self.folder_path, "icmp-sender.json")
        if os.path.exists(sender_path):
            self.data_icmp_sender = icmp_ping_from_json(sender_path)
            return
        sender_path = os.path.join(self.folder_path, "icmp_sender.json")
        if os.path.exists(sender_path):
            self.data_icmp_sender = icmp_ping_from_json(sender_path)

    def __load_probes_files(self):
        sender_path = os.path.join(self.folder_path, "probes.json")
        if os.path.exists(sender_path):
            self.data_probes_sender = probes_from_file(sender_path)

    def __load_guard_trigger_files(self):
        sender_path = os.path.join(self.folder_path, "guard_triggers.json")
        if os.path.exists(sender_path):
            self.data_guard_triggers_sender = guard_triggers_from_file(sender_path)

    def __load_weather_data(self):
        weather_path = os.path.join(self.folder_path, "weather.html")
        if os.path.exists(weather_path):
            self.weather_data = weather_data_from_file(weather_path)