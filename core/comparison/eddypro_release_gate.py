from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.comparison.eddypro_coverage_audit import (
    DEFAULT_CAPABILITY_MATRIX_PATH,
    build_eddypro_coverage_audit,
)
from core.comparison.eddypro_computation_scope_audit import build_eddypro_computation_scope_audit
from core.comparison.eddypro_computation_stress_suite import build_eddypro_computation_stress_suite
from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
from core.comparison.fixture_pack import (
    DEFAULT_FIXTURE_PACK_PATH,
    build_fixture_pack_summary,
    build_official_raw_fixture_manifest,
)
from core.comparison.official_raw_fixture_bundle import (
    build_official_raw_fixture_evidence_pack,
    run_official_raw_evidence_pack_acceptance,
)


def build_eddypro_release_gate(
    *,
    capability_matrix_path: str | Path | None = None,
    fixture_pack_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    official_raw_bundle_dir: str | Path | None = None,
    official_raw_evidence_pack_path: str | Path | None = None,
    official_raw_evidence_pack: dict[str, Any] | None = None,
    official_raw_closure_run_path: str | Path | None = None,
    official_raw_closure_run: dict[str, Any] | None = None,
    fixture_summary: dict[str, Any] | None = None,
    official_raw_manifest: dict[str, Any] | None = None,
    source_inventory: dict[str, Any] | None = None,
    coverage_audit: dict[str, Any] | None = None,
    computation_scope_audit_path: str | Path | None = None,
    computation_scope_audit: dict[str, Any] | None = None,
    computation_stress_suite_path: str | Path | None = None,
    computation_stress_suite: dict[str, Any] | None = None,
    build_computation_gate: bool = False,
    output_dir: str | Path | None = None,
    run_acceptance: bool = True,
    acceptance_timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Build the machine-readable release gate for EddyPro parity claims."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    out_dir = Path(output_dir) if output_dir not in (None, "") else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}
    closure_run = _load_closure_run(
        official_raw_closure_run=official_raw_closure_run,
        official_raw_closure_run_path=official_raw_closure_run_path,
        workspace_root=root,
    )
    closure_summary = _closure_run_summary(closure_run)
    evidence_pack_was_requested = (
        official_raw_evidence_pack is not None
        or official_raw_evidence_pack_path not in (None, "")
        or official_raw_bundle_dir not in (None, "")
        or bool(closure_run)
    )
    evidence_pack = _load_or_build_evidence_pack(
        official_raw_evidence_pack=official_raw_evidence_pack,
        official_raw_evidence_pack_path=official_raw_evidence_pack_path,
        official_raw_closure_run=closure_run,
        official_raw_bundle_dir=official_raw_bundle_dir,
        workspace_root=root,
    )
    if out_dir is not None and closure_run:
        closure_path = out_dir / "official_raw_closure_run.json"
        _write_json(closure_path, closure_run)
        artifacts["official_raw_closure_run"] = str(closure_path)
    if out_dir is not None and evidence_pack:
        evidence_path = out_dir / "official_raw_evidence_pack.json"
        _write_json(evidence_path, evidence_pack)
        artifacts["official_raw_evidence_pack"] = str(evidence_path)
        if run_acceptance:
            accepted_path = out_dir / "official_raw_evidence_pack.accepted.json"
            _write_json(accepted_path, evidence_pack)
            evidence_pack = run_official_raw_evidence_pack_acceptance(
                accepted_path,
                workspace_root=root,
                timeout_s=acceptance_timeout_s,
                write_back=True,
            )
            artifacts["accepted_official_raw_evidence_pack"] = str(accepted_path)
    elif evidence_pack and run_acceptance:
        evidence_pack = run_official_raw_evidence_pack_acceptance(
            evidence_pack,
            workspace_root=root,
            timeout_s=acceptance_timeout_s,
            write_back=False,
        )

    pack_path = _resolve(root, fixture_pack_path or DEFAULT_FIXTURE_PACK_PATH)
    summary = (
        deepcopy(dict(fixture_summary))
        if fixture_summary is not None
        else build_fixture_pack_summary(pack_path, workspace_root=root)
    )
    official_manifest = (
        deepcopy(dict(official_raw_manifest))
        if official_raw_manifest is not None
        else build_official_raw_fixture_manifest(
            pack_path,
            workspace_root=root,
            fixture_summary=summary,
        )
    )
    source = deepcopy(dict(source_inventory)) if source_inventory is not None else build_eddypro_source_inventory()
    coverage_audit = (
        deepcopy(dict(coverage_audit))
        if coverage_audit is not None
        else build_eddypro_coverage_audit(
            capability_matrix_path=capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH,
            fixture_pack_path=pack_path,
            workspace_root=root,
            fixture_summary=summary,
            official_raw_manifest=official_manifest,
            official_raw_evidence_pack=evidence_pack if (evidence_pack or evidence_pack_was_requested) else None,
            source_inventory=source,
        )
    )
    if out_dir is not None:
        coverage_path = out_dir / "eddypro_coverage_audit.json"
        _write_json(coverage_path, coverage_audit)
        artifacts["eddypro_coverage_audit"] = str(coverage_path)
    computation_suite = _load_computation_stress_suite(
        computation_stress_suite=computation_stress_suite,
        computation_stress_suite_path=computation_stress_suite_path,
        build_when_missing=bool(build_computation_gate),
        workspace_root=root,
    )
    computation_audit = _load_or_build_computation_scope_audit(
        computation_scope_audit=computation_scope_audit,
        computation_scope_audit_path=computation_scope_audit_path,
        computation_stress_suite=computation_suite,
        coverage_audit=coverage_audit,
        build_when_missing=bool(build_computation_gate),
        workspace_root=root,
    )
    if out_dir is not None and computation_suite:
        computation_suite_path = out_dir / "eddypro_computation_stress_suite.json"
        _write_json(computation_suite_path, computation_suite)
        artifacts["eddypro_computation_stress_suite"] = str(computation_suite_path)
    if out_dir is not None and computation_audit:
        computation_audit_path = out_dir / "eddypro_computation_scope_audit.json"
        _write_json(computation_audit_path, computation_audit)
        artifacts["eddypro_computation_scope_audit"] = str(computation_audit_path)

    claim_gate = dict(coverage_audit.get("claim_gate", {}) or {})
    acceptance = dict(coverage_audit.get("official_raw_acceptance_summary", {}) or {})
    closure_gate = dict(coverage_audit.get("closure_gate", {}) or {})
    surrogate_closure = dict(coverage_audit.get("surrogate_evidence_closure", {}) or {})
    closure_blockers = _closure_run_blocking_reasons(closure_summary)
    blocking_reasons = _dedupe(
        [
            *list(claim_gate.get("blocking_reasons", []) or []),
            *closure_blockers,
        ]
    )
    surrogate_release_pass = str(surrogate_closure.get("gate_status", surrogate_closure.get("status", ""))) == "pass"
    computation_release_gate = _computation_release_gate(
        computation_scope_audit=computation_audit,
        computation_stress_suite=computation_suite,
    )
    computation_release_pass = bool(
        computation_release_gate.get("can_release_source_derived_computational_superiority", False)
    )
    computation_gate_supplied = bool(computation_audit or computation_suite)
    open_source_code_blocking_reasons: list[str] = []
    if not bool(coverage_audit.get("can_claim_open_source_code_capability_parity", False)):
        open_source_code_blocking_reasons.extend(
            list(dict(coverage_audit.get("open_source_code_claim_gate", {}) or {}).get("blocking_reasons", []) or [])
            or ["open-source code capability coverage audit has not passed"]
        )
    if not surrogate_release_pass:
        open_source_code_blocking_reasons.append("source-derived functional conformance gate has not passed")
    if computation_gate_supplied and not computation_release_pass:
        open_source_code_blocking_reasons.extend(
            f"source-derived computation gate: {reason}"
            for reason in list(computation_release_gate.get("blocking_reasons", []) or [])
        )
    open_source_code_blocking_reasons = _dedupe(open_source_code_blocking_reasons)
    open_source_code_release_pass = not open_source_code_blocking_reasons
    if computation_gate_supplied and not computation_release_pass:
        blocking_reasons = _dedupe(
            [
                *blocking_reasons,
                *[
                    f"source-derived computation gate: {reason}"
                    for reason in list(computation_release_gate.get("blocking_reasons", []) or [])
                ],
            ]
        )
    release_pass = (
        bool(coverage_audit.get("can_claim_full_eddypro_parity", False))
        and not closure_blockers
        and (not computation_gate_supplied or computation_release_pass)
    )
    return {
        "artifact_type": "eddypro_release_gate_v1",
        "gate_id": "eddypro_release_gate_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if release_pass else "blocked",
        "ci_exit_code": 0 if release_pass else 2,
        "can_release_full_eddypro_parity": release_pass,
        "open_source_code_capability_status": "pass" if open_source_code_release_pass else "blocked",
        "open_source_code_capability_ci_exit_code": 0 if open_source_code_release_pass else 2,
        "can_release_open_source_code_capability_parity": open_source_code_release_pass,
        "open_source_code_capability_blocking_reasons": open_source_code_blocking_reasons,
        "surrogate_evidence_closure_status": str(surrogate_closure.get("status", "not_configured")),
        "surrogate_ci_exit_code": 0 if surrogate_release_pass else 2,
        "can_release_source_derived_functional_parity": surrogate_release_pass,
        "source_derived_computation_ci_exit_code": 0 if computation_release_pass else 2,
        "can_release_source_derived_computational_superiority": computation_release_pass,
        "workspace_root": str(root),
        "inputs": {
            "capability_matrix_path": str(_resolve(root, capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH)),
            "fixture_pack_path": str(pack_path),
            "official_raw_bundle_dir": str(official_raw_bundle_dir or ""),
            "official_raw_evidence_pack_path": str(official_raw_evidence_pack_path or ""),
            "official_raw_closure_run_path": str(official_raw_closure_run_path or ""),
            "computation_scope_audit_path": str(computation_scope_audit_path or ""),
            "computation_stress_suite_path": str(computation_stress_suite_path or ""),
            "build_computation_gate": bool(build_computation_gate),
            "run_acceptance": bool(run_acceptance),
            "acceptance_timeout_s": float(acceptance_timeout_s),
        },
        "summary": {
            "claim_gate_status": str(claim_gate.get("status", "")),
            "blocking_reasons": blocking_reasons,
            "closure_gate_status": str(closure_gate.get("status", "")),
            "closure_open_item_count": int(closure_gate.get("open_item_count", 0) or 0),
            "surrogate_evidence_closure_status": str(surrogate_closure.get("status", "not_configured")),
            "surrogate_evidence_closure_gate_status": str(
                surrogate_closure.get("gate_status", surrogate_closure.get("status", "not_configured"))
            ),
            "can_claim_source_derived_functional_parity": bool(
                coverage_audit.get("can_claim_source_derived_functional_parity", False)
            ),
            "can_claim_open_source_code_capability_parity": bool(
                coverage_audit.get("can_claim_open_source_code_capability_parity", False)
            ),
            "can_release_open_source_code_capability_parity": open_source_code_release_pass,
            "open_source_code_capability_status": "pass" if open_source_code_release_pass else "blocked",
            "open_source_code_capability_blocking_reasons": open_source_code_blocking_reasons,
            "code_capability_completion_score": float(
                dict(coverage_audit.get("code_capability_summary", {}) or {}).get("completion_score", 0.0) or 0.0
            ),
            "code_capability_evidence_pending_ids": list(
                dict(coverage_audit.get("code_capability_summary", {}) or {}).get(
                    "evidence_pending_capability_ids", []
                )
                or []
            ),
            "can_release_source_derived_functional_parity": surrogate_release_pass,
            "can_release_source_derived_computational_superiority": computation_release_pass,
            "source_derived_computation_gate_status": str(computation_release_gate.get("status", "not_supplied")),
            "source_derived_computation_blocking_reasons": list(
                computation_release_gate.get("blocking_reasons", []) or []
            ),
            "computation_scope_audit_status": str(computation_release_gate.get("computation_scope_audit_status", "")),
            "computation_stress_suite_status": str(computation_release_gate.get("computation_stress_suite_status", "")),
            "computation_surface_status": str(computation_release_gate.get("computation_surface_status", "")),
            "computation_surface_ready_family_count": int(
                computation_release_gate.get("computation_surface_ready_family_count", 0) or 0
            ),
            "computation_surface_blocked_family_count": int(
                computation_release_gate.get("computation_surface_blocked_family_count", 0) or 0
            ),
            "surrogate_accepted_item_count": int(surrogate_closure.get("accepted_item_count", 0) or 0),
            "surrogate_missing_item_count": int(surrogate_closure.get("missing_item_count", 0) or 0),
            "surrogate_failed_external_check_count": int(surrogate_closure.get("failed_external_check_count", 0) or 0),
            "official_raw_closure_run_status": str(closure_summary.get("status", "not_available")),
            "official_raw_closure_run_gate_status": str(closure_summary.get("gate_status", "not_available")),
            "official_raw_closure_run_fixture_id": str(closure_summary.get("fixture_id", "")),
            "official_raw_closure_run_parity_status": str(closure_summary.get("raw_to_final_parity_status", "")),
            "official_raw_closure_run_pass_rate": float(closure_summary.get("pass_rate", 0.0) or 0.0),
            "official_raw_closure_run_acceptance_status": str(closure_summary.get("acceptance_status", "")),
            "official_raw_closure_run_acceptance_gate_status": str(closure_summary.get("acceptance_gate_status", "")),
            "official_raw_closure_run_blockers": list(closure_summary.get("blockers", []) or []),
            "official_raw_acceptance_status": str(acceptance.get("status", "not_run")),
            "official_raw_acceptance_gate_status": str(acceptance.get("gate_status", "not_run")),
            "official_raw_acceptance_command_count": int(acceptance.get("command_count", 0) or 0),
            "official_eddypro_run_status": str(acceptance.get("official_eddypro_run_status", "not_available")),
            "official_eddypro_run_gate_status": str(acceptance.get("official_eddypro_run_gate_status", "blocked")),
            "official_eddypro_software_version": str(acceptance.get("official_eddypro_software_version", "")),
            "official_eddypro_run_command": str(acceptance.get("official_eddypro_run_command", "")),
            "official_raw_to_final_ready_count": int(official_manifest.get("official_raw_to_final_ready_count", 0) or 0),
            "capability_completion_score": float(
                dict(coverage_audit.get("capability_summary", {}) or {}).get("completion_score", 0.0) or 0.0
            ),
            "source_inventory_status": str(dict(coverage_audit.get("source_inventory_summary", {}) or {}).get("status", "")),
            "fixture_pack_status": str(summary.get("status", "")),
        },
        "artifacts": artifacts,
        "coverage_audit": coverage_audit,
        "computation_release_gate": computation_release_gate,
        "computation_scope_audit": computation_audit,
        "computation_stress_suite": computation_suite,
        "surrogate_evidence_closure": surrogate_closure,
        "official_raw_closure_run": closure_run,
        "official_raw_closure_run_summary": closure_summary,
        "official_raw_evidence_pack": evidence_pack,
        "truthfulness_note": (
            "This release gate intentionally blocks full EddyPro parity release claims unless coverage audit, "
            "official raw fixture readiness, official EddyPro executable-run provenance, source provenance, "
            "and evidence-pack acceptance all pass. Source-derived functional parity has a separate surrogate "
            "evidence gate. Open-source code capability parity combines source-surface coverage, source-derived "
            "functional conformance, and the computation gate without requiring unavailable field or hardware data; "
            "it must not be described as official field numeric parity or vendor certification."
        ),
    }


def _load_or_build_evidence_pack(
    *,
    official_raw_evidence_pack: dict[str, Any] | None,
    official_raw_evidence_pack_path: str | Path | None,
    official_raw_closure_run: dict[str, Any] | None,
    official_raw_bundle_dir: str | Path | None,
    workspace_root: Path,
) -> dict[str, Any]:
    if official_raw_evidence_pack is not None:
        return deepcopy(dict(official_raw_evidence_pack))
    if official_raw_evidence_pack_path not in (None, ""):
        return _read_json(Path(official_raw_evidence_pack_path))
    closure_pack = _evidence_pack_from_closure_run(official_raw_closure_run, workspace_root=workspace_root)
    if closure_pack:
        return closure_pack
    if official_raw_bundle_dir not in (None, ""):
        return build_official_raw_fixture_evidence_pack(
            official_raw_bundle_dir,
            workspace_root=workspace_root,
        )
    return {}


def _load_computation_stress_suite(
    *,
    computation_stress_suite: dict[str, Any] | None,
    computation_stress_suite_path: str | Path | None,
    build_when_missing: bool,
    workspace_root: Path,
) -> dict[str, Any]:
    if computation_stress_suite is not None:
        return deepcopy(dict(computation_stress_suite))
    if computation_stress_suite_path not in (None, ""):
        return _read_json(Path(computation_stress_suite_path))
    if build_when_missing:
        return build_eddypro_computation_stress_suite(workspace_root=workspace_root)
    return {}


def _load_or_build_computation_scope_audit(
    *,
    computation_scope_audit: dict[str, Any] | None,
    computation_scope_audit_path: str | Path | None,
    computation_stress_suite: dict[str, Any],
    coverage_audit: dict[str, Any],
    build_when_missing: bool,
    workspace_root: Path,
) -> dict[str, Any]:
    if computation_scope_audit is not None:
        return deepcopy(dict(computation_scope_audit))
    if computation_scope_audit_path not in (None, ""):
        return _read_json(Path(computation_scope_audit_path))
    if build_when_missing or computation_stress_suite:
        return build_eddypro_computation_scope_audit(
            workspace_root=workspace_root,
            coverage_audit=coverage_audit,
            computation_stress_suite=computation_stress_suite or None,
        )
    return {}


def _computation_release_gate(
    *,
    computation_scope_audit: dict[str, Any],
    computation_stress_suite: dict[str, Any],
) -> dict[str, Any]:
    scope = dict(computation_scope_audit or {})
    suite = dict(computation_stress_suite or {})
    stress_gate = dict(scope.get("computation_stress_suite_gate", {}) or {})
    surface = dict(suite.get("computation_surface", {}) or {})
    claim_boundary = dict(scope.get("claim_boundary", {}) or {})
    scope_ready = bool(claim_boundary.get("can_claim_source_derived_computational_superiority", False))
    suite_supplied = bool(suite)
    suite_status = str(suite.get("status", stress_gate.get("status", "not_supplied")) or "not_supplied")
    surface_status = str(surface.get("status", "not_supplied" if not suite_supplied else "unknown"))
    blocking_reasons: list[str] = []
    if not scope:
        blocking_reasons.append("computation scope audit not supplied")
    elif not scope_ready:
        blocking_reasons.append(f"computation scope audit is not claim-ready: {scope.get('status', 'unknown')}")
    if not suite_supplied:
        blocking_reasons.append("computation stress suite not supplied")
    elif suite_status != "pass":
        blocking_reasons.append(f"computation stress suite status is {suite_status}")
    if suite_supplied and surface_status != "ready":
        blocking_reasons.append(f"computation surface status is {surface_status}")
    can_release = not blocking_reasons
    return {
        "artifact_type": "source_derived_computation_release_gate_v1",
        "status": "pass" if can_release else ("not_supplied" if not scope and not suite_supplied else "blocked"),
        "can_release_source_derived_computational_superiority": can_release,
        "ci_exit_code": 0 if can_release else 2,
        "blocking_reasons": blocking_reasons,
        "computation_scope_audit_status": str(scope.get("status", "not_supplied")),
        "computation_stress_suite_status": suite_status,
        "computation_surface_status": surface_status,
        "computation_surface_ready_family_count": int(surface.get("ready_family_count", 0) or 0),
        "computation_surface_blocked_family_count": int(surface.get("blocked_family_count", 0) or 0),
        "computation_surface_required_families": list(surface.get("required_families", []) or []),
        "computation_surface_family_status": dict(surface.get("family_status", {}) or {}),
        "truthfulness_boundary": (
            "This gate only releases a source-derived EC computation-superiority claim. It does not release "
            "official field numeric parity, vendor certification, or full EddyPro software parity."
        ),
    }


def _load_closure_run(
    *,
    official_raw_closure_run: dict[str, Any] | None,
    official_raw_closure_run_path: str | Path | None,
    workspace_root: Path,
) -> dict[str, Any]:
    if official_raw_closure_run is not None:
        return deepcopy(dict(official_raw_closure_run))
    if official_raw_closure_run_path not in (None, ""):
        return _read_json(Path(official_raw_closure_run_path))
    discovered = _discover_official_raw_closure_run(workspace_root)
    if discovered:
        return discovered
    return {}


def _discover_official_raw_closure_run(root: Path) -> dict[str, Any]:
    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for path in _official_raw_closure_candidate_paths(root):
        payload = _read_json(path)
        if str(payload.get("artifact_type", "")) != "official_raw_closure_run_v1":
            continue
        payload.setdefault("artifact", _display_path(root, path))
        payload.setdefault("discovery_source", "auto_discovered_standard_artifact")
        try:
            modified_at = path.stat().st_mtime
        except OSError:
            modified_at = 0.0
        candidates.append((_official_raw_closure_score(payload), modified_at, payload))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return dict(candidates[0][2])


def _official_raw_closure_candidate_paths(root: Path) -> list[Path]:
    patterns = [
        "artifacts/eddypro_public_raw/*official_raw_closure*.json",
        "artifacts/eddypro_release_gate/*official_raw_closure*.json",
        "artifacts/**/official_raw_closure*.json",
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


def _official_raw_closure_score(payload: dict[str, Any]) -> int:
    score = 0
    if str(payload.get("gate_status", "")) == "pass":
        score += 100
    if str(payload.get("status", "")) == "pass":
        score += 40
    if str(payload.get("raw_to_final_parity_status", "")) == "pass":
        score += 30
    if str(payload.get("acceptance_gate_status", "")) == "pass":
        score += 20
    if str(payload.get("official_eddypro_run_gate_status", "")) == "pass":
        score += 20
    if float(payload.get("pass_rate", 0.0) or 0.0) >= 1.0:
        score += 10
    if dict(payload.get("evidence_pack", {}) or {}).get("artifact_type") == "official_raw_fixture_evidence_pack_v1":
        score += 5
    return score


def _evidence_pack_from_closure_run(
    closure_run: dict[str, Any] | None,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    closure = dict(closure_run or {})
    pack = dict(closure.get("evidence_pack", {}) or {})
    if pack:
        return pack
    artifact = str(closure.get("evidence_pack_artifact", "") or "")
    if not artifact:
        return {}
    path = _resolve(workspace_root, artifact)
    return _read_json(path)


def _closure_run_summary(closure_run: dict[str, Any] | None) -> dict[str, Any]:
    closure = dict(closure_run or {})
    if not closure:
        return {
            "artifact_type": "official_raw_closure_run_summary_v1",
            "status": "not_available",
            "gate_status": "not_available",
            "blockers": [],
        }
    return {
        "artifact_type": "official_raw_closure_run_summary_v1",
        "status": str(closure.get("status", "")),
        "gate_status": str(closure.get("gate_status", "")),
        "fixture_id": str(closure.get("fixture_id", "")),
        "bundle_root": str(closure.get("bundle_root", "")),
        "registered_pack_path": str(closure.get("registered_pack_path", "")),
        "evidence_pack_artifact": str(closure.get("evidence_pack_artifact", "")),
        "manifest_status": str(closure.get("manifest_status", "")),
        "registration_status": str(closure.get("registration_status", "")),
        "raw_to_final_parity_status": str(closure.get("raw_to_final_parity_status", "")),
        "pass_rate": float(closure.get("pass_rate", 0.0) or 0.0),
        "failed_fields": list(closure.get("failed_fields", []) or []),
        "official_eddypro_run_status": str(closure.get("official_eddypro_run_status", "")),
        "official_eddypro_run_gate_status": str(closure.get("official_eddypro_run_gate_status", "")),
        "acquisition_status": str(closure.get("acquisition_status", "")),
        "acquisition_gate_status": str(closure.get("acquisition_gate_status", "")),
        "acceptance_status": str(closure.get("acceptance_status", "")),
        "acceptance_gate_status": str(closure.get("acceptance_gate_status", "")),
        "blockers": list(closure.get("blockers", []) or []),
    }


def _closure_run_blocking_reasons(summary: dict[str, Any]) -> list[str]:
    if str(summary.get("status", "")) == "not_available":
        return []
    reasons: list[str] = []
    if str(summary.get("gate_status", "")) != "pass":
        reasons.append(
            "official raw closure run has not passed "
            f"(status={summary.get('status', 'not_available')}, gate={summary.get('gate_status', 'blocked')})"
        )
    blockers = [str(item) for item in list(summary.get("blockers", []) or []) if str(item).strip()]
    if blockers:
        reasons.append(f"official raw closure run blockers: {', '.join(blockers)}")
    return _dedupe(reasons)


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(items: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))
