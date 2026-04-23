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


@dataclass(slots=True)
class CommandBuilder:
    profile: SoftwareProfile

    def _build(self, command: str, target_id: str, *args: Any) -> str:
        normalized_target = normalize_device_id(target_id)
        parts = [command, self.profile.command_prefix, normalized_target]
        parts.extend(str(arg) for arg in args)
        return ",".join(parts) + self.profile.command_terminator

    def read_frame(self, *, target_id: str) -> str:
        return self._build("READDATA", target_id)

    def set_mode(self, mode: int, *, target_id: str) -> str:
        return self._build("MODE", target_id, int(mode))

    def set_comm_way(self, active_send: bool, *, target_id: str) -> str:
        return self._build("SETCOMWAY", target_id, 1 if active_send else 0)

    def set_ftd_frequency(self, hz: int, *, target_id: str) -> str:
        return self._build("FTD", target_id, int(hz))

    def set_average(self, channel: int, value: int, *, target_id: str) -> str:
        return self._build(f"AVERAGE{int(channel)}", target_id, int(value))

    def set_filter(self, window_n: int, *, target_id: str) -> str:
        return self._build("FILTER", target_id, int(window_n))

    def read_coefficients(self, group_index: int, *, target_id: str) -> str:
        return self._build("GETCO", target_id, int(group_index))

    def write_coefficients(self, group_index: int, values: list[float], *, target_id: str) -> str:
        return self._build(f"SENCO{int(group_index)}", target_id, *values)

    def write_device_id(self, new_device_id: str, *, target_id: str = "FFF") -> str:
        return self._build("ID", target_id, normalize_device_id(new_device_id))

    def broadcast_probe(self) -> str:
        return self._build("PING", "FFF")
