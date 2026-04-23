from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from core.ec_fcc.pipeline import ECFCCPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(*, sample_hz: float = 10.0, samples: int = 512, include_horizontal_wind: bool = True) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.3 + 0.20 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.32 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    vertical = np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.35 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    co2_signal = np.roll(vertical, 6) + 0.05 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, 4) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.12 * vertical
    chamber = 25.0 + 0.3 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    case = 24.7 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        payload = {"w": float(vertical[index])}
        if include_horizontal_wind:
            payload["u"] = float(u[index])
            payload["v"] = float(v[index])
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-fcc",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(chamber[index]),
                case_temp_c=float(case[index]),
                raw_text=json.dumps(payload),
            )
        )
    return rows


def test_fcc_transfer_components_present_with_complete_metadata() -> None:
    pipeline = ECFCCPipeline()
    result = pipeline.run(
        rows=_make_rows(),
        project=ProjectProfile(code="PRJ-FCC", name="FCC Transfer"),
        site=SiteProfile(station_code="SITE-FCC", station_name="FCC Site"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "lag_phase": {"search_window_s": 3.0, "expected_lag_s": 0.6},
            "correction_factor": {"factor_cap": 1.4},
            "transfer_function": {
                "tube_length_m": 12.0,
                "tube_diameter_mm": 4.0,
                "flow_lpm": 8.5,
                "sensor_separation_m": 0.35,
                "path_length_m": 0.12,
            },
        },
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )

    assert result.windows
    window = result.windows[0]
    assert window.transfer_function_components
    assert window.correction_factor_components
    assert window.total_transfer_function_freq
    assert window.total_transfer_function_value
    assert set(window.transfer_function_components.keys()) == {
        "tube_attenuation",
        "sensor_separation",
        "path_averaging",
        "phase_term",
        "low_pass_total",
    }
    assert set(window.correction_factor_components.keys()) == {
        "base_factor",
        "tube_component",
        "separation_component",
        "path_component",
        "phase_component",
        "total_factor",
    }
    assert result.summary["average_tube_component"] > 0.0
    assert result.summary["average_separation_component"] > 0.0
    assert result.summary["average_path_component"] > 0.0
    assert result.summary["average_phase_component"] > 0.0


def test_fcc_transfer_components_fallback_with_missing_metadata() -> None:
    pipeline = ECFCCPipeline()
    result = pipeline.run(
        rows=_make_rows(include_horizontal_wind=False),
        project=ProjectProfile(),
        site=SiteProfile(),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "lag_phase": {"search_window_s": 3.0},
            "correction_factor": {"factor_cap": 1.35},
        },
        data_source="unit-test",
        time_range="missing-metadata",
    )

    assert result.windows
    window = result.windows[0]
    assert window.transfer_function_components
    assert window.correction_factor_components
    assert window.provenance_notes
    assert any("fallback" in note or "unavailable" in note or "default" in note for note in window.provenance_notes)
    assert window.transfer_function_components["tube_attenuation"]["enabled"] is False
    assert window.model_version.startswith("fcc_transfer_components_v1")
