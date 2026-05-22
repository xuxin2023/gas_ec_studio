"""EddyPro reference normalization script.

Reads raw EddyPro v7 Full_Output CSV files, normalizes them into the
gas_ec_studio reference JSON format, and generates provenance documents.

Usage:
    python references/eddypro/normalize_reference.py <input_csv> <output_json> [--metadata <metadata_json_or_ini>] [--provenance <provenance_json>]
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

METHOD_FIELD_ALIASES = {
    "rotation": ["rotation_mode", "rotation_method", "rotation"],
    "lag": ["lag_determination", "lag_strategy", "lag_method", "co2_lag"],
    "detrend": ["detrend_method", "detrending_method", "detrend"],
    "density_correction": ["density_correction", "wpl_method", "wpl_correction"],
    "footprint": ["footprint_method", "footprint_model", "footprint"],
    "uncertainty": ["uncertainty_method", "random_uncertainty_method", "random_error_method"],
    "spectral_correction": ["frequency_correction", "spectral_correction_method", "spectral_correction"],
}

METHOD_DEFAULTS_FROM_COLUMNS = {
    "density_correction": ("WPL", ["WPL_water_vapor_term", "WPL_sensible_heat_term", "total_density_correction"]),
    "lag": ("covariance_max", ["co2_lag", "H2O_lag"]),
}


def normalize_csv(
    input_path: Path,
    *,
    field_mapping: dict[str, str] | None = None,
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    mapping = resolve_field_mapping(field_mapping)
    windows: list[dict[str, Any]] = []
    raw_columns: list[str] = []
    unmapped_columns: list[str] = []
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f)
        raw_columns = list(reader.fieldnames or [])
        for row in reader:
            mapped: dict[str, Any] = {}
            for source_col, target_key in mapping.items():
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
        if col not in mapping:
            unmapped_columns.append(col)
    sidecar_metadata = load_method_metadata_sidecar(metadata_path) if metadata_path else {}
    processing_settings = infer_processing_settings(
        raw_columns=raw_columns,
        windows=windows,
        sidecar_metadata=sidecar_metadata,
    )
    method_metadata = build_method_metadata(
        processing_settings=processing_settings,
        raw_columns=raw_columns,
        sidecar_metadata=sidecar_metadata,
    )
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
        "metadata_source_files": [str(metadata_path)] if metadata_path else [],
        "processing_settings": processing_settings,
        "method_metadata": method_metadata,
        "method_metadata_coverage": method_metadata_coverage(method_metadata),
        "qc_mapping_strategy": "EddyPro 0/1/2 -> gas_ec_studio A/B/C",
        "known_limitations": [
            "EddyPro QC flags are mapped approximately; original flag values are lost in normalized form",
            "WPL terms may use different sign conventions between EddyPro and gas_ec_studio",
            "EddyPro frequency correction (analytical) is applied before output; gas_ec_studio may apply it differently",
            "Lag determination may differ due to different search windows and default lags",
        ],
        "windows": windows,
    }


def resolve_field_mapping(field_mapping: dict[str, str] | None = None) -> dict[str, str]:
    mapping = dict(EDDYPRO_CSV_TO_INTERNAL)
    if not field_mapping:
        return mapping
    internal_fields = set(EDDYPRO_CSV_TO_INTERNAL.values()) | {
        "h2o_lag_seconds",
        "lag_strategy",
        "primary_flux_source",
        "applied_rotation_impl",
    }
    for key, value in field_mapping.items():
        source = str(key)
        target = str(value)
        if source in internal_fields and target not in internal_fields:
            mapping[target] = source
        else:
            mapping[source] = target
    return mapping


def load_method_metadata_sidecar(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    payload: dict[str, Any] = {}
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            payload.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if section:
            nested = payload.setdefault(section, {})
            if isinstance(nested, dict):
                nested[key] = value
        else:
            payload[key] = value
    return payload


def infer_processing_settings(
    *,
    raw_columns: list[str],
    windows: list[dict[str, Any]],
    sidecar_metadata: dict[str, Any],
) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    sidecar_settings = sidecar_metadata.get("processing_settings", {})
    if isinstance(sidecar_settings, dict):
        settings.update({str(key): value for key, value in sidecar_settings.items() if value not in ("", None)})
    flat_sidecar = flatten_metadata(sidecar_metadata)
    first_window = windows[0] if windows else {}
    for family, aliases in METHOD_FIELD_ALIASES.items():
        setting_key = family_to_processing_setting(family)
        if settings.get(setting_key):
            continue
        for alias in aliases:
            if alias in flat_sidecar and flat_sidecar[alias] not in ("", None):
                settings[setting_key] = flat_sidecar[alias]
                break
            if alias in first_window and first_window[alias] not in ("", None):
                settings[setting_key] = first_window[alias]
                break
    raw_column_set = set(raw_columns)
    for family, (method, required_columns) in METHOD_DEFAULTS_FROM_COLUMNS.items():
        setting_key = family_to_processing_setting(family)
        if not settings.get(setting_key) and any(column in raw_column_set for column in required_columns):
            settings[setting_key] = method
    return settings


def build_method_metadata(
    *,
    processing_settings: dict[str, Any],
    raw_columns: list[str],
    sidecar_metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    provided = sidecar_metadata.get("method_metadata", {})
    provided = provided if isinstance(provided, dict) else {}
    flat_sidecar = flatten_metadata(sidecar_metadata)
    raw_column_set = set(raw_columns)
    metadata: dict[str, dict[str, Any]] = {}
    for family, aliases in METHOD_FIELD_ALIASES.items():
        if isinstance(provided.get(family), dict):
            payload = dict(provided[family])
            raw_method = payload.get("raw_method", payload.get("method", ""))
            metadata[family] = {
                "reference_field": str(payload.get("reference_field", "")),
                "raw_method": str(raw_method or ""),
                "normalized_method": normalize_method_name(raw_method),
                "availability": "reported" if raw_method else str(payload.get("availability", "not_reported")),
                "evidence_source": str(payload.get("evidence_source", "method_metadata")),
            }
            continue
        setting_key = family_to_processing_setting(family)
        raw_method = processing_settings.get(setting_key, "")
        evidence_source = "processing_settings" if raw_method else "missing_from_reference_metadata"
        reference_field = setting_key
        for alias in aliases:
            if alias in flat_sidecar and flat_sidecar[alias] not in ("", None):
                raw_method = flat_sidecar[alias]
                evidence_source = "metadata_sidecar"
                reference_field = alias
                break
        if not raw_method:
            for alias in aliases:
                if alias in raw_column_set:
                    evidence_source = "raw_csv_column"
                    reference_field = alias
                    break
        metadata[family] = {
            "reference_field": reference_field,
            "raw_method": str(raw_method or ""),
            "normalized_method": normalize_method_name(raw_method),
            "availability": "reported" if raw_method else "not_reported",
            "evidence_source": evidence_source,
        }
    return metadata


def method_metadata_coverage(method_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reported = [family for family, payload in method_metadata.items() if payload.get("availability") == "reported"]
    not_reported = [family for family, payload in method_metadata.items() if payload.get("availability") != "reported"]
    return {
        "reported_families": reported,
        "not_reported_families": not_reported,
        "reported_count": len(reported),
        "total_count": len(method_metadata),
    }


def family_to_processing_setting(family: str) -> str:
    return {
        "rotation": "rotation_mode",
        "lag": "lag_determination",
        "detrend": "detrend_method",
        "density_correction": "density_correction",
        "footprint": "footprint_method",
        "uncertainty": "uncertainty_method",
        "spectral_correction": "frequency_correction",
    }[family]


def normalize_method_name(value: Any) -> str:
    method = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "block_average": "block_mean",
        "block_averaging": "block_mean",
        "double_rotation": "double",
        "covariance_maximum": "covariance_max",
        "max_covariance": "covariance_max",
        "webb_pearman_leuning": "wpl",
        "analytical_frequency_correction": "analytical",
    }
    return aliases.get(method, method)


def flatten_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            flat.update(flatten_metadata(value))
        else:
            flat[str(key)] = value
    return flat


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
        "metadata_source_files": normalized.get("metadata_source_files", []),
        "processing_settings": normalized.get("processing_settings", {}),
        "method_metadata": normalized.get("method_metadata", {}),
        "method_metadata_coverage": normalized.get("method_metadata_coverage", {}),
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
    metadata_path = None
    if "--metadata" in sys.argv:
        idx = sys.argv.index("--metadata")
        if idx + 1 < len(sys.argv):
            metadata_path = Path(sys.argv[idx + 1])
    if "--provenance" in sys.argv:
        idx = sys.argv.index("--provenance")
        if idx + 1 < len(sys.argv):
            provenance_path = Path(sys.argv[idx + 1])
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1
    normalized = normalize_csv(input_path, metadata_path=metadata_path)
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
