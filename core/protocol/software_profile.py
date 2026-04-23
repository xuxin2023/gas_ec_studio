from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SoftwareProfile:
    name: str
    label: str
    default_mode: int = 2
    default_active_send: bool = False
    command_prefix: str = "YGAS"
    command_terminator: str = "\r\n"
    active_read_window_s: float = 0.25
    passive_read_window_s: float = 0.3

    @classmethod
    def standard(cls) -> "SoftwareProfile":
        return cls(name="standard", label="标准固件")

    @classmethod
    def legacy_mode1(cls) -> "SoftwareProfile":
        return cls(
            name="legacy_mode1",
            label="兼容型固件",
            default_mode=1,
            default_active_send=False,
            active_read_window_s=0.35,
            passive_read_window_s=0.35,
        )
