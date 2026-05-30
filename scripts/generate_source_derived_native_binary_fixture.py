from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ID = "eddypro_source_native_binary_mixed_001"
FIXTURE_DIR = Path("references/eddypro/source_derived")
EDDYPRO_ENGINE_COMMIT = "3cabe637ca387e10254f1bd4a546341bf9be33b5"
GENERATED_AT = "2026-05-30T00:00:00+08:00"
SAMPLE_HZ = 10.0
SAMPLES = 600
START_TIME = datetime(2026, 5, 30, 9, 4, 0)
HEADER_LINES = [
    "GAS_EC_STUDIO_SOURCE_DERIVED_GENERIC_BINARY",
    "CO2_RAW,H2O_RAW,P_RAW,TA_RAW,U_RAW,V_RAW,W_RAW",
]
HEADER_BYTES = ("\r\n".join(HEADER_LINES) + "\r\n").encode("ascii")
COLUMNS = ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"]
COLUMN_TYPES = {
    "co2_raw": "float32",
    "h2o_raw": "float32",
    "p_raw": "int16",
    "ta_raw": "int16",
    "u_raw": "float32",
    "v_raw": "float32",
    "w_raw": "float32",
}
RECORD_HEADER_BYTES = 2
RECORD_FOOTER_BYTES = 2
RECORD_STRUCT = struct.Struct("<ffhhfff")
RECORD_LENGTH_BYTES = RECORD_HEADER_BYTES + RECORD_STRUCT.size + RECORD_FOOTER_BYTES


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and register an EddyPro source-derived native binary fixture.")
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
    raw_path = fixture_dir / f"{FIXTURE_ID}.bin"
    metadata_path = fixture_dir / f"{FIXTURE_ID}_metadata.json"
    reference_path = fixture_dir / f"{FIXTURE_ID}_reference.json"
    provenance_path = fixture_dir / f"{FIXTURE_ID}_provenance.json"

    payload = bytearray(HEADER_BYTES)
    decoded_rows: list[dict[str, float]] = []
    for index in range(SAMPLES):
        physical = _physical_row(index / SAMPLE_HZ)
        record = _encode_record(physical)
        decoded_rows.append(_decode_record_for_reference(record))
        payload.extend(bytes([0xA5, index % 256]))
        payload.extend(RECORD_STRUCT.pack(*record))
        payload.extend(bytes([0x0D, 0x0A]))
    raw_path.write_bytes(bytes(payload))

    metadata = _metadata_payload()
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    primary_flux = _manual_raw_flux(
        w=[row["w_raw"] for row in decoded_rows],
        co2=[row["co2_raw"] for row in decoded_rows],
        pressure_kpa=[row["p_raw"] for row in decoded_rows],
        temp_c=[row["ta_raw"] for row in decoded_rows],
    )
    reference = {
        "reference_id": f"{FIXTURE_ID}_source_derived_oracle",
        "source": "EddyPro engine source-derived generic binary conformance oracle",
        "description": "Reference window validates generic binary ASCII header skipping, record framing, mixed column types, and importer provenance.",
        "created_at": GENERATED_AT,
        "source_repositories": {
            "eddypro_engine": {
                "url": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "commit": EDDYPRO_ENGINE_COMMIT,
                "source_files": [
                    "src/src_common/import_binary.f90",
                    "src/src_common/import_native_data.f90",
                    "src/src_common/write_processing_project_variables.f90",
                ],
            }
        },
        "processing_settings": {
            "averaging_period_min": 1.0,
            "rotation_mode": "none",
            "density_correction": "none",
            "lag_determination": "constant",
            "detrend_method": "block_mean",
        },
        "qc_mapping_strategy": "Source-derived conformance oracle keeps QC optional; no official EddyPro QC flags are claimed.",
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
                "notes": "Source-derived generic native binary conformance oracle; not an official EddyPro executable output.",
            }
        ],
        "known_limitations": [
            "This fixture is generated from EddyPro source-code generic binary import rules and deterministic signals.",
            "It is not a real field native-binary dataset and must not close real-world binary fixture breadth blockers.",
        ],
    }
    reference_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")

    provenance = {
        "artifact_type": "source_derived_native_binary_fixture_provenance_v1",
        "fixture_id": FIXTURE_ID,
        "source_file": _rel(raw_path),
        "metadata_file": _rel(metadata_path),
        "reference_file": _rel(reference_path),
        "generation_time": GENERATED_AT,
        "generation_method": "Deterministic generic binary file generated from EddyPro import_binary.f90 semantics.",
        "normalization_script": "scripts/generate_source_derived_native_binary_fixture.py",
        "normalization_command": "python scripts/generate_source_derived_native_binary_fixture.py --register",
        "qc_mapping_strategy": reference["qc_mapping_strategy"],
        "source_repositories": reference["source_repositories"],
        "raw_columns": list(COLUMNS),
        "method_metadata": {
            "raw_format": "binary",
            "native_format": "binary",
            "data_type": "mixed",
            "column_types": [COLUMN_TYPES[column] for column in COLUMNS],
            "ascii_header_eol": "crlf",
            "header_rows": len(HEADER_LINES),
            "record_header_bytes": RECORD_HEADER_BYTES,
            "record_footer_bytes": RECORD_FOOTER_BYTES,
            "record_length_bytes": RECORD_LENGTH_BYTES,
            "timestamp_source": "extra.start_time",
            "source_derived": True,
        },
        "known_limitations": reference["known_limitations"],
    }
    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "native_binary_file": _rel(raw_path),
        "metadata_json": _rel(metadata_path),
        "reference_json": _rel(reference_path),
        "provenance_json": _rel(provenance_path),
    }


def fixture_asset(files: dict[str, str]) -> dict[str, Any]:
    asset = {
        "fixture_id": FIXTURE_ID,
        "tier": "raw_to_final_parity",
        "site_class": "source_derived_native_binary_conformance",
        "software": "gas_ec_studio source-derived EddyPro engine conformance oracle",
        "software_version": f"eddypro-engine@{EDDYPRO_ENGINE_COMMIT[:12]}",
        "source_derived": True,
        "source_derived_from": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_engine_commit": EDDYPRO_ENGINE_COMMIT,
            "eddypro_engine_files": [
                "src/src_common/import_binary.f90",
                "src/src_common/import_native_data.f90",
                "src/src_common/write_processing_project_variables.f90",
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
        },
        "thresholds": {
            "flux_rel_threshold": 1e-09,
            "lag_abs_threshold_s": 1e-12,
            "wpl_rel_threshold": 0.2,
            "qc_grade_must_match": False,
        },
        "known_limitations": [
            "Source-derived generic native binary conformance fixture validates importer and raw-to-final harness behavior.",
            "Reference output is a deterministic source-derived oracle, not an official EddyPro executable output.",
            "Real TOB1/SLT/native binary field fixtures with matching EddyPro output are still required before claiming broad parity.",
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
    real_gap = "Need real TOB1/SLT/binary field fixtures with official EddyPro Full_Output parity."
    gaps = [str(item) for item in list(updated.get("coverage_gaps", []) or [])]
    if real_gap not in gaps:
        gaps.insert(0, real_gap)
    updated["coverage_gaps"] = gaps
    pack_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _metadata_payload() -> dict[str, Any]:
    return {
        "project": {"code": "SRC-BINARY", "name": "EddyPro Source-Derived Native Binary Conformance"},
        "site": {"station_code": "SRC-BINARY", "station_name": "Source-Derived Native Binary Conformance Site"},
        "raw_file_description": {
            "source_name": FIXTURE_ID,
            "source_type": "binary",
            "timezone": "UTC",
            "notes": "Source-derived generic binary fixture based on EddyPro import_binary.f90 fixed-record semantics.",
            "column_mappings": [
                {"column_name": "co2_raw", "variable": "co2_ppm", "input_unit": "umol/mol"},
                {"column_name": "h2o_raw", "variable": "h2o_mmol", "input_unit": "mmol/mol"},
                {"column_name": "p_raw", "variable": "pressure_kpa", "input_unit": "kPa", "scaling": 0.1},
                {"column_name": "ta_raw", "variable": "chamber_temp_c", "input_unit": "C", "scaling": 0.1},
                {"column_name": "u_raw", "variable": "u", "input_unit": "m/s"},
                {"column_name": "v_raw", "variable": "v", "input_unit": "m/s"},
                {"column_name": "w_raw", "variable": "w", "input_unit": "m/s"},
            ],
        },
        "raw_file_settings": {
            "sample_hz": SAMPLE_HZ,
            "header_rows": len(HEADER_LINES),
            "extra": {
                "native_format": "binary",
                "data_type": "int16",
                "columns": list(COLUMNS),
                "column_types": COLUMN_TYPES,
                "header_rows": len(HEADER_LINES),
                "ascii_header_eol": "CR/LF",
                "record_header_bytes": RECORD_HEADER_BYTES,
                "record_footer_bytes": RECORD_FOOTER_BYTES,
                "record_length_bytes": RECORD_LENGTH_BYTES,
                "start_time": START_TIME.isoformat(),
            },
        },
        "metadata_version": "ec_core_metadata_v1",
        "notes": [
            "Source-derived conformance fixture, not a public field dataset.",
            "Record timestamps are generated from extra.start_time plus sample_hz because generic binary records do not carry explicit timestamps.",
        ],
    }


def _physical_row(t: float) -> dict[str, float]:
    w = 0.34 * math.sin(2.0 * math.pi * 0.21 * t) + 0.07 * math.cos(2.0 * math.pi * 0.43 * t)
    return {
        "co2_raw": _float32(410.8 + 4.8 * w + 0.16 * math.sin(2.0 * math.pi * 0.025 * t)),
        "h2o_raw": _float32(12.4 + 0.38 * w),
        "p_raw": _round_to_step(101.3 + 0.01 * math.sin(2.0 * math.pi * 0.01 * t), 0.1),
        "ta_raw": _round_to_step(24.1 + 0.08 * math.cos(2.0 * math.pi * 0.02 * t), 0.1),
        "u_raw": _float32(2.2 + 0.05 * math.sin(2.0 * math.pi * 0.04 * t)),
        "v_raw": _float32(0.10 * math.cos(2.0 * math.pi * 0.08 * t)),
        "w_raw": _float32(w),
    }


def _encode_record(row: dict[str, float]) -> tuple[float, float, int, int, float, float, float]:
    return (
        _float32(row["co2_raw"]),
        _float32(row["h2o_raw"]),
        int(round(row["p_raw"] / 0.1)),
        int(round(row["ta_raw"] / 0.1)),
        _float32(row["u_raw"]),
        _float32(row["v_raw"]),
        _float32(row["w_raw"]),
    )


def _decode_record_for_reference(record: tuple[float, float, int, int, float, float, float]) -> dict[str, float]:
    co2, h2o, pressure_raw, temp_raw, u, v, w = record
    return {
        "co2_raw": _float32(co2),
        "h2o_raw": _float32(h2o),
        "p_raw": float(pressure_raw) * 0.1,
        "ta_raw": float(temp_raw) * 0.1,
        "u_raw": _float32(u),
        "v_raw": _float32(v),
        "w_raw": _float32(w),
    }


def _manual_raw_flux(*, w: list[float], co2: list[float], pressure_kpa: list[float], temp_c: list[float]) -> float:
    mean_w = sum(w) / len(w)
    mean_co2 = sum(co2) / len(co2)
    cov_w_co2 = sum((wi - mean_w) * (ci - mean_co2) for wi, ci in zip(w, co2)) / len(w)
    mean_p_pa = (sum(pressure_kpa) / len(pressure_kpa)) * 1000.0
    mean_t_k = (sum(temp_c) / len(temp_c)) + 273.15
    return mean_p_pa / (8.314 * mean_t_k) * cov_w_co2


def _round_to_step(value: float, step: float) -> float:
    return round(round(float(value) / float(step)) * float(step), 6)


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(WORKSPACE_ROOT)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
