from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.exports.delivery_exporter import export_delivery_package
from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import run_headless_batch
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.5 + 0.20 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.20 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.45 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.06 * np.cos(2.0 * np.pi * 0.63 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.8 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 3) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="runtime-demo",
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
        project=ProjectProfile(code="RT-001", name="Runtime Watchdog"),
        site=SiteProfile(station_code="RT", station_name="Runtime Tower"),
    )


def _config() -> dict:
    return {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "clock_sync": {
            "enabled": True,
            "clock_source": "GPS+PTP",
            "offset_seconds": 0.25,
        },
        "runtime_profile": {
            "profile_id": "smartflux_watchdog_v1",
            "expected_sample_hz": 10.0,
            "max_gap_seconds": 0.5,
            "min_window_count": 1,
            "require_clock_sync": True,
            "watchdog_interval_s": 60,
        },
        "network_output": {
            "schema_target": "FLUXNET",
            "timezone_offset_hours": 0.0,
            "timestamp_refers_to": "start",
            "gap_fill_value": -9999.0,
        },
    }


def test_headless_batch_emits_runtime_watchdog_manifest() -> None:
    batch = run_headless_batch(config=_config(), metadata=_metadata(), rows=_make_rows(), data_source="runtime-headless")
    manifest = batch["manifest"]
    rp_result = batch["rp_result"]
    spectral_result = batch["spectral_result"]
    watchdog = batch["runtime_watchdog_summary"]

    assert watchdog["status"] == "pass"
    assert watchdog["profile_id"] == "smartflux_watchdog_v1"
    assert manifest["runtime_watchdog_summary"]["status"] == "pass"
    assert rp_result.summary["runtime_watchdog_status"] == "pass"
    assert rp_result.artifacts["runtime_watchdog"]["status"] == "pass"
    assert spectral_result.artifacts["runtime_watchdog"]["status"] == "pass"
    assert rp_result.windows[0].diagnostics["runtime_watchdog_status"] == "pass"
    assert rp_result.windows[0].diagnostics["runtime_watchdog_profile"] == "smartflux_watchdog_v1"
    assert {check["check_id"] for check in watchdog["checks"]} >= {"max_gap_seconds", "clock_sync", "network_validation"}


def test_runtime_watchdog_flags_acquisition_gap() -> None:
    rows = _make_rows()
    for index in range(100, len(rows)):
        rows[index].timestamp = rows[index].timestamp + timedelta(seconds=5.0)
    config = _config()
    config["runtime_profile"]["max_gap_seconds"] = 1.0

    batch = run_headless_batch(config=config, metadata=_metadata(), rows=rows, data_source="runtime-gap")
    watchdog = batch["runtime_watchdog_summary"]
    checks = {check["check_id"]: check for check in watchdog["checks"]}

    assert watchdog["status"] == "fail"
    assert checks["max_gap_seconds"]["status"] == "fail"
    assert any("acquisition gaps" in action for action in watchdog["recommended_actions"])


def test_runtime_watchdog_export_and_delivery_chain(tmp_path: Path) -> None:
    metadata = _metadata()
    config = _config()
    batch = run_headless_batch(config=config, metadata=metadata, rows=_make_rows(), data_source="runtime-export")
    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=batch["rp_result"],
        spectral_result=batch["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Runtime watchdog"},
        report_key="runtime_watchdog",
        full_output_mode="standard_schema",
    )

    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    watchdog_artifact = json.loads(Path(files["runtime_watchdog_artifact"]).read_text(encoding="utf-8"))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))

    assert export_manifest["runtime_watchdog_summary"]["status"] == "pass"
    assert export_manifest["runtime_watchdog_artifact"] == files["runtime_watchdog_artifact"]
    assert "RUNTIME_WATCHDOG_STATUS" in export_manifest["network_method_fields"]
    assert watchdog_artifact["summary"]["profile_id"] == "smartflux_watchdog_v1"
    assert full_rows[0]["runtime_watchdog_status"] == "pass"
    assert network_payload["rows"][0]["RUNTIME_WATCHDOG_STATUS"] == "pass"
    assert network_payload["rows"][0]["RUNTIME_WATCHDOG_PROFILE"] == "smartflux_watchdog_v1"

    delivery = export_delivery_package(
        runtime_root=tmp_path,
        formal_report={"files": {}, "pdf_status": "fallback_html_only"},
        result_bundle=bundle,
        evidence_bundle=None,
        compare_manifest=None,
        attribution_result=None,
        current_batch_id=batch["batch_id"],
    )
    package_manifest = json.loads(Path(delivery["files"]["package_manifest"]).read_text(encoding="utf-8"))

    assert package_manifest["runtime_watchdog_summary"]["status"] == "pass"
    assert package_manifest["result_manifest_summary"]["runtime_watchdog_status"] == "pass"
    assert package_manifest["artifact_index"]["runtime_watchdog_artifact"]["packaged"] is True
