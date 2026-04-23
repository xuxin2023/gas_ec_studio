from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from app.pages.ec_processing_page import ECProcessingPage
from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.5 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.08 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.8 + 0.25 * np.cos(2.0 * np.pi * 0.02 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.3 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                case_temp_c=float(temp[index] - 0.1),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def _seed_controller(controller: StudioController) -> None:
    controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
    controller.project_workspace["timing"]["block_minutes"] = 0.5
    controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
    controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
    controller.ec_processing["steps"]["lag"]["search_window_s"] = 1.5
    controller.ec_processing["steps"]["lag"]["expected_lag_s"] = 0.5
    for row in _make_rows():
        controller.realtime_buffer.append(row)


def _benchmark_config() -> dict[str, object]:
    return {
        "status": "active",
        "target": "eddypro_v7",
        "reference_id": "eddypro_v7_synthetic_001",
        "flux_rel_threshold": 0.10,
        "lag_abs_threshold_s": 0.5,
        "wpl_rel_threshold": 0.20,
        "qc_grade_must_match": False,
    }


def test_ec_processing_page_method_controls_roundtrip_to_snapshot(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ECProcessingPage(controller)
        page.footprint_enable_combo.setCurrentText("enabled")
        page.footprint_method_combo.setCurrentText("kormann_meixner")
        page.footprint_zm_spin.setValue(4.2)
        page.footprint_canopy_spin.setValue(6.4)
        page.footprint_z0_spin.setValue(0.18)
        page.footprint_ol_spin.setValue(-120.0)
        page.uncertainty_mode_combo.setCurrentText("finkelstein_sims")
        page.uncertainty_timescale_spin.setValue(7.5)
        page.uncertainty_confidence_spin.setValue(0.90)
        page.spectral_enable_combo.setCurrentText("enabled")
        page.spectral_method_combo.setCurrentText("fratini")
        page.spectral_path_spin.setValue(0.18)
        page.spectral_sep_spin.setValue(0.24)
        page.spectral_response_spin.setValue(0.12)
        page.spectral_zm_spin.setValue(3.8)
        page.spectral_ol_spin.setValue(-80.0)
        page.spectral_cospectrum_combo.setCurrentText("fcc_auto")

        payload = page._collect_payload()
        assert payload["steps"]["footprint"]["method"] == "kormann_meixner"
        assert payload["steps"]["footprint"]["z_m"] == 4.2
        assert payload["steps"]["uncertainty"]["method"] == "finkelstein_sims"
        assert payload["steps"]["uncertainty"]["integral_timescale_s"] == 7.5
        assert payload["steps"]["uncertainty"]["confidence_level"] == 0.9
        assert payload["steps"]["spectral_correction"]["method"] == "fratini"
        assert payload["steps"]["spectral_correction"]["use_fcc_measured_cospectrum"] is True

        controller.save_ec_processing(payload)
        snapshot = controller._rp_config_snapshot(precheck_only=False)
        assert snapshot["footprint"]["method"] == "kormann_meixner"
        assert snapshot["footprint"]["z_m"] == 4.2
        assert snapshot["uncertainty"]["method"] == "finkelstein_sims"
        assert snapshot["uncertainty"]["integral_timescale_s"] == 7.5
        assert snapshot["uncertainty"]["confidence_level"] == 0.9
        assert snapshot["spectral_correction"]["method"] == "fratini"
        assert snapshot["spectral_correction"]["fcc_measured_cospectra"] == []
    finally:
        controller.shutdown()


def test_fratini_auto_injects_fcc_measured_cospectrum(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _seed_controller(controller)
        controller.ec_processing["steps"]["footprint"]["method"] = "kljun"
        controller.ec_processing["steps"]["uncertainty"]["method"] = "mann_lenschow"
        controller.ec_processing["steps"]["spectral_correction"].update(
            {
                "enabled": True,
                "method": "fratini",
                "path_length_m": 0.15,
                "sensor_sep_m": 0.2,
                "response_time_s": 0.1,
                "z_m": 3.0,
                "ol": -100.0,
                "use_fcc_measured_cospectrum": True,
            }
        )

        controller.run_spectral_qc()
        controller.run_ec_processing()
        rp_run = controller.current_rp_run()
        spectral_run = controller.current_spectral_run()
        assert rp_run is not None
        assert spectral_run is not None

        diagnostics = rp_run.windows[0].diagnostics
        assert diagnostics["spectral_correction_method"] == "fratini"
        assert diagnostics["spectral_correction_measured_cospectrum_enabled"] is True
        assert diagnostics["spectral_correction_measured_cospectrum_used"] is True
        assert diagnostics["spectral_correction_measured_cospectrum_source"] == "fcc_auto"
        assert diagnostics["spectral_correction_measured_cospectrum_source_run_id"] == spectral_run.run_id

        method_summary = controller._rp_method_summary(rp_run)
        assert method_summary["spectral_correction_method"] == "fratini"
        assert method_summary["spectral_correction_measured_cospectrum_source"] == "fcc_auto"
    finally:
        controller.shutdown()


def test_uncertainty_propagates_to_export_benchmark_and_network(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _seed_controller(controller)
        controller.report_center_workspace["benchmark"] = _benchmark_config()
        controller.ec_processing["steps"]["footprint"].update({"enabled": True, "method": "hsieh", "z_m": 3.0, "canopy_height_m": 5.0})
        controller.ec_processing["steps"]["uncertainty"].update({"method": "mann_lenschow", "integral_timescale_s": 5.0, "confidence_level": 0.95})
        controller.ec_processing["steps"]["spectral_correction"].update(
            {
                "enabled": True,
                "method": "fratini",
                "path_length_m": 0.15,
                "sensor_sep_m": 0.2,
                "response_time_s": 0.1,
                "z_m": 3.0,
                "ol": -100.0,
                "use_fcc_measured_cospectrum": True,
            }
        )

        controller.run_spectral_qc()
        controller.run_ec_processing()
        controller.export_current_report()

        rp_run = controller.current_rp_run()
        spectral_run = controller.current_spectral_run()
        assert rp_run is not None
        assert spectral_run is not None
        first_diag = rp_run.windows[0].diagnostics
        assert first_diag["primary_flux_random_error"] is not None
        assert first_diag["primary_flux_relative_uncertainty"] is not None
        assert first_diag["primary_flux_uncertainty_band"] is not None
        assert first_diag["primary_flux_ci_lower"] is not None
        assert first_diag["primary_flux_ci_upper"] is not None
        assert rp_run.summary["uncertainty_random_error"] is not None
        assert rp_run.summary["uncertainty_band"] is not None
        assert "method_rollup" in rp_run.artifacts

        latest_files = spectral_run.artifacts["result_exports"]["latest"]["files"]
        method_rollup_path = Path(latest_files["method_rollup_artifact"])
        manifest_path = Path(latest_files["export_manifest"])
        full_output_path = Path(latest_files["full_output"])
        benchmark_path = Path(latest_files["benchmark_summary_artifact"])
        parity_path = Path(latest_files["parity_artifact"])
        fluxnet_path = Path(latest_files["fluxnet_half_hourly_artifact"])

        assert method_rollup_path.exists()
        rollup = json.loads(method_rollup_path.read_text(encoding="utf-8"))
        assert rollup["footprint_method"] == "hsieh"
        assert rollup["uncertainty_method"] == "mann_lenschow"
        assert rollup["spectral_correction_method"] == "fratini"
        assert rollup["spectral_correction_summary"]["measured_cospectrum_used"] is True

        full_output_csv = full_output_path.read_text(encoding="utf-8")
        assert "primary_flux_random_error" in full_output_csv
        assert "primary_flux_uncertainty_band" in full_output_csv
        assert "primary_flux_ci_lower" in full_output_csv
        assert "spectral_correction_measured_cospectrum_source" in full_output_csv

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["method_rollup_artifact"]
        assert "FOOTPRINT_METHOD" in manifest["network_method_fields"]
        assert "FC_RANDOM_ERROR" in manifest["network_uncertainty_fields"]

        benchmark_artifact = json.loads(benchmark_path.read_text(encoding="utf-8"))
        assert benchmark_artifact["per_window"][0]["primary_flux_random_error"] is not None
        assert benchmark_artifact["per_window"][0]["primary_flux_uncertainty_band"] is not None

        parity_artifact = json.loads(parity_path.read_text(encoding="utf-8"))
        assert parity_artifact["per_window"][0]["primary_flux_random_error"] is not None
        assert parity_artifact["per_window"][0]["primary_flux_ci_upper"] is not None

        fluxnet_artifact = json.loads(fluxnet_path.read_text(encoding="utf-8"))
        first_row = fluxnet_artifact["rows"][0]
        assert "FC_RANDOM_ERROR" in first_row
        assert "FC_REL_UNCERTAINTY" in first_row
        assert "FC_CI_LOWER" in first_row
        assert "FC_CI_UPPER" in first_row
        assert "FC_CI_LEVEL" in first_row
        assert first_row["FOOTPRINT_METHOD"] == "hsieh"
        assert first_row["UNCERTAINTY_METHOD"] == "mann_lenschow"
        assert first_row["SPECTRAL_CORRECTION_METHOD"] == "fratini"
        assert "METHOD_DEVIATION_NOTES" in first_row
    finally:
        controller.shutdown()
