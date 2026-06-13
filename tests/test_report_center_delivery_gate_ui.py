from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.pages.report_center_page import REPORT_SECTIONS, ReportCenterPage
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
        assert page.report_tree.indentation() == 0
        assert page.report_tree.rootIsDecorated() is False
        assert page.report_tree.uniformRowHeights() is True
        assert page.report_tree.topLevelItemCount() == len(REPORT_SECTIONS)
        assert page.report_tree_count_chip.text() == f"{len(REPORT_SECTIONS)} 项"
        assert page.report_tree_active_chip.text().startswith("运行")
        assert page.delivery_rail.property("cardRole") == "rail"
        assert page.delivery_rail_status_chip.property("closureStage") is True
        assert page.delivery_rail_status_chip.text().startswith("待生成")
        assert page.delivery_rail_action_bar.property("deckRole") == "deliveryRailActionBar"
        assert page.delivery_rail_action_bar.maximumHeight() == 38
        assert page.delivery_rail_action_button.property("railAction") is True
        assert page.delivery_rail_risk_button.property("railAction") is True
        assert page.delivery_rail_export_button.property("railAction") is True
        assert page.delivery_rail_evidence_button.property("railAction") is True
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
        assert page.report_command_deck.maximumHeight() == 146
        assert page.report_command_chip.text().startswith("待生成")
        assert set(page.report_command_tiles) == {"report", "gate", "network", "benchmark", "methods", "export"}
        assert all(tile.property("cardRole") == "tile" for tile in page.report_command_tiles.values())
        assert all(value.property("compactMetric") is True for value in page.report_command_values.values())
        assert all(chip.property("closureStage") is True for chip in page.report_command_chips.values())
        assert all(chip.minimumHeight() == 22 for chip in page.report_command_chips.values())
        assert page.report_command_values["report"].text() == "待生成"
        assert page.report_command_values["export"].text() == "待运行"
        assert page.delivery_rail_inspector.property("deckRole") == "deliveryRailInspector"
        assert page.delivery_rail_stack.property("stackRole") == "deliveryRailInspectorStack"
        assert page.delivery_rail_stack.count() == 2
        assert page.delivery_rail_stack.currentWidget() is page.delivery_focus_card
        assert page.delivery_rail_mode_buttons["delivery"].isChecked() is True
        page._show_delivery_rail_mode("summary")
        assert page.delivery_rail_stack.currentWidget() is page.summary_row
        assert page.delivery_rail_mode_buttons["summary"].isChecked() is True
        page._show_delivery_rail_mode("delivery")
        assert page.delivery_focus_card.property("cardRole") == "panel"
        assert page.delivery_focus_stack.count() == 3
        assert page.delivery_focus_buttons["gate"].isChecked() is True
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert page.delivery_gate_card.property("cardRole") == "cockpit"
        assert page.delivery_gate_card.property("deckRole") == "deliveryGateMatrix"
        assert page.delivery_gate_hero_card.property("cardRole") == "console"
        assert page.delivery_gate_hero_card.property("deckRole") == "deliveryReadinessHero"
        assert page.delivery_gate_progress_badge.objectName() == "chip"
        assert page.delivery_gate_progress_badge.property("chipTone") in {"warning", "accent", "success"}
        assert page.delivery_focus_stack.property("stackRole") == "compactDeliveryInspector"
        assert page.delivery_gate_hero_card.maximumHeight() == 36
        assert page.delivery_gate_scroll.objectName() == "deliveryGateMatrixScroll"
        assert page.delivery_gate_scroll.maximumHeight() == 74
        assert page.delivery_gate_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert page.delivery_gate_scroll.widget() is page.delivery_gate_grid_body
        assert page.delivery_gate_ready_value.property("compactMetric") is True
        assert page.delivery_gate_ready_note.isHidden() is True
        assert all(tile.maximumHeight() == 32 for tile in page.delivery_gate_tiles.values())
        assert page.delivery_gate_values["report"][0].property("compactMetric") is True
        assert page.delivery_gate_values["report"][1].isHidden() is True
        assert page.delivery_gate_values["report"][2].isHidden() is False
        assert page.delivery_gate_values["report"][2].property("closureStage") is True
        assert page.delivery_gate_values["report"][2].minimumHeight() == 18
        assert page.delivery_gate_next_value.property("compactMetric") is True
        assert page.delivery_gate_next_card.isHidden() is True
        assert page.delivery_gate_next_note.isHidden() is True
        assert page.preview_header_card.property("cardRole") == "cockpit"
        assert page.preview_header_card.property("deckRole") == "reportPreviewHeader"
        assert page.preview_header_card.property("reportPreviewHeaderDock") is True
        assert page.preview_header_card.maximumHeight() == 88
        assert page.preview_command_strip.property("cardRole") == "console"
        assert page.preview_command_strip.property("deckRole") == "reportPreviewCommandStrip"
        assert page.preview_command_strip.property("previewCommandDock") is True
        assert page.preview_command_strip.maximumHeight() == 68
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
        assert page.preview_deck_card.property("activePane") == "table"
        assert page.preview_pane_switcher.property("deckRole") == "previewPaneSwitcher"
        assert all(button.property("previewPaneSwitch") is True for button in page.preview_content_switches.values())
        assert page.preview_pane_hint_label.text()
        assert page.preview_delivery_trail_card.property("cardRole") == "console"
        assert page.preview_delivery_trail_card.maximumHeight() == 88
        assert page.preview_delivery_trail_value.property("compactMetric") is True
        assert page.preview_delivery_trail_chip.property("chipTone") == "accent"
        assert page.preview_content_card.property("cardRole") == "panel"
        assert page.preview_content_card.property("deckRole") == "compactPreviewPane"
        assert page.preview_content_card.property("density") == "desktop"
        assert page.preview_content_card.property("plotStatus") == "tableOnly"
        assert page.preview_content_card.maximumHeight() == 360
        assert page.expert_review_card.property("deckRole") == "expertReviewStrip"
        assert page.expert_review_card.isHidden() is True
        assert page.preview_plot.isHidden() is True
        assert page.preview_plot.maximumHeight() == 0
        assert page.preview_table.maximumHeight() == 180
        assert page.preview_content_card.property("activePane") == "table"
        assert set(page.preview_content_switches) == {"plot", "table", "insight"}
        assert page.preview_content_switches["table"].isChecked() is True
        assert page.preview_insight_card.property("deckRole") == "reportPreviewInsightPane"
        assert page.preview_insight_card.isHidden() is True
        assert page.preview_table.isHidden() is False
        page._show_preview_content_mode("insight")
        assert page.preview_content_card.property("activePane") == "insight"
        assert page.preview_deck_card.property("activePane") == "insight"
        assert page.preview_insight_card.isHidden() is False
        assert page.preview_table.isHidden() is True
        assert len(page.preview_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.preview_metric_cards)
        assert all(card.maximumHeight() == 74 for card in page.preview_metric_cards)
        assert all(value.property("compactMetric") is True for value in page.preview_metric_values)
        assert page.recent_status_value.toolTip()
        assert len(page.recent_status_value.text()) <= 9
        assert page.last_generated_value.toolTip()
        assert page.closure_deck_card.property("cardRole") == "rail"
        assert page.closure_deck_chip.text() == "下一步"
        assert page.inner_inspector.property("cardRole") == "panel"
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
        assert all(tile.maximumHeight() == 66 for tile in route_tiles)
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
        page._show_delivery_focus("batch")
        assert page.delivery_focus_stack.currentWidget() is page.batch_card
        assert page.delivery_focus_buttons["batch"].isChecked() is True
        assert page.delivery_rail_stack.currentWidget() is page.delivery_focus_card
        assert page.delivery_rail_mode_buttons["delivery"].isChecked() is True
        page._show_delivery_focus("details")
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.delivery_focus_buttons["details"].isChecked() is True
        assert page.inner_inspector.property("deckRole") == "deliveryDetailInspector"
        assert page.inspector_stack.property("stackRole") == "deliveryDetailInspectorStack"
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
            assert_contained(page, page.delivery_rail, page)

            page._show_delivery_rail_mode("summary")
            app.processEvents()
            assert_contained(page.delivery_rail, page.delivery_rail_action_bar, page)
            for button in (
                page.delivery_rail_action_button,
                page.delivery_rail_risk_button,
                page.delivery_rail_export_button,
                page.delivery_rail_evidence_button,
            ):
                assert_contained(page.delivery_rail_action_bar, button, page)
            summary_cards = list(page.summary_cards.values())
            assert len(summary_cards) == 4
            for card in summary_cards:
                assert_contained(page.delivery_rail, card, page)
            assert_no_visual_overlap(summary_cards, page)

            page._show_delivery_focus("gate")
            app.processEvents()
            assert_contained(page, page.preview_command_strip, page)
            for tile in page.preview_command_tiles.values():
                assert_contained(page.preview_command_strip, tile, page)
            for button in page.preview_command_buttons.values():
                assert_contained(page.preview_command_strip, button, page)
            for button in page.preview_content_switches.values():
                assert_contained(page.preview_deck_card, button, page)
            gate_widgets = [page.delivery_gate_hero_card, page.delivery_gate_scroll]
            for widget in gate_widgets:
                assert_contained(page.delivery_gate_card, widget, page)
            for widget in (page.delivery_gate_tiles["report"], page.delivery_gate_tiles["export"]):
                assert_contained(page.delivery_gate_scroll.viewport(), widget, page)
            for widget in page.delivery_gate_tiles.values():
                assert_contained(page.delivery_gate_grid_body, widget, page)
            assert_no_visual_overlap([page.delivery_gate_hero_card, page.delivery_gate_scroll], page)
            assert_no_visual_overlap(list(page.delivery_gate_tiles.values()), page)

            assert_no_visible_competitor_name(page)
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
        assert "交付归档" in page.delivery_gate_ready_note.text()
        assert page.delivery_gate_values["network"][0].text() == "FLUXNET"
        assert "缺失：无" in page.delivery_gate_values["network"][1].text()
        assert page.delivery_gate_tiles["network"].property("gateTone") == "success"
        assert page.delivery_gate_values["benchmark"][0].text() == "ref-001"
        assert page.delivery_gate_values["methods"][0].text() == "已汇总"
        assert page.delivery_gate_next_value.text() == "交付归档"
        assert page.report_command_chip.text().startswith("可交付")
        assert page.report_command_deck.property("commandStatus") == "success"
        assert page.report_command_values["report"].text() == "3 个"
        assert page.report_command_values["gate"].text() == "可交付"
        assert page.report_command_values["network"].text() == "FLUXNET"
        assert page.report_command_values["benchmark"].text() == "ref-001"
        assert page.report_command_values["methods"].text() == "已汇总"
        assert page.report_command_values["export"].text() == "已导出"
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
        page.delivery_rail_risk_button.click()
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.inspector_stack.currentWidget() is page.usage_card
        assert page.report_tree_active_chip.text().startswith("运行")
        assert page.preview_content_card.property("plotStatus") == "series"
        assert page.preview_content_card.property("activePane") == "plot"
        assert page.preview_deck_card.property("activePane") == "plot"
        assert page.preview_plot.isHidden() is False
        assert page.preview_content_switches["plot"].isChecked() is True
        assert page.preview_table.maximumHeight() == 128
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
        assert "report=run_summary" in page.preview_delivery_trail_note.text()
        assert page.preview_table.rowCount() == 2
        assert page.empty_state_card.isHidden() is True
    finally:
        page.deleteLater()
        controller.shutdown()
