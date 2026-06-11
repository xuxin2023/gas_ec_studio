from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.ec_processing_page import ECProcessingPage
from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_no_visible_competitor_name,
    assert_no_visual_overlap,
    widget_bounds,
)


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

        assert page.property("pageSurface") is True
        assert "尚未生成真实 RP 结果" in page.run_summary_label.text()
        assert page.run_bar.property("cardRole") == "command"
        assert page.rp_closure_deck.property("cardRole") == "cockpit"
        assert page.rp_closure_deck.property("deckRole") == "rpClosureDeck"
        assert page.rp_closure_deck.maximumHeight() == 146
        assert page.rp_closure_chip.text().startswith("待运行")
        assert set(page.rp_closure_tiles) == {"run", "flux", "uncertainty", "methods", "benchmark", "network"}
        assert all(tile.property("cardRole") == "tile" for tile in page.rp_closure_tiles.values())
        assert all(value.property("compactMetric") is True for value in page.rp_closure_values.values())
        assert all(chip.property("closureStage") is True for chip in page.rp_closure_chips.values())
        assert all(chip.minimumHeight() == 22 for chip in page.rp_closure_chips.values())
        assert page.rp_closure_values["run"].text() == "待运行"
        assert page.rp_closure_values["flux"].text() == "待生成"
        assert page.rp_closure_values["network"].text() == "FLUXNET"
        assert page.tree_card.property("cardRole") == "rail"
        assert page.desktop_rail.property("cardRole") == "rail"
        assert page.desktop_rail.minimumWidth() == 280
        assert page.desktop_rail.maximumWidth() == 340
        assert page.desktop_rail_scroll.objectName() == "railScroll"
        assert page.desktop_rail_scroll.widgetResizable() is True
        assert page.desktop_rail_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.desktop_rail_scroll.widget() is page.desktop_rail_body
        assert page.desktop_rail_inspector.property("deckRole") == "ecRailInspector"
        assert page.desktop_rail_stack.count() == 3
        assert page.desktop_rail_stack.currentWidget() is page.workflow_lens_card
        assert page.desktop_rail_mode_buttons["workflow"].isChecked() is True
        assert page.cockpit_card.property("cardRole") == "cockpit"
        assert page.cockpit_card.property("deckRole") == "processingCockpitDeck"
        assert page.rail_focus_card.property("cardRole") == "panel"
        assert page.rail_focus_stack.count() == 2
        assert page.rail_focus_stack.currentWidget() is page.readiness_card
        assert page.rail_focus_buttons["readiness"].isChecked() is True
        assert page.readiness_card.property("cardRole") == "panel"
        assert page.workflow_lens_card.property("cardRole") == "panel"
        assert page.workflow_lens_card.property("deckRole") == "workflowLensCompact"
        assert page.workflow_lens_card.maximumHeight() == 190
        assert page.output_coverage_card.property("cardRole") == "panel"
        assert page.method_family_card.property("cardRole") == "cockpit"
        assert page.method_support_card.property("cardRole") == "panel"
        assert page.method_support_stack.count() == 2
        assert page.method_support_stack.currentWidget() is page.primary_analyzer_card
        assert page.method_support_buttons["primary"].isChecked() is True
        assert page.method_result_card.property("cardRole") == "cockpit"
        assert page.method_result_note_card.property("cardRole") == "console"
        assert page.method_result_chip.property("chipTone") == "accent"
        assert page.method_family_stack.count() == 3
        assert page.method_family_buttons["footprint"].isChecked() is True
        assert all(
            page.content_stack.widget(index).horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            for index in page.step_indexes.values()
        )
        assert page.window_cockpit_card.property("cardRole") == "cockpit"
        assert page.window_cockpit_card.property("deckRole") == "windowSamplingCockpit"
        assert page.window_cockpit_card.maximumHeight() == 118
        assert set(page.window_cockpit_values) == {"duration", "frequency", "samples", "batches"}
        assert page.window_cockpit_values["duration"].text() == "30 min"
        assert page.window_cockpit_values["frequency"].text() == "20 Hz"
        assert page.window_cockpit_values["samples"].text() == "36,000"
        assert page.window_cockpit_values["batches"].text() == "preview x4"
        assert page.window_cockpit_tiles["batches"].property("evidenceTone") == "warning"
        assert page.cockpit_method_value.property("compactMetric") is True
        assert page.step_tree.objectName() == "workflowTree"
        assert set(page.workflow_lens_buttons) == {"project", "core", "advanced", "delivery"}
        assert page.workflow_lens_buttons["project"].text() == "项目"
        assert page.workflow_lens_active_note.text() != "--"
        assert page.workflow_lens_buttons["project"].isChecked() is True
        assert "schema=FLUXNET" in page.coverage_values["network"].text()
        assert "footprint=kljun" in page.coverage_values["methods"].text()
        assert "footprint=kljun" in page.method_snapshot_label.text()
        assert "uncertainty=mann_lenschow" in page.method_snapshot_label.text()
        assert page.method_family_gate_chip.text() in {"就绪", "复核"}
        page._show_method_family("spectral")
        assert page.method_family_stack.currentWidget() is page.spectral_card
        assert page.method_family_buttons["spectral"].isChecked() is True
        page._show_method_support("compare")
        assert page.method_support_stack.currentWidget() is page.method_compare_card
        assert page.method_support_buttons["compare"].isChecked() is True
        page._show_rail_focus("coverage")
        assert page.rail_focus_stack.currentWidget() is page.output_coverage_card
        assert page.rail_focus_buttons["coverage"].isChecked() is True
        assert page.desktop_rail_stack.currentWidget() is page.rail_focus_card
        assert page.desktop_rail_mode_buttons["closure"].isChecked() is True
        page._show_desktop_rail_mode("cockpit")
        assert page.desktop_rail_stack.currentWidget() is page.cockpit_card
        assert page.desktop_rail_mode_buttons["cockpit"].isChecked() is True
        page.footprint_zm_spin.setValue(1.0)
        page.footprint_canopy_spin.setValue(5.0)
        page._refresh_uncertainty_preview()
        assert "z_m > canopy_height_m" in page.method_validation_label.text()
        assert page.method_family_gate_chip.text() == "复核"
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
        assert page.window_cockpit_values["frequency"].text() == "10 Hz"
        assert page.window_cockpit_values["batches"].text().endswith("windows")
        assert page.window_cockpit_tiles["batches"].property("evidenceTone") == "success"
        assert page.window_cockpit_tiles["samples"].property("evidenceTone") in {"success", "warning", "danger"}
        assert "lag=" in page.lag_note_label.text()
        assert "u*=" in page.turbulence_preview_label.text()
        assert page.uncertainty_sampling_label.text() != "真实 RP 未提供"
        assert page.full_output_mode_combo.currentText() == "only_available"
        assert page.cockpit_result_value.text() != "尚未运行"
        assert page.cockpit_uncertainty_value.text().startswith("±")
        assert page.rp_closure_values["run"].text() == "已运行"
        assert page.rp_closure_values["flux"].text() != "待生成"
        assert page.rp_closure_values["uncertainty"].text().startswith("±")
        assert page.rp_closure_tiles["run"].property("evidenceTone") == "success"
        assert page.cockpit_delivery_value.text() == "FLUXNET"
        assert "windows=" in page.cockpit_result_note.text()
        assert page.window_readiness_value.text() != "36,000"
        assert "window=" in page.window_readiness_note.text()
        assert page.delivery_readiness_value.text() == "FLUXNET"
        assert page.window_plan_curve.xData is not None and len(page.window_plan_curve.xData) > 0
        assert "真实窗口" in page.window_plan_note.text()
    finally:
        controller.shutdown()


def test_ec_processing_viewport_layout_keeps_cockpit_and_rails_stable(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ECProcessingPage(controller)
        page.show()
        for width, height in ((1280, 760), (1440, 920), (1600, 900)):
            page.resize(width, height)
            page.refresh()
            app.processEvents()

            assert page.desktop_rail.width() <= page.desktop_rail.maximumWidth()
            assert page.desktop_rail.width() >= page.desktop_rail.minimumWidth()
            assert page.desktop_rail_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert_contained(page, page.rp_closure_deck, page)
            assert_contained(page, page.tree_card, page)
            assert_contained(page, page.desktop_rail, page)

            closure_tiles = list(page.rp_closure_tiles.values())
            for tile in closure_tiles:
                assert_contained(page.rp_closure_deck, tile, page)
            assert_no_visual_overlap(closure_tiles, page)

            assert_contained(page.desktop_rail_scroll.viewport(), page.workflow_lens_card, page)
            assert_contained(page.content_stack.currentWidget().viewport(), page.window_cockpit_card, page)
            assert_no_visible_competitor_name(page)
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()


def test_ec_processing_method_console_controls_are_visible_in_main_shell(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    window = None
    try:
        window = StudioMainWindow(controller)
        window.resize(1440, 900)
        window._set_page("ec_processing")
        page = window.ec_processing_page
        page.step_tree.setCurrentItem(page.step_items["uncertainty"])
        page.refresh()
        window.show()
        app.processEvents()

        scroll = page.content_stack.currentWidget()
        viewport_rect = widget_bounds(scroll.viewport(), page)
        family_rect = widget_bounds(page.method_family_card, page)
        stack_rect = widget_bounds(page.method_family_stack, page)

        assert page.method_result_card.property("deckRole") == "methodResultCompact"
        assert page.method_result_card.geometry().y() > page.method_support_card.geometry().y()
        assert family_rect.top() < viewport_rect.bottom()
        assert stack_rect.top() < viewport_rect.bottom()
        assert_contained(scroll.viewport(), page.footprint_enable_combo, page)
        assert_contained(scroll.viewport(), page.footprint_method_combo, page)
        assert page.content_stack.width() >= 620
        assert page.desktop_rail.minimumWidth() == 280
    finally:
        if window is not None:
            window.close()
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
