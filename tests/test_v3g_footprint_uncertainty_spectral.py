"""Tests for v3g: Footprint, Uncertainty, and Spectral Correction landing.

Covers:
  1. Footprint models (Kljun, Kormann-Meixner, Hsieh)
  2. Random uncertainty (Mann & Lenschow, Finkelstein & Sims)
  3. Spectral correction (Massman, Horst, Ibrom, Fratini)
  4. Pipeline integration with method provenance
  5. Export integration with method-level fields
  6. Benchmark parity method-level fields
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.ec_rp.analysis import (
    FootprintResult,
    compute_footprint,
    compute_footprint_hsieh,
    compute_footprint_kljun,
    compute_footprint_kormann_meixner,
    compute_spectral_correction,
    compute_spectral_correction_fratini,
    compute_spectral_correction_horst,
    compute_spectral_correction_ibrom,
    compute_spectral_correction_massman,
    compute_uncertainty_finkelstein_sims,
    compute_uncertainty_mann_lenschow,
)
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.rp_models import RPRunResult, WindowRPResult
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
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


# ---------------------------------------------------------------------------
# 1. Footprint models
# ---------------------------------------------------------------------------

class TestFootprintKljun:
    def test_basic_output(self):
        result = compute_footprint_kljun(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        assert isinstance(result, FootprintResult)
        assert result.method == "kljun"
        assert result.peak_distance_m > 0
        assert result.offset_distance_m > 0
        assert "x10" in result.contribution_distances
        assert "x30" in result.contribution_distances
        assert "x50" in result.contribution_distances
        assert "x70" in result.contribution_distances
        assert "x90" in result.contribution_distances

    def test_contribution_distances_ordered(self):
        result = compute_footprint_kljun(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        cd = result.contribution_distances
        assert cd["x10"] <= cd["x30"] <= cd["x50"] <= cd["x70"] <= cd["x90"]

    def test_provenance_present(self):
        result = compute_footprint_kljun(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        assert result.detail["status"] == "ok"
        assert "provenance" in result.detail
        assert "Kljun" in result.detail["provenance"]
        assert "limitations" in result.detail
        assert len(result.detail["limitations"]) > 0

    def test_insufficient_data(self):
        result = compute_footprint_kljun(
            ustar=0.0, mean_wind_speed=0.0, sigma_v=0.0, z_m=3.0, h=5.0,
        )
        assert result.peak_distance_m == 0.0
        assert result.detail["status"] == "insufficient_data"

    def test_with_ol_and_z0(self):
        result = compute_footprint_kljun(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
            z0=0.1, ol=-100.0,
        )
        assert result.peak_distance_m > 0
        assert result.detail["z0_m"] == 0.1
        assert result.detail["ol_m"] == -100.0


class TestFootprintKormannMeixner:
    def test_basic_output(self):
        result = compute_footprint_kormann_meixner(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        assert result.method == "kormann_meixner"
        assert result.peak_distance_m > 0
        assert "x50" in result.contribution_distances
        assert "provenance" in result.detail
        assert "Kormann" in result.detail["provenance"]

    def test_contribution_distances_ordered(self):
        result = compute_footprint_kormann_meixner(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        cd = result.contribution_distances
        assert cd["x10"] <= cd["x30"] <= cd["x50"] <= cd["x70"] <= cd["x90"]


class TestFootprintHsieh:
    def test_basic_output(self):
        result = compute_footprint_hsieh(
            ustar=0.3, mean_wind_speed=3.0, z_m=3.0, h=5.0,
        )
        assert result.method == "hsieh"
        assert result.peak_distance_m > 0
        assert "x50" in result.contribution_distances
        assert "provenance" in result.detail
        assert "Hsieh" in result.detail["provenance"]

    def test_stability_regimes(self):
        result_unstable = compute_footprint_hsieh(
            ustar=0.3, mean_wind_speed=3.0, z_m=3.0, h=5.0, ol=-100.0,
        )
        result_stable = compute_footprint_hsieh(
            ustar=0.3, mean_wind_speed=3.0, z_m=3.0, h=5.0, ol=100.0,
        )
        result_neutral = compute_footprint_hsieh(
            ustar=0.3, mean_wind_speed=3.0, z_m=3.0, h=5.0, ol=-1e10,
        )
        assert result_unstable.peak_distance_m > 0
        assert result_stable.peak_distance_m > 0
        assert result_neutral.peak_distance_m > 0


class TestFootprintDispatcher:
    def test_default_is_kljun(self):
        result = compute_footprint(
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        assert result.method == "kljun"

    def test_dispatch_kormann_meixner(self):
        result = compute_footprint(
            method="kormann_meixner",
            ustar=0.3, mean_wind_speed=3.0, sigma_v=1.0, z_m=3.0, h=5.0,
        )
        assert result.method == "kormann_meixner"

    def test_dispatch_hsieh(self):
        result = compute_footprint(
            method="hsieh",
            ustar=0.3, mean_wind_speed=3.0, z_m=3.0, h=5.0,
        )
        assert result.method == "hsieh"


# ---------------------------------------------------------------------------
# 2. Random uncertainty family
# ---------------------------------------------------------------------------

class TestUncertaintyMannLenschow:
    def test_basic_output(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=0.05, var_w=0.3, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
        )
        assert result["method"] == "mann_lenschow"
        assert result["status"] == "ok"
        assert result["random_error"] is not None
        assert result["random_error"] > 0
        assert result["relative_error"] > 0
        assert "n_effective" in result["components"]
        assert "provenance" in result
        assert "Mann" in result["provenance"]
        assert len(result["limitations"]) > 0

    def test_with_integral_timescale(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=0.05, var_w=0.3, var_scalar=2.0,
            n_samples=18000, averaging_period_s=1800.0,
            integral_timescale_s=5.0,
        )
        assert result["components"]["integral_timescale_s"] == 5.0

    def test_insufficient_data(self):
        result = compute_uncertainty_mann_lenschow(
            cov_w_scalar=0.0, var_w=0.0, var_scalar=0.0,
            n_samples=10, averaging_period_s=1800.0,
        )
        assert result["status"] == "insufficient_data"
        assert result["random_error"] is None


class TestUncertaintyFinkelsteinSims:
    def test_basic_output(self):
        np.random.seed(42)
        n = 1800
        w = np.random.randn(n) * 0.5
        scalar = np.roll(w, 5) * 0.8 + np.random.randn(n) * 0.1
        result = compute_uncertainty_finkelstein_sims(
            w_series=w, scalar_series=scalar,
            sample_rate_hz=10.0, averaging_period_s=180.0,
        )
        assert result["method"] == "finkelstein_sims"
        assert result["status"] == "ok"
        assert result["random_error"] is not None
        assert result["random_error"] > 0
        assert "provenance" in result
        assert "Finkelstein" in result["provenance"]
        assert len(result["limitations"]) > 0

    def test_insufficient_data(self):
        result = compute_uncertainty_finkelstein_sims(
            w_series=np.array([]), scalar_series=np.array([]),
            sample_rate_hz=10.0, averaging_period_s=180.0,
        )
        assert result["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 3. Spectral correction family
# ---------------------------------------------------------------------------

class TestSpectralCorrectionMassman:
    def test_basic_output(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0,
        )
        assert result["method"] == "massman"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0
        assert "H_path" in result["components"]
        assert "provenance" in result
        assert "Massman" in result["provenance"]
        assert len(result["limitations"]) > 0

    def test_insufficient_data(self):
        result = compute_spectral_correction_massman(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=0.5, averaging_period_s=1800.0, wind_speed=0.01,
        )
        assert result["status"] == "insufficient_data"
        assert result["correction_factor"] == 1.0


class TestSpectralCorrectionHorst:
    def test_basic_output(self):
        result = compute_spectral_correction_horst(
            path_length_m=0.15, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "horst"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0
        assert "f_peak_hz" in result["components"]
        assert "Horst" in result["provenance"]


class TestSpectralCorrectionIbrom:
    def test_basic_output(self):
        result = compute_spectral_correction_ibrom(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "ibrom"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0
        assert "Ibrom" in result["provenance"]


class TestSpectralCorrectionFratini:
    def test_basic_output_without_cospectrum(self):
        result = compute_spectral_correction_fratini(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "fratini"
        assert result["status"] == "ok"
        assert result["correction_factor"] >= 1.0
        assert "Fratini" in result["provenance"]
        assert result["components"]["uses_measured_cospectrum"] is False

    def test_with_measured_cospectrum(self):
        freqs = np.linspace(0.001, 5.0, 100)
        cospectrum = np.exp(-freqs * 0.5)
        result = compute_spectral_correction_fratini(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=3.0, ustar=0.3,
            measured_cospectrum_freq=freqs,
            measured_cospectrum_value=cospectrum,
        )
        assert result["status"] == "ok"
        assert result["components"]["uses_measured_cospectrum"] is True


class TestSpectralCorrectionDispatcher:
    def test_default_is_massman(self):
        result = compute_spectral_correction(
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, averaging_period_s=1800.0, wind_speed=3.0,
        )
        assert result["method"] == "massman"

    def test_dispatch_horst(self):
        result = compute_spectral_correction(
            method="horst",
            path_length_m=0.15, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "horst"

    def test_dispatch_ibrom(self):
        result = compute_spectral_correction(
            method="ibrom",
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "ibrom"

    def test_dispatch_fratini(self):
        result = compute_spectral_correction(
            method="fratini",
            path_length_m=0.15, sensor_sep_m=0.20, response_time_s=0.1,
            sample_rate_hz=10.0, wind_speed=3.0, z_m=3.0, ustar=0.3,
        )
        assert result["method"] == "fratini"


# ---------------------------------------------------------------------------
# 4. Pipeline integration
# ---------------------------------------------------------------------------

class TestPipelineFootprintIntegration:
    def test_pipeline_with_footprint_enabled(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="FP Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                    "rotation": {"rotation_mode": "double"},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        assert result.summary["status"] == "ok"
        window = result.windows[0]
        assert window.diagnostics.get("footprint_method") == "kljun"
        assert "footprint_peak_distance_m" in window.diagnostics
        assert window.diagnostics["footprint_peak_distance_m"] > 0
        assert "footprint_contribution_distances" in window.diagnostics
        assert "footprint_detail" in window.diagnostics
        assert "provenance" in window.diagnostics["footprint_detail"]

    def test_pipeline_with_hsieh_footprint(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="FP Hsieh"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "hsieh", "z_m": 3.0, "canopy_height_m": 5.0},
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("footprint_method") == "hsieh"

    def test_pipeline_footprint_disabled_by_default(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="FP Disabled"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert "footprint_method" not in window.diagnostics or window.diagnostics.get("footprint_method") == ""


class TestPipelineUncertaintyIntegration:
    def test_pipeline_with_mann_lenschow(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="ML Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "uncertainty": {"method": "mann_lenschow"},
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("uncertainty_method") == "mann_lenschow"
        assert "uncertainty_method_detail" in window.diagnostics
        ml = window.diagnostics["uncertainty_method_detail"]
        assert ml["method"] == "mann_lenschow"
        assert "provenance" in ml
        assert "limitations" in ml
        assert "components" in ml
        assert window.uncertainty_detail.get("selected_method") == "mann_lenschow"
        assert "provenance" in window.uncertainty_detail
        assert "limitations" in window.uncertainty_detail

    def test_pipeline_with_finkelstein_sims(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="FS Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "uncertainty": {"method": "finkelstein_sims"},
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("uncertainty_method") == "finkelstein_sims"
        fs = window.diagnostics["uncertainty_method_detail"]
        assert fs["method"] == "finkelstein_sims"
        assert "provenance" in fs
        assert window.uncertainty_detail.get("selected_method") == "finkelstein_sims"


class TestPipelineSpectralCorrectionIntegration:
    def test_pipeline_with_massman(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="SC Massman"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "spectral_correction": {
                    "enabled": True, "method": "massman",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("spectral_correction_method") == "massman"
        assert "spectral_correction_factor" in window.diagnostics
        assert "spectral_correction_detail" in window.diagnostics
        assert "spectral_correction_provenance" in window.diagnostics
        assert "Massman" in window.diagnostics["spectral_correction_provenance"]
        assert "spectral_correction_limitations" in window.diagnostics

    def test_pipeline_with_horst(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="SC Horst"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "spectral_correction": {
                    "enabled": True, "method": "horst",
                    "path_length_m": 0.15, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("spectral_correction_method") == "horst"
        assert "Horst" in window.diagnostics["spectral_correction_provenance"]

    def test_pipeline_with_ibrom(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="SC Ibrom"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "spectral_correction": {
                    "enabled": True, "method": "ibrom",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("spectral_correction_method") == "ibrom"

    def test_pipeline_with_fratini(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="SC Fratini"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "spectral_correction": {
                    "enabled": True, "method": "fratini",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        window = result.windows[0]
        assert window.diagnostics.get("spectral_correction_method") == "fratini"
        assert "Fratini" in window.diagnostics["spectral_correction_provenance"]

    def test_pipeline_summary_and_artifacts_include_method_rollups(self):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Method Rollup"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "mann_lenschow"},
                "spectral_correction": {
                    "enabled": True, "method": "massman",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        assert result.summary["footprint_method"] == "kljun"
        assert result.summary["footprint_summary"]["peak_distance_m"] > 0
        assert result.summary["uncertainty_method"] == "mann_lenschow"
        assert "provenance" in result.summary["uncertainty_summary"]
        assert result.summary["spectral_correction_method"] == "massman"
        assert result.summary["spectral_correction_summary"]["correction_factor"] >= 1.0
        assert result.artifacts["method_provenance"]["footprint_summary"]["method"] == "kljun"
        assert result.artifacts["method_provenance"]["uncertainty_summary"]["selected_method"] == "mann_lenschow"
        assert result.artifacts["method_provenance"]["spectral_correction_summary"]["method"] == "massman"


# ---------------------------------------------------------------------------
# 5. Export integration
# ---------------------------------------------------------------------------

class TestExportIntegration:
    def test_full_output_schema_contains_method_fields(self):
        schema_names = [name for name, _group, _status in FULL_OUTPUT_SCHEMA]
        assert "footprint_method" in schema_names
        assert "footprint_peak_distance_m" in schema_names
        assert "footprint_offset_distance_m" in schema_names
        assert "footprint_contribution_distances" in schema_names
        assert "uncertainty_method" in schema_names
        assert "uncertainty_method_detail" in schema_names
        assert "spectral_correction_method" in schema_names
        assert "spectral_correction_factor" in schema_names
        assert "spectral_correction_detail" in schema_names
        assert "spectral_correction_provenance" in schema_names
        assert "spectral_correction_limitations" in schema_names

    def test_export_bundle_with_all_methods(self, tmp_path: Path):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Export Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "mann_lenschow"},
                "spectral_correction": {
                    "enabled": True, "method": "massman",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        exporter = ResultExporter(tmp_path)
        bundle = exporter.export_minimal_bundle(
            rp_result=result,
            spectral_result=None,
            rp_config_snapshot={"steps": {}},
            spectral_config_snapshot={},
            project=ProjectProfile(code="PRJ-001"),
            site=SiteProfile(),
            report_payload={},
            report_key="test",
            full_output_mode="standard_schema",
        )
        export_root = Path(bundle["export_root"])
        full_output_path = export_root / "full_output.csv"
        assert full_output_path.exists()
        content = full_output_path.read_text(encoding="utf-8")
        assert "footprint_method" in content
        assert "footprint_peak_distance_m" in content
        assert "uncertainty_method" in content
        assert "spectral_correction_method" in content

    def test_parity_artifact_contains_method_fields(self, tmp_path: Path):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Parity Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "finkelstein_sims"},
                "spectral_correction": {
                    "enabled": True, "method": "horst",
                    "path_length_m": 0.15, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        exporter = ResultExporter(tmp_path)
        export_root = tmp_path / "parity_test"
        export_root.mkdir(parents=True, exist_ok=True)
        benchmark_results = [
            {
                "window_id": w.window_id,
                "comparisons": [],
                "overall_pass": True,
                "notes": [],
                "match_strategy": "none",
                "matched_reference_window_id": "",
            }
            for w in result.windows
        ]
        parity_path = exporter.export_parity_artifact(
            rp_result=result,
            benchmark_results=benchmark_results,
            export_root=export_root,
            reference_id="test_ref",
        )
        assert parity_path is not None
        artifact = json.loads(parity_path.read_text(encoding="utf-8"))
        assert artifact["total_windows"] > 0
        per_window = artifact["per_window"]
        assert len(per_window) > 0
        first = per_window[0]
        assert "footprint_method" in first
        assert "uncertainty_method" in first
        assert "spectral_correction_method" in first
        assert "method_deviation_notes" in first
        assert first["footprint_method"] == "kljun"
        assert first["uncertainty_method"] == "finkelstein_sims"
        assert first["spectral_correction_method"] == "horst"

    def test_benchmark_summary_artifact_contains_method_fields(self, tmp_path: Path):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Benchmark Summary Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "mann_lenschow"},
                "spectral_correction": {
                    "enabled": True, "method": "massman",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        exporter = ResultExporter(tmp_path)
        benchmark_results = [
            {
                "window_id": w.window_id,
                "comparisons": [],
                "overall_pass": True,
                "notes": [],
                "match_strategy": "window_id_exact",
                "matched_reference_window_id": f"ep_{w.window_id}",
            }
            for w in result.windows
        ]
        summary_path = exporter.export_benchmark_summary_artifact(
            rp_result=result,
            benchmark_results=benchmark_results,
            export_root=tmp_path,
            reference_id="test_ref",
        )
        assert summary_path is not None
        artifact = json.loads(summary_path.read_text(encoding="utf-8"))
        first = artifact["per_window"][0]
        assert first["footprint_method"] == "kljun"
        assert first["uncertainty_method"] == "mann_lenschow"
        assert first["spectral_correction_method"] == "massman"
        assert any("footprint" in note for note in first["method_deviation_notes"])

    def test_export_manifest_includes_method_summaries(self, tmp_path: Path):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Manifest Method Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "hsieh", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "finkelstein_sims"},
                "spectral_correction": {
                    "enabled": True, "method": "fratini",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        exporter = ResultExporter(tmp_path)
        bundle = exporter.export_minimal_bundle(
            rp_result=result,
            spectral_result=None,
            rp_config_snapshot={
                "steps": {},
                "benchmark": {},
                "network_output": {"schema_target": "FLUXNET"},
            },
            spectral_config_snapshot={},
            project=ProjectProfile(code="PRJ-001"),
            site=SiteProfile(),
            report_payload={},
            report_key="test",
            full_output_mode="standard_schema",
        )
        manifest = json.loads((Path(bundle["export_root"]) / "export_manifest.json").read_text(encoding="utf-8"))
        assert manifest["footprint_method"] == "hsieh"
        assert manifest["uncertainty_method"] == "finkelstein_sims"
        assert manifest["spectral_correction_method"] == "fratini"
        assert manifest["footprint_summary"]["peak_distance_m"] > 0
        assert manifest["spectral_correction_summary"]["correction_factor"] >= 1.0


# ---------------------------------------------------------------------------
# 6. Benchmark method-level parity
# ---------------------------------------------------------------------------

class TestBenchmarkMethodParity:
    def test_method_deviation_notes_include_provenance(self):
        from core.exports.result_exporter import _build_method_deviation_notes
        diag = {
            "footprint_method": "kljun",
            "footprint_detail": {"provenance": "Kljun et al. 2015"},
            "uncertainty_method": "mann_lenschow",
            "uncertainty_method_detail": {"provenance": "Mann & Lenschow 1994"},
            "spectral_correction_method": "massman",
            "spectral_correction_factor": 1.15,
            "spectral_correction_provenance": "Massman 2000, 2001",
        }
        notes = _build_method_deviation_notes(diag, {})
        assert len(notes) == 3
        assert any("kljun" in n and "Kljun et al. 2015" in n for n in notes)
        assert any("mann_lenschow" in n and "Mann & Lenschow 1994" in n for n in notes)
        assert any("massman" in n and "Massman 2000" in n for n in notes)

    def test_method_deviation_notes_empty_when_no_methods(self):
        from core.exports.result_exporter import _build_method_deviation_notes
        notes = _build_method_deviation_notes({}, {})
        assert notes == []

    def test_manifest_includes_method_provenance_fields(self, tmp_path: Path):
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=_make_rows(),
            project=ProjectProfile(code="PRJ-001", name="Manifest Test"),
            site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
            config={
                "steps": {
                    "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                    "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                },
                "footprint": {"enabled": True, "method": "kljun", "z_m": 3.0, "canopy_height_m": 5.0},
                "uncertainty": {"method": "mann_lenschow"},
                "spectral_correction": {
                    "enabled": True, "method": "massman",
                    "path_length_m": 0.15, "sensor_sep_m": 0.20,
                    "response_time_s": 0.1, "z_m": 3.0,
                },
            },
            data_source="unit-test",
            time_range="2026-04-18 09:00~09:01",
        )
        exporter = ResultExporter(tmp_path)
        bundle = exporter.export_minimal_bundle(
            rp_result=result,
            spectral_result=None,
            rp_config_snapshot={"steps": {}},
            spectral_config_snapshot={},
            project=ProjectProfile(code="PRJ-001"),
            site=SiteProfile(),
            report_payload={},
            report_key="test",
        )
        export_root = Path(bundle["export_root"])
        manifest = json.loads((export_root / "export_manifest.json").read_text(encoding="utf-8"))
        prov_fields = manifest.get("method_provenance_fields", [])
        assert "footprint_method" in prov_fields
        assert "uncertainty_method" in prov_fields
        assert "spectral_correction_method" in prov_fields
        assert "spectral_correction_provenance" in prov_fields
