from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.ec_processing_page import EC_STEPS, ECProcessingPage
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
        assert page.rp_closure_deck.maximumHeight() == 92
        assert page.rp_closure_deck.property("closureMode") == "compact"
        assert page.rp_closure_mode_buttons["compact"].isChecked() is True
        assert page.rp_closure_stack.currentWidget() is page.rp_closure_compact_strip
        assert page.rp_closure_chip.text().startswith("待运行")
        assert set(page.rp_closure_tiles) == {"run", "flux", "uncertainty", "methods", "benchmark", "network"}
        assert set(page.rp_closure_compact_tiles) == set(page.rp_closure_tiles)
        assert all(tile.property("cardRole") == "tile" for tile in page.rp_closure_tiles.values())
        assert all(tile.property("closureCompactTile") is True for tile in page.rp_closure_compact_tiles.values())
        assert all(value.property("compactMetric") is True for value in page.rp_closure_values.values())
        assert all(chip.property("closureStage") is True for chip in page.rp_closure_chips.values())
        assert all(chip.minimumHeight() == 22 for chip in page.rp_closure_chips.values())
        assert page.rp_closure_values["run"].text() == "待运行"
        assert page.rp_closure_values["flux"].text() == "待生成"
        assert page.rp_closure_values["network"].text() == "FLUXNET"
        assert page.rp_closure_compact_values["run"].text() == page.rp_closure_values["run"].text()
        page._show_rp_closure_mode("detail")
        assert page.rp_closure_deck.maximumHeight() == 146
        assert page.rp_closure_deck.property("closureMode") == "detail"
        assert page.rp_closure_mode_buttons["detail"].isChecked() is True
        assert page.tree_card.property("cardRole") == "rail"
        assert page.step_nav_summary_card.property("deckRole") == "ecStepNavigationStatus"
        assert page.step_nav_summary_card.maximumHeight() == 42
        assert page.step_nav_summary_value.text().startswith("就绪")
        assert page.step_count_chip.text() == f"{len(EC_STEPS)} 步"
        assert page.step_active_chip.text().startswith("窗口")
        assert page.step_tree.columnCount() == 2
        assert page.step_tree.indentation() == 0
        assert page.step_tree.rootIsDecorated() is False
        assert page.step_tree.uniformRowHeights() is True
        assert page.step_tree.topLevelItemCount() == len(EC_STEPS)
        assert page.step_tree.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.step_items["window_sampling"].text(1) == "就绪"
        assert page.step_items["lag"].text(1) == "待跑"
        assert page.step_items["uncertainty"].data(1, Qt.UserRole) in {"warning", "danger"}
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
        assert set(page.desktop_rail_status_tiles) == {"step", "run", "closure"}
        assert page.desktop_rail_action_button.property("railAction") is True
        assert page.desktop_rail_risk_button.property("railAction") is True
        assert page.desktop_rail_action_button.text() != "--"
        assert page.desktop_rail_risk_button.text() != "--"
        assert page.cockpit_card.property("cardRole") == "cockpit"
        assert page.cockpit_card.property("deckRole") == "processingCockpitDeck"
        assert page.rail_focus_card.property("cardRole") == "panel"
        assert page.rail_focus_stack.count() == 2
        assert page.rail_focus_stack.currentWidget() is page.readiness_card
        assert page.rail_focus_buttons["readiness"].isChecked() is True
        assert page.readiness_card.property("cardRole") == "panel"
        assert page.workflow_lens_card.property("cardRole") == "panel"
        assert page.workflow_lens_card.property("deckRole") == "workflowLensCompact"
        assert page.workflow_lens_card.maximumHeight() == 170
        assert page.workflow_lens_active_note.maximumHeight() == 32
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
        assert page.method_family_card.property("deckRole") == "methodFamilyCockpit"
        assert page.method_family_stack.property("stackRole") == "methodFamilyStack"
        assert set(page.method_console_tiles) == {"footprint", "uncertainty", "spectral"}
        assert all(tile.property("methodTile") is True for tile in page.method_console_tiles.values())
        assert all(tile.property("cardRole") == "tile" for tile in page.method_console_tiles.values())
        assert len(page.method_field_labels) >= 20
        assert all(label.property("methodFieldLabel") is True for label in page.method_field_labels)
        assert page.method_field_labels[0].objectName() == "metricLabel"
        assert min(label.minimumWidth() for label in page.method_field_labels) >= 112
        assert len(page.method_field_inputs) == len(page.method_field_labels)
        assert all(widget.property("methodFieldInput") is True for widget in page.method_field_inputs)
        assert set(page.method_group_pills) == {"footprint", "uncertainty", "spectral"}
        assert [label.text() for label in page.method_group_pills["footprint"]] == ["开关/模型", "几何/稳定度", "网格"]
        assert [label.text() for label in page.method_group_pills["spectral"]] == ["开关/模型", "路径/响应", "共谱注入"]
        assert all(label.property("methodGroupPill") is True for labels in page.method_group_pills.values() for label in labels)
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
        assert page.window_timeline_card.property("deckRole") == "windowTimelinePanel"
        assert page.window_timeline_card.maximumHeight() == 274
        assert page.window_plan_plot.maximumHeight() == 168
        assert page.window_timeline_chip.text() == "preview"
        assert page.window_timeline_chip.property("chipTone") == "warning"
        assert page.lag_param_card.property("deckRole") == "lagParameterPanel"
        assert page.lag_param_card.maximumHeight() == 330
        assert page.lag_covariance_card.property("deckRole") == "lagCovariancePanel"
        assert page.lag_covariance_card.maximumHeight() == 360
        assert page.lag_plot.maximumHeight() == 216
        assert page.lag_status_chip.text() == "preview"
        assert page.lag_status_chip.property("chipTone") == "warning"
        assert set(page.lag_metric_values) == {"lag", "confidence", "search", "strategy"}
        assert all(tile.property("cardRole") == "tile" for tile in page.lag_metric_tiles.values())
        assert page.lag_metric_values["confidence"].text() == "--"
        assert page.rotation_param_card.property("deckRole") == "rotationParameterPanel"
        assert page.rotation_param_card.maximumHeight() == 260
        assert page.rotation_evidence_card.property("deckRole") == "rotationEvidencePanel"
        assert page.rotation_evidence_card.maximumHeight() == 290
        assert page.rotation_status_chip.text() == "preview"
        assert page.rotation_status_chip.property("chipTone") == "warning"
        assert set(page.rotation_metric_values) == {"requested", "applied", "alpha", "beta"}
        assert all(tile.property("cardRole") == "tile" for tile in page.rotation_metric_tiles.values())
        assert page.rotation_metric_values["applied"].text() == "--"
        assert page.detrend_param_card.property("deckRole") == "detrendParameterPanel"
        assert page.detrend_param_card.maximumHeight() == 260
        assert page.detrend_evidence_card.property("deckRole") == "detrendEvidencePanel"
        assert page.detrend_evidence_card.maximumHeight() == 360
        assert page.detrend_flux_plot.maximumHeight() == 190
        assert page.detrend_status_chip.text() == "preview"
        assert page.detrend_status_chip.property("chipTone") == "warning"
        assert set(page.detrend_metric_values) == {"method", "windows", "raw", "primary"}
        assert all(tile.property("cardRole") == "tile" for tile in page.detrend_metric_tiles.values())
        assert page.detrend_metric_values["windows"].text() == "--"
        assert page.covariance_param_card.property("deckRole") == "covarianceParameterPanel"
        assert page.covariance_param_card.maximumHeight() == 240
        assert page.covariance_evidence_card.property("deckRole") == "covarianceEvidencePanel"
        assert page.covariance_evidence_card.maximumHeight() == 280
        assert page.covariance_status_chip.text() == "preview"
        assert page.covariance_status_chip.property("chipTone") == "warning"
        assert set(page.covariance_metric_values) == {"method", "w_co2", "w_h2o", "raw"}
        assert all(tile.property("cardRole") == "tile" for tile in page.covariance_metric_tiles.values())
        assert page.covariance_metric_values["w_co2"].text() == "--"
        assert page.density_param_card.property("deckRole") == "densityParameterPanel"
        assert page.density_param_card.maximumHeight() == 260
        assert page.density_evidence_card.property("deckRole") == "densityEvidencePanel"
        assert page.density_evidence_card.maximumHeight() == 360
        assert page.density_plot.maximumHeight() == 190
        assert page.density_status_chip.text() == "preview"
        assert page.density_status_chip.property("chipTone") == "warning"
        assert set(page.density_metric_values) == {"source", "factor", "raw", "primary"}
        assert all(tile.property("cardRole") == "tile" for tile in page.density_metric_tiles.values())
        assert page.density_metric_values["factor"].text() == "--"
        assert page.steadiness_param_card.property("deckRole") == "steadinessParameterPanel"
        assert page.steadiness_param_card.maximumHeight() == 260
        assert page.steadiness_evidence_card.property("deckRole") == "steadinessEvidencePanel"
        assert page.steadiness_evidence_card.maximumHeight() == 360
        assert page.steadiness_score_plot.maximumHeight() == 190
        assert page.steadiness_status_chip.text() == "preview"
        assert page.steadiness_status_chip.property("chipTone") == "warning"
        assert set(page.steadiness_metric_values) == {"rule", "qc", "score", "windows"}
        assert all(tile.property("cardRole") == "tile" for tile in page.steadiness_metric_tiles.values())
        assert page.steadiness_metric_values["score"].text() == "--"
        assert page.turbulence_param_card.property("deckRole") == "turbulenceParameterPanel"
        assert page.turbulence_param_card.maximumHeight() == 260
        assert page.turbulence_evidence_card.property("deckRole") == "turbulenceEvidencePanel"
        assert page.turbulence_evidence_card.maximumHeight() == 360
        assert page.turbulence_score_plot.maximumHeight() == 190
        assert page.turbulence_status_chip.text() == "preview"
        assert page.turbulence_status_chip.property("chipTone") == "warning"
        assert set(page.turbulence_metric_values) == {"rule", "ustar", "score", "status"}
        assert all(tile.property("cardRole") == "tile" for tile in page.turbulence_metric_tiles.values())
        assert page.turbulence_metric_values["ustar"].text() == "--"
        assert page.output_param_card.property("deckRole") == "outputParameterPanel"
        assert page.output_param_card.maximumHeight() == 260
        assert page.output_evidence_card.property("deckRole") == "outputEvidencePanel"
        assert page.output_evidence_card.maximumHeight() == 360
        assert page.output_status_chip.text() == "preview"
        assert page.output_status_chip.property("chipTone") == "warning"
        assert set(page.output_metric_values) == {"run", "windows", "mode", "fields", "uncertainty", "network"}
        assert all(tile.property("cardRole") == "tile" for tile in page.output_metric_tiles.values())
        assert page.output_metric_values["uncertainty"].text() == "--"
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
        assert page.method_console_values["footprint"].text() == "kljun"
        assert page.method_console_values["uncertainty"].text() == "mann_lenschow"
        assert page.method_console_values["spectral"].text() == "massman"
        assert page.method_console_tiles["footprint"].property("evidenceTone") in {"success", "danger"}
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
        assert page.method_console_tiles["footprint"].property("evidenceTone") == "danger"
        assert page.desktop_rail_risk_button.property("actionTone") == "danger"
        assert page.desktop_rail_risk_button.property("targetStep") == "uncertainty"
        page.desktop_rail_risk_button.click()
        assert controller.ec_nav_step == "uncertainty"
        assert page.desktop_rail_stack.currentWidget() is page.workflow_lens_card
        assert page.step_items["uncertainty"].text(1) == "复核"
        assert page.step_items["output"].text(1) == "复核"
        assert page.step_items["uncertainty"].data(1, Qt.UserRole) == "danger"
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
        assert page.step_items["window_sampling"].text(1) == "完成"
        assert page.step_items["lag"].text(1) == "完成"
        assert page.step_items["window_sampling"].data(1, Qt.UserRole) == "success"
        assert page.window_cockpit_values["frequency"].text() == "10 Hz"
        assert page.window_cockpit_values["batches"].text().endswith("windows")
        assert page.window_cockpit_tiles["batches"].property("evidenceTone") == "success"
        assert page.window_cockpit_tiles["samples"].property("evidenceTone") in {"success", "warning", "danger"}
        assert page.window_timeline_chip.text() == "real"
        assert page.window_timeline_chip.property("chipTone") == "success"
        assert page.lag_status_chip.text() == "real"
        assert page.lag_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.lag_metric_values["lag"].text().endswith("s")
        assert page.lag_metric_values["confidence"].text() != "--"
        assert page.lag_metric_tiles["lag"].property("evidenceTone") in {"success", "warning", "danger"}
        assert page.rotation_status_chip.text() in {"applied", "fallback", "not applied"}
        assert page.rotation_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.rotation_metric_values["requested"].text() != "--"
        assert page.rotation_metric_values["applied"].text() != "--"
        assert page.rotation_metric_values["alpha"].text().endswith("deg")
        assert page.rotation_metric_values["beta"].text().endswith("deg")
        assert page.detrend_status_chip.text() == "real"
        assert page.detrend_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.detrend_metric_values["method"].text() != "--"
        assert page.detrend_metric_values["windows"].text() != "--"
        assert page.detrend_metric_values["raw"].text() != "--"
        assert page.detrend_metric_values["primary"].text() != "--"
        assert page.covariance_status_chip.text() == "real"
        assert page.covariance_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.covariance_metric_values["method"].text() != "--"
        assert page.covariance_metric_values["w_co2"].text() != "--"
        assert page.covariance_metric_values["w_h2o"].text() != "--"
        assert page.covariance_metric_values["raw"].text() != "--"
        assert page.density_status_chip.text() == "real"
        assert page.density_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.density_metric_values["source"].text() != "--"
        assert page.density_metric_values["factor"].text().endswith("x")
        assert page.density_metric_values["raw"].text() != "--"
        assert page.density_metric_values["primary"].text() != "--"
        assert page.steadiness_status_chip.text() == "real"
        assert page.steadiness_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.steadiness_metric_values["rule"].text() != "--"
        assert page.steadiness_metric_values["qc"].text() != "--"
        assert page.steadiness_metric_values["score"].text() != "--"
        assert page.steadiness_metric_values["windows"].text() != "--"
        assert page.turbulence_status_chip.text() == "real"
        assert page.turbulence_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.turbulence_metric_values["rule"].text() != "--"
        assert page.turbulence_metric_values["ustar"].text() != "--"
        assert page.turbulence_metric_values["score"].text() != "--"
        assert page.turbulence_metric_values["status"].text() != "--"
        assert page.output_status_chip.text() == "real"
        assert page.output_status_chip.property("chipTone") in {"success", "warning", "danger"}
        assert page.output_metric_values["run"].text() != "--"
        assert page.output_metric_values["windows"].text() != "--"
        assert page.output_metric_values["mode"].text() == page.full_output_mode_combo.currentText()
        assert page.output_metric_values["fields"].text() != "--"
        assert page.output_metric_values["uncertainty"].text() != "--"
        assert page.output_metric_values["network"].text() != "--"
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
        assert page.rp_closure_compact_values["run"].text() == page.rp_closure_values["run"].text()
        assert page.rp_closure_compact_tiles["run"].property("evidenceTone") == "success"
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
            page.step_tree.setCurrentItem(page.step_items["window_sampling"])
            app.processEvents()

            assert page.desktop_rail.width() <= page.desktop_rail.maximumWidth()
            assert page.desktop_rail.width() >= page.desktop_rail.minimumWidth()
            assert page.desktop_rail_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert page.step_tree.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert_contained(page, page.rp_closure_deck, page)
            assert_contained(page, page.tree_card, page)
            assert_contained(page, page.desktop_rail, page)

            closure_tiles = list(page.rp_closure_compact_tiles.values())
            for tile in closure_tiles:
                assert_contained(page.rp_closure_deck, tile, page)
            assert_no_visual_overlap(closure_tiles, page)
            page._show_rp_closure_mode("detail")
            app.processEvents()
            detail_tiles = list(page.rp_closure_tiles.values())
            for tile in detail_tiles:
                assert_contained(page.rp_closure_deck, tile, page)
            assert_no_visual_overlap(detail_tiles, page)
            page._show_rp_closure_mode("compact")
            app.processEvents()

            assert_contained(page.desktop_rail_scroll.viewport(), page.desktop_rail_status_strip, page)
            assert_contained(page.desktop_rail_scroll.viewport(), page.desktop_rail_action_button, page)
            assert_contained(page.desktop_rail_scroll.viewport(), page.desktop_rail_risk_button, page)
            content_viewport = page.content_stack.currentWidget().viewport()
            viewport_rect = widget_bounds(content_viewport, page)
            timeline_rect = widget_bounds(page.window_timeline_card, page)
            plot_rect = widget_bounds(page.window_plan_plot, page)
            assert_contained(content_viewport, page.window_cockpit_card, page)
            assert timeline_rect.top() >= viewport_rect.top()
            assert timeline_rect.top() < viewport_rect.bottom()
            assert plot_rect.top() < viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["lag"])
            app.processEvents()
            lag_viewport = page.content_stack.currentWidget().viewport()
            lag_viewport_rect = widget_bounds(lag_viewport, page)
            lag_card_rect = widget_bounds(page.lag_covariance_card, page)
            lag_plot_rect = widget_bounds(page.lag_plot, page)
            assert page.lag_covariance_card.maximumHeight() == 360
            assert lag_card_rect.top() >= lag_viewport_rect.top()
            assert lag_card_rect.top() < lag_viewport_rect.bottom()
            assert lag_plot_rect.top() < lag_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["rotation"])
            app.processEvents()
            rotation_viewport = page.content_stack.currentWidget().viewport()
            rotation_viewport_rect = widget_bounds(rotation_viewport, page)
            rotation_card_rect = widget_bounds(page.rotation_evidence_card, page)
            assert page.rotation_evidence_card.maximumHeight() == 290
            assert rotation_card_rect.top() >= rotation_viewport_rect.top()
            assert rotation_card_rect.bottom() <= rotation_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["detrend"])
            app.processEvents()
            detrend_viewport = page.content_stack.currentWidget().viewport()
            detrend_viewport_rect = widget_bounds(detrend_viewport, page)
            detrend_card_rect = widget_bounds(page.detrend_evidence_card, page)
            detrend_plot_rect = widget_bounds(page.detrend_flux_plot, page)
            assert page.detrend_evidence_card.maximumHeight() == 360
            assert detrend_card_rect.top() >= detrend_viewport_rect.top()
            assert detrend_card_rect.top() < detrend_viewport_rect.bottom()
            assert detrend_plot_rect.top() < detrend_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["covariance"])
            app.processEvents()
            covariance_viewport = page.content_stack.currentWidget().viewport()
            covariance_viewport_rect = widget_bounds(covariance_viewport, page)
            covariance_card_rect = widget_bounds(page.covariance_evidence_card, page)
            assert page.covariance_evidence_card.maximumHeight() == 280
            assert covariance_card_rect.top() >= covariance_viewport_rect.top()
            assert covariance_card_rect.bottom() <= covariance_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["density_correction"])
            app.processEvents()
            density_viewport = page.content_stack.currentWidget().viewport()
            density_viewport_rect = widget_bounds(density_viewport, page)
            density_card_rect = widget_bounds(page.density_evidence_card, page)
            density_plot_rect = widget_bounds(page.density_plot, page)
            assert page.density_evidence_card.maximumHeight() == 360
            assert density_card_rect.top() >= density_viewport_rect.top()
            assert density_card_rect.top() < density_viewport_rect.bottom()
            assert density_plot_rect.top() < density_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["steadiness"])
            app.processEvents()
            steadiness_viewport = page.content_stack.currentWidget().viewport()
            steadiness_viewport_rect = widget_bounds(steadiness_viewport, page)
            steadiness_card_rect = widget_bounds(page.steadiness_evidence_card, page)
            steadiness_plot_rect = widget_bounds(page.steadiness_score_plot, page)
            assert page.steadiness_evidence_card.maximumHeight() == 360
            assert steadiness_card_rect.top() >= steadiness_viewport_rect.top()
            assert steadiness_card_rect.top() < steadiness_viewport_rect.bottom()
            assert steadiness_plot_rect.top() < steadiness_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["turbulence"])
            app.processEvents()
            turbulence_viewport = page.content_stack.currentWidget().viewport()
            turbulence_viewport_rect = widget_bounds(turbulence_viewport, page)
            turbulence_card_rect = widget_bounds(page.turbulence_evidence_card, page)
            turbulence_plot_rect = widget_bounds(page.turbulence_score_plot, page)
            assert page.turbulence_evidence_card.maximumHeight() == 360
            assert turbulence_card_rect.top() >= turbulence_viewport_rect.top()
            assert turbulence_card_rect.top() < turbulence_viewport_rect.bottom()
            assert turbulence_plot_rect.top() < turbulence_viewport_rect.bottom()
            page.step_tree.setCurrentItem(page.step_items["output"])
            app.processEvents()
            output_viewport = page.content_stack.currentWidget().viewport()
            output_viewport_rect = widget_bounds(output_viewport, page)
            output_card_rect = widget_bounds(page.output_evidence_card, page)
            assert page.output_evidence_card.maximumHeight() == 360
            assert output_card_rect.top() >= output_viewport_rect.top()
            assert output_card_rect.bottom() <= output_viewport_rect.bottom()
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
        assert page.method_support_card.property("deckRole") == "methodSupportDeck"
        assert page.method_console_mode_buttons["family"].isChecked() is True
        assert page.method_support_card.isHidden() is True
        assert page.method_result_card.geometry().y() > page.method_family_card.geometry().y()
        assert family_rect.top() < viewport_rect.bottom()
        assert stack_rect.top() < viewport_rect.bottom()
        assert_contained(scroll.viewport(), page.footprint_enable_combo, page)
        assert_contained(scroll.viewport(), page.footprint_method_combo, page)
        assert_contained(scroll.viewport(), page.method_field_labels[0], page)
        page._show_method_support("primary")
        app.processEvents()
        assert page.method_console_mode_buttons["primary"].isChecked() is True
        assert page.method_support_card.isHidden() is False
        assert page.method_family_switch_bar.isHidden() is True
        assert page.method_family_tile_strip.isHidden() is True
        assert page.method_family_stack.isHidden() is True
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
