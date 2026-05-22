from __future__ import annotations

import csv
import json
import math
import struct
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, RawColumnMapping


RAW_TEXT_SUFFIXES = {".csv", ".tsv", ".dat", ".txt", ".tob1", ".slt"}
RAW_NATIVE_SUFFIXES = {".tob1", ".bin", ".raw", ".slt"}

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


def can_load_raw_native(path: str | Path, metadata: MetadataBundle | dict[str, Any] | None = None) -> bool:
    source_path = Path(path)
    if source_path.suffix.lower() not in RAW_NATIVE_SUFFIXES:
        return False
    bundle = metadata if isinstance(metadata, MetadataBundle) else (MetadataBundle.from_dict(dict(metadata)) if metadata else MetadataBundle())
    source_type = str(bundle.raw_file_description.source_type or "").strip().lower()
    native_format = str(bundle.raw_file_settings.extra.get("native_format", "") or "").strip().lower()
    return bool(native_format) or source_type in {
        "tob1",
        "tob1_ieee4",
        "binary",
        "native_binary",
        "slt",
        "slt_edisol",
        "slt_eddysoft",
    }


def load_raw_native_frames(
    path: str | Path,
    *,
    metadata: MetadataBundle | dict[str, Any] | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    mode: int = 2,
) -> list[NormalizedHFFrame]:
    bundle = metadata if isinstance(metadata, MetadataBundle) else (MetadataBundle.from_dict(dict(metadata)) if metadata else MetadataBundle())
    raw_description = bundle.raw_file_description
    raw_settings = bundle.raw_file_settings
    source_path = Path(path)
    native = _native_import_config(source_path=source_path, bundle=bundle)
    rows, provenance = _read_native_rows(source_path, native)
    mappings = _mapping_by_variable(raw_description.column_mappings)
    resolved_device_uid = device_uid or bundle.project.code or raw_description.source_name or source_path.stem
    resolved_device_id = device_id or bundle.instruments.analyzer_model or native["format"]
    frames: list[NormalizedHFFrame] = []
    for index, row in enumerate(rows):
        if "timestamp" not in {key.lower() for key in row}:
            row["timestamp"] = _generated_timestamp(index, native, sample_hz=float(raw_settings.sample_hz or 10.0))
        frame = _frame_from_raw_row(
            row,
            mappings=mappings,
            source_path=source_path,
            device_uid=resolved_device_uid,
            device_id=resolved_device_id,
            mode=mode,
        )
        if frame is not None:
            payload = _load_raw_payload(frame.raw_text)
            payload["raw_native_import"] = provenance
            frame.raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            frame.status_text = f"raw_native_source={source_path.name}; native_format={native['format']}"
            frames.append(frame)
    frames.sort(key=lambda item: item.timestamp)
    return frames


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


def _native_import_config(*, source_path: Path, bundle: MetadataBundle) -> dict[str, Any]:
    settings = bundle.raw_file_settings
    description = bundle.raw_file_description
    extra = dict(settings.extra or {})
    source_type = str(description.source_type or "").strip().lower()
    native_format = str(extra.get("native_format", "") or source_type or source_path.suffix.lower().lstrip(".")).strip().lower()
    if native_format == "tob1":
        native_format = "tob1_ieee4"
    if native_format == "slt":
        native_format = "slt_edisol"
    columns = extra.get("columns")
    if not isinstance(columns, list) or not columns:
        columns = [mapping.column_name for mapping in description.column_mappings if not mapping.ignore and mapping.column_name]
    if not columns:
        raise ValueError("Native raw import requires raw_file_settings.extra.columns or raw column mappings.")
    header_rows = int(extra.get("header_rows", settings.header_rows if native_format.startswith("tob1") else 0) or 0)
    config = {
        "format": native_format,
        "columns": [str(column) for column in columns],
        "data_type": str(extra.get("data_type", "float32" if native_format == "tob1_ieee4" else "int16")).lower(),
        "endian": str(extra.get("endian", "little")).lower(),
        "header_rows": header_rows,
        "header_bytes": int(extra.get("header_bytes", 0) or 0),
        "record_header_bytes": int(extra.get("record_header_bytes", 0) or 0),
        "record_length_bytes": int(extra.get("record_length_bytes", 0) or 0),
        "start_time": str(extra.get("start_time", "") or ""),
        "timestamp_step_seconds": extra.get("timestamp_step_seconds"),
        "scale": extra.get("scale", {}),
        "offset": extra.get("offset", {}),
        "slt_variant": str(extra.get("slt_variant", native_format.replace("slt_", ""))).lower(),
        "source_reference": {
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_engine_files": _native_source_files(native_format),
        },
    }
    return config


def _read_native_rows(source_path: Path, config: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    payload = source_path.read_bytes()
    native_format = str(config["format"])
    data_offset = int(config.get("header_bytes", 0) or 0)
    header_rows = int(config.get("header_rows", 0) or 0)
    if header_rows > 0:
        data_offset = max(data_offset, _offset_after_text_lines(payload, header_rows))
    if native_format == "tob1_ieee4":
        rows = _decode_fixed_records(payload[data_offset:], columns=config["columns"], data_type="float32", endian=config["endian"])
    elif native_format in {"binary", "native_binary", "binary_int16", "binary_float32"}:
        data_type = "float32" if "float32" in native_format else str(config.get("data_type", "int16"))
        rows = _decode_fixed_records(payload[data_offset:], columns=config["columns"], data_type=data_type, endian=config["endian"])
    elif native_format == "slt_edisol":
        header_bytes = int(config.get("header_bytes", 20) or 20)
        data_offset = max(data_offset, header_bytes)
        rows = _decode_fixed_records(payload[data_offset:], columns=config["columns"], data_type="int16", endian=config["endian"])
    elif native_format == "slt_eddysoft":
        header_bytes = int(config.get("header_bytes", 8 + max(0, len(config["columns"]) - 4) * 2) or 8)
        data_offset = max(data_offset, header_bytes)
        rows = _decode_fixed_records(payload[data_offset:], columns=config["columns"], data_type="int16", endian=config["endian"])
    else:
        raise ValueError(f"Unsupported native raw format: {native_format}")

    rows = [_apply_native_scale(row, config) for row in rows]
    provenance = {
        "status": "decoded" if rows else "empty",
        "format": native_format,
        "record_count": len(rows),
        "columns": list(config["columns"]),
        "data_type": config.get("data_type"),
        "endian": config.get("endian"),
        "header_rows": config.get("header_rows", 0),
        "header_bytes": data_offset,
        "source_file": str(source_path),
        "source_reference": config.get("source_reference", {}),
        "limitations": _native_import_limitations(native_format),
    }
    return rows, provenance


def _decode_fixed_records(
    payload: bytes,
    *,
    columns: list[str],
    data_type: str,
    endian: str,
) -> list[dict[str, str]]:
    fmt_char, size = _struct_format_for_native_type(data_type)
    endian_prefix = ">" if endian in {"big", "big_endian", "be"} else "<"
    record_format = endian_prefix + (fmt_char * len(columns))
    record_size = struct.calcsize(record_format)
    rows: list[dict[str, str]] = []
    for offset in range(0, len(payload) - record_size + 1, record_size):
        values = struct.unpack(record_format, payload[offset : offset + record_size])
        if not values:
            continue
        if all((not isinstance(value, float) or math.isfinite(value)) and abs(float(value)) < 1e-15 for value in values):
            break
        rows.append({column: _native_value_to_text(value) for column, value in zip(columns, values)})
    return rows


def _struct_format_for_native_type(data_type: str) -> tuple[str, int]:
    normalized = data_type.strip().lower()
    mapping = {
        "float32": ("f", 4),
        "ieee4": ("f", 4),
        "single": ("f", 4),
        "float64": ("d", 8),
        "double": ("d", 8),
        "int16": ("h", 2),
        "integer2": ("h", 2),
        "uint16": ("H", 2),
        "int32": ("i", 4),
        "uint32": ("I", 4),
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported native data_type: {data_type}")
    return mapping[normalized]


def _offset_after_text_lines(payload: bytes, line_count: int) -> int:
    if line_count <= 0:
        return 0
    count = 0
    index = 0
    while index < len(payload):
        byte = payload[index]
        index += 1
        if byte == 10:
            count += 1
            if count >= line_count:
                return index
    return index


def _apply_native_scale(row: dict[str, str], config: dict[str, Any]) -> dict[str, str]:
    scale = config.get("scale") if isinstance(config.get("scale"), dict) else {}
    offset = config.get("offset") if isinstance(config.get("offset"), dict) else {}
    if not scale and not offset:
        return row
    updated = dict(row)
    for key, value in row.items():
        factor = scale.get(key, 1.0)
        addend = offset.get(key, 0.0)
        if factor == 1.0 and addend == 0.0:
            continue
        number = _optional_float(value)
        if number is not None:
            updated[key] = _native_value_to_text(number * float(factor) + float(addend))
    return updated


def _generated_timestamp(index: int, config: dict[str, Any], *, sample_hz: float) -> str:
    start_time = str(config.get("start_time", "") or "")
    if not start_time:
        raise ValueError("Native raw import requires extra.start_time when timestamp is not stored in records.")
    start = datetime.fromisoformat(start_time)
    step = config.get("timestamp_step_seconds")
    step_s = float(step) if step not in (None, "") else 1.0 / max(float(sample_hz), 1.0)
    return (start + timedelta(seconds=float(index * step_s))).isoformat()


def _native_value_to_text(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.12g}"


def _load_raw_payload(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _native_source_files(native_format: str) -> list[str]:
    if native_format.startswith("tob1"):
        return ["src/src_common/import_tob1.f90"]
    if native_format.startswith("slt_eddysoft"):
        return ["src/src_common/import_slt_eddysoft.f90"]
    if native_format.startswith("slt"):
        return ["src/src_common/import_slt_edisol.f90"]
    return ["src/src_common/import_binary.f90"]


def _native_import_limitations(native_format: str) -> list[str]:
    limitations = [
        "Native reader bridge decodes fixed-record numeric payloads into NormalizedHFFrame and does not yet implement every EddyPro file interpreter branch.",
        "Timestamp generation requires metadata start_time when native records do not store timestamps.",
    ]
    if native_format == "tob1_ieee4":
        limitations.append("TOB1 FP2 lookup-table decoding is not yet implemented; IEEE4 float payloads are supported.")
    if native_format.startswith("slt"):
        limitations.append("SLT support covers fixed int16 EdiSol/EddySoft-style fixtures; full vendor dialect parity still needs real datasets.")
    return limitations


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
