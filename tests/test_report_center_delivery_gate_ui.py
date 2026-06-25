from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.pages.report_center_page import REPORT_NAV_PHASES, REPORT_SECTIONS, ReportCenterPage
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


def test_report_center_delivery_gate_stays_honest_on_empty_state(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ReportCenterPage(controller)
        page.refresh()

        assert page.property("pageSurface") is True
        assert page.tree_card.property("cardRole") == "rail"
        assert page.tree_card.property("reportNavRail") is True
        assert page.tree_card.minimumWidth() == 200
        assert page.tree_card.maximumWidth() == 248
        assert page.report_tree.indentation() == 0
        assert page.report_tree.property("reportNavTree") is True
        assert page.report_tree.rootIsDecorated() is False
        assert page.report_tree.uniformRowHeights() is True
        assert page.report_tree.topLevelItemCount() == len(REPORT_SECTIONS)
        assert page.report_tree_count_chip.text() == f"{len(REPORT_SECTIONS)} 项"
        assert page.report_tree_count_chip.maximumHeight() == 22
        assert page.report_tree_active_chip.text().startswith("运行")
        assert page.report_nav_phase_strip.property("reportNavPhaseStrip") is True
        assert page.report_nav_phase_strip.maximumHeight() == 62
        assert set(page.report_nav_phase_buttons) == {phase[0] for phase in REPORT_NAV_PHASES}
        assert all(button.property("reportNavPhaseButton") is True for button in page.report_nav_phase_buttons.values())
        assert page.report_nav_phase_buttons["run"].isChecked() is True
        assert page.report_nav_stage_note.property("reportNavStageNote") is True
        assert page.report_nav_task_map.property("deckRole") == "reportNavTaskMap"
        assert page.report_nav_task_map.property("reportNavTaskMap") is True
        assert page.report_nav_task_map.maximumHeight() == 72
        assert page.report_nav_task_chip.objectName() == "chip"
        assert page.report_nav_task_value.property("compactMetric") is True
        assert page.report_nav_task_value.property("reportNavTaskValue") is True
        assert page.report_nav_task_note.property("reportNavTaskNote") is True
        assert set(page.report_nav_task_steps) == {"catalog", "preview", "evidence", "delivery"}
        assert all(step.property("reportNavTaskStep") is True for step in page.report_nav_task_steps.values())
        assert page.report_nav_task_steps["preview"].property("activeTaskStep") is True
        assert page.report_nav_stage_note.text().startswith("运行")
        assert page.report_nav_focus_card.property("cardRole") == "console"
        assert page.report_nav_focus_card.property("deckRole") == "reportNavFocusCard"
        assert page.report_nav_focus_card.property("reportNavFocusCard") is True
        assert page.report_nav_focus_card.maximumHeight() == 56
        assert page.report_nav_focus_card.property("phaseKey") == "run"
        assert page.report_nav_focus_card.property("phaseProgress") == "1/4"
        assert page.report_nav_focus_chip.objectName() == "chip"
        assert page.report_nav_focus_value.property("compactMetric") is True
        assert page.report_nav_focus_value.property("reportNavFocusValue") is True
        assert page.report_nav_focus_note.property("reportNavFocusNote") is True
        assert page.report_nav_focus_next_button.property("reportNavNextButton") is True
        assert "下一项" in page.report_nav_focus_next_button.text()
        page.report_nav_focus_next_button.click()
        assert controller.report_center_workspace["selected_report"] == "device_status"
        assert page.report_nav_focus_card.property("phaseProgress") == "2/4"
        controller.set_report_nav_section("run_summary")
        page.refresh()
        page.report_nav_phase_buttons["qc"].click()
        assert controller.report_center_workspace["selected_report"] == "spectral_qc"
        assert page.report_nav_phase_buttons["qc"].isChecked() is True
        assert page.report_nav_focus_card.property("phaseKey") == "qc"
        assert page.report_nav_focus_card.property("phaseProgress") == "1/3"
        assert page.report_nav_task_steps["evidence"].property("activeTaskStep") is True
        controller.set_report_nav_section("run_summary")
        page.refresh()
        assert page.report_nav_task_steps["preview"].property("activeTaskStep") is True
        assert page.delivery_rail.property("cardRole") == "rail"
        assert page.delivery_rail.property("deliveryMissionRail") is True
        assert page.delivery_rail.property("desktopMissionRail") is True
        assert page.delivery_rail.minimumWidth() == 276
        assert page.delivery_rail.maximumWidth() == 340
        assert page.delivery_rail_status_chip.property("closureStage") is True
        assert page.delivery_rail_status_chip.text().startswith("待生成")
        assert page.delivery_rail_console.property("deckRole") == "deliveryRailConsole"
        assert page.delivery_rail_console.property("deliveryRailConsole") is True
        assert page.delivery_rail_console.maximumHeight() == 146
        assert page.delivery_rail_next_chip.objectName() == "chip"
        assert page.delivery_rail_next_value.property("compactMetric") is True
        assert page.delivery_rail_next_value.text()
        assert page.delivery_rail_next_note.text()
        assert "report=" not in page.delivery_rail_source_note.text()
        assert "Manifest" in page.delivery_rail_source_note.text()
        assert page.delivery_cockpit_bridge.property("cardRole") == "console"
        assert page.delivery_cockpit_bridge.property("deckRole") == "deliveryCockpitBridge"
        assert page.delivery_cockpit_bridge.property("deliveryCockpitBridge") is True
        assert page.delivery_cockpit_bridge.maximumHeight() == 42
        assert set(page.delivery_bridge_buttons) == {"report", "manifest", "validation", "package"}
        assert all(
            button.property("deliveryBridgeSegment") is True
            for button in page.delivery_bridge_buttons.values()
        )
        assert all(
            button.property("bridgeTone") in {"success", "accent", "warning", "danger"}
            for button in page.delivery_bridge_buttons.values()
        )
        assert page.delivery_bridge_buttons["report"].property("bridgeStatus") == "WT"
        assert page.delivery_bridge_buttons["manifest"].property("bridgeTone") == "warning"
        page.delivery_bridge_buttons["manifest"].click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.file_card
        page._show_delivery_focus("gate")
        assert page.delivery_rail_mode_dock.property("deliveryRailModeDock") is True
        assert all(button.property("deliveryRailModeSwitch") is True for button in page.delivery_rail_mode_buttons.values())
        assert page.delivery_rail_action_bar.property("deckRole") == "deliveryRailActionBar"
        assert page.delivery_rail_action_bar.property("deliveryRailActionDock") is True
        assert page.delivery_rail_action_bar.property("deliveryRailActionMatrix") is True
        assert page.delivery_rail_action_bar.minimumHeight() == 69
        assert page.delivery_rail_action_bar.maximumHeight() == 72
        assert page.delivery_rail_action_button.property("railAction") is True
        assert page.delivery_rail_risk_button.property("railAction") is True
        assert page.delivery_rail_export_button.property("railAction") is True
        assert page.delivery_rail_evidence_button.property("railAction") is True
        assert page.delivery_rail_action_button.property("deliveryRailAction") is True
        assert page.delivery_rail_risk_button.property("deliveryRailAction") is True
        assert page.delivery_rail_export_button.property("deliveryRailAction") is True
        assert page.delivery_rail_evidence_button.property("deliveryRailAction") is True
        assert all(
            button.minimumWidth() == 84 and button.minimumHeight() == 30
            for button in (
                page.delivery_rail_action_button,
                page.delivery_rail_risk_button,
                page.delivery_rail_export_button,
                page.delivery_rail_evidence_button,
            )
        )
        action_grid = page.delivery_rail_action_bar.layout()
        assert action_grid.itemAtPosition(0, 0).widget() is page.delivery_rail_action_button
        assert action_grid.itemAtPosition(0, 1).widget() is page.delivery_rail_risk_button
        assert action_grid.itemAtPosition(1, 0).widget() is page.delivery_rail_export_button
        assert action_grid.itemAtPosition(1, 1).widget() is page.delivery_rail_evidence_button
        assert page.delivery_mission_map.property("deliveryMissionMap") is True
        assert page.delivery_mission_map.maximumHeight() == 52
        assert set(page.delivery_mission_buttons) == {
            "report",
            "export",
            "manifest",
            "network",
            "benchmark",
            "methods",
        }
        assert all(
            button.property("deliveryMissionNode") is True
            for button in page.delivery_mission_buttons.values()
        )
        assert all(
            button.property("missionTone") in {"success", "accent", "warning", "danger"}
            for button in page.delivery_mission_buttons.values()
        )
        assert page.delivery_mission_buttons["report"].isChecked() is True
        page.delivery_mission_buttons["export"].click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.export_card
        assert page.delivery_mission_buttons["export"].isChecked() is True
        assert page.delivery_rail_action_button.property("targetAction") == "run_processing"
        assert page.delivery_rail_risk_button.property("targetAction") == "report"
        assert page.delivery_rail_risk_button.property("actionTone") == "danger"
        assert page.delivery_rail_export_button.property("targetAction") == "export_report"
        assert page.delivery_rail_export_button.property("actionTone") == "warning"
        assert page.delivery_rail_evidence_button.property("targetAction") == "evidence"
        assert page.delivery_rail_evidence_button.property("actionTone") == "warning"
        page.delivery_rail_risk_button.click()
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert page.filter_bar.maximumHeight() == 104
        assert page.project_combo.minimumWidth() >= 108
        assert page.batch_combo.minimumWidth() >= 108
        assert page.view_mode_combo.minimumWidth() >= 96
        assert page.report_command_deck.property("cardRole") == "cockpit"
        assert page.report_command_deck.property("deckRole") == "reportCommandDeck"
        assert page.report_command_deck.maximumHeight() == 156
        assert page.report_command_summary_card.property("cardRole") == "console"
        assert page.report_command_summary_card.property("reportCommandSummary") is True
        assert page.report_command_summary_card.maximumHeight() == 108
        assert page.report_command_chip.text().startswith("待生成")
        assert page.report_command_next_label.property("compactMetric") is True
        assert page.report_command_next_label.text()
        assert page.report_command_next_note.property("reportCommandNextNote") is True
        assert "->" in page.report_command_next_note.text()
        assert "report=" not in page.report_command_next_note.text()
        assert page.delivery_status_radar.property("deliveryStatusRadar") is True
        assert page.delivery_status_radar.maximumHeight() == 0
        assert page.delivery_status_radar.isHidden() is True
        assert set(page.delivery_status_radar_cards) == {"network", "benchmark", "methods", "export"}
        assert all(
            cell.property("deliveryStatusRadarCell") is True
            for cell in page.delivery_status_radar_cards.values()
        )
        assert all(value.property("compactMetric") is True for value in page.delivery_status_radar_values.values())
        assert all(cell.property("radarTone") in {"success", "accent", "warning"} for cell in page.delivery_status_radar_cards.values())
        assert set(page.report_command_tiles) == {"report", "gate", "network", "benchmark", "methods", "export"}
        assert all(tile.property("cardRole") == "tile" for tile in page.report_command_tiles.values())
        assert page.delivery_closure_strip.property("deliveryClosureStrip") is True
        assert page.delivery_closure_strip.property("deliveryClosureMatrix") is True
        assert page.delivery_closure_strip.maximumHeight() == 104
        assert all(tile.property("deliveryClosureTile") is True for tile in page.report_command_tiles.values())
        assert all(tile.maximumHeight() == 46 for tile in page.report_command_tiles.values())
        assert {
            key: tile.property("commandGroup")
            for key, tile in page.report_command_tiles.items()
        } == {
            "report": "artifact",
            "gate": "artifact",
            "network": "validation",
            "benchmark": "validation",
            "methods": "validation",
            "export": "artifact",
        }
        closure_grid = page.delivery_closure_strip.layout()
        assert closure_grid.itemAtPosition(0, 0).widget() is page.report_command_tiles["report"]
        assert closure_grid.itemAtPosition(0, 1).widget() is page.report_command_tiles["gate"]
        assert closure_grid.itemAtPosition(0, 2).widget() is page.report_command_tiles["network"]
        assert closure_grid.itemAtPosition(1, 0).widget() is page.report_command_tiles["benchmark"]
        assert closure_grid.itemAtPosition(1, 1).widget() is page.report_command_tiles["methods"]
        assert closure_grid.itemAtPosition(1, 2).widget() is page.report_command_tiles["export"]
        assert all(value.property("compactMetric") is True for value in page.report_command_values.values())
        assert all(chip.property("closureStage") is True for chip in page.report_command_chips.values())
        assert all(chip.minimumHeight() == 18 for chip in page.report_command_chips.values())
        assert page.report_command_values["report"].text() == "待生成"
        assert page.report_command_values["export"].text() == "待运行"
        assert page.delivery_rail_inspector.property("deckRole") == "deliveryRailInspector"
        assert page.delivery_rail_inspector.property("deliveryMissionInspector") is True
        assert page.delivery_rail_stack.property("stackRole") == "deliveryRailInspectorStack"
        assert page.delivery_rail_stack.count() == 2
        assert page.delivery_rail_stack.currentWidget() is page.delivery_focus_card
        assert page.delivery_rail_mode_buttons["delivery"].isChecked() is True
        page._show_delivery_rail_mode("summary")
        assert page.delivery_rail_stack.currentWidget() is page.summary_row
        assert page.delivery_rail_mode_buttons["summary"].isChecked() is True
        page._show_delivery_rail_mode("delivery")
        assert page.delivery_focus_card.property("cardRole") == "panel"
        assert page.delivery_focus_card.property("deliveryFocusShell") is True
        assert page.delivery_focus_stack.count() == 3
        assert page.delivery_focus_buttons["gate"].isChecked() is True
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert page.delivery_gate_card.property("cardRole") == "cockpit"
        assert page.delivery_gate_card.property("deckRole") == "deliveryGateMatrix"
        assert page.delivery_gate_card.property("deliveryGateCompact") is True
        assert page.delivery_gate_hero_card.property("cardRole") == "console"
        assert page.delivery_gate_hero_card.property("deckRole") == "deliveryReadinessHero"
        assert page.delivery_gate_hero_card.property("deliveryGateHero") is True
        assert page.delivery_gate_hero_card.property("deliveryGateLayer") == "summary"
        assert page.delivery_gate_hero_card.isHidden() is False
        assert page.delivery_gate_progress_badge.objectName() == "chip"
        assert page.delivery_gate_progress_badge.property("chipTone") in {"warning", "accent", "success"}
        assert page.delivery_focus_stack.property("stackRole") == "compactDeliveryInspector"
        assert page.delivery_gate_hero_card.maximumHeight() == 56
        assert page.delivery_gate_card.property("deliveryGateDetailsExpanded") is False
        assert page.delivery_gate_detail_drawer.property("cardRole") == "panel"
        assert page.delivery_gate_detail_drawer.property("deckRole") == "deliveryGateDetailDrawer"
        assert page.delivery_gate_detail_drawer.property("deliveryGateDetailDrawer") is True
        assert page.delivery_gate_detail_drawer.property("deliveryGateDetailsExpanded") is False
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_detail_drawer.maximumHeight() == 0
        assert page.delivery_gate_detail_toggle.property("deliveryGateDetailToggle") is True
        assert page.delivery_gate_detail_toggle.property("detailState") == "closed"
        assert page.delivery_gate_detail_toggle.text() == "明细"
        assert page.delivery_gate_detail_toggle.isChecked() is False
        assert page.delivery_gate_detail_pinned is False
        assert page.delivery_gate_detail_pin.property("deliveryGateDetailPin") is True
        assert page.delivery_gate_detail_pin.property("pinState") == "unpinned"
        assert page.delivery_gate_detail_pin.text() == "固定"
        assert page.delivery_gate_detail_pin.isChecked() is False
        assert page.delivery_gate_detail_drawer.property("deliveryGateDetailPinned") is False
        assert page.delivery_gate_detail_drawer.property("pinState") == "unpinned"
        assert page.delivery_gate_group_strip.property("deliveryGateGroupStrip") is True
        assert page.delivery_gate_group_strip.maximumHeight() == 26
        assert set(page.delivery_gate_group_cards) == {"artifact", "validation"}
        assert set(page.delivery_gate_group_values) == {"artifact", "validation"}
        assert set(page.delivery_gate_group_chips) == {"artifact", "validation"}
        assert page.delivery_gate_group_values["artifact"].text() == "0/3"
        assert page.delivery_gate_group_values["validation"].text() == "0/3"
        assert page.delivery_gate_group_cards["artifact"].property("deliveryGateGroupTile") is True
        assert page.delivery_gate_group_cards["artifact"].property("gateGroupKey") == "artifact"
        assert page.delivery_gate_group_cards["artifact"].property("gateGroupTone") == "warning"
        assert page.delivery_gate_group_cards["validation"].property("gateGroupKey") == "validation"
        assert page.delivery_gate_group_values["artifact"].property("deliveryGateGroupValue") is True
        assert page.delivery_gate_group_chips["artifact"].property("deliveryGateGroupChip") is True
        assert page.delivery_gate_scroll.objectName() == "deliveryGateMatrixScroll"
        assert page.delivery_gate_scroll.isVisible() is False
        page.delivery_gate_detail_toggle.click()
        assert page.delivery_gate_card.property("deliveryGateDetailsExpanded") is True
        assert page.delivery_gate_detail_drawer.property("deliveryGateDetailsExpanded") is True
        assert page.delivery_gate_detail_drawer.isHidden() is False
        assert page.delivery_gate_detail_drawer.maximumHeight() == 166
        assert page.delivery_gate_detail_toggle.property("detailState") == "open"
        assert page.delivery_gate_detail_toggle.text() == "收起"
        assert page.delivery_gate_detail_toggle.isChecked() is True
        assert page.delivery_gate_scroll.isHidden() is False
        page.delivery_gate_detail_pin.click()
        assert page.delivery_gate_detail_pinned is True
        assert page.delivery_gate_detail_pin.text() == "已固定"
        assert page.delivery_gate_detail_pin.isChecked() is True
        assert page.delivery_gate_detail_pin.property("pinState") == "pinned"
        assert page.delivery_gate_detail_drawer.property("deliveryGateDetailPinned") is True
        assert page.delivery_gate_detail_drawer.property("pinState") == "pinned"
        page.delivery_gate_detail_toggle.click()
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_detail_pinned is False
        assert page.delivery_gate_detail_pin.isChecked() is False
        assert page.delivery_gate_detail_pin.property("pinState") == "unpinned"
        page.delivery_gate_detail_toggle.click()
        assert page.delivery_gate_detail_drawer.isHidden() is False
        assert page.delivery_gate_scroll.maximumHeight() == 104
        assert page.delivery_gate_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.delivery_gate_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.delivery_gate_scroll.widget() is page.delivery_gate_grid_body
        assert page.delivery_gate_grid_body.property("deliveryGateLayeredMatrix") is True
        assert page.delivery_gate_ready_value.property("compactMetric") is True
        assert page.delivery_gate_ready_note.isHidden() is False
        assert all(tile.maximumHeight() == 34 for tile in page.delivery_gate_tiles.values())
        assert all(tile.property("deliveryGateTile") is True for tile in page.delivery_gate_tiles.values())
        assert all(tile.property("deliveryGateLayerTile") is True for tile in page.delivery_gate_tiles.values())
        assert {
            key: tile.property("deliveryGateGroup")
            for key, tile in page.delivery_gate_tiles.items()
        } == {
            "report": "artifact",
            "export": "artifact",
            "manifest": "artifact",
            "network": "validation",
            "benchmark": "validation",
            "methods": "validation",
        }
        assert page.delivery_gate_values["report"][0].property("compactMetric") is True
        assert page.delivery_gate_values["report"][1].isHidden() is False
        assert page.delivery_gate_values["report"][2].isHidden() is False
        assert page.delivery_gate_values["report"][2].property("closureStage") is True
        assert page.delivery_gate_values["report"][2].minimumHeight() == 14
        assert page.delivery_gate_next_value.property("compactMetric") is True
        assert page.delivery_gate_next_card.isHidden() is True
        assert page.delivery_gate_next_note.isHidden() is True
        assert page.preview_header_card.property("cardRole") == "cockpit"
        assert page.preview_header_card.property("deckRole") == "reportPreviewHeader"
        assert page.preview_header_card.property("reportPreviewHeaderDock") is True
        assert page.preview_header_card.maximumHeight() == 0
        assert page.preview_header_card.isHidden() is True
        assert page.preview_command_strip.property("cardRole") == "console"
        assert page.preview_command_strip.property("deckRole") == "reportPreviewCommandStrip"
        assert page.preview_command_strip.property("previewCommandDock") is True
        assert page.preview_command_strip.maximumHeight() == 0
        assert page.preview_command_strip.isHidden() is True
        assert set(page.preview_command_tiles) == {"report", "gate", "export"}
        assert all(tile.property("previewCommandTile") is True for tile in page.preview_command_tiles.values())
        assert page.preview_command_values["report"].text() == "待生成"
        assert page.preview_command_values["gate"].text() == page.delivery_gate_chip.text()
        assert page.preview_command_values["export"].text() == "待运行"
        assert page.preview_command_buttons["generate"].property("targetAction") == "generate_report"
        assert page.preview_command_buttons["export"].property("targetAction") == "export_report"
        assert page.preview_command_buttons["evidence"].property("targetAction") == "evidence"
        assert all(button.property("railAction") is True for button in page.preview_command_buttons.values())
        assert all(button.property("previewCommandAction") is True for button in page.preview_command_buttons.values())
        assert page.preview_deck_card.property("cardRole") == "rail"
        assert page.preview_deck_card.property("deckRole") == "reportPreviewDeck"
        assert page.preview_deck_card.property("reportPreviewWorkbench") is True
        assert page.preview_deck_card.property("activePane") == "table"
        assert page.preview_pane_switcher.property("deckRole") == "previewPaneSwitcher"
        assert all(button.property("previewPaneSwitch") is True for button in page.preview_content_switches.values())
        assert page.preview_analysis_strip.property("deckRole") == "reportPreviewAnalysisStrip"
        assert page.preview_analysis_strip.property("reportPreviewAnalysisStrip") is True
        assert page.preview_analysis_strip.property("analysisMode") == "table"
        assert page.preview_analysis_strip.maximumHeight() == 34
        assert page.preview_analysis_chip.objectName() == "chip"
        assert page.preview_analysis_value.property("compactMetric") is True
        assert page.preview_pane_hint_label.text()
        assert page.preview_pane_hint_label.property("reportPreviewAnalysisHint") is True
        assert page.preview_pane_hint_label.isHidden() is False
        assert page.preview_route_strip.property("deckRole") == "previewWorkflowRoute"
        assert page.preview_route_strip.property("previewWorkflowRoute") is True
        assert page.preview_route_strip.maximumHeight() == 34
        assert page.preview_route_stage_chip.objectName() == "chip"
        assert page.preview_route_title_label.property("previewRouteTitle") is True
        assert set(page.preview_route_buttons) == {"catalog", "preview", "delivery"}
        assert all(button.property("previewWorkflowRouteButton") is True for button in page.preview_route_buttons.values())
        assert page.preview_route_buttons["preview"].isChecked() is True
        page.preview_route_buttons["delivery"].click()
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert page.preview_route_buttons["delivery"].isChecked() is True
        page.preview_route_buttons["preview"].click()
        assert page.preview_route_buttons["preview"].isChecked() is True
        assert page.report_action_drawer.property("deckRole") == "reportActionDrawer"
        assert page.report_action_drawer.property("reportActionDrawer") is True
        assert page.report_action_drawer.maximumHeight() == 58
        assert set(page.report_action_buttons) == {"generate", "export", "evidence", "compare"}
        assert page.report_action_next_chip.objectName() == "chip"
        assert page.report_action_buttons["generate"].property("targetAction") == "generate_report"
        assert page.report_action_buttons["export"].property("targetAction") == "export_report"
        assert page.report_action_buttons["evidence"].property("targetAction") == "evidence"
        assert page.report_action_buttons["compare"].property("targetAction") == "compare_batches"
        assert all(button.property("reportActionDrawerButton") is True for button in page.report_action_buttons.values())
        preview_deck_layout = page.preview_deck_card.layout()
        assert preview_deck_layout.indexOf(page.report_action_drawer) < preview_deck_layout.indexOf(page.preview_content_card)
        assert preview_deck_layout.indexOf(page.preview_content_card) < preview_deck_layout.indexOf(page.preview_metrics_row)
        assert page.preview_delivery_trail_card.property("cardRole") == "console"
        assert page.preview_delivery_trail_card.property("previewTrailStrip") is True
        assert page.preview_delivery_trail_card.maximumHeight() == 54
        assert page.preview_delivery_trail_value.property("compactMetric") is True
        assert page.preview_delivery_trail_chip.property("chipTone") == "accent"
        assert page.preview_content_card.property("cardRole") == "panel"
        assert page.preview_content_card.property("deckRole") == "compactPreviewPane"
        assert page.preview_content_card.property("density") == "desktop"
        assert page.preview_content_card.property("plotStatus") == "tableOnly"
        assert page.preview_content_card.maximumHeight() == 232
        assert page.preview_workbench_bridge.property("cardRole") == "console"
        assert page.preview_workbench_bridge.property("deckRole") == "previewWorkbenchBridge"
        assert page.preview_workbench_bridge.property("previewWorkbenchBridge") is True
        assert page.preview_workbench_bridge.maximumHeight() == 36
        assert set(page.preview_workbench_buttons) == {"data", "evidence", "insight"}
        assert all(
            button.property("previewWorkbenchSegment") is True
            for button in page.preview_workbench_buttons.values()
        )
        assert page.preview_workbench_buttons["data"].isChecked() is True
        assert page.preview_workbench_buttons["data"].property("activeWorkbenchSegment") is True
        assert page.preview_workbench_buttons["data"].property("workbenchTone") == "success"
        assert page.preview_workbench_buttons["evidence"].property("workbenchStatus") == "0/3"
        page.preview_workbench_buttons["evidence"].click()
        assert page.preview_workbench_buttons["evidence"].isChecked() is True
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.file_card
        page._show_delivery_focus("gate")
        page.preview_workbench_buttons["insight"].click()
        assert page.preview_workbench_buttons["insight"].isChecked() is True
        assert page.preview_content_card.property("activePane") == "insight"
        page._show_preview_content_mode("table")
        assert page.preview_content_splitter.objectName() == "reportPreviewSplitPane"
        assert page.preview_content_splitter.property("reportPreviewSplitPane") is True
        assert page.preview_content_splitter.maximumHeight() == 164
        assert page.preview_primary_pane.property("reportPreviewPrimaryPane") is True
        assert page.preview_context_pane.property("reportPreviewContextPane") is True
        assert page.preview_context_pane.property("reportPreviewEvidenceRail") is True
        assert page.preview_context_pane.minimumWidth() == 190
        assert page.preview_evidence_summary_card.property("previewEvidenceSummary") is True
        assert page.preview_evidence_summary_card.maximumHeight() == 62
        assert page.preview_evidence_progress_chip.objectName() == "chip"
        assert page.preview_evidence_progress_chip.text().endswith("/3")
        assert page.preview_evidence_note.property("previewEvidenceNote") is True
        assert page.preview_evidence_note.isHidden() is True
        assert page.preview_evidence_status_row.property("previewEvidenceStatusRow") is True
        assert set(page.preview_evidence_status_chips) == {"manifest", "network", "methods"}
        assert all(chip.property("previewEvidenceStatusChip") is True for chip in page.preview_evidence_status_chips.values())
        assert set(page.preview_context_cards) == {"manifest", "network", "methods"}
        assert all(card.property("previewContextTile") is True for card in page.preview_context_cards.values())
        assert all(card.property("previewEvidenceTile") is True for card in page.preview_context_cards.values())
        assert all(card.maximumHeight() == 28 for card in page.preview_context_cards.values())
        assert all(chip.property("closureStage") is True for chip in page.preview_context_chips.values())
        assert all(button.property("previewContextAction") is True for button in page.preview_context_buttons.values())
        assert page.preview_context_cards["manifest"].property("contextTone") == "warning"
        page.preview_context_buttons["network"].click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.file_card
        page._show_delivery_focus("gate")
        page._show_inspector_section("export")
        assert page.expert_review_card.property("deckRole") == "expertReviewStrip"
        assert page.expert_review_card.isHidden() is True
        assert page.preview_plot.isHidden() is True
        assert page.preview_plot.maximumHeight() == 0
        assert page.preview_table.maximumHeight() == 146
        assert "rows=" not in page.preview_table_note.text()
        assert "columns=" not in page.preview_table_note.text()
        assert "表格：" in page.preview_table_note.text()
        assert page.preview_content_card.property("activePane") == "table"
        assert set(page.preview_content_switches) == {"plot", "table", "insight"}
        assert page.preview_content_switches["table"].isChecked() is True
        assert page.preview_insight_card.property("deckRole") == "reportPreviewInsightPane"
        assert page.preview_insight_card.isHidden() is True
        assert page.preview_table.isHidden() is False
        page._show_preview_content_mode("insight")
        assert page.preview_content_card.property("activePane") == "insight"
        assert page.preview_deck_card.property("activePane") == "insight"
        assert page.preview_analysis_strip.property("analysisMode") == "insight"
        assert page.preview_analysis_value.text()
        assert page.preview_insight_card.isHidden() is False
        assert page.preview_table.isHidden() is True
        assert page.preview_metrics_row.property("reportPreviewMetricStrip") is True
        assert page.preview_metrics_row.maximumHeight() == 62
        assert len(page.preview_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.preview_metric_cards)
        assert all(card.property("reportPreviewMetric") is True for card in page.preview_metric_cards)
        assert all(card.maximumHeight() == 58 for card in page.preview_metric_cards)
        assert all(value.property("compactMetric") is True for value in page.preview_metric_values)
        assert page.recent_status_value.toolTip()
        assert len(page.recent_status_value.text()) <= 9
        assert page.last_generated_value.toolTip()
        assert page.closure_deck_card.property("cardRole") == "rail"
        assert page.closure_deck_card.property("closureLaunchDeck") is True
        assert page.closure_deck_chip.text() == "下一步"
        assert page.inner_inspector.property("cardRole") == "panel"
        assert page.inner_inspector.property("deliveryDetailShell") is True
        assert page.inspector_stack.count() == 4
        assert page.inspector_stack.currentWidget() is page.export_card
        assert page.inspector_switches["export"].isChecked() is True
        assert page.empty_state_card.property("cardRole") == "cockpit"
        assert page.empty_state_card.property("deckRole") == "launchActionDeck"
        assert page.empty_state_card.maximumHeight() == 228
        assert page.empty_state_card.isHidden() is False
        assert page.empty_state_chip.text() == "待运行"
        assert page.empty_state_next_card.property("cardRole") == "console"
        assert page.empty_state_next_card.property("deckRole") == "launchNextActionHero"
        assert page.empty_state_next_value.property("compactMetric") is True
        assert page.empty_state_next_value.text() == "先运行处理"
        assert "尚未发现可导出的真实运行结果" in page.empty_state_gap_label.text()
        route_tiles = [
            tile
            for tile in page.empty_state_card.findChildren(type(page.empty_state_card))
            if tile.property("routeAction") is True
        ]
        assert len(route_tiles) == 4
        assert all(tile.maximumHeight() == 58 for tile in route_tiles)
        assert set(page.empty_state_route_tiles) == {"运行处理", "生成报告", "导出", "打开验证包"}
        assert set(page.empty_state_route_status_chips) == {"运行处理", "生成报告", "导出", "打开验证包"}
        assert all(tile.property("launchRouteTile") is True for tile in page.empty_state_route_tiles.values())
        assert all(chip.property("launchRouteStatusChip") is True for chip in page.empty_state_route_status_chips.values())
        assert all(button.property("launchRouteButton") is True for button in page.empty_state_action_buttons.values())
        assert page.empty_state_route_tiles["运行处理"].property("routeTone") == "accent"
        assert page.empty_state_route_tiles["生成报告"].property("routeTone") == "warning"
        assert page.empty_state_route_status_chips["运行处理"].text() == "可启动"
        assert page.empty_state_route_status_chips["生成报告"].text() == "锁定"
        assert page.empty_state_action_buttons["运行处理"].isEnabled() is True
        assert page.empty_state_action_buttons["打开验证包"].isEnabled() is True
        assert page.empty_state_action_buttons["生成报告"].isEnabled() is False
        assert page.empty_state_action_buttons["导出"].isEnabled() is False
        assert set(page.delivery_gate_values) == {
            "report",
            "export",
            "manifest",
            "network",
            "benchmark",
            "methods",
        }
        assert page.delivery_gate_values["export"][0].text() in {"待运行", "可导出", "已导出"}
        assert page.delivery_gate_values["report"][0].text() == "待生成"
        assert page.delivery_gate_values["manifest"][0].text() == "待导出"
        assert "inactive" not in page.delivery_gate_values["benchmark"][0].text()
        assert "inactive" not in page.delivery_gate_values["benchmark"][1].text()
        assert page.delivery_gate_chip.text() in {"待生成", "待复核"}
        assert page.delivery_gate_next_value.text() in {"生成报告", "运行处理", "导出交付包"}

        page._show_inspector_section("file")

        assert page.inspector_stack.currentWidget() is page.file_card
        assert page.inspector_switches["file"].isChecked() is True
        assert page.inspector_switches["export"].isChecked() is False
        assert page.delivery_detail_status_header.property("deliveryDetailStatusHeader") is True
        assert page.delivery_detail_status_header.property("detailSection") == "file"
        assert page.delivery_detail_status_header.property("detailTone") in {"warning", "accent", "success"}
        assert page.delivery_detail_status_title.text() == "交付文件"
        assert page.delivery_detail_status_chip.property("deliveryDetailStatusChip") is True
        assert page.delivery_detail_status_chip.text().endswith("/3")
        assert page.delivery_detail_status_note.property("deliveryDetailStatusNote") is True
        assert page.delivery_detail_status_note.toolTip()
        page._show_delivery_focus("batch")
        assert page.delivery_focus_stack.currentWidget() is page.batch_card
        assert page.batch_card.property("deliveryBatchPanel") is True
        assert page.delivery_focus_buttons["batch"].isChecked() is True
        assert page.delivery_rail_stack.currentWidget() is page.delivery_focus_card
        assert page.delivery_rail_mode_buttons["delivery"].isChecked() is True
        page._show_delivery_focus("details")
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.delivery_focus_buttons["details"].isChecked() is True
        assert page.inner_inspector.property("deckRole") == "deliveryDetailInspector"
        assert page.inspector_stack.property("stackRole") == "deliveryDetailInspectorStack"
        assert page.export_card.property("deliveryInspectorSection") is True
        assert page.file_card.property("deliveryInspectorSection") is True
        assert page.version_card.property("deliveryInspectorSection") is True
        assert page.usage_card.property("deliveryInspectorSection") is True
        assert set(page.inspector_detail_tiles) == {
            "export.status",
            "export.options",
            "export.report",
            "file.count",
            "file.manifest",
            "file.network",
            "version.source",
            "version.updated",
            "version.count",
            "usage.audience",
            "usage.count",
            "usage.next",
        }
        assert all(tile.property("cardRole") == "tile" for tile in page.inspector_detail_tiles.values())
        assert all(tile.property("inspectorTile") is True for tile in page.inspector_detail_tiles.values())
        assert all(tile.maximumHeight() == 48 for tile in page.inspector_detail_tiles.values())
    finally:
        page.deleteLater()
        controller.shutdown()


def test_report_center_delivery_inspector_fits_common_desktop_viewports(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ReportCenterPage(controller)
        page.show()
        for width, height in ((1280, 760), (1440, 920), (1600, 900)):
            page.resize(width, height)
            page.refresh()
            page._show_delivery_focus("gate")
            app.processEvents()

            assert page.width() <= width
            assert page.height() <= height
            assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
            assert page.delivery_focus_stack.property("stackRole") == "compactDeliveryInspector"
            assert page.delivery_rail.width() <= page.delivery_rail.maximumWidth()
            assert page.delivery_rail.width() >= page.delivery_rail.minimumWidth()
            assert_contained(page.tree_card, page.report_nav_phase_strip, page)
            assert_contained(page.tree_card, page.report_nav_focus_card, page)
            assert_contained(page.tree_card, page.report_nav_task_map, page)
            for button in page.report_nav_phase_buttons.values():
                assert_contained(page.report_nav_phase_strip, button, page)
            assert_contained(page.report_nav_focus_card, page.report_nav_focus_next_button, page)
            assert_no_visual_overlap([page.report_nav_phase_strip, page.report_nav_focus_card, page.report_nav_task_map], page)
            assert_contained(page, page.delivery_rail, page)

            page._show_delivery_rail_mode("summary")
            app.processEvents()
            assert_contained(page.delivery_rail, page.delivery_rail_console, page)
            assert_contained(page.delivery_rail_console, page.delivery_rail_mode_dock, page)
            assert_contained(page.delivery_rail, page.delivery_rail_action_bar, page)
            assert_contained(page.delivery_rail_console, page.delivery_rail_action_bar, page)
            assert_contained(page.delivery_rail, page.delivery_mission_map, page)
            for button in (
                page.delivery_rail_action_button,
                page.delivery_rail_risk_button,
                page.delivery_rail_export_button,
                page.delivery_rail_evidence_button,
            ):
                assert_contained(page.delivery_rail_action_bar, button, page)
            assert_no_visual_overlap(
                [
                    page.delivery_rail_action_button,
                    page.delivery_rail_risk_button,
                    page.delivery_rail_export_button,
                    page.delivery_rail_evidence_button,
                ],
                page,
            )
            assert_contained(page.delivery_rail, page.delivery_cockpit_bridge, page)
            for button in page.delivery_bridge_buttons.values():
                assert_contained(page.delivery_cockpit_bridge, button, page)
            assert_no_visual_overlap(list(page.delivery_bridge_buttons.values()), page)
            summary_cards = list(page.summary_cards.values())
            assert len(summary_cards) == 4
            for card in summary_cards:
                assert_contained(page.delivery_rail, card, page)
            assert_no_visual_overlap(summary_cards, page)

            page._show_delivery_focus("gate")
            app.processEvents()
            assert_contained(page, page.report_command_deck, page)
            assert_contained(page.report_command_deck, page.report_command_summary_card, page)
            assert_contained(page.report_command_deck, page.delivery_closure_strip, page)
            for tile in page.report_command_tiles.values():
                assert_contained(page.delivery_closure_strip, tile, page)
            assert_no_visual_overlap(
                [page.report_command_summary_card, page.delivery_closure_strip],
                page,
            )
            assert_no_visual_overlap(list(page.report_command_tiles.values()), page)
            assert_contained(page, page.preview_content_splitter, page)
            assert_contained(page.preview_deck_card, page.preview_analysis_strip, page)
            assert_contained(page.preview_deck_card, page.preview_route_strip, page)
            for button in page.preview_route_buttons.values():
                assert_contained(page.preview_route_strip, button, page)
            assert_contained(page.preview_content_card, page.preview_workbench_bridge, page)
            for button in page.preview_workbench_buttons.values():
                assert_contained(page.preview_workbench_bridge, button, page)
            assert_no_visual_overlap(list(page.preview_workbench_buttons.values()), page)
            assert_contained(page.preview_deck_card, page.preview_content_splitter, page)
            assert_contained(page.preview_content_splitter, page.preview_primary_pane, page)
            assert_contained(page.preview_content_splitter, page.preview_context_pane, page)
            assert_contained(page.preview_context_pane, page.preview_evidence_summary_card, page)
            for tile in page.preview_context_cards.values():
                assert_contained(page.preview_context_pane, tile, page)
            assert_no_visual_overlap(
                [page.preview_evidence_summary_card, *page.preview_context_cards.values()],
                page,
            )
            assert_contained(page.preview_deck_card, page.report_action_drawer, page)
            assert page.preview_analysis_strip.geometry().bottom() < page.preview_route_strip.geometry().top()
            assert page.preview_route_strip.geometry().bottom() < page.report_action_drawer.geometry().top()
            assert page.report_action_drawer.geometry().bottom() < page.preview_content_card.geometry().top()
            for button in page.report_action_buttons.values():
                assert_contained(page.report_action_drawer, button, page)
            for button in page.preview_content_switches.values():
                assert_contained(page.preview_deck_card, button, page)
            if page.delivery_gate_detail_toggle.isChecked():
                page.delivery_gate_detail_toggle.click()
                app.processEvents()
            assert page.delivery_gate_detail_drawer.isHidden() is True
            assert page.delivery_gate_scroll.isVisible() is False
            assert_contained(page.delivery_gate_card, page.delivery_gate_group_strip, page)
            for widget in page.delivery_gate_group_cards.values():
                assert_contained(page.delivery_gate_group_strip, widget, page)
            assert_no_visual_overlap(
                [page.delivery_gate_hero_card, page.delivery_gate_group_strip],
                page,
            )
            page.delivery_gate_detail_toggle.click()
            app.processEvents()
            assert page.delivery_gate_card.property("deliveryGateDetailsExpanded") is True
            assert page.delivery_gate_detail_drawer.property("deliveryGateDetailsExpanded") is True
            assert page.delivery_gate_detail_drawer.isHidden() is False
            assert page.delivery_gate_scroll.isVisible() is True
            assert_contained(page.delivery_rail, page.delivery_gate_detail_drawer, page)
            assert_contained(page.delivery_gate_detail_drawer, page.delivery_gate_scroll, page)
            for widget in (page.delivery_gate_tiles["report"], page.delivery_gate_tiles["export"]):
                assert_contained(page.delivery_gate_scroll.viewport(), widget, page)
            for widget in page.delivery_gate_tiles.values():
                assert_contained(page.delivery_gate_grid_body, widget, page)
            assert_no_visual_overlap(
                [page.delivery_gate_card, page.delivery_gate_detail_drawer],
                page,
            )
            assert_no_visual_overlap(list(page.delivery_gate_group_cards.values()), page)
            assert_no_visual_overlap(list(page.delivery_gate_tiles.values()), page)
            page.delivery_gate_detail_pin.click()
            assert page.delivery_gate_detail_pinned is True
            page._show_delivery_focus("details")
            app.processEvents()
            assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
            assert page.delivery_gate_detail_drawer.isHidden() is False
            assert page.delivery_gate_detail_toggle.isChecked() is True
            assert page.delivery_gate_detail_pin.isChecked() is True
            assert_contained(page.delivery_rail, page.delivery_gate_detail_drawer, page)
            page._show_delivery_rail_mode("summary")
            app.processEvents()
            assert page.delivery_gate_detail_drawer.isHidden() is True
            assert page.delivery_gate_detail_toggle.isChecked() is False
            assert page.delivery_gate_detail_pin.isChecked() is False
            assert page.delivery_gate_detail_pinned is False

            assert_no_visible_competitor_name(page)
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()


def test_report_center_delivery_overlay_escape_and_detail_routes(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ReportCenterPage(controller)
        page.show()
        page.refresh()
        page._show_delivery_focus("gate")
        app.processEvents()

        page.delivery_gate_detail_toggle.click()
        page.delivery_gate_detail_pin.click()
        assert page.delivery_gate_detail_drawer.isHidden() is False
        assert page.delivery_gate_detail_pinned is True

        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        QApplication.sendEvent(page, event)
        app.processEvents()
        assert event.isAccepted() is True
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_detail_toggle.isChecked() is False
        assert page.delivery_gate_detail_pin.isChecked() is False
        assert page.delivery_gate_detail_pinned is False

        page._show_delivery_focus("gate")
        page.delivery_gate_detail_toggle.click()
        page.delivery_gate_detail_pin.click()
        page._activate_delivery_mission_node("export")
        app.processEvents()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.export_card
        assert page.delivery_mission_buttons["export"].isChecked() is True
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_detail_toggle.isChecked() is False
        assert page.delivery_gate_detail_pin.isChecked() is False
        assert page.delivery_gate_detail_pinned is False

        page._show_delivery_focus("gate")
        page.delivery_gate_detail_toggle.click()
        page.delivery_gate_detail_pin.click()
        page._activate_delivery_bridge_segment("manifest")
        app.processEvents()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.file_card
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_detail_toggle.isChecked() is False
        assert page.delivery_gate_detail_pin.isChecked() is False
        assert page.delivery_gate_detail_pinned is False
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()


def test_report_center_delivery_gate_closes_when_delivery_chain_is_ready(monkeypatch, tmp_path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ReportCenterPage(controller)
        manifest_path = tmp_path / "export_manifest.json"
        workspace = controller.report_center_workspace
        workspace["filters"] = {"project": "demo", "batch": "batch-001", "view_mode": "Management"}
        workspace["summary"] = {
            "recent_status": "最近批次已完成",
            "exportable_reports": 3,
            "attention_count": 0,
            "last_generated_at": "2026-06-09 10:00",
        }
        workspace["selected_report"] = "run_summary"
        workspace["export_status"] = f"交付包已导出（2026-06-09 10:00）：{tmp_path}"
        workspace["network_output"] = {"schema_target": "FLUXNET"}
        workspace["benchmark"] = {"status": "active", "reference_id": "ref-001"}
        workspace["reports"] = {
            "run_summary": {
                "report_key": "run_summary",
                "title": "运行摘要",
                "source": "batch-001",
                "updated_at": "2026-06-09 10:00",
                "metrics": [("窗口数", "2"), ("通过率", "100%")],
                "plot_series": [1.0, 1.0],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("a", "1", "ok"), ("b", "2", "ok"), ("c", "3", "ok")],
                "conclusions": ["批次可交付。"],
                "export_options": ["导出当前报告"],
                "file_info": {"export_manifest": str(manifest_path)},
                "versions": [],
                "usage": [],
            },
            "benchmark_cockpit": {
                "report_key": "benchmark_cockpit",
                "title": "基准驾驶舱",
                "source": "ref-001",
                "updated_at": "2026-06-09 10:00",
                "metrics": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [
                    ("reference_id", "ref-001", "参考数据集 ID"),
                    ("status", "active", "benchmark 状态"),
                    ("pass_rate", "100.0%", "窗口通过率"),
                    ("failed_fields", "无", "未通过的字段"),
                    ("network.schema_target", "FLUXNET", "网络导出目标"),
                    ("network.validation_status", "valid", "网络校验状态"),
                    ("network.missing_fields", "无", "网络缺失字段"),
                ],
                "file_info": {"网络校验": str(tmp_path / "network_validation_summary.json")},
            },
            "method_provenance": {
                "report_key": "method_provenance",
                "title": "方法溯源",
                "source": "batch-001",
                "updated_at": "2026-06-09 10:00",
                "metrics": [
                    ("Footprint", "Kljun"),
                    ("不确定度", "Mann & Lenschow"),
                    ("谱修正", "Fratini"),
                ],
                "table_headers": ["方法族", "方法名", "溯源"],
                "table_rows": [],
                "file_info": {"方法汇总": str(tmp_path / "method_rollup.json")},
            },
        }

        page.refresh()

        assert page.view_mode_combo.currentText() == "管理汇报"
        assert page.delivery_gate_chip.text() == "可交付"
        assert page.delivery_gate_card.property("gateStatus") == "ready"
        assert page.delivery_gate_ready_value.text() == "可交付"
        assert page.delivery_gate_progress_badge.text().startswith("6/6")
        assert page.delivery_gate_progress_badge.property("chipTone") == "success"
        assert page.delivery_gate_group_values["artifact"].text() == "3/3"
        assert page.delivery_gate_group_values["validation"].text() == "3/3"
        assert page.delivery_gate_group_cards["artifact"].property("gateGroupTone") == "success"
        assert page.delivery_gate_group_cards["validation"].property("gateGroupTone") == "success"
        assert page.delivery_gate_group_chips["artifact"].text() == "闭合"
        assert page.delivery_gate_group_chips["validation"].text() == "闭合"
        assert page.delivery_gate_detail_drawer.isHidden() is True
        assert page.delivery_gate_scroll.isVisible() is False
        page.delivery_gate_detail_toggle.click()
        assert page.delivery_gate_detail_drawer.isHidden() is False
        assert page.delivery_gate_scroll.isHidden() is False
        assert page.delivery_gate_detail_toggle.text() == "收起"
        assert "交付归档" in page.delivery_gate_ready_note.text()
        assert page.delivery_gate_values["network"][0].text() == "FLUXNET"
        assert "缺失：无" in page.delivery_gate_values["network"][1].text()
        assert page.delivery_gate_tiles["network"].property("gateTone") == "success"
        assert page.delivery_gate_values["benchmark"][0].text() == "ref-001"
        assert page.delivery_gate_values["methods"][0].text() == "已汇总"
        assert page.delivery_gate_next_value.text() == "交付归档"
        assert page.report_command_chip.text().startswith("可交付")
        assert page.report_command_deck.property("commandStatus") == "success"
        assert page.report_command_summary_card.property("commandStatus") == "success"
        assert page.report_command_next_label.text() == page.delivery_gate_next_value.text()
        assert "->" in page.report_command_next_note.text()
        assert "report=" not in page.report_command_next_note.text()
        assert page.report_command_values["report"].text() == "3 个"
        assert page.report_command_values["gate"].text() == "可交付"
        assert page.report_command_values["network"].text() == "FLUXNET"
        assert page.report_command_values["benchmark"].text() == "ref-001"
        assert page.report_command_values["methods"].text() == "已汇总"
        assert page.report_command_values["export"].text() == "已导出"
        assert page.delivery_status_radar_values["network"].text() == "FLUXNET"
        assert page.delivery_status_radar_values["benchmark"].text() == "ref-001"
        assert page.delivery_status_radar_values["methods"].text() == "已汇总"
        assert page.delivery_status_radar_values["export"].text() == "已导出"
        assert page.delivery_status_radar_cards["network"].property("radarTone") == "success"
        assert page.delivery_status_radar_cards["benchmark"].property("radarTone") == "success"
        assert page.delivery_status_radar_cards["methods"].property("radarTone") == "success"
        assert page.delivery_status_radar_cards["export"].property("radarTone") == "success"
        assert all(
            page.delivery_mission_buttons[key].property("missionTone") == "success"
            for key in ("report", "export", "manifest", "network", "benchmark", "methods")
        )
        assert all(
            page.delivery_mission_buttons[key].property("missionStatus") == "OK"
            for key in ("report", "export", "manifest", "network", "benchmark", "methods")
        )
        assert page.preview_context_cards["manifest"].property("contextTone") == "success"
        assert page.preview_context_cards["network"].property("contextTone") == "success"
        assert page.preview_context_cards["methods"].property("contextTone") == "success"
        assert page.preview_evidence_summary_card.property("evidenceTone") == "success"
        assert page.preview_evidence_progress_chip.text() == "3/3"
        assert page.preview_evidence_progress_chip.property("chipTone") == "success"
        assert page.preview_evidence_value.text() == "证据链已闭合"
        assert all(chip.property("chipTone") == "success" for chip in page.preview_evidence_status_chips.values())
        assert page.preview_context_chips["manifest"].property("chipTone") == "success"
        assert page.preview_context_values["network"].text() == "FLUXNET"
        assert page.preview_workbench_buttons["data"].property("workbenchStatus") == "2x3"
        assert page.preview_workbench_buttons["evidence"].property("workbenchStatus") == "3/3"
        assert page.preview_workbench_buttons["evidence"].property("workbenchTone") == "success"
        assert page.preview_workbench_buttons["insight"].property("workbenchStatus") == "2条"
        assert page.report_command_tiles["network"].property("commandTone") == "success"
        assert page.preview_command_values["report"].text() == "可预览"
        assert page.preview_command_values["gate"].text() == page.delivery_gate_chip.text()
        assert page.preview_command_values["export"].text() == "已导出"
        assert page.preview_command_buttons["generate"].property("targetAction") == "generate_report"
        assert page.preview_command_buttons["export"].property("targetAction") == "export_report"
        assert page.preview_command_buttons["export"].property("actionTone") == "success"
        assert page.preview_command_buttons["evidence"].property("targetAction") == "evidence"
        assert page.preview_command_buttons["evidence"].property("actionTone") == "success"
        assert page.delivery_rail_status_chip.text().startswith("可交付")
        assert page.delivery_rail_action_button.property("targetAction") == "details"
        assert page.delivery_rail_risk_button.property("targetAction") == "details"
        assert page.delivery_rail_risk_button.property("actionTone") == "success"
        assert page.delivery_rail_export_button.property("targetAction") == "export_report"
        assert page.delivery_rail_export_button.property("actionTone") == "success"
        assert page.delivery_rail_export_button.text() == "已导出"
        assert page.delivery_rail_evidence_button.property("targetAction") == "evidence"
        assert page.delivery_rail_evidence_button.property("actionTone") == "success"
        assert "report=" not in page.delivery_rail_source_note.text()
        assert "报告已就绪" in page.delivery_rail_source_note.text()
        assert "交付包已导出" in page.delivery_rail_source_note.text()
        assert all(
            button.property("bridgeTone") == "success"
            for button in page.delivery_bridge_buttons.values()
        )
        assert all(
            button.property("bridgeStatus") == "OK"
            for button in page.delivery_bridge_buttons.values()
        )
        assert page.delivery_bridge_buttons["validation"].property("bridgeValue") == "通过"
        page.delivery_bridge_buttons["package"].click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.export_card
        assert page.delivery_detail_status_header.property("detailSection") == "export"
        assert page.delivery_detail_status_header.property("detailTone") == "success"
        assert page.delivery_detail_status_title.text() == "导出链路"
        assert page.delivery_detail_status_chip.text() == "已导出"
        page.delivery_rail_risk_button.click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.usage_card
        assert page.delivery_detail_status_header.property("detailSection") == "usage"
        assert page.delivery_detail_status_title.text() == "使用建议"
        assert page.report_tree_active_chip.text().startswith("运行")
        assert page.preview_content_card.property("plotStatus") == "series"
        assert page.preview_content_card.property("activePane") == "plot"
        assert page.preview_deck_card.property("activePane") == "plot"
        assert page.preview_analysis_strip.property("analysisMode") == "plot"
        assert page.preview_analysis_chip.property("chipTone") == "accent"
        assert page.preview_plot.isHidden() is False
        assert page.preview_content_switches["plot"].isChecked() is True
        assert page.preview_table.maximumHeight() == 106
        page._show_preview_content_mode("table")
        assert page.preview_table.isHidden() is False
        page._show_preview_content_mode("insight")
        assert page.preview_insight_card.isHidden() is False
        page._show_delivery_focus("details")
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_detail_values["export.status"].text() == "已导出"
        assert page.inspector_detail_values["file.manifest"].text() == "ready"
        assert page.inspector_detail_values["file.network"].text() == "ready"
        assert page.inspector_detail_values["usage.next"].text() == "交付归档"
        page._show_delivery_focus("gate")
        assert page.closure_deck_chip.text() == "就绪"
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert "batch-001" in page.preview_delivery_trail_note.text()
        assert "report=" not in page.preview_delivery_trail_note.text()
        assert "source=" not in page.preview_delivery_trail_note.text()
        assert "来源：" in page.preview_delivery_trail_note.text()
        assert page.preview_table.rowCount() == 2
        assert page.empty_state_card.isHidden() is True
        assert page.empty_state_route_tiles["运行处理"].property("routeTone") == "accent"
        assert page.empty_state_route_tiles["生成报告"].property("routeTone") == "success"
        assert page.empty_state_route_tiles["导出"].property("routeTone") == "success"
        assert page.empty_state_route_tiles["打开验证包"].property("routeTone") == "success"
        assert page.empty_state_route_status_chips["生成报告"].text() == "可生成"
        assert page.empty_state_route_status_chips["导出"].text() == "可导出"
    finally:
        page.deleteLater()
        controller.shutdown()
