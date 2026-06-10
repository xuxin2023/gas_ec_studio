from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.spectral_qc_page import SpectralQCPage
from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _make_rows(sample_hz: float = 10.0, samples: int = 512) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    vertical = np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.35 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    co2_signal = np.roll(vertical, 6) + 0.05 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, 4) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.12 * vertical
    chamber = 25.0 + 0.3 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    case = 24.7 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(chamber[index]),
                case_temp_c=float(case[index]),
                raw_text=json.dumps({"w": float(vertical[index])}),
            )
        )
    return rows


def test_spectral_qc_page_refreshes_with_empty_result(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = SpectralQCPage(controller)
        page.refresh()

        assert page.run_bar.property("cardRole") == "command"
        assert page.spectral_source_panel.property("cardRole") == "tile"
        assert page.spectral_action_panel.property("cardRole") == "tile"
        assert page.summary_row.objectName() == "spectralSummaryDeck"
        assert page.summary_row.property("deckRole") == "spectralCockpitKpis"
        assert page.summary_row.parentWidget() is page.run_bar
        assert page.summary_row.maximumHeight() == 136
        assert len(page.summary_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
        assert page.lag_confidence_value.property("compactMetric") is True
        assert page.tree_card.property("cardRole") == "rail"
        assert page.footer_bar.property("cardRole") == "rail"
        assert page.footer_bar.maximumHeight() == 78
        visible_notes = [
            page.overview_focus_note.text(),
            page.overview_reason_label.text(),
            page.overview_action_label.text(),
            page.lag_phase_note.text(),
            page.power_note_label.text(),
            page.cross_note_label.text(),
            page.ogive_note_label.text(),
            page.qc_note_label.text(),
        ]
        assert all("???" not in text for text in visible_notes)
        assert "lag" in page.overview_focus_note.text()
        assert page.window_table.rowCount() == 0
        assert page.lag_curve.xData is None or len(page.lag_curve.xData) == 0
        assert page.power_curve.xData is None or len(page.power_curve.xData) == 0
    finally:
        controller.shutdown()


def test_spectral_qc_page_refreshes_with_real_result(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
        controller.project_workspace["timing"]["block_minutes"] = 0.5
        for row in _make_rows():
            controller.realtime_buffer.append(row)
        controller.run_spectral_qc()

        page = SpectralQCPage(controller)
        page.refresh()

        assert page.window_table.rowCount() > 0
        assert page.lag_curve.xData is not None and len(page.lag_curve.xData) > 0
        assert page.power_curve.xData is not None and len(page.power_curve.xData) > 0
        assert page.cross_curve.xData is not None and len(page.cross_curve.xData) > 0
        assert page.ogive_curve.xData is not None and len(page.ogive_curve.xData) > 0
    finally:
        controller.shutdown()


def test_main_window_can_switch_to_spectral_qc_page(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window._set_page("spectral_qc")
        assert window.stack.currentWidget() is window.spectral_qc_page
        window._set_page("report_center")
        assert window.stack.currentWidget() is window.report_center_page
        window.close()
    finally:
        controller.shutdown()
