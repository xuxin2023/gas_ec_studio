from __future__ import annotations

import json
from pathlib import Path

from core.comparison.eddypro_computation_scope_audit import build_eddypro_computation_scope_audit
from core.comparison.eddypro_computation_stress_suite import build_eddypro_computation_stress_suite
from core.headless_batch_runner import run_cli


def test_computation_stress_suite_passes_core_method_families(tmp_path: Path) -> None:
    payload = build_eddypro_computation_stress_suite(workspace_root=tmp_path)

    assert payload["artifact_type"] == "eddypro_computation_stress_suite_v1"
    assert payload["status"] == "pass"
    assert payload["pass_rate"] == 1.0
    assert payload["failed_cases"] == []
    assert payload["case_count"] == 9
    assert payload["computation_surface"]["status"] == "ready"
    assert payload["computation_surface"]["blocked_family_count"] == 0
    assert payload["claim_boundary"]["core_computation_surface_ready"] is True
    assert payload["family_counts"]["pipeline_core"] == 1
    assert payload["family_counts"]["raw_biomet_ingestion"] == 1
    assert payload["family_counts"]["raw_import_edge_cases"] == 1
    assert payload["family_counts"]["rotation_lag"] == 1
    assert payload["family_counts"]["flux_density_energy"] == 1
    assert payload["family_counts"]["footprint"] == 1
    assert payload["family_counts"]["uncertainty"] == 1
    assert payload["family_counts"]["spectral_correction"] == 1
    assert payload["family_counts"]["ch4_li7700"] == 1

    pipeline_case = next(case for case in payload["cases"] if case["family"] == "pipeline_core")
    assert pipeline_case["metrics"]["synthetic_oracle_status"] == "pass"
    assert pipeline_case["metrics"]["required_oracle_case_count"] >= 5

    raw_biomet_case = next(case for case in payload["cases"] if case["family"] == "raw_biomet_ingestion")
    assert raw_biomet_case["metrics"]["raw_row_count"] == 600
    assert raw_biomet_case["metrics"]["rp_window_count"] >= 1
    assert raw_biomet_case["metrics"]["biomet_status"] == "applied"
    assert raw_biomet_case["metrics"]["ambient_override_status"] == "applied"
    assert raw_biomet_case["metrics"]["ledger_biomet_status"] == "applied"

    raw_import_case = next(case for case in payload["cases"] if case["family"] == "raw_import_edge_cases")
    assert raw_import_case["metrics"]["format_count"] == 4
    assert raw_import_case["metrics"]["passed_format_count"] == 4
    assert raw_import_case["metrics"]["toa5_row_count"] == 3
    assert raw_import_case["metrics"]["tob1_ieee4_timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert raw_import_case["metrics"]["tob1_fp2_skip_words"] == 4
    assert raw_import_case["metrics"]["native_binary_data_type"] == "mixed"

    rotation_lag_case = next(case for case in payload["cases"] if case["family"] == "rotation_lag")
    assert rotation_lag_case["metrics"]["co2_lag_seconds"] == -0.8
    assert rotation_lag_case["metrics"]["h2o_lag_seconds"] == -0.4
    assert rotation_lag_case["metrics"]["lag_confidence"] >= 0.4

    flux_case = next(case for case in payload["cases"] if case["family"] == "flux_density_energy")
    assert flux_case["metrics"]["density_modes_checked"] == ["mixing_ratio", "none", "wpl"]
    assert flux_case["metrics"]["momentum_flux_tau_pa"] > 0.0
    assert flux_case["metrics"]["biomet_override_status"] == "applied"

    spectral_case = next(case for case in payload["cases"] if case["family"] == "spectral_correction")
    assert spectral_case["metrics"]["fratini_measured_cospectrum_used"] is True
    assert spectral_case["metrics"]["max_correction_factor"] >= 1.0

    ch4_case = next(case for case in payload["cases"] if case["family"] == "ch4_li7700")
    assert ch4_case["metrics"]["status_diagnostics_status"] == "pass"
    assert ch4_case["metrics"]["final_flux_nmol_m2_s"] > 0.0
    assert payload["claim_boundary"]["can_claim_official_field_numeric_parity"] is False


def test_headless_cli_writes_computation_stress_suite(tmp_path: Path) -> None:
    output = tmp_path / "eddypro_computation_stress_suite.json"

    code = run_cli(
        [
            "--build-eddypro-computation-stress-suite",
            "--workspace-root",
            ".",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["artifact_type"] == "eddypro_computation_stress_suite_v1"
    assert payload["status"] == "pass"
    assert payload["claim_boundary"]["can_replace_real_eddypro_raw_to_final_fixture"] is False


def test_computation_scope_audit_blocks_failed_stress_suite(tmp_path: Path) -> None:
    matrix = tmp_path / "capability_matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "capabilities": [
                    {
                        "id": "spectral_corrections",
                        "family": "spectral",
                        "gas_ec_status": "covered",
                        "coverage_checklist": [{"id": "massman_horst", "status": "done"}],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    failed_suite = {
        "artifact_type": "eddypro_computation_stress_suite_v1",
        "suite_id": "eddypro_computation_stress_suite_v1",
        "status": "fail",
        "case_count": 1,
        "passed_case_count": 0,
        "failed_case_count": 1,
        "pass_rate": 0.0,
        "failed_cases": [
            {
                "case_id": "spectral_correction_family_measured_cospectrum_sweep",
                "family": "spectral_correction",
                "failure_reasons": ["fratini:measured_cospectrum_not_used"],
            }
        ],
    }

    payload = build_eddypro_computation_scope_audit(
        capability_matrix_path=matrix,
        coverage_audit={"can_claim_source_derived_functional_parity": True},
        computation_stress_suite=failed_suite,
        workspace_root=tmp_path,
    )

    assert payload["status"] == "computation_scope_blocked"
    assert payload["claim_boundary"]["can_claim_source_derived_computational_superiority"] is False
    assert payload["computation_stress_suite_gate"]["status"] == "fail"
    assert payload["scope_summary"]["stress_suite_failed_case_count"] == 1
    assert "spectral_correction_family_measured_cospectrum_sweep" in payload["next_actions"][0]
