from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from app.pages.device_center_page import DeviceCenterPage
from app.pages.realtime_page import RealtimePage
from app.studio import StudioController
from app.theme import apply_app_theme
from tests.ui_geometry_helpers import assert_contained, assert_no_visible_competitor_name, assert_no_visual_overlap, widget_bounds


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

        assert page.property("pageSurface") is True
        assert page.status_card.property("cardRole") == "cockpit"
        assert page.field_readiness_card.property("cardRole") == "panel"
        assert page.field_readiness_card.maximumHeight() == 158
        assert page.quick_card.property("cardRole") == "command"
        assert page.quick_card.maximumHeight() == 172
        assert page.quick_stack.property("stackRole") == "deviceQuickInspectorStack"
        assert page.quick_stack.count() == 2
        assert page.quick_stack.currentWidget() is page.quick_actions_panel
        assert page.quick_mode_buttons["actions"].isChecked() is True
        page._show_quick_mode("add")
        assert page.quick_stack.currentWidget() is page.quick_add_panel
        assert page.quick_mode_buttons["add"].isChecked() is True
        page._show_quick_mode("actions")
        assert page.quick_stack.currentWidget() is page.quick_actions_panel
        assert page.quick_add_panel.property("cardRole") == "tile"
        assert page.quick_add_panel.maximumHeight() == 112
        assert page.quick_actions_panel.property("cardRole") == "tile"
        assert page.quick_actions_panel.maximumHeight() == 112
        assert page.quick_tip_card.maximumHeight() == 0
        assert page.quick_tip_card.isVisibleTo(page) is False
        assert page.device_grid_card.property("cardRole") == "panel"
        assert page.device_grid_card.minimumHeight() == 198
        assert page.device_grid_card.maximumHeight() == 206
        assert page.operator_mission_card.property("cardRole") == "cockpit"
        assert page.operator_mission_card.property("deckRole") == "deviceOperatorMissionDeck"
        assert set(page.operator_mission_tiles) == {"device", "capture", "processing", "delivery"}
        assert page.operator_mission_card.isVisibleTo(page) is True
        assert page.operator_mission_tiles["device"][0].property("compactMetric") is True
        assert page.operator_mission_tiles["processing"][1].text().startswith("status=")
        assert page.operator_evidence_card.property("cardRole") == "panel"
        assert page.operator_evidence_card.property("deckRole") == "deviceOperatorEvidenceMatrix"
        assert set(page.operator_evidence_tiles) == {
            "latest_frame",
            "protocol_tx",
            "site_event",
            "runtime_buffer",
            "processing_gate",
            "delivery_gate",
        }
        assert page.operator_evidence_card.isVisibleTo(page) is True
        assert page.operator_evidence_tiles["runtime_buffer"][0].property("compactMetric") is True
        assert "帧" in page.operator_evidence_tiles["runtime_buffer"][0].text()
        assert page.operator_evidence_tiles["processing_gate"][1].text().startswith("windows=")
        assert page.activity_card.property("cardRole") == "rail"
        assert set(page.readiness_values) == {"fleet", "target", "protocol", "next"}
        assert page.readiness_values["fleet"][0].text() in {"可采", "待检查"}
        assert page.readiness_values["next"][0].text() in {"连接设备", "进入采集", "处理异常", "选择设备"}
        controller.set_view_mode("engineer")
        assert page.operator_mission_card.isVisibleTo(page) is False
        assert page.operator_evidence_card.isVisibleTo(page) is False
        assert page.activity_card.isVisibleTo(page) is True
    finally:
        page.deleteLater()
        controller.shutdown()


def test_device_center_top_decks_fit_common_desktop_viewports() -> None:
    app = _app()
    controller = StudioController()
    page = DeviceCenterPage(controller)
    try:
        page.show()
        controller.set_view_mode("operator")
        for width, height in ((1280, 760), (1440, 920), (1600, 900)):
            page.resize(width, height)
            page.refresh()
            app.processEvents()

            top_cards = [page.status_card, page.field_readiness_card, page.quick_card, page.device_grid_card]
            for card in top_cards:
                assert_contained(page, card, page)
            assert_no_visual_overlap(top_cards, page)
            assert widget_bounds(page.device_grid_card, page).top() < height
            assert page.quick_card.height() <= page.quick_card.maximumHeight()
            assert page.quick_add_panel.height() <= page.quick_add_panel.maximumHeight()
            assert page.quick_actions_panel.height() <= page.quick_actions_panel.maximumHeight()
            assert_no_visible_competitor_name(page)
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()


def test_realtime_page_uses_session_cockpit_deck() -> None:
    _app()
    controller = StudioController()
    page = RealtimePage(controller)
    try:
        page.refresh()

        assert page.property("pageSurface") is True
        assert page.control_card.property("cardRole") == "command"
        assert page.capture_target_panel.property("cardRole") == "tile"
        assert page.capture_metric_panel.property("cardRole") == "tile"
        assert page.capture_action_panel.property("cardRole") == "tile"
        assert page.capture_command_chip.text() == "实时控制台"
        assert page.summary_card.property("cardRole") == "cockpit"
        assert page.summary_card.property("deckRole") == "realtimeSummaryDeck"
        assert page.summary_card.maximumHeight() == 116
        assert len(page.summary_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
        assert all(value.property("compactMetric") is True for value in page.summary_values.values())
        assert page.plot_card.property("cardRole") == "panel"
        assert page.bottom_card.property("cardRole") == "rail"
        assert page.bottom_card.minimumHeight() == 162
        assert page.bottom_card.maximumHeight() == 180
        assert page.session_device_value.property("compactMetric") is True
        assert page.session_state_chip.text() in {"待连接", "需关注", "采集中", "等待帧"}
        assert page.session_device_value.text() != "--"
        assert "buffer=" in page.session_window_note.text()
    finally:
        page.deleteLater()
        controller.shutdown()


def test_realtime_page_viewport_layout_keeps_cockpit_stable() -> None:
    app = _app()
    controller = StudioController()
    page = RealtimePage(controller)
    try:
        page.show()
        for width, height in ((1280, 760), (1440, 920), (1600, 900)):
            page.resize(width, height)
            page.refresh()
            app.processEvents()

            assert page.width() <= width
            assert page.height() <= height
            page_cards = [page.control_card, page.summary_card, page.plot_card, page.bottom_card]
            for card in page_cards:
                assert_contained(page, card, page)
            assert_no_visual_overlap(page_cards, page)

            control_panels = [page.capture_target_panel, page.capture_metric_panel, page.capture_action_panel]
            for panel in control_panels:
                assert_contained(page.control_card, panel, page)
            assert_no_visual_overlap(control_panels, page)

            for card in page.summary_metric_cards:
                assert_contained(page.summary_card, card, page)
            assert_no_visual_overlap(page.summary_metric_cards, page)
            assert_no_visible_competitor_name(page)
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()
