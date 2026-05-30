"""Tests for core/ec_rp/analysis.py: normalize, detrend, lag strategy, statistical screening."""
from __future__ import annotations

import numpy as np
import pytest

from core.ec_rp.analysis import (
    analyze_lag,
    apply_lag,
    normalize_detrend_mode,
    normalize_lag_strategy,
    normalize_rotation_mode,
    pick_window_slices,
    run_statistical_screening,
    _detrend,
)


# ---------------------------------------------------------------------------
# normalize_rotation_mode
# ---------------------------------------------------------------------------

class TestNormalizeRotationMode:
    def test_standard_values(self) -> None:
        assert normalize_rotation_mode("none") == "none"
        assert normalize_rotation_mode("single") == "single"
        assert normalize_rotation_mode("double") == "double"

    def test_chinese_aliases(self) -> None:
        assert normalize_rotation_mode("双旋转") == "double"
        assert normalize_rotation_mode("单旋转") == "single"
        assert normalize_rotation_mode("不旋转") == "none"

    def test_unknown_falls_back(self) -> None:
        assert normalize_rotation_mode("unknown") == "double"
        assert normalize_rotation_mode("unknown", default="none") == "none"


# ---------------------------------------------------------------------------
# normalize_detrend_mode
# ---------------------------------------------------------------------------

class TestNormalizeDetrendMode:
    def test_standard_values(self) -> None:
        assert normalize_detrend_mode("block_mean") == "block_mean"
        assert normalize_detrend_mode("linear") == "linear"
        assert normalize_detrend_mode("running_mean") == "running_mean"
        assert normalize_detrend_mode("exponential_running_mean") == "exponential_running_mean"

    def test_chinese_aliases(self) -> None:
        assert normalize_detrend_mode("线性去趋势") == "linear"
        assert normalize_detrend_mode("滑动均值") == "running_mean"
        assert normalize_detrend_mode("指数滑动均值") == "exponential_running_mean"
        assert normalize_detrend_mode("块均值") == "block_mean"

    def test_short_aliases(self) -> None:
        assert normalize_detrend_mode("ewma") == "exponential_running_mean"
        assert normalize_detrend_mode("running") == "running_mean"

    def test_unknown_falls_back(self) -> None:
        assert normalize_detrend_mode("unknown") == "block_mean"


# ---------------------------------------------------------------------------
# normalize_lag_strategy
# ---------------------------------------------------------------------------

class TestNormalizeLagStrategy:
    def test_standard_values(self) -> None:
        assert normalize_lag_strategy("none") == "none"
        assert normalize_lag_strategy("constant") == "constant"
        assert normalize_lag_strategy("covariance_max") == "covariance_max"
        assert normalize_lag_strategy("covariance_max_with_default") == "covariance_max_with_default"

    def test_chinese_aliases(self) -> None:
        assert normalize_lag_strategy("无滞后") == "none"
        assert normalize_lag_strategy("固定滞后") == "constant"
        assert normalize_lag_strategy("协方差最大") == "covariance_max"
        assert normalize_lag_strategy("协方差最大带默认") == "covariance_max_with_default"

    def test_short_aliases(self) -> None:
        assert normalize_lag_strategy("cov_max") == "covariance_max"
        assert normalize_lag_strategy("fixed") == "constant"
        assert normalize_lag_strategy("no_lag") == "none"

    def test_unknown_falls_back(self) -> None:
        assert normalize_lag_strategy("unknown") == "covariance_max"


# ---------------------------------------------------------------------------
# _detrend extensions
# ---------------------------------------------------------------------------

class TestDetrend:
    def test_block_mean(self) -> None:
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _detrend(values, mode="block_mean")
        assert abs(float(np.mean(result))) < 1e-10

    def test_linear(self) -> None:
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _detrend(values, mode="linear")
        assert abs(float(np.mean(result))) < 1e-10

    def test_running_mean(self) -> None:
        n = 300
        t = np.linspace(0, 1, n)
        values = 5.0 * t + 0.1 * np.sin(2.0 * np.pi * 3.0 * t)
        result = _detrend(values, mode="running_mean")
        assert abs(float(np.mean(result))) < 1.0

    def test_exponential_running_mean(self) -> None:
        n = 300
        t = np.linspace(0, 1, n)
        values = 5.0 * t + 0.1 * np.sin(2.0 * np.pi * 3.0 * t)
        result = _detrend(values, mode="exponential_running_mean")
        assert abs(float(np.mean(result))) < 1.0

    def test_short_series_fallback(self) -> None:
        values = np.array([1.0, 2.0])
        result = _detrend(values, mode="running_mean")
        assert result.size == 2

    def test_constant_series(self) -> None:
        values = np.ones(100) * 42.0
        result = _detrend(values, mode="block_mean")
        assert abs(float(np.mean(result))) < 1e-10


def test_pick_window_slices_keeps_exact_averaging_period_as_one_window() -> None:
    slices = pick_window_slices(total_samples=18_000, sample_rate_hz=10.0, block_minutes=30.0)

    assert slices == [(0, 18_000)]


# ---------------------------------------------------------------------------
# analyze_lag strategies
# ---------------------------------------------------------------------------

class TestAnalyzeLagStrategies:
    @pytest.fixture()
    def synthetic_data(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = 600
        sample_hz = 10.0
        t = np.arange(n, dtype=float) / sample_hz
        w = 0.5 * np.sin(2.0 * np.pi * 0.2 * t)
        co2 = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.0 * t)
        h2o = 0.7 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.8 * t)
        return w, co2, h2o

    def test_none_strategy(self, synthetic_data: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        w, co2, h2o = synthetic_data
        result = analyze_lag(w, co2, h2o, sample_rate_hz=10.0, search_window_s=1.5, lag_strategy="none")
        assert result.lag_seconds == 0.0
        assert result.confidence == 1.0
        assert result.co2_lag_seconds == 0.0
        assert result.h2o_lag_seconds == 0.0

    def test_constant_strategy(self, synthetic_data: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        w, co2, h2o = synthetic_data
        result = analyze_lag(w, co2, h2o, sample_rate_hz=10.0, search_window_s=1.5, lag_strategy="constant", expected_lag_s=0.5)
        assert result.lag_seconds == 0.5
        assert result.confidence == 1.0

    def test_covariance_max_strategy(self, synthetic_data: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        w, co2, h2o = synthetic_data
        result = analyze_lag(w, co2, h2o, sample_rate_hz=10.0, search_window_s=1.5, lag_strategy="covariance_max")
        assert result.confidence > 0.0
        assert len(result.lag_curve_x) > 0
        assert len(result.lag_curve_y) > 0

    def test_covariance_max_with_default_high_confidence(self, synthetic_data: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        w, co2, h2o = synthetic_data
        result = analyze_lag(w, co2, h2o, sample_rate_hz=10.0, search_window_s=1.5, lag_strategy="covariance_max_with_default", expected_lag_s=0.5, confidence_threshold=0.01)
        # With very low threshold, should use covariance_max result
        assert len(result.lag_curve_x) > 0

    def test_covariance_max_with_default_low_confidence_fallback(self) -> None:
        n = 100
        rng = np.random.default_rng(42)
        w = rng.standard_normal(n)
        co2 = rng.standard_normal(n)  # uncorrelated
        h2o = rng.standard_normal(n)  # uncorrelated
        result = analyze_lag(w, co2, h2o, sample_rate_hz=10.0, search_window_s=1.5, lag_strategy="covariance_max_with_default", expected_lag_s=0.5, confidence_threshold=0.99)
        # With very high threshold, should fall back to expected_lag_s
        assert result.lag_seconds == 0.5


# ---------------------------------------------------------------------------
# apply_lag
# ---------------------------------------------------------------------------

class TestApplyLag:
    def test_zero_lag(self) -> None:
        series = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_lag(series, 0.0, 10.0)
        np.testing.assert_array_equal(result, series)

    def test_positive_lag(self) -> None:
        series = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_lag(series, 0.1, 10.0)  # 1 sample shift
        assert result[0] == 1.0  # filled with first value
        assert result[1] == 1.0
        assert result[2] == 2.0


# ---------------------------------------------------------------------------
# run_statistical_screening
# ---------------------------------------------------------------------------

class TestStatisticalScreening:
    def test_constant_signal(self) -> None:
        values = np.ones(120, dtype=float) * 410.0
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_constant" in result["issues"]

    def test_spike(self) -> None:
        values = np.ones(120, dtype=float) * 410.0
        values[40] = 900.0
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_spike" in result["issues"]

    def test_dropout(self) -> None:
        values = np.linspace(410.0, 412.0, 120, dtype=float)
        values[30:50] = 411.2
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_dropout" in result["issues"]

    def test_absolute_limit(self) -> None:
        values = np.linspace(410.0, 415.0, 120, dtype=float)
        values[10] = 1800.0
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_absolute_limit" in result["issues"]

    def test_discontinuity(self) -> None:
        values = np.concatenate([np.full(60, 410.0), np.full(60, 470.0)]).astype(float)
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_discontinuity" in result["issues"]

    def test_skewness(self) -> None:
        rng = np.random.default_rng(42)
        # Exponential distribution is highly right-skewed (skewness = 2)
        values = rng.exponential(5.0, 500) + 410.0
        result = run_statistical_screening({"co2_ppm": values}, skewness_threshold=1.5)
        assert "co2_ppm_skewness" in result["issues"]

    def test_kurtosis(self) -> None:
        rng = np.random.default_rng(42)
        values = rng.standard_cauchy(500) * 0.01 + 410.0  # heavy tails
        result = run_statistical_screening({"co2_ppm": values}, kurtosis_threshold=3.0)
        assert "co2_ppm_kurtosis" in result["issues"]

    def test_empty_series(self) -> None:
        result = run_statistical_screening({"co2_ppm": np.array([], dtype=float)})
        assert "co2_ppm_missing" in result["issues"]

    def test_all_nan_series(self) -> None:
        values = np.full(100, np.nan)
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm_missing" in result["issues"]

    def test_detail_contains_provenance(self) -> None:
        values = np.ones(120, dtype=float) * 410.0
        result = run_statistical_screening({"co2_ppm": values})
        assert "co2_ppm" in result["detail"]
        assert "constant" in result["detail"]["co2_ppm"]

    def test_clean_series_no_issues(self) -> None:
        rng = np.random.default_rng(42)
        values = rng.normal(410.0, 5.0, 300)
        result = run_statistical_screening({"co2_ppm": values}, skewness_threshold=10.0, kurtosis_threshold=100.0)
        assert not any("constant" in issue for issue in result["issues"])
        assert not any("spike" in issue for issue in result["issues"])
