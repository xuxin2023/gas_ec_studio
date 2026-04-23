from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class FrameQuality(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    TRUNCATED = "TRUNCATED"
    CORRUPTED = "CORRUPTED"
    ACK_ONLY = "ACK_ONLY"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class ProtocolFrame:
    received_at: datetime
    raw_text: str
    source: str
    quality: FrameQuality
    device_id: str | None = None
    mode: int | None = None
    parsed: dict[str, Any] = field(default_factory=dict)
    status_text: str | None = None
    is_ack: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["received_at"] = self.received_at.isoformat()
        payload["quality"] = self.quality.value
        return payload

    def summary(self) -> str:
        if self.is_ack:
            return f"{self.device_id or '---'} ACK"
        if self.mode:
            co2 = self.parsed.get("co2_ppm")
            h2o = self.parsed.get("h2o_mmol")
            pressure = self.parsed.get("pressure_kpa")
            return (
                f"{self.device_id or '---'} M{self.mode} "
                f"CO2={co2 if co2 is not None else '--'} ppm "
                f"H2O={h2o if h2o is not None else '--'} mmol "
                f"P={pressure if pressure is not None else '--'} kPa"
            )
        return self.raw_text[:120]


@dataclass(slots=True)
class NormalizedHFFrame:
    timestamp: datetime
    device_uid: str
    device_id: str
    mode: int
    frame_quality: FrameQuality
    co2_ppm: float | None
    h2o_mmol: float | None
    pressure_kpa: float | None
    chamber_temp_c: float | None = None
    case_temp_c: float | None = None
    status_text: str | None = None
    raw_text: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "device_uid": self.device_uid,
            "device_id": self.device_id,
            "mode": self.mode,
            "frame_quality": self.frame_quality.value,
            "co2_ppm": self.co2_ppm,
            "h2o_mmol": self.h2o_mmol,
            "pressure_kpa": self.pressure_kpa,
            "chamber_temp_c": self.chamber_temp_c,
            "case_temp_c": self.case_temp_c,
            "status_text": self.status_text,
            "raw_text": self.raw_text,
        }
