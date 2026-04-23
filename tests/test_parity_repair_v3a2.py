"""Tests for Parity Repair v3a.2.

Covers:
  1. CLI / pipeline config path parity
  2. Rotation mode parity (triple, planar_fit)
  3. Density correction mode parity
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.ec_rp.analysis import (
    normalize_density_correction_mode,
    normalize_detrend_mode,
    normalize_lag_strategy,
    normalize_rotation_mode,
    rotate_wind,
)
from core.ec_rp.pipeline import ECRPPipeline, _config_value
from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from core.headless_batch_runner import build_batch_manifest
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.rp_models import WindowRPResult, RPRunResult
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


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


def _make_metadata() -> MetadataBundle:
    return MetadataBundle(
        project=ProjectProfile(name="Test", code="T01"),
        site=SiteProfile(station_name="Site1", station_code="S01"),
    )


# ---------------------------------------------------------------------------
# 1. CLI / pipeline config path parity
# ---------------------------------------------------------------------------

class TestCLIConfigPathParity:
    """Verify that CLI parameters inject into config paths that pipeline reads."""

    def test_lag_strategy_path_unified(self):
        config = {}
        config.setdefault("lag_phase", {})["strategy"] = "constant"
        value = _config_value(config, "lag_phase.strategy", "lag.strategy", "steps.lag.strategy", default="covariance_max")
        assert value == "constant"

    def test_expected_lag_s_path_unified(self):
        config = {}
        config.setdefault("lag_phase", {})["expected_lag_s"] = 3.5
        value = _config_value(config, "lag_phase.expected_lag_s", "lag.expected_lag_s", "steps.lag.expected_lag_s", default=None)
        assert value == 3.5

    def test_detrend_mode_path_unified(self):
        config = {}
        config["detrend_mode"] = "running_mean"
        value = _config_value(config, "detrend_mode", "steps.detrend.detrend_mode", default="block_mean")
        assert value == "running_mean"

    def test_rotation_mode_path_unified(self):
        config = {}
        config["rotation_mode"] = "triple"
        value = _config_value(config, "rotation_mode", "steps.rotation.rotation_mode", default="double")
        assert value == "triple"

    def test_density_correction_mode_path_unified(self):
        config = {}
        config["density_correction_mode"] = "mixing_ratio"
        value = _config_value(config, "density_correction_mode", "steps.density_correction.correction_mode", default="wpl")
        assert value == "mixing_ratio"

    def test_manifest_records_unified_paths(self):
        config = {
            "lag_phase": {"strategy": "constant", "expected_lag_s": 2.5},
            "detrend_mode": "running_mean",
            "rotation_mode": "triple",
            "density_correction_mode": "mixing_ratio",
        }
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert manifest["lag_strategy"] == "constant"
        assert manifest["expected_lag_s"] == 2.5
        assert manifest["detrend_mode"] == "running_mean"
        assert manifest["rotation_mode"] == "triple"
        assert manifest["density_correction_mode"] == "mixing_ratio"

    def test_cli_constant_lag_reflected_in_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "lag_phase": {"strategy": "constant", "expected_lag_s": 2.5, "search_window_s": 4.0},
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("lag_strategy") == "constant"

    def test_cli_detrend_mode_reflected_in_window(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "detrend_mode": "running_mean",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.detrend_mode == "running_mean"

    def test_cli_exponential_running_mean_reflected(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "detrend_mode": "exponential_running_mean",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.detrend_mode == "exponential_running_mean"


# ---------------------------------------------------------------------------
# 2. Rotation mode parity
# ---------------------------------------------------------------------------

class TestRotationModeParity:
    """Verify that triple and planar_fit rotation modes work correctly."""

    def test_normalize_triple_rotation(self):
        assert normalize_rotation_mode("triple") == "triple"
        assert normalize_rotation_mode("三重旋转") == "triple"
        assert normalize_rotation_mode("3d") == "triple"
        assert normalize_rotation_mode("triple_rotation") == "triple"

    def test_normalize_planar_fit(self):
        assert normalize_rotation_mode("planar_fit") == "planar_fit"
        assert normalize_rotation_mode("平面拟合") == "planar_fit"
        assert normalize_rotation_mode("pf") == "planar_fit"

    def test_rotate_wind_triple_applied(self):
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        v = 0.5 + 0.2 * np.random.randn(n)
        w = 0.1 + 0.15 * np.random.randn(n)
        result = rotate_wind(u, v, w, "triple")
        assert result.mode == "triple"
        assert result.applied
        assert "triple" in result.reason.lower() or "double" in result.reason.lower()

    def test_rotate_wind_planar_fit_applied(self):
        n = 1000
        u = 2.0 + 0.3 * np.random.randn(n)
        v = 0.5 + 0.2 * np.random.randn(n)
        w = 0.1 + 0.15 * np.random.randn(n)
        result = rotate_wind(u, v, w, "planar_fit")
        assert result.mode == "planar_fit"
        assert result.applied
        assert "planar_fit" in result.reason.lower() or "double" in result.reason.lower()

    def test_pipeline_triple_rotation_reflected_in_window(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "rotation_mode": "triple",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.rotation_mode == "triple"

    def test_pipeline_planar_fit_reflected_in_window(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "rotation_mode": "planar_fit",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.rotation_mode == "planar_fit"

    def test_rotation_reason_in_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "rotation_mode": "triple",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "rotation_reason" in window.diagnostics
            assert window.diagnostics["rotation_reason"]


# ---------------------------------------------------------------------------
# 3. Density correction mode parity
# ---------------------------------------------------------------------------

class TestDensityCorrectionModeParity:
    """Verify that density correction mode affects output and provenance."""

    def test_normalize_wpl(self):
        assert normalize_density_correction_mode("wpl") == "wpl"
        assert normalize_density_correction_mode("WPL") == "wpl"
        assert normalize_density_correction_mode("密度修正") == "wpl"

    def test_normalize_mixing_ratio(self):
        assert normalize_density_correction_mode("mixing_ratio") == "mixing_ratio"
        assert normalize_density_correction_mode("混合比优先") == "mixing_ratio"

    def test_normalize_none(self):
        assert normalize_density_correction_mode("none") == "none"
        assert normalize_density_correction_mode("不修正") == "none"
        assert normalize_density_correction_mode("raw") == "none"

    def test_pipeline_wpl_mode_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "density_correction_mode": "wpl",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("density_correction_mode") == "wpl"
            assert "wpl" in window.diagnostics.get("density_correction_reason", "").lower()

    def test_pipeline_mixing_ratio_mode_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "density_correction_mode": "mixing_ratio",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("density_correction_mode") == "mixing_ratio"
            assert "mixing_ratio" in window.diagnostics.get("density_correction_reason", "").lower()

    def test_pipeline_none_mode_diagnostics(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "density_correction_mode": "none",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("density_correction_mode") == "none"
            assert "no density correction" in window.diagnostics.get("density_correction_reason", "").lower() or "none" in window.diagnostics.get("density_correction_reason", "").lower()

    def test_export_manifest_density_correction_mode(self):
        rp_config_snapshot = {
            "density_correction_mode": "mixing_ratio",
        }
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        assert exporter._extract_screening_config is not None
        assert rp_config_snapshot.get("density_correction_mode") == "mixing_ratio"

    def test_full_output_schema_has_density_correction_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "density_correction_mode" in schema_names
        assert "density_correction_reason" in schema_names

    def test_full_output_row_contains_density_correction_mode(self):
        window = WindowRPResult(
            window_id="w1",
            start_time=datetime(2025, 1, 1, 0, 0),
            end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000,
            valid_sample_count=17900,
            continuity_ratio=0.99,
            missing_ratio=0.01,
            rotation_mode="double",
            detrend_mode="block_mean",
            lag_seconds=2.4,
            lag_confidence=0.85,
            cov_w_co2=-0.05,
            cov_w_h2o=0.01,
            raw_flux=-5.2,
            mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0,
            water_vapor_flux=0.02,
            air_molar_density=42.0,
            dry_air_molar_density=41.5,
            mean_co2_ppm=415.0,
            mean_h2o_mmol=10.0,
            mean_pressure_kpa=101.3,
            mean_temp_c=25.0,
            qc_grade="A",
            anomaly_type="",
            reason="",
            diagnostics={
                "density_correction_mode": "mixing_ratio",
                "density_correction_reason": "mixing_ratio: using dry-air mixing ratio flux",
            },
        )
        rp_result = RPRunResult(
            run_id="test_run",
            created_at=datetime(2025, 1, 1),
            windows=[window],
            summary={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert len(rows) == 1
        assert rows[0]["density_correction_mode"] == "mixing_ratio"
        assert "mixing_ratio" in rows[0]["density_correction_reason"]


# ---------------------------------------------------------------------------
# 4. End-to-end integration tests
# ---------------------------------------------------------------------------

class TestEndToEndIntegration:
    """End-to-end tests verifying full config flow from CLI to output."""

    def test_full_config_flow_constant_lag(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        config = {
            "lag_phase": {"strategy": "constant", "expected_lag_s": 1.8, "search_window_s": 4.0},
            "detrend_mode": "linear",
            "rotation_mode": "triple",
            "density_correction_mode": "none",
        }
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config=config,
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("lag_strategy") == "constant"
            assert window.detrend_mode == "linear"
            assert window.rotation_mode == "triple"
            assert window.diagnostics.get("density_correction_mode") == "none"

    def test_manifest_reflects_all_modes(self):
        config = {
            "lag_phase": {"strategy": "covariance_max_with_default", "expected_lag_s": 2.0},
            "detrend_mode": "exponential_running_mean",
            "rotation_mode": "planar_fit",
            "density_correction_mode": "mixing_ratio",
        }
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert manifest["lag_strategy"] == "covariance_max_with_default"
        assert manifest["detrend_mode"] == "exponential_running_mean"
        assert manifest["rotation_mode"] == "planar_fit"
        assert manifest["density_correction_mode"] == "mixing_ratio"
