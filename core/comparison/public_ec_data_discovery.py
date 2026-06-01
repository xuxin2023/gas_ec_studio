from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from core.ec_rp.pipeline import ECRPPipeline
from core.storage.raw_importer import (
    can_load_raw_native,
    can_load_raw_text,
    load_raw_native_frames,
    load_raw_text_frames,
)
from models.hf_models import NormalizedHFFrame
from models.station_models import MetadataBundle


DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH = Path("references/eddypro/public_raw_search/ec_public_data_sources.json")
DEFAULT_PUBLIC_EC_SAMPLE_ROOT = Path("artifacts/public_ec_data")
DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH = Path("artifacts/public_ec_data/public_ec_data_discovery_probe.json")
DEFAULT_PUBLIC_RAW_IMPORTER_SMOKE_PLAN_PATH = Path("artifacts/public_ec_data/public_raw_importer_smoke_plan.json")
DEFAULT_NEON_HDF5_DOWNLOAD_PATH = Path("artifacts/public_ec_data/neon_hdf5_download.json")
DEFAULT_NEON_HDF5_VALIDATION_PACKAGE_PATH = Path("artifacts/public_ec_data/neon_hdf5_validation_package.json")
DEFAULT_PUBLIC_RAW_SAMPLE_VALIDATION_PACKAGE_PATH = Path(
    "artifacts/public_ec_data/public_raw_sample_validation_package.json"
)


def build_public_ec_data_discovery_probe(
    *,
    manifest_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    sample_output_root: str | Path | None = None,
    sample_bytes: int = 0,
    timeout_s: float = 60.0,
    run_network: bool = True,
) -> dict[str, Any]:
    """Probe public real EC candidates without promoting them to EddyPro parity fixtures."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, manifest_path or DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH)
    manifest = _read_json(source_path)
    sources = [dict(item or {}) for item in list(manifest.get("sources", []) or [])]
    sample_root = _resolve(root, sample_output_root or DEFAULT_PUBLIC_EC_SAMPLE_ROOT)
    probes = [
        _probe_source(
            item,
            sample_root=sample_root,
            sample_bytes=sample_bytes,
            timeout_s=timeout_s,
            run_network=run_network,
        )
        for item in sources
    ]
    status_counts: dict[str, int] = {}
    for probe in probes:
        status = str(probe.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    registered_count = sum(
        1
        for probe in probes
        if str(probe.get("registration_outcome", "")) in {"registered", "registered_and_accepted"}
    )
    real_candidate_count = sum(1 for probe in probes if bool(probe.get("real_data_candidate", False)))
    downloadable_count = sum(1 for probe in probes if str(probe.get("download_url_status", "")) == "verified")
    ready_to_register_count = sum(
        1
        for probe in probes
        if str(dict(probe.get("registration_readiness", {}) or {}).get("status", "")) == "ready_to_register"
    )
    raw_without_eddypro_pair_count = sum(
        1
        for probe in probes
        if bool(dict(probe.get("registration_readiness", {}) or {}).get("has_raw_input", False))
        and (
            "eddypro_project_or_settings"
            in list(dict(probe.get("registration_readiness", {}) or {}).get("missing_requirements", []) or [])
            or "official_eddypro_full_output"
            in list(dict(probe.get("registration_readiness", {}) or {}).get("missing_requirements", []) or [])
        )
    )
    return {
        "artifact_type": "public_ec_data_discovery_probe_v1",
        "generated_at": datetime.now().isoformat(),
        "manifest_path": str(source_path),
        "manifest_id": str(manifest.get("manifest_id", "")),
        "run_network": bool(run_network),
        "sample_bytes_requested": int(sample_bytes or 0),
        "sample_output_root": str(sample_root),
        "status": "ok" if probes else "no_sources",
        "summary": {
            "source_count": len(probes),
            "status_counts": status_counts,
            "registered_count": registered_count,
            "real_data_candidate_count": real_candidate_count,
            "downloadable_candidate_count": downloadable_count,
            "ready_to_register_candidate_count": ready_to_register_count,
            "raw_without_eddypro_pair_count": raw_without_eddypro_pair_count,
            "can_change_full_parity_gate": False,
            "next_action": _next_action(probes),
        },
        "sources": probes,
        "truthfulness_boundary": (
            "This artifact proves discovery/probe status only. It does not register a fixture, does not run EddyPro, "
            "and cannot change can_release_full_eddypro_parity until a candidate completes raw-to-final registration and acceptance."
        ),
    }


def build_public_raw_importer_smoke_plan(
    *,
    discovery_probe_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    max_sample_bytes: int = 65536,
) -> dict[str, Any]:
    """Build a safe importer-smoke plan for real public raw candidates.

    The plan is intentionally evidence-oriented: it identifies real raw sources
    that are useful for importer work while preserving the missing EddyPro
    settings/output requirements that keep full parity blocked.
    """

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    probe_path = _resolve(root, discovery_probe_path or DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH)
    probe = _read_json(probe_path) if probe_path.exists() else {}
    if not probe.get("sources"):
        probe = build_public_ec_data_discovery_probe(
            manifest_path=manifest_path,
            workspace_root=root,
            run_network=False,
        )
    sources = [dict(item or {}) for item in list(probe.get("sources", []) or [])]
    candidates = [_raw_importer_candidate_plan(item, max_sample_bytes=max_sample_bytes) for item in sources]
    real_candidates = [item for item in candidates if item.get("has_real_raw_potential")]
    direct_sample_count = sum(1 for item in real_candidates if item.get("sample_mode") == "byte_range")
    operator_subset_count = sum(1 for item in real_candidates if item.get("sample_mode") == "operator_subset")
    ready_to_register_count = sum(
        1 for item in real_candidates if str(item.get("registration_readiness_status", "")) == "ready_to_register"
    )
    return {
        "artifact_type": "public_raw_importer_smoke_plan_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "ready_for_importer_smoke" if real_candidates else "no_real_raw_candidates",
        "discovery_probe_path": str(probe_path) if probe_path.exists() else "",
        "source_count": len(sources),
        "real_raw_candidate_count": len(real_candidates),
        "direct_byte_sample_candidate_count": direct_sample_count,
        "operator_subset_required_count": operator_subset_count,
        "ready_to_register_candidate_count": ready_to_register_count,
        "max_sample_bytes": int(max_sample_bytes),
        "can_change_full_parity_gate": False,
        "candidate_plans": real_candidates,
        "next_actions": _smoke_plan_next_actions(real_candidates),
        "truthfulness_boundary": (
            "This plan moves real public data into importer smoke testing only. It does not register a parity fixture "
            "and cannot change full EddyPro parity until EddyPro project/settings, official Full_Output, normalized "
            "reference, provenance, and acceptance evidence are present."
        ),
    }


def build_public_raw_sample_importer_smoke(
    *,
    sample_path: str | Path,
    metadata_path: str | Path | None = None,
    metadata: MetadataBundle | dict[str, Any] | None = None,
    source_id: str = "",
    workspace_root: str | Path | None = None,
    max_rows: int = 0,
) -> dict[str, Any]:
    """Run the existing raw importer against an operator-supplied public raw subset.

    This closes the practical discovery gap: when a public source requires a
    manual licence step, authenticated download, or large-file subset, the
    operator can supply a small raw sample and still produce a machine-readable
    importer evidence artifact without promoting it to EddyPro parity.
    """

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, sample_path)
    metadata_bundle, metadata_source, metadata_error = _load_smoke_metadata(
        metadata=metadata,
        metadata_path=metadata_path,
        root=root,
    )
    payload: dict[str, Any] = {
        "artifact_type": "public_raw_sample_importer_smoke_v1",
        "generated_at": datetime.now().isoformat(),
        "source_id": str(source_id or source_path.stem),
        "source_file": str(source_path),
        "metadata_path": str(_resolve(root, metadata_path)) if metadata_path not in (None, "") else "",
        "metadata_source": metadata_source,
        "status": "fail",
        "import_status": "not_started",
        "raw_format": "",
        "row_count": 0,
        "loaded_row_count": 0,
        "max_rows": int(max_rows or 0),
        "time_range": {"start": None, "end": None},
        "field_coverage": _empty_field_coverage(),
        "sample_hash": "",
        "sample_size_bytes": 0,
        "errors": [],
        "warnings": [],
        "ready_for_raw_to_final_registration": False,
        "can_change_full_parity_gate": False,
        "claim_boundary": (
            "This artifact validates raw importer behavior for a public/operator-supplied subset only. "
            "It is not an EddyPro raw-to-final parity fixture until paired EddyPro settings, official "
            "Full_Output, normalized reference, provenance, and acceptance evidence are registered."
        ),
    }
    if metadata_error:
        payload["errors"].append(metadata_error)
        payload["import_status"] = "metadata_error"
        return payload
    if not source_path.exists() or not source_path.is_file():
        payload["errors"].append(f"sample missing: {source_path}")
        payload["import_status"] = "sample_missing"
        return payload

    payload["sample_size_bytes"] = source_path.stat().st_size
    payload["sample_hash"] = _sha256_file(source_path)
    rows, raw_format, load_error = _load_public_raw_sample_rows(source_path, metadata_bundle)
    payload["raw_format"] = raw_format
    if load_error:
        payload["import_status"] = "loader_error" if load_error.startswith("raw importer failed") else "unsupported_format"
        payload["errors"].append(load_error)
        return payload

    all_rows = list(rows)
    if max_rows and max_rows > 0:
        rows = all_rows[: int(max_rows)]
        if len(all_rows) > len(rows):
            payload["warnings"].append(
                f"Loaded {len(all_rows)} rows and summarized the first {len(rows)} rows because max_rows is set."
            )
    payload["loaded_row_count"] = len(all_rows)
    payload["row_count"] = len(rows)
    payload["field_coverage"] = _field_coverage(rows)
    payload["time_range"] = _time_range(rows)
    payload["import_status"] = "loaded" if rows else "loaded_empty"
    payload["status"] = _sample_smoke_status(rows, payload["field_coverage"])
    payload["ready_for_raw_to_final_registration"] = False
    payload["provenance"] = {
        "sample_sha256": payload["sample_hash"],
        "sample_size_bytes": payload["sample_size_bytes"],
        "loader": "core.storage.raw_importer",
        "metadata_source": metadata_source,
        "metadata_path": payload["metadata_path"],
        "source_id": payload["source_id"],
    }
    if payload["status"] == "partial":
        payload["warnings"].append(
            "Importer loaded rows, but the subset does not expose the complete EC field family needed for RP parity."
        )
    return payload


def build_public_raw_sample_rp_smoke(
    *,
    sample_path: str | Path,
    metadata_path: str | Path | None = None,
    metadata: MetadataBundle | dict[str, Any] | None = None,
    source_id: str = "",
    workspace_root: str | Path | None = None,
    max_rows: int = 0,
    min_rows: int = 64,
    sample_hz: float | None = None,
    block_minutes: float = 0.1,
) -> dict[str, Any]:
    """Load a public/operator raw subset and run it through the local RP pipeline."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, sample_path)
    metadata_bundle, metadata_source, metadata_error = _load_smoke_metadata(
        metadata=metadata,
        metadata_path=metadata_path,
        root=root,
    )
    importer_smoke = build_public_raw_sample_importer_smoke(
        sample_path=source_path,
        metadata=metadata_bundle,
        source_id=source_id,
        workspace_root=root,
        max_rows=max_rows,
    )
    payload: dict[str, Any] = {
        "artifact_type": "public_raw_sample_rp_smoke_v1",
        "generated_at": datetime.now().isoformat(),
        "source_id": str(source_id or source_path.stem),
        "source_file": str(source_path),
        "metadata_path": str(_resolve(root, metadata_path)) if metadata_path not in (None, "") else "",
        "metadata_source": metadata_source,
        "status": "blocked",
        "importer_smoke": importer_smoke,
        "row_count": int(importer_smoke.get("row_count", 0) or 0),
        "loaded_row_count": int(importer_smoke.get("loaded_row_count", 0) or 0),
        "min_rows": int(min_rows or 0),
        "raw_format": str(importer_smoke.get("raw_format", "")),
        "field_coverage": dict(importer_smoke.get("field_coverage", {}) or {}),
        "time_range": dict(importer_smoke.get("time_range", {}) or {}),
        "rp_config": {},
        "rp_result": {},
        "rp_summary": {},
        "window_count": 0,
        "errors": [],
        "warnings": [],
        "can_change_full_parity_gate": False,
        "ready_for_raw_to_final_registration": False,
        "truthfulness_boundary": (
            "This RP smoke proves an operator/public raw subset can enter the local RP pipeline. "
            "It does not claim EddyPro raw-to-final parity without paired EddyPro settings, official "
            "Full_Output, normalized reference, provenance, and acceptance evidence."
        ),
    }
    if metadata_error:
        payload["errors"].append(metadata_error)
        payload["status"] = "metadata_error"
        return payload
    if str(importer_smoke.get("status", "")) == "fail":
        payload["errors"].extend(list(importer_smoke.get("errors", []) or []))
        payload["status"] = "importer_failed"
        return payload
    if not dict(importer_smoke.get("field_coverage", {}) or {}).get("complete_for_rp_smoke", False):
        payload["errors"].append("Importer smoke did not expose the complete EC field family required for RP smoke.")
        payload["status"] = "blocked_incomplete_fields"
        return payload
    rows, _raw_format, load_error = _load_public_raw_sample_rows(source_path, metadata_bundle)
    if load_error:
        payload["errors"].append(load_error)
        payload["status"] = "importer_failed"
        return payload
    selected_rows = list(rows)
    if max_rows and max_rows > 0:
        selected_rows = selected_rows[: int(max_rows)]
    if len(selected_rows) < int(min_rows or 0):
        payload["errors"].append(
            f"Raw sample has {len(selected_rows)} rows after max_rows; {int(min_rows or 0)} rows are required for RP smoke."
        )
        payload["status"] = "blocked_insufficient_rows"
        return payload

    config = _public_raw_rp_smoke_config(
        metadata_bundle=metadata_bundle,
        sample_hz=sample_hz,
        block_minutes=block_minutes,
    )
    payload["rp_config"] = config
    try:
        result = ECRPPipeline().run(
            rows=selected_rows,
            project=metadata_bundle.project,
            site=metadata_bundle.site,
            config=config,
            data_source="public_raw_sample_rp_smoke",
            time_range=f"{payload['time_range'].get('start', '')}~{payload['time_range'].get('end', '')}",
        )
    except Exception as exc:  # pragma: no cover - defensive guard for operator data
        payload["errors"].append(f"RP pipeline failed: {exc}")
        payload["status"] = "rp_failed"
        return payload

    result_dict = result.to_dict()
    payload["rp_result"] = result_dict
    payload["rp_summary"] = dict(result_dict.get("summary", {}) or {})
    payload["window_count"] = len(result_dict.get("windows", []) or [])
    payload["status"] = "pass" if payload["window_count"] > 0 else "no_rp_windows"
    return payload


def build_public_raw_sample_validation_package(
    *,
    sample_path: str | Path,
    workspace_root: str | Path | None = None,
    metadata_path: str | Path | None = None,
    importer_smoke_path: str | Path | None = None,
    rp_smoke_path: str | Path | None = None,
    source_id: str = "",
    max_rows: int = 0,
    min_rp_rows: int = 64,
    sample_hz: float | None = None,
    block_minutes: float = 0.1,
) -> dict[str, Any]:
    """Package public raw subset importer and RP smoke evidence behind a truthful claim gate."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, sample_path)
    importer_path = _resolve(root, importer_smoke_path) if importer_smoke_path not in (None, "") else None
    rp_path = _resolve(root, rp_smoke_path) if rp_smoke_path not in (None, "") else None
    importer_smoke = _read_json(importer_path) if importer_path else build_public_raw_sample_importer_smoke(
        sample_path=source_path,
        metadata_path=metadata_path,
        source_id=source_id,
        workspace_root=root,
        max_rows=max_rows,
    )
    rp_smoke = _read_json(rp_path) if rp_path else build_public_raw_sample_rp_smoke(
        sample_path=source_path,
        metadata_path=metadata_path,
        source_id=source_id,
        workspace_root=root,
        max_rows=max_rows,
        min_rows=min_rp_rows,
        sample_hz=sample_hz,
        block_minutes=block_minutes,
    )
    importer_status = str(importer_smoke.get("status", "not_run"))
    rp_status = str(rp_smoke.get("status", "not_run"))
    status = _public_raw_validation_status(importer_status=importer_status, rp_status=rp_status)
    claim_boundary = {
        "can_change_full_parity_gate": False,
        "can_claim_public_raw_engineering_validation": status == "pass",
        "can_claim_eddypro_raw_to_final_parity": False,
        "can_release_full_eddypro_parity": False,
    }
    return {
        "artifact_type": "public_raw_sample_validation_package_v1",
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "source_id": str(source_id or importer_smoke.get("source_id") or rp_smoke.get("source_id") or source_path.stem),
        "source_file": str(source_path),
        "importer_smoke_artifact": str(importer_path) if importer_path else "",
        "rp_smoke_artifact": str(rp_path) if rp_path else "",
        "importer_status": importer_status,
        "rp_status": rp_status,
        "row_count": int(importer_smoke.get("row_count", 0) or rp_smoke.get("row_count", 0) or 0),
        "loaded_row_count": int(importer_smoke.get("loaded_row_count", 0) or rp_smoke.get("loaded_row_count", 0) or 0),
        "rp_window_count": int(rp_smoke.get("window_count", 0) or 0),
        "raw_format": str(importer_smoke.get("raw_format", rp_smoke.get("raw_format", ""))),
        "sample_hash": str(importer_smoke.get("sample_hash", "")),
        "time_range": dict(importer_smoke.get("time_range", rp_smoke.get("time_range", {})) or {}),
        "field_coverage": dict(importer_smoke.get("field_coverage", rp_smoke.get("field_coverage", {})) or {}),
        "claim_boundary": claim_boundary,
        "can_change_full_parity_gate": False,
        "ready_for_raw_to_final_registration": False,
        "errors": list(importer_smoke.get("errors", []) or []) + list(rp_smoke.get("errors", []) or []),
        "warnings": list(importer_smoke.get("warnings", []) or []) + list(rp_smoke.get("warnings", []) or []),
        "truthfulness_boundary": (
            "This package closes public/operator raw subset engineering validation through importer and RP smoke. "
            "It is still not an EddyPro official raw-to-final parity fixture because the registered evidence set "
            "does not include official EddyPro project/settings, Full_Output, normalized reference, provenance, and acceptance."
        ),
        "known_limitations": [
            "Operator/public subsets can validate parser and RP compatibility but may not represent the full original dataset.",
            "No official EddyPro executable output is compared in this package.",
            "QC equivalence, full run segmentation, and vendor-specific preprocessing remain outside this claim scope.",
        ],
        "next_action": _public_raw_validation_next_action(status),
    }


def build_public_ec_acquisition_closure(
    *,
    discovery_probe_path: str | Path | None = None,
    smoke_plan_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
    neon_download_path: str | Path | None = None,
    neon_validation_package_path: str | Path | None = None,
    public_raw_sample_validation_package_path: str | Path | None = None,
) -> dict[str, Any]:
    """Close the public-real-data acquisition round without over-claiming parity."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    probe_path = _resolve(root, discovery_probe_path or DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH)
    plan_path = _resolve(root, smoke_plan_path or DEFAULT_PUBLIC_RAW_IMPORTER_SMOKE_PLAN_PATH)
    probe = _read_json(probe_path) if probe_path.exists() else build_public_ec_data_discovery_probe(
        manifest_path=manifest_path,
        workspace_root=root,
        run_network=False,
    )
    plan = _read_json(plan_path) if plan_path.exists() else build_public_raw_importer_smoke_plan(
        discovery_probe_path=probe_path if probe_path.exists() else None,
        manifest_path=manifest_path,
        workspace_root=root,
    )
    neon_download_file = _resolve(root, neon_download_path or DEFAULT_NEON_HDF5_DOWNLOAD_PATH)
    neon_validation_file = _resolve(root, neon_validation_package_path or DEFAULT_NEON_HDF5_VALIDATION_PACKAGE_PATH)
    public_raw_sample_file = _resolve(
        root,
        public_raw_sample_validation_package_path or DEFAULT_PUBLIC_RAW_SAMPLE_VALIDATION_PACKAGE_PATH,
    )
    neon_download = _read_json(neon_download_file)
    neon_validation = _read_json(neon_validation_file)
    public_raw_sample_validation = _read_json(public_raw_sample_file)
    source_probes = {
        str(item.get("source_id", "")): dict(item or {})
        for item in list(probe.get("sources", []) or [])
        if isinstance(item, dict)
    }
    candidate_plans = [
        dict(item or {})
        for item in list(plan.get("candidate_plans", []) or [])
        if isinstance(item, dict)
    ]
    candidate_ids = {str(item.get("source_id", "")) for item in candidate_plans}
    registered_anchor_records = [
        _acquisition_registered_anchor_record(item)
        for source_id, item in source_probes.items()
        if source_id not in candidate_ids and str(item.get("registration_outcome", "")) == "registered_and_accepted"
    ]
    candidate_records = [
        _acquisition_candidate_record(
            plan_item,
            source_probe=source_probes.get(str(plan_item.get("source_id", "")), {}),
            neon_download=neon_download,
            neon_validation=neon_validation,
            public_raw_sample_validation=public_raw_sample_validation,
            neon_download_path=neon_download_file,
            neon_validation_path=neon_validation_file,
            public_raw_sample_validation_path=public_raw_sample_file,
        )
        for plan_item in candidate_plans
    ]
    records = [*registered_anchor_records, *candidate_records]
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("acquisition_status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    engineering_validations = _engineering_validation_summaries(
        neon_validation=neon_validation,
        public_raw_sample_validation=public_raw_sample_validation,
        neon_validation_path=neon_validation_file,
        public_raw_sample_validation_path=public_raw_sample_file,
    )
    ready_to_register_count = sum(1 for item in records if bool(item.get("can_register_as_eddypro_parity_fixture", False)))
    blockers = _acquisition_closure_blockers(records, engineering_validations=engineering_validations)
    status = "ready_to_register_candidate_found" if ready_to_register_count else (
        "engineering_validation_closed_full_parity_blocked" if engineering_validations else "acquisition_blocked"
    )
    return {
        "artifact_type": "public_ec_acquisition_closure_v1",
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "workspace_root": str(root),
        "inputs": {
            "discovery_probe_path": str(probe_path),
            "smoke_plan_path": str(plan_path),
            "neon_download_path": str(neon_download_file),
            "neon_validation_package_path": str(neon_validation_file),
            "public_raw_sample_validation_package_path": str(public_raw_sample_file),
        },
        "summary": {
            "source_count": len(source_probes),
            "candidate_count": len(candidate_plans),
            "status_counts": status_counts,
            "registered_anchor_count": int(status_counts.get("registered_anchor", 0) or 0),
            "downloaded_candidate_count": int(status_counts.get("public_download_engineering_validated", 0) or 0),
            "download_validated_count": int(status_counts.get("public_download_engineering_validated", 0) or 0),
            "operator_subset_required_count": int(status_counts.get("blocked_operator_subset_required", 0) or 0),
            "licence_required_count": int(status_counts.get("blocked_license_or_operator_subset_required", 0) or 0),
            "engineering_validation_count": len(engineering_validations),
            "engineering_validation_pass_count": len(engineering_validations),
            "ready_to_register_candidate_count": ready_to_register_count,
            "can_change_full_parity_gate": False,
        },
        "neon_download_summary": _acquisition_artifact_summary(
            neon_download,
            artifact_path=neon_download_file,
            fields=("status", "source_id", "candidate_name", "local_path", "size_bytes", "md5", "sha256"),
        ),
        "neon_validation_summary": _acquisition_artifact_summary(
            neon_validation,
            artifact_path=neon_validation_file,
            fields=("status", "source_id", "source_file", "row_count", "rp_status", "rp_window_count"),
        ),
        "public_raw_sample_validation_summary": _acquisition_artifact_summary(
            public_raw_sample_validation,
            artifact_path=public_raw_sample_file,
            fields=("status", "source_id", "source_file", "row_count", "importer_status", "rp_status", "rp_window_count"),
        ),
        "engineering_validations": engineering_validations,
        "sources": records,
        "blockers": blockers,
        "next_actions": _acquisition_closure_next_actions(records, blockers=blockers),
        "claim_boundary": {
            "can_claim_public_raw_engineering_validation": bool(engineering_validations),
            "can_claim_eddypro_raw_to_final_parity": ready_to_register_count > 0,
            "can_release_full_eddypro_parity": False,
            "can_change_full_parity_gate": False,
        },
        "truthfulness_boundary": (
            "This artifact closes the acquisition/engineering round only. Full EddyPro parity remains blocked "
            "until the same source has raw input, EddyPro project/settings, official Full_Output, normalized "
            "reference, normalization provenance, and acceptance evidence."
        ),
    }


def build_public_ec_acquisition_runbook(
    *,
    acquisition_closure: dict[str, Any] | None = None,
    acquisition_closure_path: str | Path | None = None,
    discovery_probe_path: str | Path | None = None,
    smoke_plan_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
    max_sample_bytes: int = 65536,
) -> dict[str, Any]:
    """Render a deterministic action ledger for public real-data acquisition.

    The runbook does not download by itself; it records which actions are safe
    to automate and which still require external licence, account, or operator
    evidence so CI/export/report paths can close without over-claiming parity.
    """

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    closure_path = _resolve(root, acquisition_closure_path) if acquisition_closure_path not in (None, "") else None
    closure = dict(acquisition_closure or {})
    if not closure and closure_path is not None and closure_path.exists():
        closure = _read_json(closure_path)
    if not closure or closure.get("artifact_type") != "public_ec_acquisition_closure_v1":
        closure = build_public_ec_acquisition_closure(
            discovery_probe_path=discovery_probe_path,
            smoke_plan_path=smoke_plan_path,
            workspace_root=root,
            manifest_path=manifest_path,
        )
    actions = [
        _public_ec_runbook_action(
            dict(item or {}),
            workspace_root=root,
            discovery_probe_path=discovery_probe_path,
            max_sample_bytes=max_sample_bytes,
        )
        for item in list(closure.get("sources", []) or [])
        if isinstance(item, dict)
    ]
    action_counts: dict[str, int] = {}
    for action in actions:
        state = str(action.get("automation_state", "unknown"))
        action_counts[state] = action_counts.get(state, 0) + 1
    ready_registration = [
        action for action in actions if bool(action.get("ready_for_registration_attempt", False))
    ]
    downloadable = [
        action for action in actions if str(action.get("automation_state", "")) == "automatic_download_available"
    ]
    engineering_validated = [
        action for action in actions if str(action.get("automation_state", "")) == "engineering_validated_registration_pending"
    ]
    external_required = [
        action
        for action in actions
        if str(action.get("automation_state", ""))
        in {"operator_subset_required", "license_or_auth_required", "missing_eddypro_pair"}
    ]
    status = "ready_for_registration_attempt" if ready_registration else (
        "automatic_download_available" if downloadable else (
            "engineering_validated_registration_pending" if engineering_validated else (
                "external_evidence_required" if external_required else "accepted_anchor_only"
            )
        )
    )
    return {
        "artifact_type": "public_ec_acquisition_runbook_v1",
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "workspace_root": str(root),
        "closure_artifact": str(closure_path or ""),
        "closure_status": str(closure.get("status", "")),
        "summary": {
            "source_count": len(actions),
            "automation_state_counts": dict(sorted(action_counts.items())),
            "automatic_download_candidate_count": len(downloadable),
            "engineering_validated_registration_pending_count": len(engineering_validated),
            "external_evidence_required_count": len(external_required),
            "ready_for_registration_attempt_count": len(ready_registration),
            "can_change_full_parity_gate": False,
        },
        "actions": actions,
        "blockers": list(closure.get("blockers", []) or []),
        "next_actions": _public_ec_runbook_next_actions(actions, closure),
        "claim_boundary": {
            "can_claim_public_raw_engineering_validation": bool(
                dict(closure.get("claim_boundary", {}) or {}).get("can_claim_public_raw_engineering_validation", False)
            ),
            "can_claim_eddypro_raw_to_final_parity": False,
            "can_release_full_eddypro_parity": False,
            "can_change_full_parity_gate": False,
        },
        "automation_policy": {
            "may_download_direct_public_candidates": True,
            "may_byte_sample_large_candidates": True,
            "may_auto_accept_licence_or_create_accounts": False,
            "may_promote_without_official_eddypro_outputs": False,
            "max_sample_bytes": int(max_sample_bytes or 0),
        },
        "truthfulness_boundary": (
            "This runbook makes acquisition actions explicit, but it does not perform licence acceptance, "
            "account registration, or full-parity promotion. Full EddyPro parity remains blocked until the "
            "same source has raw input, EddyPro project/settings, official Full_Output, normalized reference, "
            "normalization provenance, and accepted evidence."
        ),
    }


def _probe_source(
    source: dict[str, Any],
    *,
    sample_root: Path,
    sample_bytes: int,
    timeout_s: float,
    run_network: bool,
) -> dict[str, Any]:
    source_id = str(source.get("source_id", "unknown_source") or "unknown_source")
    provider = str(source.get("provider", ""))
    payload: dict[str, Any] = {
        "source_id": source_id,
        "provider": provider,
        "source_url": str(source.get("source_url", "")),
        "registration_outcome": str(source.get("registration_outcome", "")),
        "declared_access_status": str(source.get("access_status", "")),
        "parity_value": str(source.get("parity_value", "")),
        "status": "not_probed",
        "real_data_candidate": str(source.get("parity_value", "")).startswith("real_"),
        "download_url_status": "",
        "network_errors": [],
        "truthfulness_boundary": source.get("truthfulness_boundary", ""),
    }
    if not run_network:
        payload["status"] = "skipped_network"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
        payload["registration_readiness"] = _registration_readiness(source, payload)
        return payload

    if source.get("api_query_url"):
        payload.update(
            _probe_neon_api_source(
                source,
                sample_root=sample_root,
                sample_bytes=sample_bytes,
                timeout_s=timeout_s,
            )
        )
    elif "icos" in provider.lower() or "icos" in source_id.lower():
        payload.update(_probe_icos_landing_source(source, timeout_s=timeout_s))
    elif source.get("landing_probe_keywords") or source.get("candidate_files"):
        payload.update(_probe_generic_landing_source(source, timeout_s=timeout_s))
    else:
        payload["status"] = "static_ledger_only"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
    payload["registration_readiness"] = _registration_readiness(source, payload)
    return payload


def _raw_importer_candidate_plan(source_probe: dict[str, Any], *, max_sample_bytes: int) -> dict[str, Any]:
    readiness = dict(source_probe.get("registration_readiness", {}) or {})
    candidate_files = [dict(item or {}) for item in list(source_probe.get("candidate_files", []) or [])]
    downloadable = [
        item
        for item in candidate_files
        if str(item.get("download_url_status", "")) == "verified"
        or int(dict(item.get("head", {}) or {}).get("status_code", 0) or 0) == 200
        or str(item.get("url", "") or item.get("download_url", "")).startswith(("http://", "https://"))
    ]
    has_raw = bool(readiness.get("has_raw_input", False))
    parity_value = str(source_probe.get("parity_value", "")).lower()
    already_accepted = str(readiness.get("status", "")) == "registered_and_accepted"
    real_candidate = (
        has_raw
        or parity_value.startswith(("real_ec", "real_raw", "real_high_frequency_raw", "real_large_high_frequency_raw"))
    ) and not already_accepted
    sample_mode = "not_applicable"
    if downloadable:
        sample_mode = "byte_range"
    elif real_candidate:
        sample_mode = "operator_subset"
    missing = list(readiness.get("missing_requirements", []) or [])
    return {
        "source_id": str(source_probe.get("source_id", "")),
        "provider": str(source_probe.get("provider", "")),
        "source_url": str(source_probe.get("source_url", "")),
        "status": str(source_probe.get("status", "")),
        "has_real_raw_potential": bool(real_candidate),
        "sample_mode": sample_mode,
        "sample_byte_budget": int(max_sample_bytes) if sample_mode == "byte_range" else 0,
        "candidate_file_count": len(candidate_files),
        "downloadable_file_count": len(downloadable),
        "candidate_files": [
            {
                "name": str(item.get("name", "")),
                "url": str(item.get("url", "") or item.get("download_url", "")),
                "size_bytes": int(item.get("size_bytes", item.get("size", 0)) or 0),
                "download_url_status": str(item.get("download_url_status", "")),
            }
            for item in downloadable[:5]
        ],
        "registration_readiness_status": str(readiness.get("status", "")),
        "missing_for_eddypro_parity": missing,
        "can_register_as_eddypro_parity_fixture": not missing and bool(readiness),
        "recommended_smoke": _recommended_smoke(source_probe, sample_mode=sample_mode),
        "truthfulness_boundary": (
            "Importer smoke can validate parser and metadata handling. It is not an EddyPro raw-to-final parity fixture "
            "unless the missing registration evidence list is empty and acceptance passes."
        ),
    }


def _recommended_smoke(source_probe: dict[str, Any], *, sample_mode: str) -> dict[str, Any]:
    source_id = str(source_probe.get("source_id", "")).lower()
    provider = str(source_probe.get("provider", "")).lower()
    if "neon" in source_id or "neon" in provider:
        return {
            "smoke_type": "neon_hdf5_metadata_row_rp",
            "command_family": [
                "--download-neon-hdf5-candidate",
                "--build-neon-hdf5-metadata-smoke",
                "--build-neon-hdf5-row-smoke",
                "--run-neon-hdf5-rp-smoke",
            ],
            "claim_scope": "engineering_validation_only",
        }
    if "crocus" in source_id or "osti" in provider:
        return {
            "smoke_type": "generic_high_frequency_raw_sample",
            "command_family": ["--build-public-ec-data-discovery", "operator_supplied_sample_then_raw_importer_probe"],
            "claim_scope": "importer_validation_only",
        }
    if "bas" in source_id or "antarctic" in provider:
        return {
            "smoke_type": "large_raw_subset_stress_sample",
            "command_family": ["operator_supplied_subset_then_raw_importer_probe"],
            "claim_scope": "importer_stress_validation_only",
        }
    if "icos" in source_id or "icos" in provider:
        return {
            "smoke_type": "authenticated_raw_ascii_subset",
            "command_family": ["authenticated_download_or_operator_subset_then_raw_importer_probe"],
            "claim_scope": "importer_validation_only",
        }
    return {
        "smoke_type": "manual_public_raw_subset" if sample_mode == "operator_subset" else "byte_range_sample",
        "command_family": ["operator_supplied_sample_then_raw_importer_probe"],
        "claim_scope": "engineering_validation_only",
    }


def _probe_neon_api_source(
    source: dict[str, Any],
    *,
    sample_root: Path,
    sample_bytes: int,
    timeout_s: float,
) -> dict[str, Any]:
    api_url = str(source.get("api_query_url", "")).strip()
    result: dict[str, Any] = {
        "status": "blocked",
        "api_query_url": api_url,
        "api_status": "",
        "candidate_files": [],
        "download_url_status": "not_verified",
    }
    try:
        api_payload = _read_url_json(api_url, timeout_s=timeout_s)
    except Exception as exc:  # pragma: no cover - network/environment dependent
        result["status"] = "network_error"
        result["network_errors"] = [f"api_query_failed: {exc}"]
        return result

    result["api_status"] = "pass"
    candidates = _neon_candidate_files(api_payload)
    candidate_payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_payload = dict(candidate)
        head = _head_url(str(candidate.get("url", "")), timeout_s=timeout_s)
        candidate_payload["head"] = head
        if head.get("status_code") == 200:
            candidate_payload["download_url_status"] = "verified"
        if sample_bytes > 0 and head.get("status_code") == 200:
            sample = _download_byte_sample(
                source_url=str(candidate.get("url", "")),
                target_path=sample_root / "neon" / _safe_filename(str(candidate.get("name", "neon_candidate.h5.sample"))),
                sample_bytes=int(sample_bytes),
                timeout_s=timeout_s,
            )
            candidate_payload["byte_sample"] = sample
        candidate_payloads.append(candidate_payload)

    verified_count = sum(1 for item in candidate_payloads if str(item.get("download_url_status", "")) == "verified")
    result["candidate_files"] = candidate_payloads
    result["download_url_status"] = "verified" if verified_count else "not_verified"
    result["status"] = "candidate_verified" if verified_count else "api_only"
    result["registration_outcome"] = str(source.get("registration_outcome", "not_registered"))
    return result


def _probe_icos_landing_source(source: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "landing_not_verified",
        "download_url_status": "licence_required",
        "source_page_status": "",
        "licence_page_status": "",
        "registration_outcome": str(source.get("registration_outcome", "not_programmatically_registered")),
    }
    errors: list[str] = []
    try:
        source_text = _read_url_text(str(source.get("source_url", "")), timeout_s=timeout_s)
        result["source_page_status"] = "pass"
        result["mentions_raw_ascii"] = "Raw ASCII" in source_text
    except Exception as exc:  # pragma: no cover - network/environment dependent
        errors.append(f"source_page_failed: {exc}")
    if source.get("licence_url"):
        try:
            licence_text = _read_url_text(str(source.get("licence_url", "")), timeout_s=timeout_s)
            result["licence_page_status"] = "pass"
            result["licence_acceptance_required"] = "I hereby confirm" in licence_text or "licence_accept" in licence_text
        except Exception as exc:  # pragma: no cover - network/environment dependent
            errors.append(f"licence_page_failed: {exc}")
    result["network_errors"] = errors
    result["status"] = "licence_flow_verified" if result.get("source_page_status") == "pass" else "network_error"
    return result


def _probe_generic_landing_source(source: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "landing_not_verified",
        "download_url_status": "not_verified",
        "source_page_status": "",
        "registration_outcome": str(source.get("registration_outcome", "not_registered")),
        "candidate_files": [],
    }
    errors: list[str] = []
    try:
        source_text = _read_url_text(str(source.get("source_url", "")), timeout_s=timeout_s)
        result["source_page_status"] = "pass"
        result["landing_keyword_hits"] = _keyword_hits(
            source_text,
            [str(item) for item in list(source.get("landing_probe_keywords", []) or []) if str(item).strip()],
        )
    except Exception as exc:  # pragma: no cover - network/environment dependent
        errors.append(f"source_page_failed: {exc}")

    candidate_payloads: list[dict[str, Any]] = []
    for item in list(source.get("candidate_files", []) or []):
        candidate = dict(item or {})
        url = str(candidate.get("url", "") or candidate.get("download_url", "")).strip()
        if url:
            head = _head_url(url, timeout_s=timeout_s)
            candidate["head"] = head
            if head.get("status_code") == 200:
                candidate["download_url_status"] = "verified"
        candidate_payloads.append(candidate)
    result["candidate_files"] = candidate_payloads
    verified_count = sum(1 for item in candidate_payloads if str(item.get("download_url_status", "")) == "verified")
    if verified_count:
        result["download_url_status"] = "verified"
    elif result.get("source_page_status") == "pass":
        result["download_url_status"] = str(source.get("download_url_status", "landing_only") or "landing_only")
    result["network_errors"] = errors
    result["status"] = "landing_verified" if result.get("source_page_status") == "pass" else "network_error"
    return result


def _registration_readiness(source: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    declared = dict(source.get("registration_evidence", {}) or {})
    parity_value = str(source.get("parity_value", "")).lower()
    if parity_value.startswith(("real_raw", "real_high_frequency_raw", "real_large_high_frequency_raw")):
        declared.setdefault("raw_input", True)
    if str(source.get("registration_outcome", "")) in {"registered", "registered_and_accepted"}:
        declared.setdefault("raw_input", True)
        declared.setdefault("eddypro_project_or_settings", True)
        declared.setdefault("official_eddypro_full_output", True)
        declared.setdefault("normalized_reference", True)
        declared.setdefault("normalization_provenance", True)
        declared.setdefault("acceptance_evidence", True)
    required = {
        "raw_input": bool(declared.get("raw_input", False)),
        "eddypro_project_or_settings": bool(declared.get("eddypro_project_or_settings", False)),
        "official_eddypro_full_output": bool(declared.get("official_eddypro_full_output", False)),
        "normalized_reference": bool(declared.get("normalized_reference", False)),
        "normalization_provenance": bool(declared.get("normalization_provenance", False)),
        "acceptance_evidence": bool(declared.get("acceptance_evidence", False)),
    }
    missing = [key for key, present in required.items() if not present]
    status = "ready_to_register" if not missing else "blocked_missing_registration_evidence"
    if str(source.get("registration_outcome", "")) == "registered_and_accepted":
        status = "registered_and_accepted"
    return {
        "artifact_type": "public_ec_candidate_registration_readiness_v1",
        "status": status,
        "has_raw_input": required["raw_input"],
        "has_eddypro_project_or_settings": required["eddypro_project_or_settings"],
        "has_official_eddypro_full_output": required["official_eddypro_full_output"],
        "has_normalized_reference": required["normalized_reference"],
        "has_normalization_provenance": required["normalization_provenance"],
        "has_acceptance_evidence": required["acceptance_evidence"],
        "missing_requirements": missing,
        "can_change_full_parity_gate": False,
        "probe_status": str(probe.get("status", "")),
        "truthfulness_boundary": (
            "A public EC candidate is promotion-ready only when raw input, EddyPro project/settings, "
            "official EddyPro Full_Output, normalized reference, provenance, and acceptance evidence are all present."
        ),
    }


def _neon_candidate_files(api_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for release in list(dict(api_payload.get("data", {}) or {}).get("releases", []) or []):
        for package in list(dict(release or {}).get("packages", []) or []):
            for file_payload in list(dict(package or {}).get("files", []) or []):
                file_item = dict(file_payload or {})
                name = str(file_item.get("name", ""))
                if not name.lower().endswith((".h5", ".hdf5")):
                    continue
                candidates.append(
                    {
                        "name": name,
                        "size_bytes": int(file_item.get("size", 0) or 0),
                        "md5": str(file_item.get("md5", "")),
                        "url": str(file_item.get("url", "")),
                        "release": str(dict(release or {}).get("release", "")),
                        "site_code": str(dict(package or {}).get("siteCode", "")),
                        "month": str(dict(package or {}).get("month", "")),
                        "package_type": str(dict(package or {}).get("packageType", "")),
                    }
                )
    return candidates


def _download_byte_sample(*, source_url: str, target_path: Path, sample_bytes: int, timeout_s: float) -> dict[str, Any]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path = target_path.with_suffix(target_path.suffix + ".sample")
    end = max(0, int(sample_bytes) - 1)
    request = Request(
        source_url,
        headers={
            "User-Agent": "gas_ec_studio_public_ec_discovery/1.0",
            "Range": f"bytes=0-{end}",
        },
    )
    written = 0
    digest = hashlib.sha256()
    with urlopen(request, timeout=float(timeout_s)) as response, sample_path.open("wb") as output:
        while written < sample_bytes:
            chunk = response.read(min(65536, sample_bytes - written))
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            written += len(chunk)
    return {
        "status": "sampled" if written > 0 else "empty",
        "path": str(sample_path),
        "size_bytes": written,
        "sha256": digest.hexdigest().upper() if written > 0 else "",
        "requested_bytes": int(sample_bytes),
    }


def _head_url(url: str, *, timeout_s: float) -> dict[str, Any]:
    if not url:
        return {"status": "missing_url", "status_code": 0}
    request = Request(url, method="HEAD", headers={"User-Agent": "gas_ec_studio_public_ec_discovery/1.0"})
    try:
        with urlopen(request, timeout=float(timeout_s)) as response:
            return {
                "status": "pass",
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_length": _int_header(response.headers.get("Content-Length")),
                "content_type": str(response.headers.get("Content-Type", "")),
                "accept_ranges": str(response.headers.get("Accept-Ranges", "")),
                "etag": str(response.headers.get("ETag", "")),
                "x_goog_hash": str(response.headers.get("x-goog-hash", "")),
            }
    except Exception as exc:  # pragma: no cover - network/environment dependent
        return {"status": "fail", "status_code": 0, "error": str(exc)}


def _read_url_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    text = _read_url_text(url, timeout_s=timeout_s)
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _read_url_text(url: str, *, timeout_s: float) -> str:
    request = Request(url, headers={"User-Agent": "gas_ec_studio_public_ec_discovery/1.0"})
    with urlopen(request, timeout=float(timeout_s)) as response:
        return response.read().decode("utf-8", "replace")


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    folded = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in folded]


def _next_action(probes: list[dict[str, Any]]) -> str:
    if any(str(dict(item.get("registration_readiness", {}) or {}).get("status", "")) == "ready_to_register" for item in probes):
        return "Promote the ready public candidate through official raw bundle registration and acceptance."
    if any(str(item.get("status", "")) == "candidate_verified" for item in probes):
        return "Build a small importer smoke test for the verified NEON HDF5 candidate before downloading full files."
    if any(bool(dict(item.get("registration_readiness", {}) or {}).get("has_raw_input", False)) for item in probes):
        return "Use real raw public candidates for importer smoke tests while keeping full EddyPro parity blocked until an EddyPro output pair exists."
    if any(str(item.get("status", "")) == "licence_flow_verified" for item in probes):
        return "Add an authenticated ICOS download path or use an operator-provided accepted file."
    return "Continue source-derived parity closure and rerun public discovery later."


def _smoke_plan_next_actions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    byte_range_ids = [str(item.get("source_id", "")) for item in candidates if item.get("sample_mode") == "byte_range"]
    operator_ids = [str(item.get("source_id", "")) for item in candidates if item.get("sample_mode") == "operator_subset"]
    if byte_range_ids:
        actions.append(
            {
                "priority": "P0",
                "action": "Run bounded byte-range or metadata smoke on direct-download public candidates.",
                "source_ids": byte_range_ids,
            }
        )
    if operator_ids:
        actions.append(
            {
                "priority": "P1",
                "action": "Use operator-provided subsets for landing-page-only or very large raw datasets.",
                "source_ids": operator_ids,
            }
        )
    actions.append(
        {
            "priority": "P0",
            "action": "Keep full EddyPro parity blocked until each promoted source has settings, Full_Output, provenance, and acceptance evidence.",
            "source_ids": [str(item.get("source_id", "")) for item in candidates],
        }
    )
    return actions


def _load_smoke_metadata(
    *,
    metadata: MetadataBundle | dict[str, Any] | None,
    metadata_path: str | Path | None,
    root: Path,
) -> tuple[MetadataBundle, str, str]:
    if isinstance(metadata, MetadataBundle):
        return metadata, "provided_metadata_bundle", ""
    if isinstance(metadata, dict):
        try:
            return MetadataBundle.from_dict(dict(metadata)), "provided_metadata_dict", ""
        except Exception as exc:
            return MetadataBundle(), "provided_metadata_dict", f"metadata invalid: {exc}"
    if metadata_path not in (None, ""):
        path = _resolve(root, metadata_path)
        if not path.exists() or not path.is_file():
            return MetadataBundle(), "metadata_file", f"metadata missing: {path}"
        try:
            return MetadataBundle.from_dict(json.loads(path.read_text(encoding="utf-8"))), "metadata_file", ""
        except Exception as exc:
            return MetadataBundle(), "metadata_file", f"metadata invalid: {exc}"
    return MetadataBundle(), "default_metadata_bundle", ""


def _load_public_raw_sample_rows(
    source_path: Path,
    metadata_bundle: MetadataBundle,
) -> tuple[list[NormalizedHFFrame], str, str]:
    try:
        if can_load_raw_native(source_path, metadata_bundle):
            return load_raw_native_frames(source_path, metadata=metadata_bundle), "native", ""
        if can_load_raw_text(source_path):
            return load_raw_text_frames(source_path, metadata=metadata_bundle), "text", ""
    except Exception as exc:
        return [], source_path.suffix.lower().lstrip(".") or "unknown", f"raw importer failed: {exc}"
    return [], source_path.suffix.lower().lstrip(".") or "unknown", (
        f"unsupported raw importer suffix: {source_path.suffix or '<none>'}"
    )


def _public_raw_rp_smoke_config(
    *,
    metadata_bundle: MetadataBundle,
    sample_hz: float | None,
    block_minutes: float,
) -> dict[str, Any]:
    resolved_sample_hz = float(sample_hz or metadata_bundle.raw_file_settings.sample_hz or 10.0)
    resolved_block_minutes = float(block_minutes or 0.1)
    return {
        "sample_hz": resolved_sample_hz,
        "block_minutes": resolved_block_minutes,
        "rotation_mode": "double",
        "detrend_mode": "block_mean",
        "density_correction_mode": "mixing_ratio",
        "lag_phase": {"strategy": "none", "search_window_s": 0.0},
        "benchmark": {"status": "inactive", "target": "public_raw_sample_engineering_smoke"},
        "steps": {
            "window_sampling": {
                "sample_hz": resolved_sample_hz,
                "block_minutes": resolved_block_minutes,
                "window_minutes": resolved_block_minutes,
            }
        },
    }


def _public_raw_validation_status(*, importer_status: str, rp_status: str) -> str:
    if importer_status in {"pass", "partial"} and rp_status == "pass":
        return "pass"
    if importer_status in {"pass", "partial"} and rp_status in {
        "blocked",
        "blocked_insufficient_rows",
        "blocked_incomplete_fields",
        "no_rp_windows",
        "not_run",
    }:
        return "importer_only"
    return "fail"


def _public_raw_validation_next_action(status: str) -> str:
    if status == "pass":
        return (
            "Acquire or generate the paired EddyPro project/settings and official Full_Output, then promote the "
            "same source through official raw bundle registration and raw-to-final parity acceptance."
        )
    if status == "importer_only":
        return "Increase the real subset duration/field coverage and rerun RP smoke before attempting registration."
    return "Repair importer metadata, file format support, or field mappings before rerunning the public raw package."


def _acquisition_artifact_summary(
    artifact: dict[str, Any],
    *,
    artifact_path: Path,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    summary = {
        "artifact_path": str(artifact_path),
        "available": bool(artifact) and not bool(artifact.get("errors")),
    }
    for field in fields:
        summary[field] = artifact.get(field, "")
    if artifact.get("errors"):
        summary["errors"] = list(artifact.get("errors", []) or [])
    claim_boundary = artifact.get("claim_boundary")
    if isinstance(claim_boundary, dict):
        summary["claim_boundary"] = deepcopy(claim_boundary)
    return summary


def _acquisition_registered_anchor_record(source_probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(source_probe.get("source_id", "")),
        "provider": str(source_probe.get("provider", "")),
        "source_url": str(source_probe.get("source_url", "")),
        "acquisition_status": "registered_anchor",
        "registration_readiness_status": "registered_and_accepted",
        "missing_for_eddypro_parity": [],
        "can_register_as_eddypro_parity_fixture": False,
        "can_change_full_parity_gate": False,
        "evidence": {
            "registration_outcome": str(source_probe.get("registration_outcome", "")),
            "parity_value": str(source_probe.get("parity_value", "")),
        },
        "next_action": "Use this accepted anchor as existing evidence; continue seeking additional independent public raw-to-final pairs.",
    }


def _acquisition_candidate_record(
    plan_item: dict[str, Any],
    *,
    source_probe: dict[str, Any],
    neon_download: dict[str, Any],
    neon_validation: dict[str, Any],
    public_raw_sample_validation: dict[str, Any],
    neon_download_path: Path,
    neon_validation_path: Path,
    public_raw_sample_validation_path: Path,
) -> dict[str, Any]:
    source_id = str(plan_item.get("source_id", ""))
    source_id_folded = source_id.lower()
    provider_folded = str(plan_item.get("provider", "")).lower()
    missing = list(plan_item.get("missing_for_eddypro_parity", []) or [])
    sample_mode = str(plan_item.get("sample_mode", ""))
    acquisition_status = "blocked_missing_eddypro_pair"
    evidence: dict[str, Any] = {
        "probe_status": str(source_probe.get("status", plan_item.get("status", ""))),
        "sample_mode": sample_mode,
        "downloadable_file_count": int(plan_item.get("downloadable_file_count", 0) or 0),
    }
    if "neon" in source_id_folded or "neon" in provider_folded:
        neon_claim = dict(neon_validation.get("claim_boundary", {}) or {})
        evidence.update(
            {
                "download_artifact": str(neon_download_path) if neon_download else "",
                "download_status": str(neon_download.get("status", "")),
                "downloaded_size_bytes": int(neon_download.get("size_bytes", 0) or 0),
                "validation_artifact": str(neon_validation_path) if neon_validation else "",
                "validation_status": str(neon_validation.get("status", "")),
                "rp_status": str(neon_validation.get("rp_status", "")),
                "can_claim_neon_engineering_validation": bool(
                    neon_claim.get("can_claim_neon_engineering_validation", False)
                ),
            }
        )
        if str(neon_validation.get("status", "")) == "pass":
            acquisition_status = "public_download_engineering_validated"
        else:
            acquisition_status = "ready_for_public_download_or_validation"
    elif "icos" in source_id_folded or "icos" in provider_folded:
        acquisition_status = "blocked_license_or_operator_subset_required"
    elif sample_mode == "operator_subset":
        package_claim = dict(public_raw_sample_validation.get("claim_boundary", {}) or {})
        evidence.update(
            {
                "operator_subset_validation_artifact": (
                    str(public_raw_sample_validation_path) if public_raw_sample_validation else ""
                ),
                "operator_subset_validation_status": str(public_raw_sample_validation.get("status", "")),
                "operator_subset_source_id": str(public_raw_sample_validation.get("source_id", "")),
                "can_claim_public_raw_engineering_validation": bool(
                    package_claim.get("can_claim_public_raw_engineering_validation", False)
                ),
            }
        )
        if _operator_subset_validation_matches(source_id, public_raw_sample_validation):
            acquisition_status = "operator_subset_engineering_validated"
        else:
            acquisition_status = "blocked_operator_subset_required"
    elif sample_mode == "byte_range":
        acquisition_status = "ready_for_public_download_or_validation"
    return {
        "source_id": source_id,
        "provider": str(plan_item.get("provider", "")),
        "source_url": str(plan_item.get("source_url", "")),
        "acquisition_status": acquisition_status,
        "sample_mode": sample_mode,
        "registration_readiness_status": str(plan_item.get("registration_readiness_status", "")),
        "missing_for_eddypro_parity": missing,
        "can_register_as_eddypro_parity_fixture": bool(plan_item.get("can_register_as_eddypro_parity_fixture", False)),
        "can_change_full_parity_gate": False,
        "evidence": evidence,
        "next_action": _acquisition_source_next_action(acquisition_status),
    }


def _operator_subset_validation_matches(source_id: str, package: dict[str, Any]) -> bool:
    if str(package.get("status", "")) != "pass":
        return False
    package_source = str(package.get("source_id", "")).lower()
    if not package_source:
        return False
    folded = source_id.lower()
    return package_source in folded or folded in package_source


def _engineering_validation_summaries(
    *,
    neon_validation: dict[str, Any],
    public_raw_sample_validation: dict[str, Any],
    neon_validation_path: Path,
    public_raw_sample_validation_path: Path,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    neon_claim = dict(neon_validation.get("claim_boundary", {}) or {})
    if str(neon_validation.get("status", "")) == "pass":
        items.append(
            {
                "validation_type": "neon_hdf5_engineering_validation",
                "status": "pass",
                "source_id": str(neon_validation.get("source_id", "")),
                "source_file": str(neon_validation.get("source_file", "")),
                "artifact": str(neon_validation_path),
                "row_count": int(neon_validation.get("row_count", 0) or 0),
                "rp_window_count": int(neon_validation.get("rp_window_count", 0) or 0),
                "can_claim_engineering_validation": bool(neon_claim.get("can_claim_neon_engineering_validation", False)),
                "can_claim_eddypro_raw_to_final_parity": bool(
                    neon_claim.get("can_claim_eddypro_raw_to_final_parity", False)
                ),
            }
        )
    public_claim = dict(public_raw_sample_validation.get("claim_boundary", {}) or {})
    if str(public_raw_sample_validation.get("status", "")) == "pass":
        items.append(
            {
                "validation_type": "public_raw_sample_engineering_validation",
                "status": "pass",
                "source_id": str(public_raw_sample_validation.get("source_id", "")),
                "source_file": str(public_raw_sample_validation.get("source_file", "")),
                "artifact": str(public_raw_sample_validation_path),
                "row_count": int(public_raw_sample_validation.get("row_count", 0) or 0),
                "rp_window_count": int(public_raw_sample_validation.get("rp_window_count", 0) or 0),
                "can_claim_engineering_validation": bool(
                    public_claim.get("can_claim_public_raw_engineering_validation", False)
                ),
                "can_claim_eddypro_raw_to_final_parity": bool(
                    public_claim.get("can_claim_eddypro_raw_to_final_parity", False)
                ),
            }
        )
    return items


def _acquisition_closure_blockers(
    records: list[dict[str, Any]],
    *,
    engineering_validations: list[dict[str, Any]],
) -> list[str]:
    blockers = [
        "No public candidate has the complete raw/settings/official Full_Output/reference/provenance/acceptance set required for EddyPro raw-to-final parity."
    ]
    if not engineering_validations:
        blockers.append("No public engineering validation package has passed yet.")
    if any(str(item.get("acquisition_status", "")) == "blocked_operator_subset_required" for item in records):
        blockers.append("At least one real raw candidate still requires an operator-provided subset.")
    if any(str(item.get("acquisition_status", "")) == "blocked_license_or_operator_subset_required" for item in records):
        blockers.append("At least one public source still requires licence/authenticated download handling.")
    return _dedupe_strings(blockers)


def _acquisition_closure_next_actions(records: list[dict[str, Any]], *, blockers: list[str]) -> list[dict[str, Any]]:
    actions = [
        {
            "priority": "P0",
            "action": "Keep full EddyPro parity blocked until an official raw-to-final evidence pair is registered and accepted.",
            "source_ids": [str(item.get("source_id", "")) for item in records],
        }
    ]
    for status, priority, action in (
        ("ready_for_public_download_or_validation", "P0", "Download or validate direct public candidates such as NEON."),
        ("blocked_operator_subset_required", "P1", "Obtain a small auditable raw subset for landing-page-only or very large candidates."),
        ("blocked_license_or_operator_subset_required", "P1", "Complete licence/authenticated download flow or attach an operator-provided accepted subset."),
    ):
        ids = [str(item.get("source_id", "")) for item in records if str(item.get("acquisition_status", "")) == status]
        if ids:
            actions.append({"priority": priority, "action": action, "source_ids": ids})
    if blockers:
        actions.append({"priority": "P0", "action": "Carry blockers into delivery/report manifests instead of stalling execution.", "blockers": blockers})
    return actions


def _public_ec_runbook_action(
    source: dict[str, Any],
    *,
    workspace_root: Path,
    discovery_probe_path: str | Path | None,
    max_sample_bytes: int,
) -> dict[str, Any]:
    source_id = str(source.get("source_id", ""))
    provider = str(source.get("provider", ""))
    status = str(source.get("acquisition_status", ""))
    missing = list(source.get("missing_for_eddypro_parity", []) or [])
    evidence = dict(source.get("evidence", {}) or {})
    automation_state = _public_ec_automation_state(source)
    commands = _public_ec_runbook_commands(
        source_id=source_id,
        provider=provider,
        automation_state=automation_state,
        workspace_root=workspace_root,
        discovery_probe_path=discovery_probe_path,
        max_sample_bytes=max_sample_bytes,
    )
    ready_for_registration = bool(source.get("can_register_as_eddypro_parity_fixture", False)) and not missing
    return {
        "source_id": source_id,
        "provider": provider,
        "source_url": str(source.get("source_url", "")),
        "acquisition_status": status,
        "automation_state": automation_state,
        "sample_mode": str(source.get("sample_mode", "")),
        "registration_readiness_status": str(source.get("registration_readiness_status", "")),
        "missing_for_eddypro_parity": missing,
        "ready_for_registration_attempt": ready_for_registration,
        "safe_to_run_without_user_login": automation_state == "automatic_download_available",
        "requires_external_action": automation_state in {
            "operator_subset_required",
            "license_or_auth_required",
            "missing_eddypro_pair",
        },
        "evidence": evidence,
        "commands": commands,
        "next_action": source.get("next_action", _acquisition_source_next_action(status)),
        "truthfulness_boundary": (
            "Runbook actions improve acquisition and engineering validation only. Do not claim EddyPro raw-to-final "
            "parity until the missing evidence list is empty and acceptance commands pass."
        ),
    }


def _public_ec_automation_state(source: dict[str, Any]) -> str:
    status = str(source.get("acquisition_status", ""))
    if status == "registered_anchor":
        return "accepted_anchor"
    if status in {"public_download_engineering_validated", "operator_subset_engineering_validated"}:
        return "engineering_validated_registration_pending"
    if status == "ready_for_public_download_or_validation":
        return "automatic_download_available"
    if status == "blocked_license_or_operator_subset_required":
        return "license_or_auth_required"
    if status == "blocked_operator_subset_required":
        return "operator_subset_required"
    if status == "blocked_missing_eddypro_pair":
        return "missing_eddypro_pair"
    if bool(source.get("can_register_as_eddypro_parity_fixture", False)):
        return "registration_attempt_available"
    return "tracking_only"


def _public_ec_runbook_commands(
    *,
    source_id: str,
    provider: str,
    automation_state: str,
    workspace_root: Path,
    discovery_probe_path: str | Path | None,
    max_sample_bytes: int,
) -> list[dict[str, Any]]:
    probe_arg = str(discovery_probe_path or DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH)
    root_arg = str(workspace_root)
    commands: list[dict[str, Any]] = []
    folded = f"{source_id} {provider}".lower()
    if automation_state == "automatic_download_available" and "neon" in folded:
        commands.extend(
            [
                {
                    "step": "download_neon_hdf5_candidate",
                    "claim_scope": "engineering_validation_only",
                    "command": (
                        "python -m core.headless_batch_runner "
                        f"--download-neon-hdf5-candidate \"{probe_arg}\" "
                        f"--workspace-root \"{root_arg}\" "
                        f"--neon-hdf5-source-id \"{source_id}\" "
                        "--output artifacts/public_ec_data/neon_hdf5_download.json"
                    ),
                },
                {
                    "step": "build_neon_hdf5_validation_package",
                    "claim_scope": "engineering_validation_only",
                    "command": (
                        "python -m core.headless_batch_runner "
                        "--build-neon-hdf5-validation-package <downloaded-neon-file.h5> "
                        f"--workspace-root \"{root_arg}\" "
                        f"--neon-hdf5-source-id \"{source_id}\" "
                        "--output artifacts/public_ec_data/neon_hdf5_validation_package.json"
                    ),
                },
            ]
        )
    elif automation_state == "automatic_download_available":
        commands.append(
            {
                "step": "byte_sample_public_candidate",
                "claim_scope": "importer_smoke_only",
                "command": (
                    "python -m core.headless_batch_runner "
                    f"--build-public-ec-data-discovery --workspace-root \"{root_arg}\" "
                    f"--public-ec-sample-bytes {int(max_sample_bytes or 0)} "
                    "--output artifacts/public_ec_data/public_ec_data_discovery_probe.json"
                ),
            }
        )
    if automation_state in {"operator_subset_required", "license_or_auth_required"}:
        commands.append(
            {
                "step": "validate_operator_supplied_subset",
                "claim_scope": "engineering_validation_only",
                "command": (
                    "python -m core.headless_batch_runner "
                    "--build-public-raw-sample-validation-package <operator-supplied-public-subset.csv> "
                    f"--workspace-root \"{root_arg}\" "
                    f"--public-raw-source-id \"{source_id}\" "
                    "--output artifacts/public_ec_data/public_raw_sample_validation_package.json"
                ),
            }
        )
    commands.append(
        {
            "step": "rebuild_acquisition_closure",
            "claim_scope": "closure_manifest_only",
            "command": (
                "python -m core.headless_batch_runner "
                f"--build-public-ec-acquisition-closure --workspace-root \"{root_arg}\" "
                "--output artifacts/public_ec_data/public_ec_acquisition_closure.json"
            ),
        }
    )
    commands.append(
        {
            "step": "rebuild_acquisition_runbook",
            "claim_scope": "closure_manifest_only",
            "command": (
                "python -m core.headless_batch_runner "
                f"--build-public-ec-acquisition-runbook --workspace-root \"{root_arg}\" "
                "--output artifacts/public_ec_data/public_ec_acquisition_runbook.json"
            ),
        }
    )
    return commands


def _public_ec_runbook_next_actions(actions: list[dict[str, Any]], closure: dict[str, Any]) -> list[dict[str, Any]]:
    next_actions: list[dict[str, Any]] = []
    for state, priority, action in (
        ("automatic_download_available", "P0", "Run safe direct-download or byte-sampling commands and rebuild validation artifacts."),
        ("engineering_validated_registration_pending", "P0", "Attach matching EddyPro project/settings and official Full_Output before registration."),
        ("operator_subset_required", "P1", "Provide a bounded public/operator raw subset and run validation package."),
        ("license_or_auth_required", "P1", "Complete provider licence/authenticated download externally, then validate the accepted subset."),
        ("missing_eddypro_pair", "P1", "Locate or generate the matching EddyPro settings/output pair for the same raw source."),
    ):
        ids = [str(item.get("source_id", "")) for item in actions if str(item.get("automation_state", "")) == state]
        if ids:
            next_actions.append({"priority": priority, "action": action, "source_ids": ids})
    blockers = list(closure.get("blockers", []) or [])
    if blockers:
        next_actions.append({"priority": "P0", "action": "Keep full EddyPro parity blocked and carry blockers into delivery reports.", "blockers": blockers})
    return next_actions


def _acquisition_source_next_action(status: str) -> str:
    if status == "public_download_engineering_validated":
        return "Attach official EddyPro settings and Full_Output for the same source before attempting parity registration."
    if status == "operator_subset_engineering_validated":
        return "Replace the subset with a complete official raw/settings/Full_Output evidence pair when available."
    if status == "blocked_operator_subset_required":
        return "Provide a bounded raw subset and run public raw sample validation package."
    if status == "blocked_license_or_operator_subset_required":
        return "Complete licence/authenticated download or provide accepted subset evidence."
    if status == "ready_for_public_download_or_validation":
        return "Run direct download, metadata/row smoke, and RP validation package."
    return "Keep source in acquisition ledger and rerun discovery later."


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        output.append(text)
        seen.add(text)
    return output


def _empty_field_coverage() -> dict[str, Any]:
    return {
        "row_count": 0,
        "required_fields": ["timestamp", "u", "v", "w", "co2_ppm", "h2o_mmol", "pressure_kpa"],
        "optional_fields": ["ch4_ppb", "chamber_temp_c", "case_temp_c"],
        "present_fields": [],
        "missing_required_fields": ["timestamp", "u", "v", "w", "co2_ppm", "h2o_mmol", "pressure_kpa"],
        "field_counts": {},
        "complete_for_rp_smoke": False,
    }


def _field_coverage(rows: list[NormalizedHFFrame]) -> dict[str, Any]:
    coverage = _empty_field_coverage()
    coverage["row_count"] = len(rows)
    counts = {field: 0 for field in coverage["required_fields"] + coverage["optional_fields"]}
    counts["timestamp"] = len(rows)
    for row in rows:
        raw_payload = _frame_raw_payload(row)
        for field in ("co2_ppm", "h2o_mmol", "pressure_kpa", "ch4_ppb", "chamber_temp_c", "case_temp_c"):
            if getattr(row, field) is not None:
                counts[field] += 1
        for field in ("u", "v", "w"):
            if raw_payload.get(field) is not None:
                counts[field] += 1
    present = [field for field, count in counts.items() if count > 0]
    missing = [field for field in coverage["required_fields"] if counts.get(field, 0) <= 0]
    coverage["present_fields"] = present
    coverage["missing_required_fields"] = missing
    coverage["field_counts"] = counts
    coverage["complete_for_rp_smoke"] = bool(rows) and not missing
    return coverage


def _frame_raw_payload(row: NormalizedHFFrame) -> dict[str, Any]:
    if not row.raw_text:
        return {}
    try:
        payload = json.loads(row.raw_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _time_range(rows: list[NormalizedHFFrame]) -> dict[str, str | None]:
    if not rows:
        return {"start": None, "end": None}
    ordered = sorted(rows, key=lambda item: item.timestamp)
    return {"start": ordered[0].timestamp.isoformat(), "end": ordered[-1].timestamp.isoformat()}


def _sample_smoke_status(rows: list[NormalizedHFFrame], coverage: dict[str, Any]) -> str:
    if not rows:
        return "fail"
    if coverage.get("complete_for_rp_smoke"):
        return "pass"
    return "partial"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"sources": [], "manifest_id": "", "errors": [f"manifest missing: {path}"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"sources": [], "manifest_id": "", "errors": [f"manifest invalid: {exc}"]}
    return deepcopy(payload) if isinstance(payload, dict) else {"sources": [], "manifest_id": ""}


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in value.strip())
    return safe or "public_ec_candidate"


def _int_header(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
