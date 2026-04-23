from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
import csv
from pathlib import Path
from typing import Any

from models.hf_models import FrameQuality


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


def _parse_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)
    return float(value)


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


@dataclass(slots=True)
class DeviceConnectionConfig:
    uid: str
    label: str
    port: str
    baudrate: int
    device_id: str
    software_profile: str = "standard"


@dataclass(slots=True)
class DeviceRuntimeState:
    connected: bool = False
    mode: int = 2
    active_send: bool = False
    ftd_hz: int = 10
    average_co2: int = 1
    average_h2o: int = 1
    filter_window: int = 49
    last_frame_time: datetime | None = None
    last_frame_quality: FrameQuality = FrameQuality.UNKNOWN
    last_message: str = "尚未连接设备"
    last_raw_frame: str = ""
    last_transaction_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectProfile:
    name: str = "新项目"
    code: str = "PRJ-001"
    principal: str = "现场团队"
    archive_root: str = "runtime_data"
    notes: str = "用于管理高频采集、事务追踪与后续报告导出。"


@dataclass(slots=True)
class SiteProfile:
    station_name: str = "站点 A"
    station_code: str = "SITE-A"
    location: str = "待填写"
    canopy_height_m: float = 2.0
    altitude_m: float = 30.0
    timezone: str = "Asia/Shanghai"
    latitude: float | None = None
    longitude: float | None = None
    displacement_height: float | None = None
    roughness_length: float | None = None
    timestamp_refers_to: str = "end_of_averaging_period"
    file_duration: float | None = None


@dataclass(slots=True)
class InstrumentMetadata:
    sonic_model: str = ""
    analyzer_model: str = ""
    analyzer_serial: str = ""
    sonic_serial: str = ""
    sonic_manufacturer: str = ""
    analyzer_manufacturer: str = ""
    sonic_firmware: str = ""
    analyzer_firmware: str = ""
    sonic_instrument_id: str = ""
    analyzer_instrument_id: str = ""
    analyzer_height_m: float | None = None
    sonic_height_m: float | None = None
    sensor_separation_m: float | None = None
    optical_path_length_m: float | None = None
    mount_description: str = ""
    geometry_detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawColumnMapping:
    column_name: str = ""
    ignore: bool = False
    numeric: bool = True
    variable: str = ""
    instrument: str = ""
    measurement_type: str = ""
    input_unit: str = ""
    output_unit: str = ""
    scaling: float | None = None
    nominal_lag: float | None = None
    min_lag: float | None = None
    max_lag: float | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawColumnMapping:
        return cls(
            column_name=str(payload.get("column_name", "")),
            ignore=bool(payload.get("ignore", False)),
            numeric=bool(payload.get("numeric", True)),
            variable=str(payload.get("variable", "")),
            instrument=str(payload.get("instrument", "")),
            measurement_type=str(payload.get("measurement_type", "")),
            input_unit=str(payload.get("input_unit", "")),
            output_unit=str(payload.get("output_unit", "")),
            scaling=_parse_optional_float(payload.get("scaling")),
            nominal_lag=_parse_optional_float(payload.get("nominal_lag")),
            min_lag=_parse_optional_float(payload.get("min_lag")),
            max_lag=_parse_optional_float(payload.get("max_lag")),
        )


@dataclass(slots=True)
class RawFileDescriptionMetadata:
    source_name: str = ""
    source_type: str = "csv"
    file_pattern: str = ""
    timestamp_column: str = "timestamp"
    timezone: str = "Asia/Shanghai"
    notes: str = ""
    column_mappings: list[RawColumnMapping] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawFileSettingsMetadata:
    sample_hz: float = 10.0
    delimiter: str = ","
    decimal: str = "."
    header_rows: int = 1
    encoding: str = "utf-8"
    missing_tokens: list[str] = field(default_factory=lambda: ["", "NA", "NaN"])
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SamplingChainMetadata:
    tube_length_m: float | None = None
    tube_diameter_mm: float | None = None
    flow_lpm: float | None = None
    tube_material: str = ""
    filter_model: str = ""
    heat_traced: bool = False
    insulated: bool = False
    path_length_m: float | None = None
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BiometSourceMetadata:
    source_mode: str = "none"
    source_path: str = ""
    time_column: str = "timestamp"
    aggregation_method: str = "mean"
    fields: list[str] = field(default_factory=list)
    directory_glob: str = "*.csv"
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DynamicMetadataRecord:
    start_time: datetime
    end_time: datetime
    values: dict[str, Any] = field(default_factory=dict)
    source_row: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "values": _jsonable(self.values),
            "source_row": int(self.source_row),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DynamicMetadataRecord:
        return cls(
            start_time=datetime.fromisoformat(str(payload["start_time"])),
            end_time=datetime.fromisoformat(str(payload["end_time"])),
            values=dict(payload.get("values", {})),
            source_row=int(payload.get("source_row", 0)),
        )


@dataclass(slots=True)
class DynamicMetadataConfig:
    source_path: str = ""
    start_column: str = "start_time"
    end_column: str = "end_time"
    timezone: str = "Asia/Shanghai"
    records: list[DynamicMetadataRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "start_column": self.start_column,
            "end_column": self.end_column,
            "timezone": self.timezone,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DynamicMetadataConfig:
        return cls(
            source_path=str(payload.get("source_path", "")),
            start_column=str(payload.get("start_column", "start_time")),
            end_column=str(payload.get("end_column", "end_time")),
            timezone=str(payload.get("timezone", "Asia/Shanghai")),
            records=[DynamicMetadataRecord.from_dict(item) for item in payload.get("records", [])],
        )


@dataclass(slots=True)
class MetadataBundle:
    project: ProjectProfile = field(default_factory=ProjectProfile)
    site: SiteProfile = field(default_factory=SiteProfile)
    instruments: InstrumentMetadata = field(default_factory=InstrumentMetadata)
    raw_file_description: RawFileDescriptionMetadata = field(default_factory=RawFileDescriptionMetadata)
    raw_file_settings: RawFileSettingsMetadata = field(default_factory=RawFileSettingsMetadata)
    sampling_chain: SamplingChainMetadata = field(default_factory=SamplingChainMetadata)
    biomet: BiometSourceMetadata = field(default_factory=BiometSourceMetadata)
    dynamic_metadata: DynamicMetadataConfig = field(default_factory=DynamicMetadataConfig)
    metadata_version: str = "ec_core_metadata_v1"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetadataBundle:
        return cls(
            project=ProjectProfile(**dict(payload.get("project", {}))),
            site=SiteProfile(**dict(payload.get("site", {}))),
            instruments=InstrumentMetadata(**dict(payload.get("instruments", {}))),
            raw_file_description=_raw_file_description_from_dict(dict(payload.get("raw_file_description", {}))),
            raw_file_settings=RawFileSettingsMetadata(**dict(payload.get("raw_file_settings", {}))),
            sampling_chain=SamplingChainMetadata(**dict(payload.get("sampling_chain", {}))),
            biomet=BiometSourceMetadata(**dict(payload.get("biomet", {}))),
            dynamic_metadata=DynamicMetadataConfig.from_dict(dict(payload.get("dynamic_metadata", {}))),
            metadata_version=str(payload.get("metadata_version", "ec_core_metadata_v1")),
            notes=[str(item) for item in payload.get("notes", [])],
        )


def load_dynamic_metadata_csv(
    path: str | Path,
    *,
    start_column: str = "start_time",
    end_column: str = "end_time",
) -> DynamicMetadataConfig:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        records: list[DynamicMetadataRecord] = []
        for index, row in enumerate(reader, start=2):
            start_time = _parse_datetime(row.get(start_column))
            end_time = _parse_datetime(row.get(end_column))
            if start_time is None or end_time is None:
                continue
            values = {key: value for key, value in row.items() if key not in {start_column, end_column}}
            records.append(
                DynamicMetadataRecord(
                    start_time=start_time,
                    end_time=end_time,
                    values=values,
                    source_row=index,
                )
            )
    return DynamicMetadataConfig(
        source_path=str(csv_path),
        start_column=start_column,
        end_column=end_column,
        records=records,
    )


def match_dynamic_metadata(
    records: list[DynamicMetadataRecord],
    *,
    window_start: datetime,
    window_end: datetime,
) -> DynamicMetadataRecord | None:
    best: DynamicMetadataRecord | None = None
    best_overlap = -1.0
    for record in records:
        overlap_start = max(window_start, record.start_time)
        overlap_end = min(window_end, record.end_time)
        overlap_seconds = (overlap_end - overlap_start).total_seconds()
        if overlap_seconds <= 0.0:
            continue
        if overlap_seconds > best_overlap:
            best = record
            best_overlap = overlap_seconds
    return best


def load_biomet_records(source: BiometSourceMetadata) -> list[dict[str, Any]]:
    if source.source_mode not in {"external_file", "external_directory"} or not source.source_path:
        return []
    root = Path(source.source_path)
    paths: list[Path]
    if source.source_mode == "external_file":
        paths = [root] if root.exists() else []
    else:
        paths = sorted(root.glob(source.directory_glob)) if root.exists() else []
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                timestamp = _parse_datetime(row.get(source.time_column))
                if timestamp is None:
                    continue
                parsed = {"timestamp": timestamp, "__source_file__": str(path)}
                for key, value in row.items():
                    if key == source.time_column:
                        continue
                    parsed[key] = value
                rows.append(parsed)
    rows.sort(key=lambda item: item["timestamp"])
    return rows


def aggregate_biomet_window(
    rows: list[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    fields: list[str],
    aggregation_method: str = "mean",
) -> dict[str, Any]:
    window_rows = [row for row in rows if window_start <= row["timestamp"] <= window_end]
    if not window_rows:
        return {}
    output: dict[str, Any] = {}
    for field_name in fields:
        values = [_parse_optional_float(row.get(field_name)) for row in window_rows]
        numeric = [value for value in values if value is not None]
        if not numeric:
            continue
        if aggregation_method == "last":
            output[field_name] = float(numeric[-1])
        elif aggregation_method == "max":
            output[field_name] = float(max(numeric))
        elif aggregation_method == "min":
            output[field_name] = float(min(numeric))
        else:
            output[field_name] = float(sum(numeric) / len(numeric))
    output["sample_count"] = len(window_rows)
    output["aggregation_method"] = aggregation_method
    return output


def metadata_completeness(bundle: MetadataBundle) -> dict[str, Any]:
    checks = {
        "project_name": bool(bundle.project.name.strip()),
        "project_code": bool(bundle.project.code.strip()),
        "site_name": bool(bundle.site.station_name.strip()),
        "site_code": bool(bundle.site.station_code.strip()),
        "latitude": bundle.site.latitude is not None,
        "longitude": bundle.site.longitude is not None,
        "timestamp_refers_to": bool(bundle.site.timestamp_refers_to.strip()),
        "file_duration": bundle.site.file_duration is not None and bundle.site.file_duration > 0.0,
        "tube_length": bundle.sampling_chain.tube_length_m is not None,
        "flow_lpm": bundle.sampling_chain.flow_lpm is not None,
        "sensor_separation": bundle.instruments.sensor_separation_m is not None,
        "path_length": bundle.instruments.optical_path_length_m is not None or bundle.sampling_chain.path_length_m is not None,
        "instrument_models": bool(bundle.instruments.sonic_model.strip()) and bool(bundle.instruments.analyzer_model.strip()),
        "instrument_ids": bool(bundle.instruments.sonic_instrument_id.strip()) and bool(bundle.instruments.analyzer_instrument_id.strip()),
        "sample_hz": bundle.raw_file_settings.sample_hz > 0.0,
        "timestamp_column": bool(bundle.raw_file_description.timestamp_column.strip()),
        "column_mappings": bool(bundle.raw_file_description.column_mappings),
    }
    score = int(sum(1 for ok in checks.values() if ok) / max(1, len(checks)) * 100)
    return {
        "score": score,
        "missing_items": [key for key, ok in checks.items() if not ok],
        "metadata_version": bundle.metadata_version,
    }


def _raw_file_description_from_dict(payload: dict[str, Any]) -> RawFileDescriptionMetadata:
    values = dict(payload)
    column_payload = values.pop("column_mappings", [])
    description = RawFileDescriptionMetadata(**values)
    description.column_mappings = [RawColumnMapping.from_dict(dict(item)) for item in column_payload]
    return description
