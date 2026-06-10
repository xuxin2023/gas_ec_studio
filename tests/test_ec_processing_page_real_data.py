from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.ec_processing_page import ECProcessingPage
from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


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


def test_ec_processing_page_refreshes_with_empty_state(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ECProcessingPage(controller)
        page.refresh()

        assert "尚未生成真实 RP 结果" in page.run_summary_label.text()
        assert page.run_bar.property("cardRole") == "command"
        assert page.tree_card.property("cardRole") == "rail"
        assert page.desktop_rail.property("cardRole") == "rail"
        assert page.cockpit_card.property("cardRole") == "cockpit"
        assert page.readiness_card.property("cardRole") == "panel"
        assert page.workflow_lens_card.property("cardRole") == "panel"
        assert page.output_coverage_card.property("cardRole") == "panel"
        assert page.method_family_card.property("cardRole") == "cockpit"
        assert page.method_family_stack.count() == 3
        assert page.method_family_buttons["footprint"].isChecked() is True
        assert page.cockpit_method_value.property("compactMetric") is True
        assert page.step_tree.objectName() == "workflowTree"
        assert set(page.workflow_lens_buttons) == {"project", "core", "advanced", "delivery"}
        assert "schema=FLUXNET" in page.coverage_values["network"].text()
        assert "footprint=kljun" in page.coverage_values["methods"].text()
        assert "footprint=kljun" in page.method_snapshot_label.text()
        assert "uncertainty=mann_lenschow" in page.method_snapshot_label.text()
        assert page.method_family_gate_chip.text() in {"Ready", "Review"}
        page._show_method_family("spectral")
        assert page.method_family_stack.currentWidget() is page.spectral_card
        assert page.method_family_buttons["spectral"].isChecked() is True
        page.footprint_zm_spin.setValue(1.0)
        page.footprint_canopy_spin.setValue(5.0)
        page._refresh_uncertainty_preview()
        assert "z_m > canopy_height_m" in page.method_validation_label.text()
        assert page.method_family_gate_chip.text() == "Review"
        page.workflow_lens_buttons["advanced"].click()
        assert controller.ec_nav_step == "crosswind_correction"
        assert page.workflow_lens_buttons["advanced"].property("variant") == "primary"
        assert "kljun" in page.cockpit_method_value.text()
        assert page.cockpit_result_value.text() == "尚未运行"
        assert page.cockpit_delivery_value.text() == "FLUXNET"
        assert page.window_readiness_value.text() == "36,000"
        assert "massman" in page.method_readiness_note.text()
        assert page.delivery_readiness_value.text() == "FLUXNET"
        assert page.window_plan_curve.xData is not None and len(page.window_plan_curve.xData) == 4
        assert page.lag_curve.xData is None or len(page.lag_curve.xData) == 0
        assert page.density_before_curve.xData is None or len(page.density_before_curve.xData) == 0
    finally:
        controller.shutdown()


def test_ec_processing_page_refreshes_with_real_rp_result(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
        controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
        for row in _make_rows():
            controller.realtime_buffer.append(row)
        controller.run_ec_processing()

        page = ECProcessingPage(controller)
        page.refresh()

        assert controller.current_rp_run() is not None
        assert page.lag_curve.xData is not None and len(page.lag_curve.xData) > 0
        assert page.detrend_raw_curve.xData is not None and len(page.detrend_raw_curve.xData) > 0
        assert page.detrend_primary_curve.xData is not None and len(page.detrend_primary_curve.xData) > 0
        assert page.density_before_curve.xData is not None and len(page.density_before_curve.xData) > 0
        assert page.steadiness_score_curve.xData is not None and len(page.steadiness_score_curve.xData) > 0
        assert page.turbulence_ustar_curve.xData is not None and len(page.turbulence_ustar_curve.xData) > 0
        assert page.turbulence_score_curve.xData is not None and len(page.turbulence_score_curve.xData) > 0
        assert page.window_samples_label.text() != "--"
        assert "lag=" in page.lag_note_label.text()
        assert "u*=" in page.turbulence_preview_label.text()
        assert page.uncertainty_sampling_label.text() != "真实 RP 未提供"
        assert page.full_output_mode_combo.currentText() == "only_available"
        assert page.cockpit_result_value.text() != "尚未运行"
        assert page.cockpit_uncertainty_value.text().startswith("±")
        assert page.cockpit_delivery_value.text() == "FLUXNET"
        assert "windows=" in page.cockpit_result_note.text()
        assert page.window_readiness_value.text() != "36,000"
        assert "window=" in page.window_readiness_note.text()
        assert page.delivery_readiness_value.text() == "FLUXNET"
        assert page.window_plan_curve.xData is not None and len(page.window_plan_curve.xData) > 0
        assert "真实窗口" in page.window_plan_note.text()
    finally:
        controller.shutdown()


def test_main_window_can_switch_to_ec_processing_page(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window._set_page("ec_processing")
        assert window.stack.currentWidget() is window.ec_processing_page
        window._set_page("report_center")
        assert window.stack.currentWidget() is window.report_center_page
        window.close()
    finally:
        controller.shutdown()
