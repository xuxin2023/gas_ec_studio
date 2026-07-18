from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from app.about_dialog import AboutDialog
from app.resources import application_icon, release_notes_text, resource_path, user_guide_text
from app.theme import apply_app_theme
from app.version import DISPLAY_VERSION
from core.exports.public_text import find_public_text_violations


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    apply_app_theme(app)
    return app


def test_application_identity_assets_are_available() -> None:
    icon_path = resource_path("app/assets/gas_ec_studio_icon.png")
    changelog_path = resource_path("CHANGELOG.md")

    assert icon_path.is_file()
    assert changelog_path.is_file()
    assert application_icon().isNull() is False
    assert DISPLAY_VERSION in release_notes_text()
    assert "标准流程" in user_guide_text()


def test_about_dialog_exposes_version_guide_and_release_notes() -> None:
    app = _app()
    dialog = AboutDialog()
    try:
        dialog.show()
        app.processEvents()

        assert dialog.tabs.count() == 3
        assert [dialog.tabs.tabText(index) for index in range(3)] == ["关于", "使用说明", "更新日志"]
        assert DISPLAY_VERSION in dialog.about_browser.toPlainText()
        assert "设备中心" in dialog.guide_browser.toPlainText()
        assert DISPLAY_VERSION in dialog.release_notes_browser.toPlainText()
        visible_text = [
            dialog.about_browser.toPlainText(),
            dialog.guide_browser.toPlainText(),
            dialog.release_notes_browser.toPlainText(),
        ]
        assert find_public_text_violations(visible_text) == []
    finally:
        dialog.close()
