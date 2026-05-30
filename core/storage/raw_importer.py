from __future__ import annotations

import csv
import json
import math
import re
import struct
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, RawColumnMapping


RAW_TEXT_SUFFIXES = {".csv", ".tsv", ".dat", ".txt", ".log", ".ygas", ".tob1", ".slt"}
RAW_NATIVE_SUFFIXES = {".tob1", ".bin", ".raw", ".slt"}
TOB1_DATA_TYPE_TOKENS = {"ULONG", "IEEE4", "FP2"}
TOB1_LEADING_ULONG_VALUE_PREFIX = "tob1_leading_"
TOB1_CAMPBELL_TIMESTAMP_EPOCH = datetime(1990, 1, 1)
TOB1_RECORD_SECONDS_ALIASES = {"seconds", "second", "sec", "secs", "timestamp_seconds", "seconds_since_1990"}
TOB1_RECORD_NANOSECONDS_ALIASES = {
    "nanoseconds",
    "nanosecond",
    "nanosecs",
    "nanosec",
    "nsec",
    "ns",
    "timestamp_nanoseconds",
}

DEFAULT_COLUMN_ALIASES = {
    "timestamp": ("timestamp", "datetime", "date_time", "time", "ts"),
    "co2_ppm": ("co2_ppm", "co2", "co2_molfrac", "co2_mixing_ratio"),
    "h2o_mmol": ("h2o_mmol", "h2o", "h2o_molfrac", "h2o_mixing_ratio", "h2o_mmol_mol"),
    "ch4_ppb": ("ch4_ppb", "ch4_ppm", "ch4", "methane", "ch4_molfrac", "ch4_mixing_ratio"),
    "pressure_kpa": ("pressure_kpa", "pressure", "press", "pa", "p"),
    "chamber_temp_c": ("chamber_temp_c", "temperature", "temp", "ta", "sonic_temperature"),
    "case_temp_c": ("case_temp_c", "cell_temperature", "analyzer_temperature"),
    "u": ("u", "u_ms", "u_mps", "wind_u", "u_unrot"),
    "v": ("v", "v_ms", "v_mps", "wind_v", "v_unrot"),
    "w": ("w", "w_ms", "w_mps", "wind_w", "vertical_velocity", "vertical_wind", "w_unrot"),
}

LI7700_DIAGNOSTIC_ALIASES = {
    "li7700_rssi": (
        "li7700_rssi",
        "li_7700_rssi",
        "rssi",
        "rssi_pct",
        "rss_pct",
        "rss",
        "rss_77",
        "rss77",
        "received_signal_strength",
    ),
    "signal_strength": (
        "li7700_signal_strength",
        "li_7700_signal_strength",
        "signal_strength",
        "signal_strength_pct",
        "ch4_signal_strength",
        "optical_signal",
    ),
    "mirror_rssi": (
        "mirror_rssi",
        "mirror_signal",
        "mirror_signal_strength",
        "mirror_rssi_pct",
        "li7700_mirror_rssi",
        "mirrorrssi",
    ),
    "mirror_dirty": (
        "mirror_dirty",
        "mirrordirty",
        "mirror_contaminated",
        "mirrorcontaminated",
        "dirty_mirror",
        "dirtymirror",
        "mirror_warning",
        "mirrorwarning",
        "li7700_mirror_dirty",
    ),
    "pll_locked": (
        "pll_lock",
        "pll_locked",
        "plllock",
        "plllocked",
        "laser_lock",
        "laser_locked",
        "laserlock",
        "laserlocked",
        "reference_lock",
        "reference_locked",
        "referencelock",
        "referencelocked",
        "li7700_pll_locked",
    ),
    "diagnostic_status": (
        "li7700_status",
        "li7700_diagnostic_status",
        "diagnostic_status",
        "diagnosticstatus",
        "instrument_status",
        "instrumentstatus",
        "diag_status",
        "diagstatus",
    ),
    "li7700_status_word": (
        "li7700_status_word",
        "li_7700_status_word",
        "li7700_diagnostic_word",
        "diagnostic_word",
        "diagnosticword",
        "diagnostic_code",
        "diagnosticcode",
        "status_code",
        "statuscode",
        "diag_code",
        "diagcode",
    ),
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
    if _looks_like_ygas_protocol(text, bundle):
        return _load_ygas_protocol_frames(
            text,
            source_path=source_path,
            bundle=bundle,
            device_uid=device_uid,
            device_id=device_id,
            mode=mode,
        )
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


def _looks_like_ygas_protocol(text: str, bundle: MetadataBundle) -> bool:
    source_type = str(bundle.raw_file_description.source_type or "").strip().lower()
    if source_type in {"ygas_protocol", "gas_analyzer_protocol", "ygas"}:
        return True
    for line in str(text or "").splitlines():
        candidate = line.strip().strip("<>")
        if not candidate:
            continue
        return candidate.upper().startswith("YGAS,")
    return False


def _load_ygas_protocol_frames(
    text: str,
    *,
    source_path: Path,
    bundle: MetadataBundle,
    device_uid: str | None,
    device_id: str | None,
    mode: int,
) -> list[NormalizedHFFrame]:
    settings = bundle.raw_file_settings
    resolved_device_uid = device_uid or bundle.project.code or bundle.raw_file_description.source_name or source_path.stem
    sample_hz = float(settings.sample_hz or 10.0)
    start_time = str(settings.extra.get("start_time", "") or "")
    start = datetime.fromisoformat(start_time) if start_time else datetime(2000, 1, 1)
    frames: list[NormalizedHFFrame] = []
    for index, line in enumerate(line for line in text.splitlines() if line.strip()):
        raw = line.strip()
        parsed = parse_mode2_frame(raw) or parse_mode1_frame(raw)
        if not parsed:
            continue
        timestamp = start + timedelta(seconds=index / max(sample_hz, 1.0))
        payload = {
            "raw_source": str(source_path),
            "ygas_protocol_import": {
                "status": "decoded",
                "format": "ygas_protocol",
                "source_file": str(source_path),
                "source_reference": {
                    "manual": "D:/手册/气体分析仪指令.docx",
                    "manual_title": "气体分析仪指令表",
                },
                "limitations": [
                    "Protocol logs without explicit timestamps use raw_file_settings.extra.start_time plus sample_hz.",
                    "Checksum is preserved in parsed payload when present but not validated because the manual does not specify the algorithm.",
                ],
            },
            "ygas_parsed": parsed,
        }
        frames.append(
            NormalizedHFFrame(
                timestamp=timestamp,
                device_uid=resolved_device_uid,
                device_id=device_id or str(parsed.get("device_id") or bundle.instruments.analyzer_instrument_id or "YGAS"),
                mode=int(parsed.get("mode") or mode),
                frame_quality=parsed.get("frame_quality", FrameQuality.FULL),
                co2_ppm=parsed.get("co2_ppm"),
                h2o_mmol=parsed.get("h2o_mmol"),
                pressure_kpa=parsed.get("pressure_kpa"),
                chamber_temp_c=parsed.get("chamber_temp_c"),
                case_temp_c=parsed.get("case_temp_c"),
                status_text=parsed.get("status_text"),
                raw_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
        )
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
    if source_path.suffix.lower() == ".tob1" and _detect_tob1_native_format(source_path):
        return True
    return bool(native_format) or source_type in {
        "tob1",
        "tob1_ieee4",
        "tob1_fp2",
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
    record_index_offset = int(native.get("record_index_offset", max(0, int(native.get("first_record", 1) or 1) - 1)) or 0)
    for index, row in enumerate(rows):
        if "timestamp" not in {key.lower() for key in row}:
            row["timestamp"] = _generated_timestamp(
                index + record_index_offset,
                native,
                sample_hz=float(raw_settings.sample_hz or 10.0),
            )
        frame = _frame_from_raw_row(
            row,
            mappings=mappings,
            source_path=source_path,
            device_uid=resolved_device_uid,
            device_id=resolved_device_id,
            mode=mode,
            retain_decoded_columns=True,
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
    suffix_format = source_path.suffix.lower().lstrip(".")
    if source_type == "csv" and suffix_format in {"tob1", "slt", "bin", "raw"}:
        source_type = "binary" if suffix_format in {"bin", "raw"} else suffix_format
    native_format = str(extra.get("native_format", "") or source_type or source_path.suffix.lower().lstrip(".")).strip().lower()
    tob1_header = _inspect_tob1_header(source_path) if native_format == "tob1" or native_format.startswith("tob1") else {}
    if native_format == "tob1":
        tob1_format = str(extra.get("tob1_format", "") or tob1_header.get("tob1_format") or _detect_tob1_native_format(source_path) or "ieee4").strip().lower()
        native_format = "tob1_fp2" if tob1_format == "fp2" else "tob1_ieee4"
    if native_format == "slt":
        native_format = "slt_edisol"
    explicit_columns = extra.get("columns")
    explicit_column_list = [str(column) for column in explicit_columns] if isinstance(explicit_columns, list) and explicit_columns else []
    tob1_header_columns = [str(column) for column in list(tob1_header.get("columns", []) or [])]
    requested_columns: list[str] = []
    requested_column_source = ""
    columns: list[Any] = []
    column_source = ""
    if explicit_column_list:
        requested_columns = explicit_column_list
        requested_column_source = "extra"
        resolved_selection = _resolve_tob1_explicit_columns(explicit_column_list, tob1_header_columns)
        if native_format.startswith("tob1") and tob1_header_columns and resolved_selection and resolved_selection != tob1_header_columns:
            # TOB1 binary records are fixed-width; decode the header-declared
            # record first, then let mappings/aliases select requested fields.
            columns = tob1_header_columns
            column_source = "tob1_header"
        elif native_format.startswith("tob1") and resolved_selection:
            columns = resolved_selection
            column_source = "extra"
        else:
            columns = explicit_column_list
            column_source = "extra"
    elif native_format.startswith("tob1") and tob1_header_columns:
        # TOB1 records must be decoded at full record width; metadata mappings
        # may intentionally select only a subset of those decoded columns.
        columns = tob1_header_columns
        column_source = "tob1_header"
    else:
        columns = [mapping.column_name for mapping in description.column_mappings if not mapping.ignore and mapping.column_name]
        column_source = "metadata_column_mappings"
    if not columns:
        raise ValueError("Native raw import requires raw_file_settings.extra.columns or raw column mappings.")
    columns = [str(column) for column in columns]
    data_type = str(extra.get("data_type", "fp2" if native_format == "tob1_fp2" else ("float32" if native_format == "tob1_ieee4" else "int16"))).lower()
    column_types = _normalize_column_types(
        extra.get("column_types", extra.get("data_types")),
        columns=columns,
        default_type=data_type,
    )
    column_type_source = "extra" if column_types else ""
    if not column_types and native_format == "tob1_ieee4":
        inferred_column_types = _tob1_payload_column_types(
            raw_columns=list(tob1_header.get("raw_columns", []) or []),
            data_types=list(tob1_header.get("data_types", []) or []),
            columns=columns,
        )
        if inferred_column_types and any(item != "float32" for item in inferred_column_types):
            column_types = inferred_column_types
            column_type_source = "tob1_header"
    if "header_rows" in extra:
        header_rows = int(extra.get("header_rows") or 0)
        header_row_source = "extra"
    elif native_format.startswith("tob1") and int(tob1_header.get("header_rows", 0) or 0) > 0:
        header_rows = int(tob1_header.get("header_rows", 0) or 0)
        header_row_source = "tob1_header"
    else:
        header_rows = int(settings.header_rows if native_format.startswith("tob1") else 0)
        header_row_source = "metadata_settings"
    first_record = int(extra.get("first_record", extra.get("first_record_index", 1)) or 1)
    last_record_raw = extra.get("last_record", extra.get("last_record_index"))
    last_record = int(last_record_raw) if last_record_raw not in (None, "") else 0
    if first_record < 1:
        raise ValueError("Native raw first_record must be one-based and greater than zero.")
    if last_record and last_record < first_record:
        raise ValueError("Native raw last_record must be greater than or equal to first_record.")
    compatibility = dict(tob1_header.get("eddypro_compatibility", {}) or {})
    explicit_skip_words = extra.get("fp2_skip_words")
    explicit_ulongs = extra.get("ulongs")
    if explicit_skip_words not in (None, ""):
        leading_ulongs = int(explicit_ulongs or 0)
        fp2_skip_words = int(explicit_skip_words or 0) if native_format == "tob1_fp2" else 0
        ulongs_source = "extra.fp2_skip_words"
    elif explicit_ulongs not in (None, ""):
        leading_ulongs = int(explicit_ulongs or 0)
        fp2_skip_words = leading_ulongs * 2 if native_format == "tob1_fp2" else 0
        ulongs_source = "extra.ulongs"
    elif native_format in {"tob1_fp2", "tob1_ieee4"} and compatibility.get("status") == "compatible":
        leading_ulongs = int(compatibility.get("leading_ulong_count", 0) or 0)
        fp2_skip_words = leading_ulongs * 2 if native_format == "tob1_fp2" else 0
        ulongs_source = "tob1_header"
    else:
        leading_ulongs = 0
        fp2_skip_words = 0
        ulongs_source = ""
    leading_ulong_columns = _tob1_leading_ulong_columns(
        raw_columns=list(tob1_header.get("raw_columns", []) or []),
        data_types=list(tob1_header.get("data_types", []) or []),
        leading_count=leading_ulongs,
    )
    timestamp_resolution = _native_timestamp_resolution(source_path=source_path, extra=extra)
    config = {
        "format": native_format,
        "columns": columns,
        "requested_columns": requested_columns,
        "requested_column_source": requested_column_source,
        "column_source": column_source,
        "full_record_decode": native_format.startswith("tob1") and column_source == "tob1_header",
        "preserved_leading_ulong_values": native_format in {"tob1_fp2", "tob1_ieee4"} and leading_ulongs > 0,
        "leading_ulong_value_prefix": TOB1_LEADING_ULONG_VALUE_PREFIX,
        "data_type": "mixed" if column_types else data_type,
        "column_types": column_types,
        "column_type_source": column_type_source,
        "endian": _normalize_native_endian(extra.get("endian", extra.get("byte_order", extra.get("byteorder", extra.get("endianness", "little"))))),
        "header_rows": header_rows,
        "header_row_source": header_row_source,
        "raw_header_units": list(tob1_header.get("raw_units", []) or []),
        "header_units": list(tob1_header.get("units", []) or []),
        "raw_header_processing": list(tob1_header.get("raw_processing", []) or []),
        "header_processing": list(tob1_header.get("processing", []) or []),
        "ascii_header_eol": _normalize_header_eol(extra.get("ascii_header_eol", extra.get("binary_eol", extra.get("header_eol", "auto")))),
        "header_bytes": int(extra.get("header_bytes", 0) or 0),
        "record_header_bytes": int(extra.get("record_header_bytes", 0) or 0),
        "record_length_bytes": int(extra.get("record_length_bytes", 0) or 0),
        "record_footer_bytes": int(extra.get("record_footer_bytes", extra.get("record_trailer_bytes", 0)) or 0),
        "first_record": first_record,
        "last_record": last_record,
        "record_index_offset": first_record - 1,
        "ulongs": leading_ulongs,
        "leading_ulong_columns": leading_ulong_columns,
        "ulongs_source": ulongs_source,
        "fp2_skip_words": fp2_skip_words,
        "start_time": str(timestamp_resolution.get("start_time", "") or ""),
        "timestamp_source": str(timestamp_resolution.get("source", "") or ""),
        "filename_timestamp": timestamp_resolution,
        "timestamp_step_seconds": extra.get("timestamp_step_seconds"),
        "scale": extra.get("scale", {}),
        "offset": extra.get("offset", {}),
        "slt_variant": str(extra.get("slt_variant", native_format.replace("slt_", ""))).lower(),
        "header_detection": tob1_header,
        "tob1_eddypro_compatibility": compatibility,
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
    header_detection = dict(config.get("header_detection", {}) or {})
    if header_rows > 0:
        data_offset = max(data_offset, _offset_after_text_lines(payload, header_rows, eol=str(config.get("ascii_header_eol", "auto"))))
    if native_format == "tob1_ieee4":
        rows = _decode_tob1_ieee4_records(
            payload[data_offset:],
            columns=config["columns"],
            endian=config["endian"],
            leading_ulongs=int(config.get("ulongs", 0) or 0),
            leading_ulong_columns=list(config.get("leading_ulong_columns", []) or []),
            column_types=list(config.get("column_types", []) or []),
            record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
            record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
            record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
        )
    elif native_format == "tob1_fp2":
        rows = _decode_fp2_records(
            payload[data_offset:],
            columns=config["columns"],
            endian=config["endian"],
            skip_words=int(config.get("fp2_skip_words", config.get("ulongs", 0)) or 0),
            leading_ulong_columns=list(config.get("leading_ulong_columns", []) or []),
            record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
            record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
            record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
        )
    elif native_format in {"binary", "native_binary", "binary_int16", "binary_float32"}:
        column_types = list(config.get("column_types", []) or [])
        if column_types:
            rows = _decode_mixed_records(
                payload[data_offset:],
                columns=config["columns"],
                column_types=column_types,
                endian=config["endian"],
                record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
                record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
                record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
            )
        else:
            data_type = "float32" if "float32" in native_format else str(config.get("data_type", "int16"))
            rows = _decode_fixed_records(
                payload[data_offset:],
                columns=config["columns"],
                data_type=data_type,
                endian=config["endian"],
                record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
                record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
                record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
            )
    elif native_format == "slt_edisol":
        header_bytes = int(config.get("header_bytes", 20) or 20)
        data_offset = max(data_offset, header_bytes)
        rows = _decode_fixed_records(
            payload[data_offset:],
            columns=config["columns"],
            data_type="int16",
            endian=config["endian"],
            record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
            record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
            record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
        )
    elif native_format == "slt_eddysoft":
        default_header_bytes = 8 + max(0, len(config["columns"]) - 4) * 2
        header_bytes = int(config.get("header_bytes", 0) or default_header_bytes)
        data_offset = max(data_offset, header_bytes)
        header_detection = _inspect_slt_eddysoft_header(
            payload,
            columns=list(config["columns"]),
            header_bytes=header_bytes,
        )
        rows = _decode_fixed_records(
            payload[data_offset:],
            columns=config["columns"],
            data_type="int16",
            endian=config["endian"],
            record_header_bytes=int(config.get("record_header_bytes", 0) or 0),
            record_length_bytes=int(config.get("record_length_bytes", 0) or 0),
            record_footer_bytes=int(config.get("record_footer_bytes", 0) or 0),
        )
        rows = _apply_slt_eddysoft_high_resolution(rows, header_detection=header_detection)
    else:
        raise ValueError(f"Unsupported native raw format: {native_format}")

    decoded_record_count = len(rows)
    rows = _slice_native_rows(
        rows,
        first_record=int(config.get("first_record", 1) or 1),
        last_record=int(config.get("last_record", 0) or 0),
    )
    rows = [_apply_native_scale(row, config) for row in rows]
    record_timestamp = _apply_native_record_timestamps(rows, config)
    provenance = {
        "status": "decoded" if rows else "empty",
        "format": native_format,
        "record_count": len(rows),
        "decoded_record_count": decoded_record_count,
        "columns": list(config["columns"]),
        "requested_columns": list(config.get("requested_columns", []) or []),
        "requested_column_source": config.get("requested_column_source", ""),
        "column_source": config.get("column_source", ""),
        "full_record_decode": bool(config.get("full_record_decode", False)),
        "preserved_leading_ulong_values": bool(config.get("preserved_leading_ulong_values", False)),
        "leading_ulong_value_prefix": config.get("leading_ulong_value_prefix", ""),
        "data_type": config.get("data_type"),
        "column_types": list(config.get("column_types", []) or []),
        "column_type_source": config.get("column_type_source", ""),
        "endian": config.get("endian"),
        "ulongs": config.get("ulongs", 0),
        "leading_ulong_columns": list(config.get("leading_ulong_columns", []) or []),
        "ulongs_source": config.get("ulongs_source", ""),
        "fp2_skip_words": config.get("fp2_skip_words", 0),
        "header_rows": config.get("header_rows", 0),
        "header_row_source": config.get("header_row_source", ""),
        "raw_header_units": list(config.get("raw_header_units", []) or []),
        "header_units": list(config.get("header_units", []) or []),
        "raw_header_processing": list(config.get("raw_header_processing", []) or []),
        "header_processing": list(config.get("header_processing", []) or []),
        "ascii_header_eol": config.get("ascii_header_eol", "auto"),
        "header_bytes": data_offset,
        "first_record": config.get("first_record", 1),
        "last_record": config.get("last_record", 0),
        "record_index_offset": config.get("record_index_offset", 0),
        "record_header_bytes": config.get("record_header_bytes", 0),
        "record_length_bytes": config.get("record_length_bytes", 0),
        "record_footer_bytes": config.get("record_footer_bytes", 0),
        "start_time": config.get("start_time", ""),
        "timestamp_source": record_timestamp.get("source") or config.get("timestamp_source", ""),
        "filename_timestamp": config.get("filename_timestamp", {}),
        "record_timestamp": record_timestamp,
        "source_file": str(source_path),
        "header_detection": header_detection,
        "tob1_eddypro_compatibility": config.get("tob1_eddypro_compatibility", {}),
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
    record_header_bytes: int = 0,
    record_length_bytes: int = 0,
    record_footer_bytes: int = 0,
) -> list[dict[str, str]]:
    fmt_char, size = _struct_format_for_native_type(data_type)
    endian_prefix = _native_endian_prefix(endian)
    record_format = endian_prefix + (fmt_char * len(columns))
    data_size = struct.calcsize(record_format)
    header_size = max(0, int(record_header_bytes))
    footer_size = max(0, int(record_footer_bytes))
    stride = int(record_length_bytes or 0)
    minimum_stride = header_size + data_size
    if stride <= 0:
        stride = minimum_stride + footer_size
    if stride < minimum_stride:
        raise ValueError(
            f"record_length_bytes={stride} is too small for header={header_size} and data={data_size}"
        )
    rows: list[dict[str, str]] = []
    for offset in range(0, len(payload) - minimum_stride + 1, stride):
        data_start = offset + header_size
        data_end = data_start + data_size
        values = struct.unpack(record_format, payload[data_start:data_end])
        if not values:
            continue
        if all((not isinstance(value, float) or math.isfinite(value)) and abs(float(value)) < 1e-15 for value in values):
            break
        rows.append({column: _native_value_to_text(value) for column, value in zip(columns, values)})
    return rows


def _decode_mixed_records(
    payload: bytes,
    *,
    columns: list[str],
    column_types: list[str],
    endian: str,
    record_header_bytes: int = 0,
    record_length_bytes: int = 0,
    record_footer_bytes: int = 0,
) -> list[dict[str, str]]:
    if len(column_types) != len(columns):
        raise ValueError(f"column_types length {len(column_types)} does not match columns length {len(columns)}")
    endian_prefix = _native_endian_prefix(endian)
    fmt_chars = [_struct_format_for_native_type(data_type)[0] for data_type in column_types]
    record_format = endian_prefix + "".join(fmt_chars)
    data_size = struct.calcsize(record_format)
    header_size = max(0, int(record_header_bytes))
    footer_size = max(0, int(record_footer_bytes))
    stride = int(record_length_bytes or 0)
    minimum_stride = header_size + data_size
    if stride <= 0:
        stride = minimum_stride + footer_size
    if stride < minimum_stride:
        raise ValueError(
            f"record_length_bytes={stride} is too small for header={header_size} and mixed data={data_size}"
        )
    rows: list[dict[str, str]] = []
    for offset in range(0, len(payload) - minimum_stride + 1, stride):
        data_start = offset + header_size
        data_end = data_start + data_size
        values = struct.unpack(record_format, payload[data_start:data_end])
        if not values:
            continue
        if all((not isinstance(value, float) or math.isfinite(value)) and abs(float(value)) < 1e-15 for value in values):
            break
        rows.append({column: _native_value_to_text(value) for column, value in zip(columns, values)})
    return rows


def _decode_fp2_records(
    payload: bytes,
    *,
    columns: list[str],
    endian: str,
    skip_words: int = 0,
    leading_ulong_columns: list[str] | None = None,
    record_header_bytes: int = 0,
    record_length_bytes: int = 0,
    record_footer_bytes: int = 0,
) -> list[dict[str, str]]:
    word_count = max(0, int(skip_words)) + len(columns)
    if word_count <= 0:
        return []
    endian_prefix = _native_endian_prefix(endian)
    record_format = endian_prefix + ("H" * word_count)
    data_size = struct.calcsize(record_format)
    header_size = max(0, int(record_header_bytes))
    footer_size = max(0, int(record_footer_bytes))
    stride = int(record_length_bytes or 0)
    minimum_stride = header_size + data_size
    if stride <= 0:
        stride = minimum_stride + footer_size
    if stride < minimum_stride:
        raise ValueError(
            f"record_length_bytes={stride} is too small for header={header_size} and FP2 data={data_size}"
        )
    rows: list[dict[str, str]] = []
    for offset in range(0, len(payload) - minimum_stride + 1, stride):
        data_start = offset + header_size
        data_end = data_start + data_size
        words = struct.unpack(record_format, payload[data_start:data_end])
        skipped_words = words[: int(skip_words)]
        data_words = words[int(skip_words) :]
        values = [_fp2_word_to_float(word) for word in data_words]
        if all(abs(float(value)) < 1e-15 for value in values):
            break
        leading_values = _tob1_ulong_values_from_fp2_words(skipped_words, endian=endian)
        row = _tob1_leading_ulong_value_row(leading_values, leading_ulong_columns or [])
        row.update({column: _native_value_to_text(value) for column, value in zip(columns, values)})
        rows.append(row)
    return rows


def _decode_tob1_ieee4_records(
    payload: bytes,
    *,
    columns: list[str],
    endian: str,
    leading_ulongs: int = 0,
    leading_ulong_columns: list[str] | None = None,
    column_types: list[str] | None = None,
    record_header_bytes: int = 0,
    record_length_bytes: int = 0,
    record_footer_bytes: int = 0,
) -> list[dict[str, str]]:
    skip_count = max(0, int(leading_ulongs or 0))
    payload_types = list(column_types or [])
    if payload_types and len(payload_types) != len(columns):
        raise ValueError(f"column_types length {len(payload_types)} does not match columns length {len(columns)}")
    if not payload_types and skip_count <= 0:
        return _decode_fixed_records(
            payload,
            columns=columns,
            data_type="float32",
            endian=endian,
            record_header_bytes=record_header_bytes,
            record_length_bytes=record_length_bytes,
            record_footer_bytes=record_footer_bytes,
        )
    if not payload_types:
        payload_types = ["float32"] * len(columns)
    endian_prefix = _native_endian_prefix(endian)
    fmt_chars = [_struct_format_for_native_type(data_type)[0] for data_type in payload_types]
    record_format = endian_prefix + ("I" * skip_count) + "".join(fmt_chars)
    data_size = struct.calcsize(record_format)
    header_size = max(0, int(record_header_bytes))
    footer_size = max(0, int(record_footer_bytes))
    stride = int(record_length_bytes or 0)
    minimum_stride = header_size + data_size
    if stride <= 0:
        stride = minimum_stride + footer_size
    if stride < minimum_stride:
        raise ValueError(
            f"record_length_bytes={stride} is too small for header={header_size} and TOB1 IEEE4 data={data_size}"
        )
    rows: list[dict[str, str]] = []
    for offset in range(0, len(payload) - minimum_stride + 1, stride):
        data_start = offset + header_size
        data_end = data_start + data_size
        values = struct.unpack(record_format, payload[data_start:data_end])
        leading_values = values[:skip_count]
        data_values = values[skip_count:]
        if all((not isinstance(value, float) or math.isfinite(value)) and abs(float(value)) < 1e-15 for value in data_values):
            break
        row = _tob1_leading_ulong_value_row(leading_values, leading_ulong_columns or [])
        row.update({column: _native_value_to_text(value) for column, value in zip(columns, data_values)})
        rows.append(row)
    return rows


def _tob1_leading_ulong_value_row(values: tuple[Any, ...] | list[Any], columns: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    names = _tob1_prefixed_leading_ulong_columns(columns, count=len(values))
    for name, value in zip(names, values):
        output[name] = _native_value_to_text(value)
    return output


def _tob1_prefixed_leading_ulong_columns(columns: list[str], *, count: int) -> list[str]:
    output: list[str] = []
    used: set[str] = set()
    for index in range(max(0, int(count or 0))):
        raw_name = columns[index] if index < len(columns) else f"ULONG_{index + 1}"
        cleaned = _clean_tob1_column_token(raw_name) or f"ULONG_{index + 1}"
        candidate = f"{TOB1_LEADING_ULONG_VALUE_PREFIX}{cleaned}"
        if candidate in used:
            suffix = 2
            base = candidate
            while f"{base}_{suffix}" in used:
                suffix += 1
            candidate = f"{base}_{suffix}"
        used.add(candidate)
        output.append(candidate)
    return output


def _tob1_ulong_values_from_fp2_words(words: tuple[int, ...] | list[int], *, endian: str) -> list[int]:
    values: list[int] = []
    normalized_endian = _normalize_native_endian(endian)
    for index in range(0, len(words) - 1, 2):
        first = int(words[index]) & 0xFFFF
        second = int(words[index + 1]) & 0xFFFF
        if normalized_endian == "big":
            values.append((first << 16) | second)
        else:
            values.append(first | (second << 16))
    return values


def _inspect_slt_eddysoft_header(payload: bytes, *, columns: list[str], header_bytes: int) -> dict[str, Any]:
    analog_columns = list(columns[4:]) if len(columns) > 4 else []
    expected_header_bytes = 8 + len(analog_columns) * 2
    actual_header_bytes = max(0, int(header_bytes or expected_header_bytes))
    header = payload[:actual_header_bytes]
    mask_bytes: list[int] = []
    high_resolution_columns: list[str] = []
    low_resolution_columns: list[str] = []
    for index, column in enumerate(analog_columns):
        mask_index = 8 + index * 2
        mask_byte = int(header[mask_index]) if mask_index < len(header) else 0
        mask_bytes.append(mask_byte)
        if mask_byte != 0 and mask_byte % 2 == 1:
            high_resolution_columns.append(column)
        else:
            low_resolution_columns.append(column)
    return {
        "status": "detected" if len(header) >= expected_header_bytes else "incomplete",
        "source": "slt_eddysoft_header",
        "header_bytes": actual_header_bytes,
        "expected_header_bytes": expected_header_bytes,
        "analog_column_count": len(analog_columns),
        "analog_columns": analog_columns,
        "mask_bytes": mask_bytes,
        "high_resolution_columns": high_resolution_columns,
        "low_resolution_columns": low_resolution_columns,
        "eddypro_engine_rule": "src/src_common/import_slt_eddysoft.f90: odd analog mask byte means high resolution; decoded value=(int16+25000)/10.",
        "limitations": [
            "EddySoft SLT header mask support follows EddyPro's high-resolution analog rule; broader real-world SLT dialect fixtures are still required.",
        ],
    }


def _apply_slt_eddysoft_high_resolution(
    rows: list[dict[str, str]],
    *,
    header_detection: dict[str, Any],
) -> list[dict[str, str]]:
    high_resolution = set(str(column) for column in header_detection.get("high_resolution_columns", []) or [])
    if not high_resolution:
        return rows
    output: list[dict[str, str]] = []
    for row in rows:
        updated = dict(row)
        for column in high_resolution:
            number = _optional_float(updated.get(column))
            if number is not None:
                updated[column] = _native_value_to_text((number + 25000.0) / 10.0)
        output.append(updated)
    return output


def _fp2_word_to_float(word: int) -> float:
    code = int(word) & 0xFFFF
    low_byte = code & 0xFF
    high_byte = (code >> 8) & 0xFF
    sign = -1.0 if low_byte & 0x80 else 1.0
    decimal_places = (low_byte >> 5) & 0x03
    mantissa = ((low_byte & 0x1F) << 8) + high_byte
    return sign * float(mantissa) / (10.0 ** decimal_places)


def _struct_format_for_native_type(data_type: str) -> tuple[str, int]:
    normalized = data_type.strip().lower()
    mapping = {
        "float32": ("f", 4),
        "ieee4": ("f", 4),
        "single": ("f", 4),
        "real4": ("f", 4),
        "float": ("f", 4),
        "float64": ("d", 8),
        "double": ("d", 8),
        "real8": ("d", 8),
        "int8": ("b", 1),
        "integer1": ("b", 1),
        "byte": ("b", 1),
        "uint8": ("B", 1),
        "ubyte": ("B", 1),
        "int16": ("h", 2),
        "integer2": ("h", 2),
        "short": ("h", 2),
        "uint16": ("H", 2),
        "ushort": ("H", 2),
        "int32": ("i", 4),
        "integer4": ("i", 4),
        "long": ("i", 4),
        "uint32": ("I", 4),
        "ulong": ("I", 4),
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported native data_type: {data_type}")
    return mapping[normalized]


def _normalize_native_endian(value: Any) -> str:
    normalized = str(value or "little").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"big", "big_endian", "be", ">", "network"}:
        return "big"
    if normalized in {"little", "little_endian", "le", "<", "intel", ""}:
        return "little"
    raise ValueError(f"Unsupported native endian/byte_order: {value}")


def _native_endian_prefix(endian: str) -> str:
    return ">" if _normalize_native_endian(endian) == "big" else "<"


def _normalize_column_types(value: Any, *, columns: list[str], default_type: str) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",") if item.strip()]
        if len(items) != len(columns):
            raise ValueError(f"column_types length {len(items)} does not match columns length {len(columns)}")
        return items
    if isinstance(value, (list, tuple)):
        items = [str(item).strip().lower() for item in value if str(item).strip()]
        if len(items) != len(columns):
            raise ValueError(f"column_types length {len(items)} does not match columns length {len(columns)}")
        return items
    if isinstance(value, dict):
        lookup = {str(key).lower(): str(item).strip().lower() for key, item in value.items() if str(item).strip()}
        return [lookup.get(column.lower(), str(default_type).strip().lower()) for column in columns]
    raise ValueError("column_types must be a comma-separated string, list, or mapping by column name.")


def _normalize_header_eol(value: Any) -> str:
    normalized = str(value or "auto").strip().lower().replace("_", "-")
    mapping = {
        "": "auto",
        "auto": "auto",
        "windows": "crlf",
        "dos": "crlf",
        "cr/lf": "crlf",
        "crlf": "crlf",
        "cr-lf": "crlf",
        "\\r\\n": "crlf",
        "unix": "lf",
        "lf": "lf",
        "\\n": "lf",
        "mac": "cr",
        "classic-mac": "cr",
        "cr": "cr",
        "\\r": "cr",
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported ASCII header EOL mode: {value}")
    return mapping[normalized]


def _detect_tob1_native_format(path: Path) -> str:
    head = str(_inspect_tob1_header(path).get("text", "")).lower()
    if '"fp2"' in head or ",fp2" in head or " fp2" in head:
        return "fp2"
    if '"ieee4"' in head or ",ieee4" in head or " ieee4" in head:
        return "ieee4"
    return ""


def _inspect_tob1_header(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()[:8192]
    except OSError:
        return {}
    lines = _native_text_header_lines(payload, max_lines=16)
    text = "\n".join(lines)
    columns = _tob1_columns_from_header_lines(lines)
    header_metadata = _tob1_header_metadata_from_header_lines(
        lines,
        raw_columns=list(columns.get("raw_columns", []) or []),
        column_line_index=int(columns.get("column_line_index", -1)),
    )
    data_types = _tob1_data_types_from_header_lines(lines)
    normalized_text = text.lower()
    tob1_format = ""
    if '"fp2"' in normalized_text or ",fp2" in normalized_text or " fp2" in normalized_text:
        tob1_format = "fp2"
    elif '"ieee4"' in normalized_text or ",ieee4" in normalized_text or " ieee4" in normalized_text:
        tob1_format = "ieee4"
    compatibility = _tob1_eddypro_compatibility(data_types=data_types, tob1_format=tob1_format)
    return {
        "status": "detected" if lines else "not_detected",
        "header_rows": len(lines),
        "tob1_format": tob1_format,
        "raw_columns": columns.get("raw_columns", []),
        "columns": columns.get("columns", []),
        "column_line": columns.get("column_line", ""),
        "column_line_index": columns.get("column_line_index", -1),
        "raw_units": header_metadata.get("raw_units", []),
        "units": header_metadata.get("units", []),
        "unit_line": header_metadata.get("unit_line", ""),
        "raw_processing": header_metadata.get("raw_processing", []),
        "processing": header_metadata.get("processing", []),
        "processing_line": header_metadata.get("processing_line", ""),
        "data_types": data_types,
        "eddypro_compatibility": compatibility,
        "text": text,
        "source": "tob1_file_header",
        "limitations": [
            "TOB1 header auto-detection infers hot numeric columns from the most field-like header row; leading TIMESTAMP/RECORD-style ULONG fields are tracked separately for native binary alignment.",
        ],
    }


def _tob1_payload_column_types(*, raw_columns: list[str], data_types: list[str], columns: list[str]) -> list[str]:
    if not columns:
        return []
    normalized_types = [str(item or "").strip().upper() for item in data_types]
    if raw_columns and len(raw_columns) == len(normalized_types):
        payload_types: list[str] = []
        for raw_column, data_type in zip(raw_columns, normalized_types):
            if _is_tob1_non_numeric_column(raw_column):
                continue
            payload_type = _tob1_payload_type_from_header_token(data_type)
            if not payload_type:
                return []
            payload_types.append(payload_type)
        return payload_types if len(payload_types) == len(columns) else []

    leading_ulongs = 0
    for data_type in normalized_types:
        if data_type == "ULONG":
            leading_ulongs += 1
        else:
            break
    trailing_types = normalized_types[leading_ulongs:]
    if len(trailing_types) != len(columns):
        return []
    payload_types = [_tob1_payload_type_from_header_token(data_type) for data_type in trailing_types]
    if any(not item for item in payload_types):
        return []
    return [str(item) for item in payload_types]


def _tob1_payload_type_from_header_token(data_type: str) -> str:
    normalized = str(data_type or "").strip().upper()
    if normalized == "IEEE4":
        return "float32"
    if normalized == "ULONG":
        return "uint32"
    return ""


def _tob1_data_types_from_header_lines(lines: list[str]) -> list[str]:
    best: list[str] = []
    for line in lines:
        tokens = [_clean_tob1_column_token(token).upper() for token in _split_tob1_header_tokens(line)]
        if "TOB1" in tokens:
            continue
        data_types = [token for token in tokens if token in TOB1_DATA_TYPE_TOKENS]
        if len(data_types) > len(best):
            best = data_types
    return best


def _tob1_eddypro_compatibility(*, data_types: list[str], tob1_format: str) -> dict[str, Any]:
    types = [str(item or "").upper() for item in data_types if str(item or "").strip()]
    if not types:
        status = "assumed_compatible" if tob1_format in {"fp2", "ieee4"} else "unknown"
        return {
            "status": status,
            "compatible": status == "assumed_compatible",
            "data_types": [],
            "leading_ulong_count": 0,
            "rule": "EddyPro TOB1 support is limited to ULONG/IEEE4 records or leading-ULONG plus FP2 records.",
            "note": "No explicit TOB1 data-type header row was detected; compatibility is inferred from the declared TOB1 format when available.",
        }
    leading_ulongs = 0
    for item in types:
        if item == "ULONG":
            leading_ulongs += 1
        else:
            break
    uses_ieee4 = "IEEE4" in types
    uses_fp2 = "FP2" in types
    ieee4_ok = uses_ieee4 and not uses_fp2 and all(item in {"ULONG", "IEEE4"} for item in types)
    fp2_ok = uses_fp2 and not uses_ieee4 and all(item in {"ULONG", "FP2"} for item in types) and all(
        item != "ULONG" for item in types[leading_ulongs:]
    )
    compatible = bool(ieee4_ok or fp2_ok)
    reasons: list[str] = []
    if uses_ieee4 and uses_fp2:
        reasons.append("mixed IEEE4 and FP2 payload columns are outside EddyPro TOB1 import constraints")
    if uses_fp2 and any(item == "ULONG" for item in types[leading_ulongs:]):
        reasons.append("FP2 TOB1 records require all ULONG fields to appear before FP2 fields")
    unsupported = sorted({item for item in types if item not in TOB1_DATA_TYPE_TOKENS})
    if unsupported:
        reasons.append(f"unsupported TOB1 data types: {', '.join(unsupported)}")
    if not compatible and not reasons:
        reasons.append("TOB1 data-type pattern does not match EddyPro-supported ULONG/IEEE4 or leading-ULONG/FP2 layouts")
    return {
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "data_types": types,
        "leading_ulong_count": leading_ulongs,
        "rule": "EddyPro TOB1 support is limited to ULONG/IEEE4 records or leading-ULONG plus FP2 records.",
        "reasons": reasons,
    }


def _tob1_leading_ulong_columns(*, raw_columns: list[str], data_types: list[str], leading_count: int) -> list[str]:
    count = max(0, int(leading_count or 0))
    if count <= 0:
        return []
    columns = [_clean_tob1_column_token(column) for column in raw_columns[:count] if _clean_tob1_column_token(column)]
    if len(columns) >= count:
        return columns[:count]
    fallback: list[str] = []
    for index, data_type in enumerate(data_types[:count], start=1):
        if str(data_type).upper() == "ULONG":
            fallback.append(f"ULONG_{index}")
    while len(fallback) < count:
        fallback.append(f"ULONG_{len(fallback) + 1}")
    return fallback[:count]


def _resolve_tob1_explicit_columns(explicit_columns: list[str], header_columns: list[str]) -> list[str]:
    if not explicit_columns or not header_columns:
        return []
    lookup = {_tob1_column_lookup_key(column): column for column in header_columns}
    resolved: list[str] = []
    for column in explicit_columns:
        key = _tob1_column_lookup_key(column)
        if key not in lookup:
            return []
        resolved.append(lookup[key])
    return resolved


def _tob1_column_lookup_key(column: Any) -> str:
    return _clean_tob1_column_token(column).lower().replace(" ", "_").replace("-", "_")


def _tob1_header_metadata_from_header_lines(
    lines: list[str],
    *,
    raw_columns: list[str],
    column_line_index: int,
) -> dict[str, Any]:
    if not raw_columns or column_line_index < 0:
        return {"raw_units": [], "units": [], "unit_line": "", "raw_processing": [], "processing": [], "processing_line": ""}
    metadata_rows: list[tuple[str, list[str]]] = []
    for line in lines[column_line_index + 1 :]:
        tokens = _split_tob1_header_tokens(line)
        if len(tokens) != len(raw_columns):
            continue
        if _tob1_header_tokens_match_columns(tokens, raw_columns):
            continue
        if _tob1_header_tokens_are_data_types(tokens):
            continue
        metadata_rows.append((line, tokens))
        if len(metadata_rows) >= 2:
            break
    units_line, raw_units = metadata_rows[0] if metadata_rows else ("", [])
    processing_line, raw_processing = metadata_rows[1] if len(metadata_rows) > 1 else ("", [])
    return {
        "raw_units": raw_units,
        "units": _tob1_payload_header_values(raw_columns, raw_units),
        "unit_line": units_line,
        "raw_processing": raw_processing,
        "processing": _tob1_payload_header_values(raw_columns, raw_processing),
        "processing_line": processing_line,
    }


def _tob1_header_tokens_match_columns(tokens: list[str], raw_columns: list[str]) -> bool:
    return [_tob1_column_lookup_key(token) for token in tokens] == [_tob1_column_lookup_key(column) for column in raw_columns]


def _tob1_header_tokens_are_data_types(tokens: list[str]) -> bool:
    normalized = [_clean_tob1_column_token(token).upper() for token in tokens if _clean_tob1_column_token(token)]
    return bool(normalized) and all(token in TOB1_DATA_TYPE_TOKENS for token in normalized)


def _tob1_payload_header_values(raw_columns: list[str], values: list[str]) -> list[str]:
    if len(raw_columns) != len(values):
        return []
    return [
        _clean_tob1_column_token(value)
        for column, value in zip(raw_columns, values)
        if not _is_tob1_non_numeric_column(column)
    ]


def _native_text_header_lines(payload: bytes, *, max_lines: int = 16) -> list[str]:
    lines: list[str] = []
    index = 0
    while index < len(payload) and len(lines) < max_lines:
        line_end, next_index = _next_native_line(payload, index)
        if line_end < 0:
            break
        raw_line = payload[index:line_end]
        index = next_index
        if not raw_line:
            continue
        if not _looks_like_text_header_line(raw_line):
            break
        line = raw_line.decode("latin1", errors="ignore").strip()
        if not line:
            continue
        lines.append(line)
    return lines


def _next_native_line(payload: bytes, start: int) -> tuple[int, int]:
    cursor = start
    while cursor < len(payload):
        byte = payload[cursor]
        if byte == 13:
            if cursor + 1 < len(payload) and payload[cursor + 1] == 10:
                return cursor, cursor + 2
            return cursor, cursor + 1
        if byte == 10:
            return cursor, cursor + 1
        cursor += 1
    return -1, len(payload)


def _looks_like_text_header_line(raw_line: bytes) -> bool:
    if b"\x00" in raw_line:
        return False
    if not raw_line:
        return False
    printable = 0
    for byte in raw_line:
        if byte in {9, 32} or 33 <= byte <= 126:
            printable += 1
    ratio = printable / max(len(raw_line), 1)
    if ratio < 0.85:
        return False
    text = raw_line.decode("latin1", errors="ignore")
    return any(char.isalnum() for char in text)


def _tob1_columns_from_header_lines(lines: list[str]) -> dict[str, Any]:
    best_line = ""
    best_tokens: list[str] = []
    best_score = 0
    best_index = -1
    for index, line in enumerate(lines):
        tokens = _split_tob1_header_tokens(line)
        if len(tokens) < 2:
            continue
        score = sum(_tob1_column_token_score(token) for token in tokens)
        if score > best_score:
            best_line = line
            best_tokens = tokens
            best_score = score
            best_index = index
    if best_score < 2:
        return {"raw_columns": [], "columns": [], "column_line": "", "column_line_index": -1}
    columns = [_clean_tob1_column_token(token) for token in best_tokens if not _is_tob1_non_numeric_column(token)]
    return {
        "raw_columns": [_clean_tob1_column_token(token) for token in best_tokens],
        "columns": [column for column in columns if column],
        "column_line": best_line,
        "column_line_index": best_index,
    }


def _split_tob1_header_tokens(line: str) -> list[str]:
    delimiter = "\t" if "\t" in line and line.count("\t") >= line.count(",") else ","
    return [_clean_tob1_column_token(token) for token in line.split(delimiter)]


def _clean_tob1_column_token(token: Any) -> str:
    return str(token or "").strip().strip('"').strip("'").strip()


def _is_tob1_non_numeric_column(token: Any) -> bool:
    normalized = _clean_tob1_column_token(token).lower().replace(" ", "").replace("-", "_")
    return normalized in {
        "timestamp",
        "ts",
        "datetime",
        "date_time",
        "time",
        "seconds",
        "second",
        "sec",
        "secs",
        "nanoseconds",
        "nanosecond",
        "nanosecs",
        "nanosec",
        "nsec",
        "ns",
        "record",
        "recordnumber",
        "rec",
        "rn",
    }


def _tob1_column_token_score(token: Any) -> int:
    cleaned = _clean_tob1_column_token(token)
    normalized = cleaned.lower().replace(" ", "_").replace("-", "_")
    if _is_tob1_non_numeric_column(cleaned):
        return 1
    aliases = {alias.lower() for group in DEFAULT_COLUMN_ALIASES.values() for alias in group}
    if normalized in aliases:
        return 2
    if any(marker in normalized for marker in ("co2", "h2o", "ch4")):
        return 2
    if normalized in {"u", "v", "w", "p", "ta", "ts", "tc"}:
        return 2
    return 0


def _offset_after_text_lines(payload: bytes, line_count: int, *, eol: str = "auto") -> int:
    if line_count <= 0:
        return 0
    count = 0
    index = 0
    mode = _normalize_header_eol(eol)
    while index < len(payload):
        byte = payload[index]
        if mode == "crlf":
            index += 1
            if byte == 13 and index < len(payload) and payload[index] == 10:
                index += 1
                count += 1
        elif mode == "lf":
            index += 1
            if byte == 10:
                count += 1
        elif mode == "cr":
            index += 1
            if byte == 13:
                count += 1
        elif byte == 13 and index + 1 < len(payload) and payload[index + 1] == 10:
            index += 2
            count += 1
        else:
            index += 1
            if byte in {10, 13}:
                count += 1
        if count >= line_count:
            return index
    return index


def _slice_native_rows(rows: list[dict[str, str]], *, first_record: int, last_record: int) -> list[dict[str, str]]:
    start = max(0, int(first_record) - 1)
    end = int(last_record) if int(last_record or 0) > 0 else None
    if start == 0 and end is None:
        return rows
    return rows[start:end]


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
        raise ValueError(
            "Native raw import requires TOB1 SECONDS/NANOSECONDS record timestamps, extra.start_time, "
            "or an inferable filename timestamp when records do not store timestamps."
        )
    start = datetime.fromisoformat(start_time)
    step = config.get("timestamp_step_seconds")
    step_s = float(step) if step not in (None, "") else 1.0 / max(float(sample_hz), 1.0)
    return (start + timedelta(seconds=float(index * step_s))).isoformat()


def _apply_native_record_timestamps(rows: list[dict[str, str]], config: dict[str, Any]) -> dict[str, Any]:
    native_format = str(config.get("format", ""))
    if not native_format.startswith("tob1"):
        return {
            "artifact_type": "native_record_timestamp_summary_v1",
            "status": "not_applicable",
            "source": "",
            "applied_count": 0,
            "record_count": len(rows),
        }
    applied_count = 0
    first_timestamp = ""
    seconds_column = ""
    nanoseconds_column = ""
    for row in rows:
        candidate = _tob1_record_timestamp_candidate(row)
        if not candidate:
            continue
        row["timestamp"] = str(candidate["timestamp"])
        applied_count += 1
        first_timestamp = first_timestamp or str(candidate["timestamp"])
        seconds_column = seconds_column or str(candidate.get("seconds_column", ""))
        nanoseconds_column = nanoseconds_column or str(candidate.get("nanoseconds_column", ""))
    return {
        "artifact_type": "native_record_timestamp_summary_v1",
        "status": "applied" if applied_count else "not_detected",
        "source": "tob1_record_seconds_nanoseconds" if applied_count else "",
        "epoch": TOB1_CAMPBELL_TIMESTAMP_EPOCH.isoformat(),
        "seconds_column": seconds_column,
        "nanoseconds_column": nanoseconds_column,
        "applied_count": applied_count,
        "record_count": len(rows),
        "first_timestamp": first_timestamp,
        "precision_note": "TOB1 nanosecond values are represented at Python datetime microsecond precision.",
        "limitations": [
            "Only explicit Campbell/LoggerNet SECONDS plus optional NANOSECONDS fields are interpreted as TOB1 record timestamps.",
            "Ambiguous TIMESTAMP-style leading ULONG fields are preserved but not converted without an explicit SECONDS field.",
        ],
    }


def _tob1_record_timestamp_candidate(row: dict[str, str]) -> dict[str, str] | None:
    keyed: dict[str, tuple[str, str]] = {}
    for column, value in row.items():
        normalized = _tob1_record_timestamp_key(column)
        if normalized and normalized not in keyed:
            keyed[normalized] = (str(column), str(value))
    seconds_item = _first_tob1_record_timestamp_item(keyed, TOB1_RECORD_SECONDS_ALIASES)
    if seconds_item is None:
        return None
    nanoseconds_item = _first_tob1_record_timestamp_item(keyed, TOB1_RECORD_NANOSECONDS_ALIASES)
    seconds = _optional_float(seconds_item[1])
    nanoseconds = _optional_float(nanoseconds_item[1]) if nanoseconds_item is not None else 0.0
    if seconds is None or nanoseconds is None or seconds < 0 or nanoseconds < 0 or nanoseconds >= 1_000_000_000:
        return None
    timestamp = TOB1_CAMPBELL_TIMESTAMP_EPOCH + timedelta(seconds=float(seconds) + float(nanoseconds) / 1_000_000_000.0)
    return {
        "timestamp": timestamp.isoformat(),
        "seconds_column": seconds_item[0],
        "nanoseconds_column": nanoseconds_item[0] if nanoseconds_item is not None else "",
    }


def _first_tob1_record_timestamp_item(
    keyed: dict[str, tuple[str, str]],
    aliases: set[str],
) -> tuple[str, str] | None:
    for alias in aliases:
        item = keyed.get(alias)
        if item is not None:
            return item
    return None


def _tob1_record_timestamp_key(column: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(column or "").strip().lower()).strip("_")
    prefix = TOB1_LEADING_ULONG_VALUE_PREFIX.rstrip("_").lower()
    if normalized.startswith(f"{prefix}_"):
        normalized = normalized[len(prefix) + 1 :]
    return normalized


def _native_timestamp_resolution(*, source_path: Path, extra: dict[str, Any]) -> dict[str, Any]:
    explicit_start = str(extra.get("start_time", "") or "").strip()
    if explicit_start:
        return {
            "status": "configured",
            "source": "extra.start_time",
            "start_time": explicit_start,
            "filename": source_path.name,
            "limitations": [],
        }
    template = str(
        extra.get("filename_timestamp_template", extra.get("raw_filename_template", extra.get("file_name_format", "")))
        or ""
    ).strip()
    doy_format = _truthy_value(extra.get("filename_timestamp_doy", extra.get("doy_format", False)))
    if template:
        parsed = _timestamp_from_filename_template(source_path.name, template=template, doy_format=doy_format)
        if parsed:
            return {
                "status": "inferred",
                "source": "filename_template",
                "start_time": parsed.isoformat(),
                "filename": source_path.name,
                "template": template,
                "doy_format": doy_format,
                "source_reference": {
                    "eddypro_engine_files": [
                        "src/src_common/date_subs.f90",
                        "src/src_common/parse_file_name_with_prototype.f90",
                    ],
                },
                "limitations": ["Template support covers EddyPro yyyy/yy/mm/dd/ddd/HH/MM tokens."],
            }
        return {
            "status": "not_inferred",
            "source": "filename_template",
            "start_time": "",
            "filename": source_path.name,
            "template": template,
            "doy_format": doy_format,
            "limitations": ["Configured filename timestamp template did not match this file name."],
        }
    parsed = _timestamp_from_common_filename(source_path.name)
    if parsed:
        return {
            "status": "inferred",
            "source": "filename_auto",
            "start_time": parsed.isoformat(),
            "filename": source_path.name,
            "template": "",
            "doy_format": False,
            "source_reference": {
                "eddypro_engine_files": [
                    "src/src_common/date_subs.f90",
                    "src/src_common/parse_file_name_with_prototype.f90",
                ],
            },
            "limitations": ["Auto inference recognizes common YYYYMMDD-HHMM and YYYYDDD-HHMM filename patterns."],
        }
    return {
        "status": "not_inferred",
        "source": "",
        "start_time": "",
        "filename": source_path.name,
        "limitations": ["No extra.start_time or recognizable filename timestamp was available."],
    }


def _timestamp_from_filename_template(filename: str, *, template: str, doy_format: bool) -> datetime | None:
    try:
        year = _template_token_value(filename, template, "yyyy")
        if year is None:
            year2 = _template_token_value(filename, template, "yy")
            if year2 is None:
                return None
            year_number = int(year2)
            year = str(1900 + year_number if year_number > 70 else 2000 + year_number)
        month = _template_token_value(filename, template, "mm")
        day = _template_token_value(filename, template, "dd")
        doy = _template_token_value(filename, template, "ddd")
        hour = _template_token_value(filename, template, "HH")
        minute = _template_token_value(filename, template, "MM")
        if hour is None or minute is None:
            return None
        if doy_format or doy is not None:
            if doy is None:
                return None
            base = datetime(int(year), 1, 1) + timedelta(days=int(doy) - 1)
            return _normalize_filename_time(base.year, base.month, base.day, int(hour), int(minute), 0)
        if month is None or day is None:
            return None
        return _normalize_filename_time(int(year), int(month), int(day), int(hour), int(minute), 0)
    except (TypeError, ValueError):
        return None


def _template_token_value(filename: str, template: str, token: str) -> str | None:
    start = template.find(token)
    if start < 0:
        return None
    end = start + len(token)
    if len(filename) < end:
        return None
    value = filename[start:end]
    return value if value.isdigit() else None


def _timestamp_from_common_filename(filename: str) -> datetime | None:
    stem = Path(filename).stem
    patterns = [
        re.compile(
            r"(?P<year>19\d{2}|20\d{2})[-_]?((?P<month>\d{2})[-_]?(?P<day>\d{2})|(?P<doy>\d{3}))"
            r"(?:[Tt_\-\s]?)(?P<hour>\d{2})(?:[:_\-]?(?P<minute>\d{2}))(?::?(?P<second>\d{2}))?"
        ),
        re.compile(
            r"(?P<year>\d{2})[-_](?P<month>\d{2})[-_](?P<day>\d{2})[Tt_\-\s]?"
            r"(?P<hour>\d{2})(?:[:_\-]?(?P<minute>\d{2}))(?::?(?P<second>\d{2}))?"
        ),
    ]
    for pattern in patterns:
        match = pattern.search(stem)
        if not match:
            continue
        groups = match.groupdict()
        year = int(groups["year"])
        if year < 100:
            year = 1900 + year if year > 70 else 2000 + year
        doy = groups.get("doy")
        if doy:
            base = datetime(year, 1, 1) + timedelta(days=int(doy) - 1)
            month = base.month
            day = base.day
        else:
            month = int(groups["month"])
            day = int(groups["day"])
        try:
            return _normalize_filename_time(
                year,
                month,
                day,
                int(groups["hour"]),
                int(groups["minute"]),
                int(groups.get("second") or 0),
            )
        except ValueError:
            continue
    return None


def _normalize_filename_time(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime:
    if hour == 24 and minute == 0 and second == 0:
        return datetime(year, month, day) + timedelta(days=1)
    return datetime(year, month, day, hour, minute, second)


def _truthy_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


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
    if native_format == "tob1_fp2":
        return ["src/src_common/import_tob1.f90", "src/src_common/m_fp2_to_float.f90"]
    if native_format.startswith("tob1"):
        return ["src/src_common/import_tob1.f90"]
    if native_format.startswith("slt_eddysoft"):
        return ["src/src_common/import_slt_eddysoft.f90"]
    if native_format.startswith("slt"):
        return ["src/src_common/import_slt_edisol.f90"]
    return ["src/src_common/import_binary.f90", "src/src_common/write_processing_project_variables.f90"]


def _native_import_limitations(native_format: str) -> list[str]:
    limitations = [
        "Native reader bridge decodes fixed-record numeric payloads into NormalizedHFFrame and does not yet implement every EddyPro file interpreter branch.",
        "Timestamp generation uses explicit TOB1 SECONDS/NANOSECONDS record timestamps when present, otherwise metadata start_time or common EddyPro-style filename timestamp inference.",
    ]
    if native_format == "tob1_ieee4":
        limitations.append("TOB1 IEEE4 float payloads are supported, including leading TIMESTAMP/RECORD-style ULONG fields declared by the TOB1 header.")
        limitations.append("Leading TOB1 ULONG fields are preserved for audit and binary layout alignment; generated record timestamps use the resolved run start plus sample_hz.")
    if native_format == "tob1_fp2":
        limitations.append("TOB1 FP2 decoding follows EddyPro's m_fp2_to_float table semantics through an equivalent formula; broad real-world TOB1 fixture parity is still needed.")
    if native_format.startswith("slt"):
        limitations.append("SLT support covers fixed int16 EdiSol/EddySoft-style fixtures; full vendor dialect parity still needs real datasets.")
    if native_format in {"binary", "native_binary", "binary_int16", "binary_float32"}:
        limitations.append("Generic binary support handles fixed-length records with optional CRLF/LF/CR ASCII headers, per-record prefixes, stride, footer padding, one-based record selection, and configured per-column numeric types; broad real fixture validation is still needed.")
    return limitations


def _frame_from_raw_row(
    row: dict[str, str],
    *,
    mappings: dict[str, RawColumnMapping],
    source_path: Path,
    device_uid: str,
    device_id: str,
    mode: int,
    retain_decoded_columns: bool = False,
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
    raw_payload.update(_li7700_diagnostic_payload(lookup, mappings))
    if retain_decoded_columns:
        raw_payload["raw_native_columns"] = _decoded_raw_columns(row)
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


def _decoded_raw_columns(row: dict[str, str]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for column, value in row.items():
        if _is_tob1_non_numeric_column(column) or str(column).strip().lower() == "timestamp":
            continue
        decoded[str(column)] = _decoded_raw_column_value(value)
    return decoded


def _decoded_raw_column_value(value: Any) -> Any:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    try:
        if text and all(char not in text.lower() for char in (".", "e")):
            return int(text, 0)
    except ValueError:
        pass
    number = _optional_float(text)
    if number is None:
        return text
    return number


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
    aliases.update({alias: variable for variable, variable_aliases in LI7700_DIAGNOSTIC_ALIASES.items() for alias in variable_aliases})
    for mapping in mappings:
        if mapping.ignore:
            continue
        variable = mapping.variable.strip() or mapping.column_name.strip()
        variable = aliases.get(variable.lower(), variable)
        by_variable[variable] = mapping
    return by_variable


def _li7700_diagnostic_payload(lookup: dict[str, str], mappings: dict[str, RawColumnMapping]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for variable, aliases in LI7700_DIAGNOSTIC_ALIASES.items():
        value = _diagnostic_value(lookup, mappings, variable, aliases)
        if value in (None, ""):
            continue
        payload[variable] = value
    return payload


def _diagnostic_value(
    lookup: dict[str, str],
    mappings: dict[str, RawColumnMapping],
    variable: str,
    aliases: tuple[str, ...],
) -> Any:
    mapping = mappings.get(variable)
    raw = _mapped_value(lookup, mappings, variable) if mapping is not None else _first_lookup(lookup, aliases)
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if variable in {"diagnostic_status", "mirror_dirty", "pll_locked"}:
        return text
    if variable == "li7700_status_word":
        try:
            return int(text, 0)
        except ValueError:
            number = _optional_float(text)
            return int(number) if number is not None and math.isfinite(number) else text
    number = _optional_float(text)
    if number is None:
        return text
    if mapping is not None and mapping.scaling is not None:
        number *= float(mapping.scaling)
    if variable in {"li7700_rssi", "signal_strength", "mirror_rssi"} and 0.0 <= abs(number) <= 1.0:
        number *= 100.0
    return number


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
