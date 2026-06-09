from __future__ import annotations

import json
import math
import struct
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.comparison.raw_to_final_parity import run_raw_to_final_parity_harness, write_raw_to_final_parity_artifact
from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import build_batch_manifest
from models.rp_models import RPRunResult
from models.spectral_models import SpectralRunResult
from models.station_models import MetadataBundle, ProjectProfile, RawFileDescriptionMetadata, RawFileSettingsMetadata, SiteProfile


def test_raw_to_final_parity_harness_passes_manual_raw_csv_oracle(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_fixture(tmp_path)

    artifact = run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=metadata,
        rp_config=config,
        reference_windows=reference_windows,
        fixture_id="synthetic_raw_csv_001",
        thresholds={"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12},
    )

    assert artifact["artifact_type"] == "eddypro_raw_to_final_parity_v1"
    assert artifact["status"] == "pass"
    assert artifact["raw_input"]["row_count"] == 240
    assert artifact["benchmark_summary"]["matched_window_count"] == 1
    assert artifact["benchmark_summary"]["pass_rate"] == 1.0
    assert artifact["benchmark_summary"]["failed_fields"] == []
    assert artifact["parity_diagnostics"]["artifact_type"] == "raw_to_final_parity_diagnostics_v1"
    assert artifact["parity_diagnostics"]["status"] == "ok"
    heatmap_fields = {row["field_name"] for row in artifact["parity_diagnostics"]["field_heatmap"]}
    assert "primary_flux" in heatmap_fields

    path = write_raw_to_final_parity_artifact(artifact, tmp_path / "raw_to_final_parity.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "pass"


def test_raw_to_final_parity_harness_reports_native_tob1_fp2_import(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_fp2_fixture(tmp_path)

    artifact = run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=metadata,
        rp_config=config,
        reference_windows=reference_windows,
        fixture_id="synthetic_raw_tob1_fp2_001",
        thresholds={"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12},
    )

    assert artifact["status"] == "pass"
    assert artifact["raw_input"]["format"] == "tob1"
    assert artifact["raw_input"]["import_summary"]["native"] is True
    assert artifact["raw_input"]["import_summary"]["format"] == "tob1_fp2"
    assert artifact["raw_input"]["import_summary"]["data_type"] == "fp2"
    assert artifact["raw_input"]["import_summary"]["record_count"] == 240
    assert "src/src_common/m_fp2_to_float.f90" in artifact["raw_input"]["import_summary"]["source_reference"]["eddypro_engine_files"]


def test_raw_to_final_parity_harness_compares_li7700_level_sequence(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_ch4_fixture(tmp_path)

    artifact = run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=metadata,
        rp_config=config,
        reference_windows=reference_windows,
        fixture_id="synthetic_li7700_trace_gas_001",
        thresholds={"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12, "trace_gas_rel_threshold": 1e-9},
    )

    trace = artifact["trace_gas_parity"]
    assert artifact["status"] == "pass"
    assert trace["artifact_type"] == "li7700_trace_gas_parity_v1"
    assert trace["status"] == "pass"
    assert trace["method"] == "li_7700_correction_sequence_v1"
    assert trace["coefficient_profile_id"] == "synthetic_li7700_profile"
    assert trace["coefficient_profile_source_file"].endswith("synthetic_li7700_trace_gas.json")
    assert trace["coefficient_profile_normalization_command"] == "gas_ec synthetic-li7700-oracle"
    assert trace["coefficient_profile_limitations"] == ["Synthetic oracle, not a public LI-7700 field fixture."]
    assert trace["provenance_summary"]["artifact_type"] == "trace_gas_parity_provenance_v1"
    assert trace["provenance_summary"]["gases"]["ch4"]["coefficient_profile_normalization_command"] == "gas_ec synthetic-li7700-oracle"
    assert trace["comparison_count"] == 6
    assert trace["pass_rate"] == 1.0
    assert trace["failed_fields"] == []
    compared_fields = {item["field_name"] for item in trace["windows"][0]["comparisons"]}
    assert compared_fields >= {
        "ch4_flux_level0_nmol_m2_s",
        "ch4_flux_level1_spectral_nmol_m2_s",
        "ch4_flux_level2_density_nmol_m2_s",
        "ch4_flux_corrected_nmol_m2_s",
        "ch4_flux_nmol_m2_s",
        "ch4_method",
    }
    assert artifact["actual_windows"][0]["ch4_coefficient_profile_id"] == "synthetic_li7700_profile"
    assert artifact["actual_windows"][0]["ch4_coefficient_profile_normalization_command"] == "gas_ec synthetic-li7700-oracle"
    assert artifact["trace_gas_provenance_summary"]["gases"]["ch4"]["coefficient_profile_source_file"].endswith(
        "synthetic_li7700_trace_gas.json"
    )


def test_raw_to_final_parity_harness_fails_li7700_level_mismatch(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_ch4_fixture(tmp_path)
    reference_windows[0]["ch4_flux_level2_density_nmol_m2_s"] *= 1.25

    artifact = run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=metadata,
        rp_config=config,
        reference_windows=reference_windows,
        fixture_id="synthetic_li7700_trace_gas_wrong_reference",
        thresholds={"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12, "trace_gas_rel_threshold": 1e-9},
    )

    assert artifact["status"] == "fail"
    assert artifact["trace_gas_parity"]["status"] == "fail"
    assert "ch4_flux_level2_density_nmol_m2_s" in artifact["trace_gas_parity"]["failed_fields"]
    assert "ch4_flux_level2_density_nmol_m2_s" in artifact["benchmark_summary"]["failed_fields"]
    diagnostics = artifact["parity_diagnostics"]
    assert diagnostics["status"] == "needs_attention"
    assert "ch4_flux_level2_density_nmol_m2_s" in diagnostics["top_failed_fields"]
    groups = {group["category"]: group for group in diagnostics["failure_groups"]}
    assert "trace_gas_li7700" in groups
    assert "src/src_rp/m_li7700.f90" in groups["trace_gas_li7700"]["eddypro_engine_modules"]


def test_raw_to_final_parity_harness_fails_wrong_reference(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_fixture(tmp_path)
    reference_windows[0]["primary_flux"] *= 1.5

    artifact = run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=metadata,
        rp_config=config,
        reference_windows=reference_windows,
        fixture_id="synthetic_raw_csv_wrong_reference",
        thresholds={"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12},
    )

    assert artifact["status"] == "fail"
    assert "primary_flux" in artifact["benchmark_summary"]["failed_fields"]
    assert artifact["benchmark_summary"]["pass_rate"] < 1.0
    diagnostics = artifact["parity_diagnostics"]
    assert diagnostics["status"] == "needs_attention"
    assert "primary_flux" in diagnostics["top_failed_fields"]
    primary = next(row for row in diagnostics["field_heatmap"] if row["field_name"] == "primary_flux")
    assert primary["category"] == "flux_calculation"
    assert "src/src_rp/m_fluxes.f90" in primary["eddypro_engine_modules"]
    groups = {group["category"]: group for group in diagnostics["failure_groups"]}
    assert "flux_calculation" in groups
    assert "src/src_rp/m_fluxes.f90" in groups["flux_calculation"]["eddypro_engine_modules"]


def test_result_exporter_writes_raw_to_final_parity_artifact_when_enabled(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_fixture(tmp_path)
    config["raw_to_final_parity"] = {
        "enabled": True,
        "fixture_id": "synthetic_raw_csv_001",
        "raw_path": str(raw_path),
        "metadata": metadata.to_dict(),
        "reference_windows": reference_windows,
        "thresholds": {"flux_rel_threshold": 1e-9, "lag_abs_threshold_s": 1e-12},
    }
    artifact_path = ResultExporter(tmp_path).export_raw_to_final_parity_artifact(
        rp_config_snapshot=config,
        export_root=tmp_path,
        report_key="raw_to_final_parity",
    )
    assert artifact_path is not None
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact_path.exists()
    assert payload["status"] == "pass"
    assert payload["fixture_id"] == "synthetic_raw_csv_001"
    assert payload["parity_diagnostics"]["status"] == "ok"


def test_headless_manifest_includes_raw_to_final_parity_when_enabled(tmp_path: Path) -> None:
    raw_path, metadata, reference_windows, config = _raw_fixture(tmp_path)
    config["raw_to_final_parity"] = {
        "enabled": True,
        "fixture_id": "synthetic_raw_csv_001",
        "raw_path": str(raw_path),
        "metadata": metadata.to_dict(),
        "reference_windows": reference_windows,
    }
    created_at = datetime(2026, 5, 27, 8, 0, 0)
    rp_result = RPRunResult(run_id="rp", created_at=created_at, data_source="test", time_range="", windows=[], summary={}, artifacts={})
    spectral_result = SpectralRunResult(run_id="sp", created_at=created_at, data_source="test", time_range="", qc_only=False, windows=[], summary={}, artifacts={})

    manifest = build_batch_manifest(
        batch_id="raw-to-final",
        metadata_bundle=metadata,
        config=config,
        rows=[],
        rp_result=rp_result,
        spectral_result=spectral_result,
    )

    assert manifest["raw_to_final_parity"]["status"] == "pass"
    assert manifest["raw_to_final_parity"]["fixture_id"] == "synthetic_raw_csv_001"
    assert manifest["raw_to_final_parity_diagnostics"]["status"] == "ok"
    assert manifest["raw_to_final_parity_top_failed_fields"] == []


def _raw_fixture(tmp_path: Path) -> tuple[Path, MetadataBundle, list[dict[str, object]], dict[str, object]]:
    sample_hz = 10.0
    samples = 240
    start = datetime(2026, 5, 27, 8, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.62 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.21 * np.cos(2.0 * np.pi * 0.73 * time_axis)
    u = 2.6 + 0.05 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.18 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    co2 = 410.0 + 8.0 * w
    h2o = 12.0 + 1.5 * w
    pressure = 101.3 + 0.03 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.0 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)
    raw_path = tmp_path / "synthetic_raw.csv"
    lines = ["timestamp,co2_ppm,h2o_mmol,pressure_kpa,chamber_temp_c,case_temp_c,u,v,w"]
    for index in range(samples):
        timestamp = start + timedelta(seconds=float(time_axis[index]))
        lines.append(
            ",".join(
                [
                    timestamp.isoformat(),
                    f"{co2[index]:.12f}",
                    f"{h2o[index]:.12f}",
                    f"{pressure[index]:.12f}",
                    f"{temp[index]:.12f}",
                    f"{temp[index]:.12f}",
                    f"{u[index]:.12f}",
                    f"{v[index]:.12f}",
                    f"{w[index]:.12f}",
                ]
            )
        )
    raw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata = MetadataBundle(
        project=ProjectProfile(code="RTF", name="Raw To Final Parity"),
        site=SiteProfile(station_code="RTF", station_name="Raw To Final Synthetic"),
        raw_file_description=RawFileDescriptionMetadata(source_name="synthetic_raw_csv_001", source_type="csv"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=sample_hz, delimiter=",", header_rows=1),
    )
    reference_windows = [
        {
            "window_id": "manual_oracle_w001",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=float(time_axis[-1]))).isoformat(),
            "primary_flux": _manual_raw_flux(w=w, co2=co2, pressure_kpa=pressure, temp_c=temp),
            "primary_flux_source": "none",
            "lag_seconds": 0.0,
            "lag_strategy": "constant",
            "rotation_mode": "none",
        }
    ]
    config: dict[str, object] = {
        "sample_hz": sample_hz,
        "block_minutes": 1.0,
        "steps": {"window_sampling": {"sample_hz": sample_hz, "window_minutes": 1.0}},
        "rotation_mode": "none",
        "detrend_mode": "block_mean",
        "density_correction_mode": "none",
        "lag_phase": {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0},
    }
    return raw_path, metadata, reference_windows, config


def _raw_fp2_fixture(tmp_path: Path) -> tuple[Path, MetadataBundle, list[dict[str, object]], dict[str, object]]:
    sample_hz = 10.0
    samples = 240
    start = datetime(2026, 5, 27, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.5 * np.sin(2.0 * np.pi * 0.17 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.61 * time_axis)
    u = 2.4 + 0.04 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.11 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    co2 = 410.0 + 6.0 * w
    h2o = 12.0 + 0.8 * w
    pressure = 101.3 + 0.01 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.0 + 0.1 * np.cos(2.0 * np.pi * 0.03 * time_axis)
    raw_path = tmp_path / "synthetic_raw_fp2.tob1"
    header = b'"TOB1","FP2"\r\nTIMESTAMP,U,V,W,CO2,H2O,P,TA\r\n'
    records = []
    for index in range(samples):
        records.append(
            (
                _fp2_word(u[index], 2),
                _fp2_word(v[index], 2),
                _fp2_word(w[index], 3),
                _fp2_word(co2[index], 1),
                _fp2_word(h2o[index], 2),
                _fp2_word(pressure[index], 2),
                _fp2_word(temp[index], 2),
            )
        )
    raw_path.write_bytes(header + b"".join(struct.pack("<7H", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="RTF-FP2", name="Raw To Final FP2 Parity"),
        site=SiteProfile(station_code="RTF-FP2", station_name="Raw To Final FP2 Synthetic"),
        raw_file_description=RawFileDescriptionMetadata(source_name="synthetic_raw_tob1_fp2_001", source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=sample_hz,
            header_rows=2,
            extra={
                "columns": ["u", "v", "w", "co2", "h2o", "pressure", "temperature"],
                "start_time": start.isoformat(),
            },
        ),
    )
    decoded_w = np.array([_fp2_decode(_fp2_word(value, 3)) for value in w], dtype=float)
    decoded_co2 = np.array([_fp2_decode(_fp2_word(value, 1)) for value in co2], dtype=float)
    decoded_pressure = np.array([_fp2_decode(_fp2_word(value, 2)) for value in pressure], dtype=float)
    decoded_temp = np.array([_fp2_decode(_fp2_word(value, 2)) for value in temp], dtype=float)
    reference_windows = [
        {
            "window_id": "manual_oracle_fp2_w001",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=float(time_axis[-1]))).isoformat(),
            "primary_flux": _manual_raw_flux(w=decoded_w, co2=decoded_co2, pressure_kpa=decoded_pressure, temp_c=decoded_temp),
            "primary_flux_source": "none",
            "lag_seconds": 0.0,
            "lag_strategy": "constant",
            "rotation_mode": "none",
        }
    ]
    config: dict[str, object] = {
        "sample_hz": sample_hz,
        "block_minutes": 1.0,
        "steps": {"window_sampling": {"sample_hz": sample_hz, "window_minutes": 1.0}},
        "rotation_mode": "none",
        "detrend_mode": "block_mean",
        "density_correction_mode": "none",
        "lag_phase": {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0},
    }
    return raw_path, metadata, reference_windows, config


def _raw_ch4_fixture(tmp_path: Path) -> tuple[Path, MetadataBundle, list[dict[str, object]], dict[str, object]]:
    sample_hz = 10.0
    samples = 240
    start = datetime(2026, 5, 27, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.42 * np.sin(2.0 * np.pi * 0.13 * time_axis) + 0.11 * np.cos(2.0 * np.pi * 0.47 * time_axis)
    u = 2.5 + 0.05 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.16 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    co2 = 410.0 + 5.0 * w
    h2o = 13.0 + 0.9 * w
    ch4 = 1910.0 + 32.0 * w
    pressure = 100.8 + 0.02 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.5 + 0.1 * np.cos(2.0 * np.pi * 0.03 * time_axis)
    raw_path = tmp_path / "synthetic_li7700_trace_gas.csv"
    lines = ["timestamp,co2_ppm,h2o_mmol,ch4_ppb,pressure_kpa,chamber_temp_c,u,v,w"]
    for index in range(samples):
        timestamp = start + timedelta(seconds=float(time_axis[index]))
        lines.append(
            ",".join(
                [
                    timestamp.isoformat(),
                    f"{co2[index]:.12f}",
                    f"{h2o[index]:.12f}",
                    f"{ch4[index]:.12f}",
                    f"{pressure[index]:.12f}",
                    f"{temp[index]:.12f}",
                    f"{u[index]:.12f}",
                    f"{v[index]:.12f}",
                    f"{w[index]:.12f}",
                ]
            )
        )
    raw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata = MetadataBundle(
        project=ProjectProfile(code="RTF-CH4", name="Raw To Final LI-7700 Parity"),
        site=SiteProfile(station_code="RTF-CH4", station_name="Raw To Final LI-7700 Synthetic"),
        raw_file_description=RawFileDescriptionMetadata(source_name="synthetic_li7700_trace_gas_001", source_type="csv"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=sample_hz, delimiter=",", header_rows=1),
    )
    ch4_levels = _manual_li7700_levels(w=w, ch4=ch4, h2o=h2o, pressure_kpa=pressure, temp_c=temp)
    reference_windows = [
        {
            "window_id": "manual_oracle_li7700_w001",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=float(time_axis[-1]))).isoformat(),
            "primary_flux": _manual_raw_flux(w=w, co2=co2, pressure_kpa=pressure, temp_c=temp),
            "primary_flux_source": "none",
            "lag_seconds": 0.0,
            "lag_strategy": "constant",
            "rotation_mode": "none",
            "ch4_method": "li_7700_correction_sequence_v1",
            **ch4_levels,
        }
    ]
    config: dict[str, object] = {
        "sample_hz": sample_hz,
        "block_minutes": 1.0,
        "steps": {"window_sampling": {"sample_hz": sample_hz, "window_minutes": 1.0}},
        "rotation_mode": "none",
        "detrend_mode": "block_mean",
        "density_correction_mode": "none",
        "lag_phase": {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0},
        "trace_gas": {
            "ch4": {
                "coefficient_profile_id": "synthetic_li7700_profile",
                "coefficient_registry": {
                    "synthetic_li7700_profile": {
                        "label": "Synthetic LI-7700 parity coefficients",
                        "source": "synthetic_oracle",
                        "source_file": "references/eddypro/raw_to_final/synthetic_li7700_trace_gas.json",
                        "normalization_command": "gas_ec synthetic-li7700-oracle",
                        "spectroscopic_correction": {
                            "mode": "empirical",
                            "pressure_sensitivity_per_kpa": 0.001,
                            "temperature_sensitivity_per_c": 0.0005,
                            "h2o_sensitivity_per_molfrac": 0.1,
                        },
                        "self_heating_correction": {
                            "mode": "empirical",
                            "sensor_body_temp_c": 27.0,
                            "flux_sensitivity_per_c": 0.01,
                        },
                        "known_limitations": ["Synthetic oracle, not a public LI-7700 field fixture."],
                    }
                },
                "spectral_correction_factor": 1.04,
                "apply_water_vapor_dilution": True,
            }
        },
    }
    return raw_path, metadata, reference_windows, config


def _fp2_word(value: float, decimals: int) -> int:
    sign_bit = 0x80 if value < 0 else 0
    mantissa = int(round(abs(float(value)) * (10**decimals)))
    low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
    high_byte = mantissa & 0xFF
    return (high_byte << 8) | low_byte


def _fp2_decode(word: int) -> float:
    low_byte = int(word) & 0xFF
    high_byte = (int(word) >> 8) & 0xFF
    sign = -1.0 if low_byte & 0x80 else 1.0
    decimals = (low_byte >> 5) & 0x03
    mantissa = ((low_byte & 0x1F) << 8) + high_byte
    return sign * mantissa / (10.0**decimals)


def _manual_raw_flux(*, w: np.ndarray, co2: np.ndarray, pressure_kpa: np.ndarray, temp_c: np.ndarray) -> float:
    w_det = w - np.mean(w)
    co2_det = co2 - np.mean(co2)
    cov_w_co2 = float(np.mean(w_det * co2_det))
    mean_p_pa = float(np.mean(pressure_kpa)) * 1000.0
    mean_t_k = float(np.mean(temp_c)) + 273.15
    return mean_p_pa / (8.314 * mean_t_k) * cov_w_co2


def _manual_li7700_levels(
    *,
    w: np.ndarray,
    ch4: np.ndarray,
    h2o: np.ndarray,
    pressure_kpa: np.ndarray,
    temp_c: np.ndarray,
) -> dict[str, float]:
    w_det = w - np.mean(w)
    ch4_det = ch4 - np.mean(ch4)
    cov_w_ch4 = float(np.mean(w_det * ch4_det))
    mean_p_kpa = float(np.mean(pressure_kpa))
    mean_temp_c = float(np.mean(temp_c))
    mean_h2o_mmol = float(np.mean(h2o))
    air_molar_density = mean_p_kpa * 1000.0 / (8.314 * (mean_temp_c + 273.15))
    level0 = air_molar_density * cov_w_ch4
    level1 = level0 * 1.04
    h2o_molfrac = min(max(mean_h2o_mmol / 1000.0, 0.0), 0.12)
    level2 = level1 / max(1.0 - h2o_molfrac, 0.88)
    spectroscopic_factor = 1.0 + 0.001 * (mean_p_kpa - 101.325) + 0.0005 * (mean_temp_c - 20.0) + 0.1 * h2o_molfrac
    self_heating_factor = 1.0 + 0.01 * (27.0 - mean_temp_c)
    level3 = level2 * spectroscopic_factor * self_heating_factor
    return {
        "ch4_flux_level0_nmol_m2_s": level0,
        "ch4_flux_level1_spectral_nmol_m2_s": level1,
        "ch4_flux_level2_density_nmol_m2_s": level2,
        "ch4_flux_corrected_nmol_m2_s": level3,
        "ch4_flux_nmol_m2_s": level3,
    }
