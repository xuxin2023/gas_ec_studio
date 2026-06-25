from __future__ import annotations

import os

from PySide6.QtCore import Qt
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
        assert page.status_card.property("deviceFleetStatusDock") is True
        assert page.status_card.property("deviceFleetTelemetryStrip") is True
        assert page.status_card.maximumHeight() == 82
        assert len(page.status_metric_cards) == 5
        assert all(card.property("deviceFleetMetric") is True for card in page.status_metric_cards)
        assert set(page.status_metric_cards_by_key) == {
            "online_devices",
            "abnormal_devices",
            "sampling_devices",
            "recent_alarm",
            "last_updated_at",
        }
        assert page.status_metric_cards_by_key["online_devices"].property("deviceFleetMetricKey") == "online_devices"
        assert page.status_metric_cards_by_key["abnormal_devices"].property("fleetMetricTone") in {"success", "danger"}
        assert page.status_metric_cards_by_key["sampling_devices"].property("fleetMetricTone") in {"accent", "neutral"}
        assert all(card.maximumHeight() == 58 for card in page.status_metric_cards)
        assert page.field_readiness_card.property("cardRole") == "panel"
        assert page.field_readiness_card.property("fieldReadinessDock") is True
        assert page.field_readiness_card.maximumHeight() == 128
        assert page.field_action_card.property("deckRole") == "deviceCenterActionDock"
        assert page.field_action_card.property("fieldActionDock") is True
        assert page.field_action_card.maximumHeight() == 56
        assert page.fleet_next_button.property("railAction") is True
        assert page.fleet_detail_button.property("railAction") is True
        assert page.fleet_realtime_button.property("railAction") is True
        assert page.fleet_log_button.property("railAction") is True
        assert page.fleet_next_button.property("fieldActionButton") is True
        assert page.fleet_detail_button.property("fieldActionButton") is True
        assert page.fleet_realtime_button.property("fieldActionButton") is True
        assert page.fleet_log_button.property("fieldActionButton") is True
        assert page.fleet_next_button.text() == "下一步"
        assert page.fleet_realtime_button.text() == "实时"
        assert page.quick_card.property("cardRole") == "command"
        assert page.quick_card.maximumHeight() == 154
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
        assert page.quick_add_panel.maximumHeight() == 96
        assert page.quick_actions_panel.property("cardRole") == "tile"
        assert page.quick_actions_panel.maximumHeight() == 96
        assert page.quick_tip_card.maximumHeight() == 0
        assert page.quick_tip_card.isVisibleTo(page) is False
        assert page.device_grid_card.property("cardRole") == "panel"
        assert page.device_grid_card.minimumHeight() == 176
        assert page.device_grid_card.maximumHeight() == 184
        assert page.operations_deck_card.property("cardRole") == "rail"
        assert page.operations_deck_card.property("deckRole") == "deviceOperationsInspector"
        assert page.operations_deck_card.property("deviceOperationsCompactInspector") is True
        assert page.operations_deck_card.maximumHeight() == 184
        assert page.layout.indexOf(page.operations_deck_card) < page.layout.indexOf(page.device_grid_card)
        assert page.operations_stack.property("stackRole") == "deviceOperationsInspectorStack"
        assert page.operations_stack.property("deviceInspectorStack") is True
        assert page.operations_stack.maximumHeight() == 124
        assert all(button.property("deviceInspectorModeSwitch") is True for button in page.operations_mode_buttons.values())
        assert page.operations_mode_buttons["mission"].property("inspectorMode") == "mission"
        assert page.operations_stack.currentWidget() is page.operator_mission_card
        assert page.operations_mode_buttons["mission"].isChecked() is True
        page._show_operations_mode("evidence")
        assert page.operations_stack.currentWidget() is page.operator_evidence_card
        assert page.operations_mode_buttons["evidence"].isChecked() is True
        page._show_operations_mode("mission")
        assert page.operator_mission_card.property("cardRole") == "cockpit"
        assert page.operator_mission_card.property("deckRole") == "deviceOperatorMissionDeck"
        assert page.operator_mission_card.property("deviceInspectorSection") is True
        assert page.operator_mission_card.property("deviceInspectorSectionRole") == "mission"
        assert page.operator_mission_card.maximumHeight() == 124
        assert set(page.operator_mission_tiles) == {"device", "capture", "processing", "delivery"}
        assert set(page.operator_mission_tile_cards) == {"device", "capture", "processing", "delivery"}
        assert all(card.property("deviceMissionTile") is True for card in page.operator_mission_tile_cards.values())
        assert all(
            card.property("missionTone") in {"success", "accent", "warning", "danger"}
            for card in page.operator_mission_tile_cards.values()
        )
        assert sum(1 for card in page.operator_mission_tile_cards.values() if card.property("activeMissionStage") is True) == 1
        assert page.operator_mission_card.isVisibleTo(page) is True
        assert page.operator_mission_tiles["device"][0].property("compactMetric") is True
        assert page.operator_mission_tiles["processing"][1].text().startswith("status=")
        assert page.operator_evidence_card.property("cardRole") == "panel"
        assert page.operator_evidence_card.property("deckRole") == "deviceOperatorEvidenceMatrix"
        assert page.operator_evidence_card.property("deviceInspectorSection") is True
        assert page.operator_evidence_card.property("deviceInspectorSectionRole") == "evidence"
        assert page.operator_evidence_card.maximumHeight() == 124
        assert set(page.operator_evidence_tiles) == {
            "latest_frame",
            "protocol_tx",
            "site_event",
            "runtime_buffer",
            "processing_gate",
            "delivery_gate",
        }
        assert set(page.operator_evidence_tile_cards) == set(page.operator_evidence_tiles)
        assert all(card.property("deviceEvidenceTile") is True for card in page.operator_evidence_tile_cards.values())
        assert page.operator_evidence_tile_cards["processing_gate"].property("evidenceTone") in {
            "success",
            "warning",
        }
        assert page.operator_evidence_card.isVisibleTo(page) is False
        assert page.operator_evidence_tiles["runtime_buffer"][0].property("compactMetric") is True
        assert "帧" in page.operator_evidence_tiles["runtime_buffer"][0].text()
        assert page.operator_evidence_tiles["processing_gate"][1].text().startswith("windows=")
        assert page.activity_card.property("cardRole") == "rail"
        assert page.activity_card.property("deviceActivityInspector") is True
        assert page.activity_card.property("deviceInspectorSection") is True
        assert page.activity_card.property("deviceInspectorSectionRole") == "activity"
        assert page.activity_card.maximumHeight() == 124
        assert page.transaction_table.property("deviceInspectorActivityTable") is True
        assert page.transaction_table.maximumHeight() == 88
        assert page.transaction_table.rowCount() <= 4
        assert page.event_list.property("deviceInspectorEventList") is True
        assert page.event_list.wordWrap() is True
        assert page.event_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.event_list.maximumHeight() == 88
        assert page.event_list.count() <= 4
        page._show_operations_mode("activity")
        assert page.operations_mode_buttons["activity"].isChecked() is True
        assert page.operations_stack.currentWidget() is page.activity_card
        assert set(page.readiness_values) == {"fleet", "target", "protocol", "next"}
        assert all(tile.property("fieldReadinessTile") is True for tile in page.readiness_tiles.values())
        assert all(tile.maximumHeight() == 56 for tile in page.readiness_tiles.values())
        assert all(value.property("compactMetric") is True for value, _note in page.readiness_values.values())
        assert page.readiness_values["fleet"][0].text() in {"可采", "待检查"}
        assert page.readiness_values["next"][0].text() in {"连接设备", "进入采集", "处理异常", "选择设备"}

        selected = controller.selected_device()
        assert selected is not None
        uid = selected.config.uid
        detail_hits: list[str] = []
        realtime_hits: list[str] = []
        page.open_detail_requested.connect(detail_hits.append)
        page.open_realtime_requested.connect(lambda: realtime_hits.append("realtime"))

        page.fleet_detail_button.click()
        assert detail_hits == [uid]

        page.fleet_realtime_button.click()
        assert realtime_hits == ["realtime"]

        controller.disconnect_device(uid)
        page.refresh()
        assert page.fleet_next_button.property("targetAction") == "connect"
        assert page.operator_mission_tile_cards["device"].property("activeMissionStage") is True
        page.fleet_next_button.click()
        assert controller.selected_device() is not None
        assert controller.selected_device().runtime.connected is True

        page.fleet_log_button.click()
        assert page.operations_stack.currentWidget() in {page.operator_evidence_card, page.activity_card}
        assert page.device_grid.itemAt(0).widget().isVisibleTo(page) is True
        controller.set_view_mode("engineer")
        assert page.operator_mission_card.isVisibleTo(page) is False
        assert page.operator_evidence_card.isVisibleTo(page) is False
        assert page.activity_card.isVisibleTo(page) is True
        assert page.operations_stack.currentWidget() is page.activity_card
        assert page.operations_mode_buttons["activity"].isChecked() is True
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

            top_cards = [page.status_card, page.field_readiness_card, page.quick_card, page.operations_deck_card]
            for card in top_cards:
                assert_contained(page, card, page)
            assert_no_visual_overlap(top_cards, page)
            assert widget_bounds(page.device_grid_card, page).top() < height
            assert page.quick_card.height() <= page.quick_card.maximumHeight()
            assert page.quick_add_panel.height() <= page.quick_add_panel.maximumHeight()
            assert page.quick_actions_panel.height() <= page.quick_actions_panel.maximumHeight()
            assert_contained(page, page.field_action_card, page)
            for button in (
                page.fleet_next_button,
                page.fleet_detail_button,
                page.fleet_realtime_button,
                page.fleet_log_button,
            ):
                assert_contained(page.field_action_card, button, page)
            assert widget_bounds(page.operations_deck_card, page).top() < widget_bounds(page.device_grid_card, page).top()
            assert_contained(page, page.operations_deck_card, page)
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
        assert page.control_card.property("realtimeCommandDock") is True
        assert page.control_card.property("realtimeCaptureConsole") is True
        assert page.control_card.maximumHeight() == 146
        assert page.capture_target_panel.property("cardRole") == "tile"
        assert page.capture_target_panel.property("realtimeTargetDock") is True
        assert page.capture_target_panel.property("captureConsoleCell") is True
        assert page.capture_target_panel.property("captureCellRole") == "target"
        assert page.capture_target_panel.maximumHeight() == 76
        assert page.capture_metric_panel.property("cardRole") == "tile"
        assert page.capture_metric_panel.property("realtimeMetricDock") is True
        assert page.capture_metric_panel.property("captureConsoleCell") is True
        assert page.capture_metric_panel.property("captureCellRole") == "signal"
        assert page.capture_metric_panel.maximumHeight() == 76
        assert set(page.metric_buttons) == {"co2", "h2o", "pressure"}
        assert all(button.property("realtimeMetricToggle") is True for button in page.metric_buttons.values())
        assert all(button.property("captureMetricPill") is True for button in page.metric_buttons.values())
        assert page.capture_action_panel.property("cardRole") == "tile"
        assert page.capture_action_panel.property("deckRole") == "realtimeActionDock"
        assert page.capture_action_panel.property("realtimeActionDock") is True
        assert page.capture_action_panel.property("captureConsoleCell") is True
        assert page.capture_action_panel.property("captureCellRole") == "command"
        assert page.capture_action_panel.maximumHeight() == 84
        assert page.capture_status_panel.property("cardRole") == "tile"
        assert page.capture_status_panel.property("deckRole") == "realtimeStatusDock"
        assert page.capture_status_panel.property("realtimeStatusDock") is True
        assert page.capture_status_panel.property("captureConsoleCell") is True
        assert page.capture_status_panel.property("captureCellRole") == "link"
        assert page.capture_status_panel.maximumHeight() == 76
        assert page.capture_status_panel.property("evidenceTone") in {"success", "warning", "danger"}
        assert page.capture_command_chip.property("captureConsoleChip") is True
        assert page.capture_command_chip.text() == "实时控制台"
        assert page.start_button.property("railAction") is True
        assert page.start_button.property("realtimeActionButton") is True
        assert page.start_button.property("capturePrimaryAction") is True
        assert page.start_button.property("actionTone") == "success"
        assert page.mark_button.property("railAction") is True
        assert page.mark_button.property("realtimeActionButton") is True
        assert page.mark_button.property("captureDangerAction") is True
        assert page.mark_button.property("actionTone") == "danger"
        assert page.restore_button.property("railAction") is True
        assert page.restore_button.property("realtimeActionButton") is True
        assert page.restore_button.property("captureSecondaryAction") is True
        assert page.summary_card.property("cardRole") == "cockpit"
        assert page.summary_card.property("deckRole") == "realtimeSummaryDeck"
        assert page.summary_card.property("realtimeSummaryDock") is True
        assert page.summary_card.property("realtimeTelemetryRibbon") is True
        assert page.summary_card.maximumHeight() == 104
        assert page.session_card.property("realtimeSessionTile") is True
        assert page.session_card.maximumHeight() == 82
        assert len(page.summary_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.summary_metric_cards)
        assert all(card.property("realtimeSummaryMetric") is True for card in page.summary_metric_cards)
        assert all(card.maximumHeight() == 82 for card in page.summary_metric_cards)
        assert all(value.property("compactMetric") is True for value in page.summary_values.values())
        assert page.plot_card.property("cardRole") == "panel"
        assert page.plot_card.property("realtimePlotPanel") is True
        assert page.plot_card.property("realtimeSignalScope") is True
        assert page.hover_label.property("realtimeScopeReadout") is True
        assert page.bottom_card.property("cardRole") == "rail"
        assert page.bottom_card.property("realtimeEvidenceRail") is True
        assert page.bottom_card.property("realtimeEvidenceConsole") is True
        assert page.bottom_card.minimumHeight() == 154
        assert page.bottom_card.maximumHeight() == 170
        assert page.session_device_value.property("compactMetric") is True
        assert page.session_state_chip.text() in {"待连接", "需关注", "采集中", "等待帧"}
        assert page.session_device_value.text() != "--"
        assert "buffer=" in page.session_window_note.text()
        assert page.capture_status_value.text() in {"在线", "离线"}
        assert "valid" in page.capture_status_note.text()
        assert page.capture_status_note.toolTip()
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

            control_panels = [
                page.capture_target_panel,
                page.capture_metric_panel,
                page.capture_action_panel,
                page.capture_status_panel,
            ]
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
