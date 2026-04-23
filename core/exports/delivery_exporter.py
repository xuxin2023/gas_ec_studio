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

    _copy_declared_files(formal_report.get("files", {}), package_root, file_list=file_list)
    _copy_declared_files(result_bundle.get("files", {}), package_root, file_list=file_list)

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
        _copy_declared_files(compare_files, package_root, file_list=file_list)
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
    readme_path.write_text(_build_readme(formal_report, evidence_bundle, compare_manifest, attribution_payload), encoding="utf-8")
    file_list.append(str(readme_path.relative_to(package_root)))

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
            "zip": str(zip_path),
        },
        "package_id": package_id,
    }


def _copy_declared_files(files: dict[str, Any], package_root: Path, *, file_list: list[str]) -> None:
    for path_str in files.values():
        if not path_str:
            continue
        path = Path(str(path_str))
        if not path.exists() or not path.is_file():
            continue
        target = package_root / path.name
        shutil.copy2(path, target)
        file_list.append(str(target.relative_to(package_root)))


def _list_relative_files(root: Path, package_root: Path) -> list[str]:
    return [str(path.relative_to(package_root)) for path in root.rglob("*") if path.is_file()]


def _build_readme(
    formal_report: dict[str, Any],
    evidence_bundle: dict[str, Any] | None,
    compare_manifest: dict[str, Any] | None,
    attribution_result: dict[str, Any],
) -> str:
    pdf_status = str(formal_report.get("pdf_status", "fallback_html_only"))
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
        "",
        "正式报告说明：",
        "formal_report.html 为正式 HTML 报告主文件。",
        "若当前 PDF 状态为 fallback_html_only，可直接使用浏览器打开 formal_report.html 再打印为 PDF。",
        f"当前 PDF 状态：{pdf_status}",
        "",
        "结果表说明：",
        "rp_results.csv 为 RP 窗口结果表；spectral_qc_results.csv 为谱修正/QC 窗口结果表。",
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
    lines.append("")
    return "\n".join(lines)
