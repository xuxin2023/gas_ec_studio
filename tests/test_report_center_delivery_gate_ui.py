from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from app.pages.report_center_page import ReportCenterPage
from app.studio import StudioController
from app.theme import apply_app_theme


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

        assert page.delivery_rail.property("cardRole") == "rail"
        assert page.delivery_focus_card.property("cardRole") == "panel"
        assert page.delivery_focus_stack.count() == 3
        assert page.delivery_focus_buttons["gate"].isChecked() is True
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert page.delivery_gate_card.property("cardRole") == "cockpit"
        assert page.delivery_gate_values["report"][0].property("compactMetric") is True
        assert page.delivery_gate_next_value.property("compactMetric") is True
        assert page.preview_header_card.property("cardRole") == "cockpit"
        assert page.preview_deck_card.property("cardRole") == "rail"
        assert page.preview_delivery_trail_card.property("cardRole") == "console"
        assert page.preview_delivery_trail_value.property("compactMetric") is True
        assert page.preview_delivery_trail_chip.property("chipTone") == "accent"
        assert page.preview_content_card.property("cardRole") == "panel"
        assert len(page.preview_metric_cards) == 4
        assert all(card.property("cardRole") == "tile" for card in page.preview_metric_cards)
        assert page.closure_deck_card.property("cardRole") == "rail"
        assert page.closure_deck_chip.text() == "下一步"
        assert page.inner_inspector.property("cardRole") == "panel"
        assert page.inspector_stack.count() == 4
        assert page.inspector_stack.currentWidget() is page.export_card
        assert page.inspector_switches["export"].isChecked() is True
        assert page.empty_state_card.property("cardRole") == "cockpit"
        assert page.empty_state_card.isHidden() is False
        assert page.empty_state_chip.text() == "待运行"
        assert "尚未发现可导出的真实运行结果" in page.empty_state_gap_label.text()
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
        page._show_delivery_focus("details")
        assert page.delivery_focus_stack.currentWidget() is page.inner_inspector
        assert page.delivery_focus_buttons["details"].isChecked() is True
    finally:
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
        assert page.delivery_gate_values["network"][0].text() == "FLUXNET"
        assert "缺失：无" in page.delivery_gate_values["network"][1].text()
        assert page.delivery_gate_values["benchmark"][0].text() == "ref-001"
        assert page.delivery_gate_values["methods"][0].text() == "已汇总"
        assert page.delivery_gate_next_value.text() == "交付归档"
        assert page.closure_deck_chip.text() == "就绪"
        assert page.delivery_focus_stack.currentWidget() is page.delivery_gate_card
        assert "batch-001" in page.preview_delivery_trail_note.text()
        assert "report=run_summary" in page.preview_delivery_trail_note.text()
        assert page.preview_table.rowCount() == 2
        assert page.empty_state_card.isHidden() is True
    finally:
        page.deleteLater()
        controller.shutdown()
