from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.acquisition.runtime_service import run_runtime_service_batches
from core.exports.delivery_exporter import export_delivery_package
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, start: datetime | None = None, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = start or datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.7 + 0.22 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.22 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.48 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.07 * np.cos(2.0 * np.pi * 0.62 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.8 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 3) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="service-demo",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.5,
                case_temp_c=24.4,
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def _metadata() -> MetadataBundle:
    return MetadataBundle(
        project=ProjectProfile(code="SVC-001", name="Runtime Service"),
        site=SiteProfile(station_code="SVC", station_name="Service Tower"),
    )


def _config() -> dict:
    return {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "clock_sync": {
            "enabled": True,
            "clock_source": "GPS+PTP",
            "offset_seconds": 0.1,
        },
        "runtime_profile": {
            "profile_id": "smartflux_watchdog_v1",
            "expected_sample_hz": 10.0,
            "max_gap_seconds": 0.5,
            "min_window_count": 1,
            "require_clock_sync": True,
        },
        "runtime_service": {
            "service_id": "smartflux_runtime_service_v1",
            "restart_policy": "retry_failed_batch_once",
            "max_consecutive_failures": 3,
            "max_queue_depth": 4,
        },
        "network_output": {
            "schema_target": "FLUXNET",
            "timezone_offset_hours": 0.0,
            "timestamp_refers_to": "start",
            "gap_fill_value": -9999.0,
        },
    }


def test_runtime_service_runs_queued_headless_batches(tmp_path: Path) -> None:
    service = run_runtime_service_batches(
        config=_config(),
        metadata=_metadata(),
        batches=[
            {"input_id": "ok-1", "rows": _make_rows(), "time_range": "ok-1"},
            {"input_id": "ok-2", "rows": _make_rows(start=datetime(2026, 5, 22, 10, 30, 0)), "time_range": "ok-2"},
        ],
        runtime_root=tmp_path,
    )
    manifest = service["service_manifest"]
    latest = service["latest_batch"]
    rp_result = latest["rp_result"]

    assert manifest["status"] == "pass"
    assert manifest["delivery_state"] == "ready"
    assert manifest["batch_count"] == 2
    assert len(manifest["heartbeats"]) == 2
    assert manifest["host_telemetry"]["disk_status"] in {"ok", "warn", "unknown"}
    assert rp_result.summary["runtime_service_status"] == "pass"
    assert rp_result.artifacts["runtime_service"]["service_id"] == "smartflux_runtime_service_v1"
    assert rp_result.windows[0].diagnostics["runtime_service_status"] == "pass"
    assert rp_result.windows[0].diagnostics["runtime_service_delivery_state"] == "ready"


def test_runtime_service_quarantines_bad_input_and_records_retry(tmp_path: Path) -> None:
    service = run_runtime_service_batches(
        config=_config(),
        metadata=_metadata(),
        batches=[
            {"input_id": "bad-rows", "rows": None, "time_range": "bad"},
            {"input_id": "ok-after", "rows": _make_rows(start=datetime(2026, 5, 22, 11, 0, 0)), "time_range": "ok"},
        ],
        runtime_root=tmp_path,
    )
    manifest = service["service_manifest"]

    assert manifest["status"] == "degraded"
    assert manifest["delivery_state"] == "degraded_review_required"
    assert manifest["failure_count"] == 1
    assert len(manifest["restart_records"]) == 1
    assert len(manifest["quarantine_records"]) == 1
    assert manifest["batch_records"][0]["status"] == "failed"
    assert manifest["batch_records"][1]["status"] == "ok"
    assert service["latest_batch"]["rp_result"].summary["runtime_service_status"] == "degraded"


def test_runtime_service_export_and_delivery_chain(tmp_path: Path) -> None:
    metadata = _metadata()
    config = _config()
    service = run_runtime_service_batches(
        config=config,
        metadata=metadata,
        batches=[{"input_id": "ok-1", "rows": _make_rows(), "time_range": "ok-1"}],
        runtime_root=tmp_path,
    )
    latest = service["latest_batch"]
    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=latest["rp_result"],
        spectral_result=latest["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Runtime service"},
        report_key="runtime_service",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    runtime_service_artifact = json.loads(Path(files["runtime_service_artifact"]).read_text(encoding="utf-8"))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))

    assert export_manifest["runtime_service_summary"]["status"] == "pass"
    assert export_manifest["runtime_service_artifact"] == files["runtime_service_artifact"]
    assert "RUNTIME_SERVICE_STATUS" in export_manifest["network_method_fields"]
    assert runtime_service_artifact["summary"]["service_id"] == "smartflux_runtime_service_v1"
    assert full_rows[0]["runtime_service_status"] == "pass"
    assert network_payload["rows"][0]["RUNTIME_SERVICE_STATUS"] == "pass"
    assert network_payload["rows"][0]["RUNTIME_SERVICE_DELIVERY_STATE"] == "ready"

    delivery = export_delivery_package(
        runtime_root=tmp_path,
        formal_report={"files": {}, "pdf_status": "fallback_html_only"},
        result_bundle=bundle,
        evidence_bundle=None,
        compare_manifest=None,
        attribution_result=None,
        current_batch_id=latest["batch_id"],
    )
    package_manifest = json.loads(Path(delivery["files"]["package_manifest"]).read_text(encoding="utf-8"))

    assert package_manifest["runtime_service_summary"]["status"] == "pass"
    assert package_manifest["result_manifest_summary"]["runtime_service_status"] == "pass"
    assert package_manifest["artifact_index"]["runtime_service_artifact"]["packaged"] is True
