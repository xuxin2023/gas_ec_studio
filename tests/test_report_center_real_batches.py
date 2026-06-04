from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication, QLabel

from app.main_window import StudioMainWindow
from app.pages.report_center_page import ReportCenterPage
from app.studio import StudioController
from core.headless_batch_runner import run_cli
from models.hf_models import FrameQuality, NormalizedHFFrame


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _make_rows(
    *,
    start: datetime | None = None,
    sample_hz: float = 10.0,
    samples: int = 512,
    lag_shift: int = 6,
    amplitude: float = 1.0,
) -> list[NormalizedHFFrame]:
    base = start or datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.6 + 0.20 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.06 * time_axis)
    vertical = amplitude * (
        np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.35 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    )
    co2_signal = np.roll(vertical, lag_shift) + 0.05 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, max(1, lag_shift - 2)) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.12 * vertical
    chamber = 25.0 + 0.3 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    case = 24.7 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=base + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(chamber[index]),
                case_temp_c=float(case[index]),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(vertical[index])}),
            )
        )
    return rows


def _run_real_batch(controller: StudioController, rows: list[NormalizedHFFrame]) -> None:
    controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
    controller.project_workspace["timing"]["block_minutes"] = 0.5
    for row in rows:
        controller.realtime_buffer.append(row)
    controller.run_spectral_qc()


def _write_official_raw_bundle(
    workspace: Path,
    *,
    fixture_id: str = "site_001_official",
    folder_name: str = "site_001",
    raw_name: str = "site_001.csv",
    site_class: str = "synthetic_official_bundle",
    write_manifest: bool = True,
    write_normalized: bool = True,
    include_official_run: bool = True,
) -> Path:
    source_root = Path.cwd() / "references" / "eddypro" / "raw_to_final"
    bundle = workspace / "references" / "eddypro" / "official_raw" / folder_name
    for child in ("raw", "metadata", "eddypro", "normalized"):
        (bundle / child).mkdir(parents=True, exist_ok=True)
    metadata_name = f"{folder_name}_metadata.json"
    shutil.copy2(source_root / "synthetic_raw_csv_001.csv", bundle / "raw" / raw_name)
    shutil.copy2(source_root / "synthetic_raw_csv_001_metadata.json", bundle / "metadata" / metadata_name)
    if write_normalized:
        shutil.copy2(source_root / "synthetic_raw_csv_001_reference.json", bundle / "normalized" / "reference.json")
        shutil.copy2(source_root / "synthetic_raw_csv_001_provenance.json", bundle / "normalized" / "provenance.json")
    (bundle / "eddypro" / "project.eddypro").write_text("eddypro project settings placeholder\n", encoding="utf-8")
    (bundle / "eddypro" / "eddypro_full_output.csv").write_text(
        "TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\n20260527080000,20260527080024,68.88091707890261,0\n",
        encoding="utf-8",
    )
    if write_manifest:
        manifest_payload = {
            "fixture_id": fixture_id,
            "site_class": site_class,
            "software": "EddyPro",
            "software_version": "7.0.9",
            "files": {
                "raw_file": f"raw/{raw_name}",
                "metadata_json": f"metadata/{metadata_name}",
                "eddypro_project_file": "eddypro/project.eddypro",
                "official_full_output": "eddypro/eddypro_full_output.csv",
                "reference_json": "normalized/reference.json",
                "provenance_json": "normalized/provenance.json",
            },
            "rp_config": {
                "sample_hz": 10.0,
                "block_minutes": 1.0,
                "steps": {"window_sampling": {"sample_hz": 10.0, "window_minutes": 1.0}},
                "rotation_mode": "none",
                "detrend_mode": "block_mean",
                "density_correction_mode": "none",
                "lag_phase": {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0},
            },
            "thresholds": {
                "flux_rel_threshold": 1e-9,
                "lag_abs_threshold_s": 1e-12,
                "wpl_rel_threshold": 0.2,
                "qc_grade_must_match": False,
            },
            "known_limitations": ["Synthetic bundle used to validate Report Center registration wiring."],
        }
        if include_official_run:
            manifest_payload["official_eddypro_run"] = {
                "software_version": "7.0.9",
                "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
                "command": "eddypro.exe --run eddypro/project.eddypro",
                "run_completed_at": "2026-05-28T10:00:00",
                "exit_code": 0,
                "project_file": "eddypro/project.eddypro",
                "output_files": ["eddypro/eddypro_full_output.csv"],
            }
        (bundle / "official_raw_fixture_bundle.json").write_text(
            json.dumps(
                manifest_payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return bundle


def test_report_center_page_handles_empty_real_state(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ReportCenterPage(controller)
        page.refresh()

        assert page.batch_combo.count() == 0
        assert page.preview_table.rowCount() >= 0
        assert page.batch_current_value.text() in {"", "--"}
    finally:
        controller.shutdown()


def test_report_center_page_displays_single_real_run(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_real_batch(controller, _make_rows())

        page = ReportCenterPage(controller)
        page.refresh()

        assert page.batch_combo.count() >= 1
        assert page.batch_combo.currentText()
        assert controller.report_center_workspace["summary"]["exportable_reports"] > 0
        assert page.preview_title_label.text()
        assert page.preview_table.rowCount() > 0
    finally:
        controller.shutdown()


def test_report_center_page_compares_two_real_runs(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_real_batch(controller, _make_rows())
        _run_real_batch(
            controller,
            _make_rows(start=datetime(2026, 4, 18, 10, 0, 0), lag_shift=8, amplitude=1.15),
        )

        result = controller.compare_report_batches()
        page = ReportCenterPage(controller)
        page.refresh()
        batch_compare = controller.report_center_workspace["batch_compare"]

        assert "message" in result
        assert batch_compare["current_batch"]
        assert batch_compare["compare_batch"]
        assert "valid_window_delta" in batch_compare["metric_deltas"]
        assert "average_lag_delta" in batch_compare["metric_deltas"]
        assert "average_correction_factor_delta" in batch_compare["metric_deltas"]
        assert "good_ratio_delta" in batch_compare["metric_deltas"]
        assert "attention_window_delta" in batch_compare["metric_deltas"]
        assert page.batch_current_value.text()
        assert page.batch_compare_value.text()
        assert page.batch_diff_value.text()
    finally:
        controller.shutdown()


def test_main_window_can_switch_to_report_center_page(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window._set_page("report_center")
        assert window.stack.currentWidget() is window.report_center_page
        window.close()
    finally:
        controller.shutdown()


def test_benchmark_cockpit_controls_rerun_pipeline_and_sync_exports(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.report_center_workspace["benchmark"] = {
            "status": "active",
            "target": "eddypro_v7",
            "reference_id": "eddypro_v7_synthetic_001",
            "flux_rel_threshold": 0.10,
            "lag_abs_threshold_s": 0.5,
            "wpl_rel_threshold": 0.20,
            "qc_grade_must_match": False,
        }
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("benchmark_cockpit")

        page = ReportCenterPage(controller)
        page.refresh()
        before_run_id = controller.current_rp_run().run_id

        page._bm_flux_thresh.setValue(0.07)
        page._bm_lag_thresh.setValue(0.3)
        page._on_bm_threshold_changed()

        after_run = controller.current_rp_run()
        assert after_run is not None
        assert after_run.run_id != before_run_id

        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        assert Path(latest_files["benchmark_summary_artifact"]).exists()
        assert Path(latest_files["parity_artifact"]).exists()
        assert Path(latest_files["reference_provenance_artifact"]).exists()
        assert Path(latest_files["network_validation_summary"]).exists()

        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        assert manifest["benchmark_status"] == "active"
        assert manifest["benchmark_reference_id"] == "eddypro_v7_synthetic_001"
        assert manifest["benchmark_thresholds"]["flux_rel_threshold"] == 0.07
        assert manifest["benchmark_thresholds"]["lag_abs_threshold_s"] == 0.3
        assert "pass_rate" in manifest
        assert "failed_fields" in manifest
        assert manifest["schema_target"] == "FLUXNET"
        assert "network_validation_status" in manifest

        cockpit = controller.report_center_workspace["reports"]["benchmark_cockpit"]
        assert cockpit["file_info"]["网络目标"] == "FLUXNET"
        assert cockpit["file_info"]["参考文件"]
    finally:
        controller.shutdown()


def test_refresh_report_center_reruns_benchmark_pipeline(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.report_center_workspace["benchmark"] = {
            "status": "active",
            "target": "eddypro_v7",
            "reference_id": "eddypro_v7_synthetic_001",
            "flux_rel_threshold": 0.10,
            "lag_abs_threshold_s": 0.5,
            "wpl_rel_threshold": 0.20,
            "qc_grade_must_match": False,
        }
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("benchmark_cockpit")
        before_run_id = controller.current_rp_run().run_id

        result = controller.refresh_report_center()

        after_run = controller.current_rp_run()
        assert after_run is not None
        assert after_run.run_id != before_run_id
        assert "交付包已导出" in result["message"]
        assert "交付包已导出" in controller.report_center_workspace["export_status"]
    finally:
        controller.shutdown()


def test_report_center_method_provenance_reflects_rp_method_rollups(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
        controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
        controller.ec_processing["steps"]["footprint"] = {
            "enabled": True,
            "method": "kljun",
            "z_m": 3.0,
            "canopy_height_m": 5.0,
        }
        controller.ec_processing["steps"]["uncertainty"]["method"] = "mann_lenschow"
        controller.ec_processing["steps"]["spectral_correction"] = {
            "enabled": True,
            "method": "massman",
            "path_length_m": 0.15,
            "sensor_sep_m": 0.20,
            "response_time_s": 0.1,
            "z_m": 3.0,
        }

        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("method_provenance")
        controller.refresh_report_center()

        page = ReportCenterPage(controller)
        page.refresh()

        report = controller.report_center_workspace["reports"]["method_provenance"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        assert "kljun" in rows_text.lower()
        assert "mann" in rows_text.lower()
        assert "massman" in rows_text.lower()
        assert "peak=" in rows_text.lower()
        assert "relative=" in rows_text.lower()
        assert "factor=" in rows_text.lower()
        assert page.preview_table.rowCount() >= 3
    finally:
        controller.shutdown()


def test_report_center_method_compare_surfaces_artifacts(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.report_center_workspace["benchmark"] = {
            "status": "active",
            "target": "eddypro_v7",
            "reference_id": "eddypro_v7_synthetic_001",
            "flux_rel_threshold": 0.10,
            "lag_abs_threshold_s": 0.5,
            "wpl_rel_threshold": 0.20,
            "qc_grade_must_match": False,
        }
        controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
        controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
        controller.ec_processing["steps"]["footprint"]["grid_enabled"] = True
        controller.ec_processing["steps"]["method_compare"] = {
            "enabled": True,
            "families": ["footprint", "uncertainty", "spectral_correction"],
            "deviation_threshold": 0.20,
            "max_samples": 2048,
            "footprint_methods": ["kljun", "kormann_meixner", "hsieh"],
            "uncertainty_methods": ["mann_lenschow", "finkelstein_sims"],
            "spectral_correction_methods": ["massman", "horst", "ibrom", "fratini"],
        }

        _run_real_batch(controller, _make_rows(samples=900))
        controller.run_ec_processing()
        controller.set_report_nav_section("method_compare")
        controller.export_current_report()
        controller.refresh_report_center()

        page = ReportCenterPage(controller)
        page.refresh()

        report = controller.report_center_workspace["reports"]["method_compare"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        assert report["title"] == "Method Compare"
        assert "footprint" in rows_text
        assert "uncertainty" in rows_text
        assert "spectral_correction" in rows_text
        assert "performance:" in rows_text
        assert "parity:rotation" in rows_text
        assert "processing_settings" in rows_text
        assert "missing_from_reference_metadata" in rows_text
        assert "Method Compare Artifact" in report["file_info"]
        assert "Method Parity Matrix" in report["file_info"]
        assert "Footprint 2D Contour" in report["file_info"]
        assert "Performance Profile" in report["file_info"]
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        assert Path(latest_files["method_parity_matrix_artifact"]).exists()
        assert Path(latest_files["footprint_2d_contour_svg"]).exists()
        assert Path(latest_files["performance_profile_artifact"]).exists()
        assert page.preview_table.rowCount() >= 3
    finally:
        controller.shutdown()


def test_report_center_computation_surface_uses_stress_suite_artifact(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_real_batch(controller, _make_rows(samples=900))
        controller.run_ec_processing()
        controller.set_report_nav_section("computation_surface")
        controller.export_current_report()
        controller.refresh_report_center()

        page = ReportCenterPage(controller)
        page.refresh()

        report = controller.report_center_workspace["reports"]["computation_surface"]
        metrics = dict(report["metrics"])
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        stress_suite = json.loads(Path(latest_files["eddypro_computation_stress_suite_artifact"]).read_text(encoding="utf-8"))

        assert report["report_key"] == "computation_surface"
        assert metrics["surface_status"] == "ready"
        assert metrics["ready_families"] == "9 / 9"
        assert metrics["failed_cases"] == "0"
        assert stress_suite["computation_surface"]["status"] == "ready"
        assert "rotation_lag" in rows_text
        assert "ch4_li7700" in rows_text
        assert "Computation Stress Suite" in report["file_info"]
        assert Path(latest_files["eddypro_computation_scope_audit_artifact"]).exists()
        assert "computation_surface" in page.report_items
        assert page.preview_table.rowCount() >= 7
    finally:
        controller.shutdown()


def test_report_center_fixture_pack_surfaces_validated_eddypro_assets(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.export_current_report()
        controller.set_report_nav_section("fixture_pack")
        public_refresh = controller.refresh_public_eddypro_fixtures_for_report_center()
        assert public_refresh["status"] == "pass"
        controller.refresh_report_center()

        page = ReportCenterPage(controller)
        page.refresh()

        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]

        assert report["report_key"] == "fixture_pack"
        assert report["metrics"][0] == ("status", "pass")
        assert "eddypro_v7_real_temperate_forest_001" in rows_text
        assert "ygas_protocol_manual_001" in rows_text
        assert "real_reference_windows" in rows_text
        assert "public_eddypro_fixture_catalog" in rows_text
        assert "public_eddypro_acquisition" in rows_text
        assert "official_eddypro_executable_run" in rows_text
        assert "official_eddypro_run_checklist" in rows_text
        assert "official_run_normalization" in rows_text
        assert "official_run_norm=normalized" in rows_text
        assert report["public_eddypro_fixture_catalog"]["status"] == "pass"
        assert report["public_eddypro_fixture_catalog"]["fixture_count"] == 6
        assert report["public_eddypro_fixture_acquisition"]["status"] == "pass"
        assert "Fixture Pack Artifact" in report["file_info"]
        assert "Public EddyPro Fixture Catalog" in report["file_info"]
        assert "Public EddyPro Fixture Acquisition" in report["file_info"]
        assert Path(latest_files["fixture_pack_summary_artifact"]).exists()
        assert Path(report["file_info"]["Public EddyPro Fixture Catalog"]).exists()
        assert Path(report["file_info"]["Public EddyPro Fixture Acquisition"]).exists()
        assert page.preview_title_label.text() == "Fixture Pack"
        assert page.preview_table.rowCount() >= 4
    finally:
        controller.shutdown()


def test_report_center_registers_official_raw_bundle_as_active_fixture_pack(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        bundle = _write_official_raw_bundle(tmp_path)
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")

        inspection = controller.inspect_official_raw_bundle_for_report_center(str(bundle))
        registration = controller.register_official_raw_bundle_for_report_center(str(bundle))
        pack_artifact = Path(controller.report_center_workspace["official_raw_bundle"]["evidence_pack_artifact"])
        pack_payload = json.loads(pack_artifact.read_text(encoding="utf-8"))
        pack_payload["acceptance_commands"] = [
            "python -m pytest tests/test_eddypro_capability_matrix.py::test_capability_matrix_is_truthful_about_full_eddypro_parity -q"
        ]
        pack_artifact.write_text(json.dumps(pack_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        acceptance = controller.run_official_raw_evidence_acceptance_for_report_center(str(bundle))

        page = ReportCenterPage(controller)
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        official_state = controller.report_center_workspace["official_raw_bundle"]
        active_pack = Path(official_state["registered_pack_path"])
        parity = official_state["parity"]
        acquisition = official_state["acquisition_validation"]
        evidence_pack = official_state["evidence_pack"]

        assert inspection["status"] == "ready_for_registration"
        assert inspection["acquisition_validation"]["status"] == "ready_for_registration_pending_parity"
        assert registration["status"] == "registered"
        assert active_pack.exists()
        assert parity["status"] == "pass"
        assert acquisition["status"] == "closure_ready"
        assert acquisition["gate_status"] == "pass"
        assert Path(official_state["acquisition_validation_artifact"]).exists()
        assert evidence_pack["artifact_type"] == "official_raw_fixture_evidence_pack_v1"
        assert evidence_pack["status"] == "complete"
        assert acceptance["acceptance_status"] == "pass"
        assert official_state["acceptance_status"] == "pass"
        assert evidence_pack["acceptance_run"]["passed_count"] == 1
        assert Path(official_state["evidence_pack_artifact"]).exists()
        assert parity["fixture_id"] == "site_001_official"
        assert parity["pass_rate"] == 1.0
        assert parity["failed_fields"] == []
        assert Path(parity["artifact"]).exists()
        assert controller.report_center_workspace["benchmark"]["official_raw_fixture_id"] == "site_001_official"
        assert controller.report_center_workspace["benchmark"]["official_raw_pass_rate"] == 1.0
        assert controller.report_center_workspace["benchmark"]["official_raw_failed_fields"] == []
        assert "site_001_official" in rows_text
        assert "registration" in rows_text
        assert "active_fixture_pack" in rows_text
        assert "official_raw_parity" in rows_text
        assert "official_raw_acquisition_validation" in rows_text
        assert "official_raw_evidence_pack" in rows_text
        assert "official_raw_acceptance_claim_gate" in rows_text
        assert "official_raw_acceptance_run" in rows_text
        assert "pass_rate=100.0%" in rows_text
        assert hasattr(page, "_official_bundle_controls_card")
        assert not page._official_bundle_controls_card.isHidden()

        controller.set_report_nav_section("benchmark_cockpit")
        controller.refresh_report_center()
        cockpit = controller.report_center_workspace["reports"]["benchmark_cockpit"]
        cockpit_rows = " ".join(" ".join(str(cell) for cell in row) for row in cockpit["table_rows"])
        assert "official_raw.fixture_id" in cockpit_rows
        assert "site_001_official" in cockpit_rows
        assert "official_raw.pass_rate" in cockpit_rows
        assert "100.0%" in cockpit_rows

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        assert manifest["fixture_pack_path"] == str(active_pack)
        assert manifest["official_raw_fixture_manifest"]["official_raw_to_final_ready_count"] >= 1
        assert manifest["official_raw_benchmark"]["fixture_id"] == "site_001_official"
        assert manifest["official_raw_benchmark"]["parity_status"] == "pass"
        assert manifest["official_raw_benchmark"]["pass_rate"] == 1.0
        assert manifest["official_raw_benchmark"]["failed_fields"] == []
        assert manifest["official_raw_evidence_pack_acceptance_status"] == "pass"
    finally:
        controller.shutdown()


def test_report_center_batch_registers_official_raw_bundle_tree(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        root = tmp_path / "references" / "eddypro" / "official_raw"
        _write_official_raw_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001", raw_name="site_001.csv")
        _write_official_raw_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.csv", site_class="synthetic_grassland_bundle")
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")

        discovery = controller.inspect_official_raw_bundle_tree_for_report_center(str(root))
        registration = controller.register_official_raw_bundle_tree_for_report_center(str(root))

        page = ReportCenterPage(controller)
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        state = controller.report_center_workspace["official_raw_bundle"]
        batch_parity = state["batch_parity"]
        active_pack = Path(state["registered_pack_path"])

        assert discovery["status"] == "ready"
        assert discovery["ready_count"] == 2
        assert controller.report_center_workspace["official_raw_bundle"]["repair_plan"]["status"] == "complete"
        assert registration["status"] == "registered"
        assert registration["registered_count"] == 2
        assert active_pack.exists()
        assert batch_parity["status"] == "pass"
        assert batch_parity["registered_count"] >= 2
        assert batch_parity["pass_count"] >= 2
        assert Path(batch_parity["artifact"]).exists()
        assert controller.report_center_workspace["benchmark"]["official_raw_batch_status"] == "pass"
        assert controller.report_center_workspace["benchmark"]["official_raw_batch_pass_count"] >= 2
        assert hasattr(page, "_official_bundle_register_tree")
        assert "batch_discovery" in rows_text
        assert "official_raw_repair_plan" in rows_text
        assert "batch_registration" in rows_text
        assert "official_raw_batch_parity" in rows_text
        assert "site_001_official" in rows_text
        assert "site_002_official" in rows_text

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        assert manifest["fixture_pack_path"] == str(active_pack)
        assert manifest["official_raw_fixture_manifest"]["official_raw_to_final_ready_count"] >= 2
        assert manifest["official_raw_repair_plan"]["status"] == "complete"
        assert manifest["official_raw_repair_plan_status"] == "complete"
        assert Path(latest_files["official_raw_repair_plan_artifact"]).exists()
        assert manifest["official_raw_fixture_manifest"]["evidence_matrix"]["raw_format_counts"]["csv"] >= 2
        assert manifest["official_raw_fixture_manifest"]["evidence_matrix"]["official_eddypro_run_gate_counts"]["pass"] >= 2
        assert manifest["official_raw_benchmark"]["batch_status"] == "pass"
        assert manifest["official_raw_benchmark"]["batch_pass_count"] >= 2
    finally:
        controller.shutdown()


def test_report_center_captures_official_eddypro_run_sidecar(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        bundle = _write_official_raw_bundle(
            tmp_path,
            fixture_id="capture_site_official",
            folder_name="capture_site",
            raw_name="capture_site.csv",
            include_official_run=False,
        )
        output_file = bundle / "eddypro" / "eddypro_full_output.csv"
        output_file.unlink()
        fake_eddypro = tmp_path / "fake_eddypro_report_center.py"
        fake_eddypro.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n20260527080000,20260527080024,68.88091707890261,0\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")
        page = ReportCenterPage(controller)
        page.refresh()

        capture = controller.capture_official_eddypro_run_for_report_center(
            str(bundle),
            command=f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
            software_version="7.0.9",
            output_files="eddypro/eddypro_full_output.csv",
        )
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        state = controller.report_center_workspace["official_raw_bundle"]

        assert hasattr(page, "_official_run_capture")
        assert capture["status"] == "pass"
        assert capture["gate_status"] == "pass"
        assert Path(capture["sidecar_path"]).exists()
        assert Path(state["official_run_capture_artifact"]).exists()
        assert state["official_eddypro_run"]["gate_status"] == "pass"
        assert state["acquisition_validation"]["official_eddypro_run"]["gate_status"] == "pass"
        assert state["evidence_pack"]["official_eddypro_run"]["gate_status"] == "pass"
        assert "official_eddypro_run_capture" in rows_text
        assert "gate=pass" in rows_text

        inspection = controller.inspect_official_raw_bundle_for_report_center(str(bundle))
        assert inspection["acquisition_validation"]["official_eddypro_run"]["gate_status"] == "pass"
    finally:
        controller.shutdown()


def test_report_center_runs_official_raw_closure_pipeline(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        bundle = _write_official_raw_bundle(
            tmp_path,
            fixture_id="closure_site_official",
            folder_name="closure_site",
            raw_name="closure_site.csv",
            include_official_run=False,
        )
        output_file = bundle / "eddypro" / "eddypro_full_output.csv"
        output_file.unlink()
        fake_eddypro = tmp_path / "fake_eddypro_closure.py"
        fake_eddypro.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n20260527080000,20260527080024,68.88091707890261,0\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")
        page = ReportCenterPage(controller)
        page.refresh()

        closure = controller.run_official_raw_closure_for_report_center(
            str(bundle),
            command=f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
            software_version="7.0.9",
            output_files="eddypro/eddypro_full_output.csv",
            replace=True,
            acceptance_commands=[
                "python -m pytest tests/test_eddypro_capability_matrix.py::test_capability_matrix_sources_are_official_licor_urls -q"
            ],
            acceptance_timeout_s=120,
        )
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        state = controller.report_center_workspace["official_raw_bundle"]

        assert hasattr(page, "_official_closure_run")
        assert closure["status"] == "pass"
        assert closure["gate_status"] == "pass"
        assert closure["closure_run"]["blockers"] == []
        assert Path(closure["artifact"]).exists()
        assert state["closure_run"]["status"] == "pass"
        assert state["parity"]["status"] == "pass"
        assert state["evidence_pack"]["acceptance_status"] == "pass"
        assert "official_raw_closure_run" in rows_text
        assert "gate=pass" in rows_text

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        assert manifest["official_raw_closure_run_status"] == "pass"
        assert manifest["official_raw_closure_run_gate_status"] == "pass"
        assert manifest["official_raw_closure_run"]["fixture_id"] == "closure_site_official"
        assert Path(latest_files["official_raw_closure_run_artifact"]).exists()
    finally:
        controller.shutdown()


def test_headless_cli_runs_official_raw_closure_pipeline(tmp_path) -> None:
    bundle = _write_official_raw_bundle(
        tmp_path,
        fixture_id="headless_closure_site_official",
        folder_name="headless_closure_site",
        raw_name="headless_closure_site.csv",
        include_official_run=False,
    )
    output_file = bundle / "eddypro" / "eddypro_full_output.csv"
    output_file.unlink()
    fake_eddypro = tmp_path / "fake_eddypro_headless_closure.py"
    fake_eddypro.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n20260527080000,20260527080024,68.88091707890261,0\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fixture_pack = tmp_path / "fixture_pack_v1.json"
    fixture_pack.write_text(
        json.dumps({"fixture_pack_id": "headless_closure_pack", "version": "1.0", "assets": []}, indent=2),
        encoding="utf-8",
    )
    registered_pack = tmp_path / "fixture_pack_v1_registered.json"
    closure_artifact = tmp_path / "official_raw_closure_run.json"

    exit_code = run_cli(
        [
            "--run-official-raw-closure",
            str(bundle),
            "--official-run-command",
            f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
            "--official-run-software-version",
            "7.0.9",
            "--official-run-output-files",
            "eddypro/eddypro_full_output.csv",
            "--fixture-pack",
            str(fixture_pack),
            "--closure-fixture-pack-output",
            str(registered_pack),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(closure_artifact),
            "--closure-acceptance-command",
            "python -m pytest tests/test_eddypro_capability_matrix.py::test_capability_matrix_sources_are_official_licor_urls -q",
            "--acceptance-timeout-s",
            "120",
        ]
    )

    payload = json.loads(closure_artifact.read_text(encoding="utf-8"))
    evidence_pack = json.loads(Path(payload["evidence_pack_artifact"]).read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["artifact_type"] == "official_raw_closure_run_v1"
    assert payload["status"] == "pass"
    assert payload["gate_status"] == "pass"
    assert payload["fixture_id"] == "headless_closure_site_official"
    assert payload["raw_to_final_parity_status"] == "pass"
    assert payload["acceptance_status"] == "pass"
    assert payload["blockers"] == []
    assert registered_pack.exists()
    assert evidence_pack["acceptance_gate_status"] == "pass"


def test_report_center_official_raw_matrix_filters_and_fixture_actions(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        root = tmp_path / "references" / "eddypro" / "official_raw"
        _write_official_raw_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001", raw_name="site_001.csv")
        _write_official_raw_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.csv", site_class="synthetic_grassland_bundle")
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")
        controller.register_official_raw_bundle_tree_for_report_center(str(root))

        filter_result = controller.set_official_raw_matrix_filters_for_report_center(
            raw_format="csv",
            site_class="synthetic_grassland_bundle",
            parity_status="pass",
        )
        page = ReportCenterPage(controller)
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        matrix_rows = [row for row in report["table_rows"] if str(row[0]).startswith("matrix:")]

        assert filter_result["filters"] == {
            "raw_format": "csv",
            "site_class": "synthetic_grassland_bundle",
            "parity_status": "pass",
        }
        assert len(matrix_rows) == 1
        assert matrix_rows[0][0] == "matrix:site_002_official"
        assert hasattr(page, "_official_matrix_format")
        assert hasattr(page, "_official_fixture_detail")
        assert hasattr(page, "_official_fixture_rerun")
        assert hasattr(page, "_official_fixture_disable")
        assert hasattr(page, "_official_fixture_replace")

        detail = controller.inspect_official_raw_fixture_detail_for_report_center("site_002_official")
        assert detail["status"] == "pass"
        assert Path(detail["artifact"]).exists()
        assert detail["detail"]["fixture_id"] == "site_002_official"
        assert detail["detail"]["file_checks"]["status"] == "ok"
        assert detail["detail"]["normalization"]["source_file"]

        rerun = controller.rerun_official_raw_fixture_for_report_center("site_002_official")
        assert rerun["status"] == "pass"
        assert Path(rerun["detail_artifact"]).exists()
        state = controller.report_center_workspace["official_raw_bundle"]
        assert state["selected_parity"]["fixture_id"] == "site_002_official"
        assert Path(state["selected_parity"]["artifact"]).exists()
        assert Path(state["selected_fixture_detail_artifact"]).exists()

        disable = controller.disable_official_raw_fixture_for_report_center("site_002_official")
        assert disable["status"] == "disabled"
        controller.set_official_raw_matrix_filters_for_report_center(site_class="synthetic_grassland_bundle")
        controller.refresh_report_center()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        matrix_rows = [row for row in report["table_rows"] if str(row[0]).startswith("matrix:")]
        matrix_text = " ".join(" ".join(str(cell) for cell in row) for row in matrix_rows)

        assert "matrix:site_002_official" in matrix_text
        assert "disabled" in matrix_text
        assert controller.report_center_workspace["benchmark"]["official_raw_batch_status"] == "pass"

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        official_manifest = manifest["official_raw_fixture_manifest"]
        official_detail = manifest["official_raw_fixture_detail"]
        matrix_by_id = {
            row["fixture_id"]: row
            for row in official_manifest["evidence_matrix"]["rows"]
        }
        assert official_manifest["disabled_fixture_count"] >= 1
        assert matrix_by_id["site_002_official"]["readiness_level"] == "disabled"
        assert matrix_by_id["site_002_official"]["disabled"] is True
        assert Path(latest_files["official_raw_fixture_detail_artifact"]).exists()
        assert official_detail["fixture_id"] == "site_002_official"
        assert official_detail["readiness_level"] == "disabled"
        assert official_detail["disabled"] is True
        assert manifest["official_raw_benchmark"]["batch_status"] == "pass"
    finally:
        controller.shutdown()


def test_report_center_replaces_official_raw_fixture_and_refreshes_detail(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        root = tmp_path / "references" / "eddypro" / "official_raw"
        _write_official_raw_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001", raw_name="site_001.csv")
        _write_official_raw_bundle(
            tmp_path,
            fixture_id="site_002_official",
            folder_name="site_002",
            raw_name="site_002.csv",
            site_class="synthetic_grassland_bundle",
        )
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")
        controller.register_official_raw_bundle_tree_for_report_center(str(root))
        disabled = controller.disable_official_raw_fixture_for_report_center("site_002_official")
        assert disabled["status"] == "disabled"

        replacement = _write_official_raw_bundle(
            tmp_path,
            fixture_id="site_002_official",
            folder_name="site_002_replacement",
            raw_name="site_002_replacement.csv",
            site_class="replacement_grassland_bundle",
        )
        replaced = controller.replace_official_raw_fixture_for_report_center(
            "site_002_official",
            str(replacement),
            replace=True,
        )
        assert replaced["status"] == "registered"
        state = controller.report_center_workspace["official_raw_bundle"]
        assert state["parity"]["status"] == "pass"
        assert state["selected_fixture_detail"]["site_class"] == "replacement_grassland_bundle"
        assert state["selected_fixture_detail"]["disabled"] is False
        assert Path(state["selected_fixture_detail_artifact"]).exists()

        controller.set_official_raw_matrix_filters_for_report_center(site_class="replacement_grassland_bundle")
        page = ReportCenterPage(controller)
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        matrix_text = " ".join(
            " ".join(str(cell) for cell in row)
            for row in report["table_rows"]
            if str(row[0]).startswith("matrix:")
        )
        conclusion_text = " ".join(label.text() for label in page.conclusion_card.findChildren(QLabel))

        assert "matrix:site_002_official" in matrix_text
        assert "replacement_grassland_bundle" in matrix_text
        assert "Official Raw Fixture Detail: site_002_official" in conclusion_text
        assert "replacement_grassland_bundle" in conclusion_text
        assert "file_check=ok" in conclusion_text

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        official_detail = manifest["official_raw_fixture_detail"]
        matrix_by_id = {
            row["fixture_id"]: row
            for row in manifest["official_raw_fixture_manifest"]["evidence_matrix"]["rows"]
        }

        assert matrix_by_id["site_002_official"]["site_class"] == "replacement_grassland_bundle"
        assert matrix_by_id["site_002_official"]["readiness_level"] == "official_raw_to_final_ready"
        assert matrix_by_id["site_002_official"]["disabled"] is False
        assert official_detail["fixture_id"] == "site_002_official"
        assert official_detail["site_class"] == "replacement_grassland_bundle"
        assert official_detail["readiness_level"] == "official_raw_to_final_ready"
        assert official_detail["disabled"] is False
        assert manifest["official_raw_benchmark"]["parity_status"] == "pass"
        assert Path(latest_files["official_raw_fixture_detail_artifact"]).exists()
    finally:
        controller.shutdown()


def test_report_center_builds_manifest_for_manifestless_official_raw_bundle(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        bundle = _write_official_raw_bundle(
            tmp_path,
            fixture_id="auto_site_official",
            folder_name="auto_site",
            raw_name="auto_site.csv",
            site_class="auto_generated_site",
            write_manifest=False,
            write_normalized=False,
        )
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")

        build = controller.build_official_raw_bundle_manifest_for_report_center(
            str(bundle),
            fixture_id="auto_site_official",
            site_class="auto_generated_site",
            software_version="7.0.9",
        )
        assert build["status"] == "manifest_ready"
        assert build["normalization_result"]["status"] == "normalized"
        assert build["normalization_result"]["reference_json"] == "normalized/reference.json"
        assert Path(build["manifest_path"]).exists()
        assert (bundle / "normalized" / "reference.json").exists()
        assert (bundle / "normalized" / "provenance.json").exists()

        page = ReportCenterPage(controller)
        page.refresh()
        assert hasattr(page, "_official_bundle_build_manifest")
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        assert "manifest_build" in rows_text
        assert "auto_site_official" in rows_text

        registration = controller.register_official_raw_bundle_for_report_center(str(bundle))
        assert registration["status"] == "registered"
        state = controller.report_center_workspace["official_raw_bundle"]
        assert state["parity"]["status"] == "pass"
        assert state["selected_fixture_detail"]["fixture_id"] == "auto_site_official"
        assert state["selected_fixture_detail"]["site_class"] == "auto_generated_site"
        normalization = state["selected_fixture_detail"]["normalization"]
        assert normalization["status"] == "ready"
        assert normalization["source_file"].endswith("eddypro_full_output.csv")
        assert normalization["required_fields_present"] is True
        assert normalization["qc_mapping_strategy"] == "EddyPro 0/1/2 -> gas_ec_studio A/B/C"

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        official_detail = manifest["official_raw_fixture_detail"]
        assert official_detail["fixture_id"] == "auto_site_official"
        assert official_detail["site_class"] == "auto_generated_site"
        assert official_detail["file_checks"]["status"] == "ok"
        assert manifest["official_raw_normalization_status"] == "ready"
        assert manifest["official_raw_normalization"]["source_file"].endswith("eddypro_full_output.csv")
        assert manifest["official_raw_fixture_manifest"]["evidence_matrix"]["normalization_status_counts"]["ready"] >= 1
        assert manifest["official_raw_benchmark"]["parity_status"] == "pass"
    finally:
        controller.shutdown()


def test_report_center_registers_manifestless_official_raw_bundle_tree(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        root = tmp_path / "references" / "eddypro" / "official_raw"
        _write_official_raw_bundle(
            tmp_path,
            fixture_id="site_001_official",
            folder_name="site_001",
            raw_name="site_001.csv",
            write_manifest=False,
            write_normalized=False,
        )
        _write_official_raw_bundle(
            tmp_path,
            fixture_id="site_002_official",
            folder_name="site_002",
            raw_name="site_002.csv",
            site_class="synthetic_grassland_bundle",
            write_manifest=False,
            write_normalized=False,
        )
        _run_real_batch(controller, _make_rows())
        controller.run_ec_processing()
        controller.set_report_nav_section("fixture_pack")

        build = controller.build_official_raw_bundle_tree_manifests_for_report_center(
            str(root),
            site_class="auto_tree_site",
            software_version="7.0.9",
        )
        registration = controller.register_official_raw_bundle_tree_for_report_center(str(root))

        page = ReportCenterPage(controller)
        page.refresh()
        report = controller.report_center_workspace["reports"]["fixture_pack"]
        rows_text = " ".join(" ".join(str(cell) for cell in row) for row in report["table_rows"])
        state = controller.report_center_workspace["official_raw_bundle"]
        active_pack = Path(state["registered_pack_path"])

        assert build["status"] == "ready"
        assert build["generated_count"] == 2
        assert registration["status"] == "registered"
        assert registration["manifest_generated_count"] == 0
        assert registration["registered_count"] == 2
        assert active_pack.exists()
        assert state["batch_parity"]["status"] == "pass"
        assert state["manifest_batch_build"]["ready_count"] == 2
        assert "manifest_batch_build" in rows_text
        assert "normalization=ready" in rows_text
        assert hasattr(page, "_official_bundle_build_tree_manifests")

        controller.export_current_report()
        latest_files = controller.current_spectral_run().artifacts["result_exports"]["latest"]["files"]
        manifest = json.loads(Path(latest_files["export_manifest"]).read_text(encoding="utf-8"))
        matrix = manifest["official_raw_fixture_manifest"]["evidence_matrix"]
        assert matrix["normalization_status_counts"]["ready"] >= 2
        assert manifest["official_raw_fixture_manifest"]["official_raw_to_final_ready_count"] >= 2
        assert manifest["official_raw_normalization_status"] == "ready"
    finally:
        controller.shutdown()
