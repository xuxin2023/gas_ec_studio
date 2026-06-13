from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import CardFrame, TOKENS, apply_app_theme, build_stylesheet, configure_plot_theme, preferred_ui_font_family


def test_stylesheet_contains_instrument_cockpit_contract() -> None:
    stylesheet = build_stylesheet()

    assert "QWidget#appShell" in stylesheet
    assert "qlineargradient" in stylesheet
    assert 'QFrame#card[cardRole="hero"]' in stylesheet
    assert 'QFrame#card[cardRole="hero"] QLabel#pageTitle' in stylesheet
    assert 'QFrame#card[cardRole="hero"] QLabel#subtitle[heroStatus="true"]' in stylesheet
    assert 'QFrame#card[cardRole="command"]' in stylesheet
    assert 'QFrame#card[cardRole="cockpit"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="console"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][commandTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][evidenceTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][routeAction="true"]' in stylesheet
    assert 'QLabel[shellTile="true"]' in stylesheet
    assert 'QWidget[shellClosureStrip="true"]' in stylesheet
    assert 'QLabel[closureStage="true"]' in stylesheet
    assert 'QLabel[closureStage="true"][closureTone="accent"]' in stylesheet
    assert 'QPushButton[navButton="true"]' in stylesheet
    assert 'QToolButton[viewSwitch="true"]' in stylesheet
    assert 'QToolButton[previewPaneSwitch="true"]' in stylesheet
    assert 'QToolButton[previewPaneSwitch="true"]:checked' in stylesheet
    assert 'QToolButton[methodShortcut="true"]' in stylesheet
    assert 'QToolButton[methodShortcut="true"]:checked' in stylesheet
    assert 'QToolButton[methodTaskSwitch="true"]' in stylesheet
    assert 'QToolButton[methodTaskSwitch="true"]:checked' in stylesheet
    assert 'QToolButton[windowConsoleSwitch="true"]' in stylesheet
    assert 'QToolButton[windowConsoleSwitch="true"]:checked' in stylesheet
    assert 'QToolButton[closureModeSwitch="true"]' in stylesheet
    assert 'QToolButton[closureModeSwitch="true"]:checked' in stylesheet
    assert 'QComboBox[runRibbonField="true"]' in stylesheet
    assert 'QPushButton[runRibbonAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[closureCompactTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"] QToolButton[viewSwitch="true"]:checked' in stylesheet
    assert 'QFrame#card[cardRole="command"] QToolButton[viewSwitch="true"]:checked' in stylesheet
    assert 'QLabel[methodFieldLabel="true"]' in stylesheet
    assert 'QLabel[methodGroupPill="true"]' in stylesheet
    assert 'QComboBox[methodFieldInput="true"]' in stylesheet
    assert 'QDoubleSpinBox[methodFieldInput="true"]' in stylesheet
    assert 'QToolButton[railAction="true"]' in stylesheet
    assert 'QToolButton[railAction="true"][actionTone="danger"]' in stylesheet
    assert 'QPushButton[variant="danger"]' in stylesheet and "#fff1f1" in stylesheet
    assert "QTreeWidget#workflowTree" in stylesheet
    assert "QPlainTextEdit" in stylesheet
    assert "EddyPro" not in stylesheet
    assert "eddypro" not in stylesheet


def test_apply_app_theme_registers_desktop_font_family() -> None:
    app = QApplication.instance() or QApplication([])

    apply_app_theme(app)

    family = preferred_ui_font_family()
    assert family
    assert app.font().family() == family
    if QFontDatabase.families():
        assert family in QFontDatabase.families()


def test_card_frame_exposes_role_for_stylesheet() -> None:
    card = CardFrame(role="hero")

    assert card.objectName() == "card"
    assert card.property("cardRole") == "hero"
    assert card.graphicsEffect() is not None


def test_configure_plot_theme_applies_plot_contract() -> None:
    class FakeAxis:
        def __init__(self) -> None:
            self.text_pen = None
            self.pen = None
            self.style = {}

        def setTextPen(self, value: str) -> None:  # noqa: N802
            self.text_pen = value

        def setPen(self, value: str) -> None:  # noqa: N802
            self.pen = value

        def setStyle(self, **kwargs) -> None:  # noqa: N802
            self.style.update(kwargs)

    class FakeViewBox:
        def __init__(self) -> None:
            self.default_padding = None
            self.mouse_enabled = None

        def setDefaultPadding(self, value: float) -> None:  # noqa: N802
            self.default_padding = value

        def setMouseEnabled(self, *, x: bool, y: bool) -> None:  # noqa: N802
            self.mouse_enabled = (x, y)

    class FakePlot:
        def __init__(self) -> None:
            self.background = None
            self.grid = None
            self.labels = {}
            self.hidden_axes = []
            self.menu_enabled = None
            self.axes = {"left": FakeAxis(), "bottom": FakeAxis()}
            self.view_box = FakeViewBox()

        def setBackground(self, value: str) -> None:  # noqa: N802
            self.background = value

        def showGrid(self, *, x: bool, y: bool, alpha: float) -> None:  # noqa: N802
            self.grid = (x, y, alpha)

        def setLabel(self, axis: str, label: str) -> None:  # noqa: N802
            self.labels[axis] = label

        def hideAxis(self, axis: str) -> None:  # noqa: N802
            self.hidden_axes.append(axis)

        def getAxis(self, axis: str) -> FakeAxis:  # noqa: N802
            return self.axes[axis]

        def setMenuEnabled(self, enabled: bool) -> None:  # noqa: N802
            self.menu_enabled = enabled

        def getViewBox(self) -> FakeViewBox:  # noqa: N802
            return self.view_box

    plot = FakePlot()

    configure_plot_theme(plot, left_label="CO2", bottom_label="time", show_bottom=False)

    assert plot.background == "transparent"
    assert plot.grid == (True, True, 0.13)
    assert plot.labels["left"] == "CO2"
    assert "bottom" not in plot.labels
    assert plot.hidden_axes == ["bottom"]
    assert plot.axes["left"].text_pen == TOKENS.color_text_muted
    assert plot.axes["bottom"].pen == TOKENS.color_border
    assert plot.menu_enabled is False
    assert plot.view_box.default_padding == 0.04
    assert plot.view_box.mouse_enabled == (True, True)


def test_main_window_wires_theme_semantics() -> None:
    app = QApplication.instance() or QApplication([])
    apply_app_theme(app)
    controller = StudioController()
    window = StudioMainWindow(controller)

    assert window.centralWidget().objectName() == "appShell"
    assert window.header.property("cardRole") == "hero"
    assert window.header_status.property("heroStatus") is True
    assert window.navigation.property("cardRole") == "rail"
    assert window.navigation.principle_footer.property("navPrincipleCard") is True
    assert window.navigation.principle_footer.maximumHeight() == 150
    assert window.inspector.property("cardRole") == "rail"
    assert window.log_panel.property("cardRole") == "console"
    assert window.log_panel._expanded is False
    assert window.log_panel.editor.isHidden() is True
    assert window.log_panel.latest_line.isHidden() is False
    assert window.log_panel.maximumHeight() == 54
    assert window.log_panel.toggle_button.text() == "展开"
    assert window.log_panel.log_count_chip.text().endswith("条")
    window.log_panel.set_lines(["first", "second"])
    assert window.log_panel.log_count_chip.text() == "2 条"
    assert window.log_panel.latest_line.text() == "first"
    assert window.log_panel.latest_line.toolTip() == "first"
    window.log_panel.clear()
    assert window.log_panel.log_count_chip.text() == "0 条"
    assert window.log_panel.latest_line.text() == "暂无日志。"
    assert window.header_online_tile.property("shellTile") is True
    assert window.header_alarm_tile.property("shellTone") in {"success", "danger"}
    assert window.header_closure_strip.property("shellClosureStrip") is True
    assert set(window.header_closure_tiles) == {"device", "capture", "rp", "spectral", "delivery"}
    assert all(tile.property("closureStage") is True for tile in window.header_closure_tiles.values())
    assert window.header_closure_tiles["rp"].text() == "RP\n待运行"
    assert window.header_closure_tiles["delivery"].text() == "交付\n待交付"
    assert window.operator_btn.property("viewSwitch") is True
    assert window.engineer_btn.property("viewSwitch") is True
    assert all(button.property("navButton") is True for button in window.navigation._buttons.values())

    controller.ec_processing_workspace["summary"]["status"] = "ok"
    controller.spectral_qc_workspace["run"]["last_result_status"] = "ok"
    controller.report_center_workspace["export_status"] = "exported"
    window._refresh_shell()
    assert window.header_closure_tiles["rp"].text() == "RP\n已闭合"
    assert window.header_closure_tiles["spectral"].text() == "谱修正\n已分析"
    assert window.header_closure_tiles["delivery"].text() == "交付\n已交付"

    window.log_panel.set_expanded(True)
    assert window.log_panel._expanded is True
    assert window.log_panel.editor.isHidden() is False
    assert window.log_panel.latest_line.isHidden() is True
    assert window.log_panel.maximumHeight() == 260

    window.close()
    controller.shutdown()
