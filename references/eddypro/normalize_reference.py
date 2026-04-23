"""EddyPro reference normalization script.

Reads raw EddyPro v7 Full_Output CSV files, normalizes them into the
gas_ec_studio reference JSON format, and generates provenance documents.

Usage:
    python references/eddypro/normalize_reference.py <input_csv> <output_json> [--provenance <provenance_json>]
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


EDDYPRO_CSV_TO_INTERNAL = {
    "Filename": "window_id",
    "start_time": "start_time",
    "end_time": "end_time",
    "Fc": "primary_flux",
    "Fc_QC_Flag": "qc_grade",
    "co2_lag": "lag_seconds",
    "H2O_lag": "h2o_lag_seconds",
    "rotation_method": "rotation_mode",
    "WPL_water_vapor_term": "wpl_water_vapor_term",
    "WPL_sensible_heat_term": "wpl_sensible_heat_term",
    "total_density_correction": "total_density_correction",
    "co2_flux": "co2_flux",
    "h2o_flux": "h2o_flux",
    "LE": "latent_heat_flux",
    "H": "sensible_heat_flux",
    "tau": "momentum_flux",
    "ustar": "ustar",
    "wind_speed": "wind_speed",
    "wind_dir": "wind_dir",
}

QC_FLAG_TO_GRADE = {
    "0": "A",
    "1": "B",
    "2": "C",
    0: "A",
    1: "B",
    2: "C",
}

REQUIRED_FIELDS = ["window_id", "start_time", "end_time", "primary_flux"]


def normalize_csv(input_path: Path, *, field_mapping: dict[str, str] | None = None) -> dict[str, Any]:
    mapping = dict(EDDYPRO_CSV_TO_INTERNAL)
    if field_mapping:
        mapping.update(field_mapping)
    reverse_mapping: dict[str, str] = {v: k for k, v in mapping.items()}
    windows: list[dict[str, Any]] = []
    raw_columns: list[str] = []
    unmapped_columns: list[str] = []
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f)
        raw_columns = list(reader.fieldnames or [])
        for row in reader:
            mapped: dict[str, Any] = {}
            for target_key, source_col in mapping.items():
                val = row.get(source_col, "")
                if val in ("", "-9999", "NaN", "-9999.0"):
                    mapped[target_key] = None
                else:
                    mapped[target_key] = val
            if not mapped.get("window_id"):
                mapped["window_id"] = f"ep_row_{len(windows)}"
            if not mapped.get("start_time"):
                mapped["start_time"] = ""
            if not mapped.get("end_time"):
                mapped["end_time"] = ""
            if mapped.get("qc_grade") is not None and str(mapped["qc_grade"]) in QC_FLAG_TO_GRADE:
                mapped["qc_grade"] = QC_FLAG_TO_GRADE[str(mapped["qc_grade"])]
            if mapped.get("primary_flux") is not None:
                try:
                    mapped["primary_flux"] = float(mapped["primary_flux"])
                except (ValueError, TypeError):
                    pass
            if mapped.get("lag_seconds") is not None:
                try:
                    mapped["lag_seconds"] = float(mapped["lag_seconds"])
                except (ValueError, TypeError):
                    pass
            mapped.setdefault("primary_flux_source", "wpl")
            mapped.setdefault("lag_strategy", "covariance_max")
            mapped.setdefault("applied_rotation_impl", mapped.get("rotation_mode", ""))
            windows.append(mapped)
    for col in raw_columns:
        if col not in mapping.values():
            unmapped_columns.append(col)
    reference_id = input_path.stem
    return {
        "reference_id": reference_id,
        "source": f"EddyPro v7 Full_Output CSV: {input_path.name}",
        "description": f"Normalized from raw EddyPro CSV: {input_path.name}",
        "created_at": datetime.now().isoformat(),
        "normalization_time": datetime.now().isoformat(),
        "original_file": str(input_path),
        "field_mapping": mapping,
        "raw_columns": raw_columns,
        "unmapped_columns": unmapped_columns,
        "qc_mapping_strategy": "EddyPro 0/1/2 -> gas_ec_studio A/B/C",
        "known_limitations": [
            "EddyPro QC flags are mapped approximately; original flag values are lost in normalized form",
            "WPL terms may use different sign conventions between EddyPro and gas_ec_studio",
            "EddyPro frequency correction (analytical) is applied before output; gas_ec_studio may apply it differently",
            "Lag determination may differ due to different search windows and default lags",
        ],
        "windows": windows,
    }


def generate_provenance(normalized: dict[str, Any], input_path: Path) -> dict[str, Any]:
    return {
        "reference_id": normalized["reference_id"],
        "original_file": str(input_path),
        "original_file_name": input_path.name,
        "normalization_time": normalized["normalization_time"],
        "normalization_script": "references/eddypro/normalize_reference.py",
        "field_mapping": normalized["field_mapping"],
        "raw_columns": normalized["raw_columns"],
        "unmapped_columns": normalized["unmapped_columns"],
        "qc_mapping_strategy": normalized["qc_mapping_strategy"],
        "known_limitations": normalized["known_limitations"],
        "window_count": len(normalized["windows"]),
        "required_fields_present": all(
            any(w.get(f) is not None for w in normalized["windows"])
            for f in REQUIRED_FIELDS
        ),
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input_csv> <output_json> [--provenance <provenance_json>]", file=sys.stderr)
        return 1
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    provenance_path = None
    if "--provenance" in sys.argv:
        idx = sys.argv.index("--provenance")
        if idx + 1 < len(sys.argv):
            provenance_path = Path(sys.argv[idx + 1])
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1
    normalized = normalize_csv(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Normalized reference written to: {output_path}")
    if provenance_path:
        provenance = generate_provenance(normalized, input_path)
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Provenance document written to: {provenance_path}")
    return 0


try:
    _csv = csv
except Exception:
    _csv = csv


if __name__ == "__main__":
    raise SystemExit(main())
