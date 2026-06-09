from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.pages.device_detail_page import DeviceDetailPage
from app.studio import StudioController
from app.theme import apply_app_theme


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    apply_app_theme(app)
    return app


def test_device_detail_uses_device_operations_rail(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Field YGAS",
            port="SIM1",
            baudrate=115200,
            device_id="001",
            analyzer_profile="ygas_irga",
        )
        controller.select_device(uid)
        controller.connect_device(uid)
        controller.read_frame_once(uid)
        page = DeviceDetailPage(controller)
        try:
            page.refresh()

            assert page.header_card.property("cardRole") == "command"
            assert page.summary_card.property("cardRole") == "cockpit"
            assert page.device_ops_rail.property("cardRole") == "rail"
            assert set(page.device_ops_values) == {"link", "telemetry", "primary", "trace", "diagnostics"}
            assert page.device_ops_values["link"][0].text() == "在线"
            assert page.device_ops_values["telemetry"][0].text().endswith("Hz")
            assert page.device_ops_values["primary"][0].text() == "ygas_irga"
            assert page.device_ops_next_value.text() in {"读取一帧", "启用主分析仪", "进入实时采集", "复核配置"}

            controller.disconnect_device(uid)
            page.refresh()

            assert page.device_ops_values["link"][0].text() == "离线"
            assert page.device_ops_next_value.text() == "连接设备"
        finally:
            page.deleteLater()
    finally:
        controller.shutdown()
