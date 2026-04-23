from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from core.ec_rp.pipeline import ECRPPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(
    *,
    sample_hz: float = 10.0,
    samples: int = 480,
    include_horizontal_wind: bool = True,
    include_vertical_wind: bool = True,
) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.6 + 0.22 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.42 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.10 * np.cos(2.0 * np.pi * 0.61 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 1.0 * time_axis)
    h2o_signal = 0.7 * np.roll(w, 2) + 0.02 * np.cos(2.0 * np.pi * 0.8 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        payload: dict[str, float] = {}
        if include_horizontal_wind:
            payload["u"] = float(u[index])
            payload["v"] = float(v[index])
        if include_vertical_wind:
            payload["w"] = float(w[index])
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-rp-qc",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 6.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.1 * h2o_signal[index]),
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps(payload),
            )
        )
    return rows


def _run_pipeline(rows: list[NormalizedHFFrame], *, sample_hz: float, block_minutes: float = 0.4):
    return ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-QC-MX", name="RP QC Matrix"),
        site=SiteProfile(station_code="SITE-QC-MX", station_name="QC Matrix Site"),
        config={"sample_hz": sample_hz, "block_minutes": block_minutes, "rotation_mode": "double", "detrend_mode": "linear", "lag": {"search_window_s": 1.5}},
        data_source="unit-test",
        time_range="rp-qc-matrix",
    )


def test_rp_qc_matrix_outputs_stationarity_turbulence_and_grade() -> None:
    result = _run_pipeline(_make_rows(), sample_hz=10.0)
    assert result.windows
    window = result.windows[0]
    assert window.stationarity_score is not None
    assert window.turbulence_score is not None
    assert window.ustar is not None
    assert window.qc_matrix
    assert window.qc_grade in {"A", "B", "C"}
    assert "stationarity" in window.qc_matrix
    assert "turbulence" in window.qc_matrix


def test_rp_qc_matrix_gracefully_falls_back_for_insufficient_data() -> None:
    rows = _make_rows(sample_hz=4.0, samples=80, include_horizontal_wind=False, include_vertical_wind=True)
    result = _run_pipeline(rows, sample_hz=4.0, block_minutes=0.33)
    assert result.windows
    window = result.windows[0]
    assert window.turbulence_score is None
    assert window.ustar is None
    assert window.stationarity_score is None
    assert any("stationarity" in reason for reason in window.qc_reasons)
    assert any("turbulence" in reason for reason in window.qc_reasons)
    assert window.qc_matrix["stationarity"]["status"] == "fallback"
    assert window.qc_matrix["turbulence"]["status"] == "fallback"
