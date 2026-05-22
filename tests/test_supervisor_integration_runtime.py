from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.acquisition.runtime_service import run_runtime_service_batches
from core.acquisition.supervisor_integration import (
    build_supervisor_integration_artifact,
    parse_systemd_status,
    parse_windows_service_status,
)
from core.exports.delivery_exporter import export_delivery_package
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 12, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.18 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.44 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.05 * np.cos(2.0 * np.pi * 0.63 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.8 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 3) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="supervisor-demo",
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
        project=ProjectProfile(code="SUP-001", name="Supervisor Integration"),
        site=SiteProfile(station_code="SUP", station_name="Supervisor Tower"),
    )


def _config(tmp_path: Path) -> dict:
    systemd = tmp_path / "systemd.show"
    kick_file = tmp_path / "watchdog" / "kick.jsonl"
    systemd.write_text(
        "\n".join(
            [
                "Id=gas-ec-runtime.service",
                "ActiveState=active",
                "SubState=running",
                "NRestarts=1",
                "ExecMainStatus=0",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "clock_sync": {
            "enabled": True,
            "clock_source": "GPS+PTP",
            "offset_seconds": 0.05,
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
        },
        "supervisor_integration": {
            "adapter": "systemd",
            "status_file": str(systemd),
            "require_running": True,
            "max_restart_count": 2,
            "allow_reboot_request": False,
            "hardware_watchdog_provider": {
                "provider": "file",
                "kick_file": str(kick_file),
                "dry_run": True,
                "service_name": "gas-ec-runtime",
            },
        },
        "network_output": {
            "schema_target": "FLUXNET",
            "timezone_offset_hours": 0.0,
            "timestamp_refers_to": "start",
            "gap_fill_value": -9999.0,
        },
    }


def test_supervisor_parsers_normalize_systemd_and_windows_status() -> None:
    systemd = parse_systemd_status(
        "Id=gas-ec-runtime.service\nActiveState=active\nSubState=running\nNRestarts=2\nExecMainStatus=0\n"
    )
    windows = parse_windows_service_status(
        "SERVICE_NAME: gas-ec-runtime\n        STATE              : 4  RUNNING\n        WIN32_EXIT_CODE    : 0  (0x0)\n"
    )

    assert systemd["adapter"] == "systemd"
    assert systemd["state"] == "running"
    assert systemd["restart_count"] == 2
    assert windows["adapter"] == "windows_service"
    assert windows["state"] == "running"


def test_supervisor_integration_records_watchdog_kick(tmp_path: Path) -> None:
    config = _config(tmp_path)
    artifact = build_supervisor_integration_artifact(config=config, runtime_root=tmp_path)
    kick_file = Path(config["supervisor_integration"]["hardware_watchdog_provider"]["kick_file"])

    assert artifact["status"] == "pass"
    assert artifact["service_status"]["state"] == "running"
    assert artifact["hardware_watchdog_provider"]["status"] == "kick_recorded"
    assert artifact["hardware_watchdog_provider"]["kick_recorded"] is True
    assert kick_file.exists()
    kick_payload = json.loads(kick_file.read_text(encoding="utf-8").splitlines()[-1])
    assert kick_payload["artifact_type"] == "hardware_watchdog_kick"
    assert kick_payload["dry_run"] is True


def test_supervisor_integration_reaches_export_network_and_delivery(tmp_path: Path) -> None:
    metadata = _metadata()
    config = _config(tmp_path)
    service = run_runtime_service_batches(
        config=config,
        metadata=metadata,
        batches=[{"input_id": "ok-1", "rows": _make_rows(), "time_range": "ok-1"}],
        runtime_root=tmp_path,
    )
    latest = service["latest_batch"]
    rp_result = latest["rp_result"]

    assert service["service_manifest"]["daemon_telemetry"]["supervisor_integration"]["status"] == "pass"
    assert rp_result.windows[0].diagnostics["os_supervisor_status"] == "pass"
    assert rp_result.windows[0].diagnostics["watchdog_provider_status"] == "kick_recorded"

    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=rp_result,
        spectral_result=latest["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Supervisor integration"},
        report_key="supervisor_integration",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    supervisor_artifact = json.loads(Path(files["supervisor_integration_artifact"]).read_text(encoding="utf-8"))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))

    assert export_manifest["supervisor_integration_summary"]["status"] == "pass"
    assert export_manifest["supervisor_integration_artifact"] == files["supervisor_integration_artifact"]
    assert "OS_SUPERVISOR_STATUS" in export_manifest["network_method_fields"]
    assert supervisor_artifact["summary"]["hardware_watchdog_provider"]["status"] == "kick_recorded"
    assert full_rows[0]["os_supervisor_state"] == "running"
    assert network_payload["rows"][0]["OS_SUPERVISOR_STATUS"] == "pass"
    assert network_payload["rows"][0]["OS_SUPERVISOR_STATE"] == "running"
    assert network_payload["rows"][0]["WATCHDOG_PROVIDER_STATUS"] == "kick_recorded"

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

    assert package_manifest["supervisor_integration_summary"]["status"] == "pass"
    assert package_manifest["result_manifest_summary"]["supervisor_integration_status"] == "pass"
    assert package_manifest["artifact_index"]["supervisor_integration_artifact"]["packaged"] is True
