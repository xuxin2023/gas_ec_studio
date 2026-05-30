from __future__ import annotations

import argparse
import json
import math
import struct
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import hashlib


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ID = "eddypro_source_tob1_seconds_001"
FIXTURE_DIR = Path("references/eddypro/source_derived")
TOB1_EPOCH = datetime(1990, 1, 1)
EDDYPRO_ENGINE_COMMIT = "3cabe637ca387e10254f1bd4a546341bf9be33b5"
GENERATED_AT = "2026-05-30T00:00:00+08:00"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and register the EddyPro source-derived TOB1 fixture.")
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
        pack_path = root / args.pack_path
        register_asset(pack_path, asset)
    print(json.dumps({"fixture_id": FIXTURE_ID, "asset": asset, "files": generated}, ensure_ascii=False, indent=2))
    return 0


def generate_fixture(fixture_dir: Path) -> dict[str, str]:
    raw_path = fixture_dir / f"{FIXTURE_ID}.tob1"
    metadata_path = fixture_dir / f"{FIXTURE_ID}_metadata.json"
    reference_path = fixture_dir / f"{FIXTURE_ID}_reference.json"
    provenance_path = fixture_dir / f"{FIXTURE_ID}_provenance.json"

    sample_hz = 10.0
    samples = 600
    start = datetime(2026, 5, 30, 8, 0, 0)
    decoded_rows: list[dict[str, float]] = []
    records: list[tuple[int, int, int, float, float, float, float, float, float, float]] = []
    for index in range(samples):
        t = index / sample_hz
        timestamp = start + timedelta(seconds=t)
        seconds_since_epoch = int((timestamp - TOB1_EPOCH).total_seconds())
        nanoseconds = int(round((t - math.floor(t)) * 1_000_000_000.0))
        w = 0.46 * math.sin(2.0 * math.pi * 0.17 * t) + 0.11 * math.cos(2.0 * math.pi * 0.53 * t)
        row = {
            "u": _float32(2.35 + 0.05 * math.sin(2.0 * math.pi * 0.03 * t)),
            "v": _float32(0.12 * math.cos(2.0 * math.pi * 0.07 * t)),
            "w": _float32(w),
            "co2": _float32(412.0 + 5.8 * w + 0.2 * math.sin(2.0 * math.pi * 0.02 * t)),
            "h2o": _float32(12.3 + 0.55 * w),
            "pressure": _float32(101.25 + 0.01 * math.sin(2.0 * math.pi * 0.01 * t)),
            "temperature": _float32(24.2 + 0.08 * math.cos(2.0 * math.pi * 0.02 * t)),
        }
        decoded_rows.append(row)
        records.append(
            (
                seconds_since_epoch,
                nanoseconds,
                index + 1,
                row["u"],
                row["v"],
                row["w"],
                row["co2"],
                row["h2o"],
                row["pressure"],
                row["temperature"],
            )
        )
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"SECONDS","NANOSECONDS","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"ULONG","ULONG","ULONG","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4"\r\n'
    )
    raw_path.write_bytes(header + b"".join(struct.pack("<3I7f", *record) for record in records))

    metadata = {
        "project": {"code": "SRC-TOB1", "name": "EddyPro Source-Derived TOB1 Conformance"},
        "site": {"station_code": "SRC-TOB1", "station_name": "Source-Derived TOB1 Conformance Site"},
        "raw_file_description": {
            "source_name": FIXTURE_ID,
            "source_type": "tob1",
            "timezone": "UTC",
            "notes": "Source-derived TOB1 IEEE4 conformance fixture based on EddyPro import_tob1.f90 layout rules.",
        },
        "raw_file_settings": {
            "sample_hz": sample_hz,
            "extra": {
                "native_format": "tob1_ieee4",
                "tob1_format": "IEEE4"
            },
        },
        "metadata_version": "ec_core_metadata_v1",
        "notes": [
            "Source-derived conformance fixture, not a public field dataset.",
            "Record timestamps come from TOB1 SECONDS/NANOSECONDS leading ULONG fields.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    primary_flux = _manual_raw_flux(
        w=[row["w"] for row in decoded_rows],
        co2=[row["co2"] for row in decoded_rows],
        pressure_kpa=[row["pressure"] for row in decoded_rows],
        temp_c=[row["temperature"] for row in decoded_rows],
    )
    reference = {
        "reference_id": f"{FIXTURE_ID}_source_derived_oracle",
        "source": "EddyPro engine source-derived TOB1 conformance oracle",
        "description": "Reference window validates TOB1 IEEE4 layout, leading ULONG preservation, and SECONDS/NANOSECONDS timestamp decoding.",
        "created_at": GENERATED_AT,
        "source_repositories": {
            "eddypro_engine": {
                "url": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "commit": EDDYPRO_ENGINE_COMMIT,
                "source_files": [
                    "src/src_common/import_tob1.f90",
                    "src/src_common/m_fp2_to_float.f90",
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
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(seconds=(samples - 1) / sample_hz)).isoformat(),
                "primary_flux": primary_flux,
                "primary_flux_source": "none",
                "lag_seconds": 0.0,
                "lag_strategy": "constant",
                "rotation_mode": "none",
                "applied_rotation_impl": "none",
                "qc_grade": "",
                "notes": "Source-derived TOB1 conformance oracle; not an official EddyPro executable output.",
            }
        ],
        "known_limitations": [
            "This fixture is generated from EddyPro source-code import rules and deterministic signals.",
            "It is not a real field TOB1/SLT dataset and must not close real-world fixture breadth blockers.",
        ],
    }
    reference_path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")

    provenance = {
        "artifact_type": "source_derived_tob1_fixture_provenance_v1",
        "fixture_id": FIXTURE_ID,
        "source_file": _rel(raw_path),
        "metadata_file": _rel(metadata_path),
        "reference_file": _rel(reference_path),
        "generation_time": GENERATED_AT,
        "generation_method": "Deterministic TOB1 IEEE4 binary generated from EddyPro source-code import semantics.",
        "normalization_script": "scripts/generate_source_derived_tob1_fixture.py",
        "normalization_command": "python scripts/generate_source_derived_tob1_fixture.py --register",
        "qc_mapping_strategy": reference["qc_mapping_strategy"],
        "source_repositories": reference["source_repositories"],
        "raw_columns": ["SECONDS", "NANOSECONDS", "RECORD", "U", "V", "W", "CO2", "H2O", "P", "TA"],
        "method_metadata": {
            "raw_format": "tob1_ieee4",
            "timestamp_source": "tob1_record_seconds_nanoseconds",
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
    asset = {
        "fixture_id": FIXTURE_ID,
        "tier": "raw_to_final_parity",
        "site_class": "source_derived_tob1_conformance",
        "software": "gas_ec_studio source-derived EddyPro engine conformance oracle",
        "software_version": f"eddypro-engine@{EDDYPRO_ENGINE_COMMIT[:12]}",
        "source_derived": True,
        "source_derived_from": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_engine_commit": EDDYPRO_ENGINE_COMMIT,
            "eddypro_engine_files": [
                "src/src_common/import_tob1.f90",
                "src/src_common/m_fp2_to_float.f90",
            ],
        },
        **files,
        "rp_config": {
            "sample_hz": 10.0,
            "block_minutes": 1.0,
            "steps": {"window_sampling": {"sample_hz": 10.0, "window_minutes": 1.0}},
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
            "Source-derived TOB1 conformance fixture validates importer and raw-to-final harness behavior.",
            "Reference output is a deterministic source-derived oracle, not an official EddyPro executable output.",
            "Real TOB1/SLT/native binary field fixtures with matching EddyPro output are still required before claiming broad parity.",
        ],
    }
    asset["expected_sha256"] = {
        role: _sha256(WORKSPACE_ROOT / path)
        for role, path in files.items()
    }
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
    gaps = [str(item) for item in list(updated.get("coverage_gaps", []) or [])]
    updated["coverage_gaps"] = [
        gap for gap in gaps
        if gap != "Need TOB1/SLT/binary raw fixtures with EddyPro import-output parity."
    ]
    if "Need real TOB1/SLT/binary field fixtures with official EddyPro Full_Output parity." not in updated["coverage_gaps"]:
        updated["coverage_gaps"].insert(0, "Need real TOB1/SLT/binary field fixtures with official EddyPro Full_Output parity.")
    pack_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")


def _manual_raw_flux(*, w: list[float], co2: list[float], pressure_kpa: list[float], temp_c: list[float]) -> float:
    mean_w = sum(w) / len(w)
    mean_co2 = sum(co2) / len(co2)
    cov_w_co2 = sum((wi - mean_w) * (ci - mean_co2) for wi, ci in zip(w, co2)) / len(w)
    mean_p_pa = (sum(pressure_kpa) / len(pressure_kpa)) * 1000.0
    mean_t_k = (sum(temp_c) / len(temp_c)) + 273.15
    return mean_p_pa / (8.314 * mean_t_k) * cov_w_co2


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(WORKSPACE_ROOT)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
