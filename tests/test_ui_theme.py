from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import CardFrame, apply_app_theme, build_stylesheet


def test_stylesheet_contains_instrument_cockpit_contract() -> None:
    stylesheet = build_stylesheet()

    assert "QWidget#appShell" in stylesheet
    assert "qlineargradient" in stylesheet
    assert 'QFrame#card[cardRole="hero"]' in stylesheet
    assert 'QPushButton[navButton="true"]' in stylesheet
    assert 'QToolButton[viewSwitch="true"]' in stylesheet
    assert "QPlainTextEdit" in stylesheet
    assert "EddyPro" not in stylesheet
    assert "eddypro" not in stylesheet


def test_card_frame_exposes_role_for_stylesheet() -> None:
    card = CardFrame(role="hero")

    assert card.objectName() == "card"
    assert card.property("cardRole") == "hero"
    assert card.graphicsEffect() is not None


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
