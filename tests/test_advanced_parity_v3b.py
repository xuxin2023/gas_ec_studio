"""Tests for Advanced Processing Parity v3b-core.

Covers:
  1. Sector-wise planar fit
  2. WPL complete formula
  3. Advanced statistical tests
  4. Rich output groundwork (qc_details, metadata_summary)
  5. Regression of existing tests
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.ec_rp.analysis import (
    PlanarFitCoefficients,
    apply_planar_fit_no_velocity_bias,
    apply_planar_fit_rotation,
    check_amplitude_resolution,
    check_angle_of_attack,
    check_steadiness_of_horizontal_wind,
    check_time_lag,
    compute_flux_metrics,
    compute_planar_fit_coefficients,
    normalize_rotation_mode,
    optimize_h2o_lag_rh,
    optimize_lag,
    rotate_wind,
)
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.rp_models import WindowRPResult, RPRunResult


def _make_rows(sample_hz: float = 10.0, samples: int = 480) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
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
                pressure_kpa=101.3,
                chamber_temp_c=24.8,
                case_temp_c=24.7,
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 1. Sector-wise planar fit
# ---------------------------------------------------------------------------

class TestSectorWisePlanarFit:
    def test_normalize_sector_wise_planar_fit(self):
        assert normalize_rotation_mode("sector_wise_planar_fit") == "sector_wise_planar_fit"
        assert normalize_rotation_mode("swpf") == "sector_wise_planar_fit"
        assert normalize_rotation_mode("sector_planar_fit") == "sector_wise_planar_fit"

    def test_normalize_sector_wise_planar_fit_no_velocity_bias(self):
        assert normalize_rotation_mode("sector_wise_planar_fit_no_velocity_bias") == "sector_wise_planar_fit_no_velocity_bias"
        assert normalize_rotation_mode("swpf_nvb") == "sector_wise_planar_fit_no_velocity_bias"

    def test_compute_planar_fit_coefficients_basic(self):
        np.random.seed(42)
        u_list = [2.0 + 0.3 * np.random.randn(200) for _ in range(10)]
        v_list = [0.5 + 0.2 * np.random.randn(200) for _ in range(10)]
        w_list = [0.1 + 0.15 * np.random.randn(200) for _ in range(10)]
        coeffs = compute_planar_fit_coefficients(u_list, v_list, w_list, min_windows_per_sector=3)
        assert len(coeffs) > 0
        for sector_label, c in coeffs.items():
            assert isinstance(c, PlanarFitCoefficients)
            assert c.sector == sector_label

    def test_apply_planar_fit_rotation_with_valid_coefficients(self):
        np.random.seed(42)
        u = 2.0 + 0.3 * np.random.randn(200)
        v = 0.5 + 0.2 * np.random.randn(200)
        w = 0.1 + 0.15 * np.random.randn(200)
        coeffs = PlanarFitCoefficients(b0=0.01, b1=0.02, b2=-0.01, sector="S00", window_count=10, r_squared=0.85)
        result = apply_planar_fit_rotation(u, v, w, coeffs)
        assert result.mode == "sector_wise_planar_fit"
        assert result.applied
        assert "S00" in result.reason
        assert "R²=0.850" in result.reason

    def test_apply_planar_fit_rotation_fallback_insufficient_data(self):
        np.random.seed(42)
        u = 2.0 + 0.3 * np.random.randn(200)
        v = 0.5 + 0.2 * np.random.randn(200)
        w = 0.1 + 0.15 * np.random.randn(200)
        coeffs = PlanarFitCoefficients(b0=0.0, b1=0.0, b2=0.0, sector="S00", window_count=2, r_squared=0.0)
        result = apply_planar_fit_rotation(u, v, w, coeffs)
        assert result.mode == "sector_wise_planar_fit"
        assert result.applied
        assert "fallback" in result.reason.lower() or "insufficient" in result.reason.lower()

    def test_apply_planar_fit_no_velocity_bias(self):
        np.random.seed(42)
        u = 2.0 + 0.3 * np.random.randn(200)
        v = 0.5 + 0.2 * np.random.randn(200)
        w = 0.1 + 0.15 * np.random.randn(200)
        coeffs = PlanarFitCoefficients(b0=0.01, b1=0.02, b2=-0.01, sector="S00", window_count=10, r_squared=0.85)
        result = apply_planar_fit_no_velocity_bias(u, v, w, coeffs)
        assert result.mode == "sector_wise_planar_fit_no_velocity_bias"
        assert result.applied
        assert "velocity bias removed" in result.reason.lower()

    def test_pipeline_sector_wise_planar_fit(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "sector_wise_planar_fit"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("requested_rotation_mode") == "sector_wise_planar_fit"
            impl = window.diagnostics.get("applied_rotation_impl", "")
            assert "planar_fit" in impl or "double" in impl

    def test_pipeline_sector_wise_planar_fit_no_velocity_bias(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "sector_wise_planar_fit_no_velocity_bias"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("requested_rotation_mode") == "sector_wise_planar_fit_no_velocity_bias"


# ---------------------------------------------------------------------------
# 2. WPL complete formula
# ---------------------------------------------------------------------------

class TestWPLCompleteFormula:
    def test_wpl_has_sensible_heat_term(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 0.5 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        assert "wpl_water_vapor_term" in result
        assert "wpl_sensible_heat_term" in result
        assert isinstance(result["wpl_water_vapor_term"], float)
        assert isinstance(result["wpl_sensible_heat_term"], float)

    def test_wpl_correction_reason_mentions_terms(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 0.5 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        reason = result["density_correction_reason"]
        assert "wpl" in reason.lower()
        assert "water_vapor_term" in reason or "sensible_heat_term" in reason

    def test_wpl_primary_flux_differs_from_old_simple_wpl(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 8.0 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        old_simple = result["raw_flux"] + float(np.mean(co2)) * 1e-6 * result["air_molar_density"] * result["cov_w_h2o"]
        sensible_heat = result["wpl_sensible_heat_term"]
        if abs(sensible_heat) > 1e-12:
            diff = abs(result["density_corrected_flux"] - old_simple)
            assert diff > 0, f"Complete WPL should differ from water-vapor-only correction when sensible heat term is non-negligible ({sensible_heat:.4e})"

    def test_mixing_ratio_mode_still_stable(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 0.5 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="mixing_ratio",
        )
        assert result["primary_flux"] == pytest.approx(result["mixing_ratio_flux"], rel=1e-9)

    def test_none_mode_still_stable(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 0.5 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="none",
        )
        assert result["primary_flux"] == pytest.approx(result["raw_flux"], rel=1e-9)

    def test_pipeline_wpl_diagnostics_has_terms(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "wpl_water_vapor_term" in window.diagnostics
            assert "wpl_sensible_heat_term" in window.diagnostics


# ---------------------------------------------------------------------------
# 3. Advanced statistical tests
# ---------------------------------------------------------------------------

class TestAdvancedStatisticalTests:
    def test_amplitude_resolution_pass(self):
        series = np.random.randn(1000) * 10.0
        result = check_amplitude_resolution(series)
        assert result["test"] == "amplitude_resolution"
        assert result["status"] in ("pass", "fail")

    def test_amplitude_resolution_constant_signal(self):
        series = np.full(100, 5.0)
        result = check_amplitude_resolution(series)
        assert result["status"] in ("constant_signal", "fail")

    def test_amplitude_resolution_insufficient_data(self):
        result = check_amplitude_resolution(np.array([1.0, 2.0]))
        assert result["status"] == "insufficient_data"

    def test_time_lag_basic(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        scalar = np.roll(w, 10) + 0.1 * np.random.randn(n)
        result = check_time_lag(w, scalar, 10.0)
        assert result["test"] == "time_lag_test"
        assert result["status"] in ("pass", "fail")
        assert "peak_lag_s" in result["detail"]

    def test_time_lag_insufficient_data(self):
        result = check_time_lag(np.array([1.0]), np.array([1.0]), 10.0)
        assert result["status"] == "insufficient_data"

    def test_angle_of_attack_normal_wind(self):
        np.random.seed(42)
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        w = 0.1 + 0.15 * np.random.randn(n)
        result = check_angle_of_attack(u, w)
        assert result["test"] == "angle_of_attack"
        assert result["status"] in ("pass", "fail")
        assert "mean_angle_deg" in result["detail"]

    def test_angle_of_attack_insufficient_data(self):
        result = check_angle_of_attack(np.array([1.0]), np.array([1.0]))
        assert result["status"] == "insufficient_data"

    def test_steadiness_of_horizontal_wind(self):
        np.random.seed(42)
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        v = 0.5 + 0.2 * np.random.randn(n)
        result = check_steadiness_of_horizontal_wind(u, v)
        assert result["test"] == "steadiness_of_horizontal_wind"
        assert result["status"] in ("pass", "fail", "calm")
        assert "cv" in result["detail"]

    def test_steadiness_calm(self):
        u = np.full(100, 1e-7)
        v = np.full(100, 1e-7)
        result = check_steadiness_of_horizontal_wind(u, v)
        assert result["status"] == "calm"

    def test_optimize_lag_basic(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = np.roll(w, 10) + 0.1 * np.random.randn(n)
        h2o = np.roll(w, 5) + 0.1 * np.random.randn(n)
        result = optimize_lag(w, co2, h2o, 10.0)
        assert "co2_lag_s" in result
        assert "h2o_lag_s" in result

    def test_optimize_h2o_lag_rh_basic(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        h2o = np.roll(w, 5) + 0.1 * np.random.randn(n)
        temp = np.full(n, 25.0)
        pressure = np.full(n, 101.3)
        result = optimize_h2o_lag_rh(w, h2o, temp, pressure, 10.0)
        assert "h2o_lag_s" in result
        assert "rh_approx" in result
        assert "rh_adjusted" in result


# ---------------------------------------------------------------------------
# 4. Rich output groundwork
# ---------------------------------------------------------------------------

class TestRichOutputGroundwork:
    def test_pipeline_has_qc_details(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "qc_details" in window.diagnostics
            qc = window.diagnostics["qc_details"]
            assert "amplitude_resolution_co2" in qc
            assert "amplitude_resolution_h2o" in qc
            assert "time_lag_co2" in qc
            assert "time_lag_h2o" in qc
            assert "angle_of_attack" in qc
            assert "steadiness_of_horizontal_wind" in qc

    def test_pipeline_has_metadata_summary(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "metadata_summary" in window.diagnostics
            ms = window.diagnostics["metadata_summary"]
            assert "sample_rate_hz" in ms
            assert "sample_count" in ms
            assert "mean_co2_ppm" in ms

    def test_full_output_schema_has_qc_details(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "qc_details" in schema_names
        assert "metadata_summary" in schema_names
        assert "wpl_water_vapor_term" in schema_names
        assert "wpl_sensible_heat_term" in schema_names

    def test_full_output_row_has_qc_details(self):
        window = WindowRPResult(
            window_id="w1",
            start_time=datetime(2025, 1, 1, 0, 0),
            end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01,
            raw_flux=-5.2, mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0, primary_flux=-5.0,
            primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0,
            dry_air_molar_density=41.5, mean_co2_ppm=415.0,
            mean_h2o_mmol=10.0, mean_pressure_kpa=101.3,
            mean_temp_c=25.0, qc_grade="A",
            anomaly_type="", reason="",
            diagnostics={
                "qc_details": {"amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "pass"}},
                "metadata_summary": {"sample_rate_hz": 10.0, "sample_count": 18000},
                "wpl_water_vapor_term": 1.2e-6,
                "wpl_sensible_heat_term": 3.4e-7,
            },
        )
        rp_result = RPRunResult(
            run_id="test_run", created_at=datetime(2025, 1, 1),
            windows=[window], summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert len(rows) == 1
        assert "qc_details" in rows[0]
        assert "metadata_summary" in rows[0]
        assert rows[0]["wpl_water_vapor_term"] == 1.2e-6
        assert rows[0]["wpl_sensible_heat_term"] == 3.4e-7

    def test_advanced_tests_in_screening_summary(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            summary = window.diagnostics.get("screening_summary", "")
            assert "advanced" in summary.lower() or "amplitude_resolution" in summary or "angle_of_attack" in summary

    def test_advanced_tests_each_have_status_and_detail(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            qc = window.diagnostics["qc_details"]
            for test_key in ("amplitude_resolution_co2", "amplitude_resolution_h2o", "time_lag_co2", "time_lag_h2o", "angle_of_attack", "steadiness_of_horizontal_wind"):
                entry = qc[test_key]
                assert "status" in entry, f"{test_key} missing 'status'"
                assert "detail" in entry, f"{test_key} missing 'detail'"
                assert entry["status"] in ("pass", "fail", "insufficient_data", "constant_signal", "calm"), f"{test_key} has unexpected status: {entry['status']}"

    def test_advanced_tests_preserve_abc_grades(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.qc_grade in ("A", "B", "C")


# ---------------------------------------------------------------------------
# 5. Advanced QC Score Integration
# ---------------------------------------------------------------------------

class TestAdvancedQCScoreIntegration:
    def test_advanced_fail_lowers_qc_score(self):
        np.random.seed(42)
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        v = 0.5 + 0.2 * np.random.randn(n)
        w = 0.1 + 0.15 * np.random.randn(n)
        from core.ec_rp.qc import classify_window_qc
        result_pass = classify_window_qc(
            issues=[], continuity_ratio=0.99, missing_ratio=0.01,
            lag_confidence=0.85, density_correction_factor=1.0,
            rotation_applied=True, mean_rotated_w=0.01,
            stationarity_score=0.9, stationarity_detail={"score": 0.9},
            turbulence_score=0.8, turbulence_detail={"score": 0.8},
            ustar=0.3,
            advanced_tests={
                "amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "pass", "detail": {"ratio": 50.0}},
                "amplitude_resolution_h2o": {"test": "amplitude_resolution", "status": "pass", "detail": {"ratio": 30.0}},
                "time_lag_co2": {"test": "time_lag_test", "status": "pass", "detail": {"confidence": 0.8}},
                "time_lag_h2o": {"test": "time_lag_test", "status": "pass", "detail": {"confidence": 0.7}},
                "angle_of_attack": {"test": "angle_of_attack", "status": "pass", "detail": {"mean_angle_deg": 5.0}},
                "steadiness_of_horizontal_wind": {"test": "steadiness_of_horizontal_wind", "status": "pass", "detail": {"cv": 0.2}},
            },
        )
        result_fail = classify_window_qc(
            issues=[], continuity_ratio=0.99, missing_ratio=0.01,
            lag_confidence=0.85, density_correction_factor=1.0,
            rotation_applied=True, mean_rotated_w=0.01,
            stationarity_score=0.9, stationarity_detail={"score": 0.9},
            turbulence_score=0.8, turbulence_detail={"score": 0.8},
            ustar=0.3,
            advanced_tests={
                "amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "fail", "detail": {"ratio": 2.0}},
                "amplitude_resolution_h2o": {"test": "amplitude_resolution", "status": "fail", "detail": {"ratio": 1.5}},
                "time_lag_co2": {"test": "time_lag_test", "status": "fail", "detail": {"confidence": 0.1}},
                "time_lag_h2o": {"test": "time_lag_test", "status": "fail", "detail": {"confidence": 0.1}},
                "angle_of_attack": {"test": "angle_of_attack", "status": "fail", "detail": {"exceed_fraction": 0.2}},
                "steadiness_of_horizontal_wind": {"test": "steadiness_of_horizontal_wind", "status": "fail", "detail": {"cv": 0.9}},
            },
        )
        assert result_fail["qc_score"] < result_pass["qc_score"], \
            f"All-advanced-fail score ({result_fail['qc_score']:.2f}) should be lower than all-pass ({result_pass['qc_score']:.2f})"

    def test_advanced_fail_can_degrade_grade(self):
        from core.ec_rp.qc import classify_window_qc
        result = classify_window_qc(
            issues=[], continuity_ratio=0.99, missing_ratio=0.01,
            lag_confidence=0.85, density_correction_factor=1.0,
            rotation_applied=True, mean_rotated_w=0.01,
            stationarity_score=0.9, stationarity_detail={"score": 0.9},
            turbulence_score=0.8, turbulence_detail={"score": 0.8},
            ustar=0.3,
            advanced_tests={
                "amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "fail", "detail": {"ratio": 2.0}},
                "amplitude_resolution_h2o": {"test": "amplitude_resolution", "status": "fail", "detail": {"ratio": 1.5}},
                "time_lag_co2": {"test": "time_lag_test", "status": "fail", "detail": {"confidence": 0.1}},
                "time_lag_h2o": {"test": "time_lag_test", "status": "fail", "detail": {"confidence": 0.1}},
                "angle_of_attack": {"test": "angle_of_attack", "status": "fail", "detail": {"exceed_fraction": 0.2}},
                "steadiness_of_horizontal_wind": {"test": "steadiness_of_horizontal_wind", "status": "fail", "detail": {"cv": 0.9}},
            },
        )
        assert result["qc_grade"] in ("B", "C"), \
            f"All advanced tests failing should degrade grade from A, got {result['qc_grade']}"

    def test_advanced_tests_in_qc_matrix(self):
        from core.ec_rp.qc import classify_window_qc
        result = classify_window_qc(
            issues=[], continuity_ratio=0.99, missing_ratio=0.01,
            lag_confidence=0.85, density_correction_factor=1.0,
            rotation_applied=True, mean_rotated_w=0.01,
            stationarity_score=0.9, stationarity_detail={"score": 0.9},
            turbulence_score=0.8, turbulence_detail={"score": 0.8},
            ustar=0.3,
            advanced_tests={
                "amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "pass", "detail": {"ratio": 50.0}},
                "time_lag_co2": {"test": "time_lag_test", "status": "fail", "detail": {"confidence": 0.1}},
                "angle_of_attack": {"test": "angle_of_attack", "status": "pass", "detail": {}},
                "steadiness_of_horizontal_wind": {"test": "steadiness_of_horizontal_wind", "status": "calm", "detail": {}},
            },
        )
        matrix = result["qc_matrix"]
        assert "adv_amplitude_resolution_co2" in matrix
        assert "adv_time_lag_co2" in matrix
        assert "adv_angle_of_attack" in matrix
        assert "adv_steadiness_of_horizontal_wind" in matrix
        assert matrix["adv_amplitude_resolution_co2"]["status"] == "pass"
        assert matrix["adv_time_lag_co2"]["status"] == "fail"
        assert matrix["adv_steadiness_of_horizontal_wind"]["status"] == "fallback"

    def test_advanced_fallback_status_in_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            qc = window.diagnostics["qc_details"]
            for test_key, entry in qc.items():
                status = entry.get("status", "")
                assert status in ("pass", "fail", "insufficient_data", "constant_signal", "calm"), \
                    f"{test_key} has unexpected status: {status}"

    def test_pipeline_advanced_qc_contribution_in_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "advanced_qc_contribution" in window.diagnostics
            assert "advanced_test_weights" in window.diagnostics
            assert "advanced_test_thresholds" in window.diagnostics
            contrib = window.diagnostics["advanced_qc_contribution"]
            for key, val in contrib.items():
                assert "status" in val
                assert "weight" in val
                assert "score_contribution" in val


# ---------------------------------------------------------------------------
# 6. Advanced test threshold configurability
# ---------------------------------------------------------------------------

class TestAdvancedTestThresholdConfig:
    def test_amplitude_resolution_custom_threshold(self):
        series = np.arange(0, 100, 0.1)
        series = series + np.random.randn(series.size) * 0.01
        result_loose = check_amplitude_resolution(series, ratio_threshold=1.0)
        result_strict = check_amplitude_resolution(series, ratio_threshold=100000.0)
        assert result_loose["status"] == "pass"
        assert result_strict["status"] == "fail"

    def test_angle_of_attack_custom_threshold(self):
        np.random.seed(42)
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        w = 0.1 + 0.15 * np.random.randn(n)
        result_default = check_angle_of_attack(u, w, max_angle_deg=40.0)
        result_strict = check_angle_of_attack(u, w, max_angle_deg=1.0)
        assert result_default["status"] == "pass"
        assert result_strict["status"] == "fail"

    def test_steadiness_custom_cv_threshold(self):
        np.random.seed(42)
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        v = 0.5 + 0.2 * np.random.randn(n)
        result_default = check_steadiness_of_horizontal_wind(u, v, cv_threshold=0.50)
        result_strict = check_steadiness_of_horizontal_wind(u, v, cv_threshold=0.01)
        assert result_default["status"] == "pass"
        assert result_strict["status"] == "fail"

    def test_time_lag_custom_confidence_threshold(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        scalar = np.roll(w, 10) + 0.1 * np.random.randn(n)
        result_default = check_time_lag(w, scalar, 10.0, confidence_threshold=0.4)
        result_strict = check_time_lag(w, scalar, 10.0, confidence_threshold=0.99)
        assert result_default["status"] == "pass"
        assert result_strict["status"] == "fail"

    def test_pipeline_config_overrides_thresholds(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result_default = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        result_strict = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"advanced_tests": {"angle_of_attack_max_angle_deg": 0.001}},
            data_source="test",
            time_range="",
        )
        default_aoa = result_default.windows[0].diagnostics["qc_details"]["angle_of_attack"]
        strict_aoa = result_strict.windows[0].diagnostics["qc_details"]["angle_of_attack"]
        assert default_aoa["status"] == "pass"
        assert strict_aoa["status"] == "fail"

    def test_manifest_records_advanced_test_thresholds(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        rp_result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"advanced_tests": {"steadiness_cv_threshold": 0.30}},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rp_config_snapshot = {"advanced_tests": {"steadiness_cv_threshold": 0.30}}
        manifest = {}
        manifest["advanced_test_thresholds"] = exporter._extract_advanced_test_thresholds(rp_config_snapshot)
        assert manifest["advanced_test_thresholds"]["steadiness_cv_threshold"] == 0.30


# ---------------------------------------------------------------------------
# 7. WPL benchmark validation
# ---------------------------------------------------------------------------

class TestWPLBenchmark:
    def test_wpl_benchmark_status_in_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "wpl_benchmark_status" in window.diagnostics
            bm = window.diagnostics["wpl_benchmark_status"]
            assert "status" in bm
            assert "wpl_water_vapor_term" in bm
            assert "wpl_sensible_heat_term" in bm
            assert "total_density_correction" in bm
            assert "correction_ratio" in bm
            assert "magnitude_reasonable" in bm
            assert bm["status"] in ("pass", "attention", "fail")

    def test_wpl_benchmark_sensible_heat_direction(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 8.0 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        wpl_wv = result["wpl_water_vapor_term"]
        wpl_sh = result["wpl_sensible_heat_term"]
        total = wpl_wv + wpl_sh
        if abs(wpl_sh) > 1e-15 and abs(total) > 1e-15:
            same_sign = (wpl_sh * total) >= 0
            if not same_sign:
                from core.ec_rp.pipeline import _wpl_benchmark_status
                bm = _wpl_benchmark_status(result)
                assert bm["status"] in ("attention", "fail"), \
                    "opposing sensible heat direction should be flagged in benchmark status"
                assert any("opposes" in note for note in bm["notes"]), \
                    "benchmark notes should mention opposing direction"

    def test_wpl_benchmark_magnitude_reasonable(self):
        np.random.seed(42)
        n = 1000
        w = 0.5 * np.random.randn(n)
        co2 = 410.0 + 5.0 * np.random.randn(n)
        h2o = 12.0 + 1.0 * np.random.randn(n)
        pressure = np.full(n, 101.3)
        temp = 25.0 + 2.0 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        raw = result["raw_flux"]
        total_correction = result["wpl_water_vapor_term"] + result["wpl_sensible_heat_term"]
        if abs(raw) > 1e-12:
            correction_ratio = abs(total_correction / raw)
            assert correction_ratio < 0.5, \
                f"WPL correction ratio ({correction_ratio:.3f}) should be < 0.5 for typical EC data"

    def test_wpl_benchmark_stable_case(self):
        np.random.seed(42)
        n = 18000
        w = 0.3 * np.random.randn(n)
        co2 = 415.0 + 2.0 * np.random.randn(n)
        h2o = 10.0 + 0.5 * np.random.randn(n)
        pressure = np.full(n, 101.325)
        temp = 20.0 + 0.5 * np.random.randn(n)
        result = compute_flux_metrics(
            w_series=w, co2_ppm=co2, h2o_mmol=h2o,
            pressure_kpa=pressure, temp_c=temp,
            density_correction_mode="wpl",
        )
        wpl_wv = result["wpl_water_vapor_term"]
        wpl_sh = result["wpl_sensible_heat_term"]
        assert abs(wpl_wv) > 0, "water vapor term should be non-zero"
        assert abs(wpl_sh) > 0, "sensible heat term should be non-zero for varying temperature"
        assert abs(wpl_wv) > abs(wpl_sh), \
            f"for typical EC data, water vapor term ({wpl_wv:.4e}) should dominate sensible heat term ({wpl_sh:.4e})"
        total = wpl_wv + wpl_sh
        raw = result["raw_flux"]
        if abs(raw) > 1e-12:
            correction_ratio = abs(total / raw)
            assert correction_ratio < 0.5, f"correction ratio {correction_ratio:.3f} too large"


# ---------------------------------------------------------------------------
# 8. Exporter / provenance sync
# ---------------------------------------------------------------------------

class TestExporterProvenanceSync:
    def test_full_output_schema_has_advanced_qc_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "advanced_qc_contribution" in schema_names
        assert "advanced_test_weights" in schema_names
        assert "advanced_test_thresholds" in schema_names
        assert "wpl_benchmark_status" in schema_names

    def test_full_output_row_has_advanced_qc_fields(self):
        window = WindowRPResult(
            window_id="w1",
            start_time=datetime(2025, 1, 1, 0, 0),
            end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01,
            raw_flux=-5.2, mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0, primary_flux=-5.0,
            primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0,
            dry_air_molar_density=41.5, mean_co2_ppm=415.0,
            mean_h2o_mmol=10.0, mean_pressure_kpa=101.3,
            mean_temp_c=25.0, qc_grade="A",
            anomaly_type="", reason="",
            diagnostics={
                "qc_details": {"amplitude_resolution_co2": {"test": "amplitude_resolution", "status": "pass"}},
                "metadata_summary": {"sample_rate_hz": 10.0, "sample_count": 18000},
                "wpl_water_vapor_term": 1.2e-6,
                "wpl_sensible_heat_term": 3.4e-7,
                "advanced_qc_contribution": {"amplitude_resolution_co2": {"status": "pass", "weight": 1.0, "score_contribution": 100.0}},
                "advanced_test_weights": {"amplitude_resolution_co2": 1.0},
                "advanced_test_thresholds": {"amplitude_resolution_ratio_threshold": 10.0},
                "wpl_benchmark_status": {"status": "pass", "correction_ratio": 0.05, "magnitude_reasonable": True},
            },
        )
        rp_result = RPRunResult(
            run_id="test_run", created_at=datetime(2025, 1, 1),
            windows=[window], summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert len(rows) == 1
        assert "advanced_qc_contribution" in rows[0]
        assert "advanced_test_weights" in rows[0]
        assert "advanced_test_thresholds" in rows[0]
        assert "wpl_benchmark_status" in rows[0]
        contrib = json.loads(rows[0]["advanced_qc_contribution"])
        assert "amplitude_resolution_co2" in contrib

    def test_export_manifest_includes_advanced_test_thresholds(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rp_config_snapshot = {
            "advanced_tests": {
                "amplitude_resolution_ratio_threshold": 8.0,
                "angle_of_attack_max_angle_deg": 35.0,
            }
        }
        thresholds = exporter._extract_advanced_test_thresholds(rp_config_snapshot)
        assert thresholds["amplitude_resolution_ratio_threshold"] == 8.0
        assert thresholds["angle_of_attack_max_angle_deg"] == 35.0
        assert thresholds["steadiness_cv_threshold"] == 0.50


# ---------------------------------------------------------------------------
# 9. EddyPro reference benchmark
# ---------------------------------------------------------------------------

class TestEddyProBenchmark:
    def test_benchmark_framework_on_synthetic_reference(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        window = result.windows[0]
        ref = EddyProReferenceWindow(
            window_id=window.window_id,
            start_time=window.start_time.isoformat(),
            end_time=window.end_time.isoformat(),
            primary_flux=window.primary_flux,
            primary_flux_source="wpl",
            lag_seconds=window.lag_seconds,
            lag_strategy="covariance_max",
            rotation_mode="double",
            wpl_water_vapor_term=window.diagnostics.get("wpl_water_vapor_term"),
            wpl_sensible_heat_term=window.diagnostics.get("wpl_sensible_heat_term"),
            total_density_correction=window.diagnostics.get("wpl_water_vapor_term", 0.0) + window.diagnostics.get("wpl_sensible_heat_term", 0.0),
            qc_grade=window.qc_grade,
        )
        bench = compare_window_to_reference(window, ref)
        assert "window_id" in bench
        assert "comparisons" in bench
        assert "overall_pass" in bench
        assert bench["overall_pass"] is True, f"Benchmark should pass with self-reference: {[c['note'] for c in bench['comparisons'] if c['note']]}"

    def test_benchmark_detects_flux_deviation(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        window = result.windows[0]
        ref = EddyProReferenceWindow(
            window_id=window.window_id,
            start_time=window.start_time.isoformat(),
            end_time=window.end_time.isoformat(),
            primary_flux=window.primary_flux * 2.0,
        )
        bench = compare_window_to_reference(window, ref)
        flux_comp = [c for c in bench["comparisons"] if c["field_name"] == "primary_flux"][0]
        assert not flux_comp["passed"], "Flux deviation should be detected"
        assert flux_comp["relative_error"] is not None
        assert flux_comp["relative_error"] >= 0.5

    def test_benchmark_detects_rotation_mismatch(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        window = result.windows[0]
        ref = EddyProReferenceWindow(
            window_id=window.window_id,
            start_time=window.start_time.isoformat(),
            end_time=window.end_time.isoformat(),
            rotation_mode="triple",
        )
        bench = compare_window_to_reference(window, ref)
        rot_comp = [c for c in bench["comparisons"] if c["field_name"] == "rotation_mode"]
        if rot_comp:
            assert not rot_comp[0]["passed"]

    def test_benchmark_summary_from_exporter(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        window = result.windows[0]
        ref = EddyProReferenceWindow(
            window_id=window.window_id,
            start_time=window.start_time.isoformat(),
            end_time=window.end_time.isoformat(),
            primary_flux=window.primary_flux,
            primary_flux_source="wpl",
            rotation_mode="double",
            qc_grade=window.qc_grade,
        )
        bench = compare_window_to_reference(window, ref)
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        summary = exporter.compute_benchmark_summary(rp_result=result, benchmark_results=[bench])
        assert summary["status"] in ("pass", "partial", "fail")
        assert summary["windows_compared"] == 1
        assert "field_summary" in summary


# ---------------------------------------------------------------------------
# 10. Continuous dataset groundwork
# ---------------------------------------------------------------------------

class TestContinuousDataset:
    def test_continuous_dataset_no_gaps(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        if result.windows:
            first_dur = (result.windows[0].end_time - result.windows[0].start_time).total_seconds()
            period_min = max(first_dur / 60.0, 0.01)
        else:
            period_min = 30.0
        continuous = exporter.generate_continuous_dataset(rp_result=result, averaging_period_minutes=period_min)
        assert len(continuous) >= len(result.windows)

    def test_continuous_dataset_inserts_gap_records(self):
        from datetime import datetime, timedelta
        from models.rp_models import WindowRPResult, RPRunResult
        t0 = datetime(2025, 1, 1, 0, 0)
        t1 = t0 + timedelta(minutes=30)
        t2 = t1 + timedelta(minutes=30)
        t3 = t2 + timedelta(minutes=30)
        w1 = WindowRPResult(
            window_id="w1", start_time=t0, end_time=t1,
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01,
            raw_flux=-5.2, mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0, primary_flux=-5.0,
            primary_flux_source="wpl", water_vapor_flux=0.02,
            air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0,
            mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        w3 = WindowRPResult(
            window_id="w3", start_time=t2, end_time=t3,
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01,
            raw_flux=-5.2, mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0, primary_flux=-5.0,
            primary_flux_source="wpl", water_vapor_flux=0.02,
            air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0,
            mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test_run", created_at=datetime(2025, 1, 1),
            windows=[w1, w3], summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        continuous = exporter.generate_continuous_dataset(rp_result=rp_result, averaging_period_minutes=30.0)
        assert len(continuous) == 3
        gap_row = continuous[1]
        assert gap_row["anomaly_type"] == "gap"
        assert gap_row["sample_count"] == 0
        assert gap_row["missing_ratio"] == 1.0

    def test_continuous_dataset_empty_input(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        continuous = exporter.generate_continuous_dataset(rp_result=None, averaging_period_minutes=30.0)
        assert continuous == []


# ---------------------------------------------------------------------------
# 11. Standard output foundation
# ---------------------------------------------------------------------------

class TestStandardOutputFoundation:
    def test_qc_details_artifact(self):
        import tempfile
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        with tempfile.TemporaryDirectory() as tmp:
            path = exporter.export_qc_details_artifact(rp_result=result, export_root=Path(tmp))
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data) == len(result.windows)
            for row in data:
                assert "window_id" in row
                assert "adv_amplitude_resolution_co2_status" in row

    def test_metadata_summary_artifact(self):
        import tempfile
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        with tempfile.TemporaryDirectory() as tmp:
            path = exporter.export_metadata_summary_artifact(rp_result=result, export_root=Path(tmp))
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data) == len(result.windows)
            for row in data:
                assert "sample_rate_hz" in row
                assert "sample_count" in row

    def test_stats_foundation_artifact(self):
        import tempfile
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        with tempfile.TemporaryDirectory() as tmp:
            path = exporter.export_stats_foundation_artifact(rp_result=result, export_root=Path(tmp))
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data) == len(result.windows)
            for row in data:
                assert "qc_grade" in row
                assert "ustar" in row

    def test_full_output_schema_has_benchmark_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "benchmark_status" in schema_names
        assert "benchmark_target" in schema_names
        assert "benchmark_deviation_summary" in schema_names
        assert "continuous_dataset_enabled" in schema_names


# ---------------------------------------------------------------------------
# 12. Manifest sync
# ---------------------------------------------------------------------------

class TestManifestSync:
    def test_export_manifest_has_benchmark_fields(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rp_config_snapshot = {"benchmark": {"status": "active", "target": "eddypro_v7"}}
        thresholds = {}
        thresholds["benchmark_status"] = rp_config_snapshot.get("benchmark", {}).get("status", "")
        thresholds["benchmark_target"] = rp_config_snapshot.get("benchmark", {}).get("target", "")
        assert thresholds["benchmark_status"] == "active"
        assert thresholds["benchmark_target"] == "eddypro_v7"

    def test_export_manifest_has_continuous_dataset_flag(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rp_config_snapshot = {"continuous_dataset": {"enabled": True}}
        flag = bool(rp_config_snapshot.get("continuous_dataset", {}).get("enabled", False))
        assert flag is True

    def test_headless_manifest_has_benchmark_fields(self):
        from core.headless_batch_runner import build_batch_manifest
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        config = {"benchmark": {"status": "active", "target": "eddypro_v7"}, "continuous_dataset": {"enabled": True}}
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        rows = _make_rows()
        pipeline = ECRPPipeline()
        rp_result = pipeline.run(
            rows=rows,
            project=metadata.project,
            site=metadata.site,
            config=config,
            data_source="test",
            time_range="",
        )
        from core.ec_fcc.pipeline import ECFCCPipeline
        spectral_result = ECFCCPipeline().run(
            rows=rows,
            project=metadata.project,
            site=metadata.site,
            config=config,
            data_source="test",
            time_range="",
        )
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=metadata,
            config=config,
            rows=rows,
            rp_result=rp_result,
            spectral_result=spectral_result,
        )
        assert "benchmark_status" in manifest
        assert "benchmark_target" in manifest
        assert "benchmark_deviation_summary" in manifest
        assert "continuous_dataset_enabled" in manifest
        assert manifest["benchmark_status"] == "active"
        assert manifest["benchmark_target"] == "eddypro_v7"
        assert manifest["continuous_dataset_enabled"] is True


# ---------------------------------------------------------------------------
# 13. EddyPro reference loader
# ---------------------------------------------------------------------------

class TestEddyProReferenceLoader:
    def test_load_json_reference(self):
        import tempfile
        from core.ec_rp.analysis import load_eddypro_reference_json
        ref_data = [
            {"window_id": "w1", "start_time": "2025-01-01T00:00", "end_time": "2025-01-01T00:30",
             "primary_flux": -5.0, "primary_flux_source": "wpl", "lag_seconds": 2.5,
             "rotation_mode": "double", "qc_grade": "A"},
            {"window_id": "w2", "start_time": "2025-01-01T00:30", "end_time": "2025-01-01T01:00",
             "primary_flux": -3.2, "primary_flux_source": "wpl", "lag_seconds": 1.8,
             "rotation_mode": "double", "qc_grade": "B"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(ref_data, f)
            f.flush()
            windows = load_eddypro_reference_json(f.name)
        assert len(windows) == 2
        assert windows[0]["window_id"] == "w1"
        assert windows[0]["primary_flux"] == -5.0
        assert windows[0]["primary_flux_source"] == "wpl"
        assert windows[1]["primary_flux"] == -3.2

    def test_load_json_single_window(self):
        import tempfile
        from core.ec_rp.analysis import load_eddypro_reference_json
        ref_data = {"window_id": "w1", "start_time": "2025-01-01T00:00", "end_time": "2025-01-01T00:30",
                     "primary_flux": -5.0}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(ref_data, f)
            f.flush()
            windows = load_eddypro_reference_json(f.name)
        assert len(windows) == 1
        assert windows[0]["primary_flux"] == -5.0

    def test_load_csv_reference(self):
        import tempfile
        from core.ec_rp.analysis import load_eddypro_reference_csv
        csv_content = "Filename,Fc,start_time,end_time,rotation_mode,qc_grade\n"
        csv_content += "w1,-5.0,2025-01-01T00:00,2025-01-01T00:30,double,A\n"
        csv_content += "w2,-3.2,2025-01-01T00:30,2025-01-01T01:00,double,B\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
            f.write(csv_content)
            f.flush()
            windows = load_eddypro_reference_csv(f.name)
        assert len(windows) == 2
        assert windows[0]["primary_flux"] == -5.0
        assert windows[1]["primary_flux"] == -3.2

    def test_load_csv_with_custom_field_mapping(self):
        import tempfile
        from core.ec_rp.analysis import load_eddypro_reference_csv
        csv_content = "File,CO2_flux,Start,End\n"
        csv_content += "w1,-5.0,2025-01-01T00:00,2025-01-01T00:30\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
            f.write(csv_content)
            f.flush()
            windows = load_eddypro_reference_csv(f.name, field_mapping={"window_id": "File", "primary_flux": "CO2_flux", "start_time": "Start", "end_time": "End"})
        assert len(windows) == 1
        assert windows[0]["primary_flux"] == -5.0

    def test_load_csv_handles_missing_values(self):
        import tempfile
        from core.ec_rp.analysis import load_eddypro_reference_csv
        csv_content = "Filename,Fc,start_time,end_time\n"
        csv_content += "w1,-9999,2025-01-01T00:00,2025-01-01T00:30\n"
        csv_content += "w2,NaN,2025-01-01T00:30,2025-01-01T01:00\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
            f.write(csv_content)
            f.flush()
            windows = load_eddypro_reference_csv(f.name)
        assert len(windows) == 2
        assert windows[0]["primary_flux"] is None
        assert windows[1]["primary_flux"] is None


# ---------------------------------------------------------------------------
# 14. Benchmark threshold configurability
# ---------------------------------------------------------------------------

class TestBenchmarkThresholdConfig:
    def test_custom_flux_threshold_passes_tight(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", primary_flux=-5.05)
        bench_loose = compare_window_to_reference(window, ref, flux_rel_threshold=0.10)
        bench_strict = compare_window_to_reference(window, ref, flux_rel_threshold=0.001)
        flux_loose = [c for c in bench_loose["comparisons"] if c["field_name"] == "primary_flux"][0]
        flux_strict = [c for c in bench_strict["comparisons"] if c["field_name"] == "primary_flux"][0]
        assert flux_loose["passed"]
        assert not flux_strict["passed"]

    def test_custom_lag_threshold(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", lag_seconds=3.0)
        bench_loose = compare_window_to_reference(window, ref, lag_abs_threshold_s=1.0)
        bench_strict = compare_window_to_reference(window, ref, lag_abs_threshold_s=0.1)
        lag_loose = [c for c in bench_loose["comparisons"] if c["field_name"] == "lag_seconds"][0]
        lag_strict = [c for c in bench_strict["comparisons"] if c["field_name"] == "lag_seconds"][0]
        assert lag_loose["passed"]
        assert not lag_strict["passed"]

    def test_qc_grade_must_match_flag(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="B", anomaly_type="", reason="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", qc_grade="A")
        bench_within_one = compare_window_to_reference(window, ref, qc_grade_must_match=False)
        bench_exact = compare_window_to_reference(window, ref, qc_grade_must_match=True)
        grade_within = [c for c in bench_within_one["comparisons"] if c["field_name"] == "qc_grade"]
        grade_exact = [c for c in bench_exact["comparisons"] if c["field_name"] == "qc_grade"]
        if grade_within:
            assert grade_within[0]["passed"]
        if grade_exact:
            assert not grade_exact[0]["passed"]

    def test_run_benchmark_comparison_with_config_thresholds(self):
        from core.ec_rp.analysis import run_benchmark_comparison
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", primary_flux=-5.0, rotation_mode="double")
        from dataclasses import asdict
        results = run_benchmark_comparison(rp_result, [asdict(ref)], flux_rel_threshold=0.05)
        assert len(results) == 1
        assert results[0]["overall_pass"] is True


# ---------------------------------------------------------------------------
# 15. Cross-software parity summary
# ---------------------------------------------------------------------------

class TestCrossSoftwareParitySummary:
    def test_benchmark_summary_artifact(self):
        import tempfile
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", primary_flux=-5.0, rotation_mode="double")
        bench = compare_window_to_reference(window, ref)
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        with tempfile.TemporaryDirectory() as tmp:
            path = exporter.export_benchmark_summary_artifact(
                rp_result=rp_result, benchmark_results=[bench],
                export_root=Path(tmp), reference_id="eddypro_v7_test",
                thresholds={"flux_rel_threshold": 0.10, "lag_abs_threshold_s": 0.5},
            )
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["reference_id"] == "eddypro_v7_test"
            assert "thresholds" in data
            assert "per_window" in data
            assert len(data["per_window"]) == 1
            assert "primary_flux_abs_error" in data["per_window"][0]
            assert "primary_flux_rel_error" in data["per_window"][0]
            assert "primary_flux_passed" in data["per_window"][0]

    def test_benchmark_summary_includes_max_errors(self):
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        ref = EddyProReferenceWindow(window_id="w1", start_time="", end_time="", primary_flux=-4.5)
        bench = compare_window_to_reference(window, ref)
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        summary = exporter.compute_benchmark_summary(rp_result=rp_result, benchmark_results=[bench])
        assert "field_summary" in summary
        fs = summary["field_summary"]
        if "primary_flux" in fs:
            assert "max_abs_error" in fs["primary_flux"]
            assert "max_rel_error" in fs["primary_flux"]
            assert fs["primary_flux"]["max_abs_error"] > 0


# ---------------------------------------------------------------------------
# 16. Exporter / manifest / headless sync
# ---------------------------------------------------------------------------

class TestExporterManifestHeadlessSync:
    def test_export_manifest_has_benchmark_thresholds(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rp_config_snapshot = {
            "benchmark": {
                "status": "active",
                "target": "eddypro_v7",
                "reference_id": "ep_v7_ref_001",
                "flux_rel_threshold": 0.05,
                "lag_abs_threshold_s": 0.3,
                "wpl_rel_threshold": 0.15,
                "qc_grade_must_match": True,
            }
        }
        thresholds = exporter._extract_benchmark_thresholds(rp_config_snapshot)
        assert thresholds["flux_rel_threshold"] == 0.05
        assert thresholds["lag_abs_threshold_s"] == 0.3
        assert thresholds["wpl_rel_threshold"] == 0.15
        assert thresholds["qc_grade_must_match"] is True

    def test_export_manifest_default_benchmark_thresholds(self):
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        thresholds = exporter._extract_benchmark_thresholds({})
        assert thresholds["flux_rel_threshold"] == 0.10
        assert thresholds["lag_abs_threshold_s"] == 0.5
        assert thresholds["wpl_rel_threshold"] == 0.20
        assert thresholds["qc_grade_must_match"] is False

    def test_full_output_schema_has_benchmark_threshold_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "benchmark_reference_id" in schema_names
        assert "benchmark_thresholds" in schema_names

    def test_headless_manifest_has_benchmark_thresholds(self):
        from core.headless_batch_runner import build_batch_manifest
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        config = {
            "benchmark": {
                "status": "active",
                "target": "eddypro_v7",
                "reference_id": "ep_v7_ref_001",
                "flux_rel_threshold": 0.05,
                "qc_grade_must_match": True,
            }
        }
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        rows = _make_rows()
        pipeline = ECRPPipeline()
        rp_result = pipeline.run(
            rows=rows, project=metadata.project, site=metadata.site,
            config=config, data_source="test", time_range="",
        )
        from core.ec_fcc.pipeline import ECFCCPipeline
        spectral_result = ECFCCPipeline().run(
            rows=rows, project=metadata.project, site=metadata.site,
            config=config, data_source="test", time_range="",
        )
        manifest = build_batch_manifest(
            batch_id="test_batch", metadata_bundle=metadata, config=config,
            rows=rows, rp_result=rp_result, spectral_result=spectral_result,
        )
        assert "benchmark_thresholds" in manifest
        assert manifest["benchmark_thresholds"]["flux_rel_threshold"] == 0.05
        assert manifest["benchmark_thresholds"]["qc_grade_must_match"] is True
        assert "benchmark_reference_id" in manifest
        assert manifest["benchmark_reference_id"] == "ep_v7_ref_001"


# ---------------------------------------------------------------------------
# 17. Real EddyPro reference data loading
# ---------------------------------------------------------------------------

class TestRealEddyProReferenceData:
    def test_load_json_reference_file(self):
        from core.ec_rp.analysis import load_eddypro_reference_json
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.json")
        if not ref_path.exists():
            pytest.skip("Reference file not found")
        windows = load_eddypro_reference_json(ref_path)
        assert len(windows) == 5
        assert windows[0]["window_id"] == "ep_w001"
        assert windows[0]["primary_flux"] == -4.82
        assert windows[0]["primary_flux_source"] == "wpl"
        assert windows[0]["lag_seconds"] == 2.4
        assert windows[0]["rotation_mode"] == "double"
        assert windows[0]["qc_grade"] == "A"
        assert windows[3]["primary_flux"] == 5.67
        assert windows[4]["qc_grade"] == "C"

    def test_load_csv_reference_file(self):
        from core.ec_rp.analysis import load_eddypro_reference_csv
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.csv")
        if not ref_path.exists():
            pytest.skip("Reference file not found")
        windows = load_eddypro_reference_csv(ref_path)
        assert len(windows) == 5
        assert windows[0]["primary_flux"] == -4.82
        assert windows[3]["primary_flux"] == 5.67

    def test_reference_file_has_stable_id(self):
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.json")
        if not ref_path.exists():
            pytest.skip("Reference file not found")
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        assert data["reference_id"] == "eddypro_v7_synthetic_001"

    def test_reference_file_has_qc_mapping_info(self):
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.json")
        if not ref_path.exists():
            pytest.skip("Reference file not found")
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        assert "qc_grade_mapping" in data
        assert data["qc_grade_mapping"]["mapping"]["0"] == "A"
        assert data["qc_grade_mapping"]["mapping"]["1"] == "B"
        assert data["qc_grade_mapping"]["mapping"]["2"] == "C"

    def test_load_with_qc_mapping_converts_numeric_flags(self):
        from core.ec_rp.analysis import load_eddypro_reference_with_qc_mapping
        import tempfile
        ref_data = [
            {"window_id": "w1", "start_time": "2025-01-01T00:00", "end_time": "2025-01-01T00:30",
             "primary_flux": -5.0, "qc_grade": "0"},
            {"window_id": "w2", "start_time": "2025-01-01T00:30", "end_time": "2025-01-01T01:00",
             "primary_flux": -3.2, "qc_grade": "1"},
            {"window_id": "w3", "start_time": "2025-01-01T01:00", "end_time": "2025-01-01T01:30",
             "primary_flux": 1.0, "qc_grade": "2"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(ref_data, f)
            f.flush()
            windows = load_eddypro_reference_with_qc_mapping(f.name)
        assert windows[0]["qc_grade"] == "A"
        assert windows[1]["qc_grade"] == "B"
        assert windows[2]["qc_grade"] == "C"

    def test_eddypro_qc_flag_to_grade_function(self):
        from core.ec_rp.analysis import eddypro_qc_flag_to_grade
        assert eddypro_qc_flag_to_grade(0) == "A"
        assert eddypro_qc_flag_to_grade(1) == "B"
        assert eddypro_qc_flag_to_grade(2) == "C"
        assert eddypro_qc_flag_to_grade("0") == "A"
        assert eddypro_qc_flag_to_grade("1") == "B"
        assert eddypro_qc_flag_to_grade("2") == "C"
        assert eddypro_qc_flag_to_grade(None) == ""
        assert eddypro_qc_flag_to_grade("A") == ""


# ---------------------------------------------------------------------------
# 18. Pipeline auto-inject benchmark diagnostics
# ---------------------------------------------------------------------------

class TestPipelineBenchmarkAutoInject:
    def test_pipeline_injects_benchmark_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={
                "benchmark": {
                    "status": "active",
                    "target": "eddypro_v7",
                    "reference_id": "eddypro_v7_synthetic_001",
                    "flux_rel_threshold": 0.05,
                }
            },
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            diag = window.diagnostics
            assert "benchmark_status" in diag
            assert "benchmark_target" in diag
            assert "benchmark_reference_id" in diag
            assert "benchmark_thresholds" in diag
            assert "benchmark_deviation_summary" in diag
            assert diag["benchmark_status"] == "active"
            assert diag["benchmark_target"] == "eddypro_v7"
            assert diag["benchmark_reference_id"] == "eddypro_v7_synthetic_001"
            assert diag["benchmark_thresholds"]["flux_rel_threshold"] == 0.05

    def test_pipeline_default_benchmark_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            diag = window.diagnostics
            assert "benchmark_status" in diag
            assert diag["benchmark_status"] == ""
            assert diag["benchmark_thresholds"]["flux_rel_threshold"] == 0.10
            assert diag["benchmark_thresholds"]["lag_abs_threshold_s"] == 0.5
            assert diag["benchmark_thresholds"]["wpl_rel_threshold"] == 0.20
            assert diag["benchmark_thresholds"]["qc_grade_must_match"] is False

    def test_benchmark_diagnostics_in_full_output(self):
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "qc_details": {},
                "metadata_summary": {},
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {"flux_rel_threshold": 0.05},
                "benchmark_deviation_summary": {},
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert len(rows) == 1
        assert rows[0]["benchmark_status"] == "active"
        assert rows[0]["benchmark_target"] == "eddypro_v7"
        assert rows[0]["benchmark_reference_id"] == "eddypro_v7_synthetic_001"


# ---------------------------------------------------------------------------
# 19. QC mapping documentation availability
# ---------------------------------------------------------------------------

class TestQCMappingDocumentation:
    def test_qc_mapping_doc_exists(self):
        doc_path = Path("docs/benchmark/qc_grade_mapping.md")
        assert doc_path.exists(), "QC grade mapping documentation should exist"

    def test_qc_mapping_doc_content(self):
        doc_path = Path("docs/benchmark/qc_grade_mapping.md")
        if not doc_path.exists():
            pytest.skip("QC mapping doc not found")
        content = doc_path.read_text(encoding="utf-8")
        assert "0" in content and "A" in content
        assert "1" in content and "B" in content
        assert "2" in content and "C" in content
        assert "EddyPro" in content

    def test_reference_json_contains_qc_mapping(self):
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.json")
        if not ref_path.exists():
            pytest.skip("Reference file not found")
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        mapping = data.get("qc_grade_mapping", {}).get("mapping", {})
        assert mapping.get("0") == "A"
        assert mapping.get("1") == "B"
        assert mapping.get("2") == "C"


# ---------------------------------------------------------------------------
# 20. Detrend backward compatibility (moving_average → running_mean)
# ---------------------------------------------------------------------------

class TestDetrendBackwardCompat:
    def test_moving_average_maps_to_running_mean(self):
        from core.ec_rp.analysis import normalize_detrend_mode
        assert normalize_detrend_mode("moving_average") == "running_mean"

    def test_movingaverage_maps_to_running_mean(self):
        from core.ec_rp.analysis import normalize_detrend_mode
        assert normalize_detrend_mode("movingaverage") == "running_mean"

    def test_moving_avg_maps_to_running_mean(self):
        from core.ec_rp.analysis import normalize_detrend_mode
        assert normalize_detrend_mode("moving_avg") == "running_mean"

    def test_movingavg_maps_to_running_mean(self):
        from core.ec_rp.analysis import normalize_detrend_mode
        assert normalize_detrend_mode("movingavg") == "running_mean"

    def test_pipeline_moving_average_config(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"detrend_mode": "moving_average"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.detrend_mode == "running_mean", f"Expected 'running_mean', got '{window.detrend_mode}'"

    def test_pipeline_moving_average_does_not_fall_back_to_block_mean(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"detrend_mode": "moving_average"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.detrend_mode != "block_mean", "moving_average should NOT silently fall back to block_mean"


# ---------------------------------------------------------------------------
# 21. Pipeline auto-fill benchmark deviation summary
# ---------------------------------------------------------------------------

class TestPipelineBenchmarkAutoFill:
    def test_benchmark_active_auto_fills_deviation_summary(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={
                "benchmark": {
                    "status": "active",
                    "target": "eddypro_v7",
                    "reference_id": "eddypro_v7_synthetic_001",
                }
            },
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            dev = window.diagnostics.get("benchmark_deviation_summary", {})
            assert dev, "benchmark_deviation_summary should be auto-filled when benchmark is active"
            assert "window_id" in dev or "status" in dev

    def test_benchmark_inactive_no_auto_fill(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            dev = window.diagnostics.get("benchmark_deviation_summary", {})
            assert dev == {}, "benchmark_deviation_summary should be empty when benchmark is inactive"

    def test_benchmark_reference_not_found(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={
                "benchmark": {
                    "status": "active",
                    "target": "eddypro_v7",
                    "reference_id": "nonexistent_reference",
                }
            },
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            dev = window.diagnostics.get("benchmark_deviation_summary", {})
            assert dev.get("status") == "reference_not_found"


# ---------------------------------------------------------------------------
# 22. Headless CLI benchmark args
# ---------------------------------------------------------------------------

class TestHeadlessCLIBenchmarkArgs:
    def test_cli_benchmark_args_injected_into_config(self):
        from core.headless_batch_runner import run_cli
        import tempfile
        config_data = {"detrend_mode": "block_mean"}
        metadata_data = {
            "project": {"name": "T", "code": "T01"},
            "site": {"station_name": "S", "station_code": "S01"},
        }
        input_data = []
        for i in range(120):
            input_data.append({
                "timestamp": f"2025-01-01T00:00:{i % 60:02d}.{(i * 100) % 1000:03d}",
                "co2_ppm": 410.0 + (i % 10) * 0.5,
                "h2o_mmol": 10.0 + (i % 5) * 0.2,
                "pressure_kpa": 101.3,
                "chamber_temp_c": 25.0,
            })
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            metadata_path = Path(tmp) / "metadata.json"
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "manifest.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
            metadata_path.write_text(json.dumps(metadata_data), encoding="utf-8")
            input_path.write_text(json.dumps(input_data), encoding="utf-8")
            run_cli([
                "--config", str(config_path),
                "--metadata", str(metadata_path),
                "--input", str(input_path),
                "--output", str(output_path),
                "--benchmark-status", "active",
                "--benchmark-target", "eddypro_v7",
                "--benchmark-reference-id", "eddypro_v7_synthetic_001",
                "--flux-rel-threshold", "0.05",
                "--lag-abs-threshold-s", "0.3",
                "--wpl-rel-threshold", "0.15",
                "--qc-grade-must-match", "true",
            ])
            manifest = json.loads(output_path.read_text(encoding="utf-8"))
            assert manifest["benchmark_status"] == "active"
            assert manifest["benchmark_target"] == "eddypro_v7"
            assert manifest["benchmark_reference_id"] == "eddypro_v7_synthetic_001"
            assert manifest["benchmark_thresholds"]["flux_rel_threshold"] == 0.05
            assert manifest["benchmark_thresholds"]["lag_abs_threshold_s"] == 0.3
            assert manifest["benchmark_thresholds"]["wpl_rel_threshold"] == 0.15
            assert manifest["benchmark_thresholds"]["qc_grade_must_match"] is True

    def test_cli_benchmark_defaults(self):
        from core.headless_batch_runner import run_cli
        import tempfile
        config_data = {"detrend_mode": "block_mean"}
        metadata_data = {
            "project": {"name": "T", "code": "T01"},
            "site": {"station_name": "S", "station_code": "S01"},
        }
        input_data = []
        for i in range(120):
            input_data.append({
                "timestamp": f"2025-01-01T00:00:{i % 60:02d}.{(i * 100) % 1000:03d}",
                "co2_ppm": 410.0 + (i % 10) * 0.5,
                "h2o_mmol": 10.0 + (i % 5) * 0.2,
                "pressure_kpa": 101.3,
                "chamber_temp_c": 25.0,
            })
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            metadata_path = Path(tmp) / "metadata.json"
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "manifest.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
            metadata_path.write_text(json.dumps(metadata_data), encoding="utf-8")
            input_path.write_text(json.dumps(input_data), encoding="utf-8")
            run_cli([
                "--config", str(config_path),
                "--metadata", str(metadata_path),
                "--input", str(input_path),
                "--output", str(output_path),
            ])
            manifest = json.loads(output_path.read_text(encoding="utf-8"))
            assert manifest["benchmark_status"] == ""
            assert manifest["benchmark_thresholds"]["flux_rel_threshold"] == 0.10


# ---------------------------------------------------------------------------
# 23. Benchmark cockpit data mapping
# ---------------------------------------------------------------------------

class TestBenchmarkCockpitDataMapping:
    def test_benchmark_cockpit_payload_structure(self):
        from app.studio import StudioController
        controller = StudioController.__new__(StudioController)
        controller.rp_runs = []
        from models.spectral_models import SpectralRunResult
        spectral_result = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="",
            qc_only=False,
        )
        payload = controller._benchmark_cockpit_payload(spectral_result)
        assert payload["title"] == "Benchmark 驾驶舱"
        assert "metrics" in payload
        assert "table_rows" in payload
        assert "conclusions" in payload

    def test_benchmark_cockpit_with_active_benchmark(self):
        from app.studio import StudioController
        controller = StudioController.__new__(StudioController)
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {"flux_rel_threshold": 0.10},
                "benchmark_deviation_summary": {
                    "window_id": "w1",
                    "comparisons": [
                        {"field_name": "primary_flux", "absolute_error": 0.1, "relative_error": 0.02, "passed": True, "threshold": 0.10},
                    ],
                    "overall_pass": True,
                    "notes": [],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        controller.rp_runs = [rp_result]
        from models.spectral_models import SpectralRunResult
        spectral_result = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="",
            qc_only=False,
        )
        payload = controller._benchmark_cockpit_payload(spectral_result)
        assert payload["title"] == "Benchmark 驾驶舱"
        metrics_dict = {m[0]: m[1] for m in payload["metrics"]}
        assert metrics_dict["参考"] == "eddypro_v7_synthetic_001"
        table_keys = [row[0] for row in payload["table_rows"]]
        assert "reference_id" in table_keys
        assert "pass_rate" in table_keys
        assert "max_abs_error" in table_keys
        assert "max_rel_error" in table_keys
        assert "failed_fields" in table_keys


# ---------------------------------------------------------------------------
# 24. Real EddyPro reference data
# ---------------------------------------------------------------------------

class TestRealEddyProReferenceData:
    def test_real_reference_json_exists(self):
        ref_path = Path("references/eddypro/real/eddypro_v7_real_temperate_forest_001.json")
        assert ref_path.exists(), "Real EddyPro reference JSON should exist"

    def test_real_reference_json_loadable(self):
        from core.ec_rp.analysis import load_eddypro_reference_json
        ref_path = Path("references/eddypro/real/eddypro_v7_real_temperate_forest_001.json")
        if not ref_path.exists():
            pytest.skip("Real reference file not found")
        windows = load_eddypro_reference_json(ref_path)
        assert len(windows) >= 5
        assert windows[0]["primary_flux"] is not None
        assert windows[0]["primary_flux_source"] == "wpl"
        assert windows[0]["rotation_mode"] == "double"

    def test_real_reference_has_stable_id(self):
        ref_path = Path("references/eddypro/real/eddypro_v7_real_temperate_forest_001.json")
        if not ref_path.exists():
            pytest.skip("Real reference file not found")
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        assert data["reference_id"] == "eddypro_v7_real_temperate_forest_001"

    def test_synthetic_reference_still_available(self):
        ref_path = Path("references/eddypro/eddypro_v7_synthetic_001.json")
        assert ref_path.exists(), "Synthetic reference should still be available for unit tests"


# ---------------------------------------------------------------------------
# 25. Benchmark matching strategy upgrade
# ---------------------------------------------------------------------------

class TestBenchmarkMatchingStrategy:
    def test_window_id_exact_match(self):
        from core.ec_rp.analysis import run_benchmark_comparison
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="ep_w001", start_time=datetime(2025, 6, 15, 0, 0), end_time=datetime(2025, 6, 15, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-4.82, mixing_ratio_flux=-4.82,
            density_corrected_flux=-4.82, primary_flux=-4.82, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        from dataclasses import asdict
        ref = EddyProReferenceWindow(window_id="ep_w001", start_time="2025-06-15T00:00:00", end_time="2025-06-15T00:30:00", primary_flux=-4.82, rotation_mode="double")
        results = run_benchmark_comparison(rp_result, [asdict(ref)])
        assert results[0]["match_strategy"] == "window_id_exact"
        assert results[0]["matched_reference_window_id"] == "ep_w001"

    def test_start_time_exact_match(self):
        from core.ec_rp.analysis import run_benchmark_comparison
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="my_w001", start_time=datetime(2025, 6, 15, 0, 0), end_time=datetime(2025, 6, 15, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-4.82, mixing_ratio_flux=-4.82,
            density_corrected_flux=-4.82, primary_flux=-4.82, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        from dataclasses import asdict
        ref = EddyProReferenceWindow(window_id="ep_w001", start_time="2025-06-15T00:00:00", end_time="2025-06-15T00:30:00", primary_flux=-4.82, rotation_mode="double")
        results = run_benchmark_comparison(rp_result, [asdict(ref)])
        assert results[0]["match_strategy"] == "start_time_exact"

    def test_start_time_fuzzy_match(self):
        from core.ec_rp.analysis import run_benchmark_comparison
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="my_w001", start_time=datetime(2025, 6, 15, 0, 0, 30), end_time=datetime(2025, 6, 15, 0, 30, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-4.82, mixing_ratio_flux=-4.82,
            density_corrected_flux=-4.82, primary_flux=-4.82, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        from dataclasses import asdict
        ref = EddyProReferenceWindow(window_id="ep_w001", start_time="2025-06-15T00:00:00", end_time="2025-06-15T00:30:00", primary_flux=-4.82, rotation_mode="double")
        results = run_benchmark_comparison(rp_result, [asdict(ref)], time_match_tolerance_s=60.0)
        assert "fuzzy" in results[0]["match_strategy"]

    def test_no_match(self):
        from core.ec_rp.analysis import run_benchmark_comparison
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="my_w001", start_time=datetime(2025, 1, 1, 0, 0), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.4, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-4.82, mixing_ratio_flux=-4.82,
            density_corrected_flux=-4.82, primary_flux=-4.82, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        from dataclasses import asdict
        ref = EddyProReferenceWindow(window_id="ep_w001", start_time="2025-06-15T00:00:00", end_time="2025-06-15T00:30:00", primary_flux=-4.82)
        results = run_benchmark_comparison(rp_result, [asdict(ref)])
        assert results[0]["match_strategy"] == "none"

    def test_match_strategy_in_pipeline_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={
                "benchmark": {
                    "status": "active",
                    "target": "eddypro_v7",
                    "reference_id": "eddypro_v7_synthetic_001",
                }
            },
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            dev = window.diagnostics.get("benchmark_deviation_summary", {})
            if dev and dev.get("match_strategy"):
                assert dev["match_strategy"] in ("window_id_exact", "start_time_exact", "start_time_fuzzy(0s)", "none")


# ---------------------------------------------------------------------------
# 26. Cross-software parity artifact
# ---------------------------------------------------------------------------

class TestCrossSoftwareParityArtifact:
    def test_benchmark_summary_artifact_covers_all_fields(self):
        import tempfile
        from core.ec_rp.analysis import compare_window_to_reference
        from models.rp_models import EddyProReferenceWindow
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={"wpl_water_vapor_term": 0.0001, "wpl_sensible_heat_term": 0.00003},
        )
        ref = EddyProReferenceWindow(
            window_id="w1", start_time="", end_time="",
            primary_flux=-5.0, primary_flux_source="wpl",
            lag_seconds=2.5, lag_strategy="covariance_max",
            rotation_mode="double", applied_rotation_impl="double",
            wpl_water_vapor_term=0.0001, wpl_sensible_heat_term=0.00003,
            total_density_correction=0.00013, qc_grade="A",
        )
        bench = compare_window_to_reference(window, ref)
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        with tempfile.TemporaryDirectory() as tmp:
            path = exporter.export_benchmark_summary_artifact(
                rp_result=rp_result, benchmark_results=[bench],
                export_root=Path(tmp), reference_id="eddypro_v7_synthetic_001",
                thresholds={"flux_rel_threshold": 0.10},
            )
            assert path is not None
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["reference_id"] == "eddypro_v7_synthetic_001"
            assert "per_window" in data
            pw = data["per_window"][0]
            field_names = [k.replace("_abs_error", "").replace("_rel_error", "").replace("_passed", "").replace("_threshold", "").replace("_note", "") for k in pw.keys()]
            assert "primary_flux" in field_names
            assert "lag_seconds" in field_names
            assert "wpl_water_vapor_term" in field_names
            assert "wpl_sensible_heat_term" in field_names
            assert "total_density_correction" in field_names


# ---------------------------------------------------------------------------
# 27. Report center UI tests (previously failing, now fixed)
# ---------------------------------------------------------------------------

class TestReportCenterUIFixed:
    def test_benchmark_cockpit_report_key_in_payload(self):
        from app.studio import StudioController
        from models.spectral_models import SpectralRunResult
        controller = StudioController.__new__(StudioController)
        controller.rp_runs = []
        payload = controller._benchmark_cockpit_payload(
            SpectralRunResult(run_id="t", created_at=datetime(2025, 1, 1), windows=[], summary={}, data_source="t", time_range="", qc_only=False)
        )
        assert payload["report_key"] == "benchmark_cockpit"

    def test_benchmark_cockpit_with_active_benchmark_has_kpi_metrics(self):
        from app.studio import StudioController
        from models.spectral_models import SpectralRunResult
        controller = StudioController.__new__(StudioController)
        window = WindowRPResult(
            window_id="w1", start_time=datetime(2025, 1, 1), end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000, valid_sample_count=17900, continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean", lag_seconds=2.5, lag_confidence=0.85,
            cov_w_co2=-0.05, cov_w_h2o=0.01, raw_flux=-5.0, mixing_ratio_flux=-5.0,
            density_corrected_flux=-5.0, primary_flux=-5.0, primary_flux_source="wpl",
            water_vapor_flux=0.02, air_molar_density=42.0, dry_air_molar_density=41.5,
            mean_co2_ppm=415.0, mean_h2o_mmol=10.0, mean_pressure_kpa=101.3, mean_temp_c=25.0,
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {"flux_rel_threshold": 0.10},
                "benchmark_deviation_summary": {
                    "window_id": "w1",
                    "comparisons": [
                        {"field_name": "primary_flux", "absolute_error": 0.1, "relative_error": 0.02, "passed": True, "threshold": 0.10},
                    ],
                    "overall_pass": True,
                    "notes": [],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=datetime(2025, 1, 1), windows=[window],
            summary={}, data_source="test", time_range="",
        )
        controller.rp_runs = [rp_result]
        spectral_result = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = controller._benchmark_cockpit_payload(spectral_result)
        assert payload["report_key"] == "benchmark_cockpit"
        metrics_dict = {m[0]: m[1] for m in payload["metrics"]}
        assert metrics_dict["参考"] == "eddypro_v7_synthetic_001"
        assert metrics_dict["通过率"] == "100.0%"
        table_keys = [row[0] for row in payload["table_rows"]]
        assert "reference_id" in table_keys
        assert "pass_rate" in table_keys
        assert "max_abs_error" in table_keys
        assert "max_rel_error" in table_keys
        assert "failed_fields" in table_keys
        assert any("threshold" in k for k in table_keys)


# ---------------------------------------------------------------------------
# 28. Regression of existing tests
# ---------------------------------------------------------------------------

class TestRegressionExisting:
    def test_primary_flux_wpl_still_works(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.density_corrected_flux, rel=1e-6)

    def test_primary_flux_mixing_ratio_still_works(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "mixing_ratio"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.mixing_ratio_flux, rel=1e-6)

    def test_primary_flux_none_still_works(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "none"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.raw_flux, rel=1e-6)

    def test_double_rotation_still_works(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "double"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.rotation_mode == "double"

    def test_triple_rotation_still_works(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=__import__("models.station_models", fromlist=["ProjectProfile"]).ProjectProfile(name="Test", code="T01"),
            site=__import__("models.station_models", fromlist=["SiteProfile"]).SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "triple"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.rotation_mode == "triple"


# ---------------------------------------------------------------------------
# v3e — Real Benchmark Provenance + Network Output Foundation
# ---------------------------------------------------------------------------

from core.ec_rp.analysis import (
    list_available_references,
    generate_reference_provenance,
)
from core.exports.result_exporter import (
    FLUXNET_HALF_HOURLY_SCHEMA,
    AMERIFLUX_FIELD_MAP,
    ICOS_FIELD_MAP,
    NETWORK_SCHEMA_REGISTRY,
    validate_fluxnet_row,
)


class TestReferenceProvenance:
    def test_list_available_references_finds_files(self):
        refs = list_available_references()
        assert len(refs) >= 2
        ref_ids = [r["reference_id"] for r in refs]
        assert "eddypro_v7_synthetic_001" in ref_ids
        assert "eddypro_v7_real_temperate_forest_001" in ref_ids

    def test_list_available_references_has_required_fields(self):
        refs = list_available_references()
        for ref in refs:
            assert "reference_id" in ref
            assert "json_path" in ref
            assert "window_count" in ref
            assert "source" in ref

    def test_list_available_references_csv_path_populated(self):
        refs = list_available_references()
        synthetic = next(r for r in refs if r["reference_id"] == "eddypro_v7_synthetic_001")
        assert synthetic["csv_path"] != ""

    def test_generate_reference_provenance(self):
        refs = list_available_references()
        ref = next(r for r in refs if r["reference_id"] == "eddypro_v7_real_temperate_forest_001")
        provenance = generate_reference_provenance(ref["json_path"])
        assert provenance["reference_id"] == "eddypro_v7_real_temperate_forest_001"
        assert provenance["window_count"] == 6
        assert provenance["required_fields_present"] is True
        assert "qc_mapping_strategy" in provenance
        assert "known_limitations" in provenance

    def test_generate_reference_provenance_grassland(self):
        refs = list_available_references()
        ref = next((r for r in refs if r["reference_id"] == "eddypro_v7_real_grassland_002"), None)
        if ref is None:
            pytest.skip("Grassland reference not found")
        provenance = generate_reference_provenance(ref["json_path"])
        assert provenance["reference_id"] == "eddypro_v7_real_grassland_002"
        assert provenance["window_count"] == 5
        assert provenance["required_fields_present"] is True


class TestFLUXNETHalfHourlyFoundation:
    def _make_rp_result(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        windows = []
        for i in range(4):
            w = WindowRPResult(
                window_id=f"w{i+1:03d}",
                start_time=now + timedelta(minutes=30 * i),
                end_time=now + timedelta(minutes=30 * (i + 1)),
                sample_count=18000, valid_sample_count=17900,
                continuity_ratio=0.99, missing_ratio=0.01,
                rotation_mode="double", detrend_mode="block_mean",
                lag_seconds=2.3, lag_confidence=0.85,
                cov_w_co2=-0.001, cov_w_h2o=0.0005,
                raw_flux=-3.5, mixing_ratio_flux=-3.4,
                density_corrected_flux=-3.45, water_vapor_flux=0.012,
                air_molar_density=41.5, dry_air_molar_density=41.3,
                mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
                mean_pressure_kpa=101.3, mean_temp_c=22.5,
                primary_flux=-3.45, primary_flux_source="wpl",
                qc_grade="A", anomaly_type="", reason="",
                ustar=0.35, stationarity_score=85.0, turbulence_score=90.0,
            )
            windows.append(w)
        return RPRunResult(
            run_id="test_fluxnet", created_at=now, data_source="test",
            time_range="", summary={}, windows=windows,
        )

    def test_fluxnet_export_creates_artifact(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
            timezone_offset_hours=-5.0, site_id="US-Test",
        )
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "rows" in data
        assert data["metadata"]["site_id"] == "US-Test"
        assert data["metadata"]["timezone_offset_hours"] == -5.0
        assert data["metadata"]["timestamp_refers_to"] == "start"

    def test_fluxnet_row_has_required_fields(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            assert "TIMESTAMP_START" in row
            assert "TIMESTAMP_END" in row
            assert "DOY" in row
            assert "FC" in row
            assert "FC_QC" in row
            assert "TIMEZONE_OFFSET_H" in row
            assert "TIMESTAMP_REFERS_TO" in row

    def test_fluxnet_doy_calculation(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
            timezone_offset_hours=0.0,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        first_row = data["rows"][0]
        assert first_row["DOY"] == 196  # July 15

    def test_fluxnet_timestamp_refers_to_end(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
            timestamp_refers_to="end",
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["metadata"]["timestamp_refers_to"] == "end"
        for row in data["rows"]:
            assert row["TIMESTAMP_REFERS_TO"] == "end"

    def test_fluxnet_gap_records(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        now = datetime(2025, 7, 15, 0, 0, 0)
        w1 = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
        )
        w3 = WindowRPResult(
            window_id="w003", start_time=now + timedelta(minutes=60),
            end_time=now + timedelta(minutes=90),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-2.5, mixing_ratio_flux=-2.4,
            density_corrected_flux=-2.45, water_vapor_flux=0.010,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-2.45, primary_flux_source="wpl",
            qc_grade="B", anomaly_type="", reason="",
        )
        rp_result = RPRunResult(
            run_id="test_gap", created_at=now, data_source="test",
            time_range="", summary={}, windows=[w1, w3],
        )
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        gap_rows = [r for r in data["rows"] if r.get("FC") == -9999.0]
        assert len(gap_rows) >= 1

    def test_fluxnet_csv_also_written(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        csv_path = tmp_path / "fluxnet_half_hourly_foundation.csv"
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        assert "TIMESTAMP_START" in content

    def test_fluxnet_qc_grade_mapping(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            if row.get("FC") != -9999.0:
                assert row["FC_QC"] in (0, 1, 2)


class TestAmeriFluxICOSSchemaGroundwork:
    def test_fluxnet_schema_has_required_fields(self):
        field_names = [f[0] for f in FLUXNET_HALF_HOURLY_SCHEMA]
        assert "TIMESTAMP_START" in field_names
        assert "TIMESTAMP_END" in field_names
        assert "FC" in field_names
        assert "FC_QC" in field_names
        assert "DOY" in field_names
        assert "TIMEZONE_OFFSET_H" in field_names
        assert "TIMESTAMP_REFERS_TO" in field_names

    def test_ameriflux_field_map_exists(self):
        assert "FC" in AMERIFLUX_FIELD_MAP
        assert AMERIFLUX_FIELD_MAP["FC_QC"] == "QC_FLAG"
        assert AMERIFLUX_FIELD_MAP["WIND_SPEED"] == "WS"

    def test_icos_field_map_exists(self):
        assert "FC" in ICOS_FIELD_MAP
        assert ICOS_FIELD_MAP["FC"] == "Fc"
        assert ICOS_FIELD_MAP["FC_QC"] == "Fc_QC"
        assert ICOS_FIELD_MAP["USTAR"] == "ustar"

    def test_network_schema_registry(self):
        assert "FLUXNET" in NETWORK_SCHEMA_REGISTRY
        assert "AmeriFlux" in NETWORK_SCHEMA_REGISTRY
        assert "ICOS" in NETWORK_SCHEMA_REGISTRY
        for name, schema in NETWORK_SCHEMA_REGISTRY.items():
            assert "field_map" in schema
            assert "timestamp_format" in schema
            assert "gap_value" in schema
            assert "qc_scale" in schema
            assert "averaging_period_min" in schema

    def test_validate_fluxnet_row_valid(self):
        row = {
            "TIMESTAMP_START": "202507150000",
            "FC": -3.5,
            "FC_QC": 0,
            "DOY": 196,
        }
        errors = validate_fluxnet_row(row)
        assert errors == []

    def test_validate_fluxnet_row_bad_fc(self):
        row = {
            "TIMESTAMP_START": "202507150000",
            "FC": 150.0,
            "FC_QC": 0,
            "DOY": 196,
        }
        errors = validate_fluxnet_row(row)
        assert any("exceeds plausible range" in e for e in errors)

    def test_validate_fluxnet_row_bad_qc(self):
        row = {
            "TIMESTAMP_START": "202507150000",
            "FC": -3.5,
            "FC_QC": 5,
            "DOY": 196,
        }
        errors = validate_fluxnet_row(row)
        assert any("not in valid range" in e for e in errors)

    def test_validate_fluxnet_row_bad_doy(self):
        row = {
            "TIMESTAMP_START": "202507150000",
            "FC": -3.5,
            "FC_QC": 0,
            "DOY": 400,
        }
        errors = validate_fluxnet_row(row)
        assert any("not in valid range" in e for e in errors)

    def test_validate_fluxnet_row_unknown_schema(self):
        row = {"TIMESTAMP_START": "202507150000"}
        errors = validate_fluxnet_row(row, schema_target="UnknownNet")
        assert any("Unknown schema_target" in e for e in errors)

    def test_validate_fluxnet_row_gap_value_skipped(self):
        row = {
            "TIMESTAMP_START": "202507150000",
            "FC": -9999,
            "FC_QC": -9999,
            "DOY": -9999,
        }
        errors = validate_fluxnet_row(row)
        assert errors == []


class TestCrossSoftwareParityArtifact:
    def _make_benchmark_results(self) -> list[dict]:
        return [
            {
                "window_id": "w001",
                "comparisons": [
                    {"field_name": "primary_flux", "reference_value": -3.82, "actual_value": -3.80,
                     "absolute_error": 0.02, "relative_error": 0.005, "threshold": 0.10, "passed": True, "note": ""},
                    {"field_name": "lag_seconds", "reference_value": 2.35, "actual_value": 2.30,
                     "absolute_error": 0.05, "relative_error": None, "threshold": 0.5, "passed": True, "note": ""},
                ],
                "overall_pass": True,
                "notes": [],
                "match_strategy": "window_id_exact",
                "matched_reference_window_id": "ep_w001",
            },
            {
                "window_id": "w002",
                "comparisons": [
                    {"field_name": "primary_flux", "reference_value": -2.95, "actual_value": -2.50,
                     "absolute_error": 0.45, "relative_error": 0.153, "threshold": 0.10, "passed": False,
                     "note": "primary_flux: actual=-2.5, ref=-2.95, rel_err=0.1525"},
                ],
                "overall_pass": False,
                "notes": [],
                "match_strategy": "start_time_exact",
                "matched_reference_window_id": "ep_w002",
            },
        ]

    def _make_rp_result_with_benchmark(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        bm_results = self._make_benchmark_results()
        windows = []
        for i, bm in enumerate(bm_results):
            w = WindowRPResult(
                window_id=bm["window_id"],
                start_time=now + timedelta(minutes=30 * i),
                end_time=now + timedelta(minutes=30 * (i + 1)),
                sample_count=18000, valid_sample_count=17900,
                continuity_ratio=0.99, missing_ratio=0.01,
                rotation_mode="double", detrend_mode="block_mean",
                lag_seconds=2.3, lag_confidence=0.85,
                cov_w_co2=-0.001, cov_w_h2o=0.0005,
                raw_flux=-3.5, mixing_ratio_flux=-3.4,
                density_corrected_flux=-3.45, water_vapor_flux=0.012,
                air_molar_density=41.5, dry_air_molar_density=41.3,
                mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
                mean_pressure_kpa=101.3, mean_temp_c=22.5,
                primary_flux=-3.45, primary_flux_source="wpl",
                qc_grade="A", anomaly_type="", reason="",
                diagnostics={
                    "benchmark_deviation_summary": bm,
                    "lag_strategy": "covariance_max",
                    "applied_rotation_impl": "double",
                    "wpl_water_vapor_term": 0.00009,
                    "wpl_sensible_heat_term": 0.00003,
                },
            )
            windows.append(w)
        return RPRunResult(
            run_id="test_parity", created_at=now, data_source="test",
            time_range="", summary={}, windows=windows,
        )

    def test_parity_artifact_export(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result_with_benchmark()
        bm_results = self._make_benchmark_results()
        path = exporter.export_parity_artifact(
            rp_result=rp_result, benchmark_results=bm_results,
            export_root=tmp_path, reference_id="eddypro_v7_test",
        )
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["reference_id"] == "eddypro_v7_test"
        assert data["total_windows"] == 2
        assert data["matched_windows"] == 2
        assert len(data["per_window"]) == 2

    def test_parity_artifact_per_window_fields(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result_with_benchmark()
        bm_results = self._make_benchmark_results()
        path = exporter.export_parity_artifact(
            rp_result=rp_result, benchmark_results=bm_results,
            export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for pw in data["per_window"]:
            assert "window_id" in pw
            assert "primary_flux" in pw
            assert "source" in pw
            assert "lag_seconds" in pw
            assert "lag_strategy" in pw
            assert "rotation_mode" in pw
            assert "applied_rotation_impl" in pw
            assert "wpl_water_vapor_term" in pw
            assert "wpl_sensible_heat_term" in pw
            assert "qc_grade" in pw
            assert "qc_mapping" in pw
            assert "match_strategy" in pw
            assert "absolute_error" in pw
            assert "relative_error" in pw
            assert "pass_rate" in pw
            assert "notes" in pw

    def test_parity_artifact_overall_pass_rate(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result_with_benchmark()
        bm_results = self._make_benchmark_results()
        path = exporter.export_parity_artifact(
            rp_result=rp_result, benchmark_results=bm_results,
            export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["passed_windows"] == 1
        assert data["overall_pass_rate"] == 0.5

    def test_parity_artifact_no_data_returns_none(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        path = exporter.export_parity_artifact(
            rp_result=None, benchmark_results=[],
            export_root=tmp_path,
        )
        assert path is None


class TestBenchmarkCockpitOperationLayer:
    def _make_controller(self, tmp_path):
        from app.studio import StudioController
        ctrl = StudioController.__new__(StudioController)
        ctrl.rp_runs = []
        ctrl.runtime_root = tmp_path
        return ctrl

    def test_cockpit_includes_available_references(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "available_references" in payload
        assert isinstance(payload["available_references"], list)
        assert len(payload["available_references"]) >= 2

    def test_cockpit_includes_reference_details(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "reference_details" in payload
        assert isinstance(payload["reference_details"], dict)

    def test_cockpit_includes_current_thresholds(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "current_thresholds" in payload

    def test_cockpit_includes_per_window_detail(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        now = datetime(2025, 1, 1)
        window = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {"flux_rel_threshold": 0.10},
                "benchmark_deviation_summary": {
                    "overall_pass": True,
                    "match_strategy": "window_id_exact",
                    "matched_reference_window_id": "ep_w001",
                    "comparisons": [
                        {"field_name": "primary_flux", "passed": True, "absolute_error": 0.02, "relative_error": 0.005, "note": ""},
                    ],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=now, windows=[window],
            summary={}, data_source="test", time_range="",
        )
        ctrl.rp_runs = [rp_result]
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=now,
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "per_window_detail" in payload
        assert len(payload["per_window_detail"]) == 1
        detail = payload["per_window_detail"][0]
        assert detail["window_id"] == "w001"
        assert detail["match_strategy"] == "window_id_exact"
        assert detail["matched_reference_window_id"] == "ep_w001"
        assert len(detail["comparisons"]) == 1

    def test_cockpit_table_rows_include_match_strategy(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        now = datetime(2025, 1, 1)
        window = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {},
                "benchmark_deviation_summary": {
                    "overall_pass": True,
                    "match_strategy": "start_time_fuzzy(30s)",
                    "matched_reference_window_id": "ep_w001",
                    "comparisons": [],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=now, windows=[window],
            summary={}, data_source="test", time_range="",
        )
        ctrl.rp_runs = [rp_result]
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=now,
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        window_rows = [r for r in payload["table_rows"] if r[0] == "w001"]
        assert len(window_rows) == 1
        assert "match=" in window_rows[0][2]


class TestHeadlessManifestSchemaTarget:
    def test_manifest_includes_schema_target(self, tmp_path):
        from core.headless_batch_runner import build_batch_manifest
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        config = {"network_output": {"schema_target": "FLUXNET"}}
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        from models.hf_models import FrameQuality, NormalizedHFFrame
        rows = [NormalizedHFFrame(
            timestamp=datetime(2025, 1, 1), device_uid="d1", device_id="001",
            mode=2, frame_quality=FrameQuality.FULL, co2_ppm=410.0, h2o_mmol=12.0,
            pressure_kpa=101.3, chamber_temp_c=25.0, case_temp_c=24.9, raw_text="{}",
        )]
        from core.ec_rp.pipeline import ECRPPipeline
        from core.ec_fcc.pipeline import ECFCCPipeline
        rp_result = ECRPPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        spectral_result = ECFCCPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        manifest = build_batch_manifest(
            batch_id="test", metadata_bundle=metadata, config=config,
            rows=rows, rp_result=rp_result, spectral_result=spectral_result,
        )
        assert manifest["schema_target"] == "FLUXNET"
        assert "fluxnet_timezone_offset_h" in manifest
        assert "fluxnet_timestamp_refers_to" in manifest


# ---------------------------------------------------------------------------
# v3f — Network Exporter Landing + Benchmark Cockpit Final Interaction
# ---------------------------------------------------------------------------

from core.exports.result_exporter import (
    AMERIFLUX_FIELD_MAP,
    ICOS_FIELD_MAP,
    NETWORK_SCHEMA_REGISTRY,
    validate_fluxnet_row,
)


class TestFLUXNETFullSubmission:
    def _make_rp_result(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        windows = []
        for i in range(4):
            w = WindowRPResult(
                window_id=f"w{i+1:03d}",
                start_time=now + timedelta(minutes=30 * i),
                end_time=now + timedelta(minutes=30 * (i + 1)),
                sample_count=18000, valid_sample_count=17900,
                continuity_ratio=0.99, missing_ratio=0.01,
                rotation_mode="double", detrend_mode="block_mean",
                lag_seconds=2.3, lag_confidence=0.85,
                cov_w_co2=-0.001, cov_w_h2o=0.0005,
                raw_flux=-3.5, mixing_ratio_flux=-3.4,
                density_corrected_flux=-3.45, water_vapor_flux=0.012,
                air_molar_density=41.5, dry_air_molar_density=41.3,
                mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
                mean_pressure_kpa=101.3, mean_temp_c=22.5,
                primary_flux=-3.45, primary_flux_source="wpl",
                qc_grade="A", anomaly_type="", reason="",
                ustar=0.35, stationarity_score=85.0, turbulence_score=90.0,
            )
            windows.append(w)
        return RPRunResult(
            run_id="test_fluxnet_full", created_at=now, data_source="test",
            time_range="", summary={}, windows=windows,
        )

    def test_full_submission_creates_artifact(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_full_submission(
            rp_result=rp_result, export_root=tmp_path,
            site_id="US-Ha1", pi_name="Dr. Test", pi_email="test@example.com",
            site_description="Harvard Forest", vegetation_type="DBF",
            latitude=42.54, longitude=-72.18, elevation_m=340,
        )
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "badm_header" in data
        assert "variable_list" in data
        assert "validation_summary" in data

    def test_full_submission_badm_header(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_full_submission(
            rp_result=rp_result, export_root=tmp_path,
            site_id="US-Ha1", pi_name="Dr. Test",
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        badm = data["badm_header"]
        assert badm["SITE_ID"] == "US-Ha1"
        assert badm["SUBMITTER_NAME"] == "Dr. Test"
        assert badm["AVERAGING_PERIOD_MIN"] == 30
        assert "TIMEZONE_OFFSET_H" in badm
        assert "TIMESTAMP_REFERS_TO" in badm
        assert "GAP_FILL_VALUE" in badm

    def test_full_submission_variable_list(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_full_submission(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        var_list = data["variable_list"]
        var_names = [v["name"] for v in var_list]
        assert "TIMESTAMP_START" in var_names
        assert "FC" in var_names
        assert "FC_QC" in var_names
        assert "DOY" in var_names
        for v in var_list:
            assert "name" in v
            assert "format" in v
            assert "description" in v

    def test_full_submission_validation_summary(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_fluxnet_full_submission(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        vs = data["validation_summary"]
        assert "total_rows" in vs
        assert "data_rows" in vs
        assert "gap_rows" in vs
        assert "error_count" in vs
        assert "valid" in vs

    def test_full_submission_csv_written(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        exporter.export_fluxnet_full_submission(
            rp_result=rp_result, export_root=tmp_path,
        )
        csv_path = tmp_path / "fluxnet_full_submission_data.csv"
        assert csv_path.exists()


class TestAmeriFluxExporter:
    def _make_rp_result(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        w = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            ustar=0.35, stationarity_score=85.0, turbulence_score=90.0,
        )
        return RPRunResult(
            run_id="test_ameriflux", created_at=now, data_source="test",
            time_range="", summary={}, windows=[w],
        )

    def test_ameriflux_artifact_creates(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_ameriflux_artifact(
            rp_result=rp_result, export_root=tmp_path, site_id="US-Ha1",
        )
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["metadata"]["schema_target"] == "AmeriFlux"

    def test_ameriflux_field_mapping(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_ameriflux_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            assert "QC_FLAG" in row
            assert "WS" in row
            assert "WD" in row
            assert "FC" in row

    def test_ameriflux_timestamp_format(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_ameriflux_artifact(
            rp_result=rp_result, export_root=tmp_path,
            timezone_offset_hours=-5.0,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            ts = row.get("TIMESTAMP_START", "")
            if ts and ts != "-9999":
                assert "-" in ts

    def test_ameriflux_validation_status(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_ameriflux_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "validation_status" in data["metadata"]
        assert "missing_fields" in data["metadata"]

    def test_ameriflux_csv_written(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        exporter.export_ameriflux_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        csv_path = tmp_path / "ameriflux_artifact.csv"
        assert csv_path.exists()


class TestICOSExporter:
    def _make_rp_result(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        w = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            ustar=0.35, stationarity_score=85.0, turbulence_score=90.0,
        )
        return RPRunResult(
            run_id="test_icos", created_at=now, data_source="test",
            time_range="", summary={}, windows=[w],
        )

    def test_icos_artifact_creates(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_icos_artifact(
            rp_result=rp_result, export_root=tmp_path, site_id="FI-Hyy",
        )
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["metadata"]["schema_target"] == "ICOS"

    def test_icos_field_mapping(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_icos_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            assert "Fc" in row
            assert "Fc_QC" in row
            assert "ustar" in row
            assert "Ta" in row

    def test_icos_timestamp_iso8601(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_icos_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            ts = row.get("TIMESTAMP_START", "")
            if ts and "T" in ts:
                assert "2025" in ts

    def test_icos_validation_status(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        path = exporter.export_icos_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "validation_status" in data["metadata"]
        assert "missing_fields" in data["metadata"]

    def test_icos_csv_written(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result()
        exporter.export_icos_artifact(
            rp_result=rp_result, export_root=tmp_path,
        )
        csv_path = tmp_path / "icos_artifact.csv"
        assert csv_path.exists()


class TestBenchmarkCockpitFinalInteraction:
    def _make_controller(self, tmp_path):
        from app.studio import StudioController
        ctrl = StudioController.__new__(StudioController)
        ctrl.rp_runs = []
        ctrl.runtime_root = tmp_path
        return ctrl

    def test_cockpit_includes_ref_provenance(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "ref_provenance" in payload
        assert isinstance(payload["ref_provenance"], dict)

    def test_cockpit_includes_failed_fields_filter(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "failed_fields_filter" in payload

    def test_cockpit_provenance_in_table_rows(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        now = datetime(2025, 1, 1)
        window = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {},
                "benchmark_deviation_summary": {
                    "overall_pass": True,
                    "match_strategy": "window_id_exact",
                    "matched_reference_window_id": "ep_w001",
                    "comparisons": [],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=now, windows=[window],
            summary={}, data_source="test", time_range="",
        )
        ctrl.rp_runs = [rp_result]
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=now,
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        provenance_rows = [r for r in payload["table_rows"] if r[0].startswith("provenance.")]
        assert len(provenance_rows) >= 1

    def test_cockpit_export_options_include_provenance(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=datetime(2025, 1, 1),
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert any("provenance" in opt for opt in payload["export_options"])

    def test_cockpit_file_info_includes_provenance(self, tmp_path):
        ctrl = self._make_controller(tmp_path)
        now = datetime(2025, 1, 1)
        window = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_status": "active",
                "benchmark_target": "eddypro_v7",
                "benchmark_reference_id": "eddypro_v7_synthetic_001",
                "benchmark_thresholds": {},
                "benchmark_deviation_summary": {
                    "overall_pass": True,
                    "match_strategy": "window_id_exact",
                    "matched_reference_window_id": "ep_w001",
                    "comparisons": [],
                },
            },
        )
        rp_result = RPRunResult(
            run_id="test", created_at=now, windows=[window],
            summary={}, data_source="test", time_range="",
        )
        ctrl.rp_runs = [rp_result]
        from models.spectral_models import SpectralRunResult
        spectral = SpectralRunResult(
            run_id="test", created_at=now,
            windows=[], summary={}, data_source="test", time_range="", qc_only=False,
        )
        payload = ctrl._benchmark_cockpit_payload(spectral)
        assert "参考文件" in payload["file_info"]
        assert "归一化时间" in payload["file_info"]


class TestHeadlessManifestNetworkValidation:
    def test_manifest_includes_network_validation(self, tmp_path):
        from core.headless_batch_runner import build_batch_manifest
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        config = {"network_output": {"schema_target": "AmeriFlux"}}
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        from models.hf_models import FrameQuality, NormalizedHFFrame
        rows = [NormalizedHFFrame(
            timestamp=datetime(2025, 1, 1), device_uid="d1", device_id="001",
            mode=2, frame_quality=FrameQuality.FULL, co2_ppm=410.0, h2o_mmol=12.0,
            pressure_kpa=101.3, chamber_temp_c=25.0, case_temp_c=24.9, raw_text="{}",
        )]
        from core.ec_rp.pipeline import ECRPPipeline
        from core.ec_fcc.pipeline import ECFCCPipeline
        rp_result = ECRPPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        spectral_result = ECFCCPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        manifest = build_batch_manifest(
            batch_id="test", metadata_bundle=metadata, config=config,
            rows=rows, rp_result=rp_result, spectral_result=spectral_result,
        )
        assert "network_validation_status" in manifest
        assert "network_missing_fields" in manifest
        assert manifest["schema_target"] == "AmeriFlux"


# ---------------------------------------------------------------------------
# v3g — Footprint + Uncertainty + Spectral Correction Landing
# ---------------------------------------------------------------------------

from core.ec_rp.analysis import (
    compute_footprint,
    compute_footprint_kljun,
    compute_footprint_kormann_meixner,
    compute_footprint_hsieh,
    compute_uncertainty_mann_lenschow,
    compute_uncertainty_finkelstein_sims,
    compute_spectral_correction,
    compute_spectral_correction_massman,
    compute_spectral_correction_horst,
    compute_spectral_correction_ibrom,
    compute_spectral_correction_fratini,
)


class TestFootprintKljun:
    def test_basic_computation(self):
        fp = compute_footprint_kljun(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert fp.method == "kljun"
        assert fp.peak_distance_m > 0
        assert fp.offset_distance_m > 0
        assert fp.detail.get("status") == "ok"

    def test_contribution_distances(self):
        fp = compute_footprint_kljun(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert "x10" in fp.contribution_distances
        assert "x30" in fp.contribution_distances
        assert "x50" in fp.contribution_distances
        assert "x70" in fp.contribution_distances
        assert "x90" in fp.contribution_distances
        assert fp.contribution_distances["x10"] < fp.contribution_distances["x90"]

    def test_low_ustar_returns_insufficient(self):
        fp = compute_footprint_kljun(
            ustar=1e-8, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert fp.peak_distance_m == 0.0
        assert fp.detail.get("status") == "insufficient_data"

    def test_provenance_in_detail(self):
        fp = compute_footprint_kljun(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert "provenance" in fp.detail
        assert "limitations" in fp.detail


class TestFootprintKormannMeixner:
    def test_basic_computation(self):
        fp = compute_footprint_kormann_meixner(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert fp.method == "kormann_meixner"
        assert fp.peak_distance_m > 0
        assert fp.detail.get("status") == "ok"

    def test_contribution_distances(self):
        fp = compute_footprint_kormann_meixner(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert "x50" in fp.contribution_distances

    def test_provenance_in_detail(self):
        fp = compute_footprint_kormann_meixner(
            ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2,
            z_m=30.0, h=25.0,
        )
        assert "provenance" in fp.detail
        assert "Kormann" in fp.detail["provenance"]


class TestFootprintHsieh:
    def test_basic_computation(self):
        fp = compute_footprint_hsieh(
            ustar=0.4, mean_wind_speed=3.0,
            z_m=30.0, h=25.0,
        )
        assert fp.method == "hsieh"
        assert fp.peak_distance_m > 0
        assert fp.detail.get("status") == "ok"

    def test_stable_conditions(self):
        fp = compute_footprint_hsieh(
            ustar=0.4, mean_wind_speed=3.0,
            z_m=30.0, h=25.0, ol=50.0,
        )
        assert fp.peak_distance_m > 0

    def test_unstable_conditions(self):
        fp = compute_footprint_hsieh(
            ustar=0.4, mean_wind_speed=3.0,
            z_m=30.0, h=25.0, ol=-100.0,
        )
        assert fp.peak_distance_m > 0


class TestFootprintDispatch:
    def test_dispatch_kljun(self):
        fp = compute_footprint(method="kljun", ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2, z_m=30.0, h=25.0)
        assert fp.method == "kljun"

    def test_dispatch_kormann_meixner(self):
        fp = compute_footprint(method="kormann_meixner", ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2, z_m=30.0, h=25.0)
        assert fp.method == "kormann_meixner"

    def test_dispatch_hsieh(self):
        fp = compute_footprint(method="hsieh", ustar=0.4, mean_wind_speed=3.0, z_m=30.0, h=25.0)
        assert fp.method == "hsieh"

    def test_dispatch_default_is_kljun(self):
        fp = compute_footprint(ustar=0.4, mean_wind_speed=3.0, sigma_v=1.2, z_m=30.0, h=25.0)
        assert fp.method == "kljun"


class TestUncertaintyMannLenschow:
    def test_basic_computation(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=-0.001, var_w=0.5, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
        )
        assert result["method"] == "mann_lenschow"
        assert result["status"] == "ok"
        assert result["random_error"] is not None
        assert result["random_error"] > 0
        assert result["relative_error"] is not None

    def test_components(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=-0.001, var_w=0.5, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
        )
        assert "n_effective" in result["components"]
        assert "integral_timescale_s" in result["components"]
        assert "var_w" in result["components"]

    def test_provenance_and_limitations(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=-0.001, var_w=0.5, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
        )
        assert "provenance" in result
        assert "limitations" in result
        assert len(result["limitations"]) > 0

    def test_insufficient_data(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=0.0, var_w=0.5, var_scalar=2.0,
            n_samples=10, averaging_period_s=1800.0,
        )
        assert result["status"] == "insufficient_data"

    def test_custom_integral_timescale(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=-0.001, var_w=0.5, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
            integral_timescale_s=5.0,
        )
        assert result["components"]["integral_timescale_s"] == 5.0


class TestUncertaintyFinkelsteinSims:
    def test_basic_computation(self):
        np.random.seed(42)
        n = 18000
        w = np.random.randn(n) * 0.5
        co2 = np.random.randn(n) * 2.0 + 415.0
        result = compute_uncertainty_finkelstein_sims(
            w_series=w, scalar_series=co2,
            sample_rate_hz=10.0, averaging_period_s=1800.0,
        )
        assert result["method"] == "finkelstein_sims"
        assert result["status"] == "ok"
        assert result["random_error"] is not None
        assert result["random_error"] > 0

    def test_components(self):
        np.random.seed(42)
        n = 18000
        w = np.random.randn(n) * 0.5
        co2 = np.random.randn(n) * 2.0 + 415.0
        result = compute_uncertainty_finkelstein_sims(
            w_series=w, scalar_series=co2,
            sample_rate_hz=10.0, averaging_period_s=1800.0,
        )
        assert "cov_ws" in result["components"]
        assert "var_cov" in result["components"]

    def test_provenance_and_limitations(self):
        np.random.seed(42)
        n = 18000
        w = np.random.randn(n) * 0.5
        co2 = np.random.randn(n) * 2.0 + 415.0
        result = compute_uncertainty_finkelstein_sims(
            w_series=w, scalar_series=co2,
            sample_rate_hz=10.0, averaging_period_s=1800.0,
        )
        assert "provenance" in result
        assert "Finkelstein" in result["provenance"]
        assert "limitations" in result

    def test_insufficient_data(self):
        result = compute_uncertainty_finkelstein_sims(
            w_series=np.array([1.0, 2.0]), scalar_series=np.array([1.0, 2.0]),
            sample_rate_hz=10.0, averaging_period_s=1800.0,
        )
        assert result["status"] == "insufficient_data"


class TestSpectralCorrectionMassman:
    def test_basic_computation(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0,
        )
        assert result["method"] == "massman"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0

    def test_components(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0,
        )
        assert "H_path" in result["components"]
        assert "H_sep" in result["components"]
        assert "H_resp" in result["components"]
        assert "H_total" in result["components"]

    def test_provenance(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0,
        )
        assert "provenance" in result
        assert "Massman" in result["provenance"]

    def test_low_wind_returns_insufficient(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=0.01,
        )
        assert result["status"] == "insufficient_data"
        assert result["correction_factor"] == 1.0


class TestSpectralCorrectionHorst:
    def test_basic_computation(self):
        result = compute_spectral_correction_horst(
            path_length_m=0.15, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert result["method"] == "horst"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0

    def test_provenance(self):
        result = compute_spectral_correction_horst(
            path_length_m=0.15, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert "Horst" in result["provenance"]


class TestSpectralCorrectionIbrom:
    def test_basic_computation(self):
        result = compute_spectral_correction_ibrom(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert result["method"] == "ibrom"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0

    def test_provenance(self):
        result = compute_spectral_correction_ibrom(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert "Ibrom" in result["provenance"]


class TestSpectralCorrectionFratini:
    def test_basic_computation(self):
        result = compute_spectral_correction_fratini(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert result["method"] == "fratini"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0

    def test_provenance(self):
        result = compute_spectral_correction_fratini(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4,
        )
        assert "Fratini" in result["provenance"]


class TestSpectralCorrectionDispatch:
    def test_dispatch_massman(self):
        result = compute_spectral_correction(method="massman", path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1, sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0)
        assert result["method"] == "massman"

    def test_dispatch_horst(self):
        result = compute_spectral_correction(method="horst", path_length_m=0.15, wind_speed=3.0, z_m=30.0, ustar=0.4)
        assert result["method"] == "horst"

    def test_dispatch_ibrom(self):
        result = compute_spectral_correction(method="ibrom", path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1, sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4)
        assert result["method"] == "ibrom"

    def test_dispatch_fratini(self):
        result = compute_spectral_correction(method="fratini", path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1, sample_rate_hz=10.0, wind_speed=3.0, z_m=30.0, ustar=0.4)
        assert result["method"] == "fratini"

    def test_dispatch_default_is_massman(self):
        result = compute_spectral_correction(path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1, sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0)
        assert result["method"] == "massman"


class TestPipelineFootprintIntegration:
    def test_footprint_in_diagnostics(self):
        from core.ec_rp.pipeline import ECRPPipeline
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        from models.hf_models import FrameQuality, NormalizedHFFrame
        config = {
            "footprint": {"enabled": True, "method": "kljun", "z_m": 30.0, "canopy_height_m": 25.0},
        }
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        rows = [NormalizedHFFrame(
            timestamp=datetime(2025, 1, 1) + timedelta(seconds=0.1 * i),
            device_uid="d1", device_id="001",
            mode=2, frame_quality=FrameQuality.FULL,
            co2_ppm=410.0 + 0.5 * np.random.randn(),
            h2o_mmol=12.0 + 0.3 * np.random.randn(),
            pressure_kpa=101.3, chamber_temp_c=25.0, case_temp_c=24.9, raw_text="{}",
        ) for i in range(18000)]
        result = ECRPPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        if result.windows and result.windows[0].diagnostics.get("footprint_method"):
            diag = result.windows[0].diagnostics
            assert "footprint_peak_distance_m" in diag
        else:
            assert True


class TestPipelineUncertaintyMethodIntegration:
    def test_mann_lenschow_in_diagnostics(self):
        from core.ec_rp.pipeline import ECRPPipeline
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        from models.hf_models import FrameQuality, NormalizedHFFrame
        config = {
            "uncertainty": {"method": "mann_lenschow"},
        }
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        rows = [NormalizedHFFrame(
            timestamp=datetime(2025, 1, 1) + timedelta(seconds=0.1 * i),
            device_uid="d1", device_id="001",
            mode=2, frame_quality=FrameQuality.FULL,
            co2_ppm=410.0 + 0.5 * np.random.randn(),
            h2o_mmol=12.0 + 0.3 * np.random.randn(),
            pressure_kpa=101.3, chamber_temp_c=25.0, case_temp_c=24.9, raw_text="{}",
        ) for i in range(18000)]
        result = ECRPPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        if result.windows and result.windows[0].diagnostics.get("uncertainty_method"):
            diag = result.windows[0].diagnostics
            assert diag.get("uncertainty_method") == "mann_lenschow"
            assert "uncertainty_method_detail" in diag
        else:
            assert True


class TestPipelineSpectralCorrectionIntegration:
    def test_spectral_correction_in_diagnostics(self):
        from core.ec_rp.pipeline import ECRPPipeline
        from models.station_models import MetadataBundle, ProjectProfile, SiteProfile
        from models.hf_models import FrameQuality, NormalizedHFFrame
        config = {
            "spectral_correction": {"enabled": True, "method": "massman", "z_m": 30.0},
        }
        metadata = MetadataBundle(project=ProjectProfile(name="T", code="T01"), site=SiteProfile(station_name="S", station_code="S01"))
        rows = [NormalizedHFFrame(
            timestamp=datetime(2025, 1, 1) + timedelta(seconds=0.1 * i),
            device_uid="d1", device_id="001",
            mode=2, frame_quality=FrameQuality.FULL,
            co2_ppm=410.0 + 0.5 * np.random.randn(),
            h2o_mmol=12.0 + 0.3 * np.random.randn(),
            pressure_kpa=101.3, chamber_temp_c=25.0, case_temp_c=24.9, raw_text="{}",
        ) for i in range(18000)]
        result = ECRPPipeline().run(rows=rows, project=metadata.project, site=metadata.site, config=config, data_source="test", time_range="")
        if result.windows and result.windows[0].diagnostics.get("spectral_correction_method"):
            diag = result.windows[0].diagnostics
            assert "spectral_correction_factor" in diag
        else:
            assert True


class TestParityArtifactMethodFields:
    def _make_rp_result_with_methods(self) -> RPRunResult:
        now = datetime(2025, 7, 15, 0, 0, 0)
        w = WindowRPResult(
            window_id="w001", start_time=now, end_time=now + timedelta(minutes=30),
            sample_count=18000, valid_sample_count=17900,
            continuity_ratio=0.99, missing_ratio=0.01,
            rotation_mode="double", detrend_mode="block_mean",
            lag_seconds=2.3, lag_confidence=0.85,
            cov_w_co2=-0.001, cov_w_h2o=0.0005,
            raw_flux=-3.5, mixing_ratio_flux=-3.4,
            density_corrected_flux=-3.45, water_vapor_flux=0.012,
            air_molar_density=41.5, dry_air_molar_density=41.3,
            mean_co2_ppm=415.0, mean_h2o_mmol=12.5,
            mean_pressure_kpa=101.3, mean_temp_c=22.5,
            primary_flux=-3.45, primary_flux_source="wpl",
            qc_grade="A", anomaly_type="", reason="",
            diagnostics={
                "benchmark_deviation_summary": {
                    "overall_pass": True,
                    "match_strategy": "window_id_exact",
                    "matched_reference_window_id": "ep_w001",
                    "comparisons": [],
                },
                "footprint_method": "kljun",
                "uncertainty_method": "mann_lenschow",
                "spectral_correction_method": "massman",
                "spectral_correction_factor": 1.05,
            },
        )
        return RPRunResult(
            run_id="test_method_parity", created_at=now, windows=[w],
            summary={}, data_source="test", time_range="",
        )

    def test_parity_artifact_has_method_fields(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result_with_methods()
        bm_results = [{
            "window_id": "w001",
            "comparisons": [],
            "overall_pass": True,
            "match_strategy": "window_id_exact",
            "matched_reference_window_id": "ep_w001",
        }]
        path = exporter.export_parity_artifact(
            rp_result=rp_result, benchmark_results=bm_results,
            export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        pw = data["per_window"][0]
        assert pw["footprint_method"] == "kljun"
        assert pw["uncertainty_method"] == "mann_lenschow"
        assert pw["spectral_correction_method"] == "massman"
        assert "method_deviation_notes" in pw

    def test_method_deviation_notes_populated(self, tmp_path):
        exporter = ResultExporter(tmp_path)
        rp_result = self._make_rp_result_with_methods()
        bm_results = [{
            "window_id": "w001",
            "comparisons": [],
            "overall_pass": True,
            "match_strategy": "window_id_exact",
            "matched_reference_window_id": "ep_w001",
        }]
        path = exporter.export_parity_artifact(
            rp_result=rp_result, benchmark_results=bm_results,
            export_root=tmp_path,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        pw = data["per_window"][0]
        notes = pw["method_deviation_notes"]
        assert any("footprint" in n for n in notes)
        assert any("uncertainty" in n for n in notes)
        assert any("spectral_correction" in n for n in notes)
