from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.spectral_qc_page import SpectralQCPage
from app.studio import StudioController
from models.spectral_models import SpectralRunResult, WindowSpectralResult


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _window(*, with_provenance: bool = True, with_total_tf: bool = True) -> WindowSpectralResult:
    return WindowSpectralResult(
        window_id="spectral-window-001",
        start_time=datetime(2026, 4, 18, 9, 0, 0),
        end_time=datetime(2026, 4, 18, 9, 30, 0),
        qc_grade="B",
        anomaly_type="high_freq_loss",
        lag_seconds=1.2,
        lag_confidence=0.91,
        correction_factor=1.173,
        high_freq_loss_risk="medium",
        reason="tube attenuation dominated this window",
        lag_curve_x=[0.0, 1.0],
        lag_curve_y=[0.1, 0.2],
        power_freq=[0.1, 0.2],
        power_measured=[0.9, 0.8],
        power_ref=[1.0, 0.95],
        cross_freq=[0.1, 0.2],
        cross_value=[0.7, 0.5],
        ogive_freq=[0.1, 0.2],
        ogive_value=[0.4, 0.65],
        qc_band_value=0.6,
        transfer_freq=[0.1, 0.2],
        transfer_value=[0.95, 0.88],
        correction_factor_components={
            "tube_component": 1.052,
            "separation_component": 1.031,
            "path_component": 1.018,
            "phase_component": 1.009,
            "total_factor": 1.173,
        }
        if with_provenance
        else {},
        total_transfer_function_freq=[0.1, 0.2, 0.5] if with_total_tf else [],
        total_transfer_function_value=[0.98, 0.91, 0.74] if with_total_tf else [],
        effective_cutoff_info={"effective_cutoff_hz": 0.47, "source": "fcc"},
        correction_factor_detail={"base_factor": 1.11, "cap_applied": False},
        provenance_notes=["tube attenuation used site metadata"] if with_provenance else [],
        model_version="fcc_transfer_components_v1" if with_provenance else "",
        corrected_flux_before=0.83,
        corrected_flux_after=0.97,
        sample_count=512,
    )


def _run(window: WindowSpectralResult) -> SpectralRunResult:
    return SpectralRunResult(
        run_id="spectral-run-001",
        created_at=datetime(2026, 4, 18, 10, 0, 0),
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:30",
        qc_only=False,
        summary={
            "status": "ok",
            "average_lag_confidence": 0.91,
            "high_freq_loss_risk": "medium",
            "good_window_count": 0,
            "attention_window_count": 1,
            "average_correction_factor": 1.173,
            "average_tube_component": 1.052,
            "average_separation_component": 1.031,
            "average_path_component": 1.018,
            "average_phase_component": 1.009,
        },
        windows=[window],
        artifacts={},
    )


def test_spectral_qc_page_refreshes_with_provenance(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        result = _run(_window())
        controller.spectral_runs = [result]
        controller._sync_spectral_workspace_from_result(result)

        page = SpectralQCPage(controller)
        page.refresh()

        assert page.transfer_provenance_table.rowCount() >= 6
        assert page.transfer_provenance_table.item(0, 1).text() == "1.173"
        assert page.correction_component_table.rowCount() == 5
        assert "tube attenuation used site metadata" in page.transfer_provenance_note.text()
        assert "tube:" in page.detail_dominant_components_label.text()
    finally:
        controller.shutdown()


def test_spectral_qc_page_stable_without_provenance(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        result = _run(_window(with_provenance=False, with_total_tf=False))
        controller.spectral_runs = [result]
        controller._sync_spectral_workspace_from_result(result)

        page = SpectralQCPage(controller)
        page.refresh()

        assert page.transfer_curve.xData is None or len(page.transfer_curve.xData) == 0
        assert page.transfer_plot_note.text() == "当前窗口没有 total_transfer_function 数据，不生成演示曲线。"
        assert page.transfer_provenance_note.text() == "当前窗口尚无分项修正说明"
        assert page.correction_component_note.text() == "当前窗口尚无分项修正说明"
    finally:
        controller.shutdown()


def test_total_transfer_function_consumes_real_series(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        result = _run(_window())
        controller.spectral_runs = [result]
        controller._sync_spectral_workspace_from_result(result)

        page = SpectralQCPage(controller)
        page.refresh()

        assert list(page.transfer_curve.xData) == [0.1, 0.2, 0.5]
        assert list(page.transfer_curve.yData) == [0.98, 0.91, 0.74]
    finally:
        controller.shutdown()


def test_main_window_can_switch_to_spectral_qc_page(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        result = _run(_window())
        controller.spectral_runs = [result]
        controller._sync_spectral_workspace_from_result(result)

        window = StudioMainWindow(controller)
        window._set_page("spectral_qc")

        assert window.stack.currentWidget() is window.spectral_qc_page
        assert window.spectral_qc_page.window_table.rowCount() == 1
        window.close()
    finally:
        controller.shutdown()
