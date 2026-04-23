from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from models.spectral_models import EvidenceBundleManifest, SpectralRunResult, WindowSpectralResult


class EvidenceExporter:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.exports_root = self.runtime_root / "exports" / "evidence"
        self.exports_root.mkdir(parents=True, exist_ok=True)

    def export_spectral_qc_evidence(
        self,
        *,
        run_result: SpectralRunResult,
        config_snapshot: dict,
        project: object,
        site: object,
    ) -> EvidenceBundleManifest:
        timestamp = datetime.now()
        export_root = self.exports_root / f"spectral_qc_{timestamp:%Y%m%d_%H%M%S}"
        export_root.mkdir(parents=True, exist_ok=True)

        summary_path = export_root / "summary.json"
        config_path = export_root / "current_config_snapshot.json"
        project_site_path = export_root / "project_site_snapshot.json"
        qc_windows_path = export_root / "qc_windows.csv"

        _write_json(
            summary_path,
            {
                "run_id": run_result.run_id,
                "created_at": run_result.created_at.isoformat(),
                "data_source": run_result.data_source,
                "time_range": run_result.time_range,
                "qc_only": run_result.qc_only,
                "summary": run_result.summary,
                "window_count": len(run_result.windows),
            },
        )
        _write_json(config_path, config_snapshot)
        _write_json(project_site_path, {"project": _to_jsonable(project), "site": _to_jsonable(site)})
        _write_csv(qc_windows_path, [_window_to_row(window) for window in run_result.windows])

        manifest = EvidenceBundleManifest(
            bundle_id=f"bundle_{timestamp:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}",
            export_time=timestamp,
            root_dir=str(export_root),
            included_files=[
                str(export_root / "manifest.json"),
                str(summary_path),
                str(qc_windows_path),
                str(config_path),
                str(project_site_path),
            ],
            summary_text=f"Exported {len(run_result.windows)} QC windows for spectral run {run_result.run_id}.",
        )
        manifest_payload = manifest.to_dict()
        manifest_payload["run_id"] = run_result.run_id
        _write_json(export_root / "manifest.json", manifest_payload)
        return manifest


def _window_to_row(window: WindowSpectralResult) -> dict[str, object]:
    return {
        "window_id": window.window_id,
        "start_time": window.start_time.isoformat(),
        "end_time": window.end_time.isoformat(),
        "qc_grade": window.qc_grade,
        "anomaly_type": window.anomaly_type,
        "lag_seconds": window.lag_seconds,
        "lag_confidence": window.lag_confidence,
        "correction_factor": window.correction_factor,
        "high_freq_loss_risk": window.high_freq_loss_risk,
        "reason": window.reason,
        "qc_band_value": window.qc_band_value,
    }


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "window_id",
        "start_time",
        "end_time",
        "qc_grade",
        "anomaly_type",
        "lag_seconds",
        "lag_confidence",
        "correction_factor",
        "high_freq_loss_risk",
        "reason",
        "qc_band_value",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)
    return path


def _to_jsonable(payload: object) -> object:
    if is_dataclass(payload):
        return _to_jsonable(asdict(payload))
    if isinstance(payload, dict):
        return {key: _to_jsonable(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, datetime):
        return payload.isoformat()
    if isinstance(payload, Path):
        return str(payload)
    return payload
