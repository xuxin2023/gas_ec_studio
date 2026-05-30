from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


QC_FLAG_TO_GRADE = {
    "0": "A",
    "1": "B",
    "2": "C",
    0: "A",
    1: "B",
    2: "C",
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "window_id": ("Filename", "filename", "File", "file", "window_id", "WINDOW_ID"),
    "date": ("date", "Date", "DATE"),
    "time": ("time", "Time", "TIME"),
    "start_time": ("start_time", "Start", "TIMESTAMP_START", "timestamp_start", "date_start"),
    "end_time": ("end_time", "End", "TIMESTAMP_END", "timestamp_end", "date_end"),
    "primary_flux": ("Fc", "FC", "co2_flux", "CO2_flux", "co2_flux_wpl", "FCO2"),
    "qc_grade": ("Fc_QC_Flag", "FC_QC", "qc_grade", "QC_FLAG", "qc_flag", "qc_co2_flux"),
    "lag_seconds": ("co2_lag", "CO2_lag", "lag_seconds", "max_cov_lag", "co2_time_lag"),
    "h2o_lag_seconds": ("H2O_lag", "h2o_lag", "h2o_time_lag"),
    "rotation_mode": ("rotation_method", "rotation_mode", "ROTATION_METHOD"),
    "wpl_water_vapor_term": ("WPL_water_vapor_term", "wpl_water_vapor_term"),
    "wpl_sensible_heat_term": ("WPL_sensible_heat_term", "wpl_sensible_heat_term"),
    "total_density_correction": ("total_density_correction", "TOTAL_DENSITY_CORRECTION"),
    "co2_flux": ("co2_flux", "CO2_flux"),
    "ch4_flux": ("ch4_flux", "CH4_flux", "FCH4"),
    "ch4_flux_level0_nmol_m2_s": ("FCH4_LEVEL0", "ch4_flux_level0_nmol_m2_s", "ch4_flux_level0"),
    "ch4_flux_level1_spectral_nmol_m2_s": ("FCH4_LEVEL1", "ch4_flux_level1_spectral_nmol_m2_s", "ch4_flux_level1"),
    "ch4_flux_level2_density_nmol_m2_s": ("FCH4_LEVEL2", "ch4_flux_level2_density_nmol_m2_s", "ch4_flux_level2"),
    "ch4_flux_corrected_nmol_m2_s": ("FCH4_LEVEL3", "FCH4_CORRECTED", "ch4_flux_corrected_nmol_m2_s"),
    "h2o_flux": ("h2o_flux", "H2O_flux", "FH2O"),
    "latent_heat_flux": ("LE", "latent_heat_flux"),
    "sensible_heat_flux": ("H", "sensible_heat_flux"),
    "momentum_flux": ("tau", "TAU", "momentum_flux"),
    "ustar": ("ustar", "u*", "USTAR"),
    "wind_speed": ("wind_speed", "WS", "WindSpeed"),
    "wind_dir": ("wind_dir", "WD", "WindDir"),
}

NUMERIC_FIELDS = {
    "primary_flux",
    "lag_seconds",
    "h2o_lag_seconds",
    "wpl_water_vapor_term",
    "wpl_sensible_heat_term",
    "total_density_correction",
    "co2_flux",
    "ch4_flux",
    "ch4_flux_level0_nmol_m2_s",
    "ch4_flux_level1_spectral_nmol_m2_s",
    "ch4_flux_level2_density_nmol_m2_s",
    "ch4_flux_corrected_nmol_m2_s",
    "h2o_flux",
    "latent_heat_flux",
    "sensible_heat_flux",
    "momentum_flux",
    "ustar",
    "wind_speed",
    "wind_dir",
}


def normalize_eddypro_full_output(
    input_path: str | Path,
    *,
    reference_id: str = "",
    normalization_command: str = "",
    metadata_source_files: list[str] | None = None,
) -> dict[str, Any]:
    source_path = Path(input_path)
    rows, raw_columns = _read_csv_rows(source_path)
    mapping = _resolved_mapping(raw_columns)
    windows = [_normalized_window(row, index=index, mapping=mapping) for index, row in enumerate(rows, start=1)]
    windows = [window for window in windows if window]
    unmapped_columns = [column for column in raw_columns if column not in mapping]
    now = datetime.now().isoformat()
    return {
        "reference_id": reference_id.strip() or source_path.stem,
        "source": f"EddyPro Full_Output CSV: {source_path.name}",
        "description": f"Normalized from EddyPro Full_Output CSV: {source_path.name}",
        "created_at": now,
        "normalization_time": now,
        "original_file": str(source_path),
        "field_mapping": mapping,
        "raw_columns": raw_columns,
        "unmapped_columns": unmapped_columns,
        "metadata_source_files": list(metadata_source_files or []),
        "processing_settings": _processing_settings(raw_columns=raw_columns, windows=windows),
        "method_metadata": _method_metadata(raw_columns=raw_columns, windows=windows),
        "qc_mapping_strategy": "EddyPro 0/1/2 -> gas_ec_studio A/B/C",
        "known_limitations": [
            "EddyPro QC flags are mapped approximately into A/B/C grades.",
            "Full_Output fields are post-processed EddyPro outputs; raw high-frequency parity still requires the matching raw bundle.",
            "Field aliases cover common EddyPro/FLUXNET names and should be reviewed for site-specific custom columns.",
        ],
        "normalization_command": normalization_command,
        "windows": windows,
    }


def write_eddypro_full_output_reference(
    input_path: str | Path,
    *,
    reference_path: str | Path,
    provenance_path: str | Path,
    reference_id: str = "",
    normalization_command: str = "",
    metadata_source_files: list[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_eddypro_full_output(
        input_path,
        reference_id=reference_id,
        normalization_command=normalization_command,
        metadata_source_files=metadata_source_files,
    )
    ref_path = Path(reference_path)
    prov_path = Path(provenance_path)
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    provenance = generate_eddypro_full_output_provenance(normalized, input_path=input_path, reference_path=ref_path)
    prov_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "artifact_type": "eddypro_full_output_normalization_result_v1",
        "status": "normalized" if normalized["windows"] else "empty_reference",
        "reference_path": str(ref_path),
        "provenance_path": str(prov_path),
        "reference_id": normalized["reference_id"],
        "window_count": len(normalized["windows"]),
        "field_mapping": normalized["field_mapping"],
        "unmapped_columns": normalized["unmapped_columns"],
    }


def generate_eddypro_full_output_provenance(
    normalized: dict[str, Any],
    *,
    input_path: str | Path,
    reference_path: str | Path,
) -> dict[str, Any]:
    return {
        "artifact_type": "eddypro_full_output_normalization_provenance_v1",
        "reference_id": normalized.get("reference_id", ""),
        "original_file": str(input_path),
        "original_file_name": Path(input_path).name,
        "reference_file": str(reference_path),
        "normalization_time": normalized.get("normalization_time", ""),
        "normalization_script": "core.comparison.eddypro_full_output_normalizer",
        "normalization_command": normalized.get("normalization_command", ""),
        "field_mapping": dict(normalized.get("field_mapping", {}) or {}),
        "raw_columns": list(normalized.get("raw_columns", []) or []),
        "unmapped_columns": list(normalized.get("unmapped_columns", []) or []),
        "metadata_source_files": list(normalized.get("metadata_source_files", []) or []),
        "processing_settings": dict(normalized.get("processing_settings", {}) or {}),
        "method_metadata": dict(normalized.get("method_metadata", {}) or {}),
        "qc_mapping_strategy": normalized.get("qc_mapping_strategy", ""),
        "known_limitations": list(normalized.get("known_limitations", []) or []),
        "window_count": len(list(normalized.get("windows", []) or [])),
        "required_fields_present": _required_fields_present(list(normalized.get("windows", []) or [])),
    }


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows:
        return [], []
    header_index = _eddypro_header_index(raw_rows)
    if header_index is None:
        header = [str(item).strip() for item in raw_rows[0]]
        data_rows = raw_rows[1:]
    else:
        header = [str(item).strip() for item in raw_rows[header_index]]
        data_rows = raw_rows[header_index + 1 :]
    rows = [
        {header[index]: str(row[index]).strip() if index < len(row) else "" for index in range(len(header)) if header[index]}
        for row in data_rows
        if row and not _looks_like_units_row(row)
    ]
    return rows, header


def _resolved_mapping(raw_columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    column_lookup = {column.lower(): column for column in raw_columns}
    for internal, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw_columns and alias not in mapping:
                mapping[alias] = internal
                break
            lowered = alias.lower()
            if lowered in column_lookup and column_lookup[lowered] not in mapping:
                mapping[column_lookup[lowered]] = internal
                break
    return mapping


def _normalized_window(row: dict[str, str], *, index: int, mapping: dict[str, str]) -> dict[str, Any]:
    by_internal = {target: row.get(source, "") for source, target in mapping.items()}
    window_id = str(by_internal.get("window_id", "") or f"eddypro_row_{index:04d}")
    start_time = _normalize_time(by_internal.get("start_time", ""))
    end_time = _normalize_time(by_internal.get("end_time", ""))
    if not start_time and not end_time:
        inferred_start, inferred_end = _infer_window_times(
            window_id=window_id,
            date_value=by_internal.get("date", ""),
            time_value=by_internal.get("time", ""),
        )
        start_time = inferred_start
        end_time = inferred_end
    window: dict[str, Any] = {
        "window_id": window_id,
        "start_time": start_time,
        "end_time": end_time,
        "primary_flux_source": "wpl",
        "lag_strategy": "covariance_max",
    }
    for key, raw_value in by_internal.items():
        if key in {"window_id", "date", "time", "start_time", "end_time"}:
            continue
        if key == "qc_grade":
            window["eddypro_qc_flag"] = raw_value
            window["qc_grade"] = QC_FLAG_TO_GRADE.get(str(raw_value), str(raw_value))
            continue
        if key in NUMERIC_FIELDS:
            value = _float_or_none(raw_value)
            if value is not None:
                window[key] = value
            continue
        if raw_value not in {"", "-9999", "-9999.0", "NaN", "nan"}:
            window[key] = raw_value
    if "rotation_mode" in window:
        window["applied_rotation_impl"] = window["rotation_mode"]
    return window


def _eddypro_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows[:8]):
        lowered = {str(cell).strip().lower() for cell in row if str(cell).strip()}
        if "filename" in lowered and "date" in lowered and "time" in lowered:
            return index
        if {"timestamp_start", "timestamp_end"}.issubset(lowered):
            return index
        if "co2_flux" in lowered and ("qc_co2_flux" in lowered or "filename" in lowered):
            return index
    return None


def _looks_like_units_row(row: list[str]) -> bool:
    values = [str(item).strip() for item in row if str(item).strip()]
    if not values:
        return True
    unit_like = sum(1 for item in values if item.startswith("[") and item.endswith("]"))
    return unit_like >= max(1, len(values) // 2)


def _infer_window_times(*, window_id: str, date_value: Any, time_value: Any) -> tuple[str, str]:
    start = _time_from_window_id(window_id)
    end = _date_time_to_iso(date_value, time_value)
    if start and not end:
        try:
            end = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat(timespec="seconds")
        except ValueError:
            end = ""
    return start, end


def _time_from_window_id(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 19 and text[4] == "-" and text[7] == "-" and text[10] == "T":
        candidate = text[:19]
        try:
            datetime.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
    if len(text) >= 17 and text[4] == "-" and text[7] == "-" and text[10] == "T":
        digits = text[11:17]
        if digits.isdigit():
            candidate = f"{text[:10]}T{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
            try:
                datetime.fromisoformat(candidate)
                return candidate
            except ValueError:
                pass
    return ""


def _date_time_to_iso(date_value: Any, time_value: Any) -> str:
    date_text = str(date_value or "").strip()
    time_text = str(time_value or "").strip()
    if not date_text or not time_text:
        return ""
    if len(time_text.split(":")) == 2:
        time_text = f"{time_text}:00"
    if len(time_text.split(":")) == 4:
        head = time_text.rsplit(":", 1)
        time_text = f"{head[0]}.{head[1]}"
    return _normalize_time(f"{date_text}T{time_text}")


def _normalize_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "T" in text:
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 12:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}T{digits[8:10]}:{digits[10:12]}:00"
    if len(digits) == 14:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}T{digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    return text


def _float_or_none(value: Any) -> float | None:
    text = str(value or "").strip()
    if text in {"", "-9999", "-9999.0", "NaN", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _processing_settings(*, raw_columns: list[str], windows: list[dict[str, Any]]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if any(column in raw_columns for column in ("WPL_water_vapor_term", "WPL_sensible_heat_term", "total_density_correction")):
        settings["density_correction"] = "WPL"
    if any(column.lower() in {"co2_lag", "h2o_lag"} for column in raw_columns):
        settings["lag_determination"] = "covariance_max"
    first_rotation = next((window.get("rotation_mode") for window in windows if window.get("rotation_mode")), "")
    if first_rotation:
        settings["rotation_mode"] = first_rotation
    if windows:
        settings["averaging_period_min"] = _window_minutes(windows[0])
    return settings


def _method_metadata(*, raw_columns: list[str], windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    raw_column_set = {column.lower() for column in raw_columns}
    first_rotation = next((window.get("rotation_mode") for window in windows if window.get("rotation_mode")), "")
    lag_reported = any(column in raw_column_set for column in {"co2_lag", "co2_time_lag"})
    density_reported = any("wpl" in column for column in raw_column_set)
    return {
        "rotation": {
            "reference_field": "rotation_method" if first_rotation else "",
            "raw_method": str(first_rotation or ""),
            "availability": "reported" if first_rotation else "not_reported",
            "evidence_source": "eddypro_full_output_column" if first_rotation else "missing_from_full_output",
        },
        "lag": {
            "reference_field": "co2_lag" if lag_reported else "",
            "raw_method": "reported_lag" if lag_reported else "",
            "availability": "reported" if lag_reported else "not_reported",
            "evidence_source": "eddypro_full_output_column" if lag_reported else "missing_from_full_output",
        },
        "density_correction": {
            "reference_field": "WPL_water_vapor_term",
            "raw_method": "WPL" if density_reported else "",
            "availability": "reported" if density_reported else "not_reported",
            "evidence_source": "eddypro_full_output_column" if density_reported else "missing_from_full_output",
        },
        "spectral_correction": {
            "reference_field": "",
            "raw_method": "",
            "availability": "not_reported",
            "evidence_source": "missing_from_full_output",
        },
        "footprint": {
            "reference_field": "",
            "raw_method": "",
            "availability": "not_reported",
            "evidence_source": "missing_from_full_output",
        },
        "uncertainty": {
            "reference_field": "",
            "raw_method": "",
            "availability": "not_reported",
            "evidence_source": "missing_from_full_output",
        },
    }


def _window_minutes(window: dict[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(str(window.get("start_time", "")))
        end = datetime.fromisoformat(str(window.get("end_time", "")))
    except ValueError:
        return None
    return round((end - start).total_seconds() / 60.0, 3)


def _required_fields_present(windows: list[dict[str, Any]]) -> bool:
    if not windows:
        return False
    return all(any(window.get(field) not in (None, "") for window in windows) for field in ("window_id", "start_time", "end_time", "primary_flux"))
