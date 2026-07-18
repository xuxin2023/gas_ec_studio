from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
from core.comparison.fixture_pack import (
    DEFAULT_FIXTURE_PACK_PATH,
    build_fixture_pack_summary,
    build_official_raw_fixture_manifest,
)


DEFAULT_CAPABILITY_MATRIX_PATH = Path("docs/benchmark/eddypro_capability_matrix.json")
STATUS_WEIGHTS = {
    "covered": 1.0,
    "partial": 0.5,
    "missing": 0.0,
    "beyond_eddypro": 1.0,
}
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SUBPROGRESS_DONE_STATUSES = {"done", "covered", "complete", "pass", "validated"}
SUBPROGRESS_BLOCKED_STATUSES = {"blocked", "missing", "needs_real_fixture", "needs_hardware", "needs_official_output"}
SURROGATE_ACCEPTED_STATUSES = {"accepted", "approved", "closed", "pass", "validated"}


def build_eddypro_coverage_audit(
    *,
    capability_matrix_path: str | Path | None = None,
    fixture_pack_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    fixture_summary: dict[str, Any] | None = None,
    official_raw_manifest: dict[str, Any] | None = None,
    official_raw_evidence_pack: dict[str, Any] | None = None,
    source_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single truthfulness gate for EddyPro parity claims.

    The artifact joins the static capability matrix, official source inventory,
    and fixture registry evidence so delivery packages can make the same claim
    consistently: implemented breadth is not the same thing as official
    raw-to-final numerical parity.
    """

    root = _workspace_root(workspace_root)
    matrix_path = _resolve(root, capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH)
    matrix, matrix_errors = _load_capability_matrix(matrix_path)
    capabilities = [dict(item or {}) for item in list(matrix.get("capabilities", []) or [])]
    rows = _capability_rows(capabilities)
    status_counts = Counter(str(row.get("gas_ec_status", "") or "unknown") for row in rows)
    source_payload = dict(source_inventory or build_eddypro_source_inventory())
    pack_path = _resolve(root, fixture_pack_path or DEFAULT_FIXTURE_PACK_PATH)
    summary_payload = (
        dict(fixture_summary)
        if fixture_summary is not None
        else build_fixture_pack_summary(pack_path, workspace_root=root)
    )
    official_payload = (
        dict(official_raw_manifest)
        if official_raw_manifest is not None
        else build_official_raw_fixture_manifest(
            pack_path,
            workspace_root=root,
            fixture_summary=summary_payload,
        )
    )
    evidence_pack_payload = (
        dict(official_raw_evidence_pack)
        if official_raw_evidence_pack is not None
        else _discover_official_raw_evidence_pack(root)
    )
    capability_summary = _capability_summary(rows, status_counts)
    capability_subprogress = _capability_subprogress_summary(rows)
    family_summary = _family_summary(rows)
    source_summary = _source_summary(source_payload)
    acceptance_summary = _official_raw_acceptance_summary(evidence_pack_payload)
    fixture_summary_small = _fixture_evidence_summary(summary_payload, official_payload, acceptance_summary)
    gaps = _gap_items(rows, summary_payload, official_payload, source_payload, acceptance_summary)
    closure_gate = _closure_gate(gaps)
    closure_plan = _closure_plan(closure_gate)
    surrogate_closure = _surrogate_evidence_closure_gate(
        policy=matrix.get("surrogate_evidence_closure_policy", {}),
        capability_rows=rows,
        fixture_evidence_summary=fixture_summary_small,
        source_summary=source_summary,
        acceptance_summary=acceptance_summary,
    )
    blocking_reasons = _blocking_reasons(
        capability_summary=capability_summary,
        fixture_summary=summary_payload,
        official_raw_manifest=official_payload,
        source_summary=source_summary,
        acceptance_summary=acceptance_summary,
        matrix_errors=matrix_errors,
    )
    can_claim_full_parity = not blocking_reasons
    return {
        "artifact_type": "eddypro_coverage_audit_v1",
        "audit_id": "eddypro_coverage_audit_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "full_eddypro_parity_evidence_ready" if can_claim_full_parity else "not_full_eddypro_parity_yet",
        "can_claim_full_eddypro_parity": can_claim_full_parity,
        "can_claim_source_derived_functional_parity": surrogate_closure.get("status") == "pass",
        "claim_gate": {
            "status": "pass" if can_claim_full_parity else "blocked",
            "blocking_reasons": blocking_reasons,
            "closure_gate_status": closure_gate["status"],
            "closure_open_item_count": closure_gate["open_item_count"],
            "surrogate_evidence_closure_status": surrogate_closure.get("status", "not_configured"),
            "required_evidence": [
                "No EddyPro capability rows remain partial or missing.",
                "At least one official raw-to-final fixture has raw input, EddyPro settings, official output, normalized reference, provenance, and passing parity.",
                "The official EddyPro source inventory is present and feature anchors are found.",
                "The active fixture pack validates without errors.",
                "The official EddyPro executable run provenance is present and has exit_code=0.",
                "The official raw evidence pack acceptance commands have run and passed.",
            ],
        },
        "capability_matrix": {
            "path": str(matrix_path),
            "artifact_type": str(matrix.get("artifact_type", "")),
            "updated_at": str(matrix.get("updated_at", "")),
            "overall_status": str(matrix.get("overall_status", "")),
            "coverage_summary_declared": dict(matrix.get("coverage_summary", {}) or {}),
            "load_errors": matrix_errors,
        },
        "capability_summary": capability_summary,
        "capability_subprogress": capability_subprogress,
        "family_summary": family_summary,
        "source_inventory_summary": source_summary,
        "fixture_evidence_summary": fixture_summary_small,
        "official_raw_acceptance_summary": acceptance_summary,
        "gap_summary": {
            "gap_count": len(gaps),
            "capability_gap_count": sum(1 for item in gaps if item.get("source") == "capability_matrix"),
            "fixture_gap_count": sum(1 for item in gaps if item.get("source") == "fixture_pack"),
            "source_gap_count": sum(1 for item in gaps if item.get("source") == "source_inventory"),
            "top_gaps": gaps[:20],
        },
        "closure_gate": closure_gate,
        "closure_plan": closure_plan,
        "surrogate_evidence_closure": surrogate_closure,
        "capability_rows": rows,
        "truthfulness_note": (
            "This audit is a claim gate, not a marketing score. It keeps full EddyPro parity blocked "
            "until implementation breadth, official source anchors, and official raw-to-final fixture evidence all pass together."
        ),
        "known_limitations": [
            "Capability status comes from the local docs/benchmark capability matrix and must be reviewed when upstream EddyPro changes.",
            "Source inventory checks module/file/token presence; it does not execute EddyPro.",
            "Fixture evidence is only as strong as the registered raw bundles and their provenance.",
            "Evidence-pack acceptance status must be refreshed after any source, fixture, reference, or processing change.",
        ],
    }


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value not in (None, "") else Path.cwd()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_capability_matrix(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists() or not path.is_file():
        return {"capabilities": []}, [f"capability matrix missing: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"capabilities": []}, [f"capability matrix invalid: {exc}"]
    if not isinstance(payload, dict):
        return {"capabilities": []}, ["capability matrix root is not an object"]
    return payload, []


def _discover_official_raw_evidence_pack(root: Path) -> dict[str, Any]:
    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for path in _official_raw_evidence_candidate_paths(root):
        payload = _read_json_if_possible(path)
        pack = _official_raw_evidence_pack_from_payload(payload, root=root)
        if not pack:
            continue
        pack.setdefault("artifact", _display_path(root, path))
        pack.setdefault("discovery_source", "auto_discovered_standard_artifact")
        try:
            modified_at = path.stat().st_mtime
        except OSError:
            modified_at = 0.0
        candidates.append((_official_raw_evidence_pack_score(pack), modified_at, pack))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return dict(candidates[0][2])


def _official_raw_evidence_candidate_paths(root: Path) -> list[Path]:
    patterns = [
        "artifacts/eddypro_public_raw/*official_raw_evidence_pack*.json",
        "artifacts/eddypro_public_raw/*evidence_pack*.json",
        "artifacts/eddypro_public_raw/*official_raw_closure*.json",
        "artifacts/eddypro_release_gate/*official_raw_evidence_pack*.json",
        "artifacts/eddypro_release_gate/*official_raw_closure*.json",
        "artifacts/**/official_raw_evidence_pack*.json",
        "artifacts/**/*official_raw_closure*.json",
    ]
    paths: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return paths


def _official_raw_evidence_pack_from_payload(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    artifact_type = str(payload.get("artifact_type", ""))
    if artifact_type == "official_raw_fixture_evidence_pack_v1":
        return dict(payload)
    if artifact_type == "official_raw_closure_run_v1":
        embedded = dict(payload.get("evidence_pack", {}) or {})
        if embedded.get("artifact_type") == "official_raw_fixture_evidence_pack_v1":
            return embedded
        artifact = str(payload.get("evidence_pack_artifact", "") or "")
        if artifact:
            pack = _read_json_if_possible(_resolve(root, artifact))
            if pack.get("artifact_type") == "official_raw_fixture_evidence_pack_v1":
                pack.setdefault("closure_run_artifact", artifact)
                return pack
    return {}


def _official_raw_evidence_pack_score(pack: dict[str, Any]) -> int:
    run = dict(pack.get("official_eddypro_run", {}) or {})
    acceptance_run = dict(pack.get("acceptance_run", {}) or {})
    score = 0
    if str(pack.get("acceptance_gate_status", acceptance_run.get("gate_status", ""))) == "pass":
        score += 100
    if str(pack.get("acceptance_status", acceptance_run.get("status", ""))) == "pass":
        score += 20
    if str(run.get("gate_status", "")) == "pass":
        score += 50
    if str(run.get("status", "")) == "pass":
        score += 10
    if str(pack.get("status", "")) == "complete":
        score += 10
    return score


def _read_json_if_possible(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _capability_rows(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capability in capabilities:
        status = str(capability.get("gas_ec_status", "") or "unknown")
        evidence = [str(item) for item in list(capability.get("evidence", []) or []) if str(item).strip()]
        checklist = _normalize_capability_checklist(capability.get("coverage_checklist", capability.get("subprogress", [])))
        subprogress = _capability_row_subprogress(checklist)
        rows.append(
            {
                "id": str(capability.get("id", "")),
                "family": str(capability.get("family", "") or "unclassified"),
                "gas_ec_status": status,
                "status_score": float(STATUS_WEIGHTS.get(status, 0.0)),
                "eddypro_requirement": str(capability.get("eddypro_requirement", "")),
                "gap": str(capability.get("gap", "")),
                "next_action": str(capability.get("next_action", "")),
                "evidence": evidence,
                "evidence_count": len(evidence),
                "test_evidence_count": sum(1 for item in evidence if item.replace("\\", "/").startswith("tests/")),
                "fixture_evidence_count": sum(1 for item in evidence if "references/eddypro" in item.replace("\\", "/")),
                "source_inventory_evidence_count": sum(
                    1
                    for item in evidence
                    if "eddypro_source_inventory" in item or "eddypro_capability_matrix" in item
                ),
                "coverage_checklist": checklist,
                "subprogress": subprogress,
                "blocks_full_parity_claim": status in {"partial", "missing", "unknown"},
            }
        )
    return rows


def _capability_summary(rows: list[dict[str, Any]], status_counts: Counter[str]) -> dict[str, Any]:
    eddypro_rows = [row for row in rows if row.get("gas_ec_status") != "beyond_eddypro"]
    denominator = len(eddypro_rows)
    weighted = sum(float(row.get("status_score", 0.0) or 0.0) for row in eddypro_rows)
    return {
        "total_capability_count": len(rows),
        "eddypro_capability_count": denominator,
        "covered_count": int(status_counts.get("covered", 0)),
        "partial_count": int(status_counts.get("partial", 0)),
        "missing_count": int(status_counts.get("missing", 0)),
        "beyond_eddypro_count": int(status_counts.get("beyond_eddypro", 0)),
        "unknown_count": int(status_counts.get("unknown", 0)),
        "completion_score": weighted / denominator if denominator else 0.0,
        "status_counts": dict(sorted(status_counts.items())),
    }


def _capability_subprogress_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    partial_rows = [row for row in rows if row.get("gas_ec_status") == "partial"]
    subprogress_rows: list[dict[str, Any]] = []
    total_items = 0
    done_items = 0
    blocked_items = 0
    for row in partial_rows:
        checklist = list(row.get("coverage_checklist", []) or [])
        summary = dict(row.get("subprogress", {}) or {})
        total_items += int(summary.get("total_count", 0) or 0)
        done_items += int(summary.get("done_count", 0) or 0)
        blocked_items += int(summary.get("blocked_count", 0) or 0)
        subprogress_rows.append(
            {
                "id": str(row.get("id", "")),
                "family": str(row.get("family", "")),
                "total_count": int(summary.get("total_count", 0) or 0),
                "done_count": int(summary.get("done_count", 0) or 0),
                "open_count": int(summary.get("open_count", 0) or 0),
                "blocked_count": int(summary.get("blocked_count", 0) or 0),
                "completion_ratio": float(summary.get("completion_ratio", 0.0) or 0.0),
                "done_items": [
                    str(item.get("id", item.get("label", "")))
                    for item in checklist
                    if _subprogress_item_done(item)
                ],
                "open_items": [
                    str(item.get("id", item.get("label", "")))
                    for item in checklist
                    if not _subprogress_item_done(item)
                ],
                "blocking_items": [
                    str(item.get("id", item.get("label", "")))
                    for item in checklist
                    if _subprogress_item_blocked(item)
                ],
            }
        )
    return {
        "artifact_type": "eddypro_capability_subprogress_v1",
        "claim_safe": True,
        "score_policy": "informational_only_not_used_for_full_parity_claim",
        "partial_capability_count": len(partial_rows),
        "tracked_partial_capability_count": sum(1 for row in subprogress_rows if int(row.get("total_count", 0) or 0) > 0),
        "total_item_count": total_items,
        "done_item_count": done_items,
        "open_item_count": max(0, total_items - done_items),
        "blocked_item_count": blocked_items,
        "completion_ratio": done_items / total_items if total_items else 0.0,
        "rows": subprogress_rows,
    }


def _surrogate_evidence_closure_gate(
    *,
    policy: Any,
    capability_rows: list[dict[str, Any]],
    fixture_evidence_summary: dict[str, Any],
    source_summary: dict[str, Any],
    acceptance_summary: dict[str, Any],
) -> dict[str, Any]:
    policy_payload = dict(policy or {}) if isinstance(policy, dict) else {}
    if not policy_payload:
        return {
            "artifact_type": "eddypro_surrogate_evidence_closure_v1",
            "status": "not_configured",
            "gate_status": "not_configured",
            "can_claim_source_derived_functional_parity": False,
            "surrogate_item_count": 0,
            "accepted_item_count": 0,
            "missing_item_count": 0,
            "truthfulness_note": "No surrogate evidence closure policy was configured.",
        }

    accepted_index = _surrogate_policy_index(policy_payload)
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for row in capability_rows:
        if row.get("gas_ec_status") != "partial":
            continue
        for item in list(row.get("coverage_checklist", []) or []):
            if _subprogress_item_done(item):
                continue
            capability_id = str(row.get("id", ""))
            item_id = str(item.get("id", item.get("label", "")))
            closure = _surrogate_closure_for_item(accepted_index, capability_id=capability_id, item_id=item_id)
            validation = _validate_surrogate_closure(closure)
            entry = {
                "capability_id": capability_id,
                "family": str(row.get("family", "")),
                "item_id": item_id,
                "original_status": str(item.get("status", "")),
                "original_blocker": str(item.get("blocker", "")),
                "surrogate_status": validation["status"],
                "closure_type": str(closure.get("closure_type", "")),
                "evidence": list(closure.get("evidence", []) or []),
                "limitations": list(closure.get("limitations", []) or []),
                "rationale": str(closure.get("rationale", "")),
                "missing_requirements": list(validation.get("missing_requirements", []) or []),
            }
            rows.append(entry)
            if validation["status"] == "accepted":
                accepted.append(entry)
            else:
                missing.append(entry)

    policy_status = str(policy_payload.get("status", "not_configured"))
    evidence_checks = _surrogate_external_evidence_checks(
        fixture_evidence_summary=fixture_evidence_summary,
        source_summary=source_summary,
        acceptance_summary=acceptance_summary,
    )
    failed_external = [item for item in evidence_checks if item.get("status") != "pass"]
    status = "pass" if policy_status in SURROGATE_ACCEPTED_STATUSES and not missing and not failed_external else "blocked"
    if not rows:
        status = "not_needed" if policy_status in SURROGATE_ACCEPTED_STATUSES else "not_configured"
    return {
        "artifact_type": "eddypro_surrogate_evidence_closure_v1",
        "status": status,
        "gate_status": "pass" if status in {"pass", "not_needed"} else status,
        "policy_id": str(policy_payload.get("policy_id", "")),
        "policy_status": policy_status,
        "can_claim_source_derived_functional_parity": status in {"pass", "not_needed"},
        "surrogate_item_count": len(rows),
        "accepted_item_count": len(accepted),
        "missing_item_count": len(missing),
        "external_evidence_checks": evidence_checks,
        "failed_external_check_count": len(failed_external),
        "accepted_items": accepted,
        "missing_items": missing,
        "rows": rows,
        "allowed_claims": list(policy_payload.get("allowed_claims", []) or []),
        "blocked_claims": list(policy_payload.get("blocked_claims", []) or ["official_field_numeric_parity"]),
        "truthfulness_note": str(
            policy_payload.get(
                "truthfulness_note",
                "Surrogate evidence can close source-derived functional parity only; it does not create real field golden-output evidence.",
            )
        ),
        "known_limitations": list(policy_payload.get("known_limitations", []) or []),
    }


def _surrogate_policy_index(policy: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for item in list(policy.get("accepted_blockers", []) or []):
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability_id", "") or "")
        item_id = str(item.get("item_id", "") or "")
        if capability_id and item_id:
            index[(capability_id, item_id)] = dict(item)
    return index


def _surrogate_closure_for_item(
    index: dict[tuple[str, str], dict[str, Any]],
    *,
    capability_id: str,
    item_id: str,
) -> dict[str, Any]:
    return dict(index.get((capability_id, item_id), {}) or index.get(("*", item_id), {}) or {})


def _validate_surrogate_closure(closure: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if str(closure.get("status", "")) not in SURROGATE_ACCEPTED_STATUSES:
        missing.append("accepted_status")
    if not list(closure.get("evidence", []) or []):
        missing.append("evidence")
    if not str(closure.get("rationale", "")).strip():
        missing.append("rationale")
    if not list(closure.get("limitations", []) or []):
        missing.append("limitations")
    if not str(closure.get("closure_type", "")).strip():
        missing.append("closure_type")
    return {
        "status": "accepted" if not missing else "missing_requirements",
        "missing_requirements": missing,
    }


def _surrogate_external_evidence_checks(
    *,
    fixture_evidence_summary: dict[str, Any],
    source_summary: dict[str, Any],
    acceptance_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    registered_count = int(fixture_evidence_summary.get("registered_raw_to_final_fixture_count", 0) or 0)
    active_count = int(fixture_evidence_summary.get("raw_to_final_fixture_count", 0) or 0)
    pass_count = int(fixture_evidence_summary.get("raw_to_final_pass_count", 0) or 0)
    source_derived_count = int(dict(fixture_evidence_summary.get("readiness_counts", {}) or {}).get("source_derived_conformance", 0) or 0)
    checks = [
        {
            "check_id": "fixture_pack_status",
            "status": "pass" if str(fixture_evidence_summary.get("fixture_pack_status", "")) == "pass" else "fail",
            "measured": fixture_evidence_summary.get("fixture_pack_status", ""),
            "threshold": "pass",
        },
        {
            "check_id": "source_inventory_status",
            "status": "pass" if str(source_summary.get("status", "")) == "pass" else "fail",
            "measured": source_summary.get("status", ""),
            "threshold": "pass",
        },
        {
            "check_id": "registered_raw_to_final_passes",
            "status": "pass" if active_count > 0 and pass_count >= active_count else "fail",
            "measured": {"registered": registered_count, "active": active_count, "pass": pass_count},
            "threshold": "all active raw-to-final fixtures pass",
        },
        {
            "check_id": "source_derived_conformance_breadth",
            "status": "pass" if source_derived_count >= 5 else "fail",
            "measured": source_derived_count,
            "threshold": ">=5 source-derived conformance fixtures",
        },
        {
            "check_id": "official_raw_acceptance_anchor",
            "status": "pass" if str(acceptance_summary.get("gate_status", "")) == "pass" else "fail",
            "measured": acceptance_summary.get("gate_status", "not_run"),
            "threshold": "at least one accepted official raw evidence anchor",
        },
    ]
    return checks


def _family_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    families: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(str(row.get("family", "") or "unclassified"), []).append(row)
    summary: dict[str, Any] = {}
    for family, items in sorted(families.items()):
        counts = Counter(str(item.get("gas_ec_status", "") or "unknown") for item in items)
        eddypro_items = [item for item in items if item.get("gas_ec_status") != "beyond_eddypro"]
        denominator = len(eddypro_items)
        score = sum(float(item.get("status_score", 0.0) or 0.0) for item in eddypro_items)
        summary[family] = {
            "total": len(items),
            "eddypro_total": denominator,
            "covered": int(counts.get("covered", 0)),
            "partial": int(counts.get("partial", 0)),
            "missing": int(counts.get("missing", 0)),
            "beyond_eddypro": int(counts.get("beyond_eddypro", 0)),
            "completion_score": score / denominator if denominator else 0.0,
            "blocking_capabilities": [
                str(item.get("id", ""))
                for item in items
                if bool(item.get("blocks_full_parity_claim", False))
            ],
            "subprogress_completion_ratio": _family_subprogress_ratio(items),
        }
    return summary


def _normalize_capability_checklist(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []
    items = value if isinstance(value, list) else [value]
    output: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            normalized = {
                "id": str(item.get("id", f"item_{index}") or f"item_{index}"),
                "label": str(item.get("label", item.get("name", item.get("id", f"item_{index}"))) or f"item_{index}"),
                "status": str(item.get("status", "open") or "open"),
                "evidence": [str(entry) for entry in list(item.get("evidence", []) or []) if str(entry).strip()],
                "blocker": str(item.get("blocker", item.get("gap", "")) or ""),
            }
        else:
            normalized = {
                "id": f"item_{index}",
                "label": str(item),
                "status": "open",
                "evidence": [],
                "blocker": "",
            }
        output.append(normalized)
    return output


def _capability_row_subprogress(checklist: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(checklist)
    done = sum(1 for item in checklist if _subprogress_item_done(item))
    blocked = sum(1 for item in checklist if _subprogress_item_blocked(item))
    return {
        "artifact_type": "eddypro_capability_row_subprogress_v1",
        "total_count": total,
        "done_count": done,
        "open_count": max(0, total - done),
        "blocked_count": blocked,
        "completion_ratio": done / total if total else 0.0,
    }


def _subprogress_item_done(item: dict[str, Any]) -> bool:
    return str(item.get("status", "")).strip().lower() in SUBPROGRESS_DONE_STATUSES


def _subprogress_item_blocked(item: dict[str, Any]) -> bool:
    return str(item.get("status", "")).strip().lower() in SUBPROGRESS_BLOCKED_STATUSES


def _family_subprogress_ratio(items: list[dict[str, Any]]) -> float:
    total = sum(int(dict(item.get("subprogress", {}) or {}).get("total_count", 0) or 0) for item in items)
    done = sum(int(dict(item.get("subprogress", {}) or {}).get("done_count", 0) or 0) for item in items)
    return done / total if total else 0.0


def _source_summary(source_inventory: dict[str, Any]) -> dict[str, Any]:
    repositories = dict(source_inventory.get("source_repositories", {}) or {})
    return {
        "inventory_id": str(source_inventory.get("inventory_id", "")),
        "status": str(source_inventory.get("status", "")),
        "feature_count": int(source_inventory.get("feature_count", 0) or 0),
        "present_feature_count": int(source_inventory.get("present_feature_count", 0) or 0),
        "missing_feature_count": int(source_inventory.get("missing_feature_count", 0) or 0),
        "missing_features": list(source_inventory.get("missing_features", []) or []),
        "engine_commit": str(dict(repositories.get("engine", {}) or {}).get("commit", "")),
        "gui_commit": str(dict(repositories.get("gui", {}) or {}).get("commit", "")),
    }


def _official_raw_acceptance_summary(evidence_pack: dict[str, Any] | None) -> dict[str, Any]:
    pack = dict(evidence_pack or {})
    run = dict(pack.get("acceptance_run", {}) or {})
    executable_run = _official_eddypro_executable_summary(pack)
    status = str(pack.get("acceptance_status", run.get("status", "not_run")) or "not_run")
    gate_status = str(pack.get("acceptance_gate_status", run.get("gate_status", "not_run")) or "not_run")
    return {
        "artifact_type": "official_raw_acceptance_claim_gate_summary_v1",
        "status": status,
        "gate_status": gate_status,
        "evidence_pack_status": str(pack.get("status", "not_available") or "not_available"),
        "fixture_id": str(pack.get("fixture_id", "")),
        "artifact": str(pack.get("artifact", "")),
        "command_count": int(run.get("command_count", 0) or 0),
        "passed_count": int(run.get("passed_count", 0) or 0),
        "failed_count": int(run.get("failed_count", 0) or 0),
        "skipped_count": int(run.get("skipped_count", 0) or 0),
        "completed_at": str(pack.get("acceptance_completed_at", run.get("completed_at", "")) or ""),
        "official_eddypro_run": executable_run,
        "official_eddypro_run_status": str(executable_run.get("status", "not_available")),
        "official_eddypro_run_gate_status": str(executable_run.get("gate_status", "blocked")),
        "official_eddypro_software_version": str(executable_run.get("software_version", "")),
        "official_eddypro_run_command": str(executable_run.get("command", "")),
        "required_for_full_parity_claim": True,
    }


def _official_eddypro_executable_summary(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    run = dict(evidence_pack.get("official_eddypro_run", {}) or {})
    if not run:
        return {
            "artifact_type": "official_eddypro_executable_run_v1",
            "status": "not_available",
            "gate_status": "blocked",
            "missing_requirements": ["official_eddypro_run"],
            "truthfulness_note": "No official EddyPro executable run provenance was attached to the evidence pack.",
        }
    gate_status = str(run.get("gate_status", ""))
    status = str(run.get("status", ""))
    if not gate_status:
        gate_status = "pass" if status == "pass" else "blocked"
    run["gate_status"] = gate_status
    run.setdefault("artifact_type", "official_eddypro_executable_run_v1")
    run.setdefault("missing_requirements", [])
    return run


def _fixture_evidence_summary(
    fixture_summary: dict[str, Any],
    official_raw_manifest: dict[str, Any],
    acceptance_summary: dict[str, Any],
) -> dict[str, Any]:
    evidence_matrix = dict(official_raw_manifest.get("evidence_matrix", {}) or {})
    return {
        "fixture_pack_id": str(fixture_summary.get("fixture_pack_id", "")),
        "fixture_pack_version": str(fixture_summary.get("version", "")),
        "fixture_pack_status": str(fixture_summary.get("status", "")),
        "asset_count": int(fixture_summary.get("asset_count", 0) or 0),
        "real_reference_window_count": int(fixture_summary.get("real_reference_window_count", 0) or 0),
        "raw_to_final_fixture_count": int(fixture_summary.get("raw_to_final_fixture_count", 0) or 0),
        "raw_to_final_pass_count": int(fixture_summary.get("raw_to_final_pass_count", 0) or 0),
        "official_raw_fixture_status": str(official_raw_manifest.get("status", "")),
        "official_raw_to_final_ready_count": int(official_raw_manifest.get("official_raw_to_final_ready_count", 0) or 0),
        "registered_raw_to_final_fixture_count": int(official_raw_manifest.get("registered_raw_to_final_fixture_count", 0) or 0),
        "missing_official_bundle_count": int(official_raw_manifest.get("missing_official_bundle_count", 0) or 0),
        "readiness_counts": dict(official_raw_manifest.get("readiness_counts", {}) or {}),
        "raw_format_counts": dict(evidence_matrix.get("raw_format_counts", {}) or {}),
        "site_class_counts": dict(evidence_matrix.get("site_class_counts", {}) or {}),
        "parity_status_counts": dict(evidence_matrix.get("parity_status_counts", {}) or {}),
        "official_raw_acceptance_status": str(acceptance_summary.get("status", "not_run")),
        "official_raw_acceptance_gate_status": str(acceptance_summary.get("gate_status", "not_run")),
        "official_raw_acceptance_command_count": int(acceptance_summary.get("command_count", 0) or 0),
        "official_eddypro_run_status": str(acceptance_summary.get("official_eddypro_run_status", "not_available")),
        "official_eddypro_run_gate_status": str(acceptance_summary.get("official_eddypro_run_gate_status", "blocked")),
        "official_eddypro_software_version": str(acceptance_summary.get("official_eddypro_software_version", "")),
    }


def _gap_items(
    capability_rows: list[dict[str, Any]],
    fixture_summary: dict[str, Any],
    official_raw_manifest: dict[str, Any],
    source_inventory: dict[str, Any],
    acceptance_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for row in capability_rows:
        if not bool(row.get("blocks_full_parity_claim", False)):
            continue
        gaps.append(
            {
                "source": "capability_matrix",
                "id": row.get("id", ""),
                "family": row.get("family", ""),
                "status": row.get("gas_ec_status", ""),
                "eddypro_requirement": row.get("eddypro_requirement", ""),
                "gap": row.get("gap", ""),
                "next_action": row.get("next_action", ""),
                "evidence_count": row.get("evidence_count", 0),
                "test_evidence_count": row.get("test_evidence_count", 0),
                "fixture_evidence_count": row.get("fixture_evidence_count", 0),
                "source_inventory_evidence_count": row.get("source_inventory_evidence_count", 0),
                "subprogress": row.get("subprogress", {}),
                "done_subprogress_items": [
                    item
                    for item in list(row.get("coverage_checklist", []) or [])
                    if _subprogress_item_done(item)
                ],
                "open_subprogress_items": [
                    item
                    for item in list(row.get("coverage_checklist", []) or [])
                    if not _subprogress_item_done(item)
                ],
            }
        )
    for index, gap in enumerate(list(fixture_summary.get("coverage_gaps", []) or []), start=1):
        gaps.append(
            {
                "source": "fixture_pack",
                "id": f"fixture_gap_{index}",
                "family": "benchmark",
                "status": "open",
                "blocks_full_parity": False,
                "gap": str(gap),
                "next_action": "Register an official raw bundle and rerun parity.",
            }
        )
    for feature in list(source_inventory.get("missing_features", []) or []):
        gaps.append(
            {
                "source": "source_inventory",
                "id": str(feature),
                "family": "source_inventory",
                "status": "missing",
                "blocks_full_parity": True,
                "gap": f"Official EddyPro source anchor missing: {feature}",
                "next_action": "Refresh the local EddyPro source clone or update the source inventory map.",
            }
        )
    if int(official_raw_manifest.get("official_raw_to_final_ready_count", 0) or 0) <= 0:
        gaps.append(
            {
                "source": "fixture_pack",
                "id": "official_raw_to_final_ready_count",
                "family": "benchmark",
                "status": "blocked",
                "blocks_full_parity": True,
                "gap": "No official raw-to-final EddyPro fixture is ready.",
                "next_action": "Add an anonymized EddyPro raw bundle with project/settings, Full Output, normalized reference, and provenance.",
            }
        )
    if str(acceptance_summary.get("gate_status", "not_run")) != "pass":
        gaps.append(
            {
                "source": "fixture_pack",
                "id": "official_raw_evidence_pack_acceptance",
                "family": "benchmark",
                "status": str(acceptance_summary.get("status", "not_run")),
                "blocks_full_parity": True,
                "gap": "Official raw evidence pack acceptance commands have not passed.",
                "next_action": "Run the evidence pack acceptance commands and attach the accepted evidence pack artifact.",
                "acceptance_status": str(acceptance_summary.get("status", "not_run")),
                "acceptance_gate_status": str(acceptance_summary.get("gate_status", "not_run")),
            }
        )
    if str(acceptance_summary.get("official_eddypro_run_gate_status", "blocked")) != "pass":
        gaps.append(
            {
                "source": "fixture_pack",
                "id": "official_eddypro_executable_run",
                "family": "benchmark",
                "status": str(acceptance_summary.get("official_eddypro_run_status", "not_available")),
                "blocks_full_parity": True,
                "gap": "Official EddyPro executable run provenance has not passed.",
                "next_action": "Attach official_eddypro_run evidence with software version, command, completed time, exit_code=0, and official output hash.",
                "missing_requirements": list(
                    dict(acceptance_summary.get("official_eddypro_run", {}) or {}).get("missing_requirements", []) or ["official_eddypro_run"]
                ),
            }
        )
    return gaps


def _closure_gate(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    items = [_closure_item(gap) for gap in gaps]
    items = sorted(
        items,
        key=lambda item: (
            PRIORITY_RANK.get(str(item.get("priority", "P3")), 3),
            str(item.get("source", "")),
            str(item.get("id", "")),
        ),
    )
    priority_counts = Counter(str(item.get("priority", "P3")) for item in items)
    open_items = [item for item in items if str(item.get("gate_status", "")) == "open"]
    acceptance_commands = _dedupe(
        command
        for item in open_items
        for command in list(item.get("acceptance_commands", []) or [])
        if str(command).strip()
    )
    required_evidence = _dedupe(
        evidence
        for item in open_items
        for evidence in list(item.get("required_evidence", []) or [])
        if str(evidence).strip()
    )
    return {
        "artifact_type": "eddypro_closure_gate_v1",
        "status": "pass" if not open_items else "blocked",
        "gate_item_count": len(items),
        "open_item_count": len(open_items),
        "closed_item_count": len(items) - len(open_items),
        "top_priority": str(open_items[0].get("priority", "closed")) if open_items else "closed",
        "priority_counts": dict(sorted(priority_counts.items())),
        "blocked_claims": _dedupe(
            claim
            for item in open_items
            for claim in list(item.get("blocked_claims", []) or [])
            if str(claim).strip()
        ),
        "required_evidence": required_evidence,
        "acceptance_commands": acceptance_commands,
        "gate_items": items,
        "truthfulness_note": (
            "Closure gate items are concrete blockers for full EddyPro parity claims. "
            "Closing an item requires evidence plus the listed acceptance tests, not only a UI label or documentation change."
        ),
    }


def _closure_item(gap: dict[str, Any]) -> dict[str, Any]:
    source = str(gap.get("source", "") or "unknown")
    capability_id = str(gap.get("id", "") or source)
    family = str(gap.get("family", "") or "unclassified")
    status = str(gap.get("status", "") or "open")
    priority = _closure_priority(gap)
    required_evidence = _required_evidence_for_gap(gap)
    commands = _acceptance_commands_for_gap(gap)
    return {
        "closure_id": f"{source}:{capability_id}",
        "id": capability_id,
        "source": source,
        "family": family,
        "priority": priority,
        "gate_status": "open" if bool(gap.get("blocks_full_parity", True)) else "advisory",
        "status": status,
        "blocked_claims": _blocked_claims_for_gap(gap),
        "eddypro_requirement": str(gap.get("eddypro_requirement", "")),
        "gap": str(gap.get("gap", "")),
        "next_action": str(gap.get("next_action", "")),
        "required_evidence": required_evidence,
        "acceptance_commands": commands,
        "evidence_shortfall": _evidence_shortfall(gap),
    }


def _closure_plan(closure_gate: dict[str, Any]) -> dict[str, Any]:
    open_items = [
        dict(item or {})
        for item in list(closure_gate.get("gate_items", []) or [])
        if str(dict(item or {}).get("gate_status", "")) == "open"
    ]
    next_items = open_items[:8]
    return {
        "artifact_type": "eddypro_closure_plan_v1",
        "status": "complete" if not open_items else "active",
        "next_priority": str(next_items[0].get("priority", "closed")) if next_items else "closed",
        "next_action_count": len(open_items),
        "next_actions": [
            {
                "closure_id": str(item.get("closure_id", "")),
                "priority": str(item.get("priority", "")),
                "family": str(item.get("family", "")),
                "next_action": str(item.get("next_action", "")),
                "required_evidence": list(item.get("required_evidence", []) or []),
                "acceptance_commands": list(item.get("acceptance_commands", []) or []),
            }
            for item in next_items
        ],
        "acceptance_command_sequence": list(closure_gate.get("acceptance_commands", []) or []),
        "blocked_claims": list(closure_gate.get("blocked_claims", []) or []),
    }


def _closure_priority(gap: dict[str, Any]) -> str:
    source = str(gap.get("source", "") or "")
    status = str(gap.get("status", "") or "")
    gap_id = str(gap.get("id", "") or "")
    if source == "source_inventory" or status in {"missing", "unknown"}:
        return "P0"
    if gap_id == "official_eddypro_executable_run":
        return "P0"
    if gap_id == "official_raw_evidence_pack_acceptance":
        return "P0"
    if gap_id == "official_raw_to_final_ready_count":
        return "P0"
    if source == "fixture_pack":
        return "P0" if "official raw-to-final" in str(gap.get("gap", "")).lower() else "P1"
    if status == "partial":
        return "P1"
    return "P2"


def _required_evidence_for_gap(gap: dict[str, Any]) -> list[str]:
    source = str(gap.get("source", "") or "")
    family = str(gap.get("family", "") or "")
    requirements: list[str]
    if source == "fixture_pack":
        requirements = [
            "official_raw_bundle_manifest",
            "raw_high_frequency_input",
            "eddypro_project_settings",
            "official_eddypro_full_output",
            "official_eddypro_executable_run",
            "normalized_reference_with_provenance",
            "raw_to_final_parity_pass",
        ]
        if str(gap.get("id", "")) == "official_eddypro_executable_run":
            requirements.extend(
                [
                    "official_eddypro_software_version",
                    "official_eddypro_command",
                    "official_eddypro_exit_code_zero",
                    "official_output_hash",
                ]
            )
        if str(gap.get("id", "")) == "official_raw_evidence_pack_acceptance":
            requirements.append("official_raw_evidence_pack_acceptance_run_pass")
    elif source == "source_inventory":
        requirements = [
            "local_eddypro_engine_source_anchor",
            "local_eddypro_gui_source_anchor",
            "source_inventory_feature_present",
        ]
    else:
        requirements = [
            "implemented_feature_path",
            "direct_pytest_coverage",
            "export_or_manifest_evidence",
        ]
        if family in {"raw_ingestion", "benchmark", "trace_gas"}:
            requirements.append("reference_or_fixture_evidence")
        if int(gap.get("test_evidence_count", 0) or 0) <= 0:
            requirements.append("new_direct_test")
        if int(gap.get("fixture_evidence_count", 0) or 0) <= 0 and family in {"raw_ingestion", "benchmark", "trace_gas"}:
            requirements.append("new_eddypro_fixture")
    return _dedupe(requirements)


def _acceptance_commands_for_gap(gap: dict[str, Any]) -> list[str]:
    source = str(gap.get("source", "") or "")
    family = str(gap.get("family", "") or "")
    commands = [
        "python -m pytest tests/test_eddypro_coverage_audit.py tests/test_eddypro_capability_matrix.py -q",
    ]
    if source == "fixture_pack" or family in {"benchmark", "raw_ingestion", "trace_gas"}:
        commands.append(
            "python -m pytest tests/test_official_raw_fixture_bundle.py tests/test_eddypro_fixture_pack.py tests/test_raw_to_final_parity.py -q"
        )
    if str(gap.get("id", "")) == "official_raw_evidence_pack_acceptance":
        commands.append(
            "python -m pytest tests/test_official_raw_fixture_bundle.py::test_run_official_raw_evidence_pack_acceptance_executes_safe_pytest -q"
        )
    if source == "source_inventory":
        commands.append("python -m pytest tests/test_eddypro_source_inventory.py tests/test_eddypro_coverage_audit.py -q")
    if family in {"delivery", "reporting"}:
        commands.append("python -m pytest tests/test_result_exports.py tests/test_delivery_package_export.py tests/test_formal_report_export.py -q")
    return _dedupe(commands)


def _blocked_claims_for_gap(gap: dict[str, Any]) -> list[str]:
    source = str(gap.get("source", "") or "")
    family = str(gap.get("family", "") or "unclassified")
    if source == "fixture_pack":
        return ["official_raw_to_final_numeric_parity", "full_eddypro_parity"]
    if source == "source_inventory":
        return ["source_provenance_completeness", "full_eddypro_parity"]
    return [f"{family}_parity", "full_eddypro_parity"]


def _evidence_shortfall(gap: dict[str, Any]) -> list[str]:
    shortfall: list[str] = []
    if int(gap.get("test_evidence_count", 0) or 0) <= 0 and gap.get("source") == "capability_matrix":
        shortfall.append("test_evidence_missing")
    family = str(gap.get("family", "") or "")
    if family in {"raw_ingestion", "benchmark", "trace_gas"} and int(gap.get("fixture_evidence_count", 0) or 0) <= 0:
        shortfall.append("fixture_evidence_missing")
    if str(gap.get("source", "")) == "fixture_pack":
        shortfall.append("official_raw_bundle_missing_or_not_ready")
    if str(gap.get("source", "")) == "source_inventory":
        shortfall.append("source_anchor_missing")
    return shortfall


def _dedupe(items: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))


def _blocking_reasons(
    *,
    capability_summary: dict[str, Any],
    fixture_summary: dict[str, Any],
    official_raw_manifest: dict[str, Any],
    source_summary: dict[str, Any],
    acceptance_summary: dict[str, Any],
    matrix_errors: list[str],
) -> list[str]:
    reasons: list[str] = []
    if matrix_errors:
        reasons.extend(matrix_errors)
    partial = int(capability_summary.get("partial_count", 0) or 0)
    missing = int(capability_summary.get("missing_count", 0) or 0)
    unknown = int(capability_summary.get("unknown_count", 0) or 0)
    if partial or missing or unknown:
        reasons.append(f"capability matrix still has partial={partial}, missing={missing}, unknown={unknown}")
    if int(official_raw_manifest.get("official_raw_to_final_ready_count", 0) or 0) <= 0:
        reasons.append("no official raw-to-final EddyPro fixture is ready")
    if str(fixture_summary.get("status", "")) != "pass":
        reasons.append(f"fixture pack status is {fixture_summary.get('status', 'unknown')}")
    if str(source_summary.get("status", "")) != "pass":
        reasons.append(f"official source inventory status is {source_summary.get('status', 'unknown')}")
    if int(source_summary.get("missing_feature_count", 0) or 0) > 0:
        reasons.append(f"official source inventory missing features: {', '.join(source_summary.get('missing_features', []) or [])}")
    if str(acceptance_summary.get("gate_status", "not_run")) != "pass":
        reasons.append(
            "official raw evidence pack acceptance has not passed "
            f"(status={acceptance_summary.get('status', 'not_run')})"
        )
    if str(acceptance_summary.get("official_eddypro_run_gate_status", "blocked")) != "pass":
        reasons.append(
            "official EddyPro executable run provenance has not passed "
            f"(status={acceptance_summary.get('official_eddypro_run_status', 'not_available')})"
        )
    return list(dict.fromkeys(str(item) for item in reasons if str(item).strip()))
