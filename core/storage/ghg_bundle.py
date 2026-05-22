from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any


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
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else ","
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=delimiter)
    return [dict(row) for row in reader]


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
