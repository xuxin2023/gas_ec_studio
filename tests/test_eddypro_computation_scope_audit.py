from __future__ import annotations

import json
from pathlib import Path

from core.comparison.eddypro_computation_scope_audit import build_eddypro_computation_scope_audit
from core.headless_batch_runner import run_cli


def test_computation_scope_audit_defers_non_computational_and_evidence_blockers(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "capabilities": [
                    {
                        "id": "coordinate_rotation_planar_fit",
                        "family": "preprocessing",
                        "gas_ec_status": "covered",
                        "coverage_checklist": [{"id": "rotation", "status": "done"}],
                    },
                    {
                        "id": "ch4_trace_gas_fluxes",
                        "family": "fluxes",
                        "gas_ec_status": "partial",
                        "coverage_checklist": [
                            {"id": "ch4_algorithm", "status": "done"},
                            {"id": "real_li7700_fixture", "status": "needs_real_fixture"},
                        ],
                    },
                    {
                        "id": "gps_ptp_sync",
                        "family": "acquisition",
                        "gas_ec_status": "partial",
                        "coverage_checklist": [{"id": "hardware_fixture", "status": "needs_hardware"}],
                    },
                    {
                        "id": "raw_binary_tob1_slt",
                        "family": "raw_ingestion",
                        "gas_ec_status": "partial",
                        "coverage_checklist": [{"id": "real_tob1_fixture", "status": "needs_real_fixture"}],
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_eddypro_computation_scope_audit(
        capability_matrix_path=matrix,
        coverage_audit={"can_claim_source_derived_functional_parity": True},
        workspace_root=tmp_path,
    )

    assert payload["artifact_type"] == "eddypro_computation_scope_audit_v1"
    assert payload["status"] == "source_derived_computation_ready_real_evidence_pending"
    assert payload["claim_boundary"]["can_claim_source_derived_computational_superiority"] is True
    assert payload["claim_boundary"]["can_claim_official_field_numeric_parity"] is False
    assert payload["scope_summary"]["core_algorithm_blocker_count"] == 0
    assert payload["scope_summary"]["evidence_pending_count"] == 3
    assert any(row["id"] == "gps_ptp_sync" for row in payload["deferred_non_computational_rows"])
    ch4 = next(row for row in payload["rows"] if row["id"] == "ch4_trace_gas_fluxes")
    assert ch4["algorithm_ready_for_source_derived_claim"] is True
    assert ch4["evidence_pending_count"] == 1


def test_computation_scope_audit_blocks_real_algorithm_gap(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "capabilities": [
                    {
                        "id": "spectral_corrections",
                        "family": "spectral",
                        "gas_ec_status": "partial",
                        "coverage_checklist": [{"id": "massman_horst", "status": "missing"}],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = build_eddypro_computation_scope_audit(
        capability_matrix_path=matrix,
        coverage_audit={"can_claim_source_derived_functional_parity": True},
        workspace_root=tmp_path,
    )

    assert payload["status"] == "computation_scope_blocked"
    assert payload["claim_boundary"]["can_claim_source_derived_computational_superiority"] is False
    assert payload["scope_summary"]["core_algorithm_blocker_count"] == 1
    assert payload["core_algorithm_blockers"][0]["id"] == "spectral_corrections"


def test_headless_cli_writes_computation_scope_audit(tmp_path: Path) -> None:
    output = tmp_path / "eddypro_computation_scope_audit.json"

    code = run_cli(
        [
            "--build-eddypro-computation-scope-audit",
            "--workspace-root",
            ".",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["artifact_type"] == "eddypro_computation_scope_audit_v1"
    assert payload["scope_summary"]["calculation_core_count"] >= 1
    assert payload["computation_stress_suite_gate"]["status"] == "pass"
    assert payload["scope_summary"]["stress_suite_failed_case_count"] == 0
    assert payload["claim_boundary"]["can_claim_official_field_numeric_parity"] is False
