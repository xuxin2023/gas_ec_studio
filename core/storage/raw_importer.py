from __future__ import annotations

import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, RawColumnMapping


RAW_TEXT_SUFFIXES = {".csv", ".tsv", ".dat", ".txt", ".tob1", ".slt"}

DEFAULT_COLUMN_ALIASES = {
    "timestamp": ("timestamp", "datetime", "date_time", "time", "ts"),
    "co2_ppm": ("co2_ppm", "co2", "co2_molfrac", "co2_mixing_ratio"),
    "h2o_mmol": ("h2o_mmol", "h2o", "h2o_molfrac", "h2o_mixing_ratio"),
    "ch4_ppb": ("ch4_ppb", "ch4_ppm", "ch4", "methane", "ch4_molfrac", "ch4_mixing_ratio"),
    "pressure_kpa": ("pressure_kpa", "pressure", "press", "pa", "p"),
    "chamber_temp_c": ("chamber_temp_c", "temperature", "temp", "ta", "sonic_temperature"),
    "case_temp_c": ("case_temp_c", "cell_temperature", "analyzer_temperature"),
    "u": ("u", "u_ms", "u_mps", "wind_u", "u_unrot"),
    "v": ("v", "v_ms", "v_mps", "wind_v", "v_unrot"),
    "w": ("w", "w_ms", "w_mps", "wind_w", "vertical_velocity", "vertical_wind", "w_unrot"),
}


def load_raw_text_frames(
    path: str | Path,
    *,
    metadata: MetadataBundle | dict[str, Any] | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    mode: int = 2,
) -> list[NormalizedHFFrame]:
    bundle = metadata if isinstance(metadata, MetadataBundle) else (MetadataBundle.from_dict(dict(metadata)) if metadata else MetadataBundle())
    raw_settings = bundle.raw_file_settings
    raw_description = bundle.raw_file_description
    source_path = Path(path)
    delimiter = raw_settings.delimiter if raw_settings.delimiter not in {"", "auto"} else _infer_delimiter(source_path)
    text = source_path.read_text(encoding=raw_settings.encoding or "utf-8")
    rows = _read_tabular_text(
        text,
        delimiter=delimiter,
        header_rows=max(1, int(raw_settings.header_rows or 1)),
        missing_tokens=set(raw_settings.missing_tokens or []),
    )
    mappings = _mapping_by_variable(raw_description.column_mappings)
    resolved_device_uid = device_uid or bundle.project.code or raw_description.source_name or source_path.stem
    resolved_device_id = device_id or bundle.instruments.analyzer_model or "raw"
    frames: list[NormalizedHFFrame] = []
    for row in rows:
        frame = _frame_from_raw_row(
            row,
            mappings=mappings,
            source_path=source_path,
            device_uid=resolved_device_uid,
            device_id=resolved_device_id,
            mode=mode,
        )
        if frame is not None:
            frames.append(frame)
    frames.sort(key=lambda item: item.timestamp)
    return frames


def can_load_raw_text(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RAW_TEXT_SUFFIXES


def _read_tabular_text(
    text: str,
    *,
    delimiter: str,
    header_rows: int,
    missing_tokens: set[str],
) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("#", ";"))]
    if not lines:
        return []
    if header_rows > 1:
        lines = [lines[0], *lines[header_rows:]]
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=delimiter)
    output: list[dict[str, str]] = []
    for row in reader:
        cleaned = {
            str(key).strip().strip('"'): "" if value in missing_tokens else str(value).strip().strip('"')
            for key, value in row.items()
            if key is not None
        }
        output.append(cleaned)
    return output


def _frame_from_raw_row(
    row: dict[str, str],
    *,
    mappings: dict[str, RawColumnMapping],
    source_path: Path,
    device_uid: str,
    device_id: str,
    mode: int,
) -> NormalizedHFFrame | None:
    lookup = {key.lower(): value for key, value in row.items()}
    timestamp = _parse_timestamp(_mapped_value(lookup, mappings, "timestamp") or _first_lookup(lookup, DEFAULT_COLUMN_ALIASES["timestamp"]))
    if timestamp is None:
        return None
    wind_payload = {
        key: _mapped_float(lookup, mappings, key, aliases=DEFAULT_COLUMN_ALIASES[key])
        for key in ("u", "v", "w")
    }
    ch4_ppb = _mapped_float(lookup, mappings, "ch4_ppb", aliases=DEFAULT_COLUMN_ALIASES["ch4_ppb"])
    raw_payload = {
        key: value
        for key, value in {
            **wind_payload,
            "ch4_ppb": ch4_ppb,
            "raw_source": str(source_path),
        }.items()
        if value is not None
    }
    return NormalizedHFFrame(
        timestamp=timestamp,
        device_uid=device_uid,
        device_id=device_id,
        mode=int(mode),
        frame_quality=FrameQuality.FULL,
        co2_ppm=_mapped_float(lookup, mappings, "co2_ppm", aliases=DEFAULT_COLUMN_ALIASES["co2_ppm"]),
        h2o_mmol=_mapped_float(lookup, mappings, "h2o_mmol", aliases=DEFAULT_COLUMN_ALIASES["h2o_mmol"]),
        ch4_ppb=ch4_ppb,
        pressure_kpa=_mapped_float(lookup, mappings, "pressure_kpa", aliases=DEFAULT_COLUMN_ALIASES["pressure_kpa"]),
        chamber_temp_c=_mapped_float(lookup, mappings, "chamber_temp_c", aliases=DEFAULT_COLUMN_ALIASES["chamber_temp_c"]),
        case_temp_c=_mapped_float(lookup, mappings, "case_temp_c", aliases=DEFAULT_COLUMN_ALIASES["case_temp_c"]),
        status_text=f"raw_text_source={source_path.name}",
        raw_text=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
    )


def _mapping_by_variable(mappings: list[RawColumnMapping]) -> dict[str, RawColumnMapping]:
    by_variable: dict[str, RawColumnMapping] = {}
    aliases = {
        "co2": "co2_ppm",
        "h2o": "h2o_mmol",
        "ch4": "ch4_ppb",
        "methane": "ch4_ppb",
        "ch4_ppm": "ch4_ppb",
        "pressure": "pressure_kpa",
        "temperature": "chamber_temp_c",
        "temp": "chamber_temp_c",
        "ta": "chamber_temp_c",
        "time": "timestamp",
    }
    for mapping in mappings:
        if mapping.ignore:
            continue
        variable = mapping.variable.strip() or mapping.column_name.strip()
        variable = aliases.get(variable.lower(), variable)
        by_variable[variable] = mapping
    return by_variable


def _mapped_float(
    lookup: dict[str, str],
    mappings: dict[str, RawColumnMapping],
    variable: str,
    *,
    aliases: tuple[str, ...],
) -> float | None:
    mapping = mappings.get(variable)
    alias = ""
    if mapping is not None:
        value = _mapped_value(lookup, mappings, variable)
    else:
        item = _first_lookup_item(lookup, aliases)
        alias, value = item if item is not None else ("", None)
    number = _optional_float(value)
    if number is None:
        return None
    if mapping is not None and mapping.scaling is not None:
        number *= float(mapping.scaling)
    if mapping is None and variable == "ch4_ppb":
        return _convert_ch4_alias_value(number, alias)
    return _convert_units(number, mapping.input_unit if mapping else "", variable=variable)


def _mapped_value(lookup: dict[str, str], mappings: dict[str, RawColumnMapping], variable: str) -> str | None:
    mapping = mappings.get(variable)
    if mapping is None:
        return None
    return lookup.get(mapping.column_name.lower())


def _first_lookup(lookup: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        value = lookup.get(alias.lower())
        if value not in (None, ""):
            return value
    return None


def _first_lookup_item(lookup: dict[str, str], aliases: tuple[str, ...]) -> tuple[str, str] | None:
    for alias in aliases:
        value = lookup.get(alias.lower())
        if value not in (None, ""):
            return alias.lower(), value
    return None


def _convert_ch4_alias_value(value: float, alias: str) -> float:
    if alias == "ch4_ppm":
        return value * 1000.0
    if alias in {"ch4_molfrac", "ch4_mixing_ratio"} and abs(value) < 0.01:
        return value * 1_000_000_000.0
    if alias in {"ch4", "methane", "ch4_mixing_ratio"} and 0.0 < abs(value) < 10.0:
        return value * 1000.0
    return value


def _convert_units(value: float, unit: str, *, variable: str) -> float:
    normalized = unit.strip().lower().replace(" ", "")
    if variable == "pressure_kpa":
        if normalized in {"pa", "pascal", "pascals"}:
            return value / 1000.0
        if normalized in {"hpa", "mbar"}:
            return value / 10.0
    if variable in {"chamber_temp_c", "case_temp_c"} and normalized in {"k", "kelvin"}:
        return value - 273.15
    if variable == "co2_ppm" and normalized in {"mol/mol", "molmol-1"}:
        return value * 1_000_000.0
    if variable == "h2o_mmol" and normalized in {"mol/mol", "molmol-1"}:
        return value * 1000.0
    if variable == "ch4_ppb":
        if normalized in {"mol/mol", "molmol-1"}:
            return value * 1_000_000_000.0
        if normalized in {"ppm", "umol/mol", "micromol/mol"}:
            return value * 1000.0
    return value


def _infer_delimiter(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".tsv":
        return "\t"
    sample = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    return "\t" if sample.count("\t") > sample.count(",") else ","


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None
