from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from core.comparison.eddypro_release_gate import build_eddypro_release_gate
from core.headless_batch_runner import run_cli


def _write_matrix(path: Path, *, covered: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "updated_at": "2026-05-28",
                "overall_status": "test",
                "coverage_summary": {},
                "capabilities": [
                    {
                        "id": "raw_ghg_bundle",
                        "family": "raw_ingestion",
                        "gas_ec_status": "covered" if covered else "partial",
                        "evidence": ["tests/test_ghg_bundle_import.py"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _fixture_summary() -> dict:
    return {
        "fixture_pack_id": "test_pack",
        "version": "1.0",
        "status": "pass",
        "asset_count": 1,
        "real_reference_window_count": 1,
        "raw_to_final_fixture_count": 1,
        "raw_to_final_pass_count": 1,
        "coverage_gaps": [],
    }


def _official_manifest() -> dict:
    return {
        "status": "ready",
        "official_raw_to_final_ready_count": 1,
        "registered_raw_to_final_fixture_count": 1,
        "missing_official_bundle_count": 0,
        "readiness_counts": {"official_raw_to_final_ready": 1},
        "evidence_matrix": {
            "raw_format_counts": {"ghg": 1},
            "site_class_counts": {"temperate_forest": 1},
            "parity_status_counts": {"pass": 1},
        },
    }


def _source_inventory() -> dict:
    return {
        "inventory_id": "eddypro_official_source_inventory_v1",
        "status": "pass",
        "feature_count": 1,
        "present_feature_count": 1,
        "missing_feature_count": 0,
        "missing_features": [],
        "source_repositories": {
            "engine": {"commit": "engine-commit"},
            "gui": {"commit": "gui-commit"},
        },
    }


def _accepted_pack(status: str = "pass") -> dict:
    return {
        "artifact_type": "official_raw_fixture_evidence_pack_v1",
        "status": "complete" if status == "pass" else "needs_acceptance",
        "fixture_id": "site_001_official",
        "official_eddypro_run": {
            "artifact_type": "official_eddypro_executable_run_v1",
            "status": "pass",
            "gate_status": "pass",
            "software_version": "7.0.9",
            "command": "eddypro.exe --run site_001.eddypro",
            "run_completed_at": "2026-05-28T09:45:00",
            "exit_code": 0,
            "output_files": [{"path": "eddypro_full_output.csv", "sha256": "ABC"}],
            "missing_requirements": [],
        },
        "acceptance_status": status,
        "acceptance_gate_status": "pass" if status == "pass" else "blocked",
        "acceptance_run": {
            "artifact_type": "official_raw_evidence_pack_acceptance_run_v1",
            "status": status,
            "gate_status": "pass" if status == "pass" else "blocked",
            "command_count": 1,
            "passed_count": 1 if status == "pass" else 0,
            "failed_count": 0 if status == "pass" else 1,
            "skipped_count": 0,
        },
    }


def _closure_run(status: str = "pass") -> dict:
    blockers = [] if status == "pass" else ["raw_to_final_parity"]
    return {
        "artifact_type": "official_raw_closure_run_v1",
        "status": status,
        "gate_status": "pass" if status == "pass" else "blocked",
        "fixture_id": "site_001_official",
        "registered_pack_path": "fixture_pack_v1_registered.json",
        "evidence_pack_artifact": "official_raw_evidence_pack.accepted.json",
        "raw_to_final_parity_status": "pass" if status == "pass" else "fail",
        "pass_rate": 1.0 if status == "pass" else 0.0,
        "failed_fields": [] if status == "pass" else ["FC"],
        "official_eddypro_run_status": "pass",
        "official_eddypro_run_gate_status": "pass",
        "acquisition_status": "closure_ready" if status == "pass" else "blocked",
        "acquisition_gate_status": "pass" if status == "pass" else "blocked",
        "acceptance_status": "pass",
        "acceptance_gate_status": "pass",
        "blockers": blockers,
        "evidence_pack": _accepted_pack(),
    }


def test_eddypro_release_gate_passes_when_all_claim_gates_pass(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    output_dir = tmp_path / "release_gate"
    _write_matrix(matrix, covered=True)

    gate = build_eddypro_release_gate(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        official_raw_evidence_pack=_accepted_pack(),
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(),
        source_inventory=_source_inventory(),
        output_dir=output_dir,
        run_acceptance=False,
    )

    assert gate["artifact_type"] == "eddypro_release_gate_v1"
    assert gate["status"] == "pass"
    assert gate["ci_exit_code"] == 0
    assert gate["can_release_full_eddypro_parity"] is True
    assert gate["summary"]["official_raw_acceptance_gate_status"] == "pass"
    assert gate["summary"]["official_eddypro_run_gate_status"] == "pass"
    assert Path(gate["artifacts"]["eddypro_coverage_audit"]).exists()
    assert Path(gate["artifacts"]["official_raw_evidence_pack"]).exists()


def test_eddypro_release_gate_uses_closure_run_as_first_class_input(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    output_dir = tmp_path / "release_gate"
    closure_path = tmp_path / "official_raw_closure_run.json"
    _write_matrix(matrix, covered=True)
    closure_path.write_text(json.dumps(_closure_run(), ensure_ascii=False, indent=2), encoding="utf-8")

    gate = build_eddypro_release_gate(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        official_raw_closure_run_path=closure_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(),
        source_inventory=_source_inventory(),
        output_dir=output_dir,
        run_acceptance=False,
    )

    assert gate["status"] == "pass"
    assert gate["ci_exit_code"] == 0
    assert gate["summary"]["official_raw_closure_run_gate_status"] == "pass"
    assert gate["summary"]["official_raw_closure_run_parity_status"] == "pass"
    assert gate["summary"]["official_raw_acceptance_gate_status"] == "pass"
    assert gate["official_raw_evidence_pack"]["fixture_id"] == "site_001_official"
    assert Path(gate["artifacts"]["official_raw_closure_run"]).exists()
    assert Path(gate["artifacts"]["official_raw_evidence_pack"]).exists()


def test_eddypro_release_gate_blocks_when_closure_run_is_blocked(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    _write_matrix(matrix, covered=True)

    gate = build_eddypro_release_gate(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        official_raw_closure_run=_closure_run(status="blocked"),
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(),
        source_inventory=_source_inventory(),
        run_acceptance=False,
    )

    assert gate["status"] == "blocked"
    assert gate["ci_exit_code"] == 2
    assert gate["summary"]["official_raw_closure_run_gate_status"] == "blocked"
    assert "raw_to_final_parity" in gate["summary"]["official_raw_closure_run_blockers"]
    assert any("closure run has not passed" in reason for reason in gate["summary"]["blocking_reasons"])


def test_eddypro_release_gate_blocks_when_acceptance_is_not_passed(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    _write_matrix(matrix, covered=True)

    gate = build_eddypro_release_gate(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        official_raw_evidence_pack=_accepted_pack(status="fail"),
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(),
        source_inventory=_source_inventory(),
        run_acceptance=False,
    )

    assert gate["status"] == "blocked"
    assert gate["ci_exit_code"] == 2
    assert gate["can_release_full_eddypro_parity"] is False
    assert gate["summary"]["official_raw_acceptance_gate_status"] == "blocked"
    assert any("acceptance has not passed" in reason for reason in gate["summary"]["blocking_reasons"])


def test_eddypro_release_gate_blocks_without_official_executable_run(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    _write_matrix(matrix, covered=True)
    pack = _accepted_pack()
    pack.pop("official_eddypro_run")

    gate = build_eddypro_release_gate(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        official_raw_evidence_pack=pack,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(),
        source_inventory=_source_inventory(),
        run_acceptance=False,
    )

    assert gate["status"] == "blocked"
    assert gate["can_release_full_eddypro_parity"] is False
    assert gate["summary"]["official_eddypro_run_gate_status"] == "blocked"
    assert any("executable run provenance" in reason for reason in gate["summary"]["blocking_reasons"])


def test_headless_cli_builds_eddypro_release_gate_for_current_repo(tmp_path: Path) -> None:
    output = tmp_path / "eddypro_release_gate.json"
    evidence_pack = tmp_path / "accepted_pack.json"
    evidence_pack.write_text(json.dumps(_accepted_pack(), ensure_ascii=False, indent=2), encoding="utf-8")

    code = run_cli(
        [
            "--build-eddypro-release-gate",
            "--workspace-root",
            str(Path.cwd()),
            "--official-raw-evidence-pack",
            str(evidence_pack),
            "--skip-release-gate-acceptance",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["artifact_type"] == "eddypro_release_gate_v1"
    assert payload["status"] == "blocked"
    assert payload["ci_exit_code"] == 2
    assert payload["summary"]["official_raw_acceptance_gate_status"] == "pass"
    assert payload["coverage_audit"]["claim_gate"]["status"] == "blocked"
    assert payload["surrogate_evidence_closure"]["status"] == "pass"
    assert payload["summary"]["surrogate_evidence_closure_gate_status"] == "pass"
    assert payload["can_release_source_derived_functional_parity"] is True
    assert payload["summary"]["can_claim_source_derived_functional_parity"] is True


def test_headless_cli_builds_eddypro_release_gate_from_closure_run(tmp_path: Path) -> None:
    output = tmp_path / "eddypro_release_gate.json"
    closure_run = tmp_path / "official_raw_closure_run.json"
    closure_run.write_text(json.dumps(_closure_run(), ensure_ascii=False, indent=2), encoding="utf-8")

    code = run_cli(
        [
            "--build-eddypro-release-gate",
            "--workspace-root",
            str(Path.cwd()),
            "--official-raw-closure-run",
            str(closure_run),
            "--skip-release-gate-acceptance",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["artifact_type"] == "eddypro_release_gate_v1"
    assert payload["status"] == "blocked"
    assert payload["summary"]["official_raw_closure_run_gate_status"] == "pass"
    assert payload["summary"]["official_raw_acceptance_gate_status"] == "pass"
    assert payload["coverage_audit"]["claim_gate"]["status"] == "blocked"
    assert payload["surrogate_evidence_closure"]["status"] == "pass"
    assert payload["can_release_source_derived_functional_parity"] is True


def test_release_gate_runner_script_writes_artifact_and_returns_gate_code(tmp_path: Path) -> None:
    output = tmp_path / "artifacts" / "eddypro_release_gate.json"
    summary = tmp_path / "summary.md"
    evidence_pack = tmp_path / "accepted_pack.json"
    evidence_pack.write_text(json.dumps(_accepted_pack(), ensure_ascii=False, indent=2), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(Path.cwd() / "scripts" / "run_eddypro_release_gate.py"),
            "--workspace-root",
            str(Path.cwd()),
            "--official-raw-evidence-pack",
            str(evidence_pack),
            "--skip-acceptance",
            "--output",
            str(output),
            "--summary-md",
            str(summary),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["artifact_type"] == "eddypro_release_gate_v1"
    assert payload["status"] == "blocked"
    assert payload["summary"]["official_raw_acceptance_gate_status"] == "pass"
    assert "EddyPro release gate: blocked" in completed.stdout
    assert "can_release_source_derived_functional_parity: True" in completed.stdout
    assert "surrogate_evidence_closure_status: pass" in completed.stdout
    assert "## EddyPro Release Gate" in summary.read_text(encoding="utf-8")
    summary_text = summary.read_text(encoding="utf-8")
    assert "Can release source-derived functional parity: `True`" in summary_text
    assert "Surrogate evidence closure: `pass`" in summary_text
