from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class WindowCompareResult:
    window_key: str
    start_time: datetime | None
    end_time: datetime | None
    current_lag_seconds: float | None = None
    reference_lag_seconds: float | None = None
    lag_delta: float | None = None
    current_flux: float | None = None
    reference_flux: float | None = None
    flux_delta: float | None = None
    current_correction_factor: float | None = None
    reference_correction_factor: float | None = None
    correction_factor_delta: float | None = None
    current_qc_grade: str | None = None
    reference_qc_grade: str | None = None
    qc_match: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat() if self.start_time else None
        payload["end_time"] = self.end_time.isoformat() if self.end_time else None
        return payload


@dataclass(slots=True)
class EddyProCompareResult:
    compare_id: str
    created_at: datetime
    current_source: dict[str, Any] = field(default_factory=dict)
    reference_source: dict[str, Any] = field(default_factory=dict)
    summary_metrics: dict[str, Any] = field(default_factory=dict)
    window_results: list[WindowCompareResult] = field(default_factory=list)
    risk_summary: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compare_id": self.compare_id,
            "created_at": self.created_at.isoformat(),
            "current_source": _serialize(self.current_source),
            "reference_source": _serialize(self.reference_source),
            "summary_metrics": _serialize(self.summary_metrics),
            "window_results": [window.to_dict() for window in self.window_results],
            "risk_summary": list(self.risk_summary),
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class WindowAttributionResult:
    window_key: str
    dominant_cause: str
    secondary_causes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_key": self.window_key,
            "dominant_cause": self.dominant_cause,
            "secondary_causes": list(self.secondary_causes),
            "confidence": float(self.confidence),
            "evidence": list(self.evidence),
            "recommendation": self.recommendation,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class CompareAttributionResult:
    attribution_id: str
    created_at: datetime
    compare_id: str
    dominant_causes: list[str] = field(default_factory=list)
    secondary_causes: list[str] = field(default_factory=list)
    risk_level: str = "中"
    summary_text: str = ""
    notes: list[str] = field(default_factory=list)
    window_attributions: list[WindowAttributionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribution_id": self.attribution_id,
            "created_at": self.created_at.isoformat(),
            "compare_id": self.compare_id,
            "dominant_causes": list(self.dominant_causes),
            "secondary_causes": list(self.secondary_causes),
            "risk_level": self.risk_level,
            "summary_text": self.summary_text,
            "notes": list(self.notes),
            "window_attributions": [window.to_dict() for window in self.window_attributions],
        }
