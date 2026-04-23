from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from core.ec_fcc.pipeline import ECFCCPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(sample_hz: float = 10.0, samples: int = 512) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    vertical = np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.35 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    co2_signal = np.roll(vertical, 6) + 0.05 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, 4) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.12 * vertical
    chamber = 25.0 + 0.3 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    case = 24.7 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(chamber[index]),
                case_temp_c=float(case[index]),
                raw_text=json.dumps({"w": float(vertical[index])}),
            )
        )
    return rows


def test_pipeline_generates_real_window_results() -> None:
    pipeline = ECFCCPipeline()
    result = pipeline.run(
        rows=_make_rows(),
        project=ProjectProfile(code="PRJ-001", name="Spectral Test"),
        site=SiteProfile(station_code="SITE-001", station_name="Test Site"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "lag_phase": {"search_window_s": 3.0, "expected_lag_s": 0.6},
            "correction_factor": {"factor_cap": 1.4},
        },
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )

    assert result.summary["status"] == "ok"
    assert len(result.windows) >= 1

    window = result.windows[0]
    assert len(window.lag_curve_x) > 0
    assert len(window.lag_curve_y) > 0
    assert len(window.power_freq) > 0
    assert len(window.power_measured) > 0
    assert len(window.power_ref) > 0
    assert len(window.cross_freq) > 0
    assert len(window.cross_value) > 0
    assert len(window.ogive_freq) > 0
    assert len(window.ogive_value) > 0
    assert window.qc_grade in {"A", "B", "C"}
    assert window.correction_factor > 0.0


def test_pipeline_returns_empty_result_for_insufficient_input() -> None:
    pipeline = ECFCCPipeline()
    result = pipeline.run(
        rows=_make_rows(samples=24),
        project=ProjectProfile(),
        site=SiteProfile(),
        config={"sample_hz": 10.0, "block_minutes": 0.5},
        data_source="unit-test",
        time_range="short-range",
    )

    assert result.summary["status"] == "empty"
    assert result.windows == []
