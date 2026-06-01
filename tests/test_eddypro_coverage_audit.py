from __future__ import annotations

import json
from pathlib import Path

from core.comparison.eddypro_coverage_audit import build_eddypro_coverage_audit
from core.headless_batch_runner import run_cli


def _write_matrix(path: Path, capabilities: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "updated_at": "2026-05-27",
                "overall_status": "test",
                "coverage_summary": {},
                "capabilities": capabilities,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _source_inventory(status: str = "pass") -> dict:
    return {
        "inventory_id": "eddypro_official_source_inventory_v1",
        "status": status,
        "feature_count": 2,
        "present_feature_count": 2 if status == "pass" else 1,
        "missing_feature_count": 0 if status == "pass" else 1,
        "missing_features": [] if status == "pass" else ["spectral_massman_horst_ibrom_fratini"],
        "source_repositories": {
            "engine": {"commit": "engine-commit"},
            "gui": {"commit": "gui-commit"},
        },
    }


def _fixture_summary(status: str = "pass") -> dict:
    return {
        "fixture_pack_id": "test_pack",
        "version": "1.0",
        "status": status,
        "asset_count": 2,
        "real_reference_window_count": 3,
        "raw_to_final_fixture_count": 1,
        "raw_to_final_pass_count": 1,
        "coverage_gaps": ["Need broader raw field fixtures."],
    }


def _official_manifest(ready_count: int = 0) -> dict:
    return {
        "status": "ready" if ready_count else "needs_official_raw_fixtures",
        "official_raw_to_final_ready_count": ready_count,
        "registered_raw_to_final_fixture_count": 1,
        "missing_official_bundle_count": 0 if ready_count else 1,
        "readiness_counts": {"official_raw_to_final_ready": ready_count},
        "evidence_matrix": {
            "raw_format_counts": {"ghg": ready_count},
            "site_class_counts": {"temperate_forest": ready_count},
            "parity_status_counts": {"pass": ready_count},
        },
    }


def _accepted_evidence_pack(status: str = "pass") -> dict:
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
        "acceptance_completed_at": "2026-05-28T10:00:00",
        "acceptance_run": {
            "artifact_type": "official_raw_evidence_pack_acceptance_run_v1",
            "status": status,
            "gate_status": "pass" if status == "pass" else "blocked",
            "command_count": 2,
            "passed_count": 2 if status == "pass" else 1,
            "failed_count": 0 if status == "pass" else 1,
            "skipped_count": 0,
        },
    }


def test_eddypro_coverage_audit_blocks_full_claim_when_capabilities_or_fixtures_are_partial(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    _write_matrix(
        matrix,
        [
            {
                "id": "raw_ghg_bundle",
                "family": "raw_ingestion",
                "gas_ec_status": "covered",
                "eddypro_requirement": "Read .ghg bundles.",
                "evidence": ["core/storage/ghg_bundle.py", "tests/test_ghg_bundle_import.py"],
            },
            {
                "id": "raw_binary_tob1_slt",
                "family": "raw_ingestion",
                "gas_ec_status": "partial",
                "gap": "Real TOB1/SLT fixtures are incomplete.",
                "next_action": "Add official raw fixtures.",
                "evidence": ["core/storage/raw_importer.py"],
                "coverage_checklist": [
                    {
                        "id": "decoder",
                        "status": "done",
                        "evidence": ["core/storage/raw_importer.py"],
                    },
                    {
                        "id": "real_fixture",
                        "status": "needs_real_fixture",
                        "blocker": "Need official TOB1/SLT bundle.",
                    },
                ],
            },
            {
                "id": "delivery_audit_benchmark",
                "family": "delivery",
                "gas_ec_status": "beyond_eddypro",
                "evidence": ["core/exports/delivery_exporter.py"],
            },
        ],
    )

    audit = build_eddypro_coverage_audit(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(ready_count=0),
        official_raw_evidence_pack=_accepted_evidence_pack(),
        source_inventory=_source_inventory(),
    )

    assert audit["artifact_type"] == "eddypro_coverage_audit_v1"
    assert audit["status"] == "not_full_eddypro_parity_yet"
    assert audit["can_claim_full_eddypro_parity"] is False
    assert audit["capability_summary"]["covered_count"] == 1
    assert audit["capability_summary"]["partial_count"] == 1
    assert audit["capability_summary"]["beyond_eddypro_count"] == 1
    assert audit["capability_summary"]["completion_score"] == 0.75
    assert audit["capability_subprogress"]["artifact_type"] == "eddypro_capability_subprogress_v1"
    assert audit["capability_subprogress"]["claim_safe"] is True
    assert audit["capability_subprogress"]["partial_capability_count"] == 1
    assert audit["capability_subprogress"]["done_item_count"] == 1
    assert audit["capability_subprogress"]["blocked_item_count"] == 1
    assert audit["capability_subprogress"]["completion_ratio"] == 0.5
    raw_row = next(row for row in audit["capability_subprogress"]["rows"] if row["id"] == "raw_binary_tob1_slt")
    assert raw_row["open_items"] == ["real_fixture"]
    assert raw_row["blocking_items"] == ["real_fixture"]
    assert audit["family_summary"]["raw_ingestion"]["blocking_capabilities"] == ["raw_binary_tob1_slt"]
    assert audit["family_summary"]["raw_ingestion"]["subprogress_completion_ratio"] == 0.5
    assert any("no official raw-to-final" in reason for reason in audit["claim_gate"]["blocking_reasons"])
    top_gap = next(item for item in audit["gap_summary"]["top_gaps"] if item["id"] == "raw_binary_tob1_slt")
    assert top_gap["subprogress"]["completion_ratio"] == 0.5
    assert top_gap["open_subprogress_items"][0]["id"] == "real_fixture"
    assert audit["closure_gate"]["artifact_type"] == "eddypro_closure_gate_v1"
    assert audit["closure_gate"]["status"] == "blocked"
    assert audit["closure_gate"]["open_item_count"] >= 2
    assert audit["closure_gate"]["top_priority"] == "P0"
    assert "full_eddypro_parity" in audit["closure_gate"]["blocked_claims"]
    assert any(item["closure_id"] == "fixture_pack:official_raw_to_final_ready_count" for item in audit["closure_gate"]["gate_items"])
    assert audit["closure_plan"]["artifact_type"] == "eddypro_closure_plan_v1"
    assert audit["closure_plan"]["status"] == "active"
    assert audit["closure_plan"]["next_actions"][0]["priority"] == "P0"
    assert audit["closure_plan"]["acceptance_command_sequence"]


def test_eddypro_coverage_audit_allows_full_claim_only_when_all_gates_pass(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    _write_matrix(
        matrix,
        [
            {
                "id": "raw_ghg_bundle",
                "family": "raw_ingestion",
                "gas_ec_status": "covered",
                "evidence": ["tests/test_ghg_bundle_import.py"],
            },
            {
                "id": "delivery_audit_benchmark",
                "family": "delivery",
                "gas_ec_status": "beyond_eddypro",
                "evidence": ["core/exports/delivery_exporter.py"],
            },
        ],
    )

    audit = build_eddypro_coverage_audit(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(ready_count=1),
        official_raw_evidence_pack=_accepted_evidence_pack(),
        source_inventory=_source_inventory(),
    )

    assert audit["status"] == "full_eddypro_parity_evidence_ready"
    assert audit["can_claim_full_eddypro_parity"] is True
    assert audit["claim_gate"]["blocking_reasons"] == []
    assert audit["fixture_evidence_summary"]["official_raw_to_final_ready_count"] == 1
    assert audit["fixture_evidence_summary"]["official_raw_acceptance_status"] == "pass"
    assert audit["official_raw_acceptance_summary"]["gate_status"] == "pass"
    assert audit["official_raw_acceptance_summary"]["official_eddypro_run_gate_status"] == "pass"
    assert audit["closure_gate"]["status"] == "pass"
    assert audit["closure_gate"]["open_item_count"] == 0
    assert audit["closure_plan"]["status"] == "complete"


def test_eddypro_coverage_audit_blocks_full_claim_until_evidence_pack_acceptance_passes(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    _write_matrix(
        matrix,
        [
            {
                "id": "raw_ghg_bundle",
                "family": "raw_ingestion",
                "gas_ec_status": "covered",
                "evidence": ["tests/test_ghg_bundle_import.py"],
            },
        ],
    )

    audit = build_eddypro_coverage_audit(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(ready_count=1),
        official_raw_evidence_pack=_accepted_evidence_pack(status="fail"),
        source_inventory=_source_inventory(),
    )

    assert audit["can_claim_full_eddypro_parity"] is False
    assert audit["claim_gate"]["status"] == "blocked"
    assert audit["official_raw_acceptance_summary"]["status"] == "fail"
    assert audit["fixture_evidence_summary"]["official_raw_acceptance_gate_status"] == "blocked"
    assert any("acceptance has not passed" in reason for reason in audit["claim_gate"]["blocking_reasons"])
    assert any(
        item["closure_id"] == "fixture_pack:official_raw_evidence_pack_acceptance"
        for item in audit["closure_gate"]["gate_items"]
    )


def test_eddypro_coverage_audit_auto_discovers_accepted_evidence_pack(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    _write_matrix(
        matrix,
        [
            {
                "id": "raw_ghg_bundle",
                "family": "raw_ingestion",
                "gas_ec_status": "covered",
                "evidence": ["tests/test_ghg_bundle_import.py"],
            },
        ],
    )
    artifact_dir = tmp_path / "artifacts" / "eddypro_public_raw"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "pending_official_raw_evidence_pack.json").write_text(
        json.dumps(_accepted_evidence_pack(status="fail"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    accepted = _accepted_evidence_pack()
    accepted["fixture_id"] = "auto_discovered_site"
    (artifact_dir / "auto_discovered_site_official_raw_evidence_pack.json").write_text(
        json.dumps(accepted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    audit = build_eddypro_coverage_audit(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(ready_count=1),
        source_inventory=_source_inventory(),
    )

    assert audit["official_raw_acceptance_summary"]["fixture_id"] == "auto_discovered_site"
    assert audit["official_raw_acceptance_summary"]["gate_status"] == "pass"
    assert audit["official_raw_acceptance_summary"]["official_eddypro_run_gate_status"] == "pass"
    assert audit["official_raw_acceptance_summary"]["artifact"].endswith(
        "auto_discovered_site_official_raw_evidence_pack.json"
    )
    assert audit["claim_gate"]["status"] == "pass"


def test_eddypro_coverage_audit_blocks_full_claim_without_official_executable_run(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    _write_matrix(
        matrix,
        [
            {
                "id": "raw_ghg_bundle",
                "family": "raw_ingestion",
                "gas_ec_status": "covered",
                "evidence": ["tests/test_ghg_bundle_import.py"],
            },
        ],
    )
    evidence_pack = _accepted_evidence_pack()
    evidence_pack.pop("official_eddypro_run")

    audit = build_eddypro_coverage_audit(
        capability_matrix_path=matrix,
        workspace_root=tmp_path,
        fixture_summary=_fixture_summary(),
        official_raw_manifest=_official_manifest(ready_count=1),
        official_raw_evidence_pack=evidence_pack,
        source_inventory=_source_inventory(),
    )

    assert audit["can_claim_full_eddypro_parity"] is False
    assert audit["official_raw_acceptance_summary"]["official_eddypro_run_gate_status"] == "blocked"
    assert any("executable run provenance" in reason for reason in audit["claim_gate"]["blocking_reasons"])
    assert any(
        item["closure_id"] == "fixture_pack:official_eddypro_executable_run"
        for item in audit["closure_gate"]["gate_items"]
    )


def test_headless_cli_writes_eddypro_coverage_audit(tmp_path: Path) -> None:
    output = tmp_path / "eddypro_coverage_audit.json"
    evidence_pack = tmp_path / "accepted_evidence_pack.json"
    evidence_pack.write_text(json.dumps(_accepted_evidence_pack(), ensure_ascii=False, indent=2), encoding="utf-8")

    code = run_cli(
        [
            "--build-eddypro-coverage-audit",
            "--workspace-root",
            str(Path.cwd()),
            "--official-raw-evidence-pack",
            str(evidence_pack),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "eddypro_coverage_audit_v1"
    assert payload["official_raw_acceptance_summary"]["status"] == "pass"
    assert payload["capability_summary"]["total_capability_count"] >= 20
    assert payload["capability_subprogress"]["claim_safe"] is True
    assert payload["capability_subprogress"]["tracked_partial_capability_count"] >= 1
    assert payload["claim_gate"]["status"] == "blocked"
    assert payload["closure_gate"]["status"] == "blocked"
    assert payload["closure_plan"]["next_action_count"] >= 1
    assert payload["surrogate_evidence_closure"]["artifact_type"] == "eddypro_surrogate_evidence_closure_v1"
    assert payload["surrogate_evidence_closure"]["status"] == "pass"
    assert payload["surrogate_evidence_closure"]["accepted_item_count"] == 10
    assert payload["surrogate_evidence_closure"]["missing_item_count"] == 0
    assert payload["can_claim_source_derived_functional_parity"] is True
    assert "official_field_numeric_parity" in payload["surrogate_evidence_closure"]["blocked_claims"]
