from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.comparison.eddypro_coverage_audit import DEFAULT_CAPABILITY_MATRIX_PATH
from core.comparison.fixture_pack import build_public_raw_search_summary


DEFAULT_PUBLIC_RAW_SEARCH_MANIFEST_PATH = Path("references/eddypro/public_raw_search/manifest.json")
DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH = Path("references/eddypro/public_raw_search/ec_public_data_sources.json")
DEFAULT_NEON_VALIDATION_PACKAGE_PATH = Path("artifacts/public_ec_data/neon_hdf5_validation_package.json")
DEFAULT_PUBLIC_RAW_SAMPLE_VALIDATION_PACKAGE_PATH = Path(
    "artifacts/public_ec_data/public_raw_sample_validation_package.json"
)


def build_eddypro_partial_capability_closure(
    *,
    workspace_root: str | Path | None = None,
    capability_matrix_path: str | Path | None = None,
    public_raw_search_manifest_path: str | Path | None = None,
    public_ec_data_sources_path: str | Path | None = None,
    neon_validation_package_path: str | Path | None = None,
    public_raw_sample_validation_package_path: str | Path | None = None,
    coverage_audit: dict[str, Any] | None = None,
    release_gate: dict[str, Any] | None = None,
    public_raw_search_summary: dict[str, Any] | None = None,
    public_ec_data_sources: dict[str, Any] | None = None,
    neon_validation_package: dict[str, Any] | None = None,
    public_raw_sample_validation_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-blocking closure ledger for the remaining partial EddyPro features.

    This artifact is deliberately not a full-parity gate. It records why work can
    continue when public raw data is unavailable while keeping the full EddyPro
    parity claim blocked until real raw/settings/output evidence exists.
    """

    root = _workspace_root(workspace_root)
    matrix_path = _resolve(root, capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH)
    matrix = _read_json(matrix_path)
    coverage = dict(coverage_audit or {})
    release = dict(release_gate or {})
    capability_rows = _capability_rows(matrix=matrix, coverage_audit=coverage)
    partial_rows = [row for row in capability_rows if str(row.get("gas_ec_status", "")).lower() == "partial"]
    raw_search = (
        dict(public_raw_search_summary)
        if public_raw_search_summary is not None
        else build_public_raw_search_summary(public_raw_search_manifest_path, workspace_root=root)
    )
    ec_sources_path = _resolve(root, public_ec_data_sources_path or DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH)
    ec_sources = dict(public_ec_data_sources) if public_ec_data_sources is not None else _read_json(ec_sources_path)
    neon_path = _resolve(root, neon_validation_package_path or DEFAULT_NEON_VALIDATION_PACKAGE_PATH)
    neon = dict(neon_validation_package) if neon_validation_package is not None else _discover_neon_validation(root, neon_path)
    public_raw_sample_path = _resolve(
        root,
        public_raw_sample_validation_package_path or DEFAULT_PUBLIC_RAW_SAMPLE_VALIDATION_PACKAGE_PATH,
    )
    public_raw_sample = (
        dict(public_raw_sample_validation_package)
        if public_raw_sample_validation_package is not None
        else _discover_public_raw_sample_validation(root, public_raw_sample_path)
    )
    accepted_anchor = _accepted_official_anchor(root=root, release_gate=release)
    source_derived_functional_parity = _source_derived_functional_parity(matrix, coverage, release)
    public_search = _public_search_closure(raw_search=raw_search, ec_sources=ec_sources)
    partials = [
        _partial_capability_record(
            row,
            accepted_anchor=accepted_anchor,
            raw_search=raw_search,
            public_search=public_search,
            neon=neon,
            public_raw_sample=public_raw_sample,
        )
        for row in partial_rows
    ]
    status_counts = Counter(str(row.get("gas_ec_status", "") or "unknown") for row in capability_rows)
    ready_count = int(public_search.get("ready_to_register_public_raw_candidate_count", 0) or 0)
    partial_count = len(partials)
    can_close_full_parity = (
        partial_count == 0
        and bool(release.get("can_release_full_eddypro_parity", coverage.get("can_claim_full_eddypro_parity", False)))
    )
    return {
        "artifact_type": "eddypro_partial_capability_closure_v1",
        "closure_id": "eddypro_partial_capability_closure_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "complete" if partial_count == 0 else "source_derived_closed_real_evidence_pending",
        "workspace_root": str(root),
        "inputs": {
            "capability_matrix_path": str(matrix_path),
            "public_raw_search_manifest_path": str(
                _resolve(root, public_raw_search_manifest_path or DEFAULT_PUBLIC_RAW_SEARCH_MANIFEST_PATH)
            ),
            "public_ec_data_sources_path": str(ec_sources_path),
            "neon_validation_package_path": str(neon_path),
            "public_raw_sample_validation_package_path": str(public_raw_sample_path),
            "coverage_audit_provided": bool(coverage_audit),
            "release_gate_provided": bool(release_gate),
        },
        "partial_capability_count": partial_count,
        "capability_ids": [str(row.get("id", "")) for row in partials],
        "capability_status_counts": dict(sorted(status_counts.items())),
        "claim_boundary": {
            "can_close_full_eddypro_parity": can_close_full_parity,
            "can_claim_source_derived_functional_parity": source_derived_functional_parity,
            "can_promote_from_public_search": ready_count > 0,
            "can_release_full_eddypro_parity": bool(release.get("can_release_full_eddypro_parity", False)),
            "can_release_source_derived_functional_parity": bool(
                release.get("can_release_source_derived_functional_parity", source_derived_functional_parity)
            ),
            "blocked_claims": [
                "official_field_numeric_parity",
                "vendor_certified_eddypro_equivalence",
                "complete_multi_site_real_raw_breadth",
            ]
            if not can_close_full_parity
            else [],
        },
        "accepted_official_anchor": accepted_anchor,
        "neon_engineering_validation": _neon_summary(neon),
        "public_raw_sample_engineering_validation": _public_raw_sample_summary(public_raw_sample),
        "public_search_closure": public_search,
        "partial_capabilities": partials,
        "next_actions": _next_actions(partials, public_search=public_search),
        "closure_decision": {
            "current_round_closed": True,
            "closure_mode": "public_search_exhausted_with_source_derived_functional_closure",
            "development_blocked": False,
            "full_parity_claim_blocked": not can_close_full_parity,
            "reason": (
                "No new redistributable public raw/settings/Full_Output bundle is ready to register. "
                "The remaining work stays visible as partial capabilities while engineering can proceed "
                "using the accepted official LI-COR anchor, source-derived conformance fixtures, and NEON engineering validation."
            ),
        },
        "truthfulness_note": (
            "This artifact closes the current search/engineering round, not the full EddyPro parity claim. "
            "Partial capabilities remain partial until real raw data, EddyPro settings, official outputs, "
            "normalization provenance, raw-to-final parity, and acceptance evidence pass together."
        ),
        "known_limitations": [
            "Source-derived fixtures prove software conformance paths but are not field-data substitutes.",
            "NEON HDF5 validation is real EC data engineering evidence, not EddyPro raw-to-final parity.",
            "Public search ledgers can change; rerun discovery before promoting any candidate.",
            "Hardware-dependent SmartFlux, GPS/PTP, and LI-7700 behavior still need device or field evidence for certification claims.",
        ],
    }


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value not in (None, "") else Path.cwd().resolve()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _capability_rows(*, matrix: dict[str, Any], coverage_audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(coverage_audit.get("capability_rows", []) or [])
    if rows:
        return [dict(row or {}) for row in rows]
    return [
        {
            "id": str(item.get("id", "")),
            "family": str(item.get("family", "")),
            "gas_ec_status": str(item.get("gas_ec_status", "")),
            "eddypro_requirement": str(item.get("eddypro_requirement", "")),
            "gap": str(item.get("gap", "")),
            "next_action": str(item.get("next_action", "")),
            "evidence": list(item.get("evidence", []) or []),
            "coverage_checklist": list(item.get("coverage_checklist", []) or []),
        }
        for item in list(matrix.get("capabilities", []) or [])
        if isinstance(item, dict)
    ]


def _source_derived_functional_parity(
    matrix: dict[str, Any],
    coverage_audit: dict[str, Any],
    release_gate: dict[str, Any],
) -> bool:
    if "can_release_source_derived_functional_parity" in release_gate:
        return bool(release_gate.get("can_release_source_derived_functional_parity", False))
    if "can_claim_source_derived_functional_parity" in coverage_audit:
        return bool(coverage_audit.get("can_claim_source_derived_functional_parity", False))
    policy = dict(matrix.get("surrogate_evidence_closure_policy", {}) or {})
    return str(policy.get("status", "")).lower() in {"accepted", "approved", "pass", "validated"}


def _discover_neon_validation(root: Path, preferred_path: Path) -> dict[str, Any]:
    if preferred_path.exists():
        return _read_json(preferred_path)
    candidates = sorted(
        (path for path in root.glob("artifacts/**/neon_hdf5_validation_package*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return _read_json(candidates[0]) if candidates else {}


def _discover_public_raw_sample_validation(root: Path, preferred_path: Path) -> dict[str, Any]:
    if preferred_path.exists():
        return _read_json(preferred_path)
    candidates = sorted(
        (
            path
            for path in root.glob("artifacts/**/public_raw_sample_validation_package*.json")
            if path.is_file()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return _read_json(candidates[0]) if candidates else {}


def _accepted_official_anchor(*, root: Path, release_gate: dict[str, Any]) -> dict[str, Any]:
    summary = dict(release_gate.get("official_raw_closure_run_summary", {}) or {})
    closure = dict(release_gate.get("official_raw_closure_run", {}) or {})
    if not closure:
        closure = _discover_official_raw_closure_run(root)
    if not summary and closure:
        summary = {
            "status": closure.get("status", ""),
            "gate_status": closure.get("gate_status", ""),
            "fixture_id": closure.get("fixture_id", ""),
            "raw_to_final_parity_status": closure.get("raw_to_final_parity_status", ""),
            "pass_rate": closure.get("pass_rate", 0.0),
            "acceptance_status": closure.get("acceptance_status", ""),
            "acceptance_gate_status": closure.get("acceptance_gate_status", ""),
        }
    gate_status = str(summary.get("gate_status", closure.get("gate_status", "")) or "")
    status = str(summary.get("status", closure.get("status", "")) or "")
    return {
        "status": status or "not_available",
        "gate_status": gate_status or "not_available",
        "fixture_id": str(summary.get("fixture_id", closure.get("fixture_id", "")) or ""),
        "raw_to_final_parity_status": str(
            summary.get("raw_to_final_parity_status", closure.get("raw_to_final_parity_status", "")) or ""
        ),
        "pass_rate": float(summary.get("pass_rate", closure.get("pass_rate", 0.0)) or 0.0),
        "acceptance_status": str(summary.get("acceptance_status", closure.get("acceptance_status", "")) or ""),
        "acceptance_gate_status": str(
            summary.get("acceptance_gate_status", closure.get("acceptance_gate_status", "")) or ""
        ),
        "artifact": str(closure.get("source_artifact", closure.get("artifact", closure.get("closure_run_artifact", ""))) or ""),
        "is_accepted": status == "pass" and gate_status == "pass",
    }


def _discover_official_raw_closure_run(root: Path) -> dict[str, Any]:
    candidates: list[tuple[int, float, Path, dict[str, Any]]] = []
    for pattern in (
        "artifacts/eddypro_public_raw/*official_raw_closure*.json",
        "artifacts/eddypro_release_gate/*official_raw_closure*.json",
        "artifacts/**/official_raw_closure*.json",
    ):
        for path in root.glob(pattern):
            payload = _read_json(path)
            if str(payload.get("artifact_type", "")) != "official_raw_closure_run_v1":
                continue
            score = 0
            if payload.get("status") == "pass":
                score += 10
            if payload.get("gate_status") == "pass":
                score += 10
            if payload.get("acceptance_gate_status") == "pass":
                score += 5
            try:
                modified = path.stat().st_mtime
            except OSError:
                modified = 0.0
            payload.setdefault("artifact", str(path))
            candidates.append((score, modified, path, payload))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    payload = dict(candidates[0][3])
    payload.setdefault("source_artifact", str(candidates[0][2]))
    return payload


def _public_search_closure(*, raw_search: dict[str, Any], ec_sources: dict[str, Any]) -> dict[str, Any]:
    sources = [dict(item or {}) for item in list(ec_sources.get("sources", []) or []) if isinstance(item, dict)]
    ready_sources = [
        item
        for item in sources
        if str(item.get("registration_outcome", "")).lower()
        in {"ready_to_register", "ready_for_registration", "downloaded_ready_for_registration"}
    ]
    accepted_sources = [
        item
        for item in sources
        if str(item.get("registration_outcome", "")).lower() in {"registered_and_accepted", "accepted"}
    ]
    blocked_sources = [
        {
            "source_id": str(item.get("source_id", "")),
            "provider": str(item.get("provider", "")),
            "registration_outcome": str(item.get("registration_outcome", "")),
            "access_status": str(item.get("access_status", "")),
            "parity_value": str(item.get("parity_value", "")),
            "registration_readiness": _source_registration_readiness(item),
            "next_action": str(item.get("next_action", "")),
            "known_limitations": list(item.get("known_limitations", []) or []),
        }
        for item in sources
        if item not in ready_sources and item not in accepted_sources
    ]
    return {
        "status": "ready_candidate_found" if ready_sources else "no_new_registerable_public_raw_bundle_found",
        "ready_to_register_public_raw_candidate_count": len(ready_sources),
        "accepted_public_anchor_count": len(accepted_sources),
        "blocked_or_nonpromoted_source_count": len(blocked_sources),
        "real_raw_without_eddypro_pair_count": sum(
            1
            for item in blocked_sources
            if bool(dict(item.get("registration_readiness", {}) or {}).get("has_raw_input", False))
            and bool(dict(item.get("registration_readiness", {}) or {}).get("missing_requirements", []))
        ),
        "public_raw_binary_search_status": str(dict(raw_search.get("search_status", {}) or {}).get("status", "")),
        "public_raw_binary_lead_count": int(raw_search.get("lead_count", 0) or 0),
        "public_raw_binary_raw_to_final_candidate_count": int(raw_search.get("raw_to_final_candidate_count", 0) or 0),
        "public_raw_binary_can_support_full_claim": bool(
            raw_search.get("can_support_full_raw_to_final_eddypro_claim", False)
        ),
        "promotion_blockers": list(raw_search.get("promotion_blockers", []) or []),
        "ready_sources": [
            {
                "source_id": str(item.get("source_id", "")),
                "provider": str(item.get("provider", "")),
                "source_url": str(item.get("source_url", "")),
                "next_action": str(item.get("next_action", "")),
            }
            for item in ready_sources
        ],
        "accepted_sources": [
            {
                "source_id": str(item.get("source_id", "")),
                "provider": str(item.get("provider", "")),
                "source_url": str(item.get("source_url", "")),
                "parity_value": str(item.get("parity_value", "")),
            }
            for item in accepted_sources
        ],
        "blocked_sources": blocked_sources,
        "truthfulness_boundary": str(
            ec_sources.get(
                "truthfulness_boundary",
                "Public discovery does not change full parity without raw/settings/output registration and acceptance.",
            )
        ),
    }


def _source_registration_readiness(source: dict[str, Any]) -> dict[str, Any]:
    declared = dict(source.get("registration_evidence", {}) or {})
    parity_value = str(source.get("parity_value", "")).lower()
    if parity_value.startswith(("real_raw", "real_high_frequency_raw", "real_large_high_frequency_raw")):
        declared.setdefault("raw_input", True)
    if str(source.get("registration_outcome", "")) == "registered_and_accepted":
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
    missing = [key for key, value in required.items() if not value]
    status = "registered_and_accepted" if str(source.get("registration_outcome", "")) == "registered_and_accepted" else "ready_to_register" if not missing else "blocked_missing_registration_evidence"
    return {
        "status": status,
        "has_raw_input": required["raw_input"],
        "missing_requirements": missing,
    }


def _neon_summary(neon: dict[str, Any]) -> dict[str, Any]:
    claim = dict(neon.get("claim_boundary", {}) or {})
    return {
        "status": str(neon.get("status", "not_available") or "not_available"),
        "source_id": str(neon.get("source_id", "")),
        "source_file": str(neon.get("source_file", "")),
        "metadata_status": str(neon.get("metadata_status", "")),
        "row_status": str(neon.get("row_status", "")),
        "rp_status": str(neon.get("rp_status", "")),
        "row_count": int(neon.get("row_count", 0) or 0),
        "rp_window_count": int(neon.get("rp_window_count", 0) or 0),
        "can_claim_neon_engineering_validation": bool(claim.get("can_claim_neon_engineering_validation", False)),
        "can_claim_eddypro_raw_to_final_parity": bool(claim.get("can_claim_eddypro_raw_to_final_parity", False)),
        "warning_codes": list(neon.get("warning_codes", []) or []),
    }


def _public_raw_sample_summary(package: dict[str, Any]) -> dict[str, Any]:
    claim = dict(package.get("claim_boundary", {}) or {})
    return {
        "status": str(package.get("status", "not_available") or "not_available"),
        "source_id": str(package.get("source_id", "")),
        "source_file": str(package.get("source_file", "")),
        "importer_status": str(package.get("importer_status", "")),
        "rp_status": str(package.get("rp_status", "")),
        "row_count": int(package.get("row_count", 0) or 0),
        "loaded_row_count": int(package.get("loaded_row_count", 0) or 0),
        "rp_window_count": int(package.get("rp_window_count", 0) or 0),
        "raw_format": str(package.get("raw_format", "")),
        "can_claim_public_raw_engineering_validation": bool(
            claim.get("can_claim_public_raw_engineering_validation", False)
        ),
        "can_claim_eddypro_raw_to_final_parity": bool(claim.get("can_claim_eddypro_raw_to_final_parity", False)),
        "can_release_full_eddypro_parity": bool(claim.get("can_release_full_eddypro_parity", False)),
    }


def _partial_capability_record(
    row: dict[str, Any],
    *,
    accepted_anchor: dict[str, Any],
    raw_search: dict[str, Any],
    public_search: dict[str, Any],
    neon: dict[str, Any],
    public_raw_sample: dict[str, Any],
) -> dict[str, Any]:
    capability_id = str(row.get("id", ""))
    open_items = [
        dict(item or {})
        for item in list(row.get("coverage_checklist", []) or [])
        if str(dict(item or {}).get("status", "")).lower() not in {"done", "covered", "complete", "pass", "validated"}
    ]
    closure_status = _closure_status_for_capability(
        capability_id,
        accepted_anchor=accepted_anchor,
        raw_search=raw_search,
        public_search=public_search,
        neon=neon,
        public_raw_sample=public_raw_sample,
    )
    return {
        "id": capability_id,
        "family": str(row.get("family", "")),
        "gas_ec_status": str(row.get("gas_ec_status", "")),
        "closure_status": closure_status,
        "eddypro_requirement": str(row.get("eddypro_requirement", "")),
        "gap": str(row.get("gap", "")),
        "next_action": str(row.get("next_action", "")),
        "evidence": list(row.get("evidence", []) or []),
        "open_checklist_count": len(open_items),
        "open_checklist": [
            {
                "id": str(item.get("id", "")),
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "blocker": str(item.get("blocker", "")),
            }
            for item in open_items
        ],
    }


def _closure_status_for_capability(
    capability_id: str,
    *,
    accepted_anchor: dict[str, Any],
    raw_search: dict[str, Any],
    public_search: dict[str, Any],
    neon: dict[str, Any],
    public_raw_sample: dict[str, Any],
) -> str:
    if capability_id == "raw_ghg_real_world_fixture_breadth":
        if str(public_raw_sample.get("status", "")) == "pass":
            return "public_raw_sample_engineering_validated_registration_pending"
        return "accepted_official_anchor_plus_breadth_pending" if accepted_anchor.get("is_accepted") else "needs_official_raw_anchor"
    if capability_id == "raw_binary_tob1_slt":
        if public_search.get("ready_to_register_public_raw_candidate_count", 0):
            return "public_candidate_ready_for_registration"
        if raw_search.get("source_derived_fallbacks"):
            return "source_derived_binary_conformance_closed_real_fixture_pending"
        return "real_binary_fixture_pending"
    if capability_id in {"gps_ptp_sync", "smartflux_realtime_site_processing"}:
        return "software_path_closed_real_hardware_pending"
    if capability_id == "ch4_trace_gas_fluxes":
        if str(neon.get("status", "")) == "pass":
            return "trace_gas_software_path_closed_real_li7700_raw_to_final_pending"
        return "real_li7700_raw_to_final_fixture_pending"
    return "partial_real_evidence_pending"


def _next_actions(partials: list[dict[str, Any]], *, public_search: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if public_search.get("ready_to_register_public_raw_candidate_count", 0):
        actions.append(
            {
                "priority": "P0",
                "action": "Promote ready public raw candidate through raw/settings/output registration and acceptance.",
                "capability_ids": [str(item.get("id", "")) for item in partials],
            }
        )
    else:
        actions.append(
            {
                "priority": "P0",
                "action": "Keep full EddyPro parity blocked; no new public raw/settings/Full_Output bundle is ready to register.",
                "capability_ids": [str(item.get("id", "")) for item in partials],
            }
        )
    for item in partials[:8]:
        next_action = str(item.get("next_action", "")).strip()
        if not next_action:
            continue
        actions.append(
            {
                "priority": "P1" if str(item.get("family", "")) in {"raw_ingestion", "fluxes"} else "P2",
                "capability_id": str(item.get("id", "")),
                "action": next_action,
                "closure_status": str(item.get("closure_status", "")),
            }
        )
    return actions
