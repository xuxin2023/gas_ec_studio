from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 25, 8, 0, 0)
    axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.45 * np.sin(2.0 * np.pi * 0.18 * axis) + 0.08 * np.cos(2.0 * np.pi * 0.71 * axis)
    co2 = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 1.0 * axis)
    h2o = 0.7 * np.roll(w, 2)
    rows: list[NormalizedHFFrame] = []
    for index, seconds in enumerate(axis):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(seconds)),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o[index]),
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps({"u": 2.2, "v": 0.2, "w": float(w[index])}),
            )
        )
    return rows


def _rows_with_cell_thermodynamics(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 25, 9, 0, 0)
    axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.42 * np.sin(2.0 * np.pi * 0.20 * axis) + 0.05 * np.cos(2.0 * np.pi * 0.55 * axis)
    co2 = np.roll(w, 3) + 0.02 * np.sin(2.0 * np.pi * 0.9 * axis)
    h2o = 0.5 * np.roll(w, 1)
    rows: list[NormalizedHFFrame] = []
    for index, seconds in enumerate(axis):
        payload = {
            "u": 2.4,
            "v": 0.1,
            "w": float(w[index]),
            "cell_pressure_kpa": float(101.2 + 0.04 * w[index]),
            "cell_temperature_c": float(26.0 + 0.9 * w[index]),
        }
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(seconds)),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 7.0 * co2[index]),
                h2o_mmol=float(12.0 + 0.9 * h2o[index]),
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps(payload),
            )
        )
    return rows


def test_flux_correction_ledger_is_written_to_window_summary_and_artifacts() -> None:
    result = ECRPPipeline().run(
        rows=_rows(),
        project=ProjectProfile(),
        site=SiteProfile(),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "density_correction_mode": "wpl",
            "spectral_correction": {"enabled": True, "method": "massman"},
            "uncertainty": {"method": "mann_lenschow", "confidence_level": 0.95},
        },
    )

    assert result.windows
    ledger = result.windows[0].diagnostics["flux_correction_ledger"]
    assert ledger["artifact_type"] == "flux_correction_ledger_window_v1"
    assert ledger["primary_flux_source"] == "wpl"
    assert {stage["stage"] for stage in ledger["stages"]} >= {
        "raw_covariance",
        "mixing_ratio_flux",
        "density_correction",
        "primary_flux_selection",
    }
    assert result.summary["flux_correction_ledger_summary"]["status"] == "ok"
    assert result.artifacts["flux_correction_ledger"]["summary"]["ledger_window_count"] == len(result.windows)


def test_closed_path_cell_thermodynamics_feed_density_level_and_exports(tmp_path) -> None:
    result = ECRPPipeline().run(
        rows=_rows_with_cell_thermodynamics(),
        project=ProjectProfile(),
        site=SiteProfile(),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "rotation_mode": "none",
            "density_correction_mode": "wpl",
        },
    )

    assert result.windows
    window = result.windows[0]
    diagnostics = window.diagnostics
    assert diagnostics["cell_thermodynamics_status"] == "available"
    assert diagnostics["cell_thermodynamics_source"] == "raw_payload"
    assert diagnostics["wpl_sensible_heat_source"] == "cell_temperature"
    assert abs(diagnostics["cov_w_cell_temp_c"]) > 1e-4
    assert abs(diagnostics["closed_path_cell_temperature_term"]) > 1e-10
    assert abs(diagnostics["closed_path_cell_pressure_term"]) > 1e-10

    ledger = diagnostics["flux_correction_ledger"]
    stages = {stage["stage"]: stage for stage in ledger["stages"]}
    assert "closed_path_cell_thermodynamics" in stages
    assert stages["closed_path_cell_thermodynamics"]["inputs"]["applied_to_density_corrected_flux"] is True
    assert "closed_path_cell_pressure_term" in stages["density_correction"]["inputs"]

    expected_density_flux = (
        window.raw_flux
        + diagnostics["wpl_water_vapor_term"]
        + diagnostics["wpl_sensible_heat_term"]
        + diagnostics["closed_path_cell_pressure_term"]
    )
    assert window.density_corrected_flux == pytest.approx(expected_density_flux)
    assert result.summary["flux_correction_ledger_summary"]["closed_path_cell_thermodynamics_window_count"] == len(result.windows)

    exporter = ResultExporter(tmp_path)
    rp_row = exporter._rp_row(window)
    full_row = exporter._full_output_rows(rp_result=result, spectral_result=None, mode="full_output")[0]
    assert rp_row["cell_thermodynamics_status"] == "available"
    assert rp_row["closed_path_density_term"] == diagnostics["closed_path_density_term"]
    assert full_row["cell_thermodynamics_status"] == "available"
    assert full_row["closed_path_cell_pressure_term"] == diagnostics["closed_path_cell_pressure_term"]


def test_energy_water_and_momentum_fluxes_use_eddypro_network_units(tmp_path) -> None:
    rows = _rows()
    for index, row in enumerate(rows):
        row.chamber_temp_c = 25.0 + 0.6 * float(np.sin(2.0 * np.pi * 0.17 * index / 10.0))
        row.case_temp_c = row.chamber_temp_c - 0.1
    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(),
        site=SiteProfile(),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "rotation_mode": "none",
            "density_correction_mode": "wpl",
            "network_output": {"schema_target": "FLUXNET"},
        },
    )

    assert result.windows
    window = result.windows[0]
    diagnostics = window.diagnostics
    assert diagnostics["sensible_heat_flux_w_m2"] != 0.0
    assert diagnostics["latent_heat_flux_w_m2"] != 0.0
    assert diagnostics["evapotranspiration_rate_mm_h"] != 0.0
    assert diagnostics["momentum_flux_kg_m_s2"] is not None

    expected_le = window.water_vapor_flux * 1.0e-3 * 0.01801528 * diagnostics["latent_heat_vaporization_j_kg"]
    expected_tau = diagnostics["air_density_kg_m3"] * (window.ustar or 0.0) ** 2
    assert diagnostics["latent_heat_flux_w_m2"] == pytest.approx(expected_le)
    assert diagnostics["momentum_flux_kg_m_s2"] == pytest.approx(expected_tau)
    assert diagnostics["latent_heat_flux_w_m2"] != pytest.approx(window.water_vapor_flux)

    ledger = diagnostics["flux_correction_ledger"]
    assert "energy_water_momentum_fluxes" in {stage["stage"] for stage in ledger["stages"]}

    exporter = ResultExporter(tmp_path)
    rp_row = exporter._rp_row(window)
    full_row = exporter._full_output_rows(rp_result=result, spectral_result=None, mode="full_output")[0]
    network_row = exporter._fluxnet_half_hourly_row(
        window=window,
        timezone_offset_hours=0.0,
        timestamp_refers_to="start",
        gap_fill_value=-9999.0,
    )
    assert rp_row["latent_heat_flux_w_m2"] == diagnostics["latent_heat_flux_w_m2"]
    assert full_row["sensible_heat_flux_w_m2"] == diagnostics["sensible_heat_flux_w_m2"]
    assert network_row["LE"] == diagnostics["latent_heat_flux_w_m2"]
    assert network_row["H"] == diagnostics["sensible_heat_flux_w_m2"]
    assert network_row["ET"] == diagnostics["evapotranspiration_rate_mm_h"]
    assert network_row["TAU"] == diagnostics["momentum_flux_kg_m_s2"]
