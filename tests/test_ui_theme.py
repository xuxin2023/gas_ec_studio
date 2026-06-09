from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import CardFrame, TOKENS, apply_app_theme, build_stylesheet, configure_plot_theme


def test_stylesheet_contains_instrument_cockpit_contract() -> None:
    stylesheet = build_stylesheet()

    assert "QWidget#appShell" in stylesheet
    assert "qlineargradient" in stylesheet
    assert 'QFrame#card[cardRole="hero"]' in stylesheet
    assert 'QFrame#card[cardRole="command"]' in stylesheet
    assert 'QFrame#card[cardRole="cockpit"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"]' in stylesheet
    assert 'QPushButton[navButton="true"]' in stylesheet
    assert 'QToolButton[viewSwitch="true"]' in stylesheet
    assert "QTreeWidget#workflowTree" in stylesheet
    assert "QPlainTextEdit" in stylesheet
    assert "EddyPro" not in stylesheet
    assert "eddypro" not in stylesheet


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
    assert window.operator_btn.property("viewSwitch") is True
    assert window.engineer_btn.property("viewSwitch") is True
    assert all(button.property("navButton") is True for button in window.navigation._buttons.values())

    window.close()
    controller.shutdown()
