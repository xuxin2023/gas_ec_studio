from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from app.studio import StudioController
from core.exports.delivery_exporter import export_delivery_package
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


def _prepare_reference_dir(reference_dir: Path, current_export_dir: Path) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)
    spectral_lines = (current_export_dir / "spectral_qc_results.csv").read_text(encoding="utf-8").splitlines()
    header = spectral_lines[0].split(",")
    records = [dict(zip(header, line.split(","), strict=False)) for line in spectral_lines[1:3] if line.strip()]
    rows = ["window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade"]
    for index, record in enumerate(records, start=1):
        start_time = datetime.fromisoformat(str(record.get("start_time", ""))) + timedelta(seconds=1)
        end_time = datetime.fromisoformat(str(record.get("end_time", ""))) + timedelta(seconds=1)
        rows.append(
            ",".join(
                [
                    f"ep-{index}",
                    start_time.isoformat(),
                    end_time.isoformat(),
                    f"{float(record.get('lag_seconds', '0') or 0.0) + 0.3:.3f}",
                    f"{float(record.get('corrected_flux_after', '0') or 0.0) * 0.95:.6f}",
                    f"{float(record.get('correction_factor', '1') or 1.0) * 1.03:.4f}",
                    str(record.get("qc_grade", "B")),
                ]
            )
        )
    (reference_dir / "eddypro_windows.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (reference_dir / "eddypro_summary.json").write_text(
        json.dumps({"software": "EddyPro", "mapping_incomplete": False}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prepare_real_results(controller: StudioController) -> None:
    controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
    controller.project_workspace["timing"]["block_minutes"] = 0.5
    controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
    controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
    for row in _make_rows():
        controller.realtime_buffer.append(row)
    controller.run_ec_processing()
    controller.run_spectral_qc()


def _latest_delivery_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_data" / "exports" / "delivery"
    return max((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)


def _latest_delivery_zip(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_data" / "exports" / "delivery"
    return max((path for path in root.iterdir() if path.suffix == ".zip"), key=lambda path: path.stat().st_mtime)


def test_delivery_package_exports_minimal_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        result = controller.export_current_report()

        assert "交付包已导出" in result["message"]
        assert "交付包已导出" in controller.report_center_workspace["export_status"]

        delivery_dir = _latest_delivery_dir(tmp_path)
        manifest_path = delivery_dir / "package_manifest.json"
        audit_path = delivery_dir / "delivery_audit.json"
        readme_path = delivery_dir / "README.txt"
        zip_path = _latest_delivery_zip(tmp_path)

        assert delivery_dir.exists()
        assert manifest_path.exists()
        assert audit_path.exists()
        assert readme_path.exists()
        assert zip_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        readme = readme_path.read_text(encoding="utf-8")

        assert manifest["export_status"] == "ready"
        assert manifest["delivery_audit"]["validation_status"] == "ok"
        assert audit["validation_status"] == "ok"
        assert manifest["result_manifest_summary"]["schema_target"]
        assert "network_validation_summary" in manifest
        assert manifest["artifact_index"]["export_manifest"]["packaged"] is True
        assert manifest["artifact_index"]["network_validation_summary"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_assessment_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_binned_ensemble_csv"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_full_windows_csv"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_ogive_ensemble_csv"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_assessment_library_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["spectral_assessment_library_bins_csv"]["packaged"] is True
        assert manifest["artifact_index"]["fixture_pack_summary_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["public_eddypro_fixture_catalog_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["official_raw_fixture_manifest_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["official_raw_closure_run_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["official_raw_repair_plan_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["official_raw_fixture_detail_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["official_raw_evidence_pack_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["eddypro_source_inventory_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["eddypro_coverage_audit_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["eddypro_surrogate_evidence_closure_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["eddypro_release_gate_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["eddypro_partial_capability_closure_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["flux_correction_ledger_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["method_rollup_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["method_parity_matrix_artifact"]["packaged"] is True
        assert manifest["fixture_pack_summary"]["status"] == "pass"
        assert manifest["public_eddypro_fixture_catalog"]["status"] == "pass"
        assert manifest["public_eddypro_fixture_catalog"]["fixture_count"] == 6
        assert manifest["official_raw_fixture_manifest"]["status"] == "needs_official_raw_fixtures"
        assert manifest["official_raw_closure_run"]["artifact_type"] == "official_raw_closure_run_v1"
        assert manifest["official_raw_closure_run"]["status"] == "not_available"
        assert manifest["official_raw_repair_plan"]["artifact_type"] == "official_raw_fixture_repair_plan_v1"
        assert manifest["official_raw_repair_plan"]["status"] == "not_available"
        assert manifest["official_raw_fixture_detail"]["artifact_type"] == "official_raw_fixture_detail_v1"
        assert manifest["official_raw_acquisition_validation"]["artifact_type"] == "official_raw_fixture_acquisition_validation_v1"
        assert manifest["official_raw_evidence_pack"]["artifact_type"] == "official_raw_fixture_evidence_pack_v1"
        assert manifest["official_eddypro_run"]["status"] == "not_available"
        assert manifest["eddypro_source_inventory"]["inventory_id"] == "eddypro_official_source_inventory_v1"
        assert manifest["eddypro_coverage_audit"]["artifact_type"] == "eddypro_coverage_audit_v1"
        assert manifest["eddypro_surrogate_evidence_closure"]["artifact_type"] == "eddypro_surrogate_evidence_closure_v1"
        assert manifest["result_manifest_summary"]["eddypro_surrogate_evidence_closure_status"] == "pass"
        assert manifest["result_manifest_summary"]["can_claim_source_derived_functional_parity"] is True
        assert manifest["eddypro_release_gate"]["artifact_type"] == "eddypro_release_gate_v1"
        assert manifest["eddypro_partial_capability_closure"]["artifact_type"] == "eddypro_partial_capability_closure_v1"
        assert manifest["result_manifest_summary"]["eddypro_partial_capability_count"] == 5
        assert manifest["result_manifest_summary"]["eddypro_ready_public_raw_candidate_count"] == 0
        assert manifest["result_manifest_summary"]["can_claim_full_eddypro_parity"] is False
        assert manifest["result_manifest_summary"]["can_release_full_eddypro_parity"] is False
        assert manifest["result_manifest_summary"]["can_release_source_derived_functional_parity"] is True
        assert manifest["result_manifest_summary"]["eddypro_release_gate_status"] == "blocked"
        assert manifest["eddypro_closure_gate"]["artifact_type"] == "eddypro_closure_gate_v1"
        assert manifest["result_manifest_summary"]["eddypro_closure_gate_status"] == "blocked"
        assert manifest["result_manifest_summary"]["eddypro_closure_open_item_count"] >= 1
        assert manifest["flux_correction_ledger_summary"]["status"] == "ok"
        assert manifest["result_manifest_summary"]["fixture_pack_status"] == "pass"
        assert manifest["result_manifest_summary"]["registered_raw_to_final_fixture_count"] == 8
        assert manifest["result_manifest_summary"]["official_raw_fixture_detail_id"]
        assert manifest["result_manifest_summary"]["official_raw_fixture_detail_id"] == "synthetic_li7700_trace_gas_001"
        assert "official_raw_acquisition_status" in manifest["result_manifest_summary"]
        assert manifest["result_manifest_summary"]["official_raw_closure_run_status"] == "not_available"
        assert manifest["result_manifest_summary"]["official_raw_repair_plan_status"] == "not_available"
        assert manifest["result_manifest_summary"]["official_raw_repair_item_count"] == 0
        assert "official_raw_evidence_pack_status" in manifest["result_manifest_summary"]
        assert manifest["result_manifest_summary"]["official_raw_evidence_pack_acceptance_status"] == "not_run"
        assert manifest["result_manifest_summary"]["official_eddypro_run_status"] == "not_available"
        assert manifest["result_manifest_summary"]["official_eddypro_run_gate_status"] == "blocked"
        assert manifest["result_manifest_summary"]["official_raw_normalization_status"] in {"present", "ready"}
        assert manifest["result_manifest_summary"]["official_raw_qc_mapping_strategy"]
        assert manifest["result_manifest_summary"]["official_raw_official_run_normalization_status"] == "normalized"
        assert manifest["result_manifest_summary"]["official_raw_official_run_qc_mapping_strategy"] == "EddyPro 0/1/2 -> gas_ec_studio A/B/C"
        assert manifest["official_raw_fixture_manifest"]["official_run_normalization_ready_count"] >= 1
        assert manifest["official_raw_fixture_detail"]["trace_gas_parity_status"] == "pass"
        assert manifest["result_manifest_summary"]["eddypro_source_inventory_feature_count"] >= 10
        assert manifest["result_manifest_summary"]["flux_correction_ledger_status"] == "ok"
        assert manifest["result_manifest_summary"]["spectral_assessment_status"] == "ok"
        assert manifest["result_manifest_summary"]["spectral_assessment_library_status"] == "ok"
        assert manifest["result_manifest_summary"]["public_eddypro_fixture_catalog_status"] == "pass"
        assert manifest["result_manifest_summary"]["public_eddypro_fixture_count"] == 6
        assert manifest["result_manifest_summary"]["public_eddypro_valid_fixture_count"] == 6
        assert manifest["result_manifest_summary"]["public_eddypro_can_support_raw_to_final_claim"] is False
        assert manifest["spectral_assessment"]["artifact_type"] == "spectral_assessment_export_v1"
        assert manifest["spectral_assessment_library"]["artifact_type"] == "spectral_assessment_library_v1"
        assert audit["missing_declared_files"] == []
        assert audit["missing_manifest_files"] == []
        assert manifest["file_list"]
        assert any("缺少 compare" in note or "缺少 attribution" in note for note in manifest["notes"])
        assert "formal_report.html" in readme
        assert "fallback_html_only" in readme
        assert "official_raw_closure_run" in readme
        assert "official_raw_repair_plan" in readme
        assert (delivery_dir / "formal_report.html").exists()
        assert (delivery_dir / "rp_results.csv").exists()
        assert (delivery_dir / "spectral_qc_results.csv").exists()
        with ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
        assert any(name.endswith("package_manifest.json") for name in names)
        assert any(name.endswith("delivery_audit.json") for name in names)
        assert any(name.endswith("network_validation_summary.json") for name in names)
        assert any(name.endswith("spectral_assessment.json") for name in names)
        assert any(name.endswith("spectral_assessment_library.json") for name in names)
        assert any(name.endswith("spectral_binned_ensemble.csv") for name in names)
        assert any(name.endswith("fixture_pack_summary.json") for name in names)
        assert any(name.endswith("public_eddypro_fixture_catalog.json") for name in names)
        assert any(name.endswith("official_raw_fixture_manifest.json") for name in names)
        assert any(name.endswith("official_raw_closure_run.json") for name in names)
        assert any(name.endswith("official_raw_repair_plan.json") for name in names)
        assert any(name.endswith("official_raw_evidence_pack.json") for name in names)
        assert any(name.endswith("eddypro_source_inventory.json") for name in names)
        assert any(name.endswith("eddypro_coverage_audit.json") for name in names)
        assert any(name.endswith("eddypro_surrogate_evidence_closure.json") for name in names)
        assert any(name.endswith("eddypro_release_gate.json") for name in names)
        assert any(name.endswith("eddypro_partial_capability_closure.json") for name in names)
        assert any(name.endswith("flux_correction_ledger.json") for name in names)
    finally:
        controller.shutdown()


def test_delivery_package_includes_compare_and_attribution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        controller.export_current_report()
        current_export_dir = controller._latest_result_export_dir()
        assert current_export_dir is not None

        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)
        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )
        controller.export_current_report()

        delivery_dir = _latest_delivery_dir(tmp_path)
        manifest = json.loads((delivery_dir / "package_manifest.json").read_text(encoding="utf-8"))

        assert (delivery_dir / "compare_summary.json").exists()
        assert (delivery_dir / "compare_windows.csv").exists()
        assert (delivery_dir / "compare_manifest.json").exists()
        assert (delivery_dir / "attribution_summary.json").exists()
        assert manifest["compare_id"]
        assert manifest["attribution_id"]

        zip_path = _latest_delivery_zip(tmp_path)
        with ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
        assert any(name.endswith("compare_summary.json") for name in names)
        assert any(name.endswith("attribution_summary.json") for name in names)
    finally:
        controller.shutdown()


def test_delivery_package_indexes_neon_hdf5_validation_package(tmp_path: Path) -> None:
    result_root = tmp_path / "result_bundle"
    result_root.mkdir(parents=True)
    validation_payload = {
        "artifact_type": "neon_hdf5_validation_package_v1",
        "status": "pass",
        "source_file": "NEON.TEST.h5",
        "metadata_status": "mapping_ready_for_importer_smoke",
        "row_status": "pass",
        "rp_status": "pass",
        "row_count": 120,
        "rp_window_count": 1,
        "claim_boundary": {
            "can_claim_neon_engineering_validation": True,
            "can_claim_eddypro_raw_to_final_parity": False,
        },
    }
    validation_path = result_root / "neon_hdf5_validation_package.json"
    validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = result_root / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "full_output_mode": "only_available",
                "schema_target": "FLUXNET",
                "network_validation_status": "pass",
                "network_missing_fields": [],
                "network_validation_summary": {"schema_target": "FLUXNET", "validation_status": "pass", "missing_fields": []},
                "neon_hdf5_validation_package": validation_payload,
                "neon_hdf5_validation_package_artifact": str(validation_path),
                "exported_files": ["export_manifest.json", "neon_hdf5_validation_package.json"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    delivery = export_delivery_package(
        runtime_root=tmp_path / "runtime_data",
        formal_report={"files": {}, "pdf_status": "fallback_html_only"},
        result_bundle={
            "export_root": str(result_root),
            "files": {
                "export_manifest": str(manifest_path),
                "neon_hdf5_validation_package_artifact": str(validation_path),
            },
        },
        evidence_bundle=None,
        compare_manifest=None,
        attribution_result=None,
        current_batch_id="batch-neon",
    )
    manifest = json.loads(Path(delivery["files"]["package_manifest"]).read_text(encoding="utf-8"))

    assert manifest["artifact_index"]["neon_hdf5_validation_package_artifact"]["packaged"] is True
    assert manifest["neon_hdf5_validation_package"]["status"] == "pass"
    assert manifest["neon_hdf5_summary"]["can_claim_neon_engineering_validation"] is True
    assert manifest["neon_hdf5_summary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert manifest["result_manifest_summary"]["neon_hdf5_validation_status"] == "pass"


def test_delivery_package_indexes_public_raw_sample_validation_package(tmp_path: Path) -> None:
    result_root = tmp_path / "result_bundle"
    result_root.mkdir(parents=True)
    validation_payload = {
        "artifact_type": "public_raw_sample_validation_package_v1",
        "status": "pass",
        "source_file": "operator_subset.csv",
        "importer_status": "pass",
        "rp_status": "pass",
        "row_count": 120,
        "rp_window_count": 1,
        "claim_boundary": {
            "can_claim_public_raw_engineering_validation": True,
            "can_claim_eddypro_raw_to_final_parity": False,
            "can_release_full_eddypro_parity": False,
        },
    }
    validation_path = result_root / "public_raw_sample_validation_package.json"
    validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = result_root / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "full_output_mode": "only_available",
                "schema_target": "FLUXNET",
                "network_validation_status": "pass",
                "network_missing_fields": [],
                "network_validation_summary": {"schema_target": "FLUXNET", "validation_status": "pass", "missing_fields": []},
                "public_raw_sample_validation_package": validation_payload,
                "public_raw_sample_validation_package_artifact": str(validation_path),
                "exported_files": ["export_manifest.json", "public_raw_sample_validation_package.json"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    delivery = export_delivery_package(
        runtime_root=tmp_path / "runtime_data",
        formal_report={"files": {}, "pdf_status": "fallback_html_only"},
        result_bundle={
            "export_root": str(result_root),
            "files": {
                "export_manifest": str(manifest_path),
                "public_raw_sample_validation_package_artifact": str(validation_path),
            },
        },
        evidence_bundle=None,
        compare_manifest=None,
        attribution_result=None,
        current_batch_id="batch-public-raw",
    )
    manifest = json.loads(Path(delivery["files"]["package_manifest"]).read_text(encoding="utf-8"))

    assert manifest["artifact_index"]["public_raw_sample_validation_package_artifact"]["packaged"] is True
    assert manifest["public_raw_sample_validation_package"]["status"] == "pass"
    assert manifest["public_raw_sample_summary"]["can_claim_public_raw_engineering_validation"] is True
    assert manifest["public_raw_sample_summary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert manifest["result_manifest_summary"]["public_raw_sample_validation_status"] == "pass"
    assert manifest["result_manifest_summary"]["public_raw_sample_rp_status"] == "pass"


def test_delivery_package_indexes_public_ec_acquisition_closure(tmp_path: Path) -> None:
    result_root = tmp_path / "result_bundle"
    result_root.mkdir(parents=True)
    closure_payload = {
        "artifact_type": "public_ec_acquisition_closure_v1",
        "status": "engineering_validation_closed_full_parity_blocked",
        "summary": {
            "candidate_count": 4,
            "downloaded_candidate_count": 1,
            "engineering_validation_pass_count": 2,
            "ready_to_register_candidate_count": 0,
        },
        "claim_boundary": {
            "can_claim_public_raw_engineering_validation": True,
            "can_claim_eddypro_raw_to_final_parity": False,
            "can_release_full_eddypro_parity": False,
        },
    }
    closure_path = result_root / "public_ec_acquisition_closure.json"
    closure_path.write_text(json.dumps(closure_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = result_root / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "full_output_mode": "only_available",
                "schema_target": "FLUXNET",
                "network_validation_status": "pass",
                "network_missing_fields": [],
                "network_validation_summary": {"schema_target": "FLUXNET", "validation_status": "pass", "missing_fields": []},
                "public_ec_acquisition_closure": closure_payload,
                "public_ec_acquisition_closure_artifact": str(closure_path),
                "exported_files": ["export_manifest.json", "public_ec_acquisition_closure.json"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    delivery = export_delivery_package(
        runtime_root=tmp_path / "runtime_data",
        formal_report={"files": {}, "pdf_status": "fallback_html_only"},
        result_bundle={
            "export_root": str(result_root),
            "files": {
                "export_manifest": str(manifest_path),
                "public_ec_acquisition_closure_artifact": str(closure_path),
            },
        },
        evidence_bundle=None,
        compare_manifest=None,
        attribution_result=None,
        current_batch_id="batch-public-ec",
    )
    manifest = json.loads(Path(delivery["files"]["package_manifest"]).read_text(encoding="utf-8"))

    assert manifest["artifact_index"]["public_ec_acquisition_closure_artifact"]["packaged"] is True
    assert manifest["public_ec_acquisition_closure"]["status"] == "engineering_validation_closed_full_parity_blocked"
    assert manifest["public_ec_acquisition_summary"]["engineering_validation_pass_count"] == 2
    assert manifest["public_ec_acquisition_summary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert manifest["public_ec_acquisition_summary"]["can_release_full_eddypro_parity"] is False
    assert manifest["result_manifest_summary"]["public_ec_acquisition_closure_status"] == "engineering_validation_closed_full_parity_blocked"
    assert manifest["result_manifest_summary"]["public_ec_acquisition_ready_to_register_candidate_count"] == 0
