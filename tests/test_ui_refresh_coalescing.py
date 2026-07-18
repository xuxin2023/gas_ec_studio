from __future__ import annotations

import os
from time import monotonic, sleep

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import apply_app_theme
from app.ui_refresh import CoalescedWidgetRefresh, set_dynamic_property, set_text_if_changed


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    apply_app_theme(app)
    return app


def _wait_for_events(app: QApplication, duration_ms: int) -> None:
    deadline = monotonic() + (duration_ms / 1000.0)
    while monotonic() < deadline:
        app.processEvents()
        sleep(0.005)
    app.processEvents()


def test_coalesced_refresh_limits_signal_storm_and_defers_hidden_widget() -> None:
    app = _app()
    owner = QWidget()
    calls: list[int] = []
    refresh = CoalescedWidgetRefresh(owner, lambda: calls.append(len(calls)), interval_ms=20)

    for _ in range(40):
        refresh.request()
    _wait_for_events(app, 40)
    assert calls == []

    owner.show()
    _wait_for_events(app, 40)
    assert len(calls) == 1
    assert owner.updatesEnabled() is True

    for _ in range(40):
        refresh.request()
    _wait_for_events(app, 40)
    assert len(calls) == 2
    owner.close()


def test_stable_widget_updates_ignore_unchanged_values() -> None:
    _app()
    label = QLabel("ready")
    assert set_text_if_changed(label, "ready") is False
    assert set_text_if_changed(label, "running") is True
    assert set_dynamic_property(label, "chipTone", "success") is True
    assert set_dynamic_property(label, "chipTone", "success") is False


def test_main_window_coalesces_live_updates_and_reuses_device_cards(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    window = None
    try:
        uid = controller.add_device(
            label="Field Analyzer",
            port="SIM1",
            baudrate=115200,
            device_id="001",
            analyzer_profile="ygas_irga",
        )
        window = StudioMainWindow(controller)
        window.resize(1440, 900)
        window.show()
        app.processEvents()

        device_center = window.device_center_page
        original_card = device_center._device_card_widgets[uid]
        shell_count = window._live_shell_refresh.flush_count
        page_count = device_center._live_refresh.flush_count
        realtime_count = window.realtime_page._live_refresh.flush_count

        for _ in range(40):
            controller.devices_changed.emit()
        _wait_for_events(app, 400)

        assert 1 <= window._live_shell_refresh.flush_count - shell_count <= 2
        assert 1 <= device_center._live_refresh.flush_count - page_count <= 2
        assert window.realtime_page._live_refresh.flush_count == realtime_count
        assert device_center._device_card_widgets[uid] is original_card

        window._set_page("realtime")
        _wait_for_events(app, 40)
        realtime_count = window.realtime_page._live_refresh.flush_count
        for _ in range(40):
            controller.frame_received.emit(None)
            controller.devices_changed.emit()
        _wait_for_events(app, 400)
        assert 1 <= window.realtime_page._live_refresh.flush_count - realtime_count <= 2
    finally:
        if window is not None:
            window.close()
        controller.shutdown()
