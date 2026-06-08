from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.pages.device_detail_page import DeviceDetailPage
from app.studio import StudioController


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def test_device_detail_page_applies_primary_analyzer_config_to_ec_processing(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Tower LI-7200",
            port="SIM2",
            baudrate=9600,
            device_id="LI7200",
            analyzer_profile="licor_li7200_family",
        )
        controller.select_device(uid)
        page = DeviceDetailPage(controller)
        page.refresh()

        page.primary_analyzer_profile_combo.setCurrentIndex(
            page.primary_analyzer_profile_combo.findData("licor_li7200_family")
        )
        page.primary_analyzer_enable_combo.setCurrentText("enabled")
        page.primary_signal_warning_spin.setValue(31.0)
        page.primary_signal_fail_spin.setValue(7.0)
        page.primary_require_status_combo.setCurrentText("required")
        page.primary_cell_thermo_combo.setCurrentText("required")
        page.primary_allowed_diag_words_edit.setText("0,4")
        page.primary_calibration_profile_edit.setText("li7200_device_zero_span_2026")
        page.primary_source_file_edit.setText("D:/fixtures/li7200_device_zero_span_2026.json")
        page.primary_normalization_command_edit.setText(
            "gas_ec_studio normalize-licor --profile li7200_device_zero_span_2026"
        )

        payload = page._collect_primary_analyzer_payload()
        assert payload["profile_id"] == "licor_li7200_family"
        assert payload["min_signal_warning_pct"] == 31.0
        assert payload["min_signal_fail_pct"] == 7.0
        assert payload["require_cell_thermodynamics"] is True
        assert payload["allowed_diagnostic_words"] == [0, 4]

        snapshot = controller.apply_device_primary_analyzer_config(uid, payload)
        page._populate_primary_analyzer_config(dict(snapshot))

        assert snapshot["profile_id"] == "licor_li7200_family"
        assert snapshot["calibration_profile_id"] == "li7200_device_zero_span_2026"
        assert snapshot["source_file"].endswith("li7200_device_zero_span_2026.json")
        assert controller.ec_processing["steps"]["primary_analyzer"]["profile_id"] == "licor_li7200_family"
        assert controller.project_workspace["primary_analyzer_devices"][uid]["allowed_diagnostic_words"] == [0, 4]
        assert controller.report_center_workspace["primary_analyzer"]["calibration_profile_id"] == "li7200_device_zero_span_2026"
        assert controller.device_detail_snapshot(uid)["primary_analyzer_config"]["require_cell_thermodynamics"] is True
        assert "li7200_device_zero_span_2026" in page.primary_analyzer_summary_label.text()
    finally:
        controller.shutdown()
