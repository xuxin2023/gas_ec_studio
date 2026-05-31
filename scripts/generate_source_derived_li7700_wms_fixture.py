from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ID = "eddypro_source_li7700_wms_001"
FIXTURE_DIR = Path("references/eddypro/source_derived")
EDDYPRO_ENGINE_COMMIT = "3cabe637ca387e10254f1bd4a546341bf9be33b5"
GENERATED_AT = "2026-05-30T00:30:00+08:00"
SAMPLE_HZ = 10.0
SAMPLES = 600
START_TIME = datetime(2026, 5, 30, 9, 8, 0)
SCAN_AXIS = [round(-1.0 + index * 0.05, 6) for index in range(41)]
ABSORBANCE = [0.02 + 0.7 * math.exp(-0.5 * ((axis - 0.05) / 0.26) ** 2) for axis in SCAN_AXIS]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and register an EddyPro source-derived LI-7700 WMS fixture.")
    parser.add_argument("--workspace-root", default=str(WORKSPACE_ROOT))
    parser.add_argument("--pack-path", default="references/eddypro/fixture_pack_v1.json")
    parser.add_argument("--register", action="store_true", help="Insert or replace the fixture-pack asset.")
    args = parser.parse_args()

    root = Path(args.workspace_root).resolve()
    fixture_dir = root / FIXTURE_DIR
    fixture_dir.mkdir(parents=True, exist_ok=True)
    generated = generate_fixture(fixture_dir)
    asset = fixture_asset(generated)
    if args.register:
        register_asset(root / args.pack_path, asset)
    print(json.dumps({"fixture_id": FIXTURE_ID, "asset": asset, "files": generated}, ensure_ascii=False, indent=2))
    return 0


def generate_fixture(fixture_dir: Path) -> dict[str, str]:
    raw_path = fixture_dir / f"{FIXTURE_ID}.csv"
    metadata_path = fixture_dir / f"{FIXTURE_ID}_metadata.json"
    reference_path = fixture_dir / f"{FIXTURE_ID}_reference.json"
    provenance_path = fixture_dir / f"{FIXTURE_ID}_provenance.json"

    rows = [_physical_row(index / SAMPLE_HZ) for index in range(SAMPLES)]
    _write_raw_csv(raw_path, rows)

    metadata = _metadata_payload()
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    primary_flux = _manual_raw_flux(
        w=[row["w"] for row in rows],
        co2=[row["co2_ppm"] for row in rows],
        pressure_kpa=[row["pressure_kpa"] for row in rows],
        temp_c=[row["chamber_temp_c"] for row in rows],
    )
    wms = _wms_line_shape_payload()
    ch4_levels = _manual_li7700_levels(
        w=[row["w"] for row in rows],
        ch4=[row["ch4_ppb"] for row in rows],
        h2o=[row["h2o_mmol"] for row in rows],
        pressure_kpa=[row["pressure_kpa"] for row in rows],
        temp_c=[row["chamber_temp_c"] for row in rows],
        spectroscopic_factor=wms["factor"],
    )
    reference = {
        "reference_id": f"{FIXTURE_ID}_source_derived_wms_oracle",
        "source": "EddyPro engine source-derived LI-7700 WMS conformance oracle",
        "description": "Reference window validates configured LI-7700 WMS line-shape scan fitting through the CH4 Level 0/1/2/3 raw-to-final path.",
        "created_at": GENERATED_AT,
        "source_repositories": {
            "eddypro_engine": {
                "url": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "commit": EDDYPRO_ENGINE_COMMIT,
                "source_files": [
                    "src/src_rp/m_li7700.f90",
                    "src/src_common/bpcf_li7700_analog_filters.f90",
                ],
            }
        },
        "processing_settings": {
            "averaging_period_min": 1.0,
            "rotation_mode": "none",
            "density_correction": "none",
            "lag_determination": "constant",
            "detrend_method": "block_mean",
            "trace_gas": "LI-7700 CH4 source-derived WMS line-shape sequence",
        },
        "qc_mapping_strategy": "Source-derived WMS conformance oracle keeps EddyPro QC optional; no official EddyPro QC flags are claimed.",
        "windows": [
            {
                "window_id": f"{FIXTURE_ID}_w001",
                "start_time": START_TIME.isoformat(),
                "end_time": (START_TIME + timedelta(seconds=(SAMPLES - 1) / SAMPLE_HZ)).isoformat(),
                "primary_flux": primary_flux,
                "primary_flux_source": "none",
                "lag_seconds": 0.0,
                "lag_strategy": "constant",
                "rotation_mode": "none",
                "applied_rotation_impl": "none",
                "qc_grade": "",
                "ch4_method": "li_7700_correction_sequence_v1",
                "ch4_correction_sequence": {
                    "status": "computed",
                    "levels": {
                        "level0": {"flux_nmol_m2_s": ch4_levels["ch4_flux_level0_nmol_m2_s"]},
                        "level1": {"flux_nmol_m2_s": ch4_levels["ch4_flux_level1_spectral_nmol_m2_s"]},
                        "level2": {"flux_nmol_m2_s": ch4_levels["ch4_flux_level2_density_nmol_m2_s"]},
                        "level3": {
                            "spectroscopic_status": "applied_wms_line_shape",
                            "spectroscopic_factor": wms["factor"],
                            "self_heating_status": "applied_empirical",
                            "self_heating_factor": ch4_levels["self_heating_factor"],
                            "flux_nmol_m2_s": ch4_levels["ch4_flux_corrected_nmol_m2_s"],
                        },
                    },
                },
                **{key: value for key, value in ch4_levels.items() if key.startswith("ch4_")},
                "li7700_wms_reference_area": wms["reference_area"],
                "li7700_wms_fitted_area": wms["fitted_area"],
                "li7700_wms_factor": wms["factor"],
                "notes": "Source-derived LI-7700 WMS conformance oracle; not an official EddyPro executable output.",
            }
        ],
        "known_limitations": [
            "This fixture is generated from EddyPro LI-7700 source anchors and deterministic WMS scan signals.",
            "It validates Gas EC Studio configured WMS line-shape propagation, not LI-7700 firmware-equivalent line-shape fitting.",
            "Real LI-7700 high-frequency raw data with matching EddyPro Full_Output remains required before claiming official numeric parity.",
        ],
    }
    reference_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")

    provenance = {
        "artifact_type": "source_derived_li7700_wms_fixture_provenance_v1",
        "fixture_id": FIXTURE_ID,
        "source_file": _rel(raw_path),
        "metadata_file": _rel(metadata_path),
        "reference_file": _rel(reference_path),
        "generation_time": GENERATED_AT,
        "generation_method": "Deterministic tabular LI-7700 CH4/WMS file generated from EddyPro m_li7700 source anchors.",
        "normalization_script": "scripts/generate_source_derived_li7700_wms_fixture.py",
        "normalization_command": "python scripts/generate_source_derived_li7700_wms_fixture.py --register",
        "qc_mapping_strategy": reference["qc_mapping_strategy"],
        "source_repositories": reference["source_repositories"],
        "method_metadata": {
            "trace_gas": "ch4",
            "instrument_family": "LI-7700",
            "spectroscopic_correction_mode": "wms_line_shape",
            "wms_reference_area": wms["reference_area"],
            "wms_fitted_area": wms["fitted_area"],
            "wms_factor": wms["factor"],
            "scan_sample_count": len(SCAN_AXIS),
            "source_derived": True,
        },
        "known_limitations": reference["known_limitations"],
    }
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "raw_file": _rel(raw_path),
        "metadata_json": _rel(metadata_path),
        "reference_json": _rel(reference_path),
        "provenance_json": _rel(provenance_path),
    }


def fixture_asset(files: dict[str, str]) -> dict[str, Any]:
    wms = _wms_line_shape_payload()
    asset = {
        "fixture_id": FIXTURE_ID,
        "tier": "raw_to_final_parity",
        "site_class": "source_derived_li7700_wms_conformance",
        "software": "gas_ec_studio source-derived EddyPro LI-7700 WMS conformance oracle",
        "software_version": f"eddypro-engine@{EDDYPRO_ENGINE_COMMIT[:12]}",
        "source_derived": True,
        "source_derived_from": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_engine_commit": EDDYPRO_ENGINE_COMMIT,
            "eddypro_engine_files": [
                "src/src_rp/m_li7700.f90",
                "src/src_common/bpcf_li7700_analog_filters.f90",
            ],
        },
        **files,
        "rp_config": {
            "sample_hz": SAMPLE_HZ,
            "block_minutes": 1.0,
            "steps": {"window_sampling": {"sample_hz": SAMPLE_HZ, "window_minutes": 1.0}},
            "rotation_mode": "none",
            "detrend_mode": "block_mean",
            "density_correction_mode": "none",
            "lag_phase": {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0},
            "trace_gas": {
                "ch4": {
                    "coefficient_profile_id": "source_li7700_wms_profile",
                    "coefficient_registry": {
                        "source_li7700_wms_profile": {
                            "label": "Source-derived LI-7700 WMS conformance profile",
                            "source": "eddypro_engine_source_derived",
                            "source_file": files["reference_json"],
                            "normalization_command": "python scripts/generate_source_derived_li7700_wms_fixture.py --register",
                            "spectroscopic_correction": {
                                "mode": "wms_line_shape",
                                "scan_axis": list(SCAN_AXIS),
                                "absorbance": list(ABSORBANCE),
                                "reference_area": wms["reference_area"],
                            },
                            "self_heating_correction": {
                                "mode": "empirical",
                                "sensor_body_temp_c": 27.0,
                                "flux_sensitivity_per_c": 0.01,
                            },
                            "known_limitations": [
                                "Source-derived WMS conformance profile; not a firmware-equivalent LI-7700 calibration file."
                            ],
                        }
                    },
                    "spectral_correction_factor": 1.04,
                    "apply_water_vapor_dilution": True,
                }
            },
        },
        "thresholds": {
            "flux_rel_threshold": 1e-09,
            "lag_abs_threshold_s": 1e-12,
            "wpl_rel_threshold": 0.2,
            "qc_grade_must_match": False,
            "trace_gas_rel_threshold": 1e-09,
        },
        "known_limitations": [
            "Source-derived LI-7700 WMS conformance fixture validates configured WMS propagation through raw-to-final artifacts.",
            "Reference output is a deterministic source-derived oracle, not an official EddyPro executable output.",
            "Real LI-7700 WMS/high-frequency field fixtures with matching EddyPro output are still required before claiming CH4 parity.",
        ],
    }
    asset["expected_sha256"] = {role: _sha256(WORKSPACE_ROOT / path) for role, path in files.items()}
    return asset


def register_asset(pack_path: Path, asset: dict[str, Any]) -> None:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    assets = [dict(item or {}) for item in list(pack.get("assets", []) or [])]
    fixture_id = str(asset["fixture_id"])
    index = next((i for i, item in enumerate(assets) if str(item.get("fixture_id", "")) == fixture_id), None)
    if index is None:
        assets.append(asset)
    else:
        assets[index] = asset
    updated = deepcopy(pack)
    updated["assets"] = assets
    real_gap = "Need real LI-7700 WMS/high-frequency raw field fixtures with official EddyPro Full_Output parity."
    gaps = [str(item) for item in list(updated.get("coverage_gaps", []) or [])]
    if real_gap not in gaps:
        gaps.insert(0, real_gap)
    updated["coverage_gaps"] = gaps
    pack_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _metadata_payload() -> dict[str, Any]:
    mappings = [
        ("timestamp", "timestamp", None, False),
        ("co2_ppm", "co2_ppm", "umol/mol", True),
        ("h2o_mmol", "h2o_mmol", "mmol/mol", True),
        ("ch4_ppb", "ch4_ppb", "nmol/mol", True),
        ("pressure_kpa", "pressure_kpa", "kPa", True),
        ("chamber_temp_c", "chamber_temp_c", "C", True),
        ("u", "u", "m/s", True),
        ("v", "v", "m/s", True),
        ("w", "w", "m/s", True),
        ("li7700_rssi", "li7700_rssi", "%", True),
        ("signal_strength", "signal_strength", "%", True),
        ("mirror_rssi", "mirror_rssi", "%", True),
        ("mirror_dirty", "mirror_dirty", None, False),
        ("pll_locked", "pll_locked", None, False),
        ("diagnostic_status", "diagnostic_status", None, False),
        ("li7700_status_word", "li7700_status_word", None, True),
    ]
    return {
        "project": {"code": "SRC-WMS", "name": "EddyPro Source-Derived LI-7700 WMS Conformance"},
        "site": {"station_code": "SRC-WMS", "station_name": "Source-Derived LI-7700 WMS Conformance Site"},
        "raw_file_description": {
            "source_name": FIXTURE_ID,
            "source_type": "csv",
            "timestamp_column": "timestamp",
            "timezone": "UTC",
            "notes": "Source-derived LI-7700 CH4/WMS fixture based on EddyPro m_li7700 correction-path anchors.",
            "column_mappings": [
                {"column_name": column, "variable": variable, "input_unit": unit, "numeric": numeric}
                for column, variable, unit, numeric in mappings
            ],
        },
        "raw_file_settings": {
            "sample_hz": SAMPLE_HZ,
            "delimiter": ",",
            "header_rows": 1,
            "encoding": "utf-8",
            "missing_tokens": ["", "NA", "NaN"],
        },
        "metadata_version": "ec_core_metadata_v1",
        "notes": [
            "Source-derived LI-7700 WMS conformance fixture, not a public field dataset.",
            "The WMS scan is supplied through the RP config coefficient profile rather than a raw LI-7700 firmware diagnostic file.",
        ],
    }


def _write_raw_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "timestamp",
        "co2_ppm",
        "h2o_mmol",
        "ch4_ppb",
        "pressure_kpa",
        "chamber_temp_c",
        "u",
        "v",
        "w",
        "li7700_rssi",
        "signal_strength",
        "mirror_rssi",
        "mirror_dirty",
        "pll_locked",
        "diagnostic_status",
        "li7700_status_word",
    ]
    lines = [",".join(columns)]
    for index, row in enumerate(rows):
        timestamp = START_TIME + timedelta(seconds=index / SAMPLE_HZ)
        values = []
        for column in columns:
            if column == "timestamp":
                values.append(timestamp.isoformat())
            elif isinstance(row[column], float):
                values.append(f"{row[column]:.12f}")
            else:
                values.append(str(row[column]))
        lines.append(",".join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _physical_row(t: float) -> dict[str, Any]:
    w = 0.44 * math.sin(2.0 * math.pi * 0.16 * t) + 0.10 * math.cos(2.0 * math.pi * 0.52 * t)
    return {
        "co2_ppm": 410.6 + 5.6 * w + 0.12 * math.sin(2.0 * math.pi * 0.027 * t),
        "h2o_mmol": 13.2 + 0.82 * w + 0.03 * math.cos(2.0 * math.pi * 0.033 * t),
        "ch4_ppb": 1912.0 + 30.0 * w + 0.35 * math.sin(2.0 * math.pi * 0.41 * t),
        "pressure_kpa": 100.9 + 0.015 * math.sin(2.0 * math.pi * 0.011 * t),
        "chamber_temp_c": 24.7 + 0.08 * math.cos(2.0 * math.pi * 0.018 * t),
        "u": 2.42 + 0.05 * math.sin(2.0 * math.pi * 0.04 * t),
        "v": 0.14 * math.cos(2.0 * math.pi * 0.05 * t),
        "w": w,
        "li7700_rssi": 68.0 + 1.3 * math.sin(2.0 * math.pi * 0.015 * t),
        "signal_strength": 73.0 + 1.2 * math.cos(2.0 * math.pi * 0.02 * t),
        "mirror_rssi": 83.0,
        "mirror_dirty": "clean",
        "pll_locked": "true",
        "diagnostic_status": "ok",
        "li7700_status_word": 0,
    }


def _manual_raw_flux(*, w: list[float], co2: list[float], pressure_kpa: list[float], temp_c: list[float]) -> float:
    mean_w = sum(w) / len(w)
    mean_co2 = sum(co2) / len(co2)
    cov_w_co2 = sum((wi - mean_w) * (ci - mean_co2) for wi, ci in zip(w, co2)) / len(w)
    mean_p_pa = (sum(pressure_kpa) / len(pressure_kpa)) * 1000.0
    mean_t_k = (sum(temp_c) / len(temp_c)) + 273.15
    return mean_p_pa / (8.314 * mean_t_k) * cov_w_co2


def _manual_li7700_levels(
    *,
    w: list[float],
    ch4: list[float],
    h2o: list[float],
    pressure_kpa: list[float],
    temp_c: list[float],
    spectroscopic_factor: float,
) -> dict[str, float]:
    mean_w = sum(w) / len(w)
    mean_ch4 = sum(ch4) / len(ch4)
    cov_w_ch4 = sum((wi - mean_w) * (ci - mean_ch4) for wi, ci in zip(w, ch4)) / len(w)
    mean_p_kpa = sum(pressure_kpa) / len(pressure_kpa)
    mean_temp_c = sum(temp_c) / len(temp_c)
    mean_h2o_mmol = sum(h2o) / len(h2o)
    air_molar_density = mean_p_kpa * 1000.0 / (8.314 * (mean_temp_c + 273.15))
    level0 = air_molar_density * cov_w_ch4
    level1 = level0 * 1.04
    h2o_molfrac = min(max(mean_h2o_mmol / 1000.0, 0.0), 0.12)
    level2 = level1 / max(1.0 - h2o_molfrac, 0.88)
    self_heating_factor = 1.0 + 0.01 * (27.0 - mean_temp_c)
    level3 = level2 * spectroscopic_factor * self_heating_factor
    return {
        "ch4_flux_level0_nmol_m2_s": level0,
        "ch4_flux_level1_spectral_nmol_m2_s": level1,
        "ch4_flux_level2_density_nmol_m2_s": level2,
        "ch4_flux_corrected_nmol_m2_s": level3,
        "ch4_flux_nmol_m2_s": level3,
        "self_heating_factor": self_heating_factor,
    }


def _wms_line_shape_payload() -> dict[str, float]:
    edge_count = max(1, min(5, int(len(SCAN_AXIS) // 10) or 1))
    left_baseline = sum(ABSORBANCE[:edge_count]) / edge_count
    right_baseline = sum(ABSORBANCE[-edge_count:]) / edge_count
    positive: list[float] = []
    for axis, signal in zip(SCAN_AXIS, ABSORBANCE):
        fraction = (axis - SCAN_AXIS[0]) / (SCAN_AXIS[-1] - SCAN_AXIS[0])
        baseline = left_baseline + fraction * (right_baseline - left_baseline)
        positive.append(max(signal - baseline, 0.0))
    fitted_area = _trapezoid(positive, SCAN_AXIS)
    reference_area = fitted_area * 0.96
    return {
        "fitted_area": fitted_area,
        "reference_area": reference_area,
        "factor": reference_area / fitted_area,
    }


def _trapezoid(values: list[float], axis: list[float]) -> float:
    return sum(0.5 * (values[index - 1] + values[index]) * (axis[index] - axis[index - 1]) for index in range(1, len(values)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(WORKSPACE_ROOT)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
