from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ID = "eddypro_source_smartflux_ptp_gps_001"
FIXTURE_DIR = Path("references/eddypro/source_derived/smartflux_ptp_gps_001")
GENERATED_AT = "2026-05-30T01:00:00+08:00"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a source-derived SmartFlux PTP/GPS target-host telemetry fixture.")
    parser.add_argument("--workspace-root", default=str(WORKSPACE_ROOT))
    args = parser.parse_args()
    root = Path(args.workspace_root).resolve()
    fixture_dir = root / FIXTURE_DIR
    fixture_dir.mkdir(parents=True, exist_ok=True)
    files = generate_fixture(root=root, fixture_dir=fixture_dir)
    print(json.dumps({"fixture_id": FIXTURE_ID, "files": files}, ensure_ascii=False, indent=2))
    return 0


def generate_fixture(*, root: Path, fixture_dir: Path) -> dict[str, str]:
    ptp_path = fixture_dir / "ptp4l_phc2sys.log"
    gps_path = fixture_dir / "gpsd_pps.log"
    chrony_path = fixture_dir / "chrony_tracking.log"
    watchdog_path = fixture_dir / "watchdogd.log"
    supervisor_path = fixture_dir / "supervisor.json"
    validation_path = fixture_dir / "target_host_validation.json"
    config_path = fixture_dir / "config.json"
    provenance_path = fixture_dir / "provenance.json"

    ptp_path.write_text(
        "\n".join(
            [
                "2026-05-30T01:00:00 smartflux ptp4l[102]: selected best master clock 00-1d-c1-ff-fe-ec-77-01",
                "2026-05-30T01:00:01 smartflux ptp4l[102]: master offset -92 s2 freq +5 path delay 645",
                "2026-05-30T01:00:02 smartflux ptp4l[102]: master offset 64 state s2 freq +4 path delay 640",
                "2026-05-30T01:00:03 smartflux phc2sys[104]: CLOCK_REALTIME phc offset 36 s2 freq -0.8 delay 801",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    gps_path.write_text(
        "\n".join(
            [
                json.dumps({"class": "TPV", "mode": 3, "ept": 0.00000004}, ensure_ascii=False),
                json.dumps({"class": "PPS", "offset_ns": -28, "jitter_ns": 66, "locked": True}, ensure_ascii=False),
                "^* PPS0          .PPS.            0   6   377    12   -35ns[ -42ns] +/-   75ns",
                "2026-05-30T01:00:02 gpsd pps offset_ns=31 jitter_ns=62 lock=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    chrony_path.write_text(
        "\n".join(
            [
                "Reference ID    : PPS",
                "Stratum         : 1",
                "System time     : 0.000000045 seconds fast of NTP time",
                "Last offset     : -0.000000035 seconds",
                "RMS offset      : 0.000000044 seconds",
                "Frequency       : 0.250 ppm slow",
                "Residual freq   : -0.004 ppm",
                "Leap status     : Normal",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    watchdog_path.write_text(
        "\n".join(
            [
                "2026-05-30T01:00:00 watchdogd[3]: opened /dev/watchdog0 watchdog device",
                json.dumps({"artifact_type": "hardware_watchdog_kick", "kick_delivered": True}, ensure_ascii=False),
                "2026-05-30T01:00:15 systemd[1]: gas-ec-runtime.service: WATCHDOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    supervisor_path.write_text(
        json.dumps(
            {
                "service_name": "gas-ec-runtime",
                "state": "running",
                "restart_count": 0,
                "dialect": "systemd_json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    validation = {
        "artifact_type": "source_derived_target_host_validation_snapshot_v1",
        "profile_id": "target_host_telemetry_validation_v1",
        "fixture_id": FIXTURE_ID,
        "target_host_id": "smartflux-source-derived-node-001",
        "source_derived": True,
        "expected": {
            "status": "pass",
            "supervisor": {
                "state": "running",
                "service_name": "gas-ec-runtime",
                "max_restart_count": 0,
            },
            "ptp_servo": {
                "status": "locked",
                "required_dialects": ["ptp4l", "phc2sys"],
                "max_abs_offset_ns_lte": 92.0,
            },
            "gps_pps": {
                "status": "locked",
                "required_dialects": ["gpsd", "pps"],
                "max_jitter_ns_lte": 75.0,
            },
            "clock_discipline": {
                "status": "locked",
                "clock_source": "PPS",
                "max_abs_offset_ns_lte": 45.0,
                "max_abs_frequency_ppm_lte": 0.25,
            },
            "hardware_watchdog": {
                "status": "active",
                "min_kick_count": 1,
                "max_timeout_count": 0,
            },
        },
    }
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    config = {
        "daemon_telemetry": {
            "enabled": True,
            "profile_id": "source_derived_smartflux_ptp_gps_v1",
            "source_root": _rel(fixture_dir, root=root),
            "ptp_servo_log": "ptp4l_phc2sys.log",
            "gps_pps_log": "gpsd_pps.log",
            "clock_discipline_log": "chrony_tracking.log",
            "hardware_watchdog_log": "watchdogd.log",
            "supervisor_status_file": "supervisor.json",
            "require_supervisor_running": True,
            "require_ptp_lock": True,
            "require_gps_lock": True,
            "require_clock_discipline_lock": True,
            "require_hardware_watchdog": True,
            "max_ptp_offset_ns": 100.0,
            "max_gps_jitter_ns": 100.0,
            "max_clock_discipline_offset_ns": 100.0,
            "max_clock_frequency_ppm": 1.0,
            "max_supervisor_restarts": 0,
            "target_host_validation": {
                "source_file": "target_host_validation.json",
            },
        }
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    generated_files = {
        "config_json": _rel(config_path, root=root),
        "target_host_validation_json": _rel(validation_path, root=root),
        "ptp_servo_log": _rel(ptp_path, root=root),
        "gps_pps_log": _rel(gps_path, root=root),
        "clock_discipline_log": _rel(chrony_path, root=root),
        "hardware_watchdog_log": _rel(watchdog_path, root=root),
        "supervisor_status_json": _rel(supervisor_path, root=root),
    }
    provenance = {
        "artifact_type": "source_derived_smartflux_ptp_gps_fixture_provenance_v1",
        "fixture_id": FIXTURE_ID,
        "generation_time": GENERATED_AT,
        "generation_method": "Deterministic SmartFlux-class PTP/GPS/chrony/watchdog target-host telemetry fixture.",
        "normalization_script": "scripts/generate_source_derived_smartflux_ptp_gps_fixture.py",
        "normalization_command": "python scripts/generate_source_derived_smartflux_ptp_gps_fixture.py",
        "source_repositories": {
            "eddypro_engine": {
                "url": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "used_for": "PTP/GPS/SmartFlux timing parity target and source capability matrix anchors.",
            },
            "smartflux": {
                "url": "https://bio.licor.com/env/products/eddy-covariance/smartflux",
                "used_for": "SmartFlux-class target-host GPS/PTP synchronization and embedded runtime behavior.",
            },
        },
        "files": generated_files,
        "sha256": {role: _sha256(root / path) for role, path in generated_files.items()},
        "known_limitations": [
            "This is a source-derived telemetry conformance fixture, not a capture from real SmartFlux hardware.",
            "It validates parser, target-host golden snapshot, and delivery-chain propagation only.",
            "Direct PHC/PTP/GPS clock discipline still requires bench validation on real hardware.",
        ],
    }
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    generated_files["provenance_json"] = _rel(provenance_path, root=root)
    return generated_files


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rel(path: Path, *, root: Path) -> str:
    return str(path.resolve().relative_to(root)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
