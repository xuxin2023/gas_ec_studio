from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from core.ec_rp.analysis import run_statistical_screening
from core.ec_rp.pipeline import ECRPPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _base_rows(samples: int = 240, sample_hz: float = 10.0) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.45 * np.sin(2.0 * np.pi * 0.2 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-qc",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 3.0 * w[index]),
                h2o_mmol=float(12.0 + 0.5 * w[index]),
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps({"u": 2.0, "v": 0.2, "w": float(w[index])}),
            )
        )
    return rows


def test_statistical_screening_flags_spike() -> None:
    values = np.ones(120, dtype=float) * 410.0
    values[40] = 900.0
    result = run_statistical_screening({"co2_ppm": values})
    assert "co2_ppm_spike" in result["issues"]
    assert any("spike" in item for item in result["qc_reasons"])


def test_statistical_screening_flags_dropout() -> None:
    values = np.linspace(410.0, 412.0, 120, dtype=float)
    values[30:50] = 411.2
    result = run_statistical_screening({"co2_ppm": values})
    assert "co2_ppm_dropout" in result["issues"]


def test_statistical_screening_flags_absolute_limit() -> None:
    values = np.linspace(410.0, 415.0, 120, dtype=float)
    values[10] = 1800.0
    result = run_statistical_screening({"co2_ppm": values})
    assert "co2_ppm_absolute_limit" in result["issues"]


def test_statistical_screening_flags_discontinuity() -> None:
    values = np.concatenate([np.full(60, 410.0), np.full(60, 470.0)]).astype(float)
    result = run_statistical_screening({"co2_ppm": values})
    assert "co2_ppm_discontinuity" in result["issues"]


def test_pipeline_outputs_qc_reasons_list() -> None:
    rows = _base_rows()
    for index in range(30, 50):
        rows[index].co2_ppm = 411.0
    rows[80].co2_ppm = 1800.0

    pipeline = ECRPPipeline()
    result = pipeline.run(
        rows=rows,
        project=ProjectProfile(code="PRJ-QC", name="QC Test"),
        site=SiteProfile(station_code="SITE-QC", station_name="QC Site"),
        config={"sample_hz": 10.0, "block_minutes": 0.4, "rotation_mode": "none", "detrend_mode": "block mean"},
        data_source="unit-test",
        time_range="qc-window",
    )

    assert result.windows
    window = result.windows[0]
    assert window.qc_grade in {"A", "B", "C"}
    assert window.qc_reasons
    assert isinstance(window.qc_reasons, list)
    assert "qc_reasons" in window.diagnostics
