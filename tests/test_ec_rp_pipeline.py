from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from core.ec_rp.pipeline import ECRPPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
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
                raw_text=json.dumps(
                    {
                        "u": float(u[index]),
                        "v": float(v[index]),
                        "w": float(w[index]),
                    }
                ),
            )
        )
    return rows


def test_rp_pipeline_generates_window_results() -> None:
    pipeline = ECRPPipeline()
    result = pipeline.run(
        rows=_make_rows(),
        project=ProjectProfile(code="PRJ-001", name="RP Test"),
        site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
        config={
            "steps": {
                "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                "rotation": {"rotation_mode": "双旋转"},
                "detrend": {"detrend_mode": "线性去趋势"},
            }
        },
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )

    assert result.summary["status"] == "ok"
    assert len(result.windows) >= 1

    window = result.windows[0]
    assert window.qc_grade in {"A", "B", "C"}
    assert window.anomaly_type != ""
    assert window.reason != ""
    assert window.qc_reasons
    assert window.rotation_mode == "double"
    assert window.detrend_mode == "linear"
    assert np.isfinite(window.raw_flux)
    assert np.isfinite(window.density_corrected_flux)
    assert "lag_curve_x" in window.diagnostics
    assert "lag_curve_y" in window.diagnostics


def test_rp_pipeline_builds_and_applies_h2o_rh_lag_profile() -> None:
    rows = _make_rows(samples=600)
    for index, row in enumerate(rows):
        fluctuation = float(row.h2o_mmol or 0.0) - 12.0
        row.h2o_mmol = (6.0 if index < 300 else 20.0) + fluctuation

    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-RH", name="RH lag test"),
        site=SiteProfile(station_code="SITE-RH", station_name="RH lag site"),
        config={
            "steps": {
                "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
                "lag": {
                    "search_window_s": 1.5,
                    "lag_strategy": "covariance_max",
                    "h2o_rh_optimization": {
                        "enabled": True,
                        "class_count": 2,
                        "min_samples_per_class": 1,
                        "mad_multiplier": 3.5,
                    },
                },
            }
        },
        data_source="unit-test",
        time_range="two-rh-classes",
    )

    profile = result.artifacts["h2o_rh_lag_profile"]
    assert profile["status"] == "ready"
    assert profile["source"] == "current_run_first_pass"
    assert profile["measured_class_count"] == 2
    assert result.summary["h2o_rh_lag_profile"]["status"] == "ready"
    assert len(result.windows) == 2
    for window in result.windows:
        selection = window.diagnostics["h2o_rh_lag_selection"]
        assert window.diagnostics["h2o_rh_lag_status"] == "applied"
        assert selection["source"] == "measured"
        assert window.diagnostics["h2o_lag_seconds"] == pytest.approx(selection["h2o_lag_s"])


def test_rp_pipeline_returns_empty_for_empty_input() -> None:
    pipeline = ECRPPipeline()
    result = pipeline.run(
        rows=[],
        project=ProjectProfile(),
        site=SiteProfile(),
        config={"sample_hz": 10.0, "block_minutes": 0.5},
        data_source="unit-test",
        time_range="empty",
    )

    assert result.summary["status"] == "empty"
    assert result.windows == []


def test_rp_pipeline_marks_constant_window_with_qc_reason() -> None:
    rows = _make_rows(samples=240)
    for row in rows:
        row.co2_ppm = 410.0
        row.h2o_mmol = 12.0

    pipeline = ECRPPipeline()
    result = pipeline.run(
        rows=rows,
        project=ProjectProfile(),
        site=SiteProfile(),
        config={"sample_hz": 10.0, "block_minutes": 0.4, "rotation_mode": "none", "detrend_mode": "block mean"},
        data_source="unit-test",
        time_range="constant",
    )

    assert len(result.windows) >= 1
    assert result.windows[0].qc_grade == "C"
    assert result.windows[0].anomaly_type in {"constant_signal", "minor_attention"}
    assert result.windows[0].reason != ""
    assert result.windows[0].qc_reasons
