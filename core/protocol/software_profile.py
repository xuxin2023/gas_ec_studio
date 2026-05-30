from __future__ import annotations

from dataclasses import dataclass

from core.protocol.gas_analyzer_profiles import get_gas_analyzer_profile


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
    gas_analyzer_profile_id: str = "ygas_irga"

    @classmethod
    def standard(cls) -> "SoftwareProfile":
        return cls(name="standard", label="YGAS standard firmware", gas_analyzer_profile_id="ygas_irga")

    @classmethod
    def for_analyzer_profile(cls, profile_id: str | None) -> "SoftwareProfile":
        analyzer = get_gas_analyzer_profile(profile_id)
        return cls(
            name=analyzer.profile_id,
            label=analyzer.label,
            default_mode=analyzer.default_mode,
            default_active_send=analyzer.default_active_send,
            command_prefix=analyzer.command_prefix or "YGAS",
            gas_analyzer_profile_id=analyzer.profile_id,
        )

    @classmethod
    def legacy_mode1(cls) -> "SoftwareProfile":
        return cls(
            name="legacy_mode1",
            label="兼容型固件",
            default_mode=1,
            default_active_send=False,
            active_read_window_s=0.35,
            passive_read_window_s=0.35,
            gas_analyzer_profile_id="ygas_irga",
        )
