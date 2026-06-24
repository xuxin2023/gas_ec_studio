from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSizePolicy

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

        assert page.run_bar.property("runCommandDock") is True
        assert page.run_bar.maximumHeight() == 74
        assert page.data_source_combo.maximumHeight() == 28
        assert page.time_range_combo.maximumHeight() == 28
        assert page.run_mission_strip.property("runMissionStrip") is True
        assert page.run_mission_strip.maximumHeight() == 28
        assert set(page.run_mission_values) == {"step", "status", "gate"}
        assert all(value.property("runMissionValue") is True for value in page.run_mission_values.values())
        assert page.run_summary_label.property("runMissionText") is True
        assert page.output_coverage_card.property("cardRole") == "panel"
        assert page.rail_focus_card.property("cardRole") == "panel"
        assert page.desktop_rail_inspector.property("deckRole") == "ecRailInspector"
        assert page.desktop_rail_inspector.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
        assert page.desktop_rail_status_strip.property("deckRole") == "ecRailStatusStrip"
        assert page.desktop_rail_status_strip.property("railMissionDeck") is True
        assert page.desktop_rail_status_strip.maximumHeight() == 108
        assert page.method_shortcut_card.property("deckRole") == "ecMethodShortcutDeck"
        assert page.method_shortcut_card.maximumHeight() == 96
        assert set(page.method_shortcut_buttons) == {"footprint", "uncertainty", "spectral"}
        assert all(button.property("methodShortcut") is True for button in page.method_shortcut_buttons.values())
        assert page.method_shortcut_note.text()
        assert page.desktop_rail_stack.maximumHeight() == 210
        assert set(page.desktop_rail_status_values) == {"step", "run", "closure"}
        assert page.desktop_rail_status_values["step"].text()
        assert page.desktop_rail_status_values["run"].text() == "empty"
        assert page.desktop_rail_status_values["closure"].text() == page.coverage_gate_chip.text()
        assert page.desktop_rail_action_button.property("railAction") is True
        assert page.desktop_rail_risk_button.property("railAction") is True
        assert page.desktop_rail_run_button.property("railAction") is True
        assert page.desktop_rail_coverage_button.property("railAction") is True
        assert page.desktop_rail_action_button.property("railMissionAction") is True
        assert page.desktop_rail_risk_button.property("railMissionAction") is True
        assert page.desktop_rail_run_button.property("railMissionAction") is True
        assert page.desktop_rail_coverage_button.property("railMissionAction") is True
        assert all(tile.property("railMissionTile") is True for tile in page.desktop_rail_status_tiles.values())
        assert page.desktop_rail_action_button.text()
        assert page.desktop_rail_risk_button.text()
        assert page.desktop_rail_action_button.text() == "下步"
        assert page.desktop_rail_risk_button.text() == "就绪"
        assert page.desktop_rail_run_button.text() == "运行"
        assert page.desktop_rail_coverage_button.text() == "覆盖"
        assert page.desktop_rail_run_button.property("targetStep") == "run_processing"
        assert page.desktop_rail_coverage_button.property("targetStep") == "coverage"
        assert page.desktop_rail_coverage_button.toolTip()
        assert set(page.step_command_strips) == set(page.step_indexes)
        active_strip = page.step_command_strips["window_sampling"]
        assert active_strip.property("deckRole") == "ecStepCommandStrip"
        assert active_strip.property("stepCommandDock") is True
        assert active_strip.maximumHeight() == 68
        assert page.step_command_values["window_sampling"]["step"].text()
        assert page.step_command_values["window_sampling"]["run"].text() == "empty"
        assert page.step_command_values["window_sampling"]["closure"].text() == page.coverage_gate_chip.text()
        assert all(
            tile.property("stepCommandTile") is True
            for tile in page.step_command_tiles["window_sampling"].values()
        )
        assert all(
            button.property("stepCommandAction") is True
            for button in page.step_command_buttons["window_sampling"].values()
        )
        assert page.step_command_buttons["window_sampling"]["run"].property("targetStep") == "run_processing"
        assert page.step_command_buttons["window_sampling"]["coverage"].property("targetStep") == "coverage"
        assert page.window_cockpit_card.property("activePane") == "params"
        assert set(page.window_console_switches) == {"params", "preview", "timeline"}
        assert all(button.property("windowConsoleSwitch") is True for button in page.window_console_switches.values())
        assert page.window_console_switches["params"].isChecked() is True
        assert page.window_param_card.isHidden() is False
        assert page.window_preview_card.isHidden() is True
        assert page.window_timeline_card.isHidden() is True
        page._show_window_console_pane("preview")
        assert page.window_cockpit_card.property("activePane") == "preview"
        assert page.window_param_card.isHidden() is True
        assert page.window_preview_card.isHidden() is False
        assert page.window_timeline_card.isHidden() is True
        page._show_window_console_pane("timeline")
        assert page.window_cockpit_card.property("activePane") == "timeline"
        assert page.window_timeline_card.isHidden() is False
        assert page.desktop_rail_stack.count() == 3
        assert page.method_family_card.property("methodConsoleCompact") is True
        assert page.method_family_tile_strip.property("methodStateMirror") is True
        assert page.method_family_tile_strip.maximumHeight() == 46
        assert page.method_family_tile_strip.isHidden() is False
        assert set(page.method_console_tiles) == {"footprint", "uncertainty", "spectral"}
        assert all(tile.property("methodConsoleTile") is True for tile in page.method_console_tiles.values())
        assert all(tile.property("methodTone") in {"success", "accent", "warning", "danger"} for tile in page.method_console_tiles.values())
        assert page.desktop_rail_stack.currentWidget() is page.workflow_lens_card
        assert page.desktop_rail_mode_buttons["workflow"].isChecked() is True
        assert page.rail_focus_stack.count() == 2
        assert page.rail_focus_stack.currentWidget() is page.readiness_card
        assert page.rail_focus_buttons["readiness"].isChecked() is True
        page._show_rail_focus("coverage")
        assert page.rail_focus_stack.currentWidget() is page.output_coverage_card
        assert page.rail_focus_buttons["coverage"].isChecked() is True
        assert page.desktop_rail_stack.currentWidget() is page.rail_focus_card
        assert page.desktop_rail_stack.maximumHeight() == 470
        page.desktop_rail_coverage_button.click()
        assert page.rail_focus_stack.currentWidget() is page.output_coverage_card
        page.step_command_buttons["window_sampling"]["coverage"].click()
        assert page.rail_focus_stack.currentWidget() is page.output_coverage_card
        page._show_desktop_rail_mode("cockpit")
        assert page.desktop_rail_stack.currentWidget() is page.cockpit_card
        assert page.desktop_rail_stack.maximumHeight() == 420
        page.method_shortcut_buttons["spectral"].click()
        assert controller.ec_nav_step == "uncertainty"
        assert page.content_stack.currentIndex() == page.step_indexes["uncertainty"]
        assert page.method_family_stack.currentWidget() is page.spectral_card
        assert page.method_shortcut_buttons["spectral"].isChecked() is True
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
        page._refresh_uncertainty_preview()
        page._refresh_output_coverage_panel()

        assert page.coverage_gate_chip.text() == "待补齐"
        assert page.coverage_next_value.text() == "补齐配置"
        assert "当前闭合 5/6" in page.coverage_next_note.text()
        assert page.method_console_values["spectral"].text() == "disabled"
        assert page.method_console_tiles["spectral"].property("methodTone") == "accent"
    finally:
        page.deleteLater()
        controller.shutdown()
