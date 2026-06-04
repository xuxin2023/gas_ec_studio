from __future__ import annotations

import csv
import json
import zipfile
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from models.hf_models import FrameQuality, NormalizedHFFrame


GAS_COLUMN_ALIASES = {
    "co2_ppm": ("co2_ppm", "co2", "co2_molar_density", "co2_molfrac", "co2_mixing_ratio", "co2 (umol/mol)"),
    "h2o_mmol": ("h2o_mmol", "h2o", "h2o_molar_density", "h2o_molfrac", "h2o_mixing_ratio", "h2o (mmol/mol)"),
    "ch4_ppb": ("ch4_ppb", "ch4_ppm", "ch4", "methane", "ch4_molfrac", "ch4_mixing_ratio", "ch4 (umol/mol)"),
    "n2o_ppb": ("n2o_ppb", "n2o_ppm", "n2o", "nitrous_oxide", "n2o_molfrac", "n2o_mixing_ratio", "n2o (umol/mol)"),
    "pressure_kpa": ("pressure_kpa", "pressure", "press", "p", "ambient_pressure", "pressure (kpa)", "ch4 pressure"),
    "chamber_temp_c": (
        "chamber_temp_c",
        "air_temperature",
        "temperature",
        "temp",
        "ta",
        "sonic_temperature",
        "temperature (c)",
        "t (c)",
        "ch4 temperature",
    ),
    "case_temp_c": ("case_temp_c", "cell_temperature", "analyzer_temperature", "box_temperature"),
}

WIND_COLUMN_ALIASES = {
    "u": ("u", "u_ms", "u_mps", "wind_u", "u_unrot", "u (m/s)", "aux 1 - u (m/s)"),
    "v": ("v", "v_ms", "v_mps", "wind_v", "v_unrot", "v (m/s)", "aux 2 - v (m/s)"),
    "w": ("w", "w_ms", "w_mps", "wind_w", "vertical_velocity", "vertical_wind", "w_unrot", "w (m/s)", "aux 3 - w (m/s)"),
}

TIME_COLUMN_ALIASES = ("timestamp", "time", "datetime", "date_time", "ts")

LI7700_DIAGNOSTIC_ALIASES = {
    "li7700_rssi": (
        "li7700_rssi",
        "li_7700_rssi",
        "rssi",
        "rssi_77",
        "rssi77",
        "rss",
        "rss_77",
        "rss77",
        "ch4 signal strength",
        "ch4_signal_strength",
        "received_signal_strength",
    ),
    "li7700_signal_strength": (
        "li7700_signal_strength",
        "li_7700_signal_strength",
        "signal_strength",
        "signal_strength_pct",
        "ch4_signal_strength",
        "ch4 signal strength",
        "optical_signal",
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
        "diag",
        "diag_code",
        "diagcode",
        "diag_77",
        "diag77",
        "ch4 diagnostic value",
        "ch4_diagnostic_value",
    ),
    "li7700_reference_rssi": ("refrssi", "ref_rssi", "reference_rssi", "li7700_reference_rssi"),
    "li7700_chassis_temp_c": ("chassistemp", "chassis_temp", "chassis temperature", "li7700_chassis_temp_c"),
    "li7700_optics_temp_c": ("opticstemp", "optics_temp", "optics temperature", "li7700_optics_temp_c"),
    "li7700_optics_rh_pct": ("opticsrh", "optics_rh", "optics relative humidity", "li7700_optics_rh_pct"),
    "li7700_motor_setpoint": ("motorsetpt", "motor_setpoint", "li7700_motor_setpoint"),
    "li7700_motor_actual": ("motoractual", "motor_actual", "li7700_motor_actual"),
}

LI7700_STATUS_MATCH_TOLERANCE_S = 0.35


@dataclass(slots=True)
class GHGBundleManifest:
    path: str
    member_names: list[str]
    raw_data_members: list[str]
    raw_metadata_members: list[str]
    status_members: list[str]
    biomet_data_members: list[str]
    biomet_metadata_members: list[str]
    has_embedded_biomet: bool
    has_li7700_status: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "member_names": self.member_names,
            "raw_data_members": self.raw_data_members,
            "raw_metadata_members": self.raw_metadata_members,
            "status_members": self.status_members,
            "biomet_data_members": self.biomet_data_members,
            "biomet_metadata_members": self.biomet_metadata_members,
            "has_embedded_biomet": self.has_embedded_biomet,
            "has_li7700_status": self.has_li7700_status,
            "metadata": self.metadata,
        }


def inspect_ghg_bundle(path: str | Path) -> GHGBundleManifest:
    bundle_path = Path(path)
    if not bundle_path.exists():
        raise FileNotFoundError(bundle_path)
    if not zipfile.is_zipfile(bundle_path):
        raise ValueError(f"Not a readable .ghg/zip bundle: {bundle_path}")

    with zipfile.ZipFile(bundle_path, "r") as archive:
        member_names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        raw_data = [name for name in member_names if _is_raw_data_member(name)]
        raw_metadata = [name for name in member_names if _is_raw_metadata_member(name)]
        status_members = [name for name in member_names if _is_status_member(name)]
        biomet_data = [name for name in member_names if _is_biomet_data_member(name)]
        biomet_metadata = [name for name in member_names if _is_biomet_metadata_member(name)]
        metadata: dict[str, Any] = {}
        for member in raw_metadata + biomet_metadata:
            metadata[member] = _parse_metadata_text(_read_text_member(archive, member))

    return GHGBundleManifest(
        path=str(bundle_path),
        member_names=member_names,
        raw_data_members=raw_data,
        raw_metadata_members=raw_metadata,
        status_members=status_members,
        biomet_data_members=biomet_data,
        biomet_metadata_members=biomet_metadata,
        has_embedded_biomet=bool(biomet_data or biomet_metadata),
        has_li7700_status=any("li7700" in name.lower() or "li-7700" in name.lower() for name in status_members),
        metadata=metadata,
    )


def read_ghg_tabular_member(path: str | Path, member_name: str) -> list[dict[str, str]]:
    bundle_path = Path(path)
    with zipfile.ZipFile(bundle_path, "r") as archive:
        text = _read_text_member(archive, member_name)
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("#", ";"))]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else ","
    licor_rows = _read_licor_datah_rows(lines, delimiter=delimiter)
    if licor_rows:
        return licor_rows
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=delimiter)
    return [dict(row) for row in reader]


def read_ghg_status_records(path: str | Path, member_name: str | None = None) -> list[dict[str, Any]]:
    bundle_path = Path(path)
    manifest = inspect_ghg_bundle(bundle_path)
    members = [member_name] if member_name else list(manifest.status_members)
    records: list[dict[str, Any]] = []
    for member in members:
        if not member:
            continue
        for row in read_ghg_tabular_member(bundle_path, member):
            lookup = _casefold_lookup(row)
            timestamp = _timestamp_from_ghg_row(lookup)
            epoch_ns = _epoch_ns_from_ghg_row(lookup)
            enriched: dict[str, Any] = dict(row)
            enriched["__ghg_status_member__"] = member
            if timestamp is not None:
                enriched["__timestamp__"] = timestamp
            if epoch_ns is not None:
                enriched["__epoch_ns__"] = epoch_ns
            records.append(enriched)
    records.sort(key=lambda item: (item.get("__epoch_ns__") is None, item.get("__epoch_ns__", 0), str(item.get("__timestamp__", ""))))
    return records


def load_ghg_normalized_frames(
    path: str | Path,
    *,
    device_uid: str | None = None,
    device_id: str | None = None,
    mode: int = 2,
) -> list[NormalizedHFFrame]:
    bundle_path = Path(path)
    manifest = inspect_ghg_bundle(bundle_path)
    metadata = _merged_raw_metadata(manifest)
    resolved_device_uid = device_uid or str(metadata.get("device_uid") or metadata.get("site_id") or bundle_path.stem)
    resolved_device_id = device_id or str(metadata.get("device_id") or metadata.get("analyzer_serial") or "ghg")
    status_index = _build_li7700_status_index(bundle_path, manifest)
    frames: list[NormalizedHFFrame] = []
    for member in manifest.raw_data_members:
        for row in read_ghg_tabular_member(bundle_path, member):
            frame = _normalized_frame_from_ghg_row(
                row,
                bundle_path=bundle_path,
                member_name=member,
                device_uid=resolved_device_uid,
                device_id=resolved_device_id,
                mode=mode,
                status_index=status_index,
            )
            if frame is not None:
                frames.append(frame)
    frames.sort(key=lambda item: item.timestamp)
    return frames


def load_ghg_biomet_records(
    path: str | Path,
    *,
    time_column: str = "timestamp",
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    manifest = inspect_ghg_bundle(path)
    selected_fields = set(fields or [])
    records: list[dict[str, Any]] = []
    for member in manifest.biomet_data_members:
        for row in read_ghg_tabular_member(path, member):
            lookup = _casefold_lookup(row)
            timestamp = _timestamp_from_ghg_row(lookup, preferred_key=time_column)
            if timestamp is None:
                continue
            parsed: dict[str, Any] = {"timestamp": timestamp, "__source_file__": f"{path}#{member}"}
            for key, value in row.items():
                if key == time_column:
                    continue
                if selected_fields and key not in selected_fields:
                    continue
                parsed[key] = value
            records.append(parsed)
    records.sort(key=lambda item: item["timestamp"])
    return records


def _normalized_frame_from_ghg_row(
    row: dict[str, str],
    *,
    bundle_path: Path,
    member_name: str,
    device_uid: str,
    device_id: str,
    mode: int,
    status_index: dict[str, Any] | None = None,
) -> NormalizedHFFrame | None:
    lookup = _casefold_lookup(row)
    timestamp = _timestamp_from_ghg_row(lookup)
    if timestamp is None:
        return None
    ch4_ppb = _optional_ch4_ppb(lookup)
    n2o_ppb = _optional_ppb(lookup, "n2o_ppb")
    wind_payload = {
        key: _optional_float(_first_lookup_value(lookup, aliases))
        for key, aliases in WIND_COLUMN_ALIASES.items()
    }
    status_record = _nearest_li7700_status_record(lookup, timestamp, status_index or {})
    diagnostic_payload = _li7700_diagnostic_payload(lookup, status_record)
    raw_payload = {
        key: value
        for key, value in {
            **wind_payload,
            **diagnostic_payload,
            "ch4_ppb": ch4_ppb,
            "n2o_ppb": n2o_ppb,
            "ghg_bundle": str(bundle_path),
            "ghg_member": member_name,
        }.items()
        if value is not None
    }
    return NormalizedHFFrame(
        timestamp=timestamp,
        device_uid=device_uid,
        device_id=device_id,
        mode=int(mode),
        frame_quality=FrameQuality.FULL,
        co2_ppm=_optional_float(_first_lookup_value(lookup, GAS_COLUMN_ALIASES["co2_ppm"])),
        h2o_mmol=_optional_float(_first_lookup_value(lookup, GAS_COLUMN_ALIASES["h2o_mmol"])),
        ch4_ppb=ch4_ppb,
        n2o_ppb=n2o_ppb,
        pressure_kpa=_optional_float(_first_lookup_value(lookup, GAS_COLUMN_ALIASES["pressure_kpa"])),
        chamber_temp_c=_optional_float(_first_lookup_value(lookup, GAS_COLUMN_ALIASES["chamber_temp_c"])),
        case_temp_c=_optional_float(_first_lookup_value(lookup, GAS_COLUMN_ALIASES["case_temp_c"])),
        status_text=f"ghg_bundle={bundle_path.name}; member={member_name}",
        raw_text=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
    )


def _read_text_member(archive: zipfile.ZipFile, member_name: str) -> str:
    raw = archive.read(member_name)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_licor_datah_rows(lines: list[str], *, delimiter: str) -> list[dict[str, str]]:
    parsed = [next(csv.reader([line], delimiter=delimiter)) for line in lines]
    header: list[str] = []
    data_marker = "DATA"
    rows: list[dict[str, str]] = []
    for parts in parsed:
        if not parts:
            continue
        marker = str(parts[0]).strip().upper()
        if marker.startswith("DATA") and marker.endswith("H") and len(marker) > 1:
            header = [str(item).strip() for item in parts[1:]]
            data_marker = marker[:-1] or "DATA"
            continue
        if marker != data_marker or not header:
            continue
        values = [str(item).strip() for item in parts[1:]]
        rows.append({header[index]: values[index] if index < len(values) else "" for index in range(len(header))})
    return rows


def _build_li7700_status_index(bundle_path: Path, manifest: GHGBundleManifest) -> dict[str, Any]:
    records = []
    for record in read_ghg_status_records(bundle_path):
        lookup = _casefold_lookup({key: str(value) for key, value in record.items() if not str(key).startswith("__")})
        records.append(
            {
                "member": str(record.get("__ghg_status_member__", "")),
                "lookup": lookup,
                "epoch_ns": record.get("__epoch_ns__"),
                "timestamp": record.get("__timestamp__"),
            }
        )
    epoch_records = [record for record in records if record.get("epoch_ns") is not None]
    epoch_records.sort(key=lambda item: int(item["epoch_ns"]))
    time_records = [record for record in records if isinstance(record.get("timestamp"), datetime)]
    time_records.sort(key=lambda item: item["timestamp"])
    return {
        "epoch_values": [int(record["epoch_ns"]) for record in epoch_records],
        "epoch_records": epoch_records,
        "time_values": [record["timestamp"] for record in time_records],
        "time_records": time_records,
        "status_member_count": len(manifest.status_members),
    }


def _nearest_li7700_status_record(
    lookup: dict[str, str],
    timestamp: datetime,
    status_index: dict[str, Any],
) -> dict[str, Any] | None:
    epoch_values = status_index.get("epoch_values", []) or []
    epoch_records = status_index.get("epoch_records", []) or []
    epoch_ns = _epoch_ns_from_ghg_row(lookup)
    if epoch_ns is not None and epoch_values:
        position = bisect_left(epoch_values, epoch_ns)
        candidates = []
        if position < len(epoch_records):
            candidates.append(epoch_records[position])
        if position > 0:
            candidates.append(epoch_records[position - 1])
        best = min(candidates, key=lambda item: abs(int(item["epoch_ns"]) - epoch_ns), default=None)
        if best is not None:
            delta_s = abs(int(best["epoch_ns"]) - epoch_ns) / 1_000_000_000.0
            if delta_s <= LI7700_STATUS_MATCH_TOLERANCE_S:
                return {**best, "match_delta_s": delta_s, "match_basis": "epoch_seconds"}

    time_values = status_index.get("time_values", []) or []
    time_records = status_index.get("time_records", []) or []
    if not time_values:
        return None
    position = bisect_left(time_values, timestamp)
    candidates = []
    if position < len(time_records):
        candidates.append(time_records[position])
    if position > 0:
        candidates.append(time_records[position - 1])
    best = min(candidates, key=lambda item: abs((item["timestamp"] - timestamp).total_seconds()), default=None)
    if best is None:
        return None
    delta_s = abs((best["timestamp"] - timestamp).total_seconds())
    if delta_s > LI7700_STATUS_MATCH_TOLERANCE_S:
        return None
    return {**best, "match_delta_s": delta_s, "match_basis": "timestamp"}


def _li7700_diagnostic_payload(
    raw_lookup: dict[str, str],
    status_record: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if status_record:
        status_lookup = dict(status_record.get("lookup", {}) or {})
        payload.update(_li7700_values_from_lookup(status_lookup))
        member = str(status_record.get("member", ""))
        if member:
            payload["li7700_status_source_member"] = member
        if status_record.get("match_delta_s") is not None:
            payload["li7700_status_match_delta_s"] = float(status_record["match_delta_s"])
        if status_record.get("match_basis"):
            payload["li7700_status_match_basis"] = str(status_record["match_basis"])
    payload.update(_li7700_values_from_lookup(raw_lookup))
    return payload


def _li7700_values_from_lookup(lookup: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for output_key, aliases in LI7700_DIAGNOSTIC_ALIASES.items():
        value = _first_lookup_value(lookup, aliases)
        if value in (None, ""):
            continue
        if output_key == "li7700_status_word":
            parsed = _optional_int(value)
            payload[output_key] = parsed if parsed is not None else str(value)
            continue
        parsed_float = _optional_float(value)
        payload[output_key] = parsed_float if parsed_float is not None else str(value)
    return payload


def _epoch_ns_from_ghg_row(lookup: dict[str, str]) -> int | None:
    seconds = _optional_float(lookup.get("seconds"))
    if seconds is None:
        return None
    nanoseconds = _optional_float(lookup.get("nanoseconds"))
    return int(seconds) * 1_000_000_000 + int(nanoseconds or 0.0)


def _parse_metadata_text(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        elif "\t" in line:
            key, value = line.split("\t", 1)
        else:
            continue
        metadata[key.strip()] = value.strip()
    return metadata


def _merged_raw_metadata(manifest: GHGBundleManifest) -> dict[str, str]:
    merged: dict[str, str] = {}
    for member in manifest.raw_metadata_members:
        payload = manifest.metadata.get(member, {})
        if isinstance(payload, dict):
            merged.update({str(key): str(value) for key, value in payload.items()})
    return merged


def _casefold_lookup(row: dict[str, str]) -> dict[str, str]:
    return {str(key).strip().lower(): value for key, value in row.items() if key is not None}


def _first_lookup_value(lookup: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        value = lookup.get(alias.lower())
        if value not in (None, ""):
            return value
    return None


def _timestamp_from_ghg_row(lookup: dict[str, str], *, preferred_key: str = "") -> datetime | None:
    if preferred_key:
        timestamp = _parse_datetime(lookup.get(preferred_key.lower()))
        if timestamp is not None:
            return timestamp
    timestamp = _parse_datetime(_first_lookup_value(lookup, TIME_COLUMN_ALIASES))
    if timestamp is not None and lookup.get("date") is None:
        return timestamp
    date = lookup.get("date")
    time_value = lookup.get("time")
    if date and time_value:
        timestamp = _parse_datetime(f"{date}T{_normalize_licor_time(time_value)}")
        if timestamp is not None:
            return timestamp
    seconds = _optional_float(lookup.get("seconds"))
    nanoseconds = _optional_float(lookup.get("nanoseconds"))
    if seconds is not None:
        try:
            base = datetime.fromtimestamp(seconds)
            if nanoseconds is not None:
                return base.replace(microsecond=int(nanoseconds // 1000))
            return base
        except (OSError, OverflowError, ValueError):
            return None
    return timestamp


def _normalize_licor_time(value: Any) -> str:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) == 4 and parts[-1].isdigit():
        return f"{parts[0]}:{parts[1]}:{parts[2]}.{parts[3]}"
    return text


def _first_lookup_item(lookup: dict[str, str], aliases: tuple[str, ...]) -> tuple[str, str] | None:
    for alias in aliases:
        value = lookup.get(alias.lower())
        if value not in (None, ""):
            return alias.lower(), value
    return None


def _optional_ch4_ppb(lookup: dict[str, str]) -> float | None:
    return _optional_ppb(lookup, "ch4_ppb")


def _optional_ppb(lookup: dict[str, str], field: str) -> float | None:
    item = _first_lookup_item(lookup, GAS_COLUMN_ALIASES["ch4_ppb"])
    if field != "ch4_ppb":
        item = _first_lookup_item(lookup, GAS_COLUMN_ALIASES[field])
    if item is None:
        return None
    alias, raw_value = item
    value = _optional_float(raw_value)
    if value is None:
        return None
    gas = field.removesuffix("_ppb")
    if alias == field:
        return value
    if alias in {f"{gas}_ppm", f"{gas} (umol/mol)"}:
        return value * 1000.0
    if alias in {f"{gas}_molfrac", f"{gas}_mixing_ratio"} and abs(value) < 0.01:
        return value * 1_000_000_000.0
    bare_aliases = {gas, f"{gas}_mixing_ratio"}
    if gas == "ch4":
        bare_aliases.add("methane")
    if gas == "n2o":
        bare_aliases.add("nitrous_oxide")
    if alias in bare_aliases and 0.0 < abs(value) < 10.0:
        return value * 1000.0
    return value


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    if not float(number).is_integer():
        return None
    return int(number)


def _is_biomet_data_member(name: str) -> bool:
    lower = name.lower()
    return "biomet" in lower and lower.endswith(".data")


def _is_biomet_metadata_member(name: str) -> bool:
    lower = name.lower()
    return "biomet" in lower and lower.endswith(".metadata")


def _is_raw_data_member(name: str) -> bool:
    lower = name.lower()
    return "biomet" not in lower and lower.endswith(".data")


def _is_raw_metadata_member(name: str) -> bool:
    lower = name.lower()
    return "biomet" not in lower and lower.endswith(".metadata")


def _is_status_member(name: str) -> bool:
    return name.lower().endswith(".status")


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
