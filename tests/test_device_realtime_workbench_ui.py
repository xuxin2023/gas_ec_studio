from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from app.pages.device_center_page import DeviceCenterPage
from app.pages.realtime_page import RealtimePage
from app.studio import StudioController
from app.theme import apply_app_theme


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_device_center_uses_field_operations_deck() -> None:
    _app()
    controller = StudioController()
    page = DeviceCenterPage(controller)
    try:
        page.refresh()

        assert page.status_card.property("cardRole") == "cockpit"
        assert page.field_readiness_card.property("cardRole") == "panel"
        assert page.quick_card.property("cardRole") == "command"
        assert page.quick_add_panel.property("cardRole") == "tile"
        assert page.quick_actions_panel.property("cardRole") == "tile"
        assert page.device_grid_card.property("cardRole") == "panel"
        assert page.activity_card.property("cardRole") == "rail"
        assert set(page.readiness_values) == {"fleet", "target", "protocol", "next"}
        assert page.readiness_values["fleet"][0].text() in {"可采", "待检查"}
        assert page.readiness_values["next"][0].text() in {"连接设备", "进入采集", "处理异常", "选择设备"}
    finally:
        page.deleteLater()
        controller.shutdown()


def test_realtime_page_uses_session_cockpit_deck() -> None:
    _app()
    controller = StudioController()
    page = RealtimePage(controller)
    try:
        page.refresh()

        assert page.control_card.property("cardRole") == "command"
        assert page.capture_target_panel.property("cardRole") == "tile"
        assert page.capture_metric_panel.property("cardRole") == "tile"
        assert page.capture_action_panel.property("cardRole") == "tile"
        assert page.capture_command_chip.text() == "实时控制台"
        assert page.summary_card.property("cardRole") == "cockpit"
        assert page.summary_card.property("deckRole") == "realtimeSummaryDeck"
        assert page.summary_card.maximumHeight() == 132
        assert len(page.summary_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
        assert all(value.property("compactMetric") is True for value in page.summary_values.values())
        assert page.plot_card.property("cardRole") == "panel"
        assert page.bottom_card.property("cardRole") == "rail"
        assert page.bottom_card.minimumHeight() == 214
        assert page.session_device_value.property("compactMetric") is True
        assert page.session_state_chip.text() in {"待连接", "需关注", "采集中", "等待帧"}
        assert page.session_device_value.text() != "--"
        assert "buffer=" in page.session_window_note.text()
    finally:
        page.deleteLater()
        controller.shutdown()
