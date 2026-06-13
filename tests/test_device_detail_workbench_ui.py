from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.pages.device_detail_page import DeviceDetailPage
from app.studio import StudioController
from app.theme import apply_app_theme
from tests.ui_geometry_helpers import assert_contained, assert_no_visible_competitor_name, assert_no_visual_overlap


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_device_detail_uses_device_operations_rail(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Field YGAS",
            port="SIM1",
            baudrate=115200,
            device_id="001",
            analyzer_profile="ygas_irga",
        )
        controller.select_device(uid)
        controller.connect_device(uid)
        controller.read_frame_once(uid)
        page = DeviceDetailPage(controller)
        try:
            page.refresh()

            assert page.header_card.property("cardRole") == "command"
            assert page.header_card.property("deviceDetailHeaderDock") is True
            assert page.header_card.maximumHeight() == 96
            assert page.back_button.property("deviceDetailHeaderButton") is True
            assert page.back_button.maximumHeight() == 30
            assert page.operator_btn.property("deviceDetailViewSwitch") is True
            assert page.engineer_btn.property("deviceDetailViewSwitch") is True
            assert page.operator_btn.maximumHeight() == 30
            assert page.engineer_btn.maximumHeight() == 30
            assert page.summary_card.property("cardRole") == "cockpit"
            assert page.summary_card.property("deckRole") == "deviceSummaryDeck"
            assert page.summary_card.property("deviceDetailSummaryDock") is True
            assert page.summary_card.maximumHeight() == 118
            assert len(page.summary_metric_cards) == 7
            assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
            assert all(card.property("deviceDetailSummaryMetric") is True for card in page.summary_metric_cards)
            assert all(card.maximumHeight() == 50 for card in page.summary_metric_cards)
            assert all(value.property("compactMetric") is True for value in page.summary_values.values())
            assert page.device_ops_rail.property("cardRole") == "rail"
            assert page.device_ops_rail.property("deviceOpsRail") is True
            assert page.device_ops_action_bar.property("deckRole") == "deviceOpsActionBar"
            assert page.device_ops_action_bar.property("deviceOpsActionDock") is True
            assert page.device_ops_action_bar.maximumHeight() == 36
            assert page.device_ops_action_button.property("railAction") is True
            assert page.device_ops_risk_button.property("railAction") is True
            assert page.device_ops_action_button.property("deviceOpsRailAction") is True
            assert page.device_ops_risk_button.property("deviceOpsRailAction") is True
            assert page.device_ops_action_button.maximumHeight() == 24
            assert page.device_ops_risk_button.maximumHeight() == 24
            assert page.device_ops_action_button.property("targetAction") == "trace_config"
            assert page.device_ops_risk_button.property("targetAction") == "trace_config"
            assert page.device_ops_risk_button.property("actionTone") == "warning"
            assert page.device_ops_grid.count() == 5
            assert set(page.device_ops_values) == {"link", "telemetry", "primary", "trace", "diagnostics"}
            assert page.device_ops_next_card.property("deviceOpsNextCard") is True
            assert page.device_ops_next_card.maximumHeight() == 84
            assert all(
                value.parentWidget().property("deviceOpsTile") is True
                for value, _note in page.device_ops_values.values()
                if value.parentWidget() is not None
            )
            assert page.device_ops_values["link"][0].property("compactMetric") is True
            assert page.device_ops_next_value.property("compactMetric") is True
            assert page.device_ops_values["link"][0].text() == "在线"
            assert page.device_ops_values["telemetry"][0].text().endswith("Hz")
            assert page.device_ops_values["primary"][0].text() == "ygas_irga"
            assert page.device_ops_next_value.text() in {"读取一帧", "启用主分析仪", "进入实时采集", "复核配置"}
            page.device_ops_action_button.click()
            assert page.tabs.currentIndex() == 1

            controller.disconnect_device(uid)
            page.refresh()

            assert page.device_ops_values["link"][0].text() == "离线"
            assert page.device_ops_next_value.text() == "连接设备"
            assert page.device_ops_action_button.property("targetAction") == "connect"
        finally:
            page.deleteLater()
    finally:
        controller.shutdown()


def test_device_detail_viewport_layout_keeps_summary_and_ops_stable(monkeypatch, tmp_path: Path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Field YGAS",
            port="SIM1",
            baudrate=115200,
            device_id="001",
            analyzer_profile="ygas_irga",
        )
        controller.select_device(uid)
        controller.connect_device(uid)
        controller.read_frame_once(uid)
        page = DeviceDetailPage(controller)
        try:
            page.show()
            for width, height in ((1280, 760), (1440, 920), (1600, 900)):
                page.resize(width, height)
                page.refresh()
                app.processEvents()

                assert page.width() <= width
                assert page.height() <= height
                assert page.device_ops_rail.width() <= page.device_ops_rail.maximumWidth()
                assert page.device_ops_rail.width() >= page.device_ops_rail.minimumWidth()

                assert_contained(page, page.header_card, page)
                assert_contained(page, page.summary_card, page)
                assert_contained(page, page.tabs, page)
                assert_contained(page, page.device_ops_rail, page)
                assert_contained(page.device_ops_rail, page.device_ops_action_bar, page)

                for card in page.summary_metric_cards:
                    assert_contained(page.summary_card, card, page)
                assert_no_visual_overlap(page.summary_metric_cards, page)

                ops_tiles = [
                    value.parentWidget()
                    for value, _note in page.device_ops_values.values()
                    if value.parentWidget() is not None
                ]
                ops_tiles.append(page.device_ops_next_value.parentWidget())
                ops_tiles.append(page.device_ops_action_bar)
                for tile in ops_tiles:
                    assert_contained(page.device_ops_rail, tile, page)
                assert_no_visual_overlap(ops_tiles, page)
                assert_no_visible_competitor_name(page)
        finally:
            page.close()
            page.deleteLater()
    finally:
        controller.shutdown()
