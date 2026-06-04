from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from app.studio import StudioController
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.08 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.8 + 0.25 * np.cos(2.0 * np.pi * 0.02 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.3 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                case_temp_c=float(temp[index] - 0.1),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def test_result_export_bundle_writes_real_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
        controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
        controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
        controller.project_workspace["timing"]["block_minutes"] = 0.5
        for row in _make_rows():
            controller.realtime_buffer.append(row)
        controller.run_ec_processing()
        controller.run_spectral_qc()
        result = controller.export_current_report()
        assert "交付包已导出" in result["message"]
        assert "导出" in controller.report_center_workspace["export_status"]

        export_root = tmp_path / "runtime_data" / "exports" / "results"
        bundle_root = next(export_root.iterdir())
        expected_files = {
            "rp_results.csv",
            "spectral_qc_results.csv",
            "full_output.csv",
            "summary.json",
            "config_snapshot.json",
            "project_site_snapshot.json",
            "report_snapshot.json",
            "export_manifest.json",
            "spectral_assessment.json",
            "spectral_binned_ensemble.csv",
            "spectral_full_windows.csv",
            "spectral_ogive_ensemble.csv",
            "spectral_assessment_library.json",
            "spectral_assessment_library_groups.csv",
            "spectral_assessment_library_bins.csv",
            "eddypro_source_inventory.json",
            "public_eddypro_fixture_catalog.json",
            "official_raw_fixture_manifest.json",
            "official_raw_closure_run.json",
            "official_raw_repair_plan.json",
            "official_raw_fixture_detail.json",
            "official_raw_evidence_pack.json",
            "flux_correction_ledger.json",
            "eddypro_coverage_audit.json",
            "eddypro_computation_stress_suite.json",
            "eddypro_computation_scope_audit.json",
            "eddypro_surrogate_evidence_closure.json",
            "eddypro_release_gate.json",
            "eddypro_partial_capability_closure.json",
            "public_ec_acquisition_closure.json",
            "public_ec_acquisition_runbook.json",
            "network_validation_summary.json",
            "fluxnet_half_hourly_foundation.json",
            "fluxnet_full_submission.json",
        }
        actual_files = {path.name for path in bundle_root.iterdir()}
        assert expected_files.issubset(actual_files)
        for name in expected_files:
            path = bundle_root / name
            assert path.exists()
            assert path.read_text(encoding="utf-8").strip() != ""

        rp_csv = (bundle_root / "rp_results.csv").read_text(encoding="utf-8")
        spectral_csv = (bundle_root / "spectral_qc_results.csv").read_text(encoding="utf-8")
        full_output_csv = (bundle_root / "full_output.csv").read_text(encoding="utf-8")
        assert "window_id" in rp_csv
        assert "window_id" in spectral_csv
        assert "relative_uncertainty" in full_output_csv
        assert "flux_correction_ledger" in full_output_csv
        assert "diagnostics_flags" in full_output_csv
        assert "turbulence_intermediate" in full_output_csv

        summary_payload = json.loads((bundle_root / "summary.json").read_text(encoding="utf-8"))
        assert summary_payload["rp_run"]["status"] == "ok"
        assert summary_payload["spectral_run"]["status"] == "ok"
        assert summary_payload["spectral_assessment"]["artifact_type"] == "spectral_assessment_export_v1"
        assert summary_payload["spectral_assessment"]["status"] == "ok"
        assert summary_payload["spectral_assessment"]["binned_ensemble"]["bin_count"] > 0
        assert summary_payload["spectral_assessment_files"]["spectral_binned_ensemble_csv"].endswith("spectral_binned_ensemble.csv")
        assert summary_payload["spectral_assessment_library"]["artifact_type"] == "spectral_assessment_library_v1"
        assert summary_payload["spectral_assessment_library"]["status"] == "ok"
        assert summary_payload["spectral_assessment_library_files"]["spectral_assessment_library_bins_csv"].endswith("spectral_assessment_library_bins.csv")
        assert summary_payload["flux_correction_ledger_summary"]["status"] == "ok"
        assert summary_payload["public_eddypro_fixture_catalog"]["status"] == "pass"
        assert summary_payload["public_eddypro_fixture_catalog_artifact"].endswith("public_eddypro_fixture_catalog.json")
        assert summary_payload["public_eddypro_fixture_count"] == 6
        assert summary_payload["public_eddypro_valid_fixture_count"] == 6
        assert summary_payload["official_raw_fixture_manifest"]["status"] == "needs_official_raw_fixtures"
        assert summary_payload["official_raw_fixture_manifest"]["evidence_matrix"]["row_count"] >= 1
        assert summary_payload["official_raw_fixture_manifest"]["official_run_normalization_ready_count"] >= 1
        assert summary_payload["official_raw_fixture_manifest"]["evidence_matrix"]["official_run_normalization_status_counts"]["normalized"] >= 1
        assert summary_payload["official_raw_closure_run"]["artifact_type"] == "official_raw_closure_run_v1"
        assert summary_payload["official_raw_closure_run_artifact"].endswith("official_raw_closure_run.json")
        assert summary_payload["official_raw_closure_run_status"] == "not_available"
        assert summary_payload["official_raw_repair_plan"]["artifact_type"] == "official_raw_fixture_repair_plan_v1"
        assert summary_payload["official_raw_repair_plan_artifact"].endswith("official_raw_repair_plan.json")
        assert summary_payload["official_raw_repair_plan_status"] == "not_available"
        assert summary_payload["official_raw_fixture_detail"]["artifact_type"] == "official_raw_fixture_detail_v1"
        assert summary_payload["official_raw_acquisition_validation"]["artifact_type"] == "official_raw_fixture_acquisition_validation_v1"
        assert "official_raw_acquisition_status" in summary_payload
        assert summary_payload["official_raw_evidence_pack"]["artifact_type"] == "official_raw_fixture_evidence_pack_v1"
        assert summary_payload["official_raw_evidence_pack_artifact"].endswith("official_raw_evidence_pack.json")
        assert summary_payload["official_raw_evidence_pack_acceptance_status"] == "not_run"
        assert summary_payload["official_eddypro_run_status"] == "not_available"
        assert summary_payload["official_eddypro_run_gate_status"] == "blocked"
        assert summary_payload["official_raw_official_run_normalization_status"] == "normalized"
        assert summary_payload["official_raw_official_run_reference_json"].endswith("official_eddypro_run_reference.json")
        assert summary_payload["eddypro_source_inventory"]["inventory_id"] == "eddypro_official_source_inventory_v1"
        assert summary_payload["eddypro_coverage_audit"]["artifact_type"] == "eddypro_coverage_audit_v1"
        assert summary_payload["eddypro_coverage_audit"]["can_claim_full_eddypro_parity"] is False
        assert summary_payload["eddypro_computation_stress_suite"]["artifact_type"] == "eddypro_computation_stress_suite_v1"
        assert summary_payload["eddypro_computation_stress_suite_artifact"].endswith("eddypro_computation_stress_suite.json")
        assert summary_payload["eddypro_computation_stress_suite_status"] == "pass"
        assert summary_payload["eddypro_computation_stress_failed_case_count"] == 0
        assert summary_payload["eddypro_computation_surface"]["status"] == "ready"
        assert summary_payload["eddypro_computation_surface_status"] == "ready"
        assert summary_payload["eddypro_computation_surface_ready_family_count"] == 10
        assert summary_payload["eddypro_computation_surface_blocked_family_count"] == 0
        assert summary_payload["eddypro_computation_surface_family_status"]["raw_biomet_ingestion"] == "pass"
        assert summary_payload["eddypro_computation_surface_family_status"]["raw_import_edge_cases"] == "pass"
        assert summary_payload["eddypro_computation_surface_family_status"]["multi_gas_final_flux"] == "pass"
        assert summary_payload["eddypro_computation_surface_family_status"]["rotation_lag"] == "pass"
        assert summary_payload["eddypro_computation_scope_audit"]["artifact_type"] == "eddypro_computation_scope_audit_v1"
        assert summary_payload["eddypro_computation_scope_audit_artifact"].endswith("eddypro_computation_scope_audit.json")
        assert summary_payload["can_claim_source_derived_computational_superiority"] is True
        assert summary_payload["eddypro_surrogate_evidence_closure"]["artifact_type"] == "eddypro_surrogate_evidence_closure_v1"
        assert summary_payload["eddypro_surrogate_evidence_closure_status"] == "pass"
        assert summary_payload["can_claim_source_derived_functional_parity"] is True
        assert summary_payload["eddypro_release_gate"]["artifact_type"] == "eddypro_release_gate_v1"
        assert summary_payload["eddypro_release_gate_status"] == "blocked"
        assert summary_payload["can_release_full_eddypro_parity"] is False
        assert summary_payload["can_release_source_derived_functional_parity"] is True
        assert summary_payload["can_release_source_derived_computational_superiority"] is True
        assert summary_payload["source_derived_computation_gate_status"] == "pass"
        assert summary_payload["source_derived_computation_ci_exit_code"] == 0
        assert summary_payload["eddypro_partial_capability_closure"]["artifact_type"] == "eddypro_partial_capability_closure_v1"
        assert summary_payload["eddypro_partial_capability_closure_status"] == "source_derived_closed_real_evidence_pending"
        assert summary_payload["eddypro_partial_capability_count"] == 5
        assert summary_payload["eddypro_ready_public_raw_candidate_count"] == 0
        assert summary_payload["public_ec_acquisition_closure"]["artifact_type"] == "public_ec_acquisition_closure_v1"
        assert summary_payload["public_ec_acquisition_closure_artifact"].endswith("public_ec_acquisition_closure.json")
        assert summary_payload["public_ec_acquisition_runbook"]["artifact_type"] == "public_ec_acquisition_runbook_v1"
        assert summary_payload["public_ec_acquisition_runbook_artifact"].endswith("public_ec_acquisition_runbook.json")
        assert summary_payload["public_ec_acquisition_runbook_status"]
        assert summary_payload["public_ec_acquisition_can_claim_eddypro_raw_to_final_parity"] is False
        assert summary_payload["public_ec_acquisition_can_release_full_eddypro_parity"] is False
        assert summary_payload["eddypro_closure_gate"]["artifact_type"] == "eddypro_closure_gate_v1"
        assert summary_payload["eddypro_closure_gate_status"] == "blocked"
        assert summary_payload["eddypro_closure_open_item_count"] >= 1

        ledger_payload = json.loads((bundle_root / "flux_correction_ledger.json").read_text(encoding="utf-8"))
        assert ledger_payload["artifact_type"] == "flux_correction_ledger_run_v1"
        assert ledger_payload["summary"]["ledger_window_count"] >= 1
        assert ledger_payload["windows"][0]["stage_count"] >= 4

        config_payload = json.loads((bundle_root / "config_snapshot.json").read_text(encoding="utf-8"))
        assert "rp_config_snapshot" in config_payload
        assert "spectral_config_snapshot" in config_payload

        manifest_payload = json.loads((bundle_root / "export_manifest.json").read_text(encoding="utf-8"))
        assert manifest_payload["full_output_mode"] == "only_available"
        assert manifest_payload["field_schema"]
        assert any(field["name"] == "diagnostics_flags" for field in manifest_payload["field_schema"])
        assert manifest_payload["schema_target"] == "FLUXNET"
        assert manifest_payload["spectral_assessment_artifact"].endswith("spectral_assessment.json")
        assert manifest_payload["spectral_assessment"]["full_window_row_count"] > 0
        assert manifest_payload["spectral_assessment_files"]["spectral_full_windows_csv"].endswith("spectral_full_windows.csv")
        assert manifest_payload["spectral_assessment_library_artifact"].endswith("spectral_assessment_library.json")
        assert manifest_payload["spectral_assessment_library"]["group_count"] >= 1
        assert manifest_payload["spectral_assessment_library_files"]["spectral_assessment_library_groups_csv"].endswith("spectral_assessment_library_groups.csv")
        assert manifest_payload["flux_correction_ledger_summary"]["status"] == "ok"
        assert manifest_payload["flux_correction_ledger_artifact"].endswith("flux_correction_ledger.json")
        assert manifest_payload["network_energy_fields"] == ["H", "LE", "ET", "TAU"]
        assert manifest_payload["public_eddypro_fixture_catalog_status"] == "pass"
        assert manifest_payload["public_eddypro_fixture_catalog_artifact"].endswith("public_eddypro_fixture_catalog.json")
        assert manifest_payload["public_eddypro_fixture_count"] == 6
        assert manifest_payload["public_eddypro_valid_fixture_count"] == 6
        assert Path(manifest_payload["public_eddypro_fixture_catalog_artifact"]).exists()
        assert manifest_payload["official_raw_fixture_manifest_artifact"].endswith("official_raw_fixture_manifest.json")
        assert manifest_payload["official_raw_closure_run_artifact"].endswith("official_raw_closure_run.json")
        assert manifest_payload["official_raw_closure_run_status"] == "not_available"
        assert Path(manifest_payload["official_raw_closure_run_artifact"]).exists()
        assert manifest_payload["official_raw_repair_plan_artifact"].endswith("official_raw_repair_plan.json")
        assert manifest_payload["official_raw_repair_plan_status"] == "not_available"
        assert Path(manifest_payload["official_raw_repair_plan_artifact"]).exists()
        assert manifest_payload["official_raw_fixture_detail_artifact"].endswith("official_raw_fixture_detail.json")
        assert manifest_payload["official_raw_fixture_detail"]["fixture_id"]
        assert manifest_payload["official_raw_acquisition_validation"]["artifact_type"] == "official_raw_fixture_acquisition_validation_v1"
        assert "official_raw_acquisition_missing_requirements" in manifest_payload
        assert manifest_payload["official_raw_evidence_pack_artifact"].endswith("official_raw_evidence_pack.json")
        assert "official_raw_evidence_pack_status" in manifest_payload
        assert manifest_payload["official_raw_evidence_pack_acceptance_status"] == "not_run"
        assert "official_raw_evidence_pack_acceptance_command_count" in manifest_payload
        assert manifest_payload["official_eddypro_run_status"] == "not_available"
        assert manifest_payload["official_eddypro_run_gate_status"] == "blocked"
        assert manifest_payload["official_raw_normalization_status"] in {"present", "ready"}
        assert manifest_payload["official_raw_qc_mapping_strategy"]
        assert manifest_payload["official_raw_official_run_normalization_status"] == "normalized"
        assert manifest_payload["official_raw_official_run_qc_mapping_strategy"] == "EddyPro 0/1/2 -> gas_ec_studio A/B/C"
        assert manifest_payload["official_raw_fixture_manifest"]["registered_raw_to_final_fixture_count"] == 8
        assert manifest_payload["official_raw_fixture_manifest"]["official_run_normalization_ready_count"] >= 1
        assert manifest_payload["official_raw_fixture_manifest"]["evidence_matrix"]["raw_format_counts"]["csv"] >= 1
        assert manifest_payload["official_raw_fixture_detail"]["trace_gas_parity_status"] == "pass"
        assert manifest_payload["official_raw_fixture_detail"]["trace_gas_coefficient_profile_id"] == "synthetic_li7700_profile"
        assert "raw_to_final_parity_diagnostics" in manifest_payload
        assert "raw_to_final_parity_failure_groups" in manifest_payload
        assert "raw_to_final_parity_top_failed_fields" in manifest_payload
        assert manifest_payload["eddypro_source_inventory_artifact"].endswith("eddypro_source_inventory.json")
        assert manifest_payload["eddypro_source_inventory"]["feature_count"] >= 10
        assert manifest_payload["eddypro_coverage_audit_artifact"].endswith("eddypro_coverage_audit.json")
        assert manifest_payload["eddypro_coverage_audit"]["claim_gate"]["status"] == "blocked"
        assert manifest_payload["eddypro_computation_stress_suite_artifact"].endswith("eddypro_computation_stress_suite.json")
        assert manifest_payload["eddypro_computation_stress_suite"]["status"] == "pass"
        assert manifest_payload["eddypro_computation_stress_pass_rate"] == 1.0
        assert manifest_payload["eddypro_computation_surface"]["status"] == "ready"
        assert manifest_payload["eddypro_computation_surface_status"] == "ready"
        assert manifest_payload["eddypro_computation_surface_ready_family_count"] == 10
        assert manifest_payload["eddypro_computation_surface_blocked_family_count"] == 0
        assert manifest_payload["eddypro_computation_surface_family_status"]["raw_biomet_ingestion"] == "pass"
        assert manifest_payload["eddypro_computation_surface_family_status"]["raw_import_edge_cases"] == "pass"
        assert manifest_payload["eddypro_computation_surface_family_status"]["multi_gas_final_flux"] == "pass"
        assert manifest_payload["eddypro_computation_surface_family_status"]["spectral_correction"] == "pass"
        assert manifest_payload["eddypro_computation_scope_audit_artifact"].endswith("eddypro_computation_scope_audit.json")
        assert manifest_payload["eddypro_computation_scope_audit"]["claim_boundary"]["can_claim_source_derived_computational_superiority"] is True
        assert manifest_payload["eddypro_computation_scope_audit"]["claim_boundary"]["can_claim_official_field_numeric_parity"] is False
        assert manifest_payload["eddypro_surrogate_evidence_closure_artifact"].endswith("eddypro_surrogate_evidence_closure.json")
        assert manifest_payload["eddypro_surrogate_evidence_closure"]["status"] == "pass"
        assert manifest_payload["can_claim_source_derived_functional_parity"] is True
        assert manifest_payload["eddypro_release_gate_artifact"].endswith("eddypro_release_gate.json")
        assert manifest_payload["eddypro_release_gate"]["status"] == "blocked"
        assert manifest_payload["can_release_full_eddypro_parity"] is False
        assert manifest_payload["can_release_source_derived_functional_parity"] is True
        assert manifest_payload["can_release_source_derived_computational_superiority"] is True
        assert manifest_payload["source_derived_computation_gate_status"] == "pass"
        assert manifest_payload["source_derived_computation_ci_exit_code"] == 0
        assert manifest_payload["eddypro_partial_capability_closure_artifact"].endswith("eddypro_partial_capability_closure.json")
        assert manifest_payload["eddypro_partial_capability_closure"]["partial_capability_count"] == 5
        assert manifest_payload["eddypro_partial_capability_closure"]["closure_decision"]["current_round_closed"] is True
        assert manifest_payload["public_ec_acquisition_closure_artifact"].endswith("public_ec_acquisition_closure.json")
        assert manifest_payload["public_ec_acquisition_closure"]["artifact_type"] == "public_ec_acquisition_closure_v1"
        assert manifest_payload["public_ec_acquisition_runbook_artifact"].endswith("public_ec_acquisition_runbook.json")
        assert manifest_payload["public_ec_acquisition_runbook"]["artifact_type"] == "public_ec_acquisition_runbook_v1"
        assert manifest_payload["public_ec_acquisition_can_claim_eddypro_raw_to_final_parity"] is False
        assert manifest_payload["public_ec_acquisition_can_release_full_eddypro_parity"] is False
        assert manifest_payload["eddypro_closure_gate"]["status"] == "blocked"
        assert manifest_payload["eddypro_closure_plan"]["next_action_count"] >= 1
        assert manifest_payload["eddypro_closure_top_priority"] in {"P0", "P1"}
        assert "network_validation_status" in manifest_payload
        assert "network_missing_fields" in manifest_payload

        project_site_payload = json.loads((bundle_root / "project_site_snapshot.json").read_text(encoding="utf-8"))
        assert "project" in project_site_payload
        assert "site" in project_site_payload
    finally:
        controller.shutdown()


def test_result_export_builds_neon_fixture_profile_from_validation_artifact(tmp_path: Path) -> None:
    validation_path = tmp_path / "neon_hdf5_validation_package.json"
    validation_path.write_text(
        json.dumps(
            {
                "artifact_type": "neon_hdf5_validation_package_v1",
                "status": "pass",
                "source_id": "neon_export_profile",
                "source_file": "NEON.EXPORT.h5",
                "metadata_status": "mapping_ready_for_importer_smoke",
                "row_status": "pass",
                "rp_status": "pass",
                "row_count": 120,
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
    exporter = ResultExporter(runtime_root=tmp_path / "runtime_data")

    result = exporter.export_minimal_bundle(
        rp_result=None,
        spectral_result=None,
        rp_config_snapshot={},
        spectral_config_snapshot={},
        project={"code": "TEST"},
        site={"station_code": "TST"},
        report_payload={"status": "ok"},
        report_key="neon-profile-test",
        external_artifacts={"neon_hdf5_validation_package": str(validation_path)},
    )
    manifest_path = Path(result["files"]["export_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile_path = Path(manifest["neon_hdf5_fixture_profile_artifact"])
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    assert profile_path.exists()
    assert profile["artifact_type"] == "neon_hdf5_fixture_profile_v1"
    assert profile["source_id"] == "neon_export_profile"
    assert profile["registration_profile"]["can_register_as_public_engineering_fixture"] is True
    assert profile["registration_profile"]["can_register_as_official_eddypro_raw_to_final_fixture"] is False
    assert manifest["neon_hdf5_fixture_profile_status"] == "engineering_fixture_ready_official_parity_blocked"
    assert manifest["neon_hdf5_fixture_profile"]["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
