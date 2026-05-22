from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from models.hf_models import FrameQuality, NormalizedHFFrame


GAS_COLUMN_ALIASES = {
    "co2_ppm": ("co2_ppm", "co2", "co2_molar_density", "co2_molfrac", "co2_mixing_ratio"),
    "h2o_mmol": ("h2o_mmol", "h2o", "h2o_molar_density", "h2o_molfrac", "h2o_mixing_ratio"),
    "ch4_ppb": ("ch4_ppb", "ch4_ppm", "ch4", "methane", "ch4_molfrac", "ch4_mixing_ratio"),
    "pressure_kpa": ("pressure_kpa", "pressure", "press", "p", "ambient_pressure"),
    "chamber_temp_c": ("chamber_temp_c", "air_temperature", "temperature", "temp", "ta", "sonic_temperature"),
    "case_temp_c": ("case_temp_c", "cell_temperature", "analyzer_temperature", "box_temperature"),
}

WIND_COLUMN_ALIASES = {
    "u": ("u", "u_ms", "u_mps", "wind_u", "u_unrot"),
    "v": ("v", "v_ms", "v_mps", "wind_v", "v_unrot"),
    "w": ("w", "w_ms", "w_mps", "wind_w", "vertical_velocity", "vertical_wind", "w_unrot"),
}

TIME_COLUMN_ALIASES = ("timestamp", "time", "datetime", "date_time", "ts")


@dataclass(slots=True)
class GHGBundleManifest:
    path: str
    member_names: list[str]
    raw_data_members: list[str]
    raw_metadata_members: list[str]
    biomet_data_members: list[str]
    biomet_metadata_members: list[str]
    has_embedded_biomet: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "member_names": self.member_names,
            "raw_data_members": self.raw_data_members,
            "raw_metadata_members": self.raw_metadata_members,
            "biomet_data_members": self.biomet_data_members,
            "biomet_metadata_members": self.biomet_metadata_members,
            "has_embedded_biomet": self.has_embedded_biomet,
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
        biomet_data_members=biomet_data,
        biomet_metadata_members=biomet_metadata,
        has_embedded_biomet=bool(biomet_data or biomet_metadata),
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
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=delimiter)
    return [dict(row) for row in reader]


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
            timestamp = _parse_datetime(row.get(time_column))
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
) -> NormalizedHFFrame | None:
    lookup = _casefold_lookup(row)
    timestamp = _parse_datetime(_first_lookup_value(lookup, TIME_COLUMN_ALIASES))
    if timestamp is None:
        return None
    ch4_ppb = _optional_ch4_ppb(lookup)
    wind_payload = {
        key: _optional_float(_first_lookup_value(lookup, aliases))
        for key, aliases in WIND_COLUMN_ALIASES.items()
    }
    raw_payload = {
        key: value
        for key, value in {
            **wind_payload,
            "ch4_ppb": ch4_ppb,
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


def _first_lookup_item(lookup: dict[str, str], aliases: tuple[str, ...]) -> tuple[str, str] | None:
    for alias in aliases:
        value = lookup.get(alias.lower())
        if value not in (None, ""):
            return alias.lower(), value
    return None


def _optional_ch4_ppb(lookup: dict[str, str]) -> float | None:
    item = _first_lookup_item(lookup, GAS_COLUMN_ALIASES["ch4_ppb"])
    if item is None:
        return None
    alias, raw_value = item
    value = _optional_float(raw_value)
    if value is None:
        return None
    if alias == "ch4_ppb":
        return value
    if alias == "ch4_ppm":
        return value * 1000.0
    if alias in {"ch4_molfrac", "ch4_mixing_ratio"} and abs(value) < 0.01:
        return value * 1_000_000_000.0
    if alias in {"ch4", "methane", "ch4_mixing_ratio"} and 0.0 < abs(value) < 10.0:
        return value * 1000.0
    return value


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


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


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
