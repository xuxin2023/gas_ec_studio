from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import run_headless_batch
from core.storage.clock_sync import apply_clock_sync_to_rows
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.6 + 0.25 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.25 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.45 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.08 * np.cos(2.0 * np.pi * 0.61 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.9 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 3) + 0.02 * np.cos(2.0 * np.pi * 0.8 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="clock-demo",
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


def test_clock_sync_applies_offset_and_preserves_row_provenance() -> None:
    rows = _make_rows(samples=20)

    result = apply_clock_sync_to_rows(
        rows,
        config={
            "clock_sync": {
                "enabled": True,
                "clock_source": "GPS+PTP",
                "offset_seconds": 1.25,
                "drift_ppm": 0.0,
            }
        },
    )

    assert result.summary["status"] == "applied"
    assert result.summary["clock_source"] == "GPS+PTP"
    assert result.rows[0].timestamp == rows[0].timestamp + timedelta(seconds=1.25)
    assert rows[0].timestamp == datetime(2026, 5, 22, 10, 0, 0)
    payload = json.loads(result.rows[0].raw_text)
    assert payload["clock_sync"]["original_timestamp"] == "2026-05-22T10:00:00"
    assert payload["clock_sync"]["corrected_timestamp"] == "2026-05-22T10:00:01.250000"
    assert payload["clock_sync"]["offset_seconds"] == 1.25


def test_clock_sync_events_interpolate_offsets() -> None:
    rows = _make_rows(sample_hz=1.0, samples=11)
    start = rows[0].timestamp

    result = apply_clock_sync_to_rows(
        rows,
        config={
            "clock_sync": {
                "enabled": True,
                "clock_source": "PTP",
                "events": [
                    {"timestamp": start.isoformat(), "offset_seconds": 0.5},
                    {"timestamp": (start + timedelta(seconds=10)).isoformat(), "offset_seconds": 1.5},
                ],
            }
        },
    )

    assert result.summary["event_count"] == 2
    assert result.summary["event_interpolation"] == "linear_clamped"
    assert result.rows[5].timestamp == rows[5].timestamp + timedelta(seconds=1.0)
    assert result.summary["min_offset_seconds"] == 0.5
    assert result.summary["max_offset_seconds"] == 1.5


def test_clock_sync_quality_gate_tracks_event_step_threshold() -> None:
    rows = _make_rows(sample_hz=1.0, samples=11)
    start = rows[0].timestamp

    warning = apply_clock_sync_to_rows(
        rows,
        config={
            "clock_sync": {
                "enabled": True,
                "clock_source": "PTP",
                "jitter_threshold_seconds": 0.25,
                "events": [
                    {"timestamp": start.isoformat(), "offset_seconds": 0.0},
                    {"timestamp": (start + timedelta(seconds=10)).isoformat(), "offset_seconds": 1.0},
                ],
            }
        },
    )
    fail = apply_clock_sync_to_rows(
        rows,
        config={
            "clock_sync": {
                "enabled": True,
                "clock_source": "PTP",
                "jitter_threshold_seconds": 0.25,
                "require_quality_gate": True,
                "events": [
                    {"timestamp": start.isoformat(), "offset_seconds": 0.0},
                    {"timestamp": (start + timedelta(seconds=10)).isoformat(), "offset_seconds": 1.0},
                ],
            }
        },
    )

    assert warning.summary["quality_status"] == "warning"
    assert warning.summary["quality_gate_status"] == "warning"
    assert warning.summary["max_event_step_seconds"] == 1.0
    assert warning.summary["quality_threshold_seconds"] == 0.25
    assert any(check["check_id"] == "clock_sync.quality_threshold" for check in warning.summary["quality_checks"])
    assert fail.summary["quality_status"] == "fail"
    assert fail.summary["quality_gate_status"] == "fail"


def test_rp_pipeline_applies_clock_sync_before_windowing() -> None:
    rows = _make_rows(samples=600)
    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="CLK-001", name="Clock Sync"),
        site=SiteProfile(station_code="CLK", station_name="Clock Tower"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "clock_sync": {
                "enabled": True,
                "method": "gps_ptp_offset_drift_v1",
                "clock_source": "GPS",
                "offset_seconds": 2.0,
                "jitter_threshold_seconds": 0.1,
            },
        },
        data_source="clock-test",
        time_range="clock",
    )

    assert result.summary["clock_sync_status"] == "applied"
    assert result.summary["clock_sync_mean_offset_s"] == 2.0
    assert result.artifacts["clock_sync"]["status"] == "applied"
    assert result.windows[0].start_time == rows[0].timestamp + timedelta(seconds=2.0)
    diagnostics = result.windows[0].diagnostics
    assert diagnostics["clock_sync_status"] == "applied"
    assert diagnostics["clock_sync_method"] == "gps_ptp_offset_drift_v1"
    assert diagnostics["clock_sync_source"] == "GPS"
    assert diagnostics["clock_sync_quality_status"] == "pass"
    assert diagnostics["clock_sync_quality_gate_status"] == "pass"
    assert diagnostics["clock_sync_quality_metric_s"] == 0.0


def test_headless_manifest_and_exporter_carry_clock_sync(tmp_path: Path) -> None:
    rows = _make_rows(samples=600)
    metadata = MetadataBundle(
        project=ProjectProfile(code="CLK-002", name="Clock Headless"),
        site=SiteProfile(station_code="CLK2", station_name="Clock Export"),
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "clock_sync": {
            "enabled": True,
            "clock_source": "GPS+PTP",
            "offset_seconds": 0.75,
            "drift_ppm": 0.0,
            "jitter_threshold_seconds": 0.1,
        },
        "network_output": {
            "schema_target": "FLUXNET",
            "timezone_offset_hours": 0.0,
            "timestamp_refers_to": "start",
            "gap_fill_value": -9999.0,
        },
    }

    batch = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="clock-headless")
    manifest = batch["manifest"]
    rp_result = batch["rp_result"]
    spectral_result = batch["spectral_result"]

    assert batch["clock_sync_summary"]["status"] == "applied"
    assert batch["clock_sync_summary"]["quality_status"] == "pass"
    assert manifest["clock_sync_summary"]["status"] == "applied"
    assert manifest["clock_sync_summary"]["quality_gate_status"] == "pass"
    assert manifest["time_range"]["start"] == "2026-05-22T10:00:00.750000"
    assert rp_result.windows[0].diagnostics["clock_sync_mean_offset_s"] == 0.75
    assert rp_result.windows[0].diagnostics["clock_sync_quality_status"] == "pass"
    assert spectral_result.windows[0].start_time == rows[0].timestamp + timedelta(seconds=0.75)

    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=rp_result,
        spectral_result=spectral_result,
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Clock sync"},
        report_key="clock_sync",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))

    assert export_manifest["clock_sync_summary"]["status"] == "applied"
    assert export_manifest["clock_sync_summary"]["quality_status"] == "pass"
    assert export_manifest["clock_sync_artifact"] == files["clock_sync_artifact"]
    assert "clock_sync_method" in export_manifest["method_provenance_fields"]
    assert "clock_sync_quality_status" in export_manifest["method_provenance_fields"]
    assert "CLOCK_SYNC_METHOD" in export_manifest["network_method_fields"]
    assert "CLOCK_SYNC_QUALITY_STATUS" in export_manifest["network_method_fields"]
    assert full_rows[0]["clock_sync_status"] == "applied"
    assert full_rows[0]["clock_sync_source"] == "GPS+PTP"
    assert full_rows[0]["clock_sync_quality_status"] == "pass"
    assert network_payload["rows"][0]["CLOCK_SYNC_STATUS"] == "applied"
    assert network_payload["rows"][0]["CLOCK_SYNC_METHOD"] == "gps_ptp_offset_drift_v1"
    assert network_payload["rows"][0]["CLOCK_SYNC_QUALITY_STATUS"] == "pass"
