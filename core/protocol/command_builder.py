from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.protocol.software_profile import SoftwareProfile


def normalize_device_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError("设备 ID 不能为空")
    if text == "FFF":
        return text
    if text.isdigit():
        return f"{int(text):03d}"
    return text


def _require_int_range(name: str, value: Any, min_value: int, max_value: int) -> int:
    number = int(value)
    if not (min_value <= number <= max_value):
        raise ValueError(f"{name} must be between {min_value} and {max_value}.")
    return number


def _require_float_range(name: str, value: Any, min_value: float, max_value: float) -> float:
    number = float(value)
    if not (min_value <= number <= max_value):
        raise ValueError(f"{name} must be between {min_value:g} and {max_value:g}.")
    return number


@dataclass(slots=True)
class CommandBuilder:
    profile: SoftwareProfile

    def _build(self, command: str, target_id: str, *args: Any) -> str:
        normalized_target = normalize_device_id(target_id)
        parts = [command, self.profile.command_prefix, normalized_target]
        parts.extend(str(arg) for arg in args)
        return ",".join(parts) + self.profile.command_terminator

    def query_comm_params(self, *, target_id: str) -> str:
        return self._build("SETCOM", target_id)

    def set_comm_params(
        self,
        *,
        target_id: str,
        baudrate: int,
        data_bits: int = 8,
        parity: str = "N",
        stop_bits: int = 1,
    ) -> str:
        allowed_baudrates = {1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200}
        normalized_baud = int(baudrate)
        if normalized_baud not in allowed_baudrates:
            raise ValueError("baudrate must be one of 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200.")
        normalized_data_bits = _require_int_range("data_bits", data_bits, 7, 8)
        normalized_parity = str(parity or "N").strip().upper()
        if normalized_parity not in {"N", "E", "O"}:
            raise ValueError("parity must be N, E, or O.")
        normalized_stop_bits = _require_int_range("stop_bits", stop_bits, 1, 2)
        return self._build("SETCOM", target_id, normalized_baud, normalized_data_bits, normalized_parity, normalized_stop_bits)

    def read_frame(self, *, target_id: str) -> str:
        return self._build("READDATA", target_id)

    def set_mode(self, mode: int, *, target_id: str) -> str:
        return self._build("MODE", target_id, _require_int_range("mode", mode, 1, 3))

    def query_mode(self, *, target_id: str) -> str:
        return self._build("MODE", target_id)

    def set_comm_way(self, active_send: bool, *, target_id: str) -> str:
        return self._build("SETCOMWAY", target_id, 1 if active_send else 0)

    def query_comm_way(self, *, target_id: str) -> str:
        return self._build("SETCOMWAY", target_id)

    def set_ftd_frequency(self, hz: int, *, target_id: str) -> str:
        return self._build("FTD", target_id, _require_int_range("hz", hz, 1, 20))

    def query_ftd_frequency(self, *, target_id: str) -> str:
        return self._build("FTD", target_id)

    def set_average(self, channel: int, value: int, *, target_id: str) -> str:
        normalized_channel = _require_int_range("channel", channel, 1, 2)
        return self._build(f"AVERAGE{normalized_channel}", target_id, _require_int_range("average", value, 1, 399))

    def query_average(self, channel: int, *, target_id: str) -> str:
        normalized_channel = _require_int_range("channel", channel, 1, 2)
        return self._build(f"AVERAGE{normalized_channel}", target_id)

    def set_filter(self, window_n: int, *, target_id: str) -> str:
        return self._build("AVERAGE", target_id, _require_int_range("filter_window", window_n, 1, 399))

    def query_filter(self, *, target_id: str) -> str:
        return self._build("AVERAGE", target_id)

    def read_coefficients(self, group_index: int, *, target_id: str) -> str:
        return self._build("GETCO", target_id, _require_int_range("group_index", group_index, 1, 9))

    def write_coefficients(self, group_index: int, values: list[float], *, target_id: str) -> str:
        normalized_group = _require_int_range("group_index", group_index, 1, 9)
        return self._build(f"SENCO{normalized_group}", target_id, *values)

    def clear_coefficients(self, group_index: int, *, target_id: str) -> str:
        normalized_group = _require_int_range("group_index", group_index, 1, 9)
        return self._build(f"CLEARSENCO{normalized_group}", target_id)

    def write_device_id(self, new_device_id: str, *, target_id: str = "FFF") -> str:
        return self._build("ID", target_id, normalize_device_id(new_device_id))

    def query_device_id(self, *, target_id: str = "FFF") -> str:
        return self._build("ID", target_id)

    def reset_device(self, *, target_id: str) -> str:
        return self._build("RESET", target_id)

    def set_lamp_power_mv(self, value_mv: int, *, target_id: str) -> str:
        return self._build("SETPOW", target_id, f"{_require_int_range('lamp_power_mv', value_mv, 0, 3000):04d}")

    def query_lamp_power_mv(self, *, target_id: str) -> str:
        return self._build("SETPOW", target_id)

    def capture_illumination_reference(self, *, target_id: str = "FFF") -> str:
        return self._build("SETILLUM", target_id)

    def set_reference_signal_mv(self, value_mv: int, *, target_id: str) -> str:
        return self._build("SETCO2", target_id, f"{_require_int_range('reference_signal_mv', value_mv, 100, 4000):04d}")

    def query_reference_signal_mv(self, *, target_id: str) -> str:
        return self._build("SETCO2", target_id)

    def set_timeout_compensation(self, value: int, *, target_id: str) -> str:
        return self._build("TIMEOUT", target_id, _require_int_range("timeout_compensation", value, 900, 1100))

    def query_timeout_compensation(self, *, target_id: str) -> str:
        return self._build("TIMEOUT", target_id)

    def set_calibration_temperature(self, channel: int, temp_c: float, *, target_id: str) -> str:
        normalized_channel = _require_int_range("channel", channel, 1, 2)
        normalized_temp = _require_float_range("temp_c", temp_c, -20.0, 40.0)
        return self._build(f"SENTEMP{normalized_channel}", target_id, f"{normalized_temp:.1f}")

    def query_calibration_temperature(self, channel: int, *, target_id: str) -> str:
        normalized_channel = _require_int_range("channel", channel, 1, 2)
        return self._build(f"SENTEMP{normalized_channel}", target_id)

    def broadcast_probe(self) -> str:
        return self.query_device_id(target_id="FFF")
