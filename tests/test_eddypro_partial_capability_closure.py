from __future__ import annotations

import json
from pathlib import Path

from core.comparison.partial_capability_closure import build_eddypro_partial_capability_closure
from core.headless_batch_runner import run_cli


def _raw_search_summary() -> dict:
    return {
        "artifact_type": "public_raw_binary_tob1_slt_search_summary_v1",
        "search_status": {"status": "no_public_registerable_tob1_slt_bundle_found"},
        "lead_count": 4,
        "raw_to_final_candidate_count": 0,
        "can_support_full_raw_to_final_eddypro_claim": False,
        "promotion_blockers": ["No complete public raw/settings/Full_Output bundle was found."],
        "source_derived_fallbacks": [
            {"fixture_id": "eddypro_source_tob1_seconds_001", "status": "registered_raw_to_final_pass"}
        ],
    }


def _public_ec_sources() -> dict:
    return {
        "artifact_type": "public_ec_data_source_discovery_v1",
        "truthfulness_boundary": "Discovery does not change full parity.",
        "sources": [
            {
                "source_id": "licor_eddypro_sample_data_2021",
                "provider": "LI-COR",
                "source_url": "https://www.licor.com/support/EddyPro/topics/sample-datasets.html",
                "registration_outcome": "registered_and_accepted",
                "parity_value": "official_public_raw_anchor",
            },
            {
                "source_id": "neon_dp4_00200_001",
                "provider": "NEON",
                "source_url": "https://data.neonscience.org/data-products/DP4.00200.001",
                "access_status": "api_metadata_verified",
                "registration_outcome": "not_registered",
                "parity_value": "real_ec_hdf5_candidate_not_eddypro_output",
                "next_action": "Use as engineering validation only until an EddyPro output pair exists.",
                "known_limitations": ["Not an EddyPro raw/settings/Full_Output bundle."],
            },
        ],
    }


def test_partial_capability_closure_keeps_full_claim_blocked() -> None:
    coverage = {
        "artifact_type": "eddypro_coverage_audit_v1",
        "can_claim_full_eddypro_parity": False,
        "can_claim_source_derived_functional_parity": True,
        "capability_rows": [
            {
                "id": "raw_binary_tob1_slt",
                "family": "raw_ingestion",
                "gas_ec_status": "partial",
                "eddypro_requirement": "Support binary and TOB1/SLT family raw formats.",
                "gap": "Real vendor binary fixtures remain pending.",
                "next_action": "Find a redistributable TOB1/SLT raw/settings/output bundle.",
                "evidence": ["core/storage/raw_importer.py"],
                "coverage_checklist": [
                    {"id": "source_derived", "label": "Source-derived fixtures pass.", "status": "done"},
                    {
                        "id": "real_fixture",
                        "label": "Real binary fixture pending.",
                        "status": "needs_real_fixture",
                        "blocker": "Need real public binary data.",
                    },
                ],
            }
        ],
    }
    release_gate = {
        "artifact_type": "eddypro_release_gate_v1",
        "status": "blocked",
        "can_release_full_eddypro_parity": False,
        "can_release_source_derived_functional_parity": True,
        "official_raw_closure_run_summary": {
            "status": "pass",
            "gate_status": "pass",
            "fixture_id": "ghg_sample_data_2021_licor_public_raw_candidate",
            "raw_to_final_parity_status": "pass",
            "pass_rate": 1.0,
            "acceptance_status": "pass",
            "acceptance_gate_status": "pass",
        },
    }
    neon = {
        "artifact_type": "neon_hdf5_validation_package_v1",
        "status": "pass",
        "source_id": "neon_dp4_00200_001",
        "row_count": 160,
        "rp_window_count": 1,
        "claim_boundary": {
            "can_claim_neon_engineering_validation": True,
            "can_claim_eddypro_raw_to_final_parity": False,
        },
    }

    payload = build_eddypro_partial_capability_closure(
        coverage_audit=coverage,
        release_gate=release_gate,
        public_raw_search_summary=_raw_search_summary(),
        public_ec_data_sources=_public_ec_sources(),
        neon_validation_package=neon,
    )

    assert payload["artifact_type"] == "eddypro_partial_capability_closure_v1"
    assert payload["status"] == "source_derived_closed_real_evidence_pending"
    assert payload["partial_capability_count"] == 1
    assert payload["claim_boundary"]["can_close_full_eddypro_parity"] is False
    assert payload["claim_boundary"]["can_claim_source_derived_functional_parity"] is True
    assert payload["accepted_official_anchor"]["is_accepted"] is True
    assert payload["public_search_closure"]["ready_to_register_public_raw_candidate_count"] == 0
    assert payload["public_search_closure"]["accepted_public_anchor_count"] == 1
    assert payload["neon_engineering_validation"]["can_claim_neon_engineering_validation"] is True
    assert payload["neon_engineering_validation"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["partial_capabilities"][0]["closure_status"] == "source_derived_binary_conformance_closed_real_fixture_pending"
    assert payload["closure_decision"]["current_round_closed"] is True
    assert payload["closure_decision"]["development_blocked"] is False
    assert payload["closure_decision"]["full_parity_claim_blocked"] is True


def test_partial_capability_closure_cli_writes_artifact(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "artifact_type": "eddypro_capability_matrix",
                "surrogate_evidence_closure_policy": {"status": "accepted"},
                "capabilities": [
                    {
                        "id": "raw_ghg_real_world_fixture_breadth",
                        "family": "raw_ingestion",
                        "gas_ec_status": "partial",
                        "eddypro_requirement": "Handle field .ghg dialect breadth.",
                        "gap": "Additional official output pairs remain pending.",
                        "next_action": "Promote another public or anonymized .ghg bundle.",
                        "coverage_checklist": [
                            {"id": "official_anchor", "label": "One anchor exists.", "status": "done"},
                            {"id": "multi_site", "label": "Multi-site breadth.", "status": "needs_real_fixture"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    raw_manifest_path = tmp_path / "raw_search.json"
    raw_manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "public_raw_binary_tob1_slt_search_manifest_v1",
                "search_status": {"status": "no_public_registerable_tob1_slt_bundle_found"},
                "leads": [],
                "source_derived_fallbacks": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    ec_sources_path = tmp_path / "ec_sources.json"
    ec_sources_path.write_text(json.dumps(_public_ec_sources(), ensure_ascii=False, indent=2), encoding="utf-8")
    neon_path = tmp_path / "neon.json"
    neon_path.write_text(
        json.dumps(
            {
                "artifact_type": "neon_hdf5_validation_package_v1",
                "status": "pass",
                "row_count": 160,
                "rp_window_count": 1,
                "claim_boundary": {
                    "can_claim_neon_engineering_validation": True,
                    "can_claim_eddypro_raw_to_final_parity": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "closure.json"

    exit_code = run_cli(
        [
            "--build-eddypro-partial-capability-closure",
            "--workspace-root",
            str(tmp_path),
            "--capability-matrix",
            str(matrix_path),
            "--public-raw-search-manifest",
            str(raw_manifest_path),
            "--public-ec-data-sources",
            str(ec_sources_path),
            "--neon-hdf5-validation-package",
            str(neon_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["partial_capability_count"] == 1
    assert payload["capability_ids"] == ["raw_ghg_real_world_fixture_breadth"]
    assert payload["claim_boundary"]["can_promote_from_public_search"] is False
    assert payload["closure_decision"]["current_round_closed"] is True
