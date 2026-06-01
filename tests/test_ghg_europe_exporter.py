from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from core.exports.result_exporter import (
    GHG_EUROPE_FIELD_MAP,
    NETWORK_SCHEMA_REGISTRY,
    ResultExporter,
    validate_fluxnet_row,
)
from models.rp_models import RPRunResult, WindowRPResult


def _make_rp_result() -> RPRunResult:
    start = datetime(2025, 7, 15, 0, 0, 0)
    window = WindowRPResult(
        window_id="w001",
        start_time=start,
        end_time=start + timedelta(minutes=30),
        sample_count=18000,
        valid_sample_count=17920,
        continuity_ratio=0.995,
        missing_ratio=0.005,
        rotation_mode="double",
        detrend_mode="block_mean",
        lag_seconds=2.2,
        lag_confidence=0.91,
        cov_w_co2=-0.001,
        cov_w_h2o=0.0005,
        raw_flux=-3.5,
        mixing_ratio_flux=-3.4,
        density_corrected_flux=-3.45,
        water_vapor_flux=0.012,
        air_molar_density=41.5,
        dry_air_molar_density=41.3,
        mean_co2_ppm=415.0,
        mean_h2o_mmol=12.5,
        mean_pressure_kpa=101.3,
        mean_temp_c=22.5,
        primary_flux=-3.45,
        primary_flux_source="wpl",
        qc_grade="A",
        anomaly_type="",
        reason="",
        ustar=0.35,
        stationarity_score=88.0,
        turbulence_score=91.0,
        diagnostics={
            "sensible_heat_flux_w_m2": 44.2,
            "latent_heat_flux_w_m2": 96.5,
            "evapotranspiration_rate_mm_h": 0.14,
            "momentum_flux_kg_m_s2": 0.11,
            "footprint_method": "kljun",
            "footprint_peak_distance_m": 58.0,
            "footprint_contribution_distances": {"70": 180.0, "90": 420.0},
            "uncertainty_method": "mann_lenschow",
            "spectral_correction_method": "massman",
            "primary_flux_random_error": 0.18,
            "primary_flux_relative_uncertainty": 0.052,
        },
    )
    return RPRunResult(
        run_id="ghg_europe_test",
        created_at=start,
        data_source="unit-test",
        time_range="2025-07-15T00:00/2025-07-15T00:30",
        summary={},
        windows=[window],
    )


def test_ghg_europe_schema_registry_is_available() -> None:
    assert "GHG-Europe" in NETWORK_SCHEMA_REGISTRY
    assert GHG_EUROPE_FIELD_MAP["FC_QC"] == "FC_SSITC_TEST"
    assert GHG_EUROPE_FIELD_MAP["FETCH_90"] == "FETCH_90"

    errors = validate_fluxnet_row(
        {"TIMESTAMP_START": "202507150000", "FC": -3.45, "FC_SSITC_TEST": 0, "DOY": 196},
        schema_target="GHG-Europe",
    )
    assert errors == []


def test_ghg_europe_export_writes_legacy_json_and_csv(tmp_path: Path) -> None:
    exporter = ResultExporter(tmp_path)
    path = exporter.export_ghg_europe_artifact(
        rp_result=_make_rp_result(),
        export_root=tmp_path,
        timezone_offset_hours=2.0,
        site_id="DE-Test",
    )

    assert path is not None
    assert path.exists()
    csv_path = tmp_path / "ghg_europe_legacy_artifact.csv"
    assert csv_path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["metadata"]["schema_target"] == "GHG-Europe"
    assert payload["metadata"]["validation_status"] == "pass"
    assert payload["rows"][0]["TIMESTAMP_START"] == "202507150200"
    assert payload["rows"][0]["FC_SSITC_TEST"] == 0
    assert payload["rows"][0]["NEE_PI"] == payload["rows"][0]["FC"]
    assert payload["rows"][0]["FETCH_70"] == 180.0
    assert payload["rows"][0]["FETCH_90"] == 420.0
    assert payload["rows"][0]["FETCH_FILTER"] == 1
    assert "FETCH_70" not in payload["metadata"]["missing_fields"]
    assert payload["method_provenance_rows"][0]["FOOTPRINT_METHOD"] == "kljun"
    assert "NEE_PI" in csv_path.read_text(encoding="utf-8")


def test_network_artifact_router_supports_ghg_europe(tmp_path: Path) -> None:
    exporter = ResultExporter(tmp_path)
    summary, files = exporter._export_network_artifacts(
        rp_result=_make_rp_result(),
        rp_config_snapshot={
            "network_output": {
                "schema_target": "GHG-Europe",
                "timezone_offset_hours": 2.0,
                "timestamp_refers_to": "start",
            }
        },
        export_root=tmp_path,
    )

    assert summary["schema_target"] == "GHG-Europe"
    assert summary["validation_status"] == "pass"
    assert Path(files["ghg_europe_artifact"]).exists()
    assert Path(files["ghg_europe_csv"]).exists()
    assert Path(files["network_validation_summary"]).exists()
