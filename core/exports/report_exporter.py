from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


REPORT_VERSION = "formal_report_v1"
_TEMPLATE_DIR = Path(__file__).with_name("templates")
_DEFAULT_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{REPORT_TITLE}}</title>
  <style>
{{INLINE_STYLES}}
  </style>
</head>
<body>
  <main class="report-shell">
{{REPORT_BODY}}
  </main>
</body>
</html>
"""
_DEFAULT_STYLES = """
@page { size: A4; margin: 16mm; }
body { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif; color: #1f2937; background: #f5f7fa; margin: 0; }
.report-shell { max-width: 1080px; margin: 0 auto; padding: 24px; }
.cover, .section { background: #fff; border: 1px solid #d9e0e8; border-radius: 14px; padding: 24px; margin-bottom: 18px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05); }
.cover h1 { margin: 0 0 8px; font-size: 30px; color: #0f172a; }
.cover .subtitle { color: #475569; font-size: 14px; margin-bottom: 18px; }
.meta-grid, .summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.summary-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 16px; }
.meta-card, .summary-card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; background: #fbfdff; }
.label { font-size: 12px; color: #64748b; margin-bottom: 6px; }
.value { font-size: 16px; font-weight: 600; color: #0f172a; }
.summary-card .value { font-size: 22px; }
.summary-card .note { margin-top: 6px; font-size: 12px; color: #64748b; }
.section h2 { margin: 0 0 12px; font-size: 20px; color: #0f172a; }
.section-intro { margin: 0 0 14px; font-size: 13px; color: #475569; }
.section-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e2e8f0; padding: 10px 8px; text-align: left; vertical-align: top; }
th { color: #334155; font-weight: 700; background: #f8fafc; }
td { color: #1f2937; }
.kv-list { margin: 0; padding-left: 18px; color: #334155; }
.kv-list li { margin-bottom: 6px; }
.muted { color: #64748b; }
.empty { padding: 14px; border: 1px dashed #cbd5e1; border-radius: 12px; color: #64748b; background: #f8fafc; }
.artifact-list { margin: 0; padding-left: 18px; }
.artifact-list li { margin-bottom: 8px; word-break: break-all; }
@media print {
  body { background: #fff; }
  .report-shell { max-width: none; padding: 0; }
  .cover, .section { box-shadow: none; break-inside: avoid; margin-bottom: 12px; }
}
"""


def export_report_snapshot(
    *,
    runtime_root: Path,
    report_key: str,
    run_id: str | None,
    report_payload: dict,
) -> Path:
    export_root = Path(runtime_root) / "exports" / "reports"
    export_root.mkdir(parents=True, exist_ok=True)
    suffix = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = export_root / f"{report_key}_{suffix}.json"
    _write_report_files(json_path=json_path, csv_path=export_root / f"{report_key}_{suffix}.csv", report_payload=report_payload)
    return json_path


def write_report_snapshot(*, export_root: Path, report_payload: dict, report_key: str = "report_snapshot") -> Path:
    export_root = Path(export_root)
    export_root.mkdir(parents=True, exist_ok=True)
    json_path = export_root / f"{report_key}.json"
    csv_path = export_root / f"{report_key}.csv"
    _write_report_files(json_path=json_path, csv_path=csv_path, report_payload=report_payload)
    return json_path


def export_formal_report(
    *,
    runtime_root: Path,
    project_snapshot: dict[str, Any],
    site_snapshot: dict[str, Any],
    device_snapshots: list[dict[str, Any]],
    rp_result: Any | None,
    spectral_result: Any | None,
    eddypro_compare: dict[str, Any] | None,
    attribution_result: dict[str, Any] | None,
    rp_config_snapshot: dict[str, Any],
    spectral_config_snapshot: dict[str, Any],
    latest_export_status: str,
    result_bundle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = datetime.now()
        batch_id = _batch_id(spectral_result, rp_result)
        suffix = batch_id or timestamp.strftime("%Y%m%d_%H%M%S")
        export_root = Path(runtime_root) / "exports" / "formal_reports" / f"formal_report_{suffix}"
        export_root.mkdir(parents=True, exist_ok=True)

        snapshot = _build_formal_report_snapshot(
            generated_at=timestamp,
            project_snapshot=project_snapshot,
            site_snapshot=site_snapshot,
            device_snapshots=device_snapshots,
            rp_result=rp_result,
            spectral_result=spectral_result,
            eddypro_compare=eddypro_compare or {},
            attribution_result=attribution_result or {},
            rp_config_snapshot=rp_config_snapshot,
            spectral_config_snapshot=spectral_config_snapshot,
            latest_export_status=latest_export_status,
            result_bundle=result_bundle or {},
        )

        html_path = export_root / "formal_report.html"
        snapshot_path = export_root / "formal_report_snapshot.json"
        manifest_path = export_root / "report_manifest.json"

        html_path.write_text(_render_formal_report_html(snapshot), encoding="utf-8")
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = {
            "exported_at": timestamp.isoformat(),
            "report_version": REPORT_VERSION,
            "export_dir": str(export_root),
            "exported_files": [
                "formal_report.html",
                "formal_report_snapshot.json",
                "report_manifest.json",
            ],
            "data_sources": snapshot["data_sources"],
            "current_batch_id": snapshot["header"]["current_batch_id"],
            "compare_id": snapshot["header"]["compare_id"],
            "attribution_id": snapshot["header"]["attribution_id"],
            "pdf_status": "fallback_html_only",
            "delivery_audit": snapshot.get("delivery_audit", {}),
            "artifact_index": snapshot.get("delivery_audit", {}).get("artifact_index", {}),
            "network_validation_summary": snapshot.get("delivery_audit", {}).get("network_validation_summary", {}),
            "runtime_watchdog_summary": snapshot.get("delivery_audit", {}).get("runtime_watchdog_summary", {}),
            "runtime_service_summary": snapshot.get("delivery_audit", {}).get("runtime_service_summary", {}),
            "daemon_telemetry_summary": snapshot.get("delivery_audit", {}).get("daemon_telemetry_summary", {}),
            "supervisor_integration_summary": snapshot.get("delivery_audit", {}).get("supervisor_integration_summary", {}),
            "installable_runtime_summary": snapshot.get("delivery_audit", {}).get("installable_runtime_summary", {}),
            "runtime_deployment_summary": snapshot.get("delivery_audit", {}).get("runtime_deployment_summary", {}),
            "runtime_deployment_feedback_summary": snapshot.get("delivery_audit", {}).get("runtime_deployment_feedback_summary", {}),
            "clock_sync_summary": snapshot.get("delivery_audit", {}).get("clock_sync_summary", {}),
            "biomet_ambient_summary": snapshot.get("delivery_audit", {}).get("biomet_ambient_summary", {}),
            "trace_gas_summary": snapshot.get("delivery_audit", {}).get("trace_gas_summary", {}),
            "trace_gas_provenance": snapshot.get("delivery_audit", {}).get("trace_gas_provenance", {}),
            "official_raw_fixture_manifest": snapshot.get("delivery_audit", {}).get("official_raw_fixture_manifest", {}),
            "official_raw_fixture_detail": snapshot.get("delivery_audit", {}).get("official_raw_fixture_detail", {}),
            "eddypro_coverage_audit": snapshot.get("delivery_audit", {}).get("eddypro_coverage_audit", {}),
            "eddypro_computation_scope_audit": snapshot.get("delivery_audit", {}).get("eddypro_computation_scope_audit", {}),
            "eddypro_partial_capability_closure": snapshot.get("delivery_audit", {}).get("eddypro_partial_capability_closure", {}),
            "public_ec_acquisition_closure": snapshot.get("delivery_audit", {}).get("public_ec_acquisition_closure", {}),
            "public_ec_acquisition_summary": snapshot.get("delivery_audit", {}).get("public_ec_acquisition_summary", {}),
            "public_raw_sample_validation_package": snapshot.get("delivery_audit", {}).get(
                "public_raw_sample_validation_package",
                {},
            ),
            "public_raw_sample_summary": snapshot.get("delivery_audit", {}).get("public_raw_sample_summary", {}),
            "benchmark_summary": snapshot.get("delivery_audit", {}).get("benchmark_summary", {}),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "export_root": str(export_root),
            "summary_text": f"正式报告已导出（{timestamp:%Y-%m-%d %H:%M}）",
            "files": {
                "html": str(html_path),
                "snapshot": str(snapshot_path),
                "manifest": str(manifest_path),
            },
            "pdf_status": "fallback_html_only",
        }


def _write_report_files(*, json_path: Path, csv_path: Path, report_payload: dict) -> None:
    json_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    table_rows = report_payload.get("table_rows", [])
    table_headers = report_payload.get("table_headers", [])
    if table_rows and table_headers:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(table_headers)
            writer.writerows(table_rows)


def _build_formal_report_snapshot(
    *,
    generated_at: datetime,
    project_snapshot: dict[str, Any],
    site_snapshot: dict[str, Any],
    device_snapshots: list[dict[str, Any]],
    rp_result: Any | None,
    spectral_result: Any | None,
    eddypro_compare: dict[str, Any],
    attribution_result: dict[str, Any],
    rp_config_snapshot: dict[str, Any],
    spectral_config_snapshot: dict[str, Any],
    latest_export_status: str,
    result_bundle: dict[str, Any],
) -> dict[str, Any]:
    project_profile = dict(project_snapshot.get("profile", {}))
    project_workspace = dict(project_snapshot.get("workspace", {}))
    spectral_summary = dict(getattr(spectral_result, "summary", {}) or {})
    rp_summary = dict(getattr(rp_result, "summary", {}) or {})
    spectral_windows = list(getattr(spectral_result, "windows", []) or [])
    rp_windows = list(getattr(rp_result, "windows", []) or [])
    compare_summary = dict(eddypro_compare.get("summary_metrics", {}) or {})
    evidence_bundle = dict(getattr(spectral_result, "artifacts", {}).get("evidence_bundle", {}) or {}) if spectral_result else {}
    compare_files = dict(eddypro_compare.get("files", {}) or {})
    bundle_files = dict(result_bundle.get("files", {}) or {})
    result_manifest = _read_json_file(bundle_files.get("export_manifest", ""))
    artifact_index = _bundle_artifact_index(bundle_files)
    method_parity_matrix = dict(result_manifest.get("method_parity_matrix", {}) or {})
    network_validation_summary = dict(result_manifest.get("network_validation_summary", {}) or {})
    runtime_watchdog_summary = dict(result_manifest.get("runtime_watchdog_summary", {}) or {})
    runtime_service_summary = dict(result_manifest.get("runtime_service_summary", {}) or {})
    daemon_telemetry_summary = dict(result_manifest.get("daemon_telemetry_summary", {}) or {})
    supervisor_integration_summary = dict(result_manifest.get("supervisor_integration_summary", {}) or {})
    installable_runtime_summary = dict(result_manifest.get("installable_runtime_summary", {}) or {})
    runtime_deployment_summary = dict(result_manifest.get("runtime_deployment_summary", {}) or {})
    runtime_deployment_feedback_summary = dict(result_manifest.get("runtime_deployment_feedback_summary", {}) or {})
    clock_sync_summary = dict(result_manifest.get("clock_sync_summary", {}) or {})
    biomet_ambient_summary = dict(result_manifest.get("biomet_ambient_summary", {}) or {})
    fixture_pack_summary = dict(result_manifest.get("fixture_pack_summary", {}) or {})
    official_raw_fixture_manifest = dict(result_manifest.get("official_raw_fixture_manifest", {}) or {})
    official_raw_fixture_detail = dict(result_manifest.get("official_raw_fixture_detail", {}) or {})
    official_raw_acquisition_validation = dict(
        result_manifest.get("official_raw_acquisition_validation", {})
        or official_raw_fixture_detail.get("acquisition_validation", {})
        or {}
    )
    official_raw_evidence_pack = dict(result_manifest.get("official_raw_evidence_pack", {}) or {})
    official_raw_acceptance_run = dict(official_raw_evidence_pack.get("acceptance_run", {}) or {})
    official_raw_normalization = dict(official_raw_fixture_detail.get("normalization", {}) or {})
    official_raw_official_run_normalization = dict(
        result_manifest.get("official_raw_official_run_normalization", {})
        or official_raw_fixture_detail.get("official_run_normalization", {})
        or official_raw_evidence_pack.get("official_run_normalization", {})
        or {}
    )
    eddypro_source_inventory = dict(result_manifest.get("eddypro_source_inventory", {}) or {})
    eddypro_coverage_audit = dict(result_manifest.get("eddypro_coverage_audit", {}) or {})
    eddypro_computation_stress_suite = dict(
        result_manifest.get("eddypro_computation_stress_suite", {})
        or _read_json_file(bundle_files.get("eddypro_computation_stress_suite_artifact", ""))
    )
    eddypro_computation_surface = dict(
        result_manifest.get("eddypro_computation_surface", {})
        or eddypro_computation_stress_suite.get("computation_surface", {})
        or {}
    )
    eddypro_computation_scope_audit = dict(result_manifest.get("eddypro_computation_scope_audit", {}) or {})
    eddypro_surrogate_evidence_closure = dict(
        result_manifest.get("eddypro_surrogate_evidence_closure", {})
        or eddypro_coverage_audit.get("surrogate_evidence_closure", {})
        or {}
    )
    eddypro_release_gate = dict(result_manifest.get("eddypro_release_gate", {}) or {})
    eddypro_partial_capability_closure = dict(result_manifest.get("eddypro_partial_capability_closure", {}) or {})
    neon_hdf5_validation_package = dict(result_manifest.get("neon_hdf5_validation_package", {}) or {})
    neon_hdf5_fixture_profile = dict(result_manifest.get("neon_hdf5_fixture_profile", {}) or {})
    public_ec_acquisition_closure = dict(result_manifest.get("public_ec_acquisition_closure", {}) or {})
    public_ec_acquisition_runbook = dict(result_manifest.get("public_ec_acquisition_runbook", {}) or {})
    public_ec_acquisition_summary = dict(public_ec_acquisition_closure.get("summary", {}) or {})
    public_ec_acquisition_runbook_summary = dict(public_ec_acquisition_runbook.get("summary", {}) or {})
    public_ec_acquisition_claim_boundary = dict(public_ec_acquisition_closure.get("claim_boundary", {}) or {})
    eddypro_closure_gate = dict(result_manifest.get("eddypro_closure_gate", {}) or eddypro_coverage_audit.get("closure_gate", {}) or {})
    eddypro_closure_plan = dict(result_manifest.get("eddypro_closure_plan", {}) or eddypro_coverage_audit.get("closure_plan", {}) or {})
    raw_to_final_parity = dict(result_manifest.get("raw_to_final_parity", {}) or {})
    raw_to_final_trace_gas = dict(
        result_manifest.get("raw_to_final_trace_gas_parity", {})
        or raw_to_final_parity.get("trace_gas_parity", {})
        or {}
    )
    flux_correction_ledger_summary = dict(result_manifest.get("flux_correction_ledger_summary", {}) or {})
    trace_gas_summary = dict(result_manifest.get("trace_gas_summary", {}) or {})
    trace_gas_provenance = dict(
        result_manifest.get("trace_gas_provenance", {})
        or _read_json_file(bundle_files.get("trace_gas_provenance_artifact", ""))
    )
    spectral_assessment = dict(result_manifest.get("spectral_assessment", {}) or {})
    spectral_assessment_library = dict(result_manifest.get("spectral_assessment_library", {}) or {})
    delivery_audit = {
        "artifact_type": "formal_report_delivery_audit",
        "result_bundle_root": str(result_bundle.get("export_root", "")),
        "result_manifest_path": str(bundle_files.get("export_manifest", "")),
        "artifact_index": artifact_index,
        "method_artifact_keys": [
            key
            for key in [
                "method_rollup_artifact",
                "spectral_assessment_artifact",
                "spectral_binned_ensemble_csv",
                "spectral_full_windows_csv",
                "spectral_ogive_ensemble_csv",
                "spectral_assessment_library_artifact",
                "spectral_assessment_library_groups_csv",
                "spectral_assessment_library_bins_csv",
                "method_compare_artifact",
                "method_parity_matrix_artifact",
                "method_parity_matrix_csv",
                "footprint_2d_artifact",
                "footprint_2d_contour_svg",
                "footprint_2d_grid_csv",
                "footprint_geojson_artifact",
                "footprint_geotiff_artifact",
                "footprint_land_cover_overlay_artifact",
                "footprint_gis_validation_artifact",
                "performance_profile_artifact",
                "runtime_watchdog_artifact",
                "runtime_service_artifact",
                "daemon_telemetry_artifact",
                "supervisor_integration_artifact",
                "installable_runtime_artifact",
                "runtime_deployment_artifact",
                "runtime_deployment_install_systemd_sh",
                "runtime_deployment_rollback_systemd_sh",
                "runtime_deployment_install_windows_service_ps1",
                "runtime_deployment_rollback_windows_service_ps1",
                "runtime_deployment_feedback_artifact",
                "clock_sync_artifact",
                "flux_correction_ledger_artifact",
                "trace_gas_provenance_artifact",
                "reference_provenance_artifact",
                "fixture_pack_summary_artifact",
                "official_raw_fixture_manifest_artifact",
                "official_raw_fixture_detail_artifact",
                "official_raw_evidence_pack_artifact",
                "eddypro_source_inventory_artifact",
                "eddypro_coverage_audit_artifact",
                "eddypro_computation_stress_suite_artifact",
                "eddypro_computation_scope_audit_artifact",
                "eddypro_surrogate_evidence_closure_artifact",
                "eddypro_release_gate_artifact",
                "eddypro_partial_capability_closure_artifact",
                "neon_hdf5_validation_package_artifact",
                "neon_hdf5_fixture_profile_artifact",
                "public_ec_acquisition_closure_artifact",
                "public_ec_acquisition_runbook_artifact",
                "raw_to_final_parity_artifact",
                "network_validation_summary",
            ]
            if key in bundle_files
        ],
        "network_validation_summary": network_validation_summary,
        "runtime_watchdog_summary": runtime_watchdog_summary,
        "runtime_service_summary": runtime_service_summary,
        "daemon_telemetry_summary": daemon_telemetry_summary,
        "supervisor_integration_summary": supervisor_integration_summary,
        "installable_runtime_summary": installable_runtime_summary,
        "runtime_deployment_summary": runtime_deployment_summary,
        "runtime_deployment_feedback_summary": runtime_deployment_feedback_summary,
        "clock_sync_summary": clock_sync_summary,
        "biomet_ambient_summary": biomet_ambient_summary,
        "trace_gas_summary": trace_gas_summary,
        "trace_gas_provenance": trace_gas_provenance,
        "fixture_pack_summary": fixture_pack_summary,
        "official_raw_fixture_manifest": official_raw_fixture_manifest,
        "official_raw_fixture_detail": official_raw_fixture_detail,
        "official_raw_acquisition_validation": official_raw_acquisition_validation,
        "official_raw_evidence_pack": official_raw_evidence_pack,
        "result_manifest_summary": {
            "schema_target": result_manifest.get("schema_target", ""),
            "validation_status": result_manifest.get("network_validation_status", ""),
            "official_raw_fixture_detail_id": official_raw_fixture_detail.get("fixture_id", ""),
            "official_raw_fixture_detail_status": official_raw_fixture_detail.get("status", ""),
            "official_raw_fixture_detail_readiness": official_raw_fixture_detail.get("readiness_level", ""),
            "trace_gas_status": trace_gas_summary.get("status", ""),
            "trace_gas_ch4_profile_id": trace_gas_summary.get("coefficient_profile_id", ""),
            "trace_gas_ch4_source_file": trace_gas_summary.get("coefficient_profile_source_file", ""),
            "trace_gas_ch4_normalization_command": trace_gas_summary.get("coefficient_profile_normalization_command", ""),
            "trace_gas_n2o_profile_id": trace_gas_summary.get("n2o_coefficient_profile_id", ""),
            "trace_gas_n2o_source_file": trace_gas_summary.get("n2o_coefficient_profile_source_file", ""),
            "trace_gas_n2o_normalization_command": trace_gas_summary.get("n2o_coefficient_profile_normalization_command", ""),
            "trace_gas_provenance_status": trace_gas_provenance.get("status", ""),
            "official_raw_acquisition_status": official_raw_acquisition_validation.get("status", ""),
            "official_raw_acquisition_gate_status": official_raw_acquisition_validation.get("gate_status", ""),
            "official_raw_acquisition_missing_requirements": list(official_raw_acquisition_validation.get("missing_requirements", []) or []),
            "official_raw_evidence_pack_status": official_raw_evidence_pack.get("status", ""),
            "official_raw_evidence_pack_source_file_count": official_raw_evidence_pack.get("source_file_count", 0),
            "official_raw_evidence_pack_acceptance_status": result_manifest.get(
                "official_raw_evidence_pack_acceptance_status",
                official_raw_evidence_pack.get("acceptance_status", official_raw_acceptance_run.get("status", "not_run")),
            ),
            "official_raw_evidence_pack_acceptance_gate_status": result_manifest.get(
                "official_raw_evidence_pack_acceptance_gate_status",
                official_raw_evidence_pack.get("acceptance_gate_status", official_raw_acceptance_run.get("gate_status", "not_run")),
            ),
            "official_raw_evidence_pack_acceptance_command_count": result_manifest.get(
                "official_raw_evidence_pack_acceptance_command_count",
                official_raw_acceptance_run.get("command_count", 0),
            ),
            "official_raw_evidence_pack_acceptance_failed_count": result_manifest.get(
                "official_raw_evidence_pack_acceptance_failed_count",
                official_raw_acceptance_run.get("failed_count", 0),
            ),
            "official_raw_normalization_status": result_manifest.get("official_raw_normalization_status", official_raw_normalization.get("status", "")),
            "official_raw_normalization_time": result_manifest.get("official_raw_normalization_time", official_raw_normalization.get("normalization_time", "")),
            "official_raw_normalization_source_file": official_raw_normalization.get("source_file", ""),
            "official_raw_qc_mapping_strategy": result_manifest.get("official_raw_qc_mapping_strategy", official_raw_normalization.get("qc_mapping_strategy", "")),
            "official_raw_normalization_required_fields_present": official_raw_normalization.get("required_fields_present"),
            "official_raw_official_run_normalization_status": result_manifest.get(
                "official_raw_official_run_normalization_status",
                official_raw_official_run_normalization.get("status", ""),
            ),
            "official_raw_official_run_normalization_time": result_manifest.get(
                "official_raw_official_run_normalization_time",
                official_raw_official_run_normalization.get("normalization_time", ""),
            ),
            "official_raw_official_run_normalization_source_file": official_raw_official_run_normalization.get("source_file", ""),
            "official_raw_official_run_reference_json": result_manifest.get(
                "official_raw_official_run_reference_json",
                official_raw_official_run_normalization.get("reference_json", ""),
            ),
            "official_raw_official_run_provenance_json": result_manifest.get(
                "official_raw_official_run_provenance_json",
                official_raw_official_run_normalization.get("provenance_json", ""),
            ),
            "official_raw_official_run_qc_mapping_strategy": result_manifest.get(
                "official_raw_official_run_qc_mapping_strategy",
                official_raw_official_run_normalization.get("qc_mapping_strategy", ""),
            ),
            "can_claim_full_eddypro_parity": eddypro_coverage_audit.get("can_claim_full_eddypro_parity", False),
            "eddypro_computation_stress_suite_status": eddypro_computation_stress_suite.get("status", ""),
            "eddypro_computation_stress_pass_rate": eddypro_computation_stress_suite.get("pass_rate", 0.0),
            "eddypro_computation_stress_failed_case_count": eddypro_computation_stress_suite.get("failed_case_count", 0),
            "eddypro_computation_surface_status": eddypro_computation_surface.get("status", ""),
            "eddypro_computation_surface_ready_family_count": eddypro_computation_surface.get("ready_family_count", 0),
            "eddypro_computation_surface_blocked_family_count": eddypro_computation_surface.get("blocked_family_count", 0),
            "eddypro_computation_surface_required_families": list(
                eddypro_computation_surface.get("required_families", []) or []
            ),
            "eddypro_computation_surface_family_status": dict(
                eddypro_computation_surface.get("family_status", {}) or {}
            ),
            "eddypro_computation_scope_audit_status": eddypro_computation_scope_audit.get("status", ""),
            "can_claim_source_derived_computational_superiority": dict(
                eddypro_computation_scope_audit.get("claim_boundary", {}) or {}
            ).get("can_claim_source_derived_computational_superiority", False),
            "computation_core_algorithm_blocker_count": dict(
                eddypro_computation_scope_audit.get("scope_summary", {}) or {}
            ).get("core_algorithm_blocker_count", 0),
            "computation_deferred_non_computational_count": dict(
                eddypro_computation_scope_audit.get("scope_summary", {}) or {}
            ).get("non_computational_deferrable_count", 0),
            "can_claim_source_derived_functional_parity": result_manifest.get(
                "can_claim_source_derived_functional_parity",
                eddypro_coverage_audit.get("can_claim_source_derived_functional_parity", False),
            ),
            "eddypro_surrogate_evidence_closure_status": result_manifest.get(
                "eddypro_surrogate_evidence_closure_status",
                eddypro_surrogate_evidence_closure.get("status", ""),
            ),
            "eddypro_surrogate_accepted_item_count": eddypro_surrogate_evidence_closure.get("accepted_item_count", 0),
            "eddypro_surrogate_missing_item_count": eddypro_surrogate_evidence_closure.get("missing_item_count", 0),
            "eddypro_release_gate_status": eddypro_release_gate.get("status", ""),
            "can_release_full_eddypro_parity": eddypro_release_gate.get("can_release_full_eddypro_parity", False),
            "can_release_source_derived_functional_parity": result_manifest.get(
                "can_release_source_derived_functional_parity",
                eddypro_release_gate.get("can_release_source_derived_functional_parity", False),
            ),
            "can_release_source_derived_computational_superiority": result_manifest.get(
                "can_release_source_derived_computational_superiority",
                eddypro_release_gate.get("can_release_source_derived_computational_superiority", False),
            ),
            "source_derived_computation_gate_status": result_manifest.get(
                "source_derived_computation_gate_status",
                dict(eddypro_release_gate.get("computation_release_gate", {}) or {}).get("status", ""),
            ),
            "source_derived_computation_ci_exit_code": result_manifest.get(
                "source_derived_computation_ci_exit_code",
                eddypro_release_gate.get("source_derived_computation_ci_exit_code", 2),
            ),
            "eddypro_release_gate_ci_exit_code": eddypro_release_gate.get("ci_exit_code", 2),
            "eddypro_partial_capability_closure_status": eddypro_partial_capability_closure.get("status", ""),
            "eddypro_partial_capability_count": eddypro_partial_capability_closure.get("partial_capability_count", 0),
            "eddypro_ready_public_raw_candidate_count": dict(
                eddypro_partial_capability_closure.get("public_search_closure", {}) or {}
            ).get("ready_to_register_public_raw_candidate_count", 0),
            "neon_hdf5_validation_status": neon_hdf5_validation_package.get("status", ""),
            "neon_hdf5_fixture_profile_status": neon_hdf5_fixture_profile.get("status", ""),
            "neon_hdf5_can_register_public_engineering_fixture": dict(
                neon_hdf5_fixture_profile.get("registration_profile", {}) or {}
            ).get("can_register_as_public_engineering_fixture", False),
            "neon_hdf5_can_claim_eddypro_raw_to_final_parity": dict(
                neon_hdf5_fixture_profile.get("claim_boundary", {}) or {}
            ).get("can_claim_eddypro_raw_to_final_parity", False),
            "public_ec_acquisition_closure_status": public_ec_acquisition_closure.get("status", ""),
            "public_ec_acquisition_runbook_status": public_ec_acquisition_runbook.get("status", ""),
            "public_ec_acquisition_automatic_download_candidate_count": public_ec_acquisition_runbook_summary.get(
                "automatic_download_candidate_count",
                0,
            ),
            "public_ec_acquisition_candidate_count": public_ec_acquisition_summary.get("candidate_count", 0),
            "public_ec_acquisition_engineering_validation_pass_count": public_ec_acquisition_summary.get(
                "engineering_validation_pass_count",
                0,
            ),
            "public_ec_acquisition_ready_to_register_candidate_count": public_ec_acquisition_summary.get(
                "ready_to_register_candidate_count",
                0,
            ),
            "public_ec_acquisition_can_claim_engineering_validation": public_ec_acquisition_claim_boundary.get(
                "can_claim_public_raw_engineering_validation",
                False,
            ),
            "public_ec_acquisition_can_claim_eddypro_raw_to_final_parity": public_ec_acquisition_claim_boundary.get(
                "can_claim_eddypro_raw_to_final_parity",
                False,
            ),
            "public_ec_acquisition_can_release_full_eddypro_parity": public_ec_acquisition_claim_boundary.get(
                "can_release_full_eddypro_parity",
                False,
            ),
            "eddypro_closure_gate_status": eddypro_closure_gate.get("status", ""),
            "eddypro_closure_open_item_count": eddypro_closure_gate.get("open_item_count", 0),
            "eddypro_closure_top_priority": eddypro_closure_gate.get("top_priority", ""),
        },
        "eddypro_source_inventory": eddypro_source_inventory,
        "eddypro_coverage_audit": eddypro_coverage_audit,
        "eddypro_computation_stress_suite": eddypro_computation_stress_suite,
        "eddypro_computation_surface": eddypro_computation_surface,
        "eddypro_computation_scope_audit": eddypro_computation_scope_audit,
        "eddypro_computation_summary": {
            "status": eddypro_computation_scope_audit.get("status", ""),
            "stress_suite_status": eddypro_computation_stress_suite.get("status", ""),
            "stress_suite_pass_rate": eddypro_computation_stress_suite.get("pass_rate", 0.0),
            "stress_suite_failed_case_count": eddypro_computation_stress_suite.get("failed_case_count", 0),
            "computation_surface_status": eddypro_computation_surface.get("status", ""),
            "computation_surface_ready_family_count": eddypro_computation_surface.get("ready_family_count", 0),
            "computation_surface_blocked_family_count": eddypro_computation_surface.get("blocked_family_count", 0),
            "computation_surface_required_families": list(
                eddypro_computation_surface.get("required_families", []) or []
            ),
            "computation_surface_family_status": dict(
                eddypro_computation_surface.get("family_status", {}) or {}
            ),
            "can_claim_source_derived_computational_superiority": dict(
                eddypro_computation_scope_audit.get("claim_boundary", {}) or {}
            ).get("can_claim_source_derived_computational_superiority", False),
            "core_algorithm_blocker_count": dict(
                eddypro_computation_scope_audit.get("scope_summary", {}) or {}
            ).get("core_algorithm_blocker_count", 0),
            "non_computational_deferrable_count": dict(
                eddypro_computation_scope_audit.get("scope_summary", {}) or {}
            ).get("non_computational_deferrable_count", 0),
        },
        "eddypro_surrogate_evidence_closure": eddypro_surrogate_evidence_closure,
        "eddypro_release_gate": eddypro_release_gate,
        "eddypro_partial_capability_closure": eddypro_partial_capability_closure,
        "neon_hdf5_validation_package": neon_hdf5_validation_package,
        "neon_hdf5_fixture_profile": neon_hdf5_fixture_profile,
        "neon_hdf5_summary": {
            "validation_status": neon_hdf5_validation_package.get("status", ""),
            "fixture_profile_status": neon_hdf5_fixture_profile.get("status", ""),
            "row_count": neon_hdf5_validation_package.get("row_count", 0),
            "rp_window_count": neon_hdf5_validation_package.get("rp_window_count", 0),
            "can_register_public_engineering_fixture": dict(
                neon_hdf5_fixture_profile.get("registration_profile", {}) or {}
            ).get("can_register_as_public_engineering_fixture", False),
            "can_claim_eddypro_raw_to_final_parity": dict(
                neon_hdf5_fixture_profile.get("claim_boundary", {}) or {}
            ).get("can_claim_eddypro_raw_to_final_parity", False),
        },
        "public_ec_acquisition_closure": public_ec_acquisition_closure,
        "public_ec_acquisition_runbook": public_ec_acquisition_runbook,
        "public_ec_acquisition_summary": {
            "status": public_ec_acquisition_closure.get("status", ""),
            "runbook_status": public_ec_acquisition_runbook.get("status", ""),
            "automatic_download_candidate_count": public_ec_acquisition_runbook_summary.get(
                "automatic_download_candidate_count",
                0,
            ),
            "candidate_count": public_ec_acquisition_summary.get("candidate_count", 0),
            "downloaded_candidate_count": public_ec_acquisition_summary.get("downloaded_candidate_count", 0),
            "engineering_validation_pass_count": public_ec_acquisition_summary.get(
                "engineering_validation_pass_count",
                0,
            ),
            "ready_to_register_candidate_count": public_ec_acquisition_summary.get("ready_to_register_candidate_count", 0),
            "can_claim_public_raw_engineering_validation": public_ec_acquisition_claim_boundary.get(
                "can_claim_public_raw_engineering_validation",
                False,
            ),
            "can_claim_eddypro_raw_to_final_parity": public_ec_acquisition_claim_boundary.get(
                "can_claim_eddypro_raw_to_final_parity",
                False,
            ),
            "can_release_full_eddypro_parity": public_ec_acquisition_claim_boundary.get("can_release_full_eddypro_parity", False),
        },
        "eddypro_closure_gate": eddypro_closure_gate,
        "eddypro_closure_plan": eddypro_closure_plan,
        "raw_to_final_parity": raw_to_final_parity,
        "raw_to_final_trace_gas_parity": raw_to_final_trace_gas,
        "flux_correction_ledger_summary": flux_correction_ledger_summary,
        "spectral_assessment": spectral_assessment,
        "spectral_assessment_library": spectral_assessment_library,
        "benchmark_summary": {
            "benchmark_status": result_manifest.get("benchmark_status", ""),
            "benchmark_reference_id": result_manifest.get("benchmark_reference_id", ""),
            "pass_rate": result_manifest.get("pass_rate", 0.0),
            "failed_fields": result_manifest.get("failed_fields", []),
        },
        "method_parity_matrix": {
            "status_counts": dict(method_parity_matrix.get("status_counts", {}) or {}),
            "metadata_coverage": dict(method_parity_matrix.get("metadata_coverage", {}) or {}),
            "not_reported_families": list(method_parity_matrix.get("not_reported_families", []) or []),
        },
    }
    total_tf_count = sum(
        1
        for window in spectral_windows
        if getattr(window, "total_transfer_function_freq", None) and getattr(window, "total_transfer_function_value", None)
    )
    rp_grade_counter = Counter(str(getattr(window, "qc_grade", "")) for window in rp_windows if str(getattr(window, "qc_grade", "")).strip())
    rp_reason_counter = Counter(
        reason.strip()
        for window in rp_windows
        for reason in list(getattr(window, "qc_reasons", []) or [])[:4]
        if str(reason).strip()
    )
    provenance_notes = list(
        dict.fromkeys(
            note.strip()
            for window in spectral_windows
            for note in list(getattr(window, "provenance_notes", []) or [])[:4]
            if str(note).strip()
        )
    )
    model_version = next((str(getattr(window, "model_version", "")).strip() for window in spectral_windows if str(getattr(window, "model_version", "")).strip()), "")

    header = {
        "title": "Gas EC Studio 正式结果报告",
        "project_name": project_profile.get("name") or project_workspace.get("overview", {}).get("project_name", "当前项目"),
        "site_name": site_snapshot.get("station_name") or project_workspace.get("site_info", {}).get("station_name", "当前站点"),
        "generated_at": generated_at.isoformat(),
        "generated_at_text": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "current_batch_id": _batch_id(spectral_result, rp_result),
        "report_version": REPORT_VERSION,
        "compare_id": str(eddypro_compare.get("compare_id", "")),
        "attribution_id": str(attribution_result.get("attribution_id", "")),
    }

    sections = [
        {
            "id": "run-summary",
            "title": "运行摘要",
            "intro": "汇总 RP、谱修正/QC、导出状态与当前批次核心指标。",
            "cards": [
                {"label": "RP 运行状态", "value": _run_status(rp_result), "note": f"窗口数：{len(rp_windows)}"},
                {"label": "Spectral/QC 状态", "value": _run_status(spectral_result), "note": f"窗口数：{len(spectral_windows)}"},
                {"label": "有效窗口数", "value": str(int(rp_summary.get("valid_window_count", len(rp_windows)) if rp_result else len(spectral_windows))), "note": "优先使用 RP 有效窗口统计"},
                {"label": "平均 QC 分数", "value": _fmt(rp_summary.get("average_qc_score"), 3), "note": "来自 RP 统一 QC 矩阵"},
                {"label": "平均 correction factor", "value": _fmt(spectral_summary.get("average_correction_factor"), 3), "note": "来自 FCC / 谱修正结果"},
                {"label": "最近导出状态", "value": latest_export_status or "尚未导出", "note": "导出链路最终状态"},
            ],
        },
        {
            "id": "project-site",
            "title": "项目与站点信息",
            "intro": "记录项目、站点、设备、采样链路与配置快照摘要，便于打印与归档。",
            "tables": [
                {
                    "title": "项目与站点基础信息",
                    "headers": ["项目", "内容"],
                    "rows": [
                        ["项目名称", header["project_name"]],
                        ["项目代码", str(project_profile.get("code", "--"))],
                        ["负责人", str(project_profile.get("principal", "--"))],
                        ["站点名称", header["site_name"]],
                        ["站点代码", str(site_snapshot.get("station_code", "--"))],
                        ["站点位置", str(site_snapshot.get("location", "--"))],
                        ["时区", str(site_snapshot.get("timezone", "--"))],
                    ],
                },
                {
                    "title": "设备摘要",
                    "headers": ["设备", "串口/ID", "状态"],
                    "rows": [
                        [
                            str(device.get("label", "--")),
                            f"{device.get('port', '--')} / {device.get('device_id', '--')}",
                            str(device.get("status", "--")),
                        ]
                        for device in device_snapshots
                    ]
                    or [["当前无设备快照", "--", "--"]],
                },
                {
                    "title": "采样链路摘要",
                    "headers": ["链路项", "当前值"],
                    "rows": [
                        ["tube_length_m", str(project_workspace.get("sampling_chain", {}).get("tube_length_m", "--"))],
                        ["tube_diameter_mm", str(project_workspace.get("sampling_chain", {}).get("tube_diameter_mm", "--"))],
                        ["flow_lpm", str(project_workspace.get("sampling_chain", {}).get("flow_lpm", "--"))],
                        ["tube_material", str(project_workspace.get("sampling_chain", {}).get("tube_material", "--"))],
                        ["chain_note", str(project_workspace.get("sampling_chain", {}).get("chain_note", "--"))],
                    ],
                },
                {
                    "title": "配置快照摘要",
                    "headers": ["配置项", "当前值"],
                    "rows": [
                        ["RP sample_hz", str(rp_config_snapshot.get("sample_hz", "--"))],
                        ["RP block_minutes", str(rp_config_snapshot.get("block_minutes", "--"))],
                        ["Spectral sample_hz", str(spectral_config_snapshot.get("timing", {}).get("sample_hz", "--"))],
                        ["Spectral block_minutes", str(spectral_config_snapshot.get("timing", {}).get("block_minutes", "--"))],
                        ["Spectral transfer model", str(spectral_config_snapshot.get("transfer_function", {}).get("model", "--"))],
                    ],
                },
            ],
        },
        {
            "id": "rp-summary",
            "title": "RP 结果摘要",
            "intro": "基于当前 RP 真实运行结果生成的窗口级统计摘要。",
            "tables": [
                {
                    "title": "RP 核心指标",
                    "headers": ["指标", "数值"],
                    "rows": [
                        ["窗口数", str(len(rp_windows))],
                        ["平均 lag", _fmt(rp_summary.get("average_lag_seconds"), 3)],
                        ["平均 density corrected flux", _fmt(rp_summary.get("average_density_corrected_flux"), 6)],
                        ["平均 stationarity_score", _fmt(rp_summary.get("average_stationarity_score"), 3)],
                        ["平均 turbulence_score", _fmt(rp_summary.get("average_turbulence_score"), 3)],
                        ["average_ustar", _fmt(rp_summary.get("average_ustar"), 3)],
                    ],
                },
                {
                    "title": "RP QC 分布",
                    "headers": ["QC 等级", "窗口数"],
                    "rows": [[grade, str(count)] for grade, count in sorted(rp_grade_counter.items())] or [["当前无 RP 结果", "0"]],
                },
                {
                    "title": "RP QC 原因摘要",
                    "headers": ["原因", "出现次数"],
                    "rows": [[reason, str(count)] for reason, count in rp_reason_counter.most_common(8)] or [["当前无 RP 结果", "0"]],
                },
            ],
        },
        {
            "id": "spectral-summary",
            "title": "FCC / 谱修正摘要",
            "intro": "消费现有 FCC provenance 与谱修正结果，不新增算法逻辑。",
            "tables": [
                {
                    "title": "谱修正核心指标",
                    "headers": ["指标", "数值"],
                    "rows": [
                        ["average_correction_factor", _fmt(spectral_summary.get("average_correction_factor"), 3)],
                        ["average_tube_component", _fmt(spectral_summary.get("average_tube_component"), 3)],
                        ["average_separation_component", _fmt(spectral_summary.get("average_separation_component"), 3)],
                        ["average_path_component", _fmt(spectral_summary.get("average_path_component"), 3)],
                        ["average_phase_component", _fmt(spectral_summary.get("average_phase_component"), 3)],
                        ["model_version", model_version or "--"],
                    ],
                },
                {
                    "title": "provenance 与总传递函数摘要",
                    "headers": ["项目", "说明"],
                    "rows": [
                        ["provenance_notes", "；".join(provenance_notes[:4]) if provenance_notes else "当前无分项修正说明"],
                        ["total transfer function", f"共有 {total_tf_count} 个窗口含真实总传递函数序列"],
                        [
                            "effective cutoff",
                            _format_mapping(getattr(spectral_windows[0], "effective_cutoff_info", {})) if spectral_windows else "当前无 Spectral 结果",
                        ],
                    ],
                },
            ],
        },
        {
            "id": "eddypro-summary",
            "title": "EddyPro 对标摘要",
            "intro": "若存在对标结果，则展示当前批次与参考结果的窗口匹配与偏差摘要。",
            "tables": [
                {
                    "title": "对标结果",
                    "headers": ["指标", "数值"],
                    "rows": (
                        [
                            ["current_window_count", str(compare_summary.get("current_window_count", 0))],
                            ["reference_window_count", str(compare_summary.get("reference_window_count", 0))],
                            ["matched_window_count", str(compare_summary.get("matched_window_count", 0))],
                            ["avg_lag_delta", _fmt(compare_summary.get("avg_lag_delta"), 3)],
                            ["avg_flux_delta", _fmt(compare_summary.get("avg_flux_delta"), 6)],
                            ["avg_correction_factor_delta", _fmt(compare_summary.get("avg_correction_factor_delta"), 4)],
                            ["qc_match_ratio", _fmt_ratio(compare_summary.get("qc_match_ratio"))],
                            ["risk_summary", "；".join(list(eddypro_compare.get("risk_summary", []))[:4]) or "--"],
                        ]
                        if eddypro_compare.get("status") == "ready"
                        else [["状态", "当前无对标结果"]]
                    ),
                }
            ],
        },
        {
            "id": "attribution-summary",
            "title": "差异自动归因",
            "intro": "若存在归因结果，则展示主因、次因、风险等级与窗口级摘要。",
            "tables": [
                {
                    "title": "归因摘要",
                    "headers": ["项目", "内容"],
                    "rows": (
                        [
                            ["dominant_causes", "；".join(list(attribution_result.get("dominant_causes", []))[:6]) or "--"],
                            ["secondary_causes", "；".join(list(attribution_result.get("secondary_causes", []))[:6]) or "--"],
                            ["risk_level", str(attribution_result.get("risk_level", "--"))],
                            ["summary_text", str(attribution_result.get("summary_text", "--"))],
                            ["notes", "；".join(list(attribution_result.get("notes", []))[:4]) or "--"],
                        ]
                        if attribution_result.get("status") == "ready"
                        else [["状态", "当前无归因结果"]]
                    ),
                },
                {
                    "title": "前 10 项窗口归因",
                    "headers": ["窗口", "主因", "次因 / 建议"],
                    "rows": (
                        [
                            [
                                str(row.get("window_key", "--")),
                                str(row.get("dominant_cause", "--")),
                                f"{'；'.join(row.get('secondary_causes', [])) or '--'} / {row.get('recommendation', '--')}",
                            ]
                            for row in list(attribution_result.get("window_rows", []))[:10]
                        ]
                        if attribution_result.get("status") == "ready"
                        else [["--", "--", "当前无归因结果"]]
                    ),
                },
            ],
        },
        {
            "id": "delivery-audit",
            "title": "交付链审计",
            "intro": "核对正式报告、result manifest、method artifact、network validation 与交付包所需文件的一致性。",
            "tables": [
                {
                    "title": "关键交付字段",
                    "headers": ["字段", "当前值"],
                    "rows": [
                        ["result_bundle_root", delivery_audit["result_bundle_root"] or "--"],
                        ["schema_target", str(network_validation_summary.get("schema_target", result_manifest.get("schema_target", "--")))],
                        ["network_validation_status", str(network_validation_summary.get("validation_status", result_manifest.get("network_validation_status", "--")))],
                        ["network_missing_fields", json.dumps(network_validation_summary.get("missing_fields", result_manifest.get("network_missing_fields", [])), ensure_ascii=False)],
                        ["runtime_watchdog_status", str(runtime_watchdog_summary.get("status", "--"))],
                        ["runtime_watchdog_profile", str(runtime_watchdog_summary.get("profile_id", "--"))],
                        ["runtime_watchdog_fail_count", str(runtime_watchdog_summary.get("fail_count", "--"))],
                        ["runtime_service_status", str(runtime_service_summary.get("status", "--"))],
                        ["runtime_service_delivery_state", str(runtime_service_summary.get("delivery_state", "--"))],
                        ["runtime_service_quarantine_count", str(len(runtime_service_summary.get("quarantine_records", []) or []))],
                        ["daemon_telemetry_status", str(daemon_telemetry_summary.get("status", "--"))],
                        ["target_host_validation_status", str(dict(daemon_telemetry_summary.get("target_host_validation", {}) or {}).get("status", "--"))],
                        ["target_host_validation_gate", str(dict(daemon_telemetry_summary.get("target_host_validation", {}) or {}).get("gate_status", "--"))],
                        ["target_host_id", str(dict(daemon_telemetry_summary.get("target_host_validation", {}) or {}).get("target_host_id", "--"))],
                        ["supervisor_state", str(dict(daemon_telemetry_summary.get("supervisor", {}) or {}).get("state", "--"))],
                        ["supervisor_integration_status", str(supervisor_integration_summary.get("status", "--"))],
                        ["os_supervisor_state", str(dict(supervisor_integration_summary.get("service_status", {}) or {}).get("state", "--"))],
                        ["watchdog_provider_status", str(dict(supervisor_integration_summary.get("hardware_watchdog_provider", {}) or {}).get("status", "--"))],
                        ["installable_runtime_status", str(installable_runtime_summary.get("status", "--"))],
                        ["installable_runtime_targets", json.dumps(installable_runtime_summary.get("os_targets", []), ensure_ascii=False)],
                        ["runtime_deployment_status", str(runtime_deployment_summary.get("status", "--"))],
                        ["runtime_deployment_execution_mode", str(runtime_deployment_summary.get("execution_mode", "--"))],
                        ["runtime_deployment_feedback_status", str(runtime_deployment_feedback_summary.get("status", "--"))],
                        ["runtime_deployment_feedback_service_state", str(dict(runtime_deployment_feedback_summary.get("service_status", {}) or {}).get("state", "--"))],
                        ["ptp_lock_status", str(dict(daemon_telemetry_summary.get("ptp_servo", {}) or {}).get("status", "--"))],
                        ["clock_discipline_status", str(dict(daemon_telemetry_summary.get("clock_discipline", {}) or {}).get("status", "--"))],
                        ["clock_discipline_offset_ns", str(dict(daemon_telemetry_summary.get("clock_discipline", {}) or {}).get("max_abs_offset_ns", "--"))],
                        ["hardware_watchdog_status", str(dict(daemon_telemetry_summary.get("hardware_watchdog", {}) or {}).get("status", "--"))],
                        ["clock_sync_status", str(clock_sync_summary.get("status", "--"))],
                        ["biomet_ambient_status", str(biomet_ambient_summary.get("status", "--"))],
                        ["biomet_ambient_applied_windows", str(biomet_ambient_summary.get("applied_window_count", "--"))],
                        ["biomet_ambient_fields", json.dumps(biomet_ambient_summary.get("applied_fields", {}), ensure_ascii=False)],
                        ["flux_correction_ledger_status", str(flux_correction_ledger_summary.get("status", "--"))],
                        ["flux_correction_ledger_windows", str(flux_correction_ledger_summary.get("ledger_window_count", "--"))],
                        ["trace_gas_status", str(trace_gas_summary.get("status", "--"))],
                        ["trace_gas_ch4_profile", str(trace_gas_summary.get("coefficient_profile_id", "--"))],
                        ["trace_gas_ch4_source", str(trace_gas_summary.get("coefficient_profile_source_file", "--"))],
                        ["trace_gas_ch4_normalization", str(trace_gas_summary.get("coefficient_profile_normalization_command", "--"))],
                        ["trace_gas_n2o_profile", str(trace_gas_summary.get("n2o_coefficient_profile_id", "--"))],
                        ["trace_gas_n2o_source", str(trace_gas_summary.get("n2o_coefficient_profile_source_file", "--"))],
                        ["trace_gas_n2o_normalization", str(trace_gas_summary.get("n2o_coefficient_profile_normalization_command", "--"))],
                        ["trace_gas_provenance_artifact_status", str(trace_gas_provenance.get("status", "--"))],
                        ["spectral_assessment_status", str(spectral_assessment.get("status", "--"))],
                        ["spectral_assessment_bins", str(dict(spectral_assessment.get("binned_ensemble", {}) or {}).get("bin_count", "--"))],
                        ["spectral_full_window_rows", str(spectral_assessment.get("full_window_row_count", "--"))],
                        ["spectral_library_status", str(spectral_assessment_library.get("status", "--"))],
                        ["spectral_library_groups", str(spectral_assessment_library.get("group_count", "--"))],
                        ["spectral_library_windows", str(spectral_assessment_library.get("window_count", "--"))],
                        ["fixture_pack_status", str(fixture_pack_summary.get("status", "--"))],
                        ["fixture_pack_real_windows", str(fixture_pack_summary.get("real_reference_window_count", "--"))],
                        ["fixture_pack_protocol_rows", str(fixture_pack_summary.get("protocol_validation_row_count", "--"))],
                        ["official_raw_fixture_status", str(official_raw_fixture_manifest.get("status", "--"))],
                        ["official_raw_ready_count", str(official_raw_fixture_manifest.get("official_raw_to_final_ready_count", "--"))],
                        ["registered_raw_to_final_fixtures", str(official_raw_fixture_manifest.get("registered_raw_to_final_fixture_count", "--"))],
                        ["missing_official_bundles", str(official_raw_fixture_manifest.get("missing_official_bundle_count", "--"))],
                        ["official_raw_acquisition_status", str(official_raw_acquisition_validation.get("status", "--"))],
                        ["official_raw_acquisition_gate_status", str(official_raw_acquisition_validation.get("gate_status", "--"))],
                        ["official_raw_acquisition_missing", json.dumps(official_raw_acquisition_validation.get("missing_requirements", []), ensure_ascii=False)],
                        ["official_raw_evidence_pack_status", str(official_raw_evidence_pack.get("status", "--"))],
                        ["official_raw_evidence_pack_files", f"{official_raw_evidence_pack.get('present_source_file_count', '--')}/{official_raw_evidence_pack.get('source_file_count', '--')}"],
                        ["official_raw_acceptance_status", str(official_raw_evidence_pack.get("acceptance_status", official_raw_acceptance_run.get("status", "--")))],
                        ["official_raw_acceptance_commands", f"{official_raw_acceptance_run.get('passed_count', 0)}/{official_raw_acceptance_run.get('command_count', 0)} pass; failed={official_raw_acceptance_run.get('failed_count', 0)}"],
                        ["official_raw_normalization_status", str(official_raw_normalization.get("status", "--"))],
                        ["official_raw_normalization_time", str(official_raw_normalization.get("normalization_time", "--"))],
                        ["official_raw_qc_mapping", str(official_raw_normalization.get("qc_mapping_strategy", "--"))],
                        ["official_run_normalization_status", str(official_raw_official_run_normalization.get("status", "--"))],
                        ["official_run_normalization_time", str(official_raw_official_run_normalization.get("normalization_time", "--"))],
                        ["official_run_qc_mapping", str(official_raw_official_run_normalization.get("qc_mapping_strategy", "--"))],
                        ["raw_to_final_trace_gas_status", str(raw_to_final_trace_gas.get("status", "--"))],
                        ["raw_to_final_trace_gas_pass_rate", _fmt(raw_to_final_trace_gas.get("pass_rate"), 3)],
                        ["raw_to_final_trace_gas_profile", str(raw_to_final_trace_gas.get("coefficient_profile_id", "--"))],
                        ["eddypro_coverage_audit_status", str(eddypro_coverage_audit.get("status", "--"))],
                        ["eddypro_coverage_completion_score", _fmt(dict(eddypro_coverage_audit.get("capability_summary", {}) or {}).get("completion_score"), 3)],
                        ["can_claim_full_eddypro_parity", str(eddypro_coverage_audit.get("can_claim_full_eddypro_parity", False))],
                        ["eddypro_computation_stress_suite_status", str(eddypro_computation_stress_suite.get("status", "--"))],
                        ["eddypro_computation_stress_pass_rate", _fmt(eddypro_computation_stress_suite.get("pass_rate"), 3)],
                        ["eddypro_computation_stress_failed_cases", str(eddypro_computation_stress_suite.get("failed_case_count", "--"))],
                        ["eddypro_computation_surface_status", str(eddypro_computation_surface.get("status", "--"))],
                        [
                            "eddypro_computation_surface_families",
                            (
                                f"ready={eddypro_computation_surface.get('ready_family_count', '--')}; "
                                f"blocked={eddypro_computation_surface.get('blocked_family_count', '--')}"
                            ),
                        ],
                        ["eddypro_computation_scope_audit_status", str(eddypro_computation_scope_audit.get("status", "--"))],
                        [
                            "can_claim_source_derived_computational_superiority",
                            str(
                                dict(eddypro_computation_scope_audit.get("claim_boundary", {}) or {}).get(
                                    "can_claim_source_derived_computational_superiority",
                                    False,
                                )
                            ),
                        ],
                        [
                            "computation_scope_counts",
                            (
                                f"core_blockers={dict(eddypro_computation_scope_audit.get('scope_summary', {}) or {}).get('core_algorithm_blocker_count', 0)}; "
                                f"support_blockers={dict(eddypro_computation_scope_audit.get('scope_summary', {}) or {}).get('supporting_algorithm_blocker_count', 0)}; "
                                f"deferred={dict(eddypro_computation_scope_audit.get('scope_summary', {}) or {}).get('non_computational_deferrable_count', 0)}"
                            ),
                        ],
                        [
                            "can_claim_source_derived_functional_parity",
                            str(
                                result_manifest.get(
                                    "can_claim_source_derived_functional_parity",
                                    eddypro_coverage_audit.get("can_claim_source_derived_functional_parity", False),
                                )
                            ),
                        ],
                        ["eddypro_surrogate_evidence_closure_status", str(eddypro_surrogate_evidence_closure.get("status", "--"))],
                        ["eddypro_surrogate_items", f"{eddypro_surrogate_evidence_closure.get('accepted_item_count', '--')} accepted / {eddypro_surrogate_evidence_closure.get('missing_item_count', '--')} missing"],
                        ["eddypro_release_gate_status", str(eddypro_release_gate.get("status", "--"))],
                        ["can_release_full_eddypro_parity", str(eddypro_release_gate.get("can_release_full_eddypro_parity", False))],
                        [
                            "can_release_source_derived_functional_parity",
                            str(
                                result_manifest.get(
                                    "can_release_source_derived_functional_parity",
                                    eddypro_release_gate.get("can_release_source_derived_functional_parity", False),
                                )
                            ),
                        ],
                        [
                            "can_release_source_derived_computational_superiority",
                            str(
                                result_manifest.get(
                                    "can_release_source_derived_computational_superiority",
                                    eddypro_release_gate.get(
                                        "can_release_source_derived_computational_superiority",
                                        False,
                                    ),
                                )
                            ),
                        ],
                        [
                            "source_derived_computation_gate_status",
                            str(
                                result_manifest.get(
                                    "source_derived_computation_gate_status",
                                    dict(eddypro_release_gate.get("computation_release_gate", {}) or {}).get(
                                        "status",
                                        "--",
                                    ),
                                )
                            ),
                        ],
                        ["eddypro_partial_capability_closure_status", str(eddypro_partial_capability_closure.get("status", "--"))],
                        ["eddypro_partial_capability_count", str(eddypro_partial_capability_closure.get("partial_capability_count", "--"))],
                        ["public_ec_acquisition_closure_status", str(public_ec_acquisition_closure.get("status", "--"))],
                        [
                            "public_ec_engineering_validation",
                            (
                                f"pass={public_ec_acquisition_summary.get('engineering_validation_pass_count', 0)}; "
                                f"candidates={public_ec_acquisition_summary.get('candidate_count', 0)}; "
                                f"ready_to_register={public_ec_acquisition_summary.get('ready_to_register_candidate_count', 0)}"
                            ),
                        ],
                        [
                            "public_ec_claim_boundary",
                            (
                                f"engineering={public_ec_acquisition_claim_boundary.get('can_claim_public_raw_engineering_validation', False)}; "
                                f"raw_to_final={public_ec_acquisition_claim_boundary.get('can_claim_eddypro_raw_to_final_parity', False)}; "
                                f"full={public_ec_acquisition_claim_boundary.get('can_release_full_eddypro_parity', False)}"
                            ),
                        ],
                        [
                            "eddypro_ready_public_raw_candidates",
                            str(
                                dict(eddypro_partial_capability_closure.get("public_search_closure", {}) or {}).get(
                                    "ready_to_register_public_raw_candidate_count",
                                    "--",
                                )
                            ),
                        ],
                        ["eddypro_closure_gate_status", str(eddypro_closure_gate.get("status", "--"))],
                        ["eddypro_closure_open_items", str(eddypro_closure_gate.get("open_item_count", "--"))],
                        ["eddypro_closure_top_priority", str(eddypro_closure_gate.get("top_priority", "--"))],
                        [
                            "eddypro_closure_next_actions",
                            json.dumps(
                                [
                                    {
                                        "closure_id": item.get("closure_id", ""),
                                        "priority": item.get("priority", ""),
                                        "next_action": item.get("next_action", ""),
                                    }
                                    for item in list(eddypro_closure_plan.get("next_actions", []) or [])[:3]
                                ],
                                ensure_ascii=False,
                            ),
                        ],
                        ["benchmark_status", str(delivery_audit["benchmark_summary"].get("benchmark_status", ""))],
                        ["benchmark_reference_id", str(delivery_audit["benchmark_summary"].get("benchmark_reference_id", ""))],
                        ["method_metadata_coverage", json.dumps(delivery_audit["method_parity_matrix"].get("metadata_coverage", {}), ensure_ascii=False)],
                    ],
                },
                {
                    "title": "关键 artifact 索引",
                    "headers": ["artifact", "存在", "路径"],
                    "rows": [
                        [
                            key,
                            "yes" if payload.get("exists") else "no",
                            str(payload.get("path", "")),
                        ]
                        for key, payload in artifact_index.items()
                        if key
                        in {
                            "export_manifest",
                            "method_parity_matrix_artifact",
                            "method_parity_matrix_csv",
                            "spectral_assessment_artifact",
                            "spectral_binned_ensemble_csv",
                            "spectral_full_windows_csv",
                            "spectral_ogive_ensemble_csv",
                            "spectral_assessment_library_artifact",
                            "spectral_assessment_library_groups_csv",
                            "spectral_assessment_library_bins_csv",
                            "footprint_2d_contour_svg",
                            "footprint_2d_grid_csv",
                            "footprint_geojson_artifact",
                            "footprint_geotiff_artifact",
                            "footprint_land_cover_overlay_artifact",
                            "footprint_gis_validation_artifact",
                            "performance_profile_artifact",
                            "runtime_watchdog_artifact",
                            "runtime_service_artifact",
                            "daemon_telemetry_artifact",
                            "supervisor_integration_artifact",
                            "installable_runtime_artifact",
                            "runtime_deployment_artifact",
                            "runtime_deployment_feedback_artifact",
                            "clock_sync_artifact",
                            "flux_correction_ledger_artifact",
                            "fixture_pack_summary_artifact",
                            "official_raw_fixture_manifest_artifact",
                            "official_raw_evidence_pack_artifact",
                            "eddypro_source_inventory_artifact",
                            "eddypro_coverage_audit_artifact",
                            "eddypro_computation_stress_suite_artifact",
                            "eddypro_computation_scope_audit_artifact",
                            "eddypro_surrogate_evidence_closure_artifact",
                            "eddypro_release_gate_artifact",
                            "raw_to_final_parity_artifact",
                            "network_validation_summary",
                        }
                    ]
                    or [["--", "no", "当前结果包未声明关键 artifact"]],
                },
            ],
        },
        {
            "id": "artifacts",
            "title": "导出与证据说明",
            "intro": "记录当前结果包、对标文件、证据包与关键 artifact。",
            "artifacts": [
                f"当前结果包：{path}" for path in bundle_files.values()
            ]
            + [f"对标文件：{path}" for path in compare_files.values()]
            + [f"证据包：{path}" for path in list(evidence_bundle.get('included_files', []))[:8]]
            + [
                f"结果包目录：{result_bundle.get('export_root', '--')}",
                f"evidence_root：{evidence_bundle.get('root_dir', '--')}",
            ],
        },
    ]

    return {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at.isoformat(),
        "pdf_status": "fallback_html_only",
        "header": header,
        "data_sources": {
            "project_code": str(project_profile.get("code", "")),
            "site_code": str(site_snapshot.get("station_code", "")),
            "rp_run_id": getattr(rp_result, "run_id", None),
            "spectral_run_id": getattr(spectral_result, "run_id", None),
            "compare_id": eddypro_compare.get("compare_id", ""),
            "attribution_id": attribution_result.get("attribution_id", ""),
        },
        "sections": sections,
        "delivery_audit": delivery_audit,
    }


def _render_formal_report_html(snapshot: dict[str, Any]) -> str:
    header = snapshot["header"]
    cover_meta = [
        ("项目名称", header["project_name"]),
        ("站点名称", header["site_name"]),
        ("生成时间", header["generated_at_text"]),
        ("当前批次/运行 ID", header["current_batch_id"] or "--"),
        ("compare_id", header["compare_id"] or "--"),
        ("报告版本", header["report_version"]),
    ]
    summary_section = snapshot["sections"][0]
    cover_html = [
        '<section class="cover">',
        f"<h1>{escape(header['title'])}</h1>",
        '<p class="subtitle">面向正式交付、打印与存档的第一版技术报告模板。</p>',
        '<div class="meta-grid">',
    ]
    for label, value in cover_meta:
        cover_html.append(
            f'<div class="meta-card"><div class="label">{escape(label)}</div><div class="value">{escape(str(value))}</div></div>'
        )
    cover_html.append("</div>")
    cover_html.append('<div class="summary-grid">')
    for card in summary_section.get("cards", []):
        cover_html.append(
            "<div class=\"summary-card\">"
            f"<div class=\"label\">{escape(str(card.get('label', '')))}</div>"
            f"<div class=\"value\">{escape(str(card.get('value', '--')))}</div>"
            f"<div class=\"note\">{escape(str(card.get('note', '')))}</div>"
            "</div>"
        )
    cover_html.append("</div></section>")

    section_html = [*cover_html]
    for section in snapshot["sections"]:
        section_html.append('<section class="section">')
        section_html.append(f"<h2>{escape(str(section.get('title', '章节')))}</h2>")
        section_html.append(f"<p class=\"section-intro\">{escape(str(section.get('intro', '')))}</p>")
        if section.get("cards") and section is not summary_section:
            section_html.append('<div class="summary-grid">')
            for card in section["cards"]:
                section_html.append(
                    "<div class=\"summary-card\">"
                    f"<div class=\"label\">{escape(str(card.get('label', '')))}</div>"
                    f"<div class=\"value\">{escape(str(card.get('value', '--')))}</div>"
                    f"<div class=\"note\">{escape(str(card.get('note', '')))}</div>"
                    "</div>"
                )
            section_html.append("</div>")
        tables = list(section.get("tables", []))
        if tables:
            section_html.append('<div class="section-grid">')
            for table in tables:
                section_html.append('<div class="table-wrap">')
                section_html.append(f"<h3>{escape(str(table.get('title', '明细')))}</h3>")
                section_html.append("<table><thead><tr>")
                for header_label in table.get("headers", []):
                    section_html.append(f"<th>{escape(str(header_label))}</th>")
                section_html.append("</tr></thead><tbody>")
                for row in table.get("rows", []):
                    section_html.append("<tr>")
                    for cell in row:
                        section_html.append(f"<td>{escape(str(cell))}</td>")
                    section_html.append("</tr>")
                section_html.append("</tbody></table></div>")
            section_html.append("</div>")
        artifacts = list(section.get("artifacts", []))
        if artifacts:
            section_html.append('<ul class="artifact-list">')
            for item in artifacts:
                section_html.append(f"<li>{escape(str(item))}</li>")
            section_html.append("</ul>")
        if not tables and not artifacts and not section.get("cards"):
            section_html.append('<div class="empty">当前章节暂无内容。</div>')
        section_html.append("</section>")

    template = _load_template("report_template.html", _DEFAULT_TEMPLATE)
    styles = _load_template("report_styles.css", _DEFAULT_STYLES)
    return template.replace("{{REPORT_TITLE}}", escape(header["title"])).replace("{{INLINE_STYLES}}", styles).replace(
        "{{REPORT_BODY}}",
        "\n".join(section_html),
    )


def _load_template(filename: str, fallback: str) -> str:
    path = _TEMPLATE_DIR / filename
    if not path.exists():
        return fallback
    return path.read_text(encoding="utf-8")


def _run_status(run_result: Any | None) -> str:
    if run_result is None:
        return "缺失"
    return str(getattr(run_result, "summary", {}).get("status", "ok"))


def _batch_id(spectral_result: Any | None, rp_result: Any | None) -> str:
    if spectral_result is not None:
        return str(getattr(spectral_result, "run_id", ""))
    if rp_result is not None:
        return str(getattr(rp_result, "run_id", ""))
    return ""


def _fmt(value: object, digits: int) -> str:
    if value in (None, ""):
        return "--"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_ratio(value: object) -> str:
    if value in (None, ""):
        return "--"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)


def _format_mapping(payload: dict[str, Any]) -> str:
    if not payload:
        return "--"
    rows: list[str] = []
    for key, value in payload.items():
        if isinstance(value, float):
            rows.append(f"{key}={value:.3f}")
        else:
            rows.append(f"{key}={value}")
    return "；".join(rows[:4])


def _bundle_artifact_index(bundle_files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for key, value in bundle_files.items():
        path = Path(str(value)) if value else Path()
        index[str(key)] = {
            "path": str(value or ""),
            "exists": bool(value) and path.exists() and path.is_file(),
            "filename": path.name if value else "",
        }
    return index


def _read_json_file(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value))
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _to_jsonable(payload: Any) -> Any:
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
