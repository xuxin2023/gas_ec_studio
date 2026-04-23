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


@dataclass(slots=True)
class WindowSpectralResult:
    window_id: str
    start_time: datetime
    end_time: datetime
    qc_grade: str
    anomaly_type: str
    lag_seconds: float
    lag_confidence: float
    correction_factor: float
    high_freq_loss_risk: str
    reason: str
    lag_curve_x: list[float] = field(default_factory=list)
    lag_curve_y: list[float] = field(default_factory=list)
    power_freq: list[float] = field(default_factory=list)
    power_measured: list[float] = field(default_factory=list)
    power_ref: list[float] = field(default_factory=list)
    cross_freq: list[float] = field(default_factory=list)
    cross_value: list[float] = field(default_factory=list)
    ogive_freq: list[float] = field(default_factory=list)
    ogive_value: list[float] = field(default_factory=list)
    qc_band_value: float = 0.0
    transfer_freq: list[float] = field(default_factory=list)
    transfer_value: list[float] = field(default_factory=list)
    transfer_function_components: dict[str, Any] = field(default_factory=dict)
    correction_factor_components: dict[str, float] = field(default_factory=dict)
    total_transfer_function_freq: list[float] = field(default_factory=list)
    total_transfer_function_value: list[float] = field(default_factory=list)
    effective_cutoff_info: dict[str, Any] = field(default_factory=dict)
    correction_factor_detail: dict[str, Any] = field(default_factory=dict)
    provenance_notes: list[str] = field(default_factory=list)
    model_version: str = "fcc_transfer_components_v1"
    corrected_flux_before: float = 0.0
    corrected_flux_after: float = 0.0
    sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        payload["end_time"] = self.end_time.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WindowSpectralResult:
        return cls(
            window_id=str(payload["window_id"]),
            start_time=_parse_datetime(payload["start_time"]),
            end_time=_parse_datetime(payload["end_time"]),
            qc_grade=str(payload["qc_grade"]),
            anomaly_type=str(payload["anomaly_type"]),
            lag_seconds=float(payload["lag_seconds"]),
            lag_confidence=float(payload["lag_confidence"]),
            correction_factor=float(payload["correction_factor"]),
            high_freq_loss_risk=str(payload["high_freq_loss_risk"]),
            reason=str(payload["reason"]),
            lag_curve_x=[float(item) for item in payload.get("lag_curve_x", [])],
            lag_curve_y=[float(item) for item in payload.get("lag_curve_y", [])],
            power_freq=[float(item) for item in payload.get("power_freq", [])],
            power_measured=[float(item) for item in payload.get("power_measured", [])],
            power_ref=[float(item) for item in payload.get("power_ref", [])],
            cross_freq=[float(item) for item in payload.get("cross_freq", [])],
            cross_value=[float(item) for item in payload.get("cross_value", [])],
            ogive_freq=[float(item) for item in payload.get("ogive_freq", [])],
            ogive_value=[float(item) for item in payload.get("ogive_value", [])],
            qc_band_value=float(payload.get("qc_band_value", 0.0)),
            transfer_freq=[float(item) for item in payload.get("transfer_freq", [])],
            transfer_value=[float(item) for item in payload.get("transfer_value", [])],
            transfer_function_components=dict(payload.get("transfer_function_components", {})),
            correction_factor_components={
                key: float(value) for key, value in payload.get("correction_factor_components", {}).items()
            },
            total_transfer_function_freq=[float(item) for item in payload.get("total_transfer_function_freq", [])],
            total_transfer_function_value=[float(item) for item in payload.get("total_transfer_function_value", [])],
            effective_cutoff_info=dict(payload.get("effective_cutoff_info", {})),
            correction_factor_detail=dict(payload.get("correction_factor_detail", {})),
            provenance_notes=[str(item) for item in payload.get("provenance_notes", [])],
            model_version=str(payload.get("model_version", "fcc_transfer_components_v1")),
            corrected_flux_before=float(payload.get("corrected_flux_before", 0.0)),
            corrected_flux_after=float(payload.get("corrected_flux_after", 0.0)),
            sample_count=int(payload.get("sample_count", 0)),
        )


@dataclass(slots=True)
class SpectralRunResult:
    run_id: str
    created_at: datetime
    data_source: str
    time_range: str
    qc_only: bool
    summary: dict[str, Any] = field(default_factory=dict)
    windows: list[WindowSpectralResult] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "data_source": self.data_source,
            "time_range": self.time_range,
            "qc_only": self.qc_only,
            "summary": _serialize(self.summary),
            "windows": [window.to_dict() for window in self.windows],
            "artifacts": _serialize(self.artifacts),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SpectralRunResult:
        return cls(
            run_id=str(payload["run_id"]),
            created_at=_parse_datetime(payload["created_at"]),
            data_source=str(payload["data_source"]),
            time_range=str(payload["time_range"]),
            qc_only=bool(payload["qc_only"]),
            summary=dict(payload.get("summary", {})),
            windows=[WindowSpectralResult.from_dict(item) for item in payload.get("windows", [])],
            artifacts=dict(payload.get("artifacts", {})),
        )


@dataclass(slots=True)
class EvidenceBundleManifest:
    bundle_id: str
    export_time: datetime
    root_dir: str
    included_files: list[str] = field(default_factory=list)
    summary_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "export_time": self.export_time.isoformat(),
            "root_dir": self.root_dir,
            "included_files": list(self.included_files),
            "summary_text": self.summary_text,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvidenceBundleManifest:
        return cls(
            bundle_id=str(payload["bundle_id"]),
            export_time=_parse_datetime(payload["export_time"]),
            root_dir=str(payload["root_dir"]),
            included_files=[str(item) for item in payload.get("included_files", [])],
            summary_text=str(payload.get("summary_text", "")),
        )


@dataclass(slots=True)
class BatchCompareResult:
    current_batch: str
    compare_batch: str
    metric_deltas: dict[str, float] = field(default_factory=dict)
    difference_summary: list[str] = field(default_factory=list)
    changed_windows: list[dict[str, Any]] = field(default_factory=list)
    risk_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_batch": self.current_batch,
            "compare_batch": self.compare_batch,
            "metric_deltas": {key: float(value) for key, value in self.metric_deltas.items()},
            "difference_summary": list(self.difference_summary),
            "changed_windows": _serialize(self.changed_windows),
            "risk_summary": list(self.risk_summary),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BatchCompareResult:
        return cls(
            current_batch=str(payload["current_batch"]),
            compare_batch=str(payload["compare_batch"]),
            metric_deltas={key: float(value) for key, value in payload.get("metric_deltas", {}).items()},
            difference_summary=[str(item) for item in payload.get("difference_summary", [])],
            changed_windows=[dict(item) for item in payload.get("changed_windows", [])],
            risk_summary=[str(item) for item in payload.get("risk_summary", [])],
        )
