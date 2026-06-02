from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.comparison.eddypro_coverage_audit import DEFAULT_CAPABILITY_MATRIX_PATH


CORE_COMPUTATION_FAMILIES = {
    "preprocessing",
    "fluxes",
    "spectral",
    "uncertainty",
    "footprint",
}
SUPPORTING_COMPUTATION_FAMILIES = {
    "raw_ingestion",
    "metadata",
    "instrumentation",
    "outputs",
}
NON_COMPUTATIONAL_FAMILIES = {
    "acquisition",
    "benchmark",
    "beyond_eddypro",
}
IMPLEMENTED_STATUSES = {"covered", "beyond_eddypro", "complete", "implemented", "pass"}
EVIDENCE_ONLY_STATUSES = {"needs_real_fixture", "needs_hardware", "needs_official_output"}
DONE_STATUSES = {"done", "covered", "complete", "pass", "validated"}


def build_eddypro_computation_scope_audit(
    *,
    capability_matrix_path: str | Path | None = None,
    coverage_audit: dict[str, Any] | None = None,
    computation_stress_suite: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Separate EC computation blockers from full EddyPro software-surface blockers.

    This artifact is intentionally narrower than the full EddyPro release gate:
    it answers whether gas_ec_studio's computation engine can be treated as
    source-derived computationally ready while keeping official field numeric
    parity and hardware/GUI/breadth claims separate.
    """

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    matrix_path = _resolve(root, capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH)
    matrix, matrix_errors = _read_matrix(matrix_path)
    rows = [
        _scope_row(dict(item or {}), coverage_audit=coverage_audit or {})
        for item in list(matrix.get("capabilities", []) or [])
        if isinstance(item, dict)
    ]
    core_rows = [row for row in rows if row["scope_category"] == "calculation_core"]
    supporting_rows = [row for row in rows if row["scope_category"] == "calculation_supporting"]
    deferred_rows = [row for row in rows if row["scope_category"] == "non_computational_deferrable"]
    core_algorithm_blockers = [
        row for row in core_rows if not row["algorithm_ready_for_source_derived_claim"]
    ]
    supporting_algorithm_blockers = [
        row
        for row in supporting_rows
        if row["calculation_relevance"] == "required_supporting_io"
        and not row["algorithm_ready_for_source_derived_claim"]
    ]
    evidence_pending_rows = [
        row for row in rows if row["evidence_pending_count"] > 0 and row["algorithm_ready_for_source_derived_claim"]
    ]
    status_counts = Counter(row["scope_category"] for row in rows)
    computation_ready = not core_algorithm_blockers and not supporting_algorithm_blockers
    source_functional_ok = bool((coverage_audit or {}).get("can_claim_source_derived_functional_parity", True))
    stress_suite_gate = _stress_suite_gate(computation_stress_suite)
    stress_suite_ok = (
        not stress_suite_gate["supplied"]
        or stress_suite_gate["status"] == "pass"
    )
    can_claim_source_derived = computation_ready and source_functional_ok and not matrix_errors and stress_suite_ok
    return {
        "artifact_type": "eddypro_computation_scope_audit_v1",
        "audit_id": "eddypro_computation_scope_audit_v1",
        "generated_at": datetime.now().isoformat(),
        "status": (
            "source_derived_computation_ready_real_evidence_pending"
            if can_claim_source_derived
            else "computation_scope_blocked"
        ),
        "workspace_root": str(root),
        "capability_matrix_path": str(matrix_path),
        "matrix_errors": matrix_errors,
        "scope_summary": {
            "total_capability_count": len(rows),
            "calculation_core_count": len(core_rows),
            "calculation_supporting_count": len(supporting_rows),
            "non_computational_deferrable_count": len(deferred_rows),
            "core_algorithm_blocker_count": len(core_algorithm_blockers),
            "supporting_algorithm_blocker_count": len(supporting_algorithm_blockers),
            "evidence_pending_count": len(evidence_pending_rows),
            "stress_suite_status": stress_suite_gate["status"],
            "stress_suite_failed_case_count": stress_suite_gate["failed_case_count"],
            "scope_category_counts": dict(sorted(status_counts.items())),
        },
        "computation_stress_suite_gate": stress_suite_gate,
        "claim_boundary": {
            "can_claim_source_derived_computational_superiority": can_claim_source_derived,
            "can_claim_full_eddypro_software_parity": False,
            "can_claim_official_field_numeric_parity": False,
            "can_ignore_non_computational_blockers_for_computation_claim": True,
            "requires_computation_stress_suite_pass_for_exported_claim": True,
            "requires_official_raw_to_final_evidence_for_numeric_claim": True,
        },
        "discard_policy": {
            "policy": "defer_or_exclude_from_computation_gate_not_delete",
            "deferrable_scope_categories": ["non_computational_deferrable"],
            "deferrable_examples": [
                "SmartFlux target-host deployment and service management",
                "GPS/PTP hardware fixture breadth when timestamps are already valid",
                "GUI workflow parity and cloud delivery cosmetics",
                "Additional raw dialect breadth when a compatible importer path already exists",
            ],
            "never_discard_for_computation": [
                "coordinate rotation and planar fit",
                "time lag compensation",
                "statistical screening and QC",
                "density/WPL or mixing-ratio corrections",
                "CO2/H2O/CH4/energy/momentum flux corrections",
                "spectral corrections, spectra/cospectra/ogives",
                "random uncertainty",
                "footprint",
            ],
        },
        "core_algorithm_blockers": core_algorithm_blockers,
        "supporting_algorithm_blockers": supporting_algorithm_blockers,
        "evidence_pending_rows": evidence_pending_rows,
        "deferred_non_computational_rows": deferred_rows,
        "rows": rows,
        "next_actions": _next_actions(
            can_claim_source_derived=can_claim_source_derived,
            core_algorithm_blockers=core_algorithm_blockers,
            supporting_algorithm_blockers=supporting_algorithm_blockers,
            evidence_pending_rows=evidence_pending_rows,
            stress_suite_gate=stress_suite_gate,
        ),
        "truthfulness_boundary": (
            "This audit evaluates EC computation readiness, not full EddyPro software parity. "
            "It can exclude non-computational blockers from the computation claim, but official "
            "field numeric parity still requires real raw-to-final EddyPro evidence."
        ),
        "source_basis": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_gui_repository": "https://github.com/LI-COR-Environmental/eddypro-gui",
            "eddypro_engine_readme_processing_options": "Axis rotation, detrending, lag, statistical tests, density correction, spectral correction, QC, random uncertainty, footprint, and outputs.",
        },
    }


def _scope_row(capability: dict[str, Any], *, coverage_audit: dict[str, Any]) -> dict[str, Any]:
    capability_id = str(capability.get("id", ""))
    family = str(capability.get("family", "") or "unclassified")
    status = str(capability.get("gas_ec_status", "") or "unknown")
    checklist = [dict(item or {}) for item in list(capability.get("coverage_checklist", capability.get("subprogress", [])) or [])]
    evidence_blockers = [
        item for item in checklist if str(item.get("status", "")) in EVIDENCE_ONLY_STATUSES
    ]
    implementation_blockers = [
        item
        for item in checklist
        if str(item.get("status", "")) not in DONE_STATUSES
        and str(item.get("status", "")) not in EVIDENCE_ONLY_STATUSES
    ]
    category, relevance = _scope_category(capability_id=capability_id, family=family)
    algorithm_ready = _algorithm_ready(
        status=status,
        category=category,
        relevance=relevance,
        implementation_blockers=implementation_blockers,
    )
    coverage_row = _coverage_row(coverage_audit, capability_id)
    return {
        "id": capability_id,
        "family": family,
        "title": str(capability.get("title", capability.get("label", capability_id))),
        "eddypro_requirement": str(capability.get("eddypro_requirement", "")),
        "gas_ec_status": status,
        "scope_category": category,
        "calculation_relevance": relevance,
        "algorithm_ready_for_source_derived_claim": algorithm_ready,
        "evidence_pending_count": len(evidence_blockers),
        "implementation_blocker_count": len(implementation_blockers),
        "evidence_pending_items": [_item_summary(item) for item in evidence_blockers],
        "implementation_blockers": [_item_summary(item) for item in implementation_blockers],
        "can_defer_for_computation_claim": category == "non_computational_deferrable"
        or relevance in {"validation_breadth", "hardware_runtime", "gui_or_delivery"},
        "coverage_audit_status": str(coverage_row.get("gas_ec_status", status)),
        "next_action": _row_next_action(
            category=category,
            relevance=relevance,
            algorithm_ready=algorithm_ready,
            evidence_blockers=evidence_blockers,
            default=str(capability.get("next_action", "")),
        ),
    }


def _scope_category(*, capability_id: str, family: str) -> tuple[str, str]:
    if family in CORE_COMPUTATION_FAMILIES:
        return "calculation_core", "required_algorithm"
    if capability_id in {"biomet_external_and_ghg", "dynamic_metadata", "site_instrument_metadata", "ygas_primary_analyzer"}:
        return "calculation_supporting", "required_supporting_metadata"
    if capability_id in {"raw_ghg_bundle", "raw_ascii_csv"}:
        return "calculation_supporting", "required_supporting_io"
    if capability_id in {"raw_ghg_real_world_fixture_breadth", "raw_binary_tob1_slt"}:
        return "calculation_supporting", "validation_breadth"
    if family in SUPPORTING_COMPUTATION_FAMILIES:
        return "calculation_supporting", "supporting"
    if capability_id in {"gps_ptp_sync", "smartflux_realtime_site_processing"}:
        return "non_computational_deferrable", "hardware_runtime"
    if family in NON_COMPUTATIONAL_FAMILIES:
        return "non_computational_deferrable", "gui_or_delivery"
    return "non_computational_deferrable", "not_required_for_ec_calculation"


def _algorithm_ready(
    *,
    status: str,
    category: str,
    relevance: str,
    implementation_blockers: list[dict[str, Any]],
) -> bool:
    if category == "non_computational_deferrable":
        return True
    if relevance == "validation_breadth":
        return True
    if implementation_blockers:
        return False
    return status in IMPLEMENTED_STATUSES or status == "partial"


def _row_next_action(
    *,
    category: str,
    relevance: str,
    algorithm_ready: bool,
    evidence_blockers: list[dict[str, Any]],
    default: str,
) -> str:
    if category == "non_computational_deferrable":
        return "Do not block computational superiority on this item; defer unless deployment parity is required."
    if relevance == "validation_breadth":
        return "Keep expanding fixtures opportunistically, but do not block computation claims on this breadth item."
    if algorithm_ready and evidence_blockers:
        return "Algorithm path is ready; add official/anonymized field evidence when available for numeric parity."
    if algorithm_ready:
        return default or "Keep regression tests passing and add stress cases."
    return default or "Implement missing computation logic before claiming computation readiness."


def _next_actions(
    *,
    can_claim_source_derived: bool,
    core_algorithm_blockers: list[dict[str, Any]],
    supporting_algorithm_blockers: list[dict[str, Any]],
    evidence_pending_rows: list[dict[str, Any]],
    stress_suite_gate: dict[str, Any],
) -> list[str]:
    if not can_claim_source_derived:
        blockers = core_algorithm_blockers + supporting_algorithm_blockers
        if stress_suite_gate.get("supplied") and stress_suite_gate.get("status") != "pass":
            return [
                f"Close computation stress failure: {item.get('case_id')} ({item.get('family')})."
                for item in list(stress_suite_gate.get("failed_cases", []) or [])[:8]
            ] or ["Resolve computation stress suite failures before claiming computation readiness."]
        return [
            f"Close computation blocker: {row.get('id')} ({row.get('calculation_relevance')})."
            for row in blockers[:8]
        ] or ["Resolve capability matrix or coverage audit load errors."]
    actions = [
        "Treat non-computational blockers as deferred for the computation-superiority gate.",
        "Keep official field numeric parity blocked until complete EddyPro raw/settings/Full_Output evidence exists.",
    ]
    if evidence_pending_rows:
        actions.append(
            "Prioritize real evidence where it can improve numeric parity or fixture breadth: "
            + ", ".join(str(row.get("id", "")) for row in evidence_pending_rows[:6])
            + "."
        )
    if stress_suite_gate.get("supplied"):
        actions.append("Keep expanding synthetic/source-derived stress tests as new computation families land.")
    else:
        actions.append("Run the computation stress suite before publishing an exported computation-superiority claim.")
    return actions


def _stress_suite_gate(computation_stress_suite: dict[str, Any] | None) -> dict[str, Any]:
    suite = dict(computation_stress_suite or {})
    if not suite:
        return {
            "supplied": False,
            "status": "not_supplied",
            "case_count": 0,
            "passed_case_count": 0,
            "failed_case_count": 0,
            "pass_rate": 0.0,
            "failed_cases": [],
            "can_support_source_derived_computation_stress": False,
        }
    failed_cases = [
        {
            "case_id": str(item.get("case_id", "")),
            "family": str(item.get("family", "")),
            "failure_reasons": list(item.get("failure_reasons", []) or []),
        }
        for item in list(suite.get("failed_cases", []) or [])
        if isinstance(item, dict)
    ]
    status = str(suite.get("status", "") or "unknown")
    return {
        "supplied": True,
        "artifact_type": str(suite.get("artifact_type", "")),
        "suite_id": str(suite.get("suite_id", "")),
        "status": status,
        "case_count": int(suite.get("case_count", 0) or 0),
        "passed_case_count": int(suite.get("passed_case_count", 0) or 0),
        "failed_case_count": int(suite.get("failed_case_count", len(failed_cases)) or 0),
        "pass_rate": float(suite.get("pass_rate", 0.0) or 0.0),
        "failed_cases": failed_cases,
        "can_support_source_derived_computation_stress": status == "pass",
    }


def _coverage_row(coverage_audit: dict[str, Any], capability_id: str) -> dict[str, Any]:
    for item in list(coverage_audit.get("capability_rows", []) or []):
        row = dict(item or {})
        if str(row.get("id", "")) == capability_id:
            return row
    return {}


def _item_summary(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(item.get("id", "")),
        "label": str(item.get("label", "")),
        "status": str(item.get("status", "")),
        "blocker": str(item.get("blocker", "")),
    }


def _read_matrix(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists() or not path.is_file():
        return {"capabilities": []}, [f"capability matrix missing: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"capabilities": []}, [f"capability matrix invalid: {exc}"]
    return payload if isinstance(payload, dict) else {"capabilities": []}, []


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path
