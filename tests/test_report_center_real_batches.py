from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.report_center_page import ReportCenterPage
from app.studio import StudioController
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
