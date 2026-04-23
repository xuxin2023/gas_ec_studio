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


def _parse_datetime(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


@dataclass(slots=True)
class WindowRPResult:
    window_id: str
    start_time: datetime
    end_time: datetime
    sample_count: int
    valid_sample_count: int
    continuity_ratio: float
    missing_ratio: float
    rotation_mode: str
    detrend_mode: str
    lag_seconds: float
    lag_confidence: float
    cov_w_co2: float
    cov_w_h2o: float
    raw_flux: float
    mixing_ratio_flux: float
    density_corrected_flux: float
    water_vapor_flux: float
    air_molar_density: float
    dry_air_molar_density: float
    mean_co2_ppm: float
    mean_h2o_mmol: float
    mean_pressure_kpa: float
    mean_temp_c: float
    qc_grade: str
    anomaly_type: str
    reason: str
    primary_flux: float = 0.0
    primary_flux_source: str = ""
    qc_score: float = 0.0
    stationarity_score: float | None = None
    turbulence_score: float | None = None
    ustar: float | None = None
    qc_matrix: dict[str, Any] = field(default_factory=dict)
    qc_flags: list[str] = field(default_factory=list)
    qc_reasons: list[str] = field(default_factory=list)
    stationarity_detail: dict[str, Any] = field(default_factory=dict)
    turbulence_detail: dict[str, Any] = field(default_factory=dict)
    uncertainty_detail: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        payload["end_time"] = self.end_time.isoformat()
        payload["diagnostics"] = _serialize(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WindowRPResult:
        return cls(
            window_id=str(payload["window_id"]),
            start_time=_parse_datetime(payload["start_time"]),
            end_time=_parse_datetime(payload["end_time"]),
            sample_count=int(payload.get("sample_count", 0)),
            valid_sample_count=int(payload.get("valid_sample_count", 0)),
            continuity_ratio=float(payload.get("continuity_ratio", 0.0)),
            missing_ratio=float(payload.get("missing_ratio", 0.0)),
            rotation_mode=str(payload.get("rotation_mode", "none")),
            detrend_mode=str(payload.get("detrend_mode", "block_mean")),
            lag_seconds=float(payload.get("lag_seconds", 0.0)),
            lag_confidence=float(payload.get("lag_confidence", 0.0)),
            cov_w_co2=float(payload.get("cov_w_co2", 0.0)),
            cov_w_h2o=float(payload.get("cov_w_h2o", 0.0)),
            raw_flux=float(payload.get("raw_flux", 0.0)),
            mixing_ratio_flux=float(payload.get("mixing_ratio_flux", 0.0)),
            density_corrected_flux=float(payload.get("density_corrected_flux", 0.0)),
            water_vapor_flux=float(payload.get("water_vapor_flux", 0.0)),
            air_molar_density=float(payload.get("air_molar_density", 0.0)),
            dry_air_molar_density=float(payload.get("dry_air_molar_density", 0.0)),
            mean_co2_ppm=float(payload.get("mean_co2_ppm", 0.0)),
            mean_h2o_mmol=float(payload.get("mean_h2o_mmol", 0.0)),
            mean_pressure_kpa=float(payload.get("mean_pressure_kpa", 0.0)),
            mean_temp_c=float(payload.get("mean_temp_c", 0.0)),
            qc_score=float(payload.get("qc_score", 0.0)),
            stationarity_score=_parse_optional_float(payload.get("stationarity_score")),
            turbulence_score=_parse_optional_float(payload.get("turbulence_score")),
            ustar=_parse_optional_float(payload.get("ustar")),
            qc_grade=str(payload.get("qc_grade", "C")),
            anomaly_type=str(payload.get("anomaly_type", "unknown")),
            reason=str(payload.get("reason", "")),
            primary_flux=float(payload.get("primary_flux", 0.0)),
            primary_flux_source=str(payload.get("primary_flux_source", "")),
            qc_matrix=dict(payload.get("qc_matrix", {})),
            qc_flags=[str(item) for item in payload.get("qc_flags", [])],
            qc_reasons=[str(item) for item in payload.get("qc_reasons", [])],
            stationarity_detail=dict(payload.get("stationarity_detail", {})),
            turbulence_detail=dict(payload.get("turbulence_detail", {})),
            uncertainty_detail=dict(payload.get("uncertainty_detail", {})),
            diagnostics=dict(payload.get("diagnostics", {})),
        )


@dataclass(slots=True)
class EddyProReferenceWindow:
    window_id: str
    start_time: str
    end_time: str
    primary_flux: float | None = None
    primary_flux_source: str = ""
    lag_seconds: float | None = None
    lag_strategy: str = ""
    rotation_mode: str = ""
    applied_rotation_impl: str = ""
    wpl_water_vapor_term: float | None = None
    wpl_sensible_heat_term: float | None = None
    total_density_correction: float | None = None
    qc_grade: str = ""
    qc_score: float | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EddyProReferenceWindow:
        return cls(
            window_id=str(payload.get("window_id", "")),
            start_time=str(payload.get("start_time", "")),
            end_time=str(payload.get("end_time", "")),
            primary_flux=_parse_optional_float(payload.get("primary_flux")),
            primary_flux_source=str(payload.get("primary_flux_source", "")),
            lag_seconds=_parse_optional_float(payload.get("lag_seconds")),
            lag_strategy=str(payload.get("lag_strategy", "")),
            rotation_mode=str(payload.get("rotation_mode", "")),
            applied_rotation_impl=str(payload.get("applied_rotation_impl", "")),
            wpl_water_vapor_term=_parse_optional_float(payload.get("wpl_water_vapor_term")),
            wpl_sensible_heat_term=_parse_optional_float(payload.get("wpl_sensible_heat_term")),
            total_density_correction=_parse_optional_float(payload.get("total_density_correction")),
            qc_grade=str(payload.get("qc_grade", "")),
            qc_score=_parse_optional_float(payload.get("qc_score")),
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class BenchmarkFieldComparison:
    field_name: str
    reference_value: float | None
    actual_value: float | None
    absolute_error: float | None
    relative_error: float | None
    threshold: float
    passed: bool
    note: str


@dataclass(slots=True)
class BenchmarkWindowResult:
    window_id: str
    comparisons: list[BenchmarkFieldComparison] = field(default_factory=list)
    overall_pass: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "comparisons": [
                {
                    "field_name": c.field_name,
                    "reference_value": c.reference_value,
                    "actual_value": c.actual_value,
                    "absolute_error": c.absolute_error,
                    "relative_error": c.relative_error,
                    "threshold": c.threshold,
                    "passed": c.passed,
                    "note": c.note,
                }
                for c in self.comparisons
            ],
            "overall_pass": self.overall_pass,
            "notes": self.notes,
        }


@dataclass(slots=True)
class RPRunResult:
    run_id: str
    created_at: datetime
    data_source: str
    time_range: str
    summary: dict[str, Any] = field(default_factory=dict)
    windows: list[WindowRPResult] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "data_source": self.data_source,
            "time_range": self.time_range,
            "summary": _serialize(self.summary),
            "windows": [window.to_dict() for window in self.windows],
            "artifacts": _serialize(self.artifacts),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RPRunResult:
        return cls(
            run_id=str(payload["run_id"]),
            created_at=_parse_datetime(payload["created_at"]),
            data_source=str(payload.get("data_source", "")),
            time_range=str(payload.get("time_range", "")),
            summary=dict(payload.get("summary", {})),
            windows=[WindowRPResult.from_dict(item) for item in payload.get("windows", [])],
            artifacts=dict(payload.get("artifacts", {})),
        )
