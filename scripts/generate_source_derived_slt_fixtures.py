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
FIXTURE_DIR = Path("references/eddypro/source_derived")
EDDYPRO_ENGINE_COMMIT = "3cabe637ca387e10254f1bd4a546341bf9be33b5"
GENERATED_AT = "2026-05-30T00:00:00+08:00"
SAMPLE_HZ = 10.0
SAMPLES = 600
START_TIME = datetime(2026, 5, 30, 9, 0, 0)
SOURCE_REPOSITORIES = {
    "eddypro_engine": {
        "url": "https://github.com/LI-COR-Environmental/eddypro-engine",
        "commit": EDDYPRO_ENGINE_COMMIT,
        "source_files": [
            "src/src_common/import_slt_edisol.f90",
            "src/src_common/import_slt_eddysoft.f90",
        ],
    }
}
FIXTURE_SPECS = [
    {
        "fixture_id": "eddypro_source_slt_edisol_001",
        "variant": "slt_edisol",
        "site_class": "source_derived_slt_edisol_conformance",
        "source_files": ["src/src_common/import_slt_edisol.f90"],
        "start_time": START_TIME,
        "header_bytes": 20,
    },
    {
        "fixture_id": "eddypro_source_slt_eddysoft_001",
        "variant": "slt_eddysoft",
        "site_class": "source_derived_slt_eddysoft_conformance",
        "source_files": ["src/src_common/import_slt_eddysoft.f90"],
        "start_time": START_TIME + timedelta(minutes=2),
        "header_bytes": 14,
    },
]
COLUMNS = ["U", "V", "W", "CO2", "H2O", "P", "TA"]
SCALE = {
    "U": 0.01,
    "V": 0.01,
    "W": 0.01,
    "CO2": 0.1,
    "H2O": 0.01,
    "P": 0.02,
    "TA": 0.01,
}
OFFSET = {
    "U": 0.0,
    "V": 0.0,
    "W": 0.0,
    "CO2": 0.0,
    "H2O": -18.0,
    "P": 0.0,
    "TA": -1.0,
}
EDDY_SOFT_HIGH_RES_COLUMNS = {"H2O", "P", "TA"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and register EddyPro source-derived SLT fixtures.")
    parser.add_argument("--workspace-root", default=str(WORKSPACE_ROOT))
    parser.add_argument("--pack-path", default="references/eddypro/fixture_pack_v1.json")
    parser.add_argument("--register", action="store_true", help="Insert or replace the fixture-pack assets.")
    args = parser.parse_args()

    root = Path(args.workspace_root).resolve()
    fixture_dir = root / FIXTURE_DIR
    fixture_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    generated_files: dict[str, dict[str, str]] = {}
    for spec in FIXTURE_SPECS:
        generated = generate_fixture(fixture_dir, spec=spec)
        asset = fixture_asset(generated, spec=spec)
        assets.append(asset)
        generated_files[str(spec["fixture_id"])] = generated
    if args.register:
        register_assets(root / args.pack_path, assets)
    print(json.dumps({"fixture_ids": [asset["fixture_id"] for asset in assets], "assets": assets, "files": generated_files}, ensure_ascii=False, indent=2))
    return 0


def generate_fixture(fixture_dir: Path, *, spec: dict[str, Any]) -> dict[str, str]:
    fixture_id = str(spec["fixture_id"])
    variant = str(spec["variant"])
    raw_path = fixture_dir / f"{fixture_id}.slt"
    metadata_path = fixture_dir / f"{fixture_id}_metadata.json"
    reference_path = fixture_dir / f"{fixture_id}_reference.json"
    provenance_path = fixture_dir / f"{fixture_id}_provenance.json"
    start = spec["start_time"]

    decoded_rows: list[dict[str, float]] = []
    records: list[tuple[int, ...]] = []
    for index in range(SAMPLES):
        t = index / SAMPLE_HZ
        physical = _physical_row(t)
        decoded_rows.append(physical)
        records.append(tuple(_physical_to_native(column, physical[column], variant=variant) for column in COLUMNS))

    raw_path.write_bytes(_slt_header(variant=variant) + b"".join(struct.pack("<7h", *record) for record in records))
    metadata = _metadata_payload(spec=spec)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    primary_flux = _manual_raw_flux(
        w=[row["W"] for row in decoded_rows],
        co2=[row["CO2"] for row in decoded_rows],
        pressure_kpa=[row["P"] for row in decoded_rows],
        temp_c=[row["TA"] for row in decoded_rows],
    )
    reference = {
        "reference_id": f"{fixture_id}_source_derived_oracle",
        "source": f"EddyPro engine source-derived {variant} conformance oracle",
        "description": f"Reference window validates {variant} int16 decoding and SLT source-anchor provenance.",
        "created_at": GENERATED_AT,
        "source_repositories": {
            "eddypro_engine": {
                **SOURCE_REPOSITORIES["eddypro_engine"],
                "source_files": list(spec["source_files"]),
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
                "window_id": f"{fixture_id}_w001",
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(seconds=(SAMPLES - 1) / SAMPLE_HZ)).isoformat(),
                "primary_flux": primary_flux,
                "primary_flux_source": "none",
                "lag_seconds": 0.0,
                "lag_strategy": "constant",
                "rotation_mode": "none",
                "applied_rotation_impl": "none",
                "qc_grade": "",
                "notes": f"Source-derived {variant} conformance oracle; not an official EddyPro executable output.",
            }
        ],
        "known_limitations": [
            "This fixture is generated from EddyPro source-code import rules and deterministic signals.",
            "It is not a real field SLT dataset and must not close real-world binary fixture breadth blockers.",
        ],
    }
    reference_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")

    provenance = {
        "artifact_type": "source_derived_slt_fixture_provenance_v1",
        "fixture_id": fixture_id,
        "source_file": _rel(raw_path),
        "metadata_file": _rel(metadata_path),
        "reference_file": _rel(reference_path),
        "generation_time": GENERATED_AT,
        "generation_method": f"Deterministic {variant} int16 binary generated from EddyPro source-code import semantics.",
        "normalization_script": "scripts/generate_source_derived_slt_fixtures.py",
        "normalization_command": "python scripts/generate_source_derived_slt_fixtures.py --register",
        "qc_mapping_strategy": reference["qc_mapping_strategy"],
        "source_repositories": reference["source_repositories"],
        "raw_columns": list(COLUMNS),
        "method_metadata": {
            "raw_format": variant,
            "timestamp_source": "extra.start_time",
            "source_derived": True,
            "eddysoft_high_resolution_columns": sorted(EDDY_SOFT_HIGH_RES_COLUMNS) if variant == "slt_eddysoft" else [],
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


def fixture_asset(files: dict[str, str], *, spec: dict[str, Any]) -> dict[str, Any]:
    variant = str(spec["variant"])
    fixture_id = str(spec["fixture_id"])
    asset = {
        "fixture_id": fixture_id,
        "tier": "raw_to_final_parity",
        "site_class": str(spec["site_class"]),
        "software": "gas_ec_studio source-derived EddyPro engine conformance oracle",
        "software_version": f"eddypro-engine@{EDDYPRO_ENGINE_COMMIT[:12]}",
        "source_derived": True,
        "source_derived_from": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_engine_commit": EDDYPRO_ENGINE_COMMIT,
            "eddypro_engine_files": list(spec["source_files"]),
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
            f"Source-derived {variant} conformance fixture validates importer and raw-to-final harness behavior.",
            "Reference output is a deterministic source-derived oracle, not an official EddyPro executable output.",
            "Real TOB1/SLT/native binary field fixtures with matching EddyPro output are still required before claiming broad parity.",
        ],
    }
    asset["expected_sha256"] = {role: _sha256(WORKSPACE_ROOT / path) for role, path in files.items()}
    return asset


def register_assets(pack_path: Path, assets: list[dict[str, Any]]) -> None:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    existing = [dict(item or {}) for item in list(pack.get("assets", []) or [])]
    by_id = {str(asset["fixture_id"]): asset for asset in assets}
    updated_assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in existing:
        fixture_id = str(item.get("fixture_id", ""))
        if fixture_id in by_id:
            updated_assets.append(by_id[fixture_id])
            seen.add(fixture_id)
        else:
            updated_assets.append(item)
    for asset in assets:
        fixture_id = str(asset["fixture_id"])
        if fixture_id not in seen:
            updated_assets.append(asset)
    updated = deepcopy(pack)
    updated["assets"] = updated_assets
    gaps = [str(item) for item in list(updated.get("coverage_gaps", []) or [])]
    updated["coverage_gaps"] = [
        gap for gap in gaps
        if gap != "Need TOB1/SLT/binary raw fixtures with EddyPro import-output parity."
    ]
    real_gap = "Need real TOB1/SLT/binary field fixtures with official EddyPro Full_Output parity."
    if real_gap not in updated["coverage_gaps"]:
        updated["coverage_gaps"].insert(0, real_gap)
    pack_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _metadata_payload(*, spec: dict[str, Any]) -> dict[str, Any]:
    variant = str(spec["variant"])
    fixture_id = str(spec["fixture_id"])
    return {
        "project": {"code": fixture_id.upper(), "name": f"EddyPro Source-Derived {variant} Conformance"},
        "site": {"station_code": fixture_id.upper(), "station_name": f"Source-Derived {variant} Conformance Site"},
        "raw_file_description": {
            "source_name": fixture_id,
            "source_type": variant,
            "timezone": "UTC",
            "notes": f"Source-derived {variant} fixture based on EddyPro SLT import source anchors.",
            "column_mappings": [
                {"column_name": "U", "variable": "u", "input_unit": "m/s"},
                {"column_name": "V", "variable": "v", "input_unit": "m/s"},
                {"column_name": "W", "variable": "w", "input_unit": "m/s"},
                {"column_name": "CO2", "variable": "co2_ppm", "input_unit": "umol/mol"},
                {"column_name": "H2O", "variable": "h2o_mmol", "input_unit": "mmol/mol"},
                {"column_name": "P", "variable": "pressure_kpa", "input_unit": "kPa"},
                {"column_name": "TA", "variable": "chamber_temp_c", "input_unit": "C"},
            ],
        },
        "raw_file_settings": {
            "sample_hz": SAMPLE_HZ,
            "extra": {
                "native_format": variant,
                "columns": list(COLUMNS),
                "header_bytes": int(spec["header_bytes"]),
                "start_time": spec["start_time"].isoformat(),
                "scale": SCALE,
                "offset": OFFSET,
            },
        },
        "metadata_version": "ec_core_metadata_v1",
        "notes": [
            "Source-derived conformance fixture, not a public field dataset.",
            "Record timestamps are generated from extra.start_time plus sample_hz because SLT records do not carry explicit timestamps.",
        ],
    }


def _slt_header(*, variant: str) -> bytes:
    if variant == "slt_edisol":
        return bytes(20)
    if variant == "slt_eddysoft":
        header = bytearray(8 + max(0, len(COLUMNS) - 4) * 2)
        for index, column in enumerate(COLUMNS[4:]):
            header[8 + index * 2] = 1 if column in EDDY_SOFT_HIGH_RES_COLUMNS else 0
        return bytes(header)
    raise ValueError(f"Unsupported SLT variant: {variant}")


def _physical_row(t: float) -> dict[str, float]:
    w = 0.38 * math.sin(2.0 * math.pi * 0.19 * t) + 0.08 * math.cos(2.0 * math.pi * 0.47 * t)
    return {
        "U": _round_physical(2.10 + 0.04 * math.sin(2.0 * math.pi * 0.04 * t), "U"),
        "V": _round_physical(0.08 * math.cos(2.0 * math.pi * 0.08 * t), "V"),
        "W": _round_physical(w, "W"),
        "CO2": _round_physical(411.0 + 4.2 * w + 0.2 * math.sin(2.0 * math.pi * 0.03 * t), "CO2"),
        "H2O": _round_physical(12.1 + 0.42 * w, "H2O"),
        "P": _round_physical(101.2 + 0.01 * math.sin(2.0 * math.pi * 0.01 * t), "P"),
        "TA": _round_physical(23.8 + 0.08 * math.cos(2.0 * math.pi * 0.02 * t), "TA"),
    }


def _round_physical(value: float, column: str) -> float:
    step = abs(float(SCALE[column]))
    return round(round(float(value) / step) * step, 6)


def _physical_to_native(column: str, value: float, *, variant: str) -> int:
    scaled = (float(value) - float(OFFSET[column])) / float(SCALE[column])
    if variant == "slt_eddysoft" and column in EDDY_SOFT_HIGH_RES_COLUMNS:
        native = round(float(scaled) * 10.0 - 25000.0)
    else:
        native = round(float(scaled))
    if native < -32768 or native > 32767:
        raise ValueError(f"{variant} native value for {column} out of int16 range: {native}")
    return int(native)


def _manual_raw_flux(*, w: list[float], co2: list[float], pressure_kpa: list[float], temp_c: list[float]) -> float:
    mean_w = sum(w) / len(w)
    mean_co2 = sum(co2) / len(co2)
    cov_w_co2 = sum((wi - mean_w) * (ci - mean_co2) for wi, ci in zip(w, co2)) / len(w)
    mean_p_pa = (sum(pressure_kpa) / len(pressure_kpa)) * 1000.0
    mean_t_k = (sum(temp_c) / len(temp_c)) + 273.15
    return mean_p_pa / (8.314 * mean_t_k) * cov_w_co2


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(WORKSPACE_ROOT)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
