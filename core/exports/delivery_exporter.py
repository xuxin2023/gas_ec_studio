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
        "clock_sync_summary": audit.get("clock_sync_summary", {}),
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
        "若存在 method_parity_matrix.json、footprint_2d_contour.svg、performance_profile.json，则它们来自 result bundle 并由 delivery_audit.json 统一索引。",
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
                f"footprint_2d_contour：{result_files.get('footprint_2d_contour_svg', '--')}",
                f"performance_profile：{result_files.get('performance_profile_artifact', '--')}",
                f"runtime_watchdog：{result_files.get('runtime_watchdog_artifact', '--')}",
                f"runtime_service：{result_files.get('runtime_service_artifact', '--')}",
                f"daemon_telemetry：{result_files.get('daemon_telemetry_artifact', '--')}",
                f"supervisor_integration：{result_files.get('supervisor_integration_artifact', '--')}",
                f"clock_sync：{result_files.get('clock_sync_artifact', '--')}",
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
    runtime_watchdog = dict(result_manifest.get("runtime_watchdog_summary", {}) or {})
    runtime_service = dict(result_manifest.get("runtime_service_summary", {}) or {})
    daemon_telemetry = dict(result_manifest.get("daemon_telemetry_summary", {}) or {})
    supervisor_integration = dict(result_manifest.get("supervisor_integration_summary", {}) or {})
    clock_sync = dict(result_manifest.get("clock_sync_summary", {}) or {})
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
        "method_compare_artifact",
        "method_parity_matrix_artifact",
        "method_parity_matrix_csv",
        "footprint_2d_artifact",
        "footprint_2d_contour_svg",
        "footprint_2d_grid_csv",
        "performance_profile_artifact",
        "runtime_watchdog_artifact",
        "runtime_service_artifact",
        "daemon_telemetry_artifact",
        "supervisor_integration_artifact",
        "clock_sync_artifact",
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
            "supervisor_integration_status": dict(result_manifest.get("supervisor_integration_summary", {}) or {}).get("status", ""),
            "clock_sync_status": dict(result_manifest.get("clock_sync_summary", {}) or {}).get("status", ""),
        },
        "network_validation_summary": network_validation,
        "runtime_watchdog_summary": runtime_watchdog,
        "runtime_service_summary": runtime_service,
        "daemon_telemetry_summary": daemon_telemetry,
        "supervisor_integration_summary": supervisor_integration,
        "clock_sync_summary": clock_sync,
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
