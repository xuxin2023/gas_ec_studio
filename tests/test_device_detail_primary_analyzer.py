from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.pages.device_detail_page import DeviceDetailPage
from app.studio import StudioController
from core.ec_rp.pipeline import _extract_trace_gas_config


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


def test_device_detail_page_applies_li7700_trace_gas_profile_to_pipeline(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Tower LI-7700",
            port="SIM3",
            baudrate=9600,
            device_id="LI7700",
            analyzer_profile="licor_li7700_family",
        )
        controller.select_device(uid)
        page = DeviceDetailPage(controller)
        page.refresh()

        page.trace_gas_enable_combo.setCurrentText("enabled")
        page.trace_gas_coefficient_profile_edit.setText("tower_li7700_device_2026")
        page.trace_gas_source_file_edit.setText("D:/fixtures/tower_li7700_device_2026.json")
        page.trace_gas_normalization_command_edit.setText(
            "gas_ec_studio normalize-li7700 --profile tower_li7700_device_2026"
        )
        page.trace_gas_spectroscopic_mode_combo.setCurrentText("empirical")
        page.trace_gas_self_heating_mode_combo.setCurrentText("empirical")
        page.trace_gas_water_vapor_combo.setCurrentText("enabled")
        page.trace_gas_spectral_factor_combo.setCurrentText("enabled")
        page.trace_gas_require_lock_combo.setCurrentText("required")
        page.trace_gas_rssi_warning_spin.setValue(28.0)
        page.trace_gas_rssi_fail_spin.setValue(12.0)

        payload = page._collect_trace_gas_payload()
        assert payload["coefficient_profile_id"] == "tower_li7700_device_2026"
        assert payload["spectroscopic_correction_mode"] == "empirical"
        assert payload["status_diagnostics"]["require_lock"] is True

        snapshot = controller.apply_device_trace_gas_config(uid, payload)
        page._populate_trace_gas_config(dict(snapshot))

        trace_step = controller.ec_processing["steps"]["trace_gas"]
        ch4_step = trace_step["ch4"]
        assert ch4_step["coefficient_profile_id"] == "tower_li7700_device_2026"
        assert ch4_step["coefficient_registry"]["tower_li7700_device_2026"]["source_file"].endswith(
            "tower_li7700_device_2026.json"
        )
        assert controller.project_workspace["trace_gas_devices"][uid]["status_diagnostics"]["min_rssi_warning_pct"] == 28.0
        assert controller.report_center_workspace["trace_gas"]["coefficient_profile_id"] == "tower_li7700_device_2026"

        rp_config = controller._rp_config_snapshot(precheck_only=False)
        trace_config = _extract_trace_gas_config(rp_config)
        ch4 = trace_config["ch4"]
        assert ch4["coefficient_profile_id"] == "tower_li7700_device_2026"
        assert ch4["coefficient_registry_status"] == "resolved"
        assert ch4["coefficient_profile_source_file"].endswith("tower_li7700_device_2026.json")
        assert ch4["coefficient_profile_normalization_command"].startswith("gas_ec_studio normalize-li7700")
        assert ch4["spectroscopic_correction"]["mode"] == "empirical"
        assert ch4["self_heating_correction"]["mode"] == "empirical"
        assert ch4["status_diagnostics"]["require_lock"] is True
        assert controller.device_detail_snapshot(uid)["trace_gas_config"]["coefficient_profile_id"] == "tower_li7700_device_2026"
        assert "tower_li7700_device_2026" in page.trace_gas_summary_label.text()
    finally:
        controller.shutdown()


def test_device_detail_page_applies_n2o_trace_gas_profile_to_pipeline(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Tower N2O",
            port="SIM4",
            baudrate=9600,
            device_id="N2O01",
            analyzer_profile="generic_n2o_trace_gas_family",
        )
        controller.select_device(uid)
        page = DeviceDetailPage(controller)
        page.refresh()

        assert page.trace_gas_gas_combo.currentData() == "n2o"
        page.trace_gas_enable_combo.setCurrentText("enabled")
        page.trace_gas_coefficient_profile_edit.setText("tower_n2o_device_2026")
        page.trace_gas_source_file_edit.setText("D:/fixtures/tower_n2o_device_2026.json")
        page.trace_gas_normalization_command_edit.setText(
            "gas_ec_studio normalize-trace-gas --gas n2o --profile tower_n2o_device_2026"
        )
        page.trace_gas_spectral_factor_combo.setCurrentText("enabled")
        page.trace_gas_spectral_factor_value_spin.setValue(1.07)
        page.trace_gas_analyzer_factor_spin.setValue(0.98)
        page.trace_gas_density_factor_spin.setValue(1.01)

        payload = page._collect_trace_gas_payload()
        assert payload["gas"] == "n2o"
        assert payload["method"] == "n2o_empirical_correction_sequence_v1"
        assert payload["analyzer_profile_id"] == "generic_n2o_trace_gas_family"
        assert payload["coefficient_profile_id"] == "tower_n2o_device_2026"

        snapshot = controller.apply_device_trace_gas_config(uid, payload)
        page._populate_trace_gas_config(dict(snapshot))

        trace_step = controller.ec_processing["steps"]["trace_gas"]
        n2o_step = trace_step["n2o"]
        assert trace_step["gas"] == "n2o"
        assert n2o_step["coefficient_profile_id"] == "tower_n2o_device_2026"
        assert n2o_step["coefficient_registry"]["tower_n2o_device_2026"]["source_file"].endswith(
            "tower_n2o_device_2026.json"
        )
        assert n2o_step["spectral_correction_factor"] == 1.07
        assert n2o_step["analyzer_correction_factor"] == 0.98
        assert n2o_step["density_correction_factor"] == 1.01
        assert controller.report_center_workspace["trace_gas"]["gas"] == "n2o"

        rp_config = controller._rp_config_snapshot(precheck_only=False)
        trace_config = _extract_trace_gas_config(rp_config)
        n2o = trace_config["n2o"]
        assert n2o["coefficient_profile_id"] == "tower_n2o_device_2026"
        assert n2o["coefficient_registry_status"] == "resolved"
        assert n2o["coefficient_profile_source_file"].endswith("tower_n2o_device_2026.json")
        assert n2o["coefficient_profile_normalization_command"].startswith("gas_ec_studio normalize-trace-gas")
        assert n2o["spectral_correction_factor"] == 1.07
        assert n2o["analyzer_correction_factor"] == 0.98
        assert n2o["density_correction_factor"] == 1.01
        assert controller.device_detail_snapshot(uid)["trace_gas_config"]["gas"] == "n2o"
        assert "tower_n2o_device_2026" in page.trace_gas_summary_label.text()
    finally:
        controller.shutdown()
