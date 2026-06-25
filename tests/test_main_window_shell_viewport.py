from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import apply_app_theme
from tests.ui_geometry_helpers import assert_contained, assert_no_visual_overlap


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_main_window_shell_fits_common_desktop_viewports(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window.show()
        app.processEvents()

        for width, height, compact in ((1366, 768, True), (1440, 900, True), (1600, 900, False)):
            window.resize(width, height)
            app.processEvents()

            assert window.width() <= width
            assert window.height() <= height
            assert window._compact_shell is compact
            assert window.inspector.isVisible() is not compact
            assert window.header_status.isVisible() is not compact
            assert window.log_panel.maximumHeight() == 44
            assert window.log_panel.latest_line.isVisible() is True

            root = window.centralWidget()
            visible_shell_widgets = [window.header, window.navigation, window.stack, window.log_panel]
            if window.inspector.isVisible():
                visible_shell_widgets.append(window.inspector)
            for widget in visible_shell_widgets:
                assert_contained(root, widget, root)
            assert_no_visual_overlap(visible_shell_widgets, root)

            nav_widgets = [window.navigation.nav_mission_chip, *window.navigation._buttons.values(), window.navigation.principle_footer]
            for widget in nav_widgets:
                assert_contained(window.navigation, widget, root)
            assert_no_visual_overlap(nav_widgets, root)

            visible_header_widgets = [
                window.route_cockpit,
                window.header_closure_strip,
                window.header_telemetry_strip,
                window.operator_btn,
                window.engineer_btn,
            ]
            if window.header_status.isVisible():
                visible_header_widgets.insert(0, window.header_status)
            for widget in visible_header_widgets:
                assert_contained(window.header, widget, root)
            assert_no_visual_overlap(visible_header_widgets, root)
    finally:
        window.close()
        controller.shutdown()


def test_main_window_switches_every_page_without_expanding_viewport(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window.show()
        window.resize(1440, 900)
        app.processEvents()

        for page_key, page in window.pages.items():
            window._set_page(page_key)
            app.processEvents()

            assert window.stack.currentWidget() is page
            assert window.width() <= 1440
            assert window.height() <= 900
            assert window._compact_shell is True
            assert window.inspector.isVisible() is False
    finally:
        window.close()
        controller.shutdown()


def test_main_window_hides_outer_inspector_for_embedded_workbench_pages(monkeypatch, tmp_path) -> None:
    app = _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        window = StudioMainWindow(controller)
        window.show()
        window.resize(1600, 900)
        app.processEvents()

        window._set_page("device_center")
        app.processEvents()
        assert window._compact_shell is False
        assert window.inspector.isVisible() is True

        for page_key in ("device_detail", "project_site", "ec_processing", "report_center"):
            window._set_page(page_key)
            app.processEvents()
            assert window.width() <= 1600
            assert window.height() <= 900
            assert window._compact_shell is False
            assert window.inspector.isVisible() is False
            assert window.stack.width() >= 1180
    finally:
        window.close()
        controller.shutdown()
