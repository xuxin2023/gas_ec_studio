from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


def export_delivery_package(
    *,
    runtime_root: Path,
    formal_report: dict[str, Any],
    result_bundle: dict[str, Any],
    evidence_bundle: dict[str, Any] | None,
    compare_manifest: dict[str, Any] | None,
    attribution_result: dict[str, Any] | None,
    current_batch_id: str,
) -> dict[str, Any]:
    timestamp = datetime.now()
    suffix = timestamp.strftime("%Y%m%d_%H%M%S")
    package_id = f"delivery_{suffix}"
    exports_root = Path(runtime_root) / "exports" / "delivery"
    package_root = exports_root / package_id
    package_root.mkdir(parents=True, exist_ok=True)

    file_list: list[str] = []
    notes: list[str] = []
    file_index: dict[str, dict[str, Any]] = {}

    _copy_declared_files(formal_report.get("files", {}), package_root, file_list=file_list, file_index=file_index, source_group="formal_report")
    _copy_declared_files(result_bundle.get("files", {}), package_root, file_list=file_list, file_index=file_index, source_group="result_bundle")

    if evidence_bundle and evidence_bundle.get("root_dir"):
        evidence_root = Path(str(evidence_bundle["root_dir"]))
        if evidence_root.exists():
            target_root = package_root / "evidence"
            shutil.copytree(evidence_root, target_root, dirs_exist_ok=True)
            file_list.extend(_list_relative_files(target_root, package_root))
        else:
            notes.append("evidence bundle 路径不存在，已跳过复制。")
    else:
        notes.append("当前缺少 evidence bundle，已导出最小交付包。")

    if compare_manifest and compare_manifest.get("files"):
        compare_files = dict(compare_manifest.get("files", {}))
        _copy_declared_files(compare_files, package_root, file_list=file_list, file_index=file_index, source_group="eddypro_compare")
    else:
        notes.append("当前缺少 compare 结果，已导出最小交付包。")

    attribution_payload = dict(attribution_result or {})
    if attribution_payload.get("status") == "ready":
        attribution_path = package_root / "attribution_summary.json"
        attribution_path.write_text(json.dumps(attribution_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        file_list.append(str(attribution_path.relative_to(package_root)))
    else:
        notes.append("当前缺少 attribution 结果，已导出最小交付包。")

    readme_path = package_root / "README.txt"
    readme_path.write_text(_build_readme(formal_report, evidence_bundle, compare_manifest, attribution_payload, result_bundle), encoding="utf-8")
    file_list.append(str(readme_path.relative_to(package_root)))

    audit = _build_delivery_audit(
        formal_report=formal_report,
        result_bundle=result_bundle,
        evidence_bundle=evidence_bundle or {},
        compare_manifest=compare_manifest or {},
        attribution_result=attribution_payload,
        file_index=file_index,
        package_file_list=file_list,
        notes=notes,
    )
    audit_path = package_root / "delivery_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    file_list.append(str(audit_path.relative_to(package_root)))

    manifest_path = package_root / "package_manifest.json"
    zip_path = exports_root / f"{package_id}.zip"
    manifest = {
        "package_id": package_id,
        "created_at": timestamp.isoformat(),
        "current_batch_id": current_batch_id,
        "compare_id": str((compare_manifest or {}).get("compare_id", "")),
        "attribution_id": str(attribution_payload.get("attribution_id", "")),
        "file_list": sorted(set(file_list)),
        "zip_file": str(zip_path),
        "export_status": "ready",
        "delivery_audit": audit,
        "artifact_index": audit.get("artifact_index", {}),
        "result_manifest_summary": audit.get("result_manifest_summary", {}),
        "network_validation_summary": audit.get("network_validation_summary", {}),
        "runtime_watchdog_summary": audit.get("runtime_watchdog_summary", {}),
        "runtime_service_summary": audit.get("runtime_service_summary", {}),
        "daemon_telemetry_summary": audit.get("daemon_telemetry_summary", {}),
        "supervisor_integration_summary": audit.get("supervisor_integration_summary", {}),
        "installable_runtime_summary": audit.get("installable_runtime_summary", {}),
        "runtime_deployment_summary": audit.get("runtime_deployment_summary", {}),
        "runtime_deployment_feedback_summary": audit.get("runtime_deployment_feedback_summary", {}),
        "clock_sync_summary": audit.get("clock_sync_summary", {}),
        "flux_correction_ledger_summary": audit.get("flux_correction_ledger_summary", {}),
        "spectral_assessment": audit.get("spectral_assessment", {}),
        "spectral_assessment_library": audit.get("spectral_assessment_library", {}),
        "fixture_pack_summary": audit.get("fixture_pack_summary", {}),
        "public_eddypro_fixture_catalog": audit.get("public_eddypro_fixture_catalog", {}),
        "official_raw_fixture_manifest": audit.get("official_raw_fixture_manifest", {}),
        "official_raw_closure_run": audit.get("official_raw_closure_run", {}),
        "official_raw_repair_plan": audit.get("official_raw_repair_plan", {}),
        "official_raw_fixture_detail": audit.get("official_raw_fixture_detail", {}),
        "official_raw_acquisition_validation": audit.get("official_raw_acquisition_validation", {}),
        "official_raw_evidence_pack": audit.get("official_raw_evidence_pack", {}),
        "official_eddypro_run": audit.get("official_eddypro_run", {}),
        "eddypro_source_inventory": audit.get("eddypro_source_inventory", {}),
        "eddypro_coverage_audit": audit.get("eddypro_coverage_audit", {}),
        "eddypro_surrogate_evidence_closure": audit.get("eddypro_surrogate_evidence_closure", {}),
        "eddypro_release_gate": audit.get("eddypro_release_gate", {}),
        "eddypro_partial_capability_closure": audit.get("eddypro_partial_capability_closure", {}),
        "eddypro_closure_gate": audit.get("eddypro_closure_gate", {}),
        "eddypro_closure_plan": audit.get("eddypro_closure_plan", {}),
        "raw_to_final_parity": audit.get("raw_to_final_parity", {}),
        "raw_to_final_parity_diagnostics": audit.get("raw_to_final_parity_diagnostics", {}),
        "raw_to_final_trace_gas_parity": audit.get("raw_to_final_trace_gas_parity", {}),
        "neon_hdf5_validation_package": audit.get("neon_hdf5_validation_package", {}),
        "neon_hdf5_summary": audit.get("neon_hdf5_summary", {}),
        "public_raw_sample_validation_package": audit.get("public_raw_sample_validation_package", {}),
        "public_raw_sample_summary": audit.get("public_raw_sample_summary", {}),
        "benchmark_summary": audit.get("benchmark_summary", {}),
        "method_artifact_keys": audit.get("method_artifact_keys", []),
        "notes": notes or ["交付包已完整导出。"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    file_list.append(str(manifest_path.relative_to(package_root)))
    manifest["file_list"] = sorted(set(file_list))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(package_root.parent))

    return {
        "export_root": str(package_root),
        "summary_text": f"交付包已导出：{package_id}",
        "files": {
            "package_manifest": str(manifest_path),
            "readme": str(readme_path),
            "delivery_audit": str(audit_path),
            "zip": str(zip_path),
        },
        "package_id": package_id,
    }


def _copy_declared_files(
    files: dict[str, Any],
    package_root: Path,
    *,
    file_list: list[str],
    file_index: dict[str, dict[str, Any]],
    source_group: str,
) -> None:
    for key, path_str in files.items():
        if not path_str:
            continue
        path = Path(str(path_str))
        index_key = f"{source_group}.{key}"
        file_index[index_key] = {
            "source_group": source_group,
            "key": str(key),
            "source_path": str(path),
            "source_exists": path.exists() and path.is_file(),
            "package_relative_path": "",
            "packaged": False,
        }
        if not path.exists() or not path.is_file():
            continue
        target = package_root / path.name
        shutil.copy2(path, target)
        file_list.append(str(target.relative_to(package_root)))
        file_index[index_key]["package_relative_path"] = str(target.relative_to(package_root))
        file_index[index_key]["packaged"] = True


def _list_relative_files(root: Path, package_root: Path) -> list[str]:
    return [str(path.relative_to(package_root)) for path in root.rglob("*") if path.is_file()]


def _build_readme(
    formal_report: dict[str, Any],
    evidence_bundle: dict[str, Any] | None,
    compare_manifest: dict[str, Any] | None,
    attribution_result: dict[str, Any],
    result_bundle: dict[str, Any] | None,
) -> str:
    pdf_status = str(formal_report.get("pdf_status", "fallback_html_only"))
    result_files = dict((result_bundle or {}).get("files", {}) or {})
    lines = [
        "Gas EC Studio 交付包说明",
        "",
        "本交付包用于对当前批次的正式结果进行归档与交付。",
        "",
        "目录结构说明：",
        "1. formal_report.html / formal_report_snapshot.json / report_manifest.json：正式报告与其快照、manifest。",
        "2. rp_results.csv / spectral_qc_results.csv / summary.json / config_snapshot.json / project_site_snapshot.json / report_snapshot.json：结果表与运行快照。",
        "3. compare_summary.json / compare_windows.csv / compare_manifest.json：EddyPro 对标结果。",
        "4. evidence/ 子目录：谱修正与 QC 证据包，包括 manifest、summary、qc_windows 等。",
        "5. attribution_summary.json：自动归因结果摘要。",
        "6. delivery_audit.json：交付链审计摘要，校验 result manifest、artifact、network validation 与包内文件一致性。",
        "",
        "正式报告说明：",
        "formal_report.html 为正式 HTML 报告主文件。",
        "若当前 PDF 状态为 fallback_html_only，可直接使用浏览器打开 formal_report.html 再打印为 PDF。",
        f"当前 PDF 状态：{pdf_status}",
        "",
        "结果表说明：",
        "rp_results.csv 为 RP 窗口结果表；spectral_qc_results.csv 为谱修正/QC 窗口结果表。",
        "若存在 method_parity_matrix.json、spectral_assessment.json、footprint_2d_contour.svg、performance_profile.json，则它们来自 result bundle 并由 delivery_audit.json 统一索引。",
        "",
        "对标结果说明：",
        "若当前批次存在 EddyPro compare，则 compare 相关文件会出现在包内。",
        "",
        "证据包说明：",
        "若当前批次存在 evidence bundle，则 evidence/ 子目录包含对应证据导出。",
        "",
    ]
    if not evidence_bundle or not evidence_bundle.get("root_dir"):
        lines.append("当前无 evidence bundle，交付包已按最小内容导出。")
    if not compare_manifest or not compare_manifest.get("files"):
        lines.append("当前无对标结果，交付包未包含 compare 文件。")
    if attribution_result.get("status") != "ready":
        lines.append("当前无归因结果，交付包未包含 attribution_summary.json。")
    if result_files:
        lines.extend(
            [
                "",
                "关键结果 artifact：",
                f"export_manifest：{result_files.get('export_manifest', '--')}",
                f"method_parity_matrix：{result_files.get('method_parity_matrix_artifact', '--')}",
                f"spectral_assessment：{result_files.get('spectral_assessment_artifact', '--')}",
                f"spectral_binned_ensemble：{result_files.get('spectral_binned_ensemble_csv', '--')}",
                f"spectral_full_windows：{result_files.get('spectral_full_windows_csv', '--')}",
                f"footprint_2d_contour：{result_files.get('footprint_2d_contour_svg', '--')}",
                f"footprint_geojson：{result_files.get('footprint_geojson_artifact', '--')}",
                f"footprint_geotiff：{result_files.get('footprint_geotiff_artifact', '--')}",
                f"footprint_land_cover_overlay：{result_files.get('footprint_land_cover_overlay_artifact', '--')}",
                f"footprint_gis_validation：{result_files.get('footprint_gis_validation_artifact', '--')}",
                f"performance_profile：{result_files.get('performance_profile_artifact', '--')}",
                f"runtime_watchdog：{result_files.get('runtime_watchdog_artifact', '--')}",
                f"runtime_service：{result_files.get('runtime_service_artifact', '--')}",
                f"daemon_telemetry：{result_files.get('daemon_telemetry_artifact', '--')}",
                f"supervisor_integration：{result_files.get('supervisor_integration_artifact', '--')}",
                f"installable_runtime：{result_files.get('installable_runtime_artifact', '--')}",
                f"runtime_deployment：{result_files.get('runtime_deployment_artifact', '--')}",
                f"runtime_deployment_feedback：{result_files.get('runtime_deployment_feedback_artifact', '--')}",
                f"clock_sync：{result_files.get('clock_sync_artifact', '--')}",
                f"flux_correction_ledger：{result_files.get('flux_correction_ledger_artifact', '--')}",
                f"fixture_pack_summary：{result_files.get('fixture_pack_summary_artifact', '--')}",
                f"public_eddypro_fixture_catalog：{result_files.get('public_eddypro_fixture_catalog_artifact', '--')}",
                f"official_raw_fixture_manifest：{result_files.get('official_raw_fixture_manifest_artifact', '--')}",
                f"official_raw_closure_run：{result_files.get('official_raw_closure_run_artifact', '--')}",
                f"official_raw_repair_plan：{result_files.get('official_raw_repair_plan_artifact', '--')}",
                f"official_raw_fixture_detail：{result_files.get('official_raw_fixture_detail_artifact', '--')}",
                f"official_raw_evidence_pack：{result_files.get('official_raw_evidence_pack_artifact', '--')}",
                "official_eddypro_run：stored inside official_raw_evidence_pack.official_eddypro_run",
                f"eddypro_source_inventory：{result_files.get('eddypro_source_inventory_artifact', '--')}",
                f"eddypro_coverage_audit：{result_files.get('eddypro_coverage_audit_artifact', '--')}",
                f"raw_to_final_parity：{result_files.get('raw_to_final_parity_artifact', '--')}",
                f"network_validation_summary：{result_files.get('network_validation_summary', '--')}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _build_delivery_audit(
    *,
    formal_report: dict[str, Any],
    result_bundle: dict[str, Any],
    evidence_bundle: dict[str, Any],
    compare_manifest: dict[str, Any],
    attribution_result: dict[str, Any],
    file_index: dict[str, dict[str, Any]],
    package_file_list: list[str],
    notes: list[str],
) -> dict[str, Any]:
    result_files = dict(result_bundle.get("files", {}) or {})
    result_manifest = _read_json_file(result_files.get("export_manifest", ""))
    method_parity = _read_json_file(result_files.get("method_parity_matrix_artifact", ""))
    network_validation = dict(result_manifest.get("network_validation_summary", {}) or {})
    neon_validation = dict(
        result_manifest.get("neon_hdf5_validation_package", {})
        or _read_json_file(result_files.get("neon_hdf5_validation_package_artifact", ""))
    )
    public_raw_sample_validation = dict(
        result_manifest.get("public_raw_sample_validation_package", {})
        or _read_json_file(result_files.get("public_raw_sample_validation_package_artifact", ""))
    )
    runtime_watchdog = dict(result_manifest.get("runtime_watchdog_summary", {}) or {})
    runtime_service = dict(result_manifest.get("runtime_service_summary", {}) or {})
    daemon_telemetry = dict(result_manifest.get("daemon_telemetry_summary", {}) or {})
    supervisor_integration = dict(result_manifest.get("supervisor_integration_summary", {}) or {})
    installable_runtime = dict(result_manifest.get("installable_runtime_summary", {}) or {})
    runtime_deployment = dict(result_manifest.get("runtime_deployment_summary", {}) or {})
    runtime_deployment_feedback = dict(result_manifest.get("runtime_deployment_feedback_summary", {}) or {})
    clock_sync = dict(result_manifest.get("clock_sync_summary", {}) or {})
    flux_correction_ledger = dict(result_manifest.get("flux_correction_ledger_summary", {}) or {})
    biomet_ambient = dict(result_manifest.get("biomet_ambient_summary", {}) or {})
    spectral_assessment = dict(result_manifest.get("spectral_assessment", {}) or {})
    spectral_assessment_library = dict(result_manifest.get("spectral_assessment_library", {}) or {})
    fixture_pack = dict(result_manifest.get("fixture_pack_summary", {}) or {})
    public_eddypro_fixture_catalog = dict(result_manifest.get("public_eddypro_fixture_catalog", {}) or {})
    official_raw_fixture = dict(result_manifest.get("official_raw_fixture_manifest", {}) or {})
    official_raw_closure_run = dict(result_manifest.get("official_raw_closure_run", {}) or {})
    official_raw_repair_plan = dict(result_manifest.get("official_raw_repair_plan", {}) or {})
    official_raw_fixture_detail = dict(result_manifest.get("official_raw_fixture_detail", {}) or {})
    official_raw_acquisition_validation = dict(
        result_manifest.get("official_raw_acquisition_validation", {})
        or official_raw_fixture_detail.get("acquisition_validation", {})
        or {}
    )
    official_raw_evidence_pack = dict(result_manifest.get("official_raw_evidence_pack", {}) or {})
    official_eddypro_run = dict(result_manifest.get("official_eddypro_run", {}) or official_raw_evidence_pack.get("official_eddypro_run", {}) or {})
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
    eddypro_surrogate_evidence_closure = dict(
        result_manifest.get("eddypro_surrogate_evidence_closure", {})
        or eddypro_coverage_audit.get("surrogate_evidence_closure", {})
        or {}
    )
    eddypro_release_gate = dict(result_manifest.get("eddypro_release_gate", {}) or {})
    eddypro_partial_capability_closure = dict(result_manifest.get("eddypro_partial_capability_closure", {}) or {})
    eddypro_closure_gate = dict(result_manifest.get("eddypro_closure_gate", {}) or eddypro_coverage_audit.get("closure_gate", {}) or {})
    eddypro_closure_plan = dict(result_manifest.get("eddypro_closure_plan", {}) or eddypro_coverage_audit.get("closure_plan", {}) or {})
    raw_to_final_parity = dict(result_manifest.get("raw_to_final_parity", {}) or {})
    raw_to_final_trace_gas = dict(
        result_manifest.get("raw_to_final_trace_gas_parity", {})
        or raw_to_final_parity.get("trace_gas_parity", {})
        or {}
    )
    raw_to_final_parity_diagnostics = dict(
        result_manifest.get("raw_to_final_parity_diagnostics", {})
        or raw_to_final_parity.get("parity_diagnostics", {})
        or {}
    )
    raw_to_final_parity_failure_groups = [
        str(item.get("category", ""))
        for item in list(raw_to_final_parity_diagnostics.get("failure_groups", []) or [])
        if str(item.get("category", ""))
    ]
    raw_to_final_parity_top_failed_fields = list(raw_to_final_parity_diagnostics.get("top_failed_fields", []) or [])
    benchmark_summary = {
        "benchmark_status": result_manifest.get("benchmark_status", ""),
        "benchmark_reference_id": result_manifest.get("benchmark_reference_id", ""),
        "pass_rate": result_manifest.get("pass_rate", 0.0),
        "failed_fields": result_manifest.get("failed_fields", []),
    }
    packaged_names = {Path(item).name for item in package_file_list}
    exported_files = [str(item) for item in list(result_manifest.get("exported_files", []) or [])]
    missing_manifest_files = sorted(
        item
        for item in exported_files
        if Path(item).name not in packaged_names
    )
    missing_declared_files = sorted(
        key
        for key, payload in file_index.items()
        if not payload.get("source_exists", False)
    )
    artifact_keys = [
        "export_manifest",
        "full_output",
        "summary",
        "config_snapshot",
        "project_site_snapshot",
        "report_snapshot",
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
        "fixture_pack_summary_artifact",
        "public_eddypro_fixture_catalog_artifact",
        "official_raw_fixture_manifest_artifact",
        "official_raw_closure_run_artifact",
        "official_raw_repair_plan_artifact",
        "official_raw_fixture_detail_artifact",
        "official_raw_evidence_pack_artifact",
        "eddypro_source_inventory_artifact",
        "eddypro_coverage_audit_artifact",
        "eddypro_surrogate_evidence_closure_artifact",
        "eddypro_release_gate_artifact",
        "eddypro_partial_capability_closure_artifact",
        "raw_to_final_parity_artifact",
        "neon_hdf5_validation_package_artifact",
        "neon_hdf5_metadata_smoke_artifact",
        "neon_hdf5_row_smoke_artifact",
        "neon_hdf5_rp_smoke_artifact",
        "public_raw_sample_validation_package_artifact",
        "public_raw_sample_importer_smoke_artifact",
        "public_raw_sample_rp_smoke_artifact",
        "benchmark_summary_artifact",
        "parity_artifact",
        "reference_provenance_artifact",
        "network_validation_summary",
    ]
    artifact_index: dict[str, dict[str, Any]] = {}
    for key in artifact_keys:
        source_path = str(result_files.get(key, ""))
        package_entry = file_index.get(f"result_bundle.{key}", {})
        artifact_index[key] = {
            "source_path": source_path,
            "source_exists": Path(source_path).exists() if source_path else False,
            "package_relative_path": package_entry.get("package_relative_path", ""),
            "packaged": bool(package_entry.get("packaged", False)),
        }
    validation_status = "ok"
    if missing_declared_files or missing_manifest_files:
        validation_status = "warning"
    if not result_manifest:
        validation_status = "missing_result_manifest"
    return {
        "artifact_type": "delivery_audit",
        "validation_status": validation_status,
        "formal_report_files": dict(formal_report.get("files", {}) or {}),
        "result_bundle_root": str(result_bundle.get("export_root", "")),
        "result_manifest_path": str(result_files.get("export_manifest", "")),
        "result_manifest_summary": {
            "full_output_mode": result_manifest.get("full_output_mode", ""),
            "schema_target": result_manifest.get("schema_target", ""),
            "network_validation_status": result_manifest.get("network_validation_status", ""),
            "network_missing_fields": result_manifest.get("network_missing_fields", []),
            "method_parity_status_counts": dict((result_manifest.get("method_parity_matrix", {}) or {}).get("status_counts", {}) or {}),
            "method_metadata_coverage": dict((result_manifest.get("method_parity_matrix", {}) or {}).get("metadata_coverage", {}) or {}),
            "runtime_watchdog_status": dict(result_manifest.get("runtime_watchdog_summary", {}) or {}).get("status", ""),
            "runtime_service_status": dict(result_manifest.get("runtime_service_summary", {}) or {}).get("status", ""),
            "runtime_service_delivery_state": dict(result_manifest.get("runtime_service_summary", {}) or {}).get("delivery_state", ""),
            "daemon_telemetry_status": dict(result_manifest.get("daemon_telemetry_summary", {}) or {}).get("status", ""),
            "target_host_validation_status": dict(dict(result_manifest.get("daemon_telemetry_summary", {}) or {}).get("target_host_validation", {}) or {}).get("status", ""),
            "target_host_validation_gate_status": dict(dict(result_manifest.get("daemon_telemetry_summary", {}) or {}).get("target_host_validation", {}) or {}).get("gate_status", ""),
            "supervisor_integration_status": dict(result_manifest.get("supervisor_integration_summary", {}) or {}).get("status", ""),
            "installable_runtime_status": dict(result_manifest.get("installable_runtime_summary", {}) or {}).get("status", ""),
            "runtime_deployment_status": dict(result_manifest.get("runtime_deployment_summary", {}) or {}).get("status", ""),
            "runtime_deployment_feedback_status": dict(result_manifest.get("runtime_deployment_feedback_summary", {}) or {}).get("status", ""),
            "clock_sync_status": dict(result_manifest.get("clock_sync_summary", {}) or {}).get("status", ""),
            "biomet_ambient_status": biomet_ambient.get("status", ""),
            "biomet_ambient_applied_window_count": biomet_ambient.get("applied_window_count", 0),
            "flux_correction_ledger_status": dict(result_manifest.get("flux_correction_ledger_summary", {}) or {}).get("status", ""),
            "flux_correction_ledger_window_count": dict(result_manifest.get("flux_correction_ledger_summary", {}) or {}).get("ledger_window_count", 0),
            "spectral_assessment_status": spectral_assessment.get("status", ""),
            "spectral_assessment_bin_count": dict(spectral_assessment.get("binned_ensemble", {}) or {}).get("bin_count", 0),
            "spectral_assessment_full_window_row_count": spectral_assessment.get("full_window_row_count", 0),
            "spectral_assessment_library_status": spectral_assessment_library.get("status", ""),
            "spectral_assessment_library_group_count": spectral_assessment_library.get("group_count", 0),
            "spectral_assessment_library_window_count": spectral_assessment_library.get("window_count", 0),
            "fixture_pack_status": dict(result_manifest.get("fixture_pack_summary", {}) or {}).get("status", ""),
            "fixture_pack_real_reference_window_count": dict(result_manifest.get("fixture_pack_summary", {}) or {}).get("real_reference_window_count", 0),
            "fixture_pack_protocol_validation_row_count": dict(result_manifest.get("fixture_pack_summary", {}) or {}).get("protocol_validation_row_count", 0),
            "public_eddypro_fixture_catalog_status": public_eddypro_fixture_catalog.get("status", ""),
            "public_eddypro_fixture_count": public_eddypro_fixture_catalog.get("fixture_count", 0),
            "public_eddypro_valid_fixture_count": public_eddypro_fixture_catalog.get("valid_fixture_count", 0),
            "public_eddypro_dataset_count": public_eddypro_fixture_catalog.get("dataset_count", 0),
            "public_eddypro_can_support_raw_to_final_claim": dict(public_eddypro_fixture_catalog.get("claim_boundary", {}) or {}).get("can_support_full_raw_to_final_eddypro_claim", False),
            "official_raw_fixture_status": official_raw_fixture.get("status", ""),
            "official_raw_to_final_ready_count": official_raw_fixture.get("official_raw_to_final_ready_count", 0),
            "registered_raw_to_final_fixture_count": official_raw_fixture.get("registered_raw_to_final_fixture_count", 0),
            "synthetic_guardrail_count": official_raw_fixture.get("synthetic_guardrail_count", 0),
            "missing_official_bundle_count": official_raw_fixture.get("missing_official_bundle_count", 0),
            "official_raw_closure_run_status": official_raw_closure_run.get("status", ""),
            "official_raw_closure_run_gate_status": official_raw_closure_run.get("gate_status", ""),
            "official_raw_closure_run_blockers": list(official_raw_closure_run.get("blockers", []) or []),
            "official_raw_repair_plan_status": official_raw_repair_plan.get("status", ""),
            "official_raw_repair_item_count": official_raw_repair_plan.get("repair_item_count", 0),
            "official_raw_repair_missing_requirement_counts": dict(official_raw_repair_plan.get("missing_requirement_counts", {}) or {}),
            "official_raw_repair_official_run_blocked_count": official_raw_repair_plan.get("official_eddypro_run_blocked_count", 0),
            "official_raw_fixture_detail_id": official_raw_fixture_detail.get("fixture_id", ""),
            "official_raw_fixture_detail_status": official_raw_fixture_detail.get("status", ""),
            "official_raw_fixture_detail_readiness": official_raw_fixture_detail.get("readiness_level", ""),
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
            "official_eddypro_run_status": result_manifest.get(
                "official_eddypro_run_status",
                official_eddypro_run.get("status", "not_available"),
            ),
            "official_eddypro_run_gate_status": result_manifest.get(
                "official_eddypro_run_gate_status",
                official_eddypro_run.get("gate_status", "blocked"),
            ),
            "official_eddypro_software_version": result_manifest.get(
                "official_eddypro_software_version",
                official_eddypro_run.get("software_version", ""),
            ),
            "official_eddypro_run_command": result_manifest.get(
                "official_eddypro_run_command",
                official_eddypro_run.get("command", ""),
            ),
            "official_raw_normalization_status": official_raw_normalization.get("status", ""),
            "official_raw_normalization_time": official_raw_normalization.get("normalization_time", ""),
            "official_raw_normalization_source_file": official_raw_normalization.get("source_file", ""),
            "official_raw_qc_mapping_strategy": official_raw_normalization.get("qc_mapping_strategy", ""),
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
            "eddypro_source_inventory_status": eddypro_source_inventory.get("status", ""),
            "eddypro_source_inventory_present_feature_count": eddypro_source_inventory.get("present_feature_count", 0),
            "eddypro_source_inventory_feature_count": eddypro_source_inventory.get("feature_count", 0),
            "eddypro_coverage_audit_status": eddypro_coverage_audit.get("status", ""),
            "eddypro_coverage_completion_score": dict(eddypro_coverage_audit.get("capability_summary", {}) or {}).get("completion_score", 0.0),
            "can_claim_full_eddypro_parity": eddypro_coverage_audit.get("can_claim_full_eddypro_parity", False),
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
            "eddypro_release_gate_ci_exit_code": eddypro_release_gate.get("ci_exit_code", 2),
            "eddypro_partial_capability_closure_status": eddypro_partial_capability_closure.get("status", ""),
            "eddypro_partial_capability_count": eddypro_partial_capability_closure.get("partial_capability_count", 0),
            "eddypro_partial_capability_ids": list(eddypro_partial_capability_closure.get("capability_ids", []) or []),
            "eddypro_ready_public_raw_candidate_count": dict(
                eddypro_partial_capability_closure.get("public_search_closure", {}) or {}
            ).get("ready_to_register_public_raw_candidate_count", 0),
            "eddypro_partial_closure_current_round_closed": dict(
                eddypro_partial_capability_closure.get("closure_decision", {}) or {}
            ).get("current_round_closed", False),
            "eddypro_closure_gate_status": eddypro_closure_gate.get("status", ""),
            "eddypro_closure_open_item_count": eddypro_closure_gate.get("open_item_count", 0),
            "eddypro_closure_top_priority": eddypro_closure_gate.get("top_priority", ""),
            "eddypro_closure_next_actions": list(eddypro_closure_plan.get("next_actions", []) or [])[:5],
            "raw_to_final_parity_status": raw_to_final_parity.get("status", ""),
            "raw_to_final_parity_pass_rate": dict(raw_to_final_parity.get("benchmark_summary", {}) or {}).get("pass_rate", 0.0),
            "raw_to_final_parity_diagnostics_status": raw_to_final_parity_diagnostics.get("status", ""),
            "raw_to_final_parity_failure_groups": raw_to_final_parity_failure_groups,
            "raw_to_final_parity_top_failed_fields": raw_to_final_parity_top_failed_fields,
            "raw_to_final_trace_gas_parity_status": raw_to_final_trace_gas.get("status", ""),
            "raw_to_final_trace_gas_pass_rate": raw_to_final_trace_gas.get("pass_rate", 0.0),
            "raw_to_final_trace_gas_failed_fields": list(raw_to_final_trace_gas.get("failed_fields", []) or []),
            "raw_to_final_trace_gas_coefficient_profile_id": raw_to_final_trace_gas.get("coefficient_profile_id", ""),
            "neon_hdf5_validation_status": neon_validation.get("status", ""),
            "neon_hdf5_metadata_status": neon_validation.get("metadata_status", ""),
            "neon_hdf5_row_status": neon_validation.get("row_status", ""),
            "neon_hdf5_rp_status": neon_validation.get("rp_status", ""),
            "neon_hdf5_row_count": neon_validation.get("row_count", 0),
            "neon_hdf5_rp_window_count": neon_validation.get("rp_window_count", 0),
            "neon_hdf5_source_file": neon_validation.get("source_file", ""),
            "neon_hdf5_can_claim_engineering_validation": dict(neon_validation.get("claim_boundary", {}) or {}).get(
                "can_claim_neon_engineering_validation",
                False,
            ),
            "neon_hdf5_can_claim_eddypro_raw_to_final_parity": dict(neon_validation.get("claim_boundary", {}) or {}).get(
                "can_claim_eddypro_raw_to_final_parity",
                False,
            ),
            "public_raw_sample_validation_status": public_raw_sample_validation.get("status", ""),
            "public_raw_sample_importer_status": public_raw_sample_validation.get("importer_status", ""),
            "public_raw_sample_rp_status": public_raw_sample_validation.get("rp_status", ""),
            "public_raw_sample_row_count": public_raw_sample_validation.get("row_count", 0),
            "public_raw_sample_rp_window_count": public_raw_sample_validation.get("rp_window_count", 0),
            "public_raw_sample_source_file": public_raw_sample_validation.get("source_file", ""),
            "public_raw_sample_can_claim_engineering_validation": dict(
                public_raw_sample_validation.get("claim_boundary", {}) or {}
            ).get("can_claim_public_raw_engineering_validation", False),
            "public_raw_sample_can_claim_eddypro_raw_to_final_parity": dict(
                public_raw_sample_validation.get("claim_boundary", {}) or {}
            ).get("can_claim_eddypro_raw_to_final_parity", False),
        },
        "network_validation_summary": network_validation,
        "neon_hdf5_validation_package": neon_validation,
        "neon_hdf5_summary": {
            "status": neon_validation.get("status", ""),
            "source_file": neon_validation.get("source_file", ""),
            "row_count": neon_validation.get("row_count", 0),
            "rp_window_count": neon_validation.get("rp_window_count", 0),
            "can_claim_neon_engineering_validation": dict(neon_validation.get("claim_boundary", {}) or {}).get(
                "can_claim_neon_engineering_validation",
                False,
            ),
            "can_claim_eddypro_raw_to_final_parity": dict(neon_validation.get("claim_boundary", {}) or {}).get(
                "can_claim_eddypro_raw_to_final_parity",
                False,
            ),
        },
        "public_raw_sample_validation_package": public_raw_sample_validation,
        "public_raw_sample_summary": {
            "status": public_raw_sample_validation.get("status", ""),
            "source_file": public_raw_sample_validation.get("source_file", ""),
            "row_count": public_raw_sample_validation.get("row_count", 0),
            "rp_window_count": public_raw_sample_validation.get("rp_window_count", 0),
            "can_claim_public_raw_engineering_validation": dict(
                public_raw_sample_validation.get("claim_boundary", {}) or {}
            ).get("can_claim_public_raw_engineering_validation", False),
            "can_claim_eddypro_raw_to_final_parity": dict(
                public_raw_sample_validation.get("claim_boundary", {}) or {}
            ).get("can_claim_eddypro_raw_to_final_parity", False),
        },
        "runtime_watchdog_summary": runtime_watchdog,
        "runtime_service_summary": runtime_service,
        "daemon_telemetry_summary": daemon_telemetry,
        "supervisor_integration_summary": supervisor_integration,
        "installable_runtime_summary": installable_runtime,
        "runtime_deployment_summary": runtime_deployment,
        "runtime_deployment_feedback_summary": runtime_deployment_feedback,
        "clock_sync_summary": clock_sync,
        "biomet_ambient_summary": biomet_ambient,
        "flux_correction_ledger_summary": flux_correction_ledger,
        "spectral_assessment": spectral_assessment,
        "spectral_assessment_library": spectral_assessment_library,
        "fixture_pack_summary": fixture_pack,
        "public_eddypro_fixture_catalog": public_eddypro_fixture_catalog,
        "official_raw_fixture_manifest": official_raw_fixture,
        "official_raw_closure_run": official_raw_closure_run,
        "official_raw_repair_plan": official_raw_repair_plan,
        "official_raw_fixture_detail": official_raw_fixture_detail,
        "official_raw_acquisition_validation": official_raw_acquisition_validation,
        "official_raw_evidence_pack": official_raw_evidence_pack,
        "official_eddypro_run": official_eddypro_run,
        "eddypro_source_inventory": eddypro_source_inventory,
        "eddypro_coverage_audit": eddypro_coverage_audit,
        "eddypro_surrogate_evidence_closure": eddypro_surrogate_evidence_closure,
        "eddypro_release_gate": eddypro_release_gate,
        "eddypro_partial_capability_closure": eddypro_partial_capability_closure,
        "eddypro_closure_gate": eddypro_closure_gate,
        "eddypro_closure_plan": eddypro_closure_plan,
        "raw_to_final_parity": raw_to_final_parity,
        "raw_to_final_parity_diagnostics": raw_to_final_parity_diagnostics,
        "raw_to_final_trace_gas_parity": raw_to_final_trace_gas,
        "benchmark_summary": benchmark_summary,
        "method_artifact_keys": [key for key in artifact_keys if key in result_files],
        "method_parity_matrix": {
            "status_counts": dict(method_parity.get("status_counts", {}) or {}),
            "metadata_coverage": dict(method_parity.get("metadata_coverage", {}) or {}),
            "not_reported_families": list(method_parity.get("not_reported_families", []) or []),
        },
        "artifact_index": artifact_index,
        "package_file_count": len(set(package_file_list)),
        "missing_declared_files": missing_declared_files,
        "missing_manifest_files": missing_manifest_files,
        "evidence_root": str(evidence_bundle.get("root_dir", "")),
        "compare_id": str(compare_manifest.get("compare_id", "")),
        "attribution_status": str(attribution_result.get("status", "")),
        "notes": list(notes),
    }


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
