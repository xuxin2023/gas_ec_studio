from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from app.pages.project_site_page import ProjectSitePage
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


def test_project_site_viewport_layout_keeps_directory_and_closure_rail_stable(
    monkeypatch, tmp_path: Path
) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    page = ProjectSitePage(controller)
    try:
        page.show()
        for width, height in ((1280, 760), (1440, 920), (1600, 900)):
            page.resize(width, height)
            page.refresh()
            app.processEvents()

            assert page.width() <= width
            assert page.height() <= height
            assert page.tree_card.width() <= page.tree_card.maximumWidth()
            assert page.tree_card.width() >= page.tree_card.minimumWidth()
            assert page.site_ops_rail.width() <= page.site_ops_rail.maximumWidth()
            assert page.site_ops_rail.width() >= page.site_ops_rail.minimumWidth()

            assert_contained(page, page.top_bar, page)
            assert_contained(page, page.tree_card, page)
            assert_contained(page, page.content_stack, page)
            assert_contained(page, page.site_ops_rail, page)
            assert_no_visual_overlap([page.tree_card, page.content_stack, page.site_ops_rail], page)

            for tile in page.site_ops_tiles:
                assert_contained(page.site_ops_rail, tile, page)
            assert_no_visual_overlap(page.site_ops_tiles, page)
            assert_no_visible_competitor_name(page)
    finally:
        page.close()
        page.deleteLater()
        controller.shutdown()
