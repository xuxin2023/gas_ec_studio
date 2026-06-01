from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.acquisition.daemon_telemetry import (
    build_daemon_telemetry_artifact,
    build_target_host_telemetry_validation_artifact,
    parse_clock_discipline_log,
    parse_gps_pps_log,
    parse_hardware_watchdog_log,
    parse_ptp_servo_log,
)
from core.acquisition.runtime_service import run_runtime_service_batches
from core.exports.delivery_exporter import export_delivery_package
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.6 + 0.20 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.20 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.46 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.06 * np.cos(2.0 * np.pi * 0.63 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.8 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 3) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="daemon-demo",
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
        project=ProjectProfile(code="DMT-001", name="Daemon Telemetry"),
        site=SiteProfile(station_code="DMT", station_name="Daemon Tower"),
    )


def _write_good_telemetry(tmp_path: Path) -> dict[str, str]:
    ptp = tmp_path / "ptp4l.log"
    gps = tmp_path / "gps_pps.log"
    watchdog = tmp_path / "watchdog.log"
    supervisor = tmp_path / "supervisor.json"
    discipline = tmp_path / "chrony_tracking.log"
    ptp.write_text(
        "\n".join(
            [
                "2026-05-22T10:00:00 ptp4l[1]: master offset -120 s2 freq +12 path delay 800",
                "2026-05-22T10:00:01 ptp4l[1]: master offset 80 state s2 freq +10",
            ]
        ),
        encoding="utf-8",
    )
    gps.write_text(
        "\n".join(
            [
                "2026-05-22T10:00:00 pps offset_ns=40 jitter_ns=70 lock=1",
                "2026-05-22T10:00:01 pps offset_ns=-30 jitter_ns=60 locked",
            ]
        ),
        encoding="utf-8",
    )
    watchdog.write_text(
        "\n".join(
            [
                "2026-05-22T10:00:00 hardware watchdog armed",
                "2026-05-22T10:00:30 hardware watchdog kick keepalive",
            ]
        ),
        encoding="utf-8",
    )
    supervisor.write_text(
        json.dumps({"service_name": "gas-ec-runtime", "state": "running", "restart_count": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    discipline.write_text(
        "\n".join(
            [
                "Reference ID    : PPS",
                "Stratum         : 1",
                "System time     : 0.000000080 seconds slow of NTP time",
                "Last offset     : -0.000000040 seconds",
                "Frequency       : 12.500 ppm fast",
                "Residual freq   : -0.010 ppm",
                "Leap status     : Normal",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "ptp_servo_log": str(ptp),
        "gps_pps_log": str(gps),
        "clock_discipline_log": str(discipline),
        "hardware_watchdog_log": str(watchdog),
        "supervisor_status_file": str(supervisor),
    }


def _config(tmp_path: Path, *, watchdog_timeout: bool = False) -> dict:
    paths = _write_good_telemetry(tmp_path)
    if watchdog_timeout:
        Path(paths["hardware_watchdog_log"]).write_text(
            "2026-05-22T10:00:00 hardware watchdog armed\n2026-05-22T10:01:00 hardware watchdog timeout expired\n",
            encoding="utf-8",
        )
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
        },
        "daemon_telemetry": {
            **paths,
            "profile_id": "daemon_telemetry_v1",
            "require_supervisor_running": True,
            "require_ptp_lock": True,
            "require_gps_lock": True,
            "require_clock_discipline_lock": True,
            "require_hardware_watchdog": True,
            "max_ptp_offset_ns": 1000,
            "max_gps_jitter_ns": 1000,
            "max_clock_discipline_offset_ns": 1000,
            "max_clock_frequency_ppm": 20,
            "max_supervisor_restarts": 2,
        },
        "network_output": {
            "schema_target": "FLUXNET",
            "timezone_offset_hours": 0.0,
            "timestamp_refers_to": "start",
            "gap_fill_value": -9999.0,
        },
    }


def _with_target_host_validation(config: dict, *, max_ptp_offset_ns: float = 120.0) -> dict:
    config["daemon_telemetry"]["target_host_validation"] = {
        "profile_id": "target_host_telemetry_validation_v1",
        "fixture_id": "smartflux-target-host-good-001",
        "target_host_id": "smartflux-node-001",
        "expected": {
            "status": "pass",
            "supervisor": {"state": "running", "max_restart_count": 1},
            "ptp_servo": {
                "status": "locked",
                "required_dialects": ["ptp4l"],
                "max_abs_offset_ns_lte": max_ptp_offset_ns,
            },
            "gps_pps": {
                "status": "locked",
                "required_dialects": ["pps"],
                "max_jitter_ns_lte": 70.0,
            },
            "clock_discipline": {
                "status": "locked",
                "clock_source": "PPS",
                "max_abs_offset_ns_lte": 80.0,
                "max_abs_frequency_ppm_lte": 12.5,
            },
            "hardware_watchdog": {
                "status": "active",
                "min_kick_count": 1,
                "max_timeout_count": 0,
            },
        },
    }
    return config


def test_daemon_telemetry_parses_supervisor_clock_and_watchdog_logs(tmp_path: Path) -> None:
    artifact = build_daemon_telemetry_artifact(config=_config(tmp_path), runtime_root=tmp_path)

    assert artifact["status"] == "pass"
    assert artifact["supervisor"]["state"] == "running"
    assert artifact["ptp_servo"]["status"] == "locked"
    assert artifact["ptp_servo"]["max_abs_offset_ns"] == 120.0
    assert artifact["gps_pps"]["status"] == "locked"
    assert artifact["gps_pps"]["max_jitter_ns"] == 70.0
    assert artifact["clock_discipline"]["status"] == "locked"
    assert artifact["clock_discipline"]["max_abs_offset_ns"] == 80.0
    assert artifact["clock_discipline"]["max_abs_frequency_ppm"] == 12.5
    assert artifact["hardware_watchdog"]["status"] == "active"
    assert artifact["process_telemetry"]["pid"]


def test_target_host_telemetry_validation_passes_against_golden_snapshot(tmp_path: Path) -> None:
    config = _with_target_host_validation(_config(tmp_path))

    artifact = build_daemon_telemetry_artifact(config=config, runtime_root=tmp_path)
    validation = artifact["target_host_validation"]
    standalone = build_target_host_telemetry_validation_artifact(
        config=config,
        runtime_root=tmp_path,
        telemetry_artifact=artifact,
    )

    assert artifact["status"] == "pass"
    assert validation["status"] == "pass"
    assert validation["gate_status"] == "pass"
    assert validation["fixture_id"] == "smartflux-target-host-good-001"
    assert validation["target_host_id"] == "smartflux-node-001"
    assert validation["fail_count"] == 0
    assert standalone["status"] == "pass"
    assert any(check["check_id"] == "target_host.ptp_servo.required_dialects" for check in validation["checks"])


def test_target_host_telemetry_validation_blocks_mismatched_snapshot(tmp_path: Path) -> None:
    config = _with_target_host_validation(_config(tmp_path), max_ptp_offset_ns=10.0)

    artifact = build_daemon_telemetry_artifact(config=config, runtime_root=tmp_path)
    validation = artifact["target_host_validation"]

    assert artifact["status"] == "fail"
    assert validation["status"] == "fail"
    assert validation["gate_status"] == "blocked"
    assert validation["fail_count"] >= 1
    assert any(check["check_id"] == "target_host_validation" for check in artifact["checks"])


def test_daemon_telemetry_parses_target_host_daemon_dialects(tmp_path: Path) -> None:
    ptp = tmp_path / "chrony_phc2sys.log"
    gps = tmp_path / "gpsd_pps.log"
    watchdog = tmp_path / "watchdogd_provider.jsonl"
    supervisor = tmp_path / "supervisor_journal.log"
    discipline = tmp_path / "discipline.jsonl"
    ptp.write_text(
        "\n".join(
            [
                "May 25 12:00:00 smartflux chronyd[41]: Selected source PPS",
                "System time     : 0.000000080 seconds slow of NTP time",
                "Last offset     : -0.000000040 seconds",
                "Leap status     : Normal",
                "phc2sys[99]: CLOCK_REALTIME phc offset -23 s2 freq +12 delay 800",
            ]
        ),
        encoding="utf-8",
    )
    gps.write_text(
        "\n".join(
            [
                json.dumps({"class": "TPV", "mode": 3, "ept": 0.00000005}, ensure_ascii=False),
                json.dumps({"class": "PPS", "offset_ns": -30, "jitter_ns": 65, "locked": True}, ensure_ascii=False),
                "^* PPS0          .PPS.            0   6   377    12   -35ns[ -42ns] +/-   80ns",
            ]
        ),
        encoding="utf-8",
    )
    watchdog.write_text(
        "\n".join(
            [
                "watchdogd[3]: opened /dev/watchdog0 watchdog device",
                json.dumps({"artifact_type": "hardware_watchdog_kick", "kick_delivered": True}, ensure_ascii=False),
                "systemd[1]: gas-ec-runtime.service: WATCHDOG=1",
            ]
        ),
        encoding="utf-8",
    )
    supervisor.write_text(
        "\n".join(
            [
                "May 25 12:00:00 smartflux systemd[1]: Started gas-ec-runtime.service.",
                "Event ID 7036 Service Control Manager: Gas EC Studio Runtime service entered the running state.",
                "Restart counter is at 1.",
            ]
        ),
        encoding="utf-8",
    )
    discipline.write_text(
        "\n".join(
            [
                json.dumps({"source": "PHC0", "state": "locked", "offset_ns": 42, "frequency_ppm": -0.4, "stratum": 1}, ensure_ascii=False),
                "phc2sys[77]: CLOCK_REALTIME phc offset -37 s2 freq +7 delay 799",
            ]
        ),
        encoding="utf-8",
    )

    ptp_summary = parse_ptp_servo_log(ptp)
    gps_summary = parse_gps_pps_log(gps)
    discipline_summary = parse_clock_discipline_log(discipline)
    watchdog_summary = parse_hardware_watchdog_log(watchdog)
    artifact = build_daemon_telemetry_artifact(
        config={
            "daemon_telemetry": {
                "ptp_servo_log": str(ptp),
                "gps_pps_log": str(gps),
                "clock_discipline_log": str(discipline),
                "hardware_watchdog_log": str(watchdog),
                "supervisor_status_file": str(supervisor),
                "require_supervisor_running": True,
                "require_ptp_lock": True,
                "require_gps_lock": True,
                "require_clock_discipline_lock": True,
                "require_hardware_watchdog": True,
                "max_ptp_offset_ns": 1000,
                "max_gps_jitter_ns": 1000,
                "max_clock_discipline_offset_ns": 1000,
                "max_clock_frequency_ppm": 20,
                "max_supervisor_restarts": 2,
            }
        },
        runtime_root=tmp_path,
    )

    assert ptp_summary["status"] == "locked"
    assert {"chrony", "phc2sys"}.issubset(set(ptp_summary["dialects"]))
    assert ptp_summary["max_abs_offset_ns"] == 80.0
    assert gps_summary["status"] == "locked"
    assert {"gpsd", "pps"}.issubset(set(gps_summary["dialects"]))
    assert gps_summary["max_jitter_ns"] == 80.0
    assert discipline_summary["status"] == "locked"
    assert {"json", "phc2sys"}.issubset(set(discipline_summary["dialects"]))
    assert discipline_summary["max_abs_offset_ns"] == 42.0
    assert discipline_summary["max_abs_frequency_ppm"] == 7.0
    assert watchdog_summary["status"] == "active"
    assert {"watchdogd", "linux_watchdog", "systemd_journal", "json"}.issubset(set(watchdog_summary["dialects"]))
    assert watchdog_summary["provider_record_count"] == 1
    assert artifact["status"] == "pass"
    assert artifact["clock_discipline"]["clock_source"] == "PHC0"
    assert artifact["supervisor"]["dialect"] in {"systemd_journal", "windows_event"}
    assert artifact["supervisor"]["state"] == "running"
    assert artifact["supervisor"]["restart_count"] == 1


def test_source_derived_smartflux_ptp_gps_fixture_validates_from_repo() -> None:
    fixture_root = Path("references/eddypro/source_derived/smartflux_ptp_gps_001")
    config = json.loads((fixture_root / "config.json").read_text(encoding="utf-8"))
    provenance = json.loads((fixture_root / "provenance.json").read_text(encoding="utf-8"))

    artifact = build_daemon_telemetry_artifact(config=config, runtime_root=Path.cwd())
    validation = artifact["target_host_validation"]

    assert provenance["fixture_id"] == "eddypro_source_smartflux_ptp_gps_001"
    assert artifact["status"] == "pass"
    assert artifact["source_root"].endswith("references\\eddypro\\source_derived\\smartflux_ptp_gps_001")
    assert artifact["ptp_servo"]["status"] == "locked"
    assert {"ptp4l", "phc2sys"}.issubset(set(artifact["ptp_servo"]["dialects"]))
    assert artifact["gps_pps"]["status"] == "locked"
    assert {"gpsd", "pps"}.issubset(set(artifact["gps_pps"]["dialects"]))
    assert artifact["clock_discipline"]["status"] == "locked"
    assert artifact["clock_discipline"]["clock_source"] == "PPS"
    assert artifact["hardware_watchdog"]["status"] == "active"
    assert validation["fixture_id"] == "eddypro_source_smartflux_ptp_gps_001"
    assert validation["target_host_id"] == "smartflux-source-derived-node-001"
    assert validation["gate_status"] == "pass"
    assert validation["fail_count"] == 0
    assert any(check["check_id"] == "target_host.ptp_servo.required_dialects" for check in validation["checks"])


def test_daemon_telemetry_reaches_export_network_and_delivery(tmp_path: Path) -> None:
    metadata = _metadata()
    config = _with_target_host_validation(_config(tmp_path))
    service = run_runtime_service_batches(
        config=config,
        metadata=metadata,
        batches=[{"input_id": "ok-1", "rows": _make_rows(), "time_range": "ok-1"}],
        runtime_root=tmp_path,
    )
    latest = service["latest_batch"]
    rp_result = latest["rp_result"]

    assert service["service_manifest"]["daemon_telemetry"]["status"] == "pass"
    assert rp_result.artifacts["daemon_telemetry"]["hardware_watchdog"]["status"] == "active"
    assert rp_result.windows[0].diagnostics["daemon_telemetry_status"] == "pass"
    assert rp_result.windows[0].diagnostics["target_host_validation_status"] == "pass"
    assert rp_result.windows[0].diagnostics["target_host_validation_gate_status"] == "pass"
    assert rp_result.windows[0].diagnostics["ptp_lock_status"] == "locked"
    assert rp_result.windows[0].diagnostics["clock_discipline_status"] == "locked"

    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=rp_result,
        spectral_result=latest["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Daemon telemetry"},
        report_key="daemon_telemetry",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    daemon_artifact = json.loads(Path(files["daemon_telemetry_artifact"]).read_text(encoding="utf-8"))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))

    assert export_manifest["daemon_telemetry_summary"]["status"] == "pass"
    assert export_manifest["daemon_telemetry_summary"]["target_host_validation"]["status"] == "pass"
    assert export_manifest["daemon_telemetry_artifact"] == files["daemon_telemetry_artifact"]
    assert "DAEMON_TELEMETRY_STATUS" in export_manifest["network_method_fields"]
    assert "TARGET_HOST_VALIDATION_STATUS" in export_manifest["network_method_fields"]
    assert daemon_artifact["summary"]["ptp_servo"]["status"] == "locked"
    assert daemon_artifact["summary"]["target_host_validation"]["gate_status"] == "pass"
    assert daemon_artifact["summary"]["clock_discipline"]["status"] == "locked"
    assert full_rows[0]["daemon_telemetry_status"] == "pass"
    assert full_rows[0]["target_host_validation_status"] == "pass"
    assert full_rows[0]["target_host_validation_target_host_id"] == "smartflux-node-001"
    assert full_rows[0]["clock_discipline_status"] == "locked"
    assert network_payload["rows"][0]["DAEMON_TELEMETRY_STATUS"] == "pass"
    assert network_payload["rows"][0]["TARGET_HOST_VALIDATION_STATUS"] == "pass"
    assert network_payload["rows"][0]["TARGET_HOST_VALIDATION_GATE_STATUS"] == "pass"
    assert network_payload["rows"][0]["TARGET_HOST_ID"] == "smartflux-node-001"
    assert network_payload["rows"][0]["PTP_LOCK_STATUS"] == "locked"
    assert network_payload["rows"][0]["CLOCK_DISCIPLINE_STATUS"] == "locked"
    assert network_payload["rows"][0]["CLOCK_DISCIPLINE_OFFSET_NS"] == 80.0
    assert network_payload["rows"][0]["HARDWARE_WATCHDOG_STATUS"] == "active"

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

    assert package_manifest["daemon_telemetry_summary"]["status"] == "pass"
    assert package_manifest["daemon_telemetry_summary"]["target_host_validation"]["status"] == "pass"
    assert package_manifest["result_manifest_summary"]["daemon_telemetry_status"] == "pass"
    assert package_manifest["artifact_index"]["daemon_telemetry_artifact"]["packaged"] is True


def test_daemon_telemetry_fault_blocks_runtime_delivery(tmp_path: Path) -> None:
    service = run_runtime_service_batches(
        config=_config(tmp_path, watchdog_timeout=True),
        metadata=_metadata(),
        batches=[{"input_id": "ok-1", "rows": _make_rows(), "time_range": "ok-1"}],
        runtime_root=tmp_path,
    )
    manifest = service["service_manifest"]

    assert manifest["daemon_telemetry"]["status"] == "fail"
    assert manifest["daemon_telemetry"]["hardware_watchdog"]["status"] == "fault"
    assert manifest["status"] == "fail"
    assert manifest["delivery_state"] == "blocked"
    assert service["latest_batch"]["rp_result"].windows[0].diagnostics["hardware_watchdog_status"] == "fault"
