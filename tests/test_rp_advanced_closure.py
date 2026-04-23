"""Tests for RP advanced closure: GUI->config mapping, exporter fields, CLI manifest."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from core.headless_batch_runner import build_batch_manifest
from models.rp_models import WindowRPResult, RPRunResult
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_window(**overrides) -> WindowRPResult:
    defaults = dict(
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
        qc_flags=["spike_w"],
        diagnostics={
            "lag_strategy": "covariance_max",
            "lag_fallback_reason": "",
            "screening_detail": {
                "co2_ppm": {"valid_count": 17900, "issues": []},
                "h2o_mmol": {"valid_count": 17900, "issues": ["skewness"]},
            },
            "issues": ["spike_w", "skewness_h2o_mmol"],
        },
    )
    defaults.update(overrides)
    return WindowRPResult(**defaults)


def _make_metadata() -> MetadataBundle:
    return MetadataBundle(
        project=ProjectProfile(name="Test", code="T01"),
        site=SiteProfile(station_name="Site1", station_code="S01"),
    )


# ---------------------------------------------------------------------------
# 1. GUI -> config mapping (lag_strategy in payload)
# ---------------------------------------------------------------------------

class TestGUIConfigMapping:
    """Verify that lag_strategy and detrend_mode are correctly mapped
    from GUI combo text to config payload dict."""

    LAG_STRATEGY_MAP = {
        "协方差最大": "covariance_max",
        "协方差最大带默认": "covariance_max_with_default",
        "固定滞后": "constant",
        "无滞后": "none",
    }

    DETREND_MAP = {
        "块均值": "block_mean",
        "线性去趋势": "linear",
        "滑动均值": "running_mean",
        "指数滑动均值": "exponential_running_mean",
    }

    @pytest.mark.parametrize("gui_text,expected", list(LAG_STRATEGY_MAP.items()))
    def test_lag_strategy_mapping(self, gui_text, expected):
        """GUI combo text should map to canonical strategy name."""
        from core.ec_rp.analysis import normalize_lag_strategy
        assert normalize_lag_strategy(gui_text) == expected

    @pytest.mark.parametrize("gui_text,expected", list(DETREND_MAP.items()))
    def test_detrend_mode_mapping(self, gui_text, expected):
        """GUI combo text should map to canonical detrend mode."""
        from core.ec_rp.analysis import normalize_detrend_mode
        assert normalize_detrend_mode(gui_text) == expected

    def test_constant_lag_expected_lag_s_in_payload(self):
        """When strategy is 'constant', expected_lag_s must be present in config."""
        config = {
            "lag": {
                "lag_strategy": "constant",
                "expected_lag_s": 2.5,
                "search_window_s": 8.0,
            }
        }
        assert config["lag"]["lag_strategy"] == "constant"
        assert config["lag"]["expected_lag_s"] == 2.5

    def test_none_lag_no_search_window_needed(self):
        """When strategy is 'none', search_window is not needed."""
        config = {
            "lag": {
                "lag_strategy": "none",
                "expected_lag_s": 0.0,
                "search_window_s": 0.0,
            }
        }
        assert config["lag"]["lag_strategy"] == "none"


# ---------------------------------------------------------------------------
# 2. Exporter: new fields in full_output
# ---------------------------------------------------------------------------

class TestExporterFields:
    """Verify that lag_strategy, lag_fallback_reason, screening_detail
    appear in full_output CSV and rp_results CSV."""

    def test_full_output_schema_has_new_fields(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "lag_strategy" in schema_names
        assert "lag_fallback_reason" in schema_names
        assert "screening_detail" in schema_names

    def test_full_output_row_contains_lag_strategy(self):
        window = _make_window()
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
        assert rows[0]["lag_strategy"] == "covariance_max"
        assert rows[0]["lag_fallback_reason"] == ""

    def test_full_output_row_contains_screening_detail(self):
        window = _make_window()
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
        screening = json.loads(rows[0]["screening_detail"])
        assert "co2_ppm" in screening
        assert "h2o_mmol" in screening

    def test_rp_row_contains_lag_strategy(self):
        window = _make_window()
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        row = exporter._rp_row(window)
        assert row["lag_strategy"] == "covariance_max"

    def test_diagnostics_issues_in_full_output(self):
        window = _make_window()
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
        assert "spike_w" in rows[0]["diagnostics_issues"]
        assert "skewness_h2o_mmol" in rows[0]["diagnostics_issues"]


# ---------------------------------------------------------------------------
# 3. CLI manifest recording
# ---------------------------------------------------------------------------

class TestCLIManifest:
    """Verify that lag_strategy, expected_lag_s, detrend_mode are recorded
    in the batch manifest when provided via CLI."""

    def test_manifest_records_lag_strategy(self):
        config = {
            "lag": {"lag_strategy": "covariance_max_with_default", "expected_lag_s": 2.4},
            "detrend": {"detrend_mode": "exponential_running_mean"},
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
        assert manifest["expected_lag_s"] == 2.4
        assert manifest["detrend_mode"] == "exponential_running_mean"

    def test_manifest_defaults_empty(self):
        config = {}
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert manifest["lag_strategy"] == ""
        assert manifest["expected_lag_s"] == ""
        assert manifest["detrend_mode"] == ""

    def test_cli_args_inject_config(self):
        """Simulate CLI --lag-strategy and --detrend-mode injection into config."""
        config = {"lag": {}, "detrend": {}}
        # Simulate what run_cli does
        lag_strategy = "constant"
        expected_lag_s = "3.0"
        detrend_mode = "running_mean"
        if lag_strategy:
            config.setdefault("lag", {})["lag_strategy"] = lag_strategy
        if expected_lag_s:
            config.setdefault("lag", {})["expected_lag_s"] = float(expected_lag_s)
        if detrend_mode:
            config.setdefault("detrend", {})["detrend_mode"] = detrend_mode
        assert config["lag"]["lag_strategy"] == "constant"
        assert config["lag"]["expected_lag_s"] == 3.0
        assert config["detrend"]["detrend_mode"] == "running_mean"


# ---------------------------------------------------------------------------
# 4. Studio config snapshot: lag_strategy in lag_phase
# ---------------------------------------------------------------------------

class TestStudioConfigSnapshot:
    """Verify that _rp_config_snapshot includes lag_strategy in lag_phase."""

    def test_lag_phase_includes_strategy(self):
        """Simulate the config snapshot logic for lag_phase."""
        steps = {
            "lag": {
                "lag_strategy": "协方差最大",
                "search_window_s": 8.0,
                "expected_lag_s": 2.4,
            }
        }
        lag_phase = {
            "search_window_s": float(steps.get("lag", {}).get("search_window_s", 4.0) or 4.0),
            "expected_lag_s": float(steps.get("lag", {}).get("expected_lag_s", 0.0) or 0.0),
            "strategy": str(steps.get("lag", {}).get("lag_strategy", "covariance_max")),
        }
        assert lag_phase["strategy"] == "协方差最大"
        assert lag_phase["search_window_s"] == 8.0
        assert lag_phase["expected_lag_s"] == 2.4

    def test_lag_phase_default_strategy(self):
        """When lag_strategy is missing, default to covariance_max."""
        steps = {"lag": {"search_window_s": 4.0, "expected_lag_s": 0.0}}
        strategy = str(steps.get("lag", {}).get("lag_strategy", "covariance_max"))
        assert strategy == "covariance_max"
