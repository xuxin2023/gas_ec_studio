from __future__ import annotations

import csv
import json
from pathlib import Path

from core.acquisition.runtime_install import build_installable_runtime_profile, has_runtime_install_config
from core.acquisition.runtime_service import run_runtime_service_batches
from core.exports.delivery_exporter import export_delivery_package
from core.exports.result_exporter import ResultExporter
from tests.test_supervisor_integration_runtime import _config, _make_rows, _metadata


def _install_config(tmp_path: Path) -> dict:
    return {
        "profile_id": "site_install_profile_v1",
        "service_name": "gas-ec-runtime",
        "display_name": "Gas EC Studio Runtime",
        "description": "Gas EC Studio production runtime",
        "working_directory": str(tmp_path),
        "command": ["python", "-m", "core.headless_batch_runner", "--config", "runtime_config.json"],
        "os_targets": ["systemd", "windows_service"],
        "environment": {"GAS_EC_SITE": "SUP"},
        "restart_policy": "on-failure",
        "restart_sec": 15,
        "dry_run": True,
    }


def test_installable_runtime_profile_renders_systemd_and_windows_plans(tmp_path: Path) -> None:
    config = {"runtime_install": _install_config(tmp_path)}
    artifact = build_installable_runtime_profile(config=config, runtime_root=tmp_path)

    assert has_runtime_install_config(config) is True
    assert artifact["status"] == "pass"
    assert artifact["execution_mode"] == "plan_only_no_install_performed"
    assert artifact["command_explicit"] is True
    assert artifact["systemd_unit"]["unit_name"] == "gas-ec-runtime.service"
    assert "ExecStart=python -m core.headless_batch_runner --config runtime_config.json" in artifact["systemd_unit"]["content"]
    assert "Environment=GAS_EC_SITE=\"SUP\"" in artifact["systemd_unit"]["content"]
    assert artifact["windows_service"]["service_name"] == "gas-ec-runtime"
    assert "New-Service" in artifact["windows_service"]["dry_run_commands"][0]
    assert all(check["status"] == "pass" for check in artifact["checks"])


def test_installable_runtime_profile_warns_without_explicit_command(tmp_path: Path) -> None:
    artifact = build_installable_runtime_profile(
        config={"runtime_install": {"working_directory": str(tmp_path)}},
        runtime_root=tmp_path,
    )

    assert artifact["status"] == "warning"
    assert artifact["command_explicit"] is False
    assert "--help" in artifact["command"]
    warning_ids = {check["check_id"] for check in artifact["checks"] if check["status"] == "warn"}
    assert "runtime_command_explicit" in warning_ids


def test_installable_runtime_reaches_export_network_report_and_delivery(tmp_path: Path) -> None:
    metadata = _metadata()
    config = _config(tmp_path)
    config["runtime_install"] = _install_config(tmp_path)
    service = run_runtime_service_batches(
        config=config,
        metadata=metadata,
        batches=[{"input_id": "install-1", "rows": _make_rows(), "time_range": "install-1"}],
        runtime_root=tmp_path,
    )
    latest = service["latest_batch"]
    rp_result = latest["rp_result"]
    supervisor = service["service_manifest"]["daemon_telemetry"]["supervisor_integration"]
    install_profile = supervisor["installable_runtime_profile"]

    assert install_profile["status"] == "pass"
    assert rp_result.windows[0].diagnostics["installable_runtime_status"] == "pass"
    assert rp_result.windows[0].diagnostics["installable_runtime_targets"] == ["systemd", "windows_service"]

    exporter = ResultExporter(tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=rp_result,
        spectral_result=latest["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Installable runtime"},
        report_key="installable_runtime",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    export_manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    install_artifact = json.loads(Path(files["installable_runtime_artifact"]).read_text(encoding="utf-8"))
    network_payload = json.loads(Path(files["fluxnet_half_hourly_artifact"]).read_text(encoding="utf-8"))
    full_rows = list(csv.DictReader(Path(files["full_output"]).open(encoding="utf-8")))

    assert export_manifest["installable_runtime_summary"]["status"] == "pass"
    assert export_manifest["installable_runtime_artifact"] == files["installable_runtime_artifact"]
    assert "INSTALLABLE_RUNTIME_STATUS" in export_manifest["network_method_fields"]
    assert install_artifact["summary"]["systemd_unit"]["unit_name"] == "gas-ec-runtime.service"
    assert full_rows[0]["installable_runtime_status"] == "pass"
    assert full_rows[0]["installable_runtime_targets"] == "systemd|windows_service"
    assert network_payload["rows"][0]["INSTALLABLE_RUNTIME_STATUS"] == "pass"
    assert network_payload["rows"][0]["INSTALLABLE_RUNTIME_TARGETS"] == "systemd|windows_service"

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

    assert package_manifest["installable_runtime_summary"]["status"] == "pass"
    assert package_manifest["result_manifest_summary"]["installable_runtime_status"] == "pass"
    assert package_manifest["artifact_index"]["installable_runtime_artifact"]["packaged"] is True
