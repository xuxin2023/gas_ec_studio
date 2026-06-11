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
            assert page.summary_card.property("cardRole") == "cockpit"
            assert page.summary_card.property("deckRole") == "deviceSummaryDeck"
            assert page.summary_card.maximumHeight() == 132
            assert len(page.summary_metric_cards) == 7
            assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
            assert all(value.property("compactMetric") is True for value in page.summary_values.values())
            assert page.device_ops_rail.property("cardRole") == "rail"
            assert page.device_ops_grid.count() == 5
            assert set(page.device_ops_values) == {"link", "telemetry", "primary", "trace", "diagnostics"}
            assert page.device_ops_values["link"][0].property("compactMetric") is True
            assert page.device_ops_next_value.property("compactMetric") is True
            assert page.device_ops_values["link"][0].text() == "在线"
            assert page.device_ops_values["telemetry"][0].text().endswith("Hz")
            assert page.device_ops_values["primary"][0].text() == "ygas_irga"
            assert page.device_ops_next_value.text() in {"读取一帧", "启用主分析仪", "进入实时采集", "复核配置"}

            controller.disconnect_device(uid)
            page.refresh()

            assert page.device_ops_values["link"][0].text() == "离线"
            assert page.device_ops_next_value.text() == "连接设备"
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

                for card in page.summary_metric_cards:
                    assert_contained(page.summary_card, card, page)
                assert_no_visual_overlap(page.summary_metric_cards, page)

                ops_tiles = [
                    value.parentWidget()
                    for value, _note in page.device_ops_values.values()
                    if value.parentWidget() is not None
                ]
                ops_tiles.append(page.device_ops_next_value.parentWidget())
                for tile in ops_tiles:
                    assert_contained(page.device_ops_rail, tile, page)
                assert_no_visual_overlap(ops_tiles, page)
                assert_no_visible_competitor_name(page)
        finally:
            page.close()
            page.deleteLater()
    finally:
        controller.shutdown()
