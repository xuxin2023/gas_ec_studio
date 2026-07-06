from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, url2pathname, urlopen
import zipfile

from core.comparison import raw_to_final_parity as raw_to_final_parity_module
from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
from core.comparison.official_raw_fixture_bundle import official_raw_fixture_bundle_schema
from core.comparison.raw_to_final_parity import run_raw_to_final_parity_harness
from core.ec_rp import analysis as ec_rp_analysis_module
from core.ec_rp import pipeline as ec_rp_pipeline_module
from core.storage import ghg_bundle as ghg_bundle_module
from core.storage import raw_importer as raw_importer_module
from core.storage.raw_importer import load_raw_text_frames
from models.station_models import MetadataBundle


DEFAULT_FIXTURE_PACK_PATH = Path("references/eddypro/fixture_pack_v1.json")
DEFAULT_PUBLIC_SPECTRAL_MANIFEST_PATH = Path("references/eddypro/public_spectral/manifest.json")
DEFAULT_PUBLIC_FULL_OUTPUT_MANIFEST_PATH = Path("references/eddypro/public_full_output/manifest.json")
DEFAULT_PUBLIC_OFFICIAL_RAW_MANIFEST_PATH = Path("references/eddypro/public_official_raw/manifest.json")
DEFAULT_PUBLIC_RAW_SEARCH_MANIFEST_PATH = Path("references/eddypro/public_raw_search/manifest.json")
OFFICIAL_RAW_BUNDLE_MANIFEST_NAMES = (
    "official_raw_fixture_bundle.json",
    "fixture_bundle.json",
    "manifest.json",
)
_FIXTURE_PACK_SUMMARY_CACHE_MAX_ENTRIES = 16
_FIXTURE_PACK_SUMMARY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_FIXTURE_PACK_SUMMARY_FILE_FIELDS = (
    "reference_json",
    "source_csv",
    "provenance_json",
    "protocol_log",
    "metadata_json",
    "raw_file",
    "raw_ghg_file",
    "tob1_file",
    "slt_file",
    "native_binary_file",
    "eddypro_project_file",
    "project_file",
    "settings_file",
    "official_full_output",
    "full_output_csv",
)
_FIXTURE_PACK_SUMMARY_PUBLIC_MANIFESTS = (
    DEFAULT_PUBLIC_SPECTRAL_MANIFEST_PATH,
    DEFAULT_PUBLIC_FULL_OUTPUT_MANIFEST_PATH,
    DEFAULT_PUBLIC_OFFICIAL_RAW_MANIFEST_PATH,
    DEFAULT_PUBLIC_RAW_SEARCH_MANIFEST_PATH,
)
_FIXTURE_PACK_SUMMARY_PERSISTENT_CACHE_SCHEMA = "fixture_pack_summary_cache_v2"
_PUBLIC_MANIFEST_LOCAL_PATH_KEYS = {
    "fixture_pack_path",
    "metadata_file",
    "path",
    "provenance_file",
    "raw_file",
    "reference_file",
}


def load_fixture_pack(path: str | Path | None = None) -> dict[str, Any]:
    pack_path = Path(path) if path is not None else DEFAULT_FIXTURE_PACK_PATH
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    payload["_pack_path"] = str(pack_path)
    return payload


def _resolved_path_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _file_signature(path: Path) -> tuple[str, int, int]:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    try:
        stat = resolved.stat()
        return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (str(resolved), 0, -1)


def _module_file_signature(module: Any) -> tuple[str, int, int]:
    filename = str(getattr(module, "__file__", "") or "")
    return _file_signature(Path(filename)) if filename else ("", 0, -1)


def _fixture_pack_summary_code_signatures() -> tuple[tuple[Any, ...], ...]:
    return (
        ("fixture_pack.py", *_file_signature(Path(__file__))),
        ("raw_to_final_parity.py", *_module_file_signature(raw_to_final_parity_module)),
        ("ec_rp_analysis.py", *_module_file_signature(ec_rp_analysis_module)),
        ("ec_rp_pipeline.py", *_module_file_signature(ec_rp_pipeline_module)),
        ("ghg_bundle.py", *_module_file_signature(ghg_bundle_module)),
        ("raw_importer.py", *_module_file_signature(raw_importer_module)),
    )


def _fixture_pack_summary_public_manifest_file_signatures(root: Path, manifest_path: Path) -> tuple[tuple[Any, ...], ...]:
    absolute_manifest = root / manifest_path
    try:
        manifest = json.loads(absolute_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()

    signatures: list[tuple[Any, ...]] = []

    def visit(value: Any, trail: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key)
                if normalized_key in _PUBLIC_MANIFEST_LOCAL_PATH_KEYS and isinstance(child, str):
                    path_text = child.strip()
                    if path_text and "://" not in path_text:
                        signatures.append(
                            (
                                str(manifest_path),
                                ".".join((*trail, normalized_key)),
                                *_file_signature(_resolve(root, path_text)),
                            )
                        )
                visit(child, (*trail, normalized_key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*trail, str(index)))

    visit(manifest, ())
    return tuple(sorted(signatures))


def _fixture_pack_summary_cache_key(pack_path: Path, root: Path, pack: dict[str, Any]) -> tuple[Any, ...]:
    file_signatures: list[tuple[Any, ...]] = [("pack", *_file_signature(pack_path))]
    file_signatures.extend(("code", *signature) for signature in _fixture_pack_summary_code_signatures())
    for manifest_path in _FIXTURE_PACK_SUMMARY_PUBLIC_MANIFESTS:
        file_signatures.append((str(manifest_path), *_file_signature(root / manifest_path)))
        file_signatures.extend(_fixture_pack_summary_public_manifest_file_signatures(root, manifest_path))
    for asset in list(pack.get("assets", []) or []):
        asset_payload = dict(asset or {})
        fixture_id = str(asset_payload.get("fixture_id", ""))
        for field_name in _FIXTURE_PACK_SUMMARY_FILE_FIELDS:
            value = str(asset_payload.get(field_name, "") or "").strip()
            if value:
                file_signatures.append((fixture_id, field_name, *_file_signature(_resolve(root, value))))
    return (
        "fixture_pack_summary_v1",
        _resolved_path_text(pack_path),
        _resolved_path_text(root),
        tuple(file_signatures),
    )


def _cache_fixture_pack_summary(cache_key: tuple[Any, ...], summary: dict[str, Any]) -> None:
    if cache_key not in _FIXTURE_PACK_SUMMARY_CACHE and len(_FIXTURE_PACK_SUMMARY_CACHE) >= _FIXTURE_PACK_SUMMARY_CACHE_MAX_ENTRIES:
        _FIXTURE_PACK_SUMMARY_CACHE.pop(next(iter(_FIXTURE_PACK_SUMMARY_CACHE)))
    _FIXTURE_PACK_SUMMARY_CACHE[cache_key] = deepcopy(summary)


def _fixture_pack_summary_persistent_cache_dir() -> Path | None:
    disabled = str(os.environ.get("GAS_EC_DISABLE_FIXTURE_PACK_SUMMARY_CACHE", "")).strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return None
    configured = str(os.environ.get("GAS_EC_FIXTURE_PACK_SUMMARY_CACHE_DIR", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "gas_ec_studio" / "fixture_pack_summary_cache"


def _fixture_pack_summary_persistent_cache_hash(cache_key: tuple[Any, ...]) -> str:
    encoded = json.dumps(cache_key, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _fixture_pack_summary_persistent_cache_path(cache_key: tuple[Any, ...]) -> tuple[Path | None, str]:
    cache_hash = _fixture_pack_summary_persistent_cache_hash(cache_key)
    cache_dir = _fixture_pack_summary_persistent_cache_dir()
    if cache_dir is None:
        return None, cache_hash
    return cache_dir / f"{cache_hash}.json", cache_hash


def _read_fixture_pack_summary_persistent_cache(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    path, cache_hash = _fixture_pack_summary_persistent_cache_path(cache_key)
    if path is None or not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if wrapper.get("artifact_type") != _FIXTURE_PACK_SUMMARY_PERSISTENT_CACHE_SCHEMA:
        return None
    if str(wrapper.get("cache_hash", "")) != cache_hash:
        return None
    payload = wrapper.get("summary", {})
    return deepcopy(payload) if isinstance(payload, dict) else None


def _write_fixture_pack_summary_persistent_cache(cache_key: tuple[Any, ...], summary: dict[str, Any]) -> None:
    path, cache_hash = _fixture_pack_summary_persistent_cache_path(cache_key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "artifact_type": _FIXTURE_PACK_SUMMARY_PERSISTENT_CACHE_SCHEMA,
                    "cache_hash": cache_hash,
                    "created_at": datetime.now().isoformat(),
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def build_fixture_pack_summary(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    root = _workspace_root_for_pack(path, workspace_root)
    pack_path = Path(path) if path is not None else root / DEFAULT_FIXTURE_PACK_PATH
    pack = load_fixture_pack(pack_path)
    cache_key = _fixture_pack_summary_cache_key(pack_path, root, pack)
    if use_cache and cache_key in _FIXTURE_PACK_SUMMARY_CACHE:
        return deepcopy(_FIXTURE_PACK_SUMMARY_CACHE[cache_key])
    if use_cache:
        cached_summary = _read_fixture_pack_summary_persistent_cache(cache_key)
        if cached_summary is not None:
            _cache_fixture_pack_summary(cache_key, cached_summary)
            return cached_summary
    assets = []
    errors: list[str] = []
    tier_counts: Counter[str] = Counter()
    total_real_windows = 0
    total_protocol_rows = 0
    raw_to_final_fixture_count = 0
    raw_to_final_pass_count = 0

    for asset in pack.get("assets", []):
        result = validate_fixture_asset(asset, workspace_root=root)
        assets.append(result)
        tier_counts[str(result.get("tier", ""))] += 1
        total_real_windows += int(result.get("window_count", 0) or 0) if result.get("tier") == "real_reference_output" else 0
        total_protocol_rows += int(result.get("row_count", 0) or 0) if result.get("tier") == "manual_protocol_validation" else 0
        if result.get("tier") == "raw_to_final_parity" and result.get("status") != "disabled":
            raw_to_final_fixture_count += 1
            if result.get("raw_to_final_parity", {}).get("status") == "pass":
                raw_to_final_pass_count += 1
        errors.extend(str(item) for item in result.get("errors", []))

    source_inventory = build_eddypro_source_inventory()
    public_spectral_summary = build_public_spectral_fixture_summary(workspace_root=root)
    public_full_output_summary = build_public_full_output_fixture_summary(workspace_root=root)
    public_official_raw_summary = build_public_official_raw_fixture_summary(workspace_root=root)
    public_raw_search_summary = build_public_raw_search_summary(workspace_root=root)
    public_fixture_catalog = build_public_eddypro_fixture_catalog(workspace_root=root)
    errors.extend(str(item) for item in public_spectral_summary.get("errors", []))
    errors.extend(str(item) for item in public_full_output_summary.get("errors", []))
    errors.extend(str(item) for item in public_official_raw_summary.get("errors", []))
    errors.extend(str(item) for item in public_raw_search_summary.get("errors", []))
    summary = {
        "fixture_pack_id": pack.get("fixture_pack_id", ""),
        "version": pack.get("version", ""),
        "status": "pass" if not errors else "fail",
        "asset_count": len(assets),
        "tier_counts": dict(sorted(tier_counts.items())),
        "real_reference_window_count": total_real_windows,
        "protocol_validation_row_count": total_protocol_rows,
        "raw_to_final_fixture_count": raw_to_final_fixture_count,
        "raw_to_final_pass_count": raw_to_final_pass_count,
        "disabled_fixture_count": sum(1 for asset in assets if asset.get("status") == "disabled"),
        "assets": assets,
        "public_spectral_fixture_summary": public_spectral_summary,
        "public_spectral_fixture_count": int(public_spectral_summary.get("fixture_count", 0) or 0),
        "public_spectral_status": public_spectral_summary.get("status", ""),
        "public_full_output_fixture_summary": public_full_output_summary,
        "public_full_output_fixture_count": int(public_full_output_summary.get("fixture_count", 0) or 0),
        "public_full_output_status": public_full_output_summary.get("status", ""),
        "public_official_raw_fixture_summary": public_official_raw_summary,
        "public_official_raw_candidate_count": int(public_official_raw_summary.get("candidate_count", 0) or 0),
        "public_official_raw_status": public_official_raw_summary.get("status", ""),
        "public_raw_search_summary": public_raw_search_summary,
        "public_raw_search_status": public_raw_search_summary.get("status", ""),
        "public_raw_search_lead_count": int(public_raw_search_summary.get("lead_count", 0) or 0),
        "public_raw_search_raw_data_candidate_count": int(public_raw_search_summary.get("raw_data_candidate_count", 0) or 0),
        "public_eddypro_fixture_catalog": public_fixture_catalog,
        "public_eddypro_fixture_catalog_status": public_fixture_catalog.get("status", ""),
        "coverage_gaps": list(pack.get("coverage_gaps", [])),
        "official_source_inventory": _fixture_source_inventory_summary(source_inventory),
        "truthfulness_note": pack.get("truthfulness_note", ""),
        "errors": errors,
    }
    _cache_fixture_pack_summary(cache_key, summary)
    _write_fixture_pack_summary_persistent_cache(cache_key, summary)
    return summary


def build_public_full_output_fixture_summary(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate a real public EddyPro Full_Output-style sample fixture."""

    root = _workspace_root(workspace_root)
    manifest_path = _resolve(root, path) if path is not None else root / DEFAULT_PUBLIC_FULL_OUTPUT_MANIFEST_PATH
    generated_at = datetime.now().isoformat()
    if not manifest_path.exists():
        return {
            "artifact_type": "public_eddypro_full_output_fixture_summary_v1",
            "generated_at": generated_at,
            "manifest_path": str(manifest_path),
            "status": "fail",
            "fixture_count": 0,
            "valid_fixture_count": 0,
            "files": [],
            "errors": [f"public full-output manifest missing: {manifest_path}"],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "artifact_type": "public_eddypro_full_output_fixture_summary_v1",
            "generated_at": generated_at,
            "manifest_path": str(manifest_path),
            "status": "fail",
            "fixture_count": 0,
            "valid_fixture_count": 0,
            "files": [],
            "errors": [f"public full-output manifest invalid: {exc}"],
        }

    errors: list[str] = []
    files: list[dict[str, Any]] = []
    for file_payload in list(manifest.get("files", []) or []):
        item = _validate_public_full_output_file(file_payload, root)
        files.append(item)
        errors.extend(str(error) for error in item.get("errors", []))

    sample_files = [item for item in files if item.get("role") == "full_output_sample"]
    descriptor_files = [item for item in files if item.get("role") == "variable_units_descriptor"]
    return {
        "artifact_type": "public_eddypro_full_output_fixture_summary_v1",
        "generated_at": generated_at,
        "manifest_id": manifest.get("manifest_id", ""),
        "manifest_path": str(manifest_path),
        "dataset_id": manifest.get("dataset_id", ""),
        "title": manifest.get("title", ""),
        "source_url": manifest.get("source_url", ""),
        "license": manifest.get("license", ""),
        "source_note": manifest.get("source_note", ""),
        "normalization_time": manifest.get("normalization_time", ""),
        "normalization_command": manifest.get("normalization_command", ""),
        "qc_mapping": dict(manifest.get("qc_mapping", {}) or {}),
        "known_limitations": list(manifest.get("known_limitations", []) or []),
        "original_files": list(manifest.get("original_files", []) or []),
        "status": "pass" if not errors else "fail",
        "fixture_count": len(files),
        "valid_fixture_count": sum(1 for item in files if item.get("status") == "pass"),
        "sample_row_count": sum(int(item.get("row_count", 0) or 0) for item in sample_files),
        "sample_column_count": max([int(item.get("column_count", 0) or 0) for item in sample_files] or [0]),
        "descriptor_variable_count": sum(int(item.get("variable_count", 0) or 0) for item in descriptor_files),
        "files": files,
        "errors": errors,
    }


def build_public_official_raw_fixture_summary(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Describe public official raw-data candidates without promoting them to parity fixtures."""

    root = _workspace_root(workspace_root)
    manifest_path = _resolve(root, path) if path is not None else root / DEFAULT_PUBLIC_OFFICIAL_RAW_MANIFEST_PATH
    manifest = _load_public_fixture_manifest(manifest_path)
    candidates = [_public_official_raw_candidate_record(dict(item or {}), root) for item in list(manifest.get("candidate_bundles", []) or [])]
    errors = [str(error) for item in candidates for error in list(item.get("errors", []) or [])]
    return {
        "artifact_type": "public_official_raw_fixture_candidate_summary_v1",
        "manifest_path": str(manifest_path),
        "manifest_id": manifest.get("manifest_id", ""),
        "dataset_id": manifest.get("dataset_id", ""),
        "title": manifest.get("title", ""),
        "source_url": manifest.get("source_url", ""),
        "license": manifest.get("license", ""),
        "source_note": manifest.get("source_note", ""),
        "acquired_at": manifest.get("acquired_at", ""),
        "normalization_time": manifest.get("normalization_time", ""),
        "normalization_command": manifest.get("normalization_command", ""),
        "qc_mapping": dict(manifest.get("qc_mapping", {}) or {}),
        "known_limitations": list(manifest.get("known_limitations", []) or []),
        "original_files": list(manifest.get("original_files", []) or []),
        "status": "pass" if not errors and candidates else "fail",
        "candidate_count": len(candidates),
        "valid_candidate_count": sum(1 for item in candidates if item.get("status") == "pass"),
        "fixture_count": 0,
        "valid_fixture_count": 0,
        "can_be_downloaded": any(bool(item.get("can_be_downloaded", False)) for item in candidates),
        "can_be_promoted_to_official_raw_bundle": False,
        "promotion_blockers": _dedupe(
            blocker
            for item in candidates
            for blocker in list(item.get("promotion_blockers", []) or [])
            if str(blocker).strip()
        ),
        "candidate_bundles": candidates,
        "errors": errors,
    }


def build_public_raw_search_summary(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Record public TOB1/SLT/native-binary search leads without claiming parity."""

    root = _workspace_root(workspace_root)
    manifest_path = _resolve(root, path) if path is not None else root / DEFAULT_PUBLIC_RAW_SEARCH_MANIFEST_PATH
    manifest = _load_public_fixture_manifest(manifest_path)
    leads = [_public_raw_search_lead_record(dict(item or {}), root) for item in list(manifest.get("leads", []) or [])]
    errors = [str(error) for lead in leads for error in list(lead.get("errors", []) or [])]
    raw_format_counts: Counter[str] = Counter()
    evidence_type_counts: Counter[str] = Counter()
    candidate_status_counts: Counter[str] = Counter()
    for lead in leads:
        for raw_format in list(lead.get("raw_formats", []) or []):
            raw_format_counts[str(raw_format)] += 1
        evidence_type_counts[str(lead.get("evidence_type", ""))] += 1
        candidate_status_counts[str(lead.get("candidate_status", ""))] += 1
    raw_data_candidate_count = sum(1 for lead in leads if bool(lead.get("can_support_raw_fixture_acquisition", False)))
    raw_to_final_candidate_count = sum(1 for lead in leads if bool(lead.get("can_support_raw_to_final_parity", False)))
    return {
        "artifact_type": "public_raw_binary_tob1_slt_search_summary_v1",
        "generated_at": datetime.now().isoformat(),
        "manifest_path": str(manifest_path),
        "manifest_id": manifest.get("manifest_id", ""),
        "dataset_id": manifest.get("dataset_id", ""),
        "title": manifest.get("title", ""),
        "source_url": manifest.get("source_url", ""),
        "license": manifest.get("license", ""),
        "source_note": manifest.get("source_note", ""),
        "normalization_time": manifest.get("normalization_time", ""),
        "normalization_command": manifest.get("normalization_command", ""),
        "qc_mapping": dict(manifest.get("qc_mapping", {}) or {}),
        "known_limitations": list(manifest.get("known_limitations", []) or []),
        "search_status": dict(manifest.get("search_status", {}) or {}),
        "source_derived_fallback": dict(manifest.get("source_derived_fallback", {}) or {}),
        "source_derived_fallbacks": list(manifest.get("source_derived_fallbacks", []) or []),
        "status": "pass" if leads and not errors else "fail",
        "lead_count": len(leads),
        "valid_lead_count": sum(1 for lead in leads if lead.get("status") == "pass"),
        "raw_data_candidate_count": raw_data_candidate_count,
        "raw_to_final_candidate_count": raw_to_final_candidate_count,
        "raw_format_counts": dict(sorted(raw_format_counts.items())),
        "evidence_type_counts": dict(sorted(evidence_type_counts.items())),
        "candidate_status_counts": dict(sorted(candidate_status_counts.items())),
        "fixture_count": 0,
        "valid_fixture_count": 0,
        "can_support_raw_fixture_acquisition": raw_data_candidate_count > 0,
        "can_support_full_raw_to_final_eddypro_claim": raw_to_final_candidate_count > 0,
        "promotion_blockers": _dedupe(
            blocker
            for lead in leads
            for blocker in list(lead.get("promotion_blockers", []) or [])
            if str(blocker).strip()
        ),
        "leads": leads,
        "errors": errors,
        "truthfulness_note": (
            "This search ledger records public leads and documentation sources for TOB1/SLT/native-binary parity work. "
            "Documentation-only leads and source-derived fallback fixtures do not support a full raw-to-final EddyPro parity claim."
        ),
    }


def build_public_eddypro_fixture_catalog(
    *,
    workspace_root: str | Path | None = None,
    spectral_manifest_path: str | Path | None = None,
    full_output_manifest_path: str | Path | None = None,
    official_raw_manifest_path: str | Path | None = None,
    raw_search_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate public EddyPro-derived fixtures into one delivery artifact."""

    root = _workspace_root(workspace_root)
    spectral_summary = build_public_spectral_fixture_summary(spectral_manifest_path, workspace_root=root)
    full_output_summary = build_public_full_output_fixture_summary(full_output_manifest_path, workspace_root=root)
    official_raw_summary = build_public_official_raw_fixture_summary(official_raw_manifest_path, workspace_root=root)
    raw_search_summary = build_public_raw_search_summary(raw_search_manifest_path, workspace_root=root)
    summaries = [spectral_summary, full_output_summary, official_raw_summary, raw_search_summary]
    errors = [str(error) for summary in summaries for error in list(summary.get("errors", []) or [])]
    datasets = [
        _public_fixture_dataset_record("spectral", spectral_summary),
        _public_fixture_dataset_record("full_output", full_output_summary),
        _public_fixture_dataset_record("official_raw_candidate", official_raw_summary),
        _public_fixture_dataset_record("raw_binary_search", raw_search_summary),
    ]
    fixture_count = sum(int(summary.get("fixture_count", 0) or 0) for summary in summaries)
    valid_fixture_count = sum(int(summary.get("valid_fixture_count", 0) or 0) for summary in summaries)
    remote_originals = [
        dict(item)
        for summary in summaries
        for item in list(summary.get("original_files", []) or [])
        if isinstance(item, dict)
    ]
    acquisition_commands = [
        str(summary.get("normalization_command", "")).strip()
        for summary in summaries
        if str(summary.get("normalization_command", "")).strip()
    ]
    return {
        "artifact_type": "public_eddypro_fixture_catalog_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if not errors and fixture_count == valid_fixture_count and fixture_count > 0 else "fail",
        "workspace_root": str(root),
        "dataset_count": len([item for item in datasets if item.get("dataset_id")]),
        "fixture_count": fixture_count,
        "valid_fixture_count": valid_fixture_count,
        "spectral_status": spectral_summary.get("status", ""),
        "spectral_fixture_count": int(spectral_summary.get("fixture_count", 0) or 0),
        "full_output_status": full_output_summary.get("status", ""),
        "full_output_fixture_count": int(full_output_summary.get("fixture_count", 0) or 0),
        "official_raw_status": official_raw_summary.get("status", ""),
        "official_raw_candidate_count": int(official_raw_summary.get("candidate_count", 0) or 0),
        "official_raw_valid_candidate_count": int(official_raw_summary.get("valid_candidate_count", 0) or 0),
        "raw_binary_search_status": raw_search_summary.get("status", ""),
        "raw_binary_search_lead_count": int(raw_search_summary.get("lead_count", 0) or 0),
        "raw_binary_search_raw_data_candidate_count": int(raw_search_summary.get("raw_data_candidate_count", 0) or 0),
        "raw_binary_search_raw_format_counts": dict(raw_search_summary.get("raw_format_counts", {}) or {}),
        "datasets": datasets,
        "remote_originals": remote_originals,
        "acquisition_plan": {
            "artifact_type": "public_eddypro_fixture_acquisition_plan_v1",
            "status": "ready" if acquisition_commands else "missing_commands",
            "commands": acquisition_commands,
            "verification": [
                "Run build_public_eddypro_fixture_catalog() after acquisition.",
                "Require status=pass, fixture_count=valid_fixture_count, and matching MD5/SHA-256 for local sample files.",
                "For large remote originals, verify retained expected_size_bytes and expected_md5 before promoting to official bundle evidence.",
            ],
        },
        "claim_boundary": {
            "can_support_processed_output_schema_evidence": bool(full_output_summary.get("status") == "pass"),
            "can_support_spectral_output_schema_evidence": bool(spectral_summary.get("status") == "pass"),
            "can_support_official_raw_bundle_acquisition": bool(official_raw_summary.get("status") == "pass"),
            "can_support_full_raw_to_final_eddypro_claim": False,
            "reason": (
                "Public fixtures currently validate EddyPro-derived processed-output and spectral products, "
                "and now include a public official LI-COR EddyPro sample-data acquisition candidate. "
                "The raw-binary search ledger records TOB1/SLT/native-binary leads separately, without promoting "
                "documentation-only sources to fixtures. They still do not provide a registered high-frequency raw input, EddyPro project/settings, "
                "official output, normalized reference, and acceptance record in one official raw-to-final bundle."
            ),
        },
        "spectral_fixture_summary": spectral_summary,
        "full_output_fixture_summary": full_output_summary,
        "official_raw_fixture_summary": official_raw_summary,
        "raw_binary_search_summary": raw_search_summary,
        "errors": errors,
    }


def acquire_public_eddypro_fixture_files(
    *,
    workspace_root: str | Path | None = None,
    spectral_manifest_path: str | Path | None = None,
    full_output_manifest_path: str | Path | None = None,
    official_raw_manifest_path: str | Path | None = None,
    overwrite: bool = False,
    include_remote_originals: bool = False,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Download or refresh public EddyPro fixture files declared by manifests."""

    root = _workspace_root(workspace_root)
    manifest_specs = [
        ("spectral", _resolve(root, spectral_manifest_path) if spectral_manifest_path else root / DEFAULT_PUBLIC_SPECTRAL_MANIFEST_PATH),
        ("full_output", _resolve(root, full_output_manifest_path) if full_output_manifest_path else root / DEFAULT_PUBLIC_FULL_OUTPUT_MANIFEST_PATH),
        (
            "official_raw_candidate",
            _resolve(root, official_raw_manifest_path)
            if official_raw_manifest_path
            else root / DEFAULT_PUBLIC_OFFICIAL_RAW_MANIFEST_PATH,
        ),
    ]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for family, manifest_path in manifest_specs:
        manifest = _load_public_fixture_manifest_for_acquisition(manifest_path)
        if manifest.get("status") == "fail":
            error = str(manifest.get("error", f"manifest load failed: {manifest_path}"))
            errors.append(error)
            items.append(
                {
                    "family": family,
                    "manifest_path": str(manifest_path),
                    "status": "fail",
                    "action": "manifest_error",
                    "errors": [error],
                }
            )
            continue
        file_entries = list(manifest.get("files", []) or [])
        if include_remote_originals:
            file_entries.extend(
                {
                    **dict(entry),
                    "role": str(dict(entry).get("role", "remote_original")),
                    "remote_original": True,
                }
                for entry in list(manifest.get("original_files", []) or [])
                if isinstance(entry, dict)
            )
        for entry in file_entries:
            item = _acquire_public_fixture_entry(
                family=family,
                manifest_path=manifest_path,
                entry=dict(entry or {}),
                root=root,
                overwrite=overwrite,
                timeout_s=timeout_s,
            )
            items.append(item)
            errors.extend(str(error) for error in item.get("errors", []))

    catalog = build_public_eddypro_fixture_catalog(
        workspace_root=root,
        spectral_manifest_path=spectral_manifest_path,
        full_output_manifest_path=full_output_manifest_path,
        official_raw_manifest_path=official_raw_manifest_path,
    )
    errors.extend(str(error) for error in catalog.get("errors", []))
    downloaded_count = sum(1 for item in items if item.get("action") == "downloaded")
    skipped_count = sum(1 for item in items if item.get("action") == "skipped_existing")
    failed_count = sum(1 for item in items if item.get("status") == "fail")
    return {
        "artifact_type": "public_eddypro_fixture_acquisition_run_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if not errors and catalog.get("status") == "pass" else "fail",
        "workspace_root": str(root),
        "overwrite": bool(overwrite),
        "include_remote_originals": bool(include_remote_originals),
        "timeout_s": float(timeout_s),
        "item_count": len(items),
        "downloaded_count": downloaded_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "items": items,
        "catalog": catalog,
        "claim_boundary": dict(catalog.get("claim_boundary", {}) or {}),
        "errors": errors,
    }


def inspect_public_official_raw_archive(
    archive_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect a downloaded public official raw archive without promoting it to parity evidence."""

    root = _workspace_root(workspace_root)
    path = _resolve(root, archive_path)
    generated_at = datetime.now().isoformat()
    if not path.exists() or not path.is_file():
        return {
            "artifact_type": "public_official_raw_archive_inspection_v1",
            "generated_at": generated_at,
            "status": "fail",
            "archive_path": str(path),
            "errors": [f"archive missing: {path}"],
        }
    try:
        archive = _read_public_official_raw_archive(path)
    except zipfile.BadZipFile as exc:
        return {
            "artifact_type": "public_official_raw_archive_inspection_v1",
            "generated_at": generated_at,
            "status": "fail",
            "archive_path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "errors": [f"archive invalid: {exc}"],
        }

    files = archive["files"]
    role_counts = Counter(role for item in files for role in list(item.get("roles", []) or []))
    raw_format_counts = Counter(str(item.get("extension", "")) for item in files if "raw_input" in item.get("roles", []))
    candidate_bundles = _public_official_raw_archive_candidate_bundles(files)
    missing_required_roles = _archive_missing_required_roles(files)
    promotion_blockers = _public_official_raw_archive_promotion_blockers(
        missing_required_roles=missing_required_roles,
        candidate_bundles=candidate_bundles,
    )
    return {
        "artifact_type": "public_official_raw_archive_inspection_v1",
        "generated_at": generated_at,
        "status": "pass" if files else "fail",
        "archive_path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "outer_archive": archive["outer_archive"],
        "inspected_archive": archive["inspected_archive"],
        "nested_archive_count": len(archive["nested_archives"]),
        "nested_archives": archive["nested_archives"],
        "file_count": len(files),
        "total_uncompressed_bytes": sum(int(item.get("size_bytes", 0) or 0) for item in files),
        "raw_file_count": int(role_counts.get("raw_input", 0)),
        "raw_format_counts": dict(sorted(raw_format_counts.items())),
        "project_file_count": int(role_counts.get("eddypro_project_or_settings", 0)),
        "full_output_count": int(role_counts.get("official_full_output", 0)),
        "metadata_file_count": int(role_counts.get("metadata", 0)),
        "biomet_file_count": int(role_counts.get("biomet", 0)),
        "ignored_macosx_file_count": int(role_counts.get("ignored_macosx", 0)),
        "candidate_bundle_count": len(candidate_bundles),
        "candidate_bundles": candidate_bundles,
        "missing_required_roles": missing_required_roles,
        "can_be_promoted_to_official_raw_bundle": False,
        "promotion_blockers": promotion_blockers,
        "claim_boundary": {
            "can_support_raw_ingestion_fixture": int(role_counts.get("raw_input", 0)) > 0,
            "can_support_full_raw_to_final_eddypro_claim": False,
            "reason": (
                "The archive contains public official raw input candidates, but a parity claim also requires "
                "EddyPro project/settings, official Full_Output, normalized reference/provenance, executable-run "
                "evidence, registration, and closure acceptance."
            ),
        },
        "files": files,
        "errors": [],
        "truthfulness_note": (
            "This inspection is acquisition evidence only. It must not be treated as raw-to-final parity until "
            "a complete official raw bundle is built and accepted through the closure gate."
        ),
    }


def materialize_public_official_raw_bundle_draft(
    archive_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    output_root: str | Path | None = None,
    candidate_id: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Extract a public official raw-only candidate into an auditable bundle draft."""

    root = _workspace_root(workspace_root)
    path = _resolve(root, archive_path)
    inspection = inspect_public_official_raw_archive(path, workspace_root=root)
    if inspection.get("status") != "pass":
        return {
            "artifact_type": "public_official_raw_bundle_draft_v1",
            "generated_at": datetime.now().isoformat(),
            "status": "fail",
            "archive_path": str(path),
            "errors": list(inspection.get("errors", []) or ["archive inspection failed"]),
            "archive_inspection": inspection,
        }
    candidates = [dict(item or {}) for item in list(inspection.get("candidate_bundles", []) or [])]
    selected = _select_public_official_raw_candidate(candidates, candidate_id=candidate_id)
    if not selected:
        return {
            "artifact_type": "public_official_raw_bundle_draft_v1",
            "generated_at": datetime.now().isoformat(),
            "status": "fail",
            "archive_path": str(path),
            "errors": [f"candidate_id not found: {candidate_id or '<first>'}"],
            "archive_inspection": inspection,
        }

    selected_id = str(selected.get("candidate_id", "") or "public_official_raw_candidate")
    bundle_root = (
        _resolve(root, output_root)
        if output_root not in (None, "")
        else root / "artifacts" / "eddypro_public_raw" / "official_raw_candidates" / selected_id
    )
    raw_dir = bundle_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (bundle_root / "eddypro").mkdir(parents=True, exist_ok=True)
    (bundle_root / "normalized").mkdir(parents=True, exist_ok=True)
    (bundle_root / "metadata").mkdir(parents=True, exist_ok=True)

    raw_paths = _extract_public_official_raw_candidate_files(
        archive_path=path,
        candidate_folder=str(selected.get("folder", "")),
        raw_dir=raw_dir,
        overwrite=overwrite,
    )
    embedded_evidence = _extract_embedded_eddypro_evidence_from_ghg(
        raw_paths=raw_paths,
        bundle_root=bundle_root,
        overwrite=overwrite,
    )
    relative_raw_paths = [str(item.relative_to(bundle_root)).replace("\\", "/") for item in raw_paths]
    manifest_path = bundle_root / "official_raw_fixture_bundle.json"
    manifest = _public_official_raw_bundle_draft_manifest(
        fixture_id=f"{selected_id}_licor_public_raw_candidate",
        selected=selected,
        archive_inspection=inspection,
        relative_raw_paths=relative_raw_paths,
        embedded_evidence=embedded_evidence,
    )
    if overwrite or not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    from core.comparison.official_raw_fixture_bundle import inspect_official_raw_fixture_bundle

    bundle_inspection = inspect_official_raw_fixture_bundle(bundle_root, workspace_root=root)
    missing_required_groups = list(bundle_inspection.get("missing_required_files", []) or [])
    official_run = dict(bundle_inspection.get("official_eddypro_run", {}) or {})
    official_run_missing = list(official_run.get("missing_requirements", []) or [])
    extracted_files = [
        {
            "path": str(path_item),
            "relative_to_bundle": str(path_item.relative_to(bundle_root)).replace("\\", "/"),
            "size_bytes": path_item.stat().st_size,
            "sha256": _sha256(path_item),
        }
        for path_item in raw_paths
    ]
    return {
        "artifact_type": "public_official_raw_bundle_draft_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "draft_ready" if raw_paths else "fail",
        "archive_path": str(path),
        "bundle_root": str(bundle_root),
        "manifest_path": str(manifest_path),
        "candidate_id": selected_id,
        "fixture_id": manifest["fixture_id"],
        "extracted_file_count": len(extracted_files),
        "raw_file_count": len(relative_raw_paths),
        "raw_files": relative_raw_paths,
        "extracted_files": extracted_files,
        "embedded_eddypro_evidence": embedded_evidence,
        "bundle_inspection_status": str(bundle_inspection.get("status", "")),
        "missing_required_groups": missing_required_groups,
        "official_eddypro_run_gate_status": str(official_run.get("gate_status", "")),
        "official_eddypro_run_missing_requirements": official_run_missing,
        "can_run_official_raw_closure": bool(
            bundle_inspection.get("status") == "ready_for_registration" and official_run.get("gate_status") == "pass"
        ),
        "promotion_blockers": _dedupe(
            [
                *[f"bundle draft missing required file group: {item}" for item in missing_required_groups],
                *[f"official EddyPro executable-run evidence missing: {item}" for item in official_run_missing],
                "bundle draft has not passed --run-official-raw-closure",
            ]
        ),
        "archive_inspection": inspection,
        "bundle_inspection": bundle_inspection,
        "truthfulness_note": (
            "This draft extracts official public raw files into the official bundle directory contract. "
            "It is intentionally incomplete and cannot support full EddyPro parity until missing evidence is added and closure passes."
        ),
        "errors": [] if raw_paths else ["no raw files extracted"],
    }


def _public_fixture_dataset_record(kind: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "dataset_id": summary.get("dataset_id", ""),
        "title": summary.get("title", ""),
        "source_url": summary.get("source_url", ""),
        "license": summary.get("license", ""),
        "status": summary.get("status", ""),
        "fixture_count": int(summary.get("fixture_count", 0) or 0),
        "valid_fixture_count": int(summary.get("valid_fixture_count", 0) or 0),
        "normalization_time": summary.get("normalization_time", ""),
        "qc_mapping": dict(summary.get("qc_mapping", {}) or {}),
        "known_limitations": list(summary.get("known_limitations", []) or []),
        **(
            {
                "candidate_count": int(summary.get("candidate_count", 0) or 0),
                "valid_candidate_count": int(summary.get("valid_candidate_count", 0) or 0),
                "can_be_downloaded": bool(summary.get("can_be_downloaded", False)),
                "promotion_blockers": list(summary.get("promotion_blockers", []) or []),
            }
            if kind == "official_raw_candidate"
            else {}
        ),
        **(
            {
                "lead_count": int(summary.get("lead_count", 0) or 0),
                "raw_data_candidate_count": int(summary.get("raw_data_candidate_count", 0) or 0),
                "raw_to_final_candidate_count": int(summary.get("raw_to_final_candidate_count", 0) or 0),
                "raw_format_counts": dict(summary.get("raw_format_counts", {}) or {}),
                "promotion_blockers": list(summary.get("promotion_blockers", []) or []),
            }
            if kind == "raw_binary_search"
            else {}
        ),
    }


def _public_raw_search_lead_record(lead: dict[str, Any], root: Path) -> dict[str, Any]:
    raw_formats = [
        str(item).strip().lower().lstrip(".")
        for item in list(lead.get("raw_formats", []) or [])
        if str(item).strip()
    ]
    source_url = str(lead.get("source_url", "") or "")
    source_name = str(lead.get("source_name", "") or "")
    evidence_type = str(lead.get("evidence_type", "") or "unknown")
    candidate_status = str(lead.get("candidate_status", "") or "unknown")
    local_path = str(lead.get("path", "") or "")
    target_path = _resolve(root, local_path) if local_path else None
    can_download = bool(lead.get("download_url") or lead.get("source_url")) and bool(local_path)
    can_support_raw = candidate_status in {"downloadable_raw_data", "raw_archive_candidate"} and can_download
    can_support_raw_to_final = bool(can_support_raw and lead.get("has_eddypro_project") and lead.get("has_official_full_output"))
    promotion_blockers = list(lead.get("promotion_blockers", []) or [])
    if evidence_type != "raw_data":
        promotion_blockers.append("lead is not a downloadable raw-data fixture")
    if not can_support_raw:
        promotion_blockers.append("lead does not provide an auditable local raw-data download path")
    if not can_support_raw_to_final:
        promotion_blockers.append("lead lacks a complete EddyPro project/settings plus official Full_Output raw-to-final pair")
    errors: list[str] = []
    if not source_url:
        errors.append("lead source_url missing")
    if not raw_formats:
        errors.append("lead raw_formats missing")
    return {
        "lead_id": str(lead.get("lead_id", "")),
        "source_name": source_name,
        "source_url": source_url,
        "license": str(lead.get("license", "")),
        "raw_formats": raw_formats,
        "evidence_type": evidence_type,
        "candidate_status": candidate_status,
        "status": "pass" if not errors else "fail",
        "path": str(target_path) if target_path is not None else "",
        "local_file_exists": bool(target_path.exists()) if target_path is not None else False,
        "can_be_downloaded": can_download,
        "can_support_raw_fixture_acquisition": can_support_raw,
        "can_support_raw_to_final_parity": can_support_raw_to_final,
        "has_eddypro_project": bool(lead.get("has_eddypro_project", False)),
        "has_official_full_output": bool(lead.get("has_official_full_output", False)),
        "source_reference": dict(lead.get("source_reference", {}) or {}),
        "notes": str(lead.get("notes", "")),
        "promotion_blockers": _dedupe(promotion_blockers),
        "errors": errors,
    }


def _public_official_raw_candidate_record(candidate: dict[str, Any], root: Path) -> dict[str, Any]:
    required_roles = [
        "high_frequency_raw_input",
        "eddypro_project_or_settings_file",
        "official_eddypro_full_output",
        "normalized_reference_with_provenance",
        "official_eddypro_executable_run",
    ]
    declared_roles = [str(item) for item in list(candidate.get("declared_roles", []) or []) if str(item).strip()]
    source_url = str(candidate.get("source_url", "") or "")
    local_path = str(candidate.get("path", "") or "")
    target_path = _resolve(root, local_path) if local_path else None
    missing_roles = [role for role in required_roles if role not in declared_roles]
    promotion_blockers = list(candidate.get("promotion_blockers", []) or [])
    if missing_roles:
        promotion_blockers.append(f"candidate bundle has not been inspected for roles: {', '.join(missing_roles)}")
    if not local_path:
        promotion_blockers.append("candidate bundle has not been downloaded into an auditable local path")
    return {
        "candidate_id": str(candidate.get("candidate_id", "")),
        "source_name": str(candidate.get("source_name", "")),
        "source_url": source_url,
        "path": str(target_path) if target_path is not None else "",
        "expected_size_bytes": int(candidate.get("expected_size_bytes", 0) or 0),
        "expected_sha256": str(candidate.get("expected_sha256", "")),
        "expected_md5": str(candidate.get("expected_md5", "")),
        "license": str(candidate.get("license", "")),
        "status": "pass" if source_url else "fail",
        "can_be_downloaded": bool(source_url and local_path),
        "local_file_exists": bool(target_path.exists()) if target_path is not None else False,
        "declared_roles": declared_roles,
        "missing_roles": missing_roles,
        "promotion_blockers": _dedupe(promotion_blockers),
        "truthfulness_note": (
            "This public raw candidate is acquisition evidence only. It is not an official raw-to-final parity fixture "
            "until the downloaded archive is unpacked, inspected, normalized, registered, and accepted through closure."
        ),
        "errors": [] if source_url else ["candidate source_url missing"],
    }


def _read_public_official_raw_archive(path: Path) -> dict[str, Any]:
    nested_archives: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as outer:
        outer_infos = outer.infolist()
        outer_files = [
            info for info in outer_infos if not info.is_dir() and not _is_macosx_artifact(info.filename)
        ]
        zip_files = [info for info in outer_files if Path(info.filename).suffix.lower() == ".zip"]
        if len(zip_files) == 1 and len(outer_files) == 1:
            nested_info = zip_files[0]
            nested_bytes = outer.read(nested_info.filename)
            nested_archives.append(
                {
                    "name": nested_info.filename,
                    "size_bytes": nested_info.file_size,
                    "compressed_size_bytes": nested_info.compress_size,
                    "sha256": hashlib.sha256(nested_bytes).hexdigest().upper(),
                    "selected_for_inspection": True,
                }
            )
            with zipfile.ZipFile(BytesIO(nested_bytes)) as nested:
                return {
                    "outer_archive": _archive_summary(path, outer_infos),
                    "inspected_archive": {
                        "name": nested_info.filename,
                        "source": "nested_zip",
                        "size_bytes": nested_info.file_size,
                        "sha256": nested_archives[-1]["sha256"],
                    },
                    "nested_archives": nested_archives,
                    "files": _public_official_raw_zip_file_records(nested.infolist()),
                }
        nested_archives.extend(
            {
                "name": info.filename,
                "size_bytes": info.file_size,
                "compressed_size_bytes": info.compress_size,
                "sha256": "",
                "selected_for_inspection": False,
            }
            for info in zip_files
        )
        return {
            "outer_archive": _archive_summary(path, outer_infos),
            "inspected_archive": {
                "name": path.name,
                "source": "outer_zip",
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            },
            "nested_archives": nested_archives,
            "files": _public_official_raw_zip_file_records(outer_infos),
        }


def _select_public_official_raw_candidate(
    candidates: list[dict[str, Any]],
    *,
    candidate_id: str = "",
) -> dict[str, Any]:
    if not candidates:
        return {}
    requested = str(candidate_id or "").strip()
    if not requested:
        return dict(sorted(candidates, key=lambda item: str(item.get("candidate_id", "")))[0])
    for item in candidates:
        if requested in {str(item.get("candidate_id", "")), str(item.get("folder", ""))}:
            return dict(item)
    return {}


def _extract_public_official_raw_candidate_files(
    *,
    archive_path: Path,
    candidate_folder: str,
    raw_dir: Path,
    overwrite: bool = False,
) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    folder = candidate_folder.replace("\\", "/").strip("/")
    archive_bytes = _selected_public_official_raw_archive_bytes(archive_path)
    extracted: list[Path] = []
    used_names: set[str] = set()
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        members = [
            info
            for info in archive.infolist()
            if _is_public_official_raw_candidate_member(info, folder)
        ]
        for info in sorted(members, key=lambda item: item.filename):
            target = _unique_public_official_raw_target(raw_dir, Path(info.filename).name, used_names)
            used_names.add(target.name)
            if target.exists() and not overwrite:
                extracted.append(target)
                continue
            target.write_bytes(archive.read(info.filename))
            extracted.append(target)
    return extracted


def _selected_public_official_raw_archive_bytes(path: Path) -> bytes:
    with zipfile.ZipFile(path) as outer:
        outer_files = [
            info for info in outer.infolist() if not info.is_dir() and not _is_macosx_artifact(info.filename)
        ]
        nested_zips = [info for info in outer_files if Path(info.filename).suffix.lower() == ".zip"]
        if len(nested_zips) == 1 and len(outer_files) == 1:
            return outer.read(nested_zips[0].filename)
    return path.read_bytes()


def _is_public_official_raw_candidate_member(info: zipfile.ZipInfo, folder: str) -> bool:
    if info.is_dir() or _is_macosx_artifact(info.filename):
        return False
    normalized = info.filename.replace("\\", "/").strip("/")
    if folder and not (normalized == folder or normalized.startswith(f"{folder}/")):
        return False
    return "raw_input" in _public_official_raw_file_roles(normalized)


def _unique_public_official_raw_target(raw_dir: Path, filename: str, used_names: set[str]) -> Path:
    safe_name = Path(filename).name or "raw_input.ghg"
    target = raw_dir / safe_name
    if safe_name not in used_names:
        return target
    stem = target.stem or "raw_input"
    suffix = target.suffix
    index = 2
    while True:
        candidate = raw_dir / f"{stem}_{index}{suffix}"
        if candidate.name not in used_names:
            return candidate
        index += 1


def _extract_embedded_eddypro_evidence_from_ghg(
    *,
    raw_paths: list[Path],
    bundle_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "artifact_type": "embedded_eddypro_evidence_extraction_v1",
        "status": "not_found",
        "source_raw_file": "",
        "project_file": "",
        "official_full_output": "",
        "log_file": "",
        "reference_json": "",
        "provenance_json": "",
        "normalization_result": {},
        "extracted_members": [],
        "errors": [],
        "truthfulness_note": (
            "Embedded EddyPro/SmartFlux files are preserved as source evidence. They do not prove an external "
            "EddyPro executable run unless a run sidecar with exit_code=0 is supplied."
        ),
    }
    for raw_path in raw_paths:
        if not zipfile.is_zipfile(raw_path):
            continue
        with zipfile.ZipFile(raw_path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/") and name.lower().startswith("eddypro/")]
            project_member = _first_embedded_eddypro_member(names, suffix=".eddypro")
            output_member = _first_embedded_eddypro_member(names, suffix=".csv", contains="full_output")
            log_member = _first_embedded_eddypro_member(names, suffix=".log")
            if not any((project_member, output_member, log_member)):
                continue
            evidence["source_raw_file"] = str(raw_path)
            evidence["project_file"] = _extract_embedded_eddypro_member(
                archive,
                project_member,
                bundle_root=bundle_root,
                overwrite=overwrite,
            )
            evidence["official_full_output"] = _extract_embedded_eddypro_member(
                archive,
                output_member,
                bundle_root=bundle_root,
                overwrite=overwrite,
            )
            evidence["log_file"] = _extract_embedded_eddypro_member(
                archive,
                log_member,
                bundle_root=bundle_root,
                overwrite=overwrite,
            )
            evidence["extracted_members"] = [
                item
                for item in [
                    project_member,
                    output_member,
                    log_member,
                ]
                if item
            ]
            break
    full_output = evidence.get("official_full_output", "")
    if full_output:
        normalization = _normalize_embedded_full_output(
            bundle_root=bundle_root,
            full_output_relative=str(full_output),
            project_relative=str(evidence.get("project_file", "")),
        )
        evidence["normalization_result"] = normalization
        if normalization.get("status") in {"normalized", "empty_reference"}:
            evidence["reference_json"] = "normalized/reference.json"
            evidence["provenance_json"] = "normalized/provenance.json"
    if evidence.get("official_full_output") and evidence.get("project_file"):
        evidence["status"] = "embedded_output_ready" if evidence.get("reference_json") else "embedded_output_extracted"
    return evidence


def _first_embedded_eddypro_member(names: list[str], *, suffix: str, contains: str = "") -> str:
    for name in sorted(names):
        lower = name.lower()
        if lower.endswith(suffix.lower()) and (not contains or contains.lower() in lower):
            return name
    return ""


def _extract_embedded_eddypro_member(
    archive: zipfile.ZipFile,
    member_name: str,
    *,
    bundle_root: Path,
    overwrite: bool = False,
) -> str:
    if not member_name:
        return ""
    target = bundle_root / "eddypro" / Path(member_name).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not target.exists():
        target.write_bytes(archive.read(member_name))
    return str(target.relative_to(bundle_root)).replace("\\", "/")


def _normalize_embedded_full_output(
    *,
    bundle_root: Path,
    full_output_relative: str,
    project_relative: str = "",
) -> dict[str, Any]:
    from core.comparison.eddypro_full_output_normalizer import write_eddypro_full_output_reference

    full_output_path = bundle_root / full_output_relative
    metadata_sources = [project_relative] if project_relative else []
    command = (
        "gas-ec-headless --materialize-public-official-raw-bundle "
        '"artifacts/eddypro_public_raw/EddyPro Sample Datasets.zip"'
    )
    try:
        return write_eddypro_full_output_reference(
            full_output_path,
            reference_path=bundle_root / "normalized" / "reference.json",
            provenance_path=bundle_root / "normalized" / "provenance.json",
            reference_id=f"{_safe_id_from_path(str(bundle_root.name))}_embedded_full_output_reference",
            normalization_command=command,
            metadata_source_files=metadata_sources,
        )
    except Exception as exc:
        return {
            "artifact_type": "eddypro_full_output_normalization_result_v1",
            "status": "normalization_error",
            "errors": [str(exc)],
        }


def _public_official_raw_bundle_draft_manifest(
    *,
    fixture_id: str,
    selected: dict[str, Any],
    archive_inspection: dict[str, Any],
    relative_raw_paths: list[str],
    embedded_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first_raw = relative_raw_paths[0] if relative_raw_paths else ""
    raw_format_counts = dict(selected.get("raw_format_counts", {}) or {})
    source_archive = dict(archive_inspection.get("inspected_archive", {}) or {})
    files = {"raw_file": first_raw} if first_raw else {}
    embedded = dict(embedded_evidence or {})
    if embedded.get("project_file"):
        files["eddypro_project_file"] = str(embedded["project_file"])
    if embedded.get("official_full_output"):
        files["official_full_output"] = str(embedded["official_full_output"])
    if embedded.get("reference_json"):
        files["reference_json"] = str(embedded["reference_json"])
    if embedded.get("provenance_json"):
        files["provenance_json"] = str(embedded["provenance_json"])
    return {
        "fixture_id": fixture_id,
        "site_class": "licor_public_ghg_sample_raw_only",
        "software": "EddyPro",
        "software_version": "",
        "official_eddypro_run": {
            "gate_status": "blocked",
            "capture_status": "embedded_output_only" if embedded.get("official_full_output") else "not_available",
            "software_version": "",
            "command": "",
            "run_completed_at": "",
            "output_files": [str(embedded["official_full_output"])] if embedded.get("official_full_output") else [],
            "truthfulness_note": (
                "Embedded EddyPro output was found inside the public .ghg bundle, but no operator-captured "
                "EddyPro executable run with exit_code=0 has been supplied."
            ),
        },
        "files": files,
        "raw_files": relative_raw_paths,
        "import_plan": {
            "artifact_type": "official_raw_import_plan_v1",
            "status": "raw_only_candidate",
            "raw_input": {
                "role": "raw_file",
                "path": first_raw,
                "format": next(iter(raw_format_counts.keys()), "ghg"),
                "file_count": len(relative_raw_paths),
            },
            "metadata_draft": {
                "project": {"code": "licor_public_ghg_sample_data_2021"},
                "site": {"station_code": "licor_public_sample"},
                "raw_file_description": {
                    "source_name": Path(first_raw).name if first_raw else "",
                    "source_type": "ghg",
                    "column_mappings": {},
                },
                "raw_file_settings": {
                    "sample_hz": 10.0,
                    "delimiter": "",
                    "header_rows": 0,
                    "extra": {"raw_format": "ghg_bundle", "review_required": True},
                },
            },
            "rp_config_draft": {
                "sample_hz": 10.0,
                "block_minutes": 30.0,
                "metadata_bundle": {},
            },
            "unresolved": [
                "EddyPro project/settings are not present in the public sample archive.",
                "Official EddyPro Full_Output is not present in the public sample archive.",
                "Normalized reference/provenance must be generated from an official EddyPro run before parity closure.",
            ],
            "truthfulness_note": (
                "This plan preserves official public raw inputs only. Operators must add settings, official output, "
                "normalization provenance, and run evidence before any raw-to-final claim."
            ),
        },
        "thresholds": {},
        "acquisition_source": {
            "source": "LI-COR public EddyPro Sample Datasets Box archive",
            "source_archive_name": source_archive.get("name", ""),
            "source_archive_sha256": source_archive.get("sha256", archive_inspection.get("sha256", "")),
            "candidate_folder": selected.get("folder", ""),
            "archive_path": archive_inspection.get("archive_path", ""),
            "raw_file_count": len(relative_raw_paths),
            "raw_format_counts": raw_format_counts,
            "materialization": "raw-only fixture bundle draft",
            "embedded_eddypro_evidence_status": embedded.get("status", ""),
        },
        "known_limitations": [
            "Draft extracted from LI-COR's public sample archive.",
            "Embedded EddyPro/SmartFlux project and Full_Output files are preserved when present inside the .ghg bundle.",
            "Not a raw-to-final parity claim and not eligible for official closure until operator-captured executable-run evidence is added.",
        ],
        "truthfulness_note": (
            "This manifest is intentionally incomplete. It exists so the official bundle inspection, repair, "
            "registration, and closure tooling can track exactly what remains missing."
        ),
        "generated_by": "gas_ec_studio_public_official_raw_materializer",
        "generated_at": datetime.now().isoformat(),
    }


def _archive_summary(path: Path, infos: list[zipfile.ZipInfo]) -> dict[str, Any]:
    files = [info for info in infos if not info.is_dir()]
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "entry_count": len(infos),
        "file_count": len(files),
        "total_uncompressed_bytes": sum(info.file_size for info in files),
    }


def _public_official_raw_zip_file_records(infos: list[zipfile.ZipInfo]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for info in infos:
        if info.is_dir():
            continue
        roles = _public_official_raw_file_roles(info.filename)
        records.append(
            {
                "path": info.filename,
                "name": Path(info.filename).name,
                "folder": str(Path(info.filename).parent).replace("\\", "/"),
                "extension": Path(info.filename).suffix.lower().lstrip("."),
                "size_bytes": info.file_size,
                "compressed_size_bytes": info.compress_size,
                "roles": roles,
                "ignored": "ignored_macosx" in roles,
            }
        )
    return records


def _public_official_raw_file_roles(name: str) -> list[str]:
    normalized = name.replace("\\", "/")
    lower = normalized.lower()
    if _is_macosx_artifact(normalized):
        return ["ignored_macosx"]
    suffix = Path(lower).suffix
    stem = Path(lower).name
    roles: list[str] = []
    if suffix in {".ghg", ".tob1", ".slt", ".dat", ".raw", ".bin"}:
        roles.append("raw_input")
    if suffix in {".eddypro", ".metadata", ".proj", ".ini"} or stem in {"eddypro.eddypro", "metadata"}:
        roles.append("eddypro_project_or_settings")
    if "full_output" in stem or "eddypro_full_output" in stem:
        roles.append("official_full_output")
    if suffix in {".metadata", ".json", ".xml"} or "metadata" in stem:
        roles.append("metadata")
    if "biomet" in stem or "bio" in stem:
        roles.append("biomet")
    if not roles:
        roles.append("other")
    return _dedupe(roles)


def _is_macosx_artifact(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return normalized.startswith("__MACOSX/") or "/._" in normalized or Path(normalized).name.startswith("._")


def _public_official_raw_archive_candidate_bundles(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in files:
        if bool(item.get("ignored", False)):
            continue
        folder = str(item.get("folder", ".") or ".")
        if folder == ".":
            folder = str(Path(str(item.get("path", ""))).parent).replace("\\", "/")
        grouped.setdefault(folder, []).append(item)
    candidates: list[dict[str, Any]] = []
    for folder, items in sorted(grouped.items()):
        role_counts = Counter(role for item in items for role in list(item.get("roles", []) or []))
        if int(role_counts.get("raw_input", 0)) <= 0:
            continue
        missing_roles = [
            role
            for role, count in {
                "eddypro_project_or_settings": role_counts.get("eddypro_project_or_settings", 0),
                "official_full_output": role_counts.get("official_full_output", 0),
                "normalized_reference_with_provenance": 0,
                "official_eddypro_executable_run": 0,
            }.items()
            if int(count or 0) <= 0
        ]
        candidates.append(
            {
                "candidate_id": _safe_id_from_path(folder),
                "folder": folder,
                "status": "raw_only_candidate" if missing_roles else "complete_candidate",
                "file_count": len(items),
                "raw_file_count": int(role_counts.get("raw_input", 0)),
                "raw_format_counts": dict(
                    sorted(
                        Counter(str(item.get("extension", "")) for item in items if "raw_input" in item.get("roles", [])).items()
                    )
                ),
                "project_file_count": int(role_counts.get("eddypro_project_or_settings", 0)),
                "full_output_count": int(role_counts.get("official_full_output", 0)),
                "metadata_file_count": int(role_counts.get("metadata", 0)),
                "missing_roles": missing_roles,
                "sample_files": [str(item.get("path", "")) for item in items[:10]],
                "promotion_blockers": [
                    f"missing {role}" for role in missing_roles
                ],
            }
        )
    return candidates


def _archive_missing_required_roles(files: list[dict[str, Any]]) -> list[str]:
    role_counts = Counter(role for item in files for role in list(item.get("roles", []) or []))
    required = {
        "raw_input": role_counts.get("raw_input", 0),
        "eddypro_project_or_settings": role_counts.get("eddypro_project_or_settings", 0),
        "official_full_output": role_counts.get("official_full_output", 0),
        "normalized_reference_with_provenance": 0,
        "official_eddypro_executable_run": 0,
    }
    return [role for role, count in required.items() if int(count or 0) <= 0]


def _public_official_raw_archive_promotion_blockers(
    *,
    missing_required_roles: list[str],
    candidate_bundles: list[dict[str, Any]],
) -> list[str]:
    blockers = [f"archive missing required role: {role}" for role in missing_required_roles if role != "raw_input"]
    if not candidate_bundles:
        blockers.append("archive contains no raw input candidate folders")
    blockers.append("archive has not been transformed into official_raw_fixture_bundle.json")
    blockers.append("archive has not produced normalized reference/provenance artifacts")
    blockers.append("archive has not passed --run-official-raw-closure")
    return _dedupe(blockers)


def _safe_id_from_path(value: str) -> str:
    text = value.strip("/\\").replace("\\", "/").split("/")[-1] or "public_official_raw_candidate"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return safe.strip("_") or "public_official_raw_candidate"


def build_public_spectral_fixture_summary(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate real public EddyPro-derived spectra/cospectra fixture files."""

    root = _workspace_root(workspace_root)
    manifest_path = _resolve(root, path) if path is not None else root / DEFAULT_PUBLIC_SPECTRAL_MANIFEST_PATH
    generated_at = datetime.now().isoformat()
    if not manifest_path.exists():
        return {
            "artifact_type": "public_eddypro_spectral_fixture_summary_v1",
            "generated_at": generated_at,
            "manifest_path": str(manifest_path),
            "status": "fail",
            "fixture_count": 0,
            "valid_fixture_count": 0,
            "files": [],
            "errors": [f"public spectral manifest missing: {manifest_path}"],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "artifact_type": "public_eddypro_spectral_fixture_summary_v1",
            "generated_at": generated_at,
            "manifest_path": str(manifest_path),
            "status": "fail",
            "fixture_count": 0,
            "valid_fixture_count": 0,
            "files": [],
            "errors": [f"public spectral manifest invalid: {exc}"],
        }

    errors: list[str] = []
    files: list[dict[str, Any]] = []
    for file_payload in list(manifest.get("files", []) or []):
        item = _validate_public_spectral_file(file_payload, root)
        files.append(item)
        errors.extend(str(error) for error in item.get("errors", []))

    return {
        "artifact_type": "public_eddypro_spectral_fixture_summary_v1",
        "generated_at": generated_at,
        "manifest_id": manifest.get("manifest_id", ""),
        "manifest_path": str(manifest_path),
        "dataset_id": manifest.get("dataset_id", ""),
        "title": manifest.get("title", ""),
        "source_url": manifest.get("source_url", ""),
        "license": manifest.get("license", ""),
        "source_note": manifest.get("source_note", ""),
        "normalization_time": manifest.get("normalization_time", ""),
        "normalization_command": manifest.get("normalization_command", ""),
        "qc_mapping": dict(manifest.get("qc_mapping", {}) or {}),
        "known_limitations": list(manifest.get("known_limitations", []) or []),
        "status": "pass" if not errors else "fail",
        "fixture_count": len(files),
        "valid_fixture_count": sum(1 for item in files if item.get("status") == "pass"),
        "files": files,
        "errors": errors,
    }


def build_official_raw_fixture_manifest(
    path: str | Path | None = None,
    *,
    workspace_root: str | Path | None = None,
    fixture_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the machine-readable checklist for official EddyPro raw-to-final fixtures.

    The manifest intentionally separates synthetic guardrails from official raw bundles so
    delivery artifacts cannot accidentally over-claim EddyPro parity.
    """

    root = _workspace_root_for_pack(path, workspace_root)
    pack_path = Path(path) if path is not None else root / DEFAULT_FIXTURE_PACK_PATH
    pack = load_fixture_pack(pack_path)
    summary = fixture_summary if fixture_summary is not None else build_fixture_pack_summary(pack_path, workspace_root=root)
    summary_assets = {str(asset.get("fixture_id", "")): dict(asset) for asset in list(summary.get("assets", []) or [])}
    manifest_assets: list[dict[str, Any]] = []
    readiness_counts: Counter[str] = Counter()
    missing_official_bundle_count = 0

    for asset in list(pack.get("assets", []) or []):
        item = _official_raw_fixture_item(asset, summary_assets.get(str(asset.get("fixture_id", "")), {}), root)
        manifest_assets.append(item)
        readiness = str(item.get("readiness_level", "unknown"))
        readiness_counts[readiness] += 1
        if readiness not in {"official_raw_to_final_ready", "disabled"}:
            missing_official_bundle_count += 1

    official_ready_count = int(readiness_counts.get("official_raw_to_final_ready", 0))
    synthetic_guardrail_count = sum(
        int(readiness_counts.get(key, 0))
        for key in ("synthetic_guardrail", "synthetic_reference_guardrail")
    )
    device_protocol_guardrail_count = int(readiness_counts.get("device_protocol_guardrail", 0))
    registered_raw_to_final_count = sum(1 for item in manifest_assets if item.get("tier") == "raw_to_final_parity")
    disabled_fixture_count = sum(1 for item in manifest_assets if item.get("readiness_level") == "disabled")
    source_inventory = dict(summary.get("official_source_inventory", {}) or _fixture_source_inventory_summary(build_eddypro_source_inventory()))
    status = "ready" if official_ready_count > 0 and missing_official_bundle_count == 0 else "needs_official_raw_fixtures"
    if summary.get("status") == "fail":
        status = "blocked_by_fixture_errors"
    evidence_matrix = _official_raw_fixture_evidence_matrix(manifest_assets)
    official_run_norm_counts = dict(evidence_matrix.get("official_run_normalization_status_counts", {}) or {})
    public_spectral_summary = dict(summary.get("public_spectral_fixture_summary", {}) or {})
    public_full_output_summary = dict(summary.get("public_full_output_fixture_summary", {}) or {})
    public_fixture_catalog = dict(summary.get("public_eddypro_fixture_catalog", {}) or {})
    return {
        "artifact_type": "official_raw_fixture_pack_manifest_v2",
        "fixture_pack_id": pack.get("fixture_pack_id", ""),
        "version": pack.get("version", ""),
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "official_raw_to_final_ready_count": official_ready_count,
        "registered_raw_to_final_fixture_count": registered_raw_to_final_count,
        "disabled_fixture_count": disabled_fixture_count,
        "synthetic_guardrail_count": synthetic_guardrail_count,
        "device_protocol_guardrail_count": device_protocol_guardrail_count,
        "missing_official_bundle_count": missing_official_bundle_count,
        "readiness_counts": dict(sorted(readiness_counts.items())),
        "required_official_bundle_files": [
            "high_frequency_raw_input",
            "eddypro_project_or_settings_file",
            "official_eddypro_full_output",
            "normalized_reference_json",
            "normalization_provenance",
        ],
        "official_bundle_schema": official_raw_fixture_bundle_schema(),
        "evidence_matrix": evidence_matrix,
        "official_run_normalization_status_counts": official_run_norm_counts,
        "official_run_normalization_ready_count": sum(
            int(official_run_norm_counts.get(status, 0) or 0)
            for status in ("normalized", "already_present", "ready", "present")
        ),
        "assets": manifest_assets,
        "public_spectral_fixture_summary": public_spectral_summary,
        "public_spectral_fixture_count": int(summary.get("public_spectral_fixture_count", 0) or 0),
        "public_spectral_status": summary.get("public_spectral_status", ""),
        "public_full_output_fixture_summary": public_full_output_summary,
        "public_full_output_fixture_count": int(summary.get("public_full_output_fixture_count", 0) or 0),
        "public_full_output_status": summary.get("public_full_output_status", ""),
        "public_eddypro_fixture_catalog": public_fixture_catalog,
        "public_eddypro_fixture_catalog_status": summary.get("public_eddypro_fixture_catalog_status", ""),
        "coverage_gaps": list(pack.get("coverage_gaps", [])),
        "official_source_inventory": source_inventory,
        "truthfulness_note": (
            "Current registry includes synthetic/manual guardrails and normalized EddyPro outputs. "
            "Full EddyPro raw-to-final parity must remain unclaimed until at least one official raw bundle "
            "contains raw high-frequency input, EddyPro project/settings, official output, normalized reference, "
            "and provenance in the same fixture."
        ),
        "errors": list(summary.get("errors", []) or []),
    }


def build_official_raw_fixture_detail(
    path: str | Path | None = None,
    *,
    fixture_id: str = "",
    workspace_root: str | Path | None = None,
    fixture_summary: dict[str, Any] | None = None,
    fixture_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a single-fixture audit artifact from the validated registry.

    The matrix row is useful for screening; this payload is intentionally more
    verbose so delivery packages can prove exactly which files, hashes,
    provenance, limitations, and parity result supported one fixture decision.
    """

    root = _workspace_root_for_pack(path, workspace_root)
    pack_path = Path(path) if path is not None else root / DEFAULT_FIXTURE_PACK_PATH
    pack = load_fixture_pack(pack_path)
    summary = fixture_summary if fixture_summary is not None else build_fixture_pack_summary(pack_path, workspace_root=root)
    manifest = fixture_manifest if fixture_manifest is not None else build_official_raw_fixture_manifest(
        pack_path,
        workspace_root=root,
        fixture_summary=summary,
    )
    manifest_assets = [dict(asset or {}) for asset in list(manifest.get("assets", []) or [])]
    requested_id = str(fixture_id or "").strip()
    if not requested_id:
        requested_id = next(
            (
                str(asset.get("fixture_id", ""))
                for asset in manifest_assets
                if str(asset.get("tier", "")) == "raw_to_final_parity"
                and str(asset.get("trace_gas_parity_status", "")) not in {"", "not_available"}
            ),
            "",
        )
    if not requested_id:
        requested_id = next(
            (
                str(asset.get("fixture_id", ""))
                for asset in manifest_assets
                if str(asset.get("tier", "")) == "raw_to_final_parity"
            ),
            str(manifest_assets[0].get("fixture_id", "")) if manifest_assets else "",
        )
    manifest_asset = next(
        (asset for asset in manifest_assets if str(asset.get("fixture_id", "")) == requested_id),
        None,
    )
    summary_asset = next(
        (
            dict(asset or {})
            for asset in list(summary.get("assets", []) or [])
            if str(dict(asset or {}).get("fixture_id", "")) == requested_id
        ),
        {},
    )
    pack_asset = next(
        (
            dict(asset or {})
            for asset in list(pack.get("assets", []) or [])
            if str(dict(asset or {}).get("fixture_id", "")) == requested_id
        ),
        {},
    )
    if manifest_asset is None:
        return {
            "artifact_type": "official_raw_fixture_detail_v1",
            "generated_at": datetime.now().isoformat(),
            "fixture_pack_id": pack.get("fixture_pack_id", ""),
            "fixture_pack_path": str(pack_path),
            "fixture_pack_workspace_root": str(root),
            "fixture_id": requested_id,
            "status": "not_found",
            "readiness_level": "not_found",
            "errors": [f"fixture_id not found: {requested_id}"],
            "truthfulness_note": "No fixture detail can be claimed because the fixture id was not found in the active registry.",
        }

    matrix = dict(manifest.get("evidence_matrix", {}) or {})
    matrix_row = next(
        (
            dict(row or {})
            for row in list(matrix.get("rows", []) or [])
            if str(dict(row or {}).get("fixture_id", "")) == requested_id
        ),
        {},
    )
    files = dict(manifest_asset.get("files", {}) or {})
    parity = dict(summary_asset.get("raw_to_final_parity", {}) or {})
    benchmark_summary = dict(parity.get("benchmark_summary", {}) or {})
    trace_gas_parity = dict(parity.get("trace_gas_parity", {}) or {})
    trace_gas_provenance_summary = dict(
        parity.get("trace_gas_provenance_summary", {})
        or trace_gas_parity.get("provenance_summary", {})
        or {}
    )
    trace_gas_ch4_provenance = dict(dict(trace_gas_provenance_summary.get("gases", {}) or {}).get("ch4", {}) or {})
    parity_diagnostics = dict(parity.get("parity_diagnostics", {}) or {})
    provenance = dict(summary_asset.get("provenance", {}) or {})
    known_limitations = _merged_string_list(
        summary_asset.get("known_limitations", []),
        manifest_asset.get("known_limitations", []),
        pack_asset.get("known_limitations", []),
        parity.get("known_limitations", []),
    )
    source_file = (
        provenance.get("source_file")
        or provenance.get("original_file")
        or _first_existing_file_path(files, ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file", "source_csv"))
    )
    normalization = {
        **dict(manifest_asset.get("normalization", {}) or {}),
        "source_file": source_file,
        "reference_file": provenance.get("reference_file") or _first_existing_file_path(files, ("reference_json",)),
        "provenance_file": provenance.get("provenance_file") or _first_existing_file_path(files, ("provenance_json",)),
        "normalization_script": provenance.get("normalization_script", ""),
        "normalization_command": provenance.get("normalization_command", ""),
        "normalization_time": provenance.get("normalization_time", ""),
        "qc_mapping_strategy": provenance.get("qc_mapping_strategy", ""),
        "known_limitations": known_limitations,
        "required_fields_present": provenance.get("required_fields_present"),
        "raw_columns": list(provenance.get("raw_columns", []) or []),
        "unmapped_columns": list(provenance.get("unmapped_columns", []) or []),
        "method_metadata": dict(provenance.get("method_metadata", {}) or {}),
    }
    normalization.setdefault("status", _normalization_status(normalization, files))
    official_run_normalization = dict(manifest_asset.get("official_run_normalization", {}) or {})
    file_checks = _official_fixture_file_checks(files)
    acquisition_validation = _official_fixture_acquisition_validation(
        fixture_id=requested_id,
        readiness_level=str(manifest_asset.get("readiness_level", "")),
        files=files,
        file_checks=file_checks,
        parity=parity,
        normalization=normalization,
    )
    return {
        "artifact_type": "official_raw_fixture_detail_v1",
        "generated_at": datetime.now().isoformat(),
        "fixture_pack_id": pack.get("fixture_pack_id", ""),
        "fixture_pack_version": pack.get("version", ""),
        "fixture_pack_path": str(pack_path),
        "fixture_pack_workspace_root": str(root),
        "fixture_id": requested_id,
        "status": str(summary_asset.get("status", manifest_asset.get("status", "unknown"))),
        "readiness_level": str(manifest_asset.get("readiness_level", "")),
        "evidence_role": str(manifest_asset.get("evidence_role", "")),
        "tier": str(manifest_asset.get("tier", "")),
        "site_class": str(manifest_asset.get("site_class", "")),
        "software": str(manifest_asset.get("software", "")),
        "software_version": str(manifest_asset.get("software_version", "")),
        "disabled": bool(manifest_asset.get("disabled", False)),
        "disabled_reason": str(manifest_asset.get("disabled_reason", "")),
        "matrix_row": matrix_row,
        "files": files,
        "file_checks": file_checks,
        "acquisition_validation": acquisition_validation,
        "rp_config": dict(pack_asset.get("rp_config", {}) or {}),
        "thresholds": dict(pack_asset.get("thresholds", {}) or {}),
        "parity": parity,
        "benchmark_summary": benchmark_summary,
        "pass_rate": float(benchmark_summary.get("pass_rate", manifest_asset.get("pass_rate", 0.0)) or 0.0),
        "failed_fields": list(benchmark_summary.get("failed_fields", manifest_asset.get("failed_fields", [])) or []),
        "trace_gas_parity": trace_gas_parity,
        "parity_diagnostics": parity_diagnostics,
        "trace_gas_parity_status": str(trace_gas_parity.get("status", matrix_row.get("trace_gas_parity_status", ""))),
        "trace_gas_pass_rate": float(trace_gas_parity.get("pass_rate", matrix_row.get("trace_gas_pass_rate", 0.0)) or 0.0),
        "trace_gas_failed_fields": list(trace_gas_parity.get("failed_fields", matrix_row.get("trace_gas_failed_fields", [])) or []),
        "trace_gas_coefficient_profile_id": str(trace_gas_parity.get("coefficient_profile_id", "")),
        "trace_gas_coefficient_profile_source_file": str(
            trace_gas_parity.get("coefficient_profile_source_file", trace_gas_ch4_provenance.get("coefficient_profile_source_file", ""))
        ),
        "trace_gas_coefficient_profile_normalization_command": str(
            trace_gas_parity.get(
                "coefficient_profile_normalization_command",
                trace_gas_ch4_provenance.get("coefficient_profile_normalization_command", ""),
            )
        ),
        "trace_gas_provenance_summary": trace_gas_provenance_summary,
        "trace_gas_known_limitations": list(
            trace_gas_parity.get("coefficient_profile_limitations", trace_gas_ch4_provenance.get("coefficient_profile_limitations", []))
            or []
        ),
        "provenance": provenance,
        "normalization": normalization,
        "official_run_normalization": official_run_normalization,
        "official_run_normalization_status": str(official_run_normalization.get("status", "")),
        "official_run_normalization_time": str(official_run_normalization.get("normalization_time", "")),
        "missing_for_official_claim": list(manifest_asset.get("missing_for_official_claim", []) or []),
        "known_limitations": known_limitations,
        "truthfulness_note": (
            "This detail artifact is derived from the validated fixture registry and raw-to-final harness. "
            "It does not replace the original files; it records their paths, hashes, provenance and current parity status."
        ),
        "errors": list(summary_asset.get("errors", []) or []),
    }


def _official_raw_fixture_evidence_matrix(assets: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_format_counts: Counter[str] = Counter()
    readiness_counts: Counter[str] = Counter()
    site_class_counts: Counter[str] = Counter()
    software_counts: Counter[str] = Counter()
    parity_status_counts: Counter[str] = Counter()
    normalization_status_counts: Counter[str] = Counter()
    official_run_status_counts: Counter[str] = Counter()
    official_run_gate_counts: Counter[str] = Counter()
    official_run_normalization_status_counts: Counter[str] = Counter()
    for asset in assets:
        files = dict(asset.get("files", {}) or {})
        normalization = dict(asset.get("normalization", {}) or {})
        official_run = dict(asset.get("official_eddypro_run", {}) or {})
        official_run_normalization = dict(asset.get("official_run_normalization", {}) or {})
        raw_format = _raw_format_from_file_claims(files)
        readiness = str(asset.get("readiness_level", "unknown"))
        parity_status = str(asset.get("raw_to_final_status", "") or "not_run")
        normalization_status = str(normalization.get("status", "") or "unknown")
        official_run_normalization_status = str(official_run_normalization.get("status", "") or "not_available")
        row = {
            "fixture_id": str(asset.get("fixture_id", "")),
            "tier": str(asset.get("tier", "")),
            "site_class": str(asset.get("site_class", "") or "unknown"),
            "software": str(asset.get("software", "") or "unknown"),
            "software_version": str(asset.get("software_version", "")),
            "official_eddypro_run_status": str(official_run.get("status", "")),
            "official_eddypro_run_gate_status": str(official_run.get("gate_status", "")),
            "raw_format": raw_format,
            "readiness_level": readiness,
            "evidence_role": str(asset.get("evidence_role", "")),
            "validation_status": str(asset.get("status", "")),
            "parity_status": parity_status,
            "pass_rate": float(asset.get("pass_rate", 0.0) or 0.0),
            "failed_fields": list(asset.get("failed_fields", []) or []),
            "parity_failure_groups": list(asset.get("parity_failure_groups", []) or []),
            "parity_top_failed_fields": list(asset.get("parity_top_failed_fields", []) or []),
            "trace_gas_parity_status": str(asset.get("trace_gas_parity_status", "")),
            "trace_gas_pass_rate": float(asset.get("trace_gas_pass_rate", 0.0) or 0.0),
            "trace_gas_failed_fields": list(asset.get("trace_gas_failed_fields", []) or []),
            "trace_gas_coefficient_profile_id": str(asset.get("trace_gas_coefficient_profile_id", "")),
            "trace_gas_coefficient_profile_source_file": str(asset.get("trace_gas_coefficient_profile_source_file", "")),
            "trace_gas_coefficient_profile_normalization_command": str(
                asset.get("trace_gas_coefficient_profile_normalization_command", "")
            ),
            "trace_gas_known_limitation_count": len(list(asset.get("trace_gas_known_limitations", []) or [])),
            "disabled": bool(asset.get("disabled", False)),
            "disabled_reason": str(asset.get("disabled_reason", "")),
            "has_raw_input": bool(asset.get("has_raw_input", False)),
            "has_eddypro_project": bool(asset.get("has_eddypro_project", False)),
            "has_official_output": bool(asset.get("has_official_output", False)),
            "has_normalized_reference": bool(asset.get("has_normalized_reference", False)),
            "has_provenance": bool(asset.get("has_provenance", False)),
            "normalization_status": normalization_status,
            "normalization_time": str(normalization.get("normalization_time", "")),
            "normalization_source_file": str(normalization.get("source_file", "")),
            "qc_mapping_strategy": str(normalization.get("qc_mapping_strategy", "")),
            "normalization_required_fields_present": normalization.get("required_fields_present"),
            "normalization_known_limitation_count": len(list(normalization.get("known_limitations", []) or [])),
            "official_run_normalization_status": official_run_normalization_status,
            "official_run_normalization_time": str(official_run_normalization.get("normalization_time", "")),
            "official_run_normalization_source_file": str(official_run_normalization.get("source_file", "")),
            "official_run_reference_file": str(official_run_normalization.get("reference_file", "")),
            "official_run_provenance_file": str(official_run_normalization.get("provenance_file", "")),
            "official_run_qc_mapping_strategy": str(official_run_normalization.get("qc_mapping_strategy", "")),
            "official_run_normalization_required_fields_present": official_run_normalization.get("required_fields_present"),
            "official_run_normalization_window_count": int(official_run_normalization.get("window_count", 0) or 0),
            "official_run_normalization_known_limitation_count": len(
                list(official_run_normalization.get("known_limitations", []) or [])
            ),
            "missing_for_official_claim": list(asset.get("missing_for_official_claim", []) or []),
        }
        rows.append(row)
        raw_format_counts[raw_format] += 1
        readiness_counts[readiness] += 1
        site_class_counts[row["site_class"]] += 1
        software_counts[row["software"]] += 1
        parity_status_counts[parity_status] += 1
        normalization_status_counts[normalization_status] += 1
        official_run_status_counts[str(official_run.get("status", "not_available") or "not_available")] += 1
        official_run_gate_counts[str(official_run.get("gate_status", "blocked") or "blocked")] += 1
        official_run_normalization_status_counts[official_run_normalization_status] += 1
    return {
        "artifact_type": "official_raw_fixture_evidence_matrix_v1",
        "row_count": len(rows),
        "official_ready_count": int(readiness_counts.get("official_raw_to_final_ready", 0)),
        "raw_format_counts": dict(sorted(raw_format_counts.items())),
        "readiness_counts": dict(sorted(readiness_counts.items())),
        "site_class_counts": dict(sorted(site_class_counts.items())),
        "software_counts": dict(sorted(software_counts.items())),
        "parity_status_counts": dict(sorted(parity_status_counts.items())),
        "normalization_status_counts": dict(sorted(normalization_status_counts.items())),
        "official_eddypro_run_status_counts": dict(sorted(official_run_status_counts.items())),
        "official_eddypro_run_gate_counts": dict(sorted(official_run_gate_counts.items())),
        "official_run_normalization_status_counts": dict(sorted(official_run_normalization_status_counts.items())),
        "rows": rows,
    }


def _official_raw_fixture_item(asset: dict[str, Any], validation: dict[str, Any], root: Path) -> dict[str, Any]:
    readiness = _official_readiness_level(asset, validation)
    files = _fixture_file_claims(asset, validation, root)
    missing_claims = _raw_fixture_missing_claims(asset, files=files, readiness_level=readiness)
    parity = dict(validation.get("raw_to_final_parity", {}) or {})
    benchmark_summary = dict(parity.get("benchmark_summary", {}) or {})
    trace_gas_parity = dict(parity.get("trace_gas_parity", {}) or {})
    trace_gas_provenance_summary = dict(
        parity.get("trace_gas_provenance_summary", {})
        or trace_gas_parity.get("provenance_summary", {})
        or {}
    )
    trace_gas_ch4_provenance = dict(dict(trace_gas_provenance_summary.get("gases", {}) or {}).get("ch4", {}) or {})
    parity_diagnostics = dict(parity.get("parity_diagnostics", {}) or {})
    top_failure_groups = [str(item.get("category", "")) for item in list(parity_diagnostics.get("failure_groups", []) or [])[:4]]
    normalization = _normalization_summary_from_validation(validation, files)
    official_run = dict(asset.get("official_eddypro_run", {}) or validation.get("official_eddypro_run", {}) or {})
    official_run_normalization = _official_run_normalization_summary(asset, validation, files, root)
    return {
        "fixture_id": asset.get("fixture_id", ""),
        "tier": asset.get("tier", ""),
        "site_class": asset.get("site_class", ""),
        "software": asset.get("software", ""),
        "software_version": asset.get("software_version", ""),
        "readiness_level": readiness,
        "evidence_role": _fixture_evidence_role(str(asset.get("tier", "")), readiness),
        "status": validation.get("status", "unknown"),
        "files": files,
        "has_raw_input": any(key in files for key in ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file")),
        "has_eddypro_project": any(key in files for key in ("eddypro_project_file", "project_file", "metadata_json")),
        "has_official_output": any(key in files for key in ("official_full_output", "full_output_csv", "source_csv")),
        "has_normalized_reference": "reference_json" in files,
        "has_provenance": "provenance_json" in files,
        "normalization": normalization,
        "official_eddypro_run": official_run,
        "official_run_normalization": official_run_normalization,
        "normalization_status": normalization.get("status", ""),
        "normalization_time": normalization.get("normalization_time", ""),
        "qc_mapping_strategy": normalization.get("qc_mapping_strategy", ""),
        "official_run_normalization_status": official_run_normalization.get("status", ""),
        "official_run_normalization_time": official_run_normalization.get("normalization_time", ""),
        "missing_for_official_claim": missing_claims,
        "raw_to_final_status": parity.get("status", ""),
        "pass_rate": benchmark_summary.get("pass_rate", 0.0),
        "failed_fields": list(benchmark_summary.get("failed_fields", []) or []),
        "parity_diagnostics": parity_diagnostics,
        "parity_failure_groups": top_failure_groups,
        "parity_top_failed_fields": list(parity_diagnostics.get("top_failed_fields", []) or []),
        "trace_gas_parity_status": trace_gas_parity.get("status", ""),
        "trace_gas_pass_rate": trace_gas_parity.get("pass_rate", 0.0),
        "trace_gas_failed_fields": list(trace_gas_parity.get("failed_fields", []) or []),
        "trace_gas_coefficient_profile_id": trace_gas_parity.get("coefficient_profile_id", ""),
        "trace_gas_coefficient_profile_source_file": trace_gas_parity.get(
            "coefficient_profile_source_file",
            trace_gas_ch4_provenance.get("coefficient_profile_source_file", ""),
        ),
        "trace_gas_coefficient_profile_normalization_command": trace_gas_parity.get(
            "coefficient_profile_normalization_command",
            trace_gas_ch4_provenance.get("coefficient_profile_normalization_command", ""),
        ),
        "trace_gas_provenance_summary": trace_gas_provenance_summary,
        "trace_gas_known_limitations": list(
            trace_gas_parity.get("coefficient_profile_limitations", trace_gas_ch4_provenance.get("coefficient_profile_limitations", []))
            or []
        ),
        "known_limitations": list(validation.get("known_limitations", asset.get("known_limitations", [])) or []),
        "disabled": bool(asset.get("disabled", False)),
        "disabled_reason": str(asset.get("disabled_reason", "")),
    }


def _official_readiness_level(asset: dict[str, Any], validation: dict[str, Any]) -> str:
    if bool(asset.get("disabled", False)) or validation.get("status") == "disabled":
        return "disabled"
    tier = str(asset.get("tier", ""))
    if bool(asset.get("source_derived", False)):
        return "source_derived_conformance"
    software = str(asset.get("software", ""))
    if tier == "raw_to_final_parity":
        has_official_reference = software.lower().startswith("eddypro") or bool(asset.get("official_eddypro_output"))
        parity_status = dict(validation.get("raw_to_final_parity", {}) or {}).get("status")
        if has_official_reference and parity_status == "pass":
            return "official_raw_to_final_ready"
        return "synthetic_guardrail"
    if tier == "real_reference_output":
        return "normalized_official_output_only"
    if tier == "manual_protocol_validation":
        return "device_protocol_guardrail"
    if tier == "synthetic_regression_reference":
        return "synthetic_reference_guardrail"
    return "unclassified"


def _fixture_evidence_role(tier: str, readiness_level: str) -> str:
    if readiness_level == "official_raw_to_final_ready":
        return "official_raw_to_final_parity"
    if readiness_level == "source_derived_conformance":
        return "source_derived_raw_import_conformance"
    if tier == "real_reference_output":
        return "official_output_window_reference"
    if tier == "raw_to_final_parity":
        return "raw_pipeline_guardrail"
    if tier == "manual_protocol_validation":
        return "device_parser_guardrail"
    return "regression_guardrail"


def _fixture_file_claims(asset: dict[str, Any], validation: dict[str, Any], root: Path) -> dict[str, dict[str, Any]]:
    labels = [
        "raw_file",
        "raw_ghg_file",
        "tob1_file",
        "slt_file",
        "native_binary_file",
        "metadata_json",
        "eddypro_project_file",
        "project_file",
        "settings_file",
        "official_full_output",
        "full_output_csv",
        "source_csv",
        "reference_json",
        "provenance_json",
        "protocol_log",
    ]
    validation_files = dict(validation.get("files", {}) or {})
    validation_hashes = dict(validation.get("hashes", {}) or {})
    expected_hashes = dict(asset.get("expected_sha256", {}) or {})
    claims: dict[str, dict[str, Any]] = {}
    for label in labels:
        raw_value = asset.get(label) or validation_files.get(label)
        if not raw_value:
            continue
        path = _resolve(root, raw_value)
        claims[label] = {
            "path": str(path),
            "exists": path.exists() and path.is_file(),
            "sha256": validation_hashes.get(label) or (_sha256(path) if path.exists() and path.is_file() else ""),
            "expected_sha256": expected_hashes.get(label, ""),
        }
    return claims


def _normalization_summary_from_validation(validation: dict[str, Any], files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    provenance = dict(validation.get("provenance", {}) or {})
    known_limitations = list(provenance.get("known_limitations", validation.get("known_limitations", [])) or [])
    summary = {
        "status": "",
        "artifact_type": str(provenance.get("artifact_type", "")),
        "source_file": str(
            provenance.get("source_file")
            or provenance.get("original_file")
            or _first_existing_file_path(files, ("official_full_output", "full_output_csv", "source_csv", "raw_file"))
        ),
        "original_file": str(provenance.get("original_file", "")),
        "original_file_name": str(provenance.get("original_file_name", "")),
        "metadata_file": str(provenance.get("metadata_file", _first_existing_file_path(files, ("metadata_json",)))),
        "reference_file": str(provenance.get("reference_file", _first_existing_file_path(files, ("reference_json",)))),
        "provenance_file": str(provenance.get("provenance_file", _first_existing_file_path(files, ("provenance_json",)))),
        "normalization_script": str(provenance.get("normalization_script", "")),
        "normalization_command": str(provenance.get("normalization_command", "")),
        "normalization_time": str(provenance.get("normalization_time", "")),
        "qc_mapping_strategy": str(provenance.get("qc_mapping_strategy", "")),
        "known_limitations": known_limitations,
        "required_fields_present": provenance.get("required_fields_present"),
        "raw_columns": list(provenance.get("raw_columns", []) or []),
        "unmapped_columns": list(provenance.get("unmapped_columns", []) or []),
        "method_metadata": dict(provenance.get("method_metadata", {}) or {}),
    }
    summary["status"] = _normalization_status(summary, files)
    return summary


def _normalization_status(normalization: dict[str, Any], files: dict[str, dict[str, Any]]) -> str:
    if normalization.get("required_fields_present") is False:
        return "needs_review"
    if normalization.get("normalization_time") and files.get("reference_json", {}).get("exists") and files.get("provenance_json", {}).get("exists"):
        return "ready"
    if files.get("reference_json", {}).get("exists") and files.get("provenance_json", {}).get("exists"):
        return "present"
    if files.get("reference_json", {}).get("exists"):
        return "missing_provenance"
    return "missing_reference"


def _official_run_normalization_summary(
    asset: dict[str, Any],
    validation: dict[str, Any],
    files: dict[str, dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    raw_summary = _first_official_run_normalization_payload(asset, validation)
    bundle_root = _official_raw_bundle_root_from_asset(asset, files, root)
    if not raw_summary and bundle_root is not None:
        raw_summary = _official_run_normalization_from_bundle_manifest(bundle_root)
    if not raw_summary:
        return {
            "artifact_type": "official_eddypro_run_output_normalization_v1",
            "status": "not_available",
            "source_file": "",
            "reference_json": "",
            "provenance_json": "",
            "reference_file": "",
            "provenance_file": "",
            "normalization_time": "",
            "qc_mapping_strategy": "",
            "known_limitations": [],
            "required_fields_present": None,
            "window_count": 0,
        }

    reference_json = str(raw_summary.get("reference_json", "") or "").strip()
    provenance_json = str(raw_summary.get("provenance_json", "") or "").strip()
    reference_path = _resolve_official_bundle_artifact_path(reference_json, root, bundle_root)
    provenance_path = _resolve_official_bundle_artifact_path(provenance_json, root, bundle_root)
    provenance_payload = _read_json_payload(provenance_path)
    reference_payload = _read_json_payload(reference_path)
    windows = reference_payload.get("windows", []) if isinstance(reference_payload, dict) else []
    generated_files = [
        str(item)
        for item in list(raw_summary.get("generated_files", []) or [])
        if str(item).strip()
    ]
    source_file = str(
        raw_summary.get("source_file")
        or provenance_payload.get("original_file")
        or provenance_payload.get("source_file")
        or ""
    )
    status = str(raw_summary.get("status", "") or "").strip()
    if not status:
        status = "present" if reference_path.exists() and provenance_path.exists() else "not_available"
    return {
        "artifact_type": str(raw_summary.get("artifact_type", "official_eddypro_run_output_normalization_v1")),
        "status": status,
        "source_file": source_file,
        "source_file_name": str(provenance_payload.get("original_file_name", "")),
        "reference_json": reference_json,
        "provenance_json": provenance_json,
        "reference_file": str(reference_path) if reference_json else "",
        "provenance_file": str(provenance_path) if provenance_json else "",
        "reference_exists": reference_path.exists() if reference_json else False,
        "provenance_exists": provenance_path.exists() if provenance_json else False,
        "generated_files": generated_files,
        "normalization_time": str(provenance_payload.get("normalization_time", raw_summary.get("normalization_time", ""))),
        "normalization_script": str(provenance_payload.get("normalization_script", raw_summary.get("normalization_script", ""))),
        "normalization_command": str(provenance_payload.get("normalization_command", raw_summary.get("normalization_command", ""))),
        "qc_mapping_strategy": str(provenance_payload.get("qc_mapping_strategy", raw_summary.get("qc_mapping_strategy", ""))),
        "field_mapping": dict(raw_summary.get("field_mapping", provenance_payload.get("field_mapping", {})) or {}),
        "known_limitations": list(provenance_payload.get("known_limitations", raw_summary.get("known_limitations", [])) or []),
        "required_fields_present": provenance_payload.get("required_fields_present", raw_summary.get("required_fields_present")),
        "raw_columns": list(provenance_payload.get("raw_columns", []) or []),
        "unmapped_columns": list(raw_summary.get("unmapped_columns", provenance_payload.get("unmapped_columns", [])) or []),
        "window_count": int(raw_summary.get("window_count", len(windows) if isinstance(windows, list) else 0) or 0),
        "truthfulness_note": str(
            raw_summary.get(
                "truthfulness_note",
                "This summary describes a separately normalized official EddyPro executable-run output; it does not replace the primary reference.",
            )
        ),
    }


def _first_official_run_normalization_payload(asset: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        asset.get("official_run_normalization_result"),
        asset.get("official_run_normalization"),
        validation.get("official_run_normalization_result"),
        validation.get("official_run_normalization"),
        dict(asset.get("import_plan", {}) or {}).get("official_run_normalization_result"),
        dict(validation.get("import_plan", {}) or {}).get("official_run_normalization_result"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _official_run_normalization_from_bundle_manifest(bundle_root: Path) -> dict[str, Any]:
    for name in OFFICIAL_RAW_BUNDLE_MANIFEST_NAMES:
        path = bundle_root / name
        payload = _read_json_payload(path)
        if not payload:
            continue
        normalization = dict(payload.get("official_run_normalization_result", {}) or {})
        if normalization:
            return normalization
    return {}


def _official_raw_bundle_root_from_asset(
    asset: dict[str, Any],
    files: dict[str, dict[str, Any]],
    root: Path,
) -> Path | None:
    values: list[str] = []
    for key in (
        "bundle_root",
        "bundle_dir",
        "manifest_path",
        "raw_file",
        "raw_ghg_file",
        "tob1_file",
        "slt_file",
        "native_binary_file",
        "reference_json",
        "provenance_json",
        "official_full_output",
        "full_output_csv",
        "eddypro_project_file",
        "project_file",
    ):
        value = str(asset.get(key, "") or "").strip()
        if value:
            values.append(value)
    for claim in files.values():
        value = str(dict(claim or {}).get("path", "") or "").strip()
        if value:
            values.append(value)
    for value in values:
        path = _resolve(root, value)
        candidates = [path if path.is_dir() else path.parent, *list((path if path.is_dir() else path.parent).parents)]
        for candidate in candidates[:8]:
            if any((candidate / name).exists() for name in OFFICIAL_RAW_BUNDLE_MANIFEST_NAMES):
                return candidate
    return None


def _resolve_official_bundle_artifact_path(value: str, root: Path, bundle_root: Path | None) -> Path:
    if not value:
        return Path("")
    path = Path(value)
    if path.is_absolute():
        return path
    if bundle_root is not None and (bundle_root / path).exists():
        return bundle_root / path
    return root / path


def _read_json_payload(path: Path) -> dict[str, Any]:
    if not str(path) or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _raw_format_from_file_claims(files: dict[str, dict[str, Any]]) -> str:
    for label in ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file"):
        if not files.get(label, {}).get("exists", False):
            continue
        path = Path(str(files.get(label, {}).get("path", "")))
        suffix = path.suffix.lower().lstrip(".")
        if suffix:
            return suffix
        if label != "raw_file":
            return label.replace("_file", "")
        return "raw"
    return "missing"


def _raw_fixture_missing_claims(
    asset: dict[str, Any],
    *,
    files: dict[str, dict[str, Any]],
    readiness_level: str,
) -> list[str]:
    missing: list[str] = []
    has_raw = any(key in files and files[key].get("exists") for key in ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file"))
    has_project = any(key in files and files[key].get("exists") for key in ("eddypro_project_file", "project_file"))
    has_output = any(key in files and files[key].get("exists") for key in ("official_full_output", "full_output_csv", "source_csv"))
    has_reference = bool(files.get("reference_json", {}).get("exists"))
    has_provenance = bool(files.get("provenance_json", {}).get("exists"))
    if not has_raw:
        missing.append("high_frequency_raw_input")
    if not has_project:
        missing.append("eddypro_project_or_settings_file")
    if not has_output:
        missing.append("official_eddypro_full_output")
    if not has_reference:
        missing.append("normalized_reference_json")
    if not has_provenance:
        missing.append("normalization_provenance")
    if readiness_level == "synthetic_guardrail" and not str(asset.get("software", "")).lower().startswith("eddypro"):
        missing.append("official_eddypro_executable_output")
    return list(dict.fromkeys(missing))


def _merged_string_list(*values: Any) -> list[str]:
    merged: list[str] = []
    for value in values:
        for item in list(value or []):
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _first_existing_file_path(files: dict[str, dict[str, Any]], roles: tuple[str, ...]) -> str:
    for role in roles:
        payload = dict(files.get(role, {}) or {})
        path = str(payload.get("path", "")).strip()
        if path:
            return path
    return ""


def _official_fixture_file_checks(files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required_groups = {
        "high_frequency_raw_input": ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file"),
        "eddypro_project_or_settings_file": ("eddypro_project_file", "project_file", "settings_file"),
        "official_eddypro_full_output": ("official_full_output", "full_output_csv", "source_csv"),
        "normalized_reference_json": ("reference_json",),
        "normalization_provenance": ("provenance_json",),
    }
    group_status = {
        group: any(bool(dict(files.get(role, {}) or {}).get("exists", False)) for role in roles)
        for group, roles in required_groups.items()
    }
    hash_mismatches = [
        role
        for role, payload in sorted(files.items())
        if str(dict(payload or {}).get("expected_sha256", "")).strip()
        and str(dict(payload or {}).get("sha256", "")).strip().upper() != str(dict(payload or {}).get("expected_sha256", "")).strip().upper()
    ]
    missing_roles = [
        role
        for role, payload in sorted(files.items())
        if not bool(dict(payload or {}).get("exists", False))
    ]
    return {
        "required_groups": group_status,
        "missing_required_groups": [group for group, ok in group_status.items() if not ok],
        "present_file_count": sum(1 for payload in files.values() if bool(dict(payload or {}).get("exists", False))),
        "declared_file_count": len(files),
        "missing_roles": missing_roles,
        "hash_mismatches": hash_mismatches,
        "status": "ok" if not hash_mismatches and all(group_status.values()) else "needs_attention",
    }


def _official_fixture_acquisition_validation(
    *,
    fixture_id: str,
    readiness_level: str,
    files: dict[str, dict[str, Any]],
    file_checks: dict[str, Any],
    parity: dict[str, Any],
    normalization: dict[str, Any],
) -> dict[str, Any]:
    required_groups = dict(file_checks.get("required_groups", {}) or {})
    requirements = [
        {
            "requirement_id": group,
            "label": group.replace("_", " "),
            "status": "pass" if bool(ok) else "fail",
            "required_for_closure": True,
            "evidence_paths": [
                str(dict(payload or {}).get("path", ""))
                for payload in files.values()
                if bool(dict(payload or {}).get("exists", False))
            ][:8],
            "missing": [] if bool(ok) else [group],
        }
        for group, ok in sorted(required_groups.items())
    ]
    parity_status = str(parity.get("status", "") or "")
    benchmark_summary = dict(parity.get("benchmark_summary", {}) or {})
    requirements.append(
        {
            "requirement_id": "raw_to_final_parity_pass",
            "label": "raw to final parity pass",
            "status": "pass" if parity_status == "pass" else ("fail" if parity_status == "fail" else "pending"),
            "required_for_closure": True,
            "evidence_paths": [],
            "missing": [] if parity_status == "pass" else ["raw_to_final_parity status=pass"],
            "detail": {
                "parity_status": parity_status or "not_run",
                "pass_rate": float(benchmark_summary.get("pass_rate", 0.0) or 0.0),
                "failed_fields": list(benchmark_summary.get("failed_fields", []) or []),
            },
        }
    )
    missing = [
        str(item.get("requirement_id", ""))
        for item in requirements
        if str(item.get("status", "")) != "pass"
    ]
    status = "closure_ready" if readiness_level == "official_raw_to_final_ready" and not missing else "blocked"
    return {
        "artifact_type": "official_raw_fixture_acquisition_validation_v1",
        "closure_id": "fixture_pack:official_raw_to_final_ready_count",
        "priority": "P0",
        "status": status,
        "gate_status": "pass" if status == "closure_ready" else "blocked",
        "fixture_id": fixture_id,
        "readiness_level": readiness_level,
        "missing_requirements": missing,
        "requirements": requirements,
        "provenance_summary": {
            "normalization_command": str(normalization.get("normalization_command", "")),
            "normalization_time": str(normalization.get("normalization_time", "")),
            "qc_mapping_strategy": str(normalization.get("qc_mapping_strategy", "")),
            "known_limitations": list(normalization.get("known_limitations", []) or []),
        },
        "blocked_claims": [] if status == "closure_ready" else ["official_raw_to_final_numeric_parity", "full_eddypro_parity"],
        "acceptance_commands": [
            "python -m pytest tests/test_official_raw_fixture_bundle.py tests/test_eddypro_fixture_pack.py tests/test_raw_to_final_parity.py -q",
            "python -m pytest tests/test_eddypro_coverage_audit.py tests/test_result_exports.py -q",
        ],
    }


def _fixture_source_inventory_summary(source_inventory: dict[str, Any]) -> dict[str, Any]:
    repositories = dict(source_inventory.get("source_repositories", {}) or {})
    return {
        "inventory_id": source_inventory.get("inventory_id", ""),
        "status": source_inventory.get("status", ""),
        "feature_count": source_inventory.get("feature_count", 0),
        "present_feature_count": source_inventory.get("present_feature_count", 0),
        "missing_feature_count": source_inventory.get("missing_feature_count", 0),
        "missing_features": list(source_inventory.get("missing_features", []) or []),
        "engine_commit": dict(repositories.get("engine", {}) or {}).get("commit", ""),
        "gui_commit": dict(repositories.get("gui", {}) or {}).get("commit", ""),
        "truthfulness_note": source_inventory.get("truthfulness_note", ""),
    }


def validate_fixture_asset(asset: dict[str, Any], *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(workspace_root) if workspace_root is not None else _workspace_root(None)
    tier = str(asset.get("tier", ""))
    result: dict[str, Any] = {
        "fixture_id": asset.get("fixture_id", ""),
        "tier": tier,
        "site_class": asset.get("site_class", ""),
        "software": asset.get("software", ""),
        "software_version": asset.get("software_version", ""),
        "status": "pass",
        "files": {},
        "hashes": {},
        "errors": [],
        "known_limitations": list(asset.get("known_limitations", [])),
    }
    if bool(asset.get("disabled", False)):
        result["status"] = "disabled"
        result["disabled"] = True
        result["disabled_reason"] = str(asset.get("disabled_reason", "operator_disabled"))
        return result
    if tier in {"real_reference_output", "synthetic_regression_reference"}:
        _validate_reference_asset(asset, result, root)
    elif tier == "manual_protocol_validation":
        _validate_protocol_asset(asset, result, root)
    elif tier == "raw_to_final_parity":
        _validate_raw_to_final_asset(asset, result, root)
    else:
        result["errors"].append(f"unsupported fixture tier: {tier}")
    if result["errors"]:
        result["status"] = "fail"
    return result


def _validate_reference_asset(asset: dict[str, Any], result: dict[str, Any], root: Path) -> None:
    reference_path = _resolve(root, asset.get("reference_json"))
    source_path = _resolve(root, asset.get("source_csv")) if asset.get("source_csv") else None
    provenance_path = _resolve(root, asset.get("provenance_json")) if asset.get("provenance_json") else None
    _record_file(result, "reference_json", reference_path, expected_hash=asset.get("expected_sha256", {}).get("reference_json"))
    if source_path is not None:
        _record_file(result, "source_csv", source_path, expected_hash=asset.get("expected_sha256", {}).get("source_csv"))
    if provenance_path is not None:
        _record_file(result, "provenance_json", provenance_path, expected_hash=asset.get("expected_sha256", {}).get("provenance_json"))
    if not reference_path.exists():
        result["errors"].append(f"reference_json missing: {reference_path}")
        return
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"reference_json invalid: {exc}")
        return
    windows = reference.get("windows", [])
    result["reference_id"] = reference.get("reference_id", "")
    result["window_count"] = len(windows) if isinstance(windows, list) else 0
    expected_window_count = int(asset.get("expected_window_count", 0) or 0)
    if expected_window_count and result["window_count"] != expected_window_count:
        result["errors"].append(f"window_count expected {expected_window_count}, got {result['window_count']}")
    required_fields = [str(item) for item in asset.get("required_fields", [])]
    missing_fields = _missing_required_window_fields(windows if isinstance(windows, list) else [], required_fields)
    result["required_fields"] = required_fields
    result["missing_fields"] = missing_fields
    if missing_fields:
        result["errors"].append(f"missing required fields: {', '.join(missing_fields)}")
    provenance = {}
    if provenance_path is not None and provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["errors"].append(f"provenance_json invalid: {exc}")
    result["provenance"] = {
        "artifact_type": provenance.get("artifact_type", ""),
        "source_file": provenance.get("source_file", provenance.get("original_file", asset.get("source_csv", ""))),
        "original_file": provenance.get("original_file", asset.get("source_csv", "")),
        "original_file_name": provenance.get("original_file_name", ""),
        "reference_file": provenance.get("reference_file", asset.get("reference_json", "")),
        "provenance_file": str(provenance_path) if provenance_path is not None else "",
        "normalization_time": provenance.get("normalization_time", reference.get("normalization_time", "")),
        "normalization_script": provenance.get("normalization_script", "references/eddypro/normalize_reference.py"),
        "normalization_command": provenance.get("normalization_command", ""),
        "qc_mapping_strategy": provenance.get("qc_mapping_strategy", reference.get("qc_mapping_strategy", "")),
        "known_limitations": provenance.get("known_limitations", asset.get("known_limitations", [])),
        "required_fields_present": provenance.get("required_fields_present"),
        "raw_columns": list(provenance.get("raw_columns", []) or []),
        "unmapped_columns": list(provenance.get("unmapped_columns", []) or []),
        "method_metadata": dict(provenance.get("method_metadata", {}) or {}),
    }


def _validate_protocol_asset(asset: dict[str, Any], result: dict[str, Any], root: Path) -> None:
    protocol_path = _resolve(root, asset.get("protocol_log"))
    metadata_path = _resolve(root, asset.get("metadata_json"))
    _record_file(result, "protocol_log", protocol_path, expected_hash=asset.get("expected_sha256", {}).get("protocol_log"))
    _record_file(result, "metadata_json", metadata_path, expected_hash=asset.get("expected_sha256", {}).get("metadata_json"))
    if not protocol_path.exists() or not metadata_path.exists():
        return
    try:
        metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"metadata_json invalid: {exc}")
        return
    metadata = MetadataBundle.from_dict(_metadata_bundle_payload(metadata_payload))
    rows = load_raw_text_frames(protocol_path, metadata=metadata, device_uid=str(asset.get("fixture_id", "ygas")))
    result["row_count"] = len(rows)
    result["modes"] = sorted({row.mode for row in rows})
    result["device_ids"] = sorted({row.device_id for row in rows})
    expected_count = int(asset.get("expected_row_count", 0) or 0)
    if expected_count and len(rows) != expected_count:
        result["errors"].append(f"row_count expected {expected_count}, got {len(rows)}")
    expected_modes = sorted(int(item) for item in asset.get("expected_modes", []))
    if expected_modes and result["modes"] != expected_modes:
        result["errors"].append(f"modes expected {expected_modes}, got {result['modes']}")
    expected = metadata_payload.get("expected", {}) if isinstance(metadata_payload.get("expected", {}), dict) else {}
    if rows and expected.get("first_co2_ppm") is not None and abs(float(rows[0].co2_ppm or 0.0) - float(expected["first_co2_ppm"])) > 1e-9:
        result["errors"].append("first_co2_ppm does not match metadata expectation")
    result["provenance"] = {
        "source": metadata_payload.get("source", ""),
        "fixture_tier": metadata_payload.get("fixture_tier", ""),
        "known_limitations": metadata_payload.get("known_limitations", asset.get("known_limitations", [])),
    }


def _validate_raw_to_final_asset(asset: dict[str, Any], result: dict[str, Any], root: Path) -> None:
    raw_role = _first_available_asset_key(asset, ["raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file"])
    raw_path = _resolve(root, asset.get(raw_role))
    metadata_value = str(asset.get("metadata_json", "") or "").strip()
    metadata_path = _resolve(root, metadata_value) if metadata_value else None
    reference_path = _resolve(root, asset.get("reference_json"))
    provenance_path = _resolve(root, asset.get("provenance_json")) if asset.get("provenance_json") else None
    expected_hashes = dict(asset.get("expected_sha256", {}) or {})
    _record_file(result, raw_role or "raw_file", raw_path, expected_hash=expected_hashes.get(raw_role or "raw_file"))
    if metadata_path is not None:
        _record_file(result, "metadata_json", metadata_path, expected_hash=expected_hashes.get("metadata_json"))
    else:
        result.setdefault("files", {})["metadata_json"] = ""
    _record_file(result, "reference_json", reference_path, expected_hash=expected_hashes.get("reference_json"))
    if provenance_path is not None:
        _record_file(result, "provenance_json", provenance_path, expected_hash=expected_hashes.get("provenance_json"))
    for extra_role in ("eddypro_project_file", "project_file", "settings_file", "official_full_output", "full_output_csv"):
        if asset.get(extra_role):
            _record_file(result, extra_role, _resolve(root, asset.get(extra_role)), expected_hash=expected_hashes.get(extra_role))
    if not raw_path.exists() or not reference_path.exists() or (metadata_path is not None and not metadata_path.exists()):
        return
    metadata_payload: dict[str, Any] = {}
    if metadata_path is not None:
        try:
            metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["errors"].append(f"metadata_json invalid: {exc}")
            return
    try:
        reference_payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"reference_json invalid: {exc}")
        return
    provenance_payload: dict[str, Any] = {}
    if provenance_path is not None and provenance_path.exists():
        try:
            provenance_payload = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["errors"].append(f"provenance_json invalid: {exc}")
    cache_key = _raw_to_final_harness_cache_key(asset, result)
    harness = _read_raw_to_final_harness_cache(cache_key)
    if harness is None:
        harness = run_raw_to_final_parity_harness(
            raw_path=raw_path,
            metadata=metadata_payload,
            rp_config=dict(asset.get("rp_config", {}) or {}),
            reference_json_path=reference_path,
            fixture_id=str(asset.get("fixture_id", "")),
            thresholds=dict(asset.get("thresholds", {}) or {}),
            data_source=str(asset.get("fixture_id", "raw_to_final_fixture")),
            time_range=str(asset.get("time_range", "")),
        )
        _write_raw_to_final_harness_cache(cache_key, harness)
    else:
        result["raw_to_final_cache"] = {
            "status": "hit",
            "cache_key": cache_key,
        }
    result["reference_id"] = reference_payload.get("reference_id", "")
    result["raw_row_count"] = harness.get("raw_input", {}).get("row_count", 0)
    result["window_count"] = harness.get("pipeline", {}).get("window_count", 0)
    result["reference_window_count"] = harness.get("reference", {}).get("reference_window_count", 0)
    trace_gas_parity = dict(harness.get("trace_gas_parity", {}) or {})
    trace_gas_provenance_summary = dict(
        harness.get("trace_gas_provenance_summary", {})
        or trace_gas_parity.get("provenance_summary", {})
        or {}
    )
    trace_gas_ch4_provenance = dict(dict(trace_gas_provenance_summary.get("gases", {}) or {}).get("ch4", {}) or {})
    result["raw_to_final_parity"] = {
        "artifact_type": harness.get("artifact_type", ""),
        "status": harness.get("status", ""),
        "fixture_id": harness.get("fixture_id", ""),
        "raw_input": harness.get("raw_input", {}),
        "benchmark_summary": harness.get("benchmark_summary", {}),
        "trace_gas_parity": trace_gas_parity,
        "trace_gas_provenance_summary": trace_gas_provenance_summary,
        "li7700_level_parity": harness.get("li7700_level_parity", {}),
        "parity_diagnostics": harness.get("parity_diagnostics", {}),
        "truthfulness_note": harness.get("truthfulness_note", ""),
        "known_limitations": harness.get("known_limitations", []),
    }
    result["trace_gas_parity_status"] = str(trace_gas_parity.get("status", ""))
    result["trace_gas_pass_rate"] = float(trace_gas_parity.get("pass_rate", 0.0) or 0.0)
    result["trace_gas_failed_fields"] = list(trace_gas_parity.get("failed_fields", []) or [])
    result["trace_gas_coefficient_profile_id"] = str(trace_gas_parity.get("coefficient_profile_id", ""))
    result["trace_gas_coefficient_profile_source_file"] = str(
        trace_gas_parity.get("coefficient_profile_source_file", trace_gas_ch4_provenance.get("coefficient_profile_source_file", ""))
    )
    result["trace_gas_coefficient_profile_normalization_command"] = str(
        trace_gas_parity.get(
            "coefficient_profile_normalization_command",
            trace_gas_ch4_provenance.get("coefficient_profile_normalization_command", ""),
        )
    )
    result["trace_gas_provenance_summary"] = trace_gas_provenance_summary
    result["trace_gas_known_limitations"] = list(
        trace_gas_parity.get("coefficient_profile_limitations", trace_gas_ch4_provenance.get("coefficient_profile_limitations", []))
        or []
    )
    result["provenance"] = {
        "artifact_type": provenance_payload.get("artifact_type", ""),
        "source_file": (
            provenance_payload.get("source_file")
            or provenance_payload.get("original_file")
            or asset.get("official_full_output", "")
            or asset.get("full_output_csv", "")
            or asset.get("source_csv", "")
            or asset.get("raw_file", "")
        ),
        "original_file": provenance_payload.get("original_file", ""),
        "original_file_name": provenance_payload.get("original_file_name", ""),
        "metadata_file": provenance_payload.get("metadata_file", asset.get("metadata_json", "")),
        "reference_file": provenance_payload.get("reference_file", asset.get("reference_json", "")),
        "provenance_file": str(provenance_path) if provenance_path is not None else "",
        "normalization_script": provenance_payload.get("normalization_script", ""),
        "normalization_command": provenance_payload.get("normalization_command", ""),
        "normalization_time": provenance_payload.get("normalization_time", ""),
        "qc_mapping_strategy": provenance_payload.get("qc_mapping_strategy", reference_payload.get("qc_mapping_strategy", "")),
        "known_limitations": provenance_payload.get("known_limitations", asset.get("known_limitations", [])),
        "required_fields_present": provenance_payload.get("required_fields_present"),
        "raw_columns": list(provenance_payload.get("raw_columns", []) or []),
        "unmapped_columns": list(provenance_payload.get("unmapped_columns", []) or []),
        "method_metadata": dict(provenance_payload.get("method_metadata", {}) or {}),
    }
    if harness.get("status") != "pass":
        failed_fields = harness.get("benchmark_summary", {}).get("failed_fields", [])
        result["errors"].append(f"raw-to-final parity failed: failed_fields={failed_fields}")


def _raw_to_final_harness_cache_key(asset: dict[str, Any], result: dict[str, Any]) -> str:
    payload = {
        "cache_schema": "raw_to_final_harness_cache_v1",
        "fixture_id": str(asset.get("fixture_id", "")),
        "tier": str(asset.get("tier", "")),
        "raw_role": _first_available_asset_key(
            asset,
            ["raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file"],
        ),
        "files": dict(sorted((result.get("hashes", {}) or {}).items())),
        "rp_config": dict(asset.get("rp_config", {}) or {}),
        "thresholds": dict(asset.get("thresholds", {}) or {}),
        "time_range": str(asset.get("time_range", "")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _raw_to_final_harness_cache_dir() -> Path | None:
    if str(os.environ.get("GAS_EC_DISABLE_RAW_TO_FINAL_CACHE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return None
    configured = str(os.environ.get("GAS_EC_RAW_TO_FINAL_CACHE_DIR", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "gas_ec_studio" / "raw_to_final_harness_cache"


def _raw_to_final_harness_cache_path(cache_key: str) -> Path | None:
    cache_dir = _raw_to_final_harness_cache_dir()
    if cache_dir is None:
        return None
    return cache_dir / f"{cache_key}.json"


def _read_raw_to_final_harness_cache(cache_key: str) -> dict[str, Any] | None:
    path = _raw_to_final_harness_cache_path(cache_key)
    if path is None or not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(wrapper.get("cache_key", "")) != cache_key:
        return None
    payload = wrapper.get("payload", {})
    if not isinstance(payload, dict) or payload.get("artifact_type") != "eddypro_raw_to_final_parity_v1":
        return None
    return payload


def _write_raw_to_final_harness_cache(cache_key: str, payload: dict[str, Any]) -> None:
    path = _raw_to_final_harness_cache_path(cache_key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "artifact_type": "raw_to_final_harness_cache_entry_v1",
                    "cache_key": cache_key,
                    "created_at": datetime.now().isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def _load_public_fixture_manifest_for_acquisition(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "fail", "error": f"public fixture manifest missing: {path}"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "fail", "error": f"public fixture manifest invalid: {exc}"}
    payload["_manifest_path"] = str(path)
    payload["status"] = "pass"
    return payload


def _load_public_fixture_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "manifest_id": "",
            "files": [],
            "candidate_bundles": [],
            "original_files": [],
            "known_limitations": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "manifest_id": "",
            "files": [],
            "candidate_bundles": [],
            "original_files": [],
            "known_limitations": [],
        }
    return payload if isinstance(payload, dict) else {}


def _acquire_public_fixture_entry(
    *,
    family: str,
    manifest_path: Path,
    entry: dict[str, Any],
    root: Path,
    overwrite: bool,
    timeout_s: float,
) -> dict[str, Any]:
    file_id = str(entry.get("file_id", "") or entry.get("source_filename", "public_fixture"))
    target_value = entry.get("path")
    result: dict[str, Any] = {
        "family": family,
        "file_id": file_id,
        "role": entry.get("role", ""),
        "manifest_path": str(manifest_path),
        "source_url": entry.get("source_url", ""),
        "status": "pass",
        "action": "",
        "errors": [],
    }
    if not target_value:
        result["status"] = "skipped"
        result["action"] = "skipped_no_local_path"
        result["reason"] = "remote original is retained as provenance only; no local path was declared"
        return result

    target_path = _resolve(root, target_value)
    result["path"] = str(target_path)
    if target_path.exists() and not overwrite:
        result["action"] = "skipped_existing"
        result["size_bytes"] = target_path.stat().st_size
        return result

    source_url = str(entry.get("source_url", "")).strip()
    if not source_url:
        result["status"] = "fail"
        result["action"] = "missing_source_url"
        result["errors"].append(f"{file_id} has no source_url")
        return result

    try:
        written = _download_public_fixture_entry(entry, target_path, timeout_s=timeout_s)
    except Exception as exc:  # pragma: no cover - exercised by integration paths and operator networks
        result["status"] = "fail"
        result["action"] = "download_failed"
        result["errors"].append(f"{file_id} download failed: {exc}")
        return result

    result["action"] = "downloaded"
    result["size_bytes"] = written
    return result


def _download_public_fixture_entry(entry: dict[str, Any], target_path: Path, *, timeout_s: float) -> int:
    if str(entry.get("download_method", "")) == "dryad_public_preview":
        return _download_dryad_public_preview(entry, target_path, timeout_s=timeout_s)

    source_url = str(entry.get("source_url", "")).strip()
    source_url = _resolve_box_shared_folder_zip_url(entry, source_url=source_url, timeout_s=timeout_s)
    range_start = entry.get("range_start")
    range_end = entry.get("range_end")
    expected_size = int(entry.get("expected_size_bytes", 0) or 0)
    start = int(range_start) if range_start not in (None, "") else None
    end = int(range_end) if range_end not in (None, "") else None
    max_bytes = expected_size if expected_size > 0 else ((end - start + 1) if start is not None and end is not None else None)
    if str(entry.get("download_method", "")) == "box_shared_folder_zip":
        # Box returns a generated folder archive; its central directory can be
        # larger than the listed item size for the file inside the folder.
        max_bytes = None

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    written = _copy_public_fixture_bytes(
        source_url=source_url,
        tmp_path=tmp_path,
        start=start,
        end=end,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
    )
    tmp_path.replace(target_path)
    return written


class _DryadPreviewTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.cells: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        if tag in {"th", "td"}:
            self.in_cell = True
            self.cells = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cells.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"}:
            self.row.append("".join(self.cells).strip())
            self.in_cell = False
        if tag == "tr" and self.row:
            self.rows.append(self.row)


def _download_dryad_public_preview(entry: dict[str, Any], target_path: Path, *, timeout_s: float) -> int:
    dataset_url = str(entry.get("dataset_url") or entry.get("source_page_url") or entry.get("source_url") or "").strip()
    preview_id = str(entry.get("dryad_file_stream_id") or entry.get("preview_file_stream_id") or "").strip()
    if not dataset_url:
        raise ValueError("dryad_public_preview requires dataset_url/source_page_url")
    if not preview_id:
        raise ValueError("dryad_public_preview requires dryad_file_stream_id")
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    base_headers = {
        "User-Agent": "Mozilla/5.0 gas-ec-studio-public-fixture-acquisition/1.0",
        "Referer": dataset_url,
    }
    page_text = opener.open(Request(dataset_url, headers=base_headers), timeout=float(timeout_s)).read().decode("utf-8", "ignore")
    token_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page_text)
    if token_match is None:
        raise ValueError("Dryad preview page did not expose a CSRF token")
    preview_headers = {
        **base_headers,
        "X-CSRF-Token": token_match.group(1),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/javascript, application/javascript, */*; q=0.01",
    }
    preview_url = f"https://datadryad.org/data_file/preview/{preview_id}"
    js_text = opener.open(Request(preview_url, headers=preview_headers), timeout=float(timeout_s)).read().decode("utf-8", "ignore")
    html_match = re.search(r"innerHTML = `(.*)`\s*$", js_text, flags=re.S)
    table_html = html_match.group(1) if html_match else js_text
    parser = _DryadPreviewTableParser()
    parser.feed(_unescape_html_entities(table_html))
    if not parser.rows:
        raise ValueError(f"Dryad preview table is empty for file_stream/{preview_id}")
    header = parser.rows[0]
    rows = [row for row in parser.rows if len(row) == len(header)]
    if len(rows) <= 1:
        raise ValueError(f"Dryad preview table has no complete data rows for file_stream/{preview_id}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerows(rows)
    tmp_path.replace(target_path)
    return target_path.stat().st_size


def _unescape_html_entities(value: str) -> str:
    import html as html_module

    return html_module.unescape(value)


def _copy_public_fixture_bytes(
    *,
    source_url: str,
    tmp_path: Path,
    start: int | None,
    end: int | None,
    max_bytes: int | None,
    timeout_s: float,
) -> int:
    parsed = urlparse(source_url)
    if parsed.scheme in {"", "file"}:
        source_path = _local_path_from_source_url(source_url)
        return _copy_public_fixture_local_bytes(
            source_path=source_path,
            tmp_path=tmp_path,
            start=start,
            max_bytes=max_bytes,
        )

    request = Request(source_url, headers={"User-Agent": "gas_ec_studio_public_fixture_acquisition/1.0"})
    if start is not None and end is not None:
        request.add_header("Range", f"bytes={start}-{end}")
    written = 0
    with urlopen(request, timeout=float(timeout_s)) as response, tmp_path.open("wb") as output:
        if start and int(getattr(response, "status", 200) or 200) != 206:
            _discard_bytes(response, start)
        while True:
            chunk_size = 1024 * 1024
            if max_bytes is not None:
                remaining = max_bytes - written
                if remaining <= 0:
                    break
                chunk_size = min(chunk_size, remaining)
            chunk = response.read(chunk_size)
            if not chunk:
                break
            output.write(chunk)
            written += len(chunk)
    return written


def _resolve_box_shared_folder_zip_url(entry: dict[str, Any], *, source_url: str, timeout_s: float) -> str:
    if str(entry.get("download_method", "")) != "box_shared_folder_zip":
        return source_url
    folder_id = str(entry.get("box_folder_id", "")).strip()
    shared_name = str(entry.get("box_shared_name", "")).strip()
    if not folder_id or not shared_name:
        return source_url
    request_url = (
        "https://app.boxenterprise.net/index.php?"
        f"folder_id={folder_id}&q%5Bshared_item%5D%5Bshared_name%5D={shared_name}&rm=box_v2_zip_shared_folder"
    )
    request = Request(
        request_url,
        headers={
            "User-Agent": "gas_ec_studio_public_fixture_acquisition/1.0",
            "Referer": source_url,
        },
    )
    with urlopen(request, timeout=float(timeout_s)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    download_url = str(payload.get("download_url", "")).replace("\\/", "/")
    return download_url or source_url


def _copy_public_fixture_local_bytes(
    *,
    source_path: Path,
    tmp_path: Path,
    start: int | None,
    max_bytes: int | None,
) -> int:
    written = 0
    with source_path.open("rb") as source, tmp_path.open("wb") as output:
        if start:
            source.seek(start)
        while True:
            chunk_size = 1024 * 1024
            if max_bytes is not None:
                remaining = max_bytes - written
                if remaining <= 0:
                    break
                chunk_size = min(chunk_size, remaining)
            chunk = source.read(chunk_size)
            if not chunk:
                break
            output.write(chunk)
            written += len(chunk)
    return written


def _discard_bytes(response: Any, byte_count: int) -> None:
    remaining = max(0, int(byte_count or 0))
    while remaining > 0:
        chunk = response.read(min(1024 * 1024, remaining))
        if not chunk:
            return
        remaining -= len(chunk)


def _local_path_from_source_url(source_url: str) -> Path:
    parsed = urlparse(source_url)
    if parsed.scheme == "file":
        return Path(url2pathname(unquote(parsed.path)))
    return Path(source_url)


def _validate_public_full_output_file(file_payload: dict[str, Any], root: Path) -> dict[str, Any]:
    file_path = _resolve(root, file_payload.get("path"))
    role = str(file_payload.get("role", ""))
    result: dict[str, Any] = {
        "file_id": file_payload.get("file_id", ""),
        "role": role,
        "path": str(file_path),
        "source_filename": file_payload.get("source_filename", ""),
        "source_url": file_payload.get("source_url", ""),
        "range_start": file_payload.get("range_start"),
        "range_end": file_payload.get("range_end"),
        "status": "pass",
        "errors": [],
    }
    if not file_path.exists():
        result["status"] = "fail"
        result["errors"].append(f"public full-output file missing: {file_path}")
        return result

    _apply_public_file_hash_validation(file_payload, file_path, result)
    if role == "full_output_sample":
        detail = _public_full_output_sample_summary(
            file_path,
            list(file_payload.get("required_columns", []) or []),
            delimiter=_fixture_delimiter(file_payload),
        )
    elif role == "variable_units_descriptor":
        detail = _public_variable_units_summary(file_path, list(file_payload.get("required_variables", []) or []))
    else:
        result["errors"].append(f"unsupported public full-output file role: {role}")
        detail = {}

    detail_errors = list(detail.pop("errors", []) or [])
    result.update(detail)
    result["errors"].extend(str(error) for error in detail_errors)

    if result["errors"]:
        result["status"] = "fail"
    return result


def _apply_public_file_hash_validation(file_payload: dict[str, Any], file_path: Path, result: dict[str, Any]) -> None:
    expected_size = int(file_payload.get("expected_size_bytes", 0) or 0)
    actual_size = file_path.stat().st_size
    result["size_bytes"] = actual_size
    result["expected_size_bytes"] = expected_size
    result["size_status"] = "pass" if not expected_size or actual_size == expected_size else "fail"
    if result["size_status"] == "fail":
        result["errors"].append(f"{result.get('file_id', '')} size mismatch")

    expected_md5 = str(file_payload.get("expected_md5", "")).strip().upper()
    expected_sha256 = str(file_payload.get("expected_sha256", "")).strip().upper()
    md5 = _md5(file_path)
    sha256 = _sha256(file_path)
    result["md5"] = md5
    result["expected_md5"] = expected_md5
    result["md5_status"] = "pass" if not expected_md5 or md5 == expected_md5 else "fail"
    result["sha256"] = sha256
    result["expected_sha256"] = expected_sha256
    result["sha256_status"] = "pass" if not expected_sha256 or sha256 == expected_sha256 else "fail"
    if result["md5_status"] == "fail":
        result["errors"].append(f"{result.get('file_id', '')} md5 mismatch")
    if result["sha256_status"] == "fail":
        result["errors"].append(f"{result.get('file_id', '')} sha256 mismatch")


def _public_full_output_sample_summary(
    path: Path,
    required_columns: list[Any],
    *,
    delimiter: str = "\t",
) -> dict[str, Any]:
    required = [str(item) for item in required_columns]
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = [_clean_public_column_name(cell) for cell in next(reader)]
        except StopIteration:
            return {
                "column_count": 0,
                "row_count": 0,
                "required_columns": required,
                "missing_columns": required,
                "errors": ["full-output sample is empty"],
            }
        column_count = len(header)
        complete_rows = 0
        numeric_value_count = 0
        first_timestamp = ""
        last_timestamp = ""
        qc_columns = [column for column in header if column.startswith("qc_")]
        random_error_columns = [column for column in header if column.startswith("rand_err_")]
        footprint_columns = [column for column in header if column in {"x_peak", "x_offset", "x_10", "x_30", "x_50", "x_70", "x_90"}]
        ch4_flux_columns = [column for column in header if column in {"ch4_flux", "FCH4", "fch4"} or column.lower().endswith("ch4_flux")]
        li7700_diagnostic_columns = [
            column
            for column in header
            if "rssi_77" in column.lower() or "li7700" in column.lower() or "li_7700" in column.lower()
        ]
        ch4_numeric_value_count = 0
        ch4_non_missing_count = 0
        for row in reader:
            if len(row) < column_count:
                continue
            complete_rows += 1
            row_map = {header[index]: str(row[index]).strip().strip('"') for index in range(column_count)}
            timestamp = " ".join(part for part in [row_map.get("date", ""), row_map.get("time", "")] if part)
            if timestamp and not first_timestamp:
                first_timestamp = timestamp
            if timestamp:
                last_timestamp = timestamp
            numeric_value_count += sum(
                1
                for value in row[:column_count]
                if _parse_public_spectral_float(value) is not None
            )
            for column in ch4_flux_columns:
                index = header.index(column)
                parsed = _parse_public_spectral_float(row[index])
                if parsed is None:
                    continue
                ch4_numeric_value_count += 1
                if abs(parsed + 9999.0) > 1e-9:
                    ch4_non_missing_count += 1

    missing = [column for column in required if column not in header]
    return {
        "column_count": column_count,
        "row_count": complete_rows,
        "numeric_value_count": numeric_value_count,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "required_columns": required,
        "missing_columns": missing,
        "qc_columns": qc_columns,
        "random_error_columns": random_error_columns,
        "footprint_columns": footprint_columns,
        "ch4_flux_columns": ch4_flux_columns,
        "li7700_diagnostic_columns": li7700_diagnostic_columns,
        "has_energy_flux_fields": all(column in header for column in ("H", "LE", "ET", "Tau")),
        "has_uncertainty_fields": len(random_error_columns) >= 4,
        "has_footprint_fields": len(footprint_columns) >= 7,
        "has_ch4_flux_fields": bool(ch4_flux_columns),
        "has_li7700_status_fields": bool(li7700_diagnostic_columns),
        "ch4_numeric_value_count": ch4_numeric_value_count,
        "ch4_non_missing_count": ch4_non_missing_count,
        "errors": [f"missing full-output columns: {', '.join(missing)}"] if missing else [],
    }


def _fixture_delimiter(file_payload: dict[str, Any]) -> str:
    value = str(file_payload.get("delimiter", "") or "").strip().lower()
    if value in {"comma", "csv", ","}:
        return ","
    if value in {"semicolon", ";"}:
        return ";"
    if value in {"space", " "}:
        return " "
    return "\t"


def _public_variable_units_summary(path: Path, required_variables: list[Any]) -> dict[str, Any]:
    required = [str(item) for item in required_variables]
    variables: list[str] = []
    category_counts: Counter[str] = Counter()
    current_category = "uncategorized"
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            variable = _clean_public_column_name(row.get("variable", ""))
            if not variable:
                continue
            variables.append(variable)
            declared_category = str(row.get("info", "") or "").strip()
            if declared_category:
                current_category = declared_category
            category_counts[current_category] += 1
    missing = [variable for variable in required if variable not in variables]
    return {
        "variable_count": len(variables),
        "required_variables": required,
        "missing_variables": missing,
        "category_counts": dict(sorted(category_counts.items())),
        "errors": [f"missing variable-unit rows: {', '.join(missing)}"] if missing else [],
    }


def _clean_public_column_name(value: Any) -> str:
    return str(value or "").strip().strip('"')


def _validate_public_spectral_file(file_payload: dict[str, Any], root: Path) -> dict[str, Any]:
    file_path = _resolve(root, file_payload.get("path"))
    result: dict[str, Any] = {
        "file_id": file_payload.get("file_id", ""),
        "role": file_payload.get("role", ""),
        "spectral_family": file_payload.get("spectral_family", ""),
        "species": list(file_payload.get("species", []) or []),
        "path": str(file_path),
        "source_filename": file_payload.get("source_filename", ""),
        "source_url": file_payload.get("source_url", ""),
        "status": "pass",
        "errors": [],
    }
    if not file_path.exists():
        result["status"] = "fail"
        result["errors"].append(f"public spectral file missing: {file_path}")
        return result

    _apply_public_file_hash_validation(file_payload, file_path, result)
    result.update(_public_spectral_csv_summary(file_path))
    if int(result.get("numeric_row_count", 0) or 0) <= 0:
        result["errors"].append(f"{result['file_id']} has no spectral numeric rows")
    if int(result.get("numeric_value_count", 0) or 0) <= 0:
        result["errors"].append(f"{result['file_id']} has no spectral numeric values")
    if result["errors"]:
        result["status"] = "fail"
    return result


def _public_spectral_csv_summary(path: Path) -> dict[str, Any]:
    line_count = 0
    header_row = 0
    header: list[str] = []
    column_count = 0
    frequency_column_count = 0
    numeric_row_count = 0
    numeric_value_count = 0
    frequency_min: float | None = None
    frequency_max: float | None = None

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, start=1):
            line_count = line_number
            cells = [str(cell or "").strip() for cell in row]
            if not any(cells):
                continue
            if not header and _is_public_spectral_header(cells):
                header = cells
                header_row = line_number
                column_count = max(column_count, len(cells))
                frequency_column_count = sum(1 for cell in cells if _is_public_frequency_column(cell))
                continue
            if not header:
                continue

            parsed = [_parse_public_spectral_float(cell) for cell in cells]
            finite_values = [value for value in parsed if value is not None]
            if not finite_values:
                continue
            numeric_value_count += len(finite_values)
            column_count = max(column_count, len(cells))
            frequency_values = [
                value
                for index, value in enumerate(parsed)
                if value is not None and index < len(header) and _is_public_frequency_column(header[index])
            ]
            positive_frequencies = [value for value in frequency_values if value > 0.0]
            if not positive_frequencies:
                continue
            numeric_row_count += 1
            row_frequency_min = min(positive_frequencies)
            row_frequency_max = max(positive_frequencies)
            frequency_min = row_frequency_min if frequency_min is None else min(frequency_min, row_frequency_min)
            frequency_max = row_frequency_max if frequency_max is None else max(frequency_max, row_frequency_max)

    return {
        "line_count": line_count,
        "header_row": header_row,
        "column_count": column_count,
        "frequency_column_count": frequency_column_count,
        "numeric_row_count": numeric_row_count,
        "numeric_value_count": numeric_value_count,
        "frequency_min": frequency_min,
        "frequency_max": frequency_max,
    }


def _is_public_spectral_header(cells: list[str]) -> bool:
    normalized = [cell.strip().lower() for cell in cells]
    if not any(_is_public_frequency_column(cell) for cell in normalized):
        return False
    joined = ",".join(normalized)
    return any(token in joined for token in ("avrg_sp", "pred_sp", "avrg_cosp", "fit_cosp", "kaimal_cosp"))


def _is_public_frequency_column(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"fn", "nat_freq", "natural_frequency", "frequency", "freq"}


def _parse_public_spectral_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "na", "null", "none"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed) or parsed <= -9990.0:
        return None
    return parsed


def _metadata_bundle_payload(metadata_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(metadata_payload)
    return {
        "raw_file_description": payload.get("raw_file_description", {}),
        "raw_file_settings": payload.get("raw_file_settings", {}),
        "instruments": payload.get("instruments", {}),
    }


def _first_available_asset_key(asset: dict[str, Any], keys: list[str]) -> str:
    return next((key for key in keys if asset.get(key)), keys[0])


def _missing_required_window_fields(windows: list[dict[str, Any]], required_fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field_name in required_fields:
        if not windows or any(window.get(field_name) in (None, "") for window in windows):
            missing.append(field_name)
    return missing


def _record_file(result: dict[str, Any], label: str, path: Path, *, expected_hash: str | None = None) -> None:
    files = result.setdefault("files", {})
    hashes = result.setdefault("hashes", {})
    files[label] = str(path)
    if not path.exists():
        result.setdefault("errors", []).append(f"{label} missing: {path}")
        return
    if not path.is_file():
        result.setdefault("errors", []).append(f"{label} is not a file: {path}")
        return
    digest = _sha256(path)
    hashes[label] = digest
    if expected_hash and digest.upper() != str(expected_hash).upper():
        result.setdefault("errors", []).append(f"{label} sha256 mismatch")


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _md5(path: Path) -> str:
    hasher = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def _workspace_root(value: str | Path | None) -> Path:
    if value is not None:
        candidate = Path(value)
        if (candidate / DEFAULT_FIXTURE_PACK_PATH).exists():
            return candidate
    cwd = Path.cwd()
    if (cwd / DEFAULT_FIXTURE_PACK_PATH).exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def _workspace_root_for_pack(path: str | Path | None, workspace_root: str | Path | None) -> Path:
    if path is not None and workspace_root is not None:
        return Path(workspace_root)
    return _workspace_root(workspace_root)


def _dedupe(items: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))
