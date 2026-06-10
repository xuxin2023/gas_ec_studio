from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from app.pages.project_site_page import ProjectSitePage
from app.studio import StudioController
from app.theme import apply_app_theme


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_project_site_uses_station_closure_rail(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    page = ProjectSitePage(controller)
    try:
        page.refresh()

        assert page.top_bar.property("cardRole") == "command"
        assert page.tree_card.property("cardRole") == "rail"
        assert page.site_ops_rail.property("cardRole") == "rail"
        assert set(page.site_ops_values) == {
            "readiness",
            "geometry",
            "chain",
            "timing",
            "delivery",
            "metadata",
        }
        assert page.site_ops_values["readiness"][0].text().endswith(" 分")
        assert page.site_ops_next_value.text() in {"补齐项目身份", "复核采样链路", "确认导出模板", "保存并运行"}
        assert "???" not in "\n".join(label.text() for label in page.findChildren(QLabel))

        page.tube_length_spin.setValue(9.5)
        page.tube_diameter_spin.setValue(4.0)
        page.flow_spin.setValue(5.2)
        page._refresh_top_bar()

        assert page.site_ops_values["chain"][0].text() == "5.2 L/min"
        assert "9.5 m / 4.0 mm" in page.site_ops_values["chain"][1].text()
    finally:
        page.deleteLater()
        controller.shutdown()
