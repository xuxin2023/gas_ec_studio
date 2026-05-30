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
    )
    closure_summary = _closure_run_summary(closure_run)
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
            official_raw_evidence_pack=evidence_pack,
            source_inventory=source,
        )
    )
    if out_dir is not None:
        coverage_path = out_dir / "eddypro_coverage_audit.json"
        _write_json(coverage_path, coverage_audit)
        artifacts["eddypro_coverage_audit"] = str(coverage_path)

    claim_gate = dict(coverage_audit.get("claim_gate", {}) or {})
    acceptance = dict(coverage_audit.get("official_raw_acceptance_summary", {}) or {})
    closure_gate = dict(coverage_audit.get("closure_gate", {}) or {})
    closure_blockers = _closure_run_blocking_reasons(closure_summary)
    blocking_reasons = _dedupe(
        [
            *list(claim_gate.get("blocking_reasons", []) or []),
            *closure_blockers,
        ]
    )
    release_pass = bool(coverage_audit.get("can_claim_full_eddypro_parity", False)) and not closure_blockers
    return {
        "artifact_type": "eddypro_release_gate_v1",
        "gate_id": "eddypro_release_gate_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if release_pass else "blocked",
        "ci_exit_code": 0 if release_pass else 2,
        "can_release_full_eddypro_parity": release_pass,
        "workspace_root": str(root),
        "inputs": {
            "capability_matrix_path": str(_resolve(root, capability_matrix_path or DEFAULT_CAPABILITY_MATRIX_PATH)),
            "fixture_pack_path": str(pack_path),
            "official_raw_bundle_dir": str(official_raw_bundle_dir or ""),
            "official_raw_evidence_pack_path": str(official_raw_evidence_pack_path or ""),
            "official_raw_closure_run_path": str(official_raw_closure_run_path or ""),
            "run_acceptance": bool(run_acceptance),
            "acceptance_timeout_s": float(acceptance_timeout_s),
        },
        "summary": {
            "claim_gate_status": str(claim_gate.get("status", "")),
            "blocking_reasons": blocking_reasons,
            "closure_gate_status": str(closure_gate.get("status", "")),
            "closure_open_item_count": int(closure_gate.get("open_item_count", 0) or 0),
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
        "official_raw_closure_run": closure_run,
        "official_raw_closure_run_summary": closure_summary,
        "official_raw_evidence_pack": evidence_pack,
        "truthfulness_note": (
            "This release gate intentionally blocks full EddyPro parity release claims unless coverage audit, "
            "official raw fixture readiness, official EddyPro executable-run provenance, source provenance, "
            "and evidence-pack acceptance all pass."
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


def _load_closure_run(
    *,
    official_raw_closure_run: dict[str, Any] | None,
    official_raw_closure_run_path: str | Path | None,
) -> dict[str, Any]:
    if official_raw_closure_run is not None:
        return deepcopy(dict(official_raw_closure_run))
    if official_raw_closure_run_path not in (None, ""):
        return _read_json(Path(official_raw_closure_run_path))
    return {}


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


def _dedupe(items: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))
