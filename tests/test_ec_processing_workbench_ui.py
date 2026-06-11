from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.pages.ec_processing_page import ECProcessingPage
from app.studio import StudioController
from app.theme import apply_app_theme


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_ec_processing_output_coverage_uses_compact_gate(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    page = ECProcessingPage(controller)
    try:
        page.refresh()

        assert page.output_coverage_card.property("cardRole") == "panel"
        assert page.rail_focus_card.property("cardRole") == "panel"
        assert page.desktop_rail_inspector.property("deckRole") == "ecRailInspector"
        assert page.desktop_rail_stack.count() == 3
        assert page.desktop_rail_stack.currentWidget() is page.workflow_lens_card
        assert page.desktop_rail_mode_buttons["workflow"].isChecked() is True
        assert page.rail_focus_stack.count() == 2
        assert page.rail_focus_stack.currentWidget() is page.readiness_card
        assert page.rail_focus_buttons["readiness"].isChecked() is True
        page._show_rail_focus("coverage")
        assert page.rail_focus_stack.currentWidget() is page.output_coverage_card
        assert page.rail_focus_buttons["coverage"].isChecked() is True
        assert page.desktop_rail_stack.currentWidget() is page.rail_focus_card
        page._show_desktop_rail_mode("cockpit")
        assert page.desktop_rail_stack.currentWidget() is page.cockpit_card
        assert set(page.coverage_values) == {
            "metadata",
            "processing",
            "statistics",
            "spectral",
            "methods",
            "network",
        }
        assert page.coverage_gate_chip.text() == "可运行"
        assert page.coverage_next_value.text() == "运行处理"
        assert "schema=FLUXNET" in page.coverage_values["network"].text()

        page.spectral_enable_combo.setCurrentText("disabled")
        page._refresh_output_coverage_panel()

        assert page.coverage_gate_chip.text() == "待补齐"
        assert page.coverage_next_value.text() == "补齐配置"
        assert "当前闭合 5/6" in page.coverage_next_note.text()
    finally:
        page.deleteLater()
        controller.shutdown()
