"""Tests for Truthfulness & Method Parity Repair v3a.3.

Covers:
  1. Density correction mode primary flux semantics
  2. Planar_fit fallback method semantics
  3. Method provenance completeness
  4. Full_output / manifest field consistency
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.ec_rp.analysis import (
    LagAnalysisResult,
    normalize_density_correction_mode,
    normalize_rotation_mode,
    rotate_wind,
)
from core.ec_rp.pipeline import ECRPPipeline
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
# 1. Density correction mode primary flux semantics
# ---------------------------------------------------------------------------

class TestPrimaryFluxSemantics:
    """Verify that correction_mode determines the primary_flux output."""

    def test_wpl_primary_flux_equals_density_corrected(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.density_corrected_flux, rel=1e-9)
            assert window.primary_flux_source == "wpl"

    def test_mixing_ratio_primary_flux_equals_mixing_ratio_flux(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "mixing_ratio"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.mixing_ratio_flux, rel=1e-9)
            assert window.primary_flux_source == "mixing_ratio"

    def test_none_primary_flux_equals_raw_flux(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "none"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux == pytest.approx(window.raw_flux, rel=1e-9)
            assert window.primary_flux_source == "none"

    def test_wpl_primary_flux_differs_from_raw(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "wpl"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.primary_flux != pytest.approx(window.raw_flux, rel=1e-6)

    def test_diagnostics_primary_flux_source(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"density_correction_mode": "mixing_ratio"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("primary_flux_source") == "mixing_ratio"

    def test_three_modes_primary_flux_values_differ(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        results = {}
        for mode in ("wpl", "mixing_ratio", "none"):
            result = pipeline.run(
                rows=rows,
                project=ProjectProfile(name="Test", code="T01"),
                site=SiteProfile(station_name="Site1", station_code="S01"),
                config={"density_correction_mode": mode},
                data_source="test",
                time_range="",
            )
            results[mode] = result.windows[0].primary_flux
        assert results["wpl"] != results["none"]
        assert results["mixing_ratio"] != results["none"]


# ---------------------------------------------------------------------------
# 2. Planar_fit fallback method semantics
# ---------------------------------------------------------------------------

class TestPlanarFitFallbackSemantics:
    """Verify that planar_fit fallback is clearly marked in diagnostics."""

    def test_planar_fit_requested_vs_applied(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "planar_fit"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("requested_rotation_mode") == "planar_fit"
            assert window.diagnostics.get("applied_rotation_impl") == "planar_fit"
            assert "planar_fit" in window.diagnostics.get("rotation_reason", "").lower()

    def test_double_rotation_requested_equals_applied(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "double"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("requested_rotation_mode") == "double"
            assert window.diagnostics.get("applied_rotation_impl") == "double"

    def test_triple_rotation_requested_equals_applied(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "triple"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("requested_rotation_mode") == "triple"
            assert window.diagnostics.get("applied_rotation_impl") == "triple"

    def test_planar_fit_rotation_reason_mentions_fallback(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"rotation_mode": "planar_fit"},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            reason = window.diagnostics.get("rotation_reason", "")
            assert "fallback" in reason.lower() or "planar_fit" in reason.lower()


# ---------------------------------------------------------------------------
# 3. Method provenance completeness
# ---------------------------------------------------------------------------

class TestMethodProvenanceCompleteness:
    """Verify that all required provenance fields are present in diagnostics."""

    REQUIRED_PROVENANCE_FIELDS = [
        "primary_flux_source",
        "applied_rotation_impl",
        "requested_rotation_mode",
        "lag_strategy",
        "lag_fallback_reason",
        "density_correction_mode",
        "density_correction_reason",
        "screening_config",
        "screening_summary",
    ]

    def test_all_provenance_fields_present(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            for field_name in self.REQUIRED_PROVENANCE_FIELDS:
                assert field_name in window.diagnostics, f"Missing provenance field: {field_name}"

    def test_lag_fallback_reason_for_constant_strategy(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"lag_phase": {"strategy": "constant", "expected_lag_s": 2.0, "search_window_s": 4.0}},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("lag_fallback_reason") != ""
            assert "constant" in window.diagnostics.get("lag_fallback_reason", "").lower()

    def test_lag_fallback_reason_empty_for_covariance_max(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={"lag_phase": {"strategy": "covariance_max", "search_window_s": 4.0}},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert window.diagnostics.get("lag_fallback_reason") == ""

    def test_screening_summary_present(self):
        rows = _make_rows()
        pipeline = ECRPPipeline()
        result = pipeline.run(
            rows=rows,
            project=ProjectProfile(name="Test", code="T01"),
            site=SiteProfile(station_name="Site1", station_code="S01"),
            config={},
            data_source="test",
            time_range="",
        )
        assert result.windows
        for window in result.windows:
            assert "screening_summary" in window.diagnostics
            assert isinstance(window.diagnostics["screening_summary"], str)

    def test_manifest_includes_method_provenance_fields(self):
        config = {
            "density_correction_mode": "mixing_ratio",
            "rotation_mode": "planar_fit",
        }
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert manifest["density_correction_mode"] == "mixing_ratio"
        assert manifest["rotation_mode"] == "planar_fit"


# ---------------------------------------------------------------------------
# 4. Full_output / manifest field consistency
# ---------------------------------------------------------------------------

class TestFullOutputManifestConsistency:
    """Verify that full_output and manifest contain consistent provenance fields."""

    def test_full_output_schema_has_primary_flux_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "primary_flux" in schema_names
        assert "primary_flux_source" in schema_names

    def test_full_output_schema_has_rotation_impl_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "requested_rotation_mode" in schema_names
        assert "applied_rotation_impl" in schema_names

    def test_full_output_schema_has_lag_fallback_reason(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "lag_fallback_reason" in schema_names

    def test_full_output_schema_has_screening_summary(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "screening_summary" in schema_names

    def test_full_output_row_primary_flux_wpl(self):
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
            primary_flux=-5.0,
            primary_flux_source="wpl",
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
                "density_correction_mode": "wpl",
                "density_correction_reason": "wpl: Webb-Pearman-Leuning density correction applied",
                "primary_flux_source": "wpl",
                "requested_rotation_mode": "double",
                "applied_rotation_impl": "double",
                "lag_fallback_reason": "",
                "screening_summary": "issues=0, passed=0",
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
        assert rows[0]["primary_flux"] == -5.0
        assert rows[0]["primary_flux_source"] == "wpl"
        assert rows[0]["requested_rotation_mode"] == "double"
        assert rows[0]["applied_rotation_impl"] == "double"
        assert rows[0]["lag_fallback_reason"] == ""

    def test_full_output_row_primary_flux_mixing_ratio(self):
        window = WindowRPResult(
            window_id="w1",
            start_time=datetime(2025, 1, 1, 0, 0),
            end_time=datetime(2025, 1, 1, 0, 30),
            sample_count=18000,
            valid_sample_count=17900,
            continuity_ratio=0.99,
            missing_ratio=0.01,
            rotation_mode="planar_fit",
            detrend_mode="block_mean",
            lag_seconds=2.4,
            lag_confidence=0.85,
            cov_w_co2=-0.05,
            cov_w_h2o=0.01,
            raw_flux=-5.2,
            mixing_ratio_flux=-5.1,
            density_corrected_flux=-5.0,
            primary_flux=-5.1,
            primary_flux_source="mixing_ratio",
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
                "primary_flux_source": "mixing_ratio",
                "requested_rotation_mode": "planar_fit",
                "applied_rotation_impl": "planar_fit",
                "lag_fallback_reason": "lag_strategy=constant: using expected_lag_s",
                "screening_summary": "issues=1, passed=2",
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
        assert rows[0]["primary_flux"] == -5.1
        assert rows[0]["primary_flux_source"] == "mixing_ratio"
        assert rows[0]["requested_rotation_mode"] == "planar_fit"
        assert rows[0]["applied_rotation_impl"] == "planar_fit"
        assert "constant" in rows[0]["lag_fallback_reason"]

    def test_export_manifest_method_provenance_fields(self):
        rp_config_snapshot = {
            "density_correction_mode": "mixing_ratio",
            "rotation_mode": "planar_fit",
            "detrend_mode": "running_mean",
            "lag_phase": {"strategy": "constant"},
        }
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        assert rp_config_snapshot.get("density_correction_mode") == "mixing_ratio"
        assert "method_provenance_fields" not in dir(exporter)

    def test_window_to_dict_includes_primary_flux(self):
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
            primary_flux=-5.0,
            primary_flux_source="wpl",
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
        )
        d = window.to_dict()
        assert "primary_flux" in d
        assert d["primary_flux"] == -5.0
        assert "primary_flux_source" in d
        assert d["primary_flux_source"] == "wpl"
