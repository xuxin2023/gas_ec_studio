from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, Signal

from core.acquisition.acquisition_service import AcquisitionService
from core.acquisition.realtime_buffer import RealtimeBuffer
from core.adapters.factory import build_adapter
from core.comparison.eddypro_comparator import EddyProComparator
from core.ec_fcc.pipeline import ECFCCPipeline
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.delivery_exporter import export_delivery_package
from core.exports.evidence_exporter import EvidenceExporter
from core.exports.report_exporter import export_formal_report, export_report_snapshot
from core.exports.result_exporter import ResultExporter
from core.protocol.coefficient_codec import encode_coefficients, parse_coefficient_line
from core.protocol.command_builder import CommandBuilder, normalize_device_id
from core.protocol.software_profile import SoftwareProfile
from core.protocol.transaction_manager import TransactionManager
from core.storage.hf_data_store import HFDataStore
from core.storage.metadata_store import MetadataStore
from core.storage.raw_stream_store import RawStreamStore
from core.storage.run_result_store import RunResultStore
from models.comparison_models import CompareAttributionResult, EddyProCompareResult, WindowCompareResult
from models.hf_models import FrameQuality, NormalizedHFFrame, ProtocolFrame
from models.result_models import EventRecord, TransactionRecord
from models.rp_models import RPRunResult, WindowRPResult
from models.spectral_models import BatchCompareResult, EvidenceBundleManifest, SpectralRunResult, WindowSpectralResult
from models.station_models import (
    DeviceConnectionConfig,
    DeviceRuntimeState,
    MetadataBundle,
    ProjectProfile,
    SiteProfile,
    SamplingChainMetadata,
    InstrumentMetadata,
    RawColumnMapping,
    RawFileDescriptionMetadata,
    RawFileSettingsMetadata,
    BiometSourceMetadata,
    DynamicMetadataConfig,
    load_dynamic_metadata_csv,
    metadata_completeness,
)


@dataclass(slots=True)
class ManagedDevice:
    config: DeviceConnectionConfig
    runtime: DeviceRuntimeState
    profile: SoftwareProfile
    builder: CommandBuilder
    adapter: object


class StudioController(QObject):
    devices_changed = Signal()
    frame_received = Signal(object)
    transactions_changed = Signal()
    selection_changed = Signal()
    logs_changed = Signal()
    events_changed = Signal()
    view_mode_changed = Signal(str)
    project_changed = Signal()
    processing_changed = Signal()
    spectral_qc_changed = Signal()
    report_changed = Signal()

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        super().__init__()
        self.workspace_root = Path(workspace_root or Path.cwd())
        self.runtime_root = self.workspace_root / "runtime_data"
        self.runtime_root.mkdir(parents=True, exist_ok=True)

        self.project_profile = ProjectProfile(archive_root=str(self.runtime_root))
        self.site_profile = SiteProfile()
        self.metadata_store = MetadataStore(self.runtime_root / "meta")
        self.raw_store = RawStreamStore(self.runtime_root / "raw")
        self.hf_store = HFDataStore(self.runtime_root / "hf")
        self.run_result_store = RunResultStore(self.runtime_root / "run_results")
        self.evidence_exporter = EvidenceExporter(self.runtime_root)
        self.result_exporter = ResultExporter(self.runtime_root)
        self.metadata_store.upsert_project(self.project_profile)
        self.metadata_store.upsert_site(self.site_profile)

        self.transaction_manager = TransactionManager()
        self.ec_fcc_pipeline = ECFCCPipeline()
        self.ec_rp_pipeline = ECRPPipeline()
        self.realtime_buffer = RealtimeBuffer(maxlen=7200)
        self.devices: dict[str, ManagedDevice] = {}
        self.raw_frames: deque[ProtocolFrame] = deque(maxlen=160)
        self.device_frame_history: dict[str, deque[ProtocolFrame]] = defaultdict(lambda: deque(maxlen=240))
        self.events: deque[EventRecord] = deque(maxlen=240)
        self.logs: deque[dict] = deque(maxlen=400)
        self.view_mode = "operator"
        self.selected_device_uid: str | None = None
        self.selected_page = "device_center"
        self.project_nav_section = "overview"
        self.ec_nav_step = "window_sampling"
        self.spectral_qc_nav_section = "overview"
        self._lock = Lock()
        self._event_cooldowns: dict[tuple[str, str], datetime] = {}
        self.spectral_runs: list[SpectralRunResult] = self.run_result_store.list_spectral_runs()
        self.latest_evidence_manifest: EvidenceBundleManifest | None = None
        self.latest_batch_compare: BatchCompareResult | None = None
        self.latest_eddypro_compare_result: EddyProCompareResult | None = None
        self.latest_eddypro_compare_manifest: dict[str, object] | None = None
        self.latest_eddypro_attribution_result: CompareAttributionResult | None = None
        self.rp_runs: list[RPRunResult] = []
        self.project_workspace = self._build_default_project_workspace()
        self.ec_processing = self._build_default_ec_processing()
        self.ec_processing_workspace = self._build_default_ec_processing_workspace()
        self.spectral_qc_workspace = self._build_default_spectral_qc_workspace()
        self.report_center_workspace = self._build_default_report_center_workspace()
        self._persist_metadata_bundle()

        self.acquisition = AcquisitionService(
            frame_callback=self._handle_frame,
            log_callback=self._append_log,
        )
        self.bootstrap_demo_device()
        self._load_persisted_results()

    def bootstrap_demo_device(self) -> None:
        uid = self.add_device(
            label="演示分析仪",
            port="SIM1",
            baudrate=115200,
            device_id="001",
        )
        self.connect_device(uid)
        self.set_comm_way(uid, False)
        self._append_log("info", "已载入演示设备，可直接查看设备中心、单设备详情和实时采集界面。")

    def shutdown(self) -> None:
        self.acquisition.shutdown()

    def set_selected_page(self, page_key: str) -> None:
        self.selected_page = page_key
        self.selection_changed.emit()

    def set_view_mode(self, view_mode: str) -> None:
        self.view_mode = "engineer" if view_mode == "engineer" else "operator"
        self.view_mode_changed.emit(self.view_mode)

    def set_project_nav_section(self, section_key: str) -> None:
        self.project_nav_section = section_key
        self.selection_changed.emit()

    def set_ec_nav_step(self, step_key: str) -> None:
        self.ec_nav_step = step_key
        self.selection_changed.emit()

    def set_spectral_qc_nav_section(self, section_key: str) -> None:
        self.spectral_qc_nav_section = section_key
        self.selection_changed.emit()

    def set_report_nav_section(self, section_key: str) -> None:
        self.report_center_workspace["selected_report"] = section_key
        self.report_changed.emit()
        self.selection_changed.emit()

    def set_report_view_mode(self, view_mode: str) -> None:
        self.report_center_workspace.setdefault("filters", {})["view_mode"] = view_mode
        self._sync_report_center_from_results()
        self.report_changed.emit()
        self.selection_changed.emit()

    def set_report_batch_label(self, batch_label: str) -> None:
        filters = self.report_center_workspace.setdefault("filters", {})
        filters["batch"] = batch_label
        run_id = self.report_center_workspace.get("batch_lookup", {}).get(batch_label)
        self.report_center_workspace["active_run_id"] = run_id
        if run_id is not None:
            run = next((result for result in self.spectral_runs if result.run_id == run_id), None)
            if run is not None:
                self._sync_spectral_workspace_from_result(run)
        self._sync_report_center_from_results()
        self.report_changed.emit()
        self.spectral_qc_changed.emit()
        self.selection_changed.emit()

    def current_spectral_run(self) -> SpectralRunResult | None:
        run_id = self.spectral_qc_workspace.get("active_run_id") or self.report_center_workspace.get("active_run_id")
        if run_id:
            for result in self.spectral_runs:
                if result.run_id == run_id:
                    return result
        return self.spectral_runs[0] if self.spectral_runs else None

    def current_window_result(self) -> WindowSpectralResult | None:
        run = self.current_spectral_run()
        if run is None or not run.windows:
            return None
        selected_id = self.spectral_qc_workspace.get("selected_window_id")
        if selected_id:
            for window in run.windows:
                if window.window_id == selected_id:
                    return window
        return run.windows[0]

    def available_batch_labels(self) -> list[str]:
        return [self._batch_label(result) for result in self.spectral_runs]

    def add_device(self, *, label: str, port: str, baudrate: int, device_id: str) -> str:
        uid = uuid4().hex[:8]
        normalized_id = normalize_device_id(device_id)
        profile = SoftwareProfile.standard()
        config = DeviceConnectionConfig(
            uid=uid,
            label=label.strip() or f"分析仪 {normalized_id}",
            port=port.strip() or "COM1",
            baudrate=int(baudrate),
            device_id=normalized_id,
            software_profile=profile.name,
        )
        runtime = DeviceRuntimeState(active_send=profile.default_active_send, mode=profile.default_mode)
        runtime.last_message = "尚未开始采集"
        adapter = build_adapter(port=config.port, baudrate=config.baudrate, device_id=config.device_id)
        entry = ManagedDevice(
            config=config,
            runtime=runtime,
            profile=profile,
            builder=CommandBuilder(profile=profile),
            adapter=adapter,
        )
        with self._lock:
            self.devices[uid] = entry
            self.device_frame_history[uid]
            if self.selected_device_uid is None:
                self.selected_device_uid = uid
        self.metadata_store.upsert_device(config)
        self._append_log("info", f"已添加设备连接：{config.label}（{config.port}）")
        self.devices_changed.emit()
        self.selection_changed.emit()
        return uid

    def connect_device(self, device_uid: str) -> None:
        entry = self._get_device(device_uid)
        if entry.runtime.connected:
            return
        self.acquisition.connect_session(
            device_uid=entry.config.uid,
            device_id=entry.config.device_id,
            adapter=entry.adapter,
            builder=entry.builder,
            profile=entry.profile,
            active_send=entry.runtime.active_send,
            ftd_hz=entry.runtime.ftd_hz,
        )
        with self._lock:
            entry.runtime.connected = True
            entry.runtime.last_message = "设备在线，正在等待有效数据。"
            entry.runtime.extra["last_seen_at"] = datetime.now()
        self._append_log("info", f"{entry.config.label} 已连接。")
        self.devices_changed.emit()

    def disconnect_device(self, device_uid: str) -> None:
        entry = self._get_device(device_uid)
        if not entry.runtime.connected:
            return
        self.acquisition.disconnect_session(device_uid)
        with self._lock:
            entry.runtime.connected = False
            entry.runtime.last_message = "设备已断开，采集已停止。"
        self._append_log("info", f"{entry.config.label} 已断开。")
        self.devices_changed.emit()

    def connect_all_devices(self) -> None:
        for uid, entry in list(self.devices.items()):
            if not entry.runtime.connected:
                self.connect_device(uid)

    def disconnect_all_devices(self) -> None:
        for uid, entry in list(self.devices.items()):
            if entry.runtime.connected:
                self.disconnect_device(uid)

    def select_device(self, device_uid: str) -> None:
        self.selected_device_uid = device_uid
        self.selection_changed.emit()

    def save_project_and_site(self, project: ProjectProfile, site: SiteProfile) -> None:
        self.project_profile = project
        self.site_profile = site
        self.report_center_workspace.setdefault("filters", {})["project"] = project.name or "当前项目"
        self.metadata_store.upsert_project(project)
        self.metadata_store.upsert_site(site)
        self._append_log("info", "项目与站点信息已保存。")
        self.project_changed.emit()

    def save_project_workspace(self, payload: dict) -> None:
        self.project_workspace = self._ensure_metadata_workspace(deepcopy(payload))
        overview = self.project_workspace.get("overview", {})
        site_info = self.project_workspace.get("site_info", {})
        station_meta = self.project_workspace.get("metadata", {}).get("station", {})
        self.project_profile = ProjectProfile(
            name=str(overview.get("project_name") or self.project_profile.name),
            code=str(overview.get("project_code") or self.project_profile.code),
            principal=str(overview.get("principal") or self.project_profile.principal),
            archive_root=str(overview.get("archive_root") or self.project_profile.archive_root),
            notes=str(overview.get("notes") or self.project_profile.notes),
        )
        self.site_profile = SiteProfile(
            station_name=str(site_info.get("station_name") or self.site_profile.station_name),
            station_code=str(site_info.get("station_code") or self.site_profile.station_code),
            location=str(site_info.get("location") or self.site_profile.location),
            canopy_height_m=float(site_info.get("canopy_height_m") or self.site_profile.canopy_height_m),
            altitude_m=float(site_info.get("altitude_m") or self.site_profile.altitude_m),
            timezone=str(site_info.get("timezone") or self.site_profile.timezone),
            latitude=self._coerce_optional_float(station_meta.get("latitude"), self.site_profile.latitude),
            longitude=self._coerce_optional_float(station_meta.get("longitude"), self.site_profile.longitude),
            displacement_height=self._coerce_optional_float(station_meta.get("displacement_height"), self.site_profile.displacement_height),
            roughness_length=self._coerce_optional_float(station_meta.get("roughness_length"), self.site_profile.roughness_length),
            timestamp_refers_to=str(station_meta.get("timestamp_refers_to") or self.site_profile.timestamp_refers_to),
            file_duration=self._coerce_optional_float(station_meta.get("file_duration"), self.site_profile.file_duration),
        )
        self.report_center_workspace.setdefault("filters", {})["project"] = self.project_profile.name or "当前项目"
        self.metadata_store.upsert_project(self.project_profile)
        self.metadata_store.upsert_site(self.site_profile)
        self._persist_metadata_bundle()
        self._append_log("info", "项目与站点工作区配置已保存。")
        self.project_changed.emit()

    def metadata_bundle(self) -> MetadataBundle:
        state = self._ensure_metadata_workspace(deepcopy(self.project_workspace))
        overview = state.get("overview", {})
        site_info = state.get("site_info", {})
        instrument_layout = state.get("instrument_layout", {})
        sampling_chain = state.get("sampling_chain", {})
        timing = state.get("timing", {})
        metadata = state.get("metadata", {})
        station_meta = metadata.get("station", {})
        instrument_meta = metadata.get("instruments", {})
        raw_description_meta = metadata.get("raw_file_description", {})
        raw_settings_meta = metadata.get("raw_file_settings", {})
        biomet_meta = metadata.get("biomet_source", {})
        dynamic_meta = metadata.get("dynamic_metadata", {})
        alternative_meta = metadata.get("alternative_metadata", {})
        return MetadataBundle(
            project=self.project_profile,
            site=SiteProfile(
                station_name=str(site_info.get("station_name") or self.site_profile.station_name),
                station_code=str(site_info.get("station_code") or self.site_profile.station_code),
                location=str(site_info.get("location") or self.site_profile.location),
                canopy_height_m=float(site_info.get("canopy_height_m") or self.site_profile.canopy_height_m),
                altitude_m=float(site_info.get("altitude_m") or self.site_profile.altitude_m),
                timezone=str(site_info.get("timezone") or self.site_profile.timezone),
                latitude=self._coerce_optional_float(station_meta.get("latitude"), self.site_profile.latitude),
                longitude=self._coerce_optional_float(station_meta.get("longitude"), self.site_profile.longitude),
                displacement_height=self._coerce_optional_float(station_meta.get("displacement_height"), self.site_profile.displacement_height),
                roughness_length=self._coerce_optional_float(station_meta.get("roughness_length"), self.site_profile.roughness_length),
                timestamp_refers_to=str(station_meta.get("timestamp_refers_to") or self.site_profile.timestamp_refers_to),
                file_duration=self._coerce_optional_float(station_meta.get("file_duration"), self.site_profile.file_duration),
            ),
            instruments=InstrumentMetadata(
                analyzer_model=str(instrument_meta.get("analyzer_model") or instrument_layout.get("analyzer_mount", "")),
                sonic_model=str(instrument_meta.get("sonic_model") or instrument_layout.get("sonic_mount", "")),
                analyzer_serial=str(instrument_meta.get("analyzer_serial", "")),
                sonic_serial=str(instrument_meta.get("sonic_serial", "")),
                analyzer_manufacturer=str(instrument_meta.get("analyzer_manufacturer", "")),
                sonic_manufacturer=str(instrument_meta.get("sonic_manufacturer", "")),
                analyzer_firmware=str(instrument_meta.get("analyzer_firmware", "")),
                sonic_firmware=str(instrument_meta.get("sonic_firmware", "")),
                analyzer_instrument_id=str(instrument_meta.get("analyzer_instrument_id", "")),
                sonic_instrument_id=str(instrument_meta.get("sonic_instrument_id", "")),
                analyzer_height_m=float(instrument_layout.get("analyzer_height_m") or 0.0) or None,
                sonic_height_m=float(instrument_layout.get("sonic_height_m") or 0.0) or None,
                sensor_separation_m=float(instrument_layout.get("height_delta_m") or 0.0) or None,
                optical_path_length_m=float(sampling_chain.get("path_length_m") or 0.0) or None,
                mount_description=str(instrument_meta.get("mount_description") or instrument_layout.get("layout_note", "")),
                geometry_detail=str(instrument_meta.get("geometry_detail", "")),
                extra={
                    "reference_sensor": instrument_layout.get("reference_sensor", ""),
                    "orientation_deg": instrument_layout.get("orientation_deg", 0),
                },
            ),
            raw_file_description=RawFileDescriptionMetadata(
                source_name=str(raw_description_meta.get("source_name") or overview.get("project_name", "")),
                source_type=str(raw_description_meta.get("source_type", "hf_frame")),
                file_pattern=str(raw_description_meta.get("file_pattern") or state.get("output_template", {}).get("file_pattern", "")),
                timestamp_column=str(raw_description_meta.get("timestamp_column", "timestamp")),
                timezone=str(raw_description_meta.get("timezone") or timing.get("timezone") or self.site_profile.timezone),
                notes=str(raw_description_meta.get("notes") or overview.get("notes", "")),
                column_mappings=self._parse_column_mappings(raw_description_meta.get("column_mappings_json", "")),
            ),
            raw_file_settings=RawFileSettingsMetadata(
                sample_hz=float(raw_settings_meta.get("sample_hz") or timing.get("sample_hz") or 10.0),
                delimiter=str(raw_settings_meta.get("delimiter", ",")),
                decimal=str(raw_settings_meta.get("decimal", ".")),
                header_rows=int(raw_settings_meta.get("header_rows", 1) or 1),
                encoding=str(raw_settings_meta.get("encoding", "utf-8")),
                missing_tokens=self._split_csv_values(raw_settings_meta.get("missing_tokens", ",NA,NaN")),
                extra={
                    "block_minutes": float(timing.get("block_minutes") or 30.0),
                    "clock_source": timing.get("clock_source", ""),
                    "file_duration": self._coerce_optional_float(station_meta.get("file_duration"), self.site_profile.file_duration),
                    "timestamp_refers_to": str(station_meta.get("timestamp_refers_to") or self.site_profile.timestamp_refers_to),
                },
            ),
            sampling_chain=SamplingChainMetadata(
                tube_length_m=float(sampling_chain.get("tube_length_m") or 0.0) or None,
                tube_diameter_mm=float(sampling_chain.get("tube_diameter_mm") or 0.0) or None,
                flow_lpm=float(sampling_chain.get("flow_lpm") or 0.0) or None,
                tube_material=str(sampling_chain.get("tube_material", "")),
                filter_model=str(sampling_chain.get("filter_model", "")),
                heat_traced=bool(sampling_chain.get("heat_traced", False)),
                insulated=bool(sampling_chain.get("insulated", False)),
                path_length_m=float(sampling_chain.get("path_length_m") or 0.0) or None,
                notes=str(sampling_chain.get("chain_note", "")),
            ),
            biomet=BiometSourceMetadata(
                source_mode=str(biomet_meta.get("source_mode", "none")),
                source_path=str(biomet_meta.get("source_path", "")),
                time_column=str(biomet_meta.get("time_column", "timestamp")),
                aggregation_method=str(biomet_meta.get("aggregation_method", "mean")),
                fields=self._split_csv_values(biomet_meta.get("fields", "")),
                directory_glob=str(biomet_meta.get("directory_glob", "*.csv")),
                notes=str(biomet_meta.get("notes", "")),
                extra={},
            ),
            dynamic_metadata=DynamicMetadataConfig.from_dict(
                {
                    "source_path": str(dynamic_meta.get("source_path", "")),
                    "start_column": str(dynamic_meta.get("start_column", "start_time")),
                    "end_column": str(dynamic_meta.get("end_column", "end_time")),
                    "timezone": str(dynamic_meta.get("timezone", self.site_profile.timezone)),
                    "records": list(dynamic_meta.get("records", [])),
                }
            ),
            notes=[
                f"project_template={overview.get('template_name', '')}",
                f"runtime_template={state.get('runtime_template', {}).get('template_name', '')}",
                f"alternative_profile={alternative_meta.get('active_profile', self.project_profile.code or 'default')}",
            ],
        )

    def metadata_profile_names(self) -> list[str]:
        return self.metadata_store.list_alternative_metadata()

    def import_dynamic_metadata_csv(self, path: str, *, start_column: str, end_column: str, timezone: str) -> dict:
        config = load_dynamic_metadata_csv(path, start_column=start_column, end_column=end_column)
        payload = config.to_dict()
        payload["timezone"] = timezone
        metadata = deepcopy(self.project_workspace.get("metadata", {}))
        metadata.setdefault("dynamic_metadata", {}).update(payload)
        self.project_workspace["metadata"] = metadata
        self._persist_metadata_bundle()
        self.project_changed.emit()
        return payload

    def save_metadata_profile(self, profile_name: str) -> str:
        name = profile_name.strip() or (self.project_profile.code or "default")
        bundle = self.metadata_bundle()
        self.metadata_store.save_alternative_metadata(name, bundle)
        metadata = deepcopy(self.project_workspace.get("metadata", {}))
        alt = metadata.setdefault("alternative_metadata", {})
        alt["active_profile"] = name
        alt["available_profiles"] = self.metadata_store.list_alternative_metadata()
        self.project_workspace["metadata"] = metadata
        self.metadata_store.save_metadata_document("active_profile", {"profile_name": name})
        self._persist_metadata_bundle()
        self.project_changed.emit()
        return name

    def load_metadata_profile(self, profile_name: str) -> bool:
        bundle = self.metadata_store.load_alternative_metadata(profile_name)
        if bundle is None:
            return False
        self._apply_metadata_bundle(bundle, profile_name=profile_name)
        self._persist_metadata_bundle()
        self.project_changed.emit()
        return True

    def _apply_metadata_bundle(self, bundle: MetadataBundle, *, profile_name: str | None = None) -> None:
        workspace = self._ensure_metadata_workspace(deepcopy(self.project_workspace))
        overview = workspace.setdefault("overview", {})
        site_info = workspace.setdefault("site_info", {})
        instrument_layout = workspace.setdefault("instrument_layout", {})
        sampling_chain = workspace.setdefault("sampling_chain", {})
        timing = workspace.setdefault("timing", {})
        metadata = workspace.setdefault("metadata", {})

        overview["project_name"] = bundle.project.name
        overview["project_code"] = bundle.project.code
        overview["principal"] = bundle.project.principal
        overview["archive_root"] = bundle.project.archive_root
        overview["notes"] = bundle.project.notes

        site_info["station_name"] = bundle.site.station_name
        site_info["station_code"] = bundle.site.station_code
        site_info["location"] = bundle.site.location
        site_info["canopy_height_m"] = bundle.site.canopy_height_m
        site_info["altitude_m"] = bundle.site.altitude_m
        site_info["timezone"] = bundle.site.timezone

        instrument_layout["analyzer_height_m"] = bundle.instruments.analyzer_height_m or 0.0
        instrument_layout["sonic_height_m"] = bundle.instruments.sonic_height_m or 0.0
        instrument_layout["height_delta_m"] = bundle.instruments.sensor_separation_m or 0.0
        instrument_layout["analyzer_mount"] = bundle.instruments.analyzer_model
        instrument_layout["sonic_mount"] = bundle.instruments.sonic_model
        instrument_layout["layout_note"] = bundle.instruments.mount_description

        sampling_chain["tube_length_m"] = bundle.sampling_chain.tube_length_m or 0.0
        sampling_chain["tube_diameter_mm"] = bundle.sampling_chain.tube_diameter_mm or 0.0
        sampling_chain["flow_lpm"] = bundle.sampling_chain.flow_lpm or 0.0
        sampling_chain["tube_material"] = bundle.sampling_chain.tube_material
        sampling_chain["filter_model"] = bundle.sampling_chain.filter_model
        sampling_chain["heat_traced"] = bundle.sampling_chain.heat_traced
        sampling_chain["insulated"] = bundle.sampling_chain.insulated
        sampling_chain["path_length_m"] = bundle.sampling_chain.path_length_m or 0.0
        sampling_chain["chain_note"] = bundle.sampling_chain.notes

        timing["timezone"] = bundle.site.timezone
        timing["sample_hz"] = bundle.raw_file_settings.sample_hz
        timing["block_minutes"] = bundle.raw_file_settings.extra.get("block_minutes", timing.get("block_minutes", 30.0))

        metadata["station"] = {
            "latitude": bundle.site.latitude,
            "longitude": bundle.site.longitude,
            "displacement_height": bundle.site.displacement_height,
            "roughness_length": bundle.site.roughness_length,
            "timestamp_refers_to": bundle.site.timestamp_refers_to,
            "file_duration": bundle.site.file_duration,
        }
        metadata["instruments"] = {
            "sonic_model": bundle.instruments.sonic_model,
            "analyzer_model": bundle.instruments.analyzer_model,
            "sonic_serial": bundle.instruments.sonic_serial,
            "analyzer_serial": bundle.instruments.analyzer_serial,
            "sonic_manufacturer": bundle.instruments.sonic_manufacturer,
            "analyzer_manufacturer": bundle.instruments.analyzer_manufacturer,
            "sonic_firmware": bundle.instruments.sonic_firmware,
            "analyzer_firmware": bundle.instruments.analyzer_firmware,
            "sonic_instrument_id": bundle.instruments.sonic_instrument_id,
            "analyzer_instrument_id": bundle.instruments.analyzer_instrument_id,
            "mount_description": bundle.instruments.mount_description,
            "geometry_detail": bundle.instruments.geometry_detail,
        }
        metadata["raw_file_description"] = {
            "source_name": bundle.raw_file_description.source_name,
            "source_type": bundle.raw_file_description.source_type,
            "file_pattern": bundle.raw_file_description.file_pattern,
            "timestamp_column": bundle.raw_file_description.timestamp_column,
            "timezone": bundle.raw_file_description.timezone,
            "notes": bundle.raw_file_description.notes,
            "column_mappings_json": self._column_mappings_to_text(bundle.raw_file_description.column_mappings),
        }
        metadata["raw_file_settings"] = {
            "sample_hz": bundle.raw_file_settings.sample_hz,
            "delimiter": bundle.raw_file_settings.delimiter,
            "decimal": bundle.raw_file_settings.decimal,
            "header_rows": bundle.raw_file_settings.header_rows,
            "encoding": bundle.raw_file_settings.encoding,
            "missing_tokens": ",".join(bundle.raw_file_settings.missing_tokens),
        }
        metadata["biomet_source"] = {
            "source_mode": bundle.biomet.source_mode,
            "source_path": bundle.biomet.source_path,
            "time_column": bundle.biomet.time_column,
            "aggregation_method": bundle.biomet.aggregation_method,
            "fields": ",".join(bundle.biomet.fields),
            "directory_glob": bundle.biomet.directory_glob,
            "notes": bundle.biomet.notes,
        }
        metadata["dynamic_metadata"] = bundle.dynamic_metadata.to_dict()
        metadata["alternative_metadata"] = {
            "active_profile": profile_name or bundle.project.code or "default",
            "available_profiles": self.metadata_store.list_alternative_metadata(),
        }
        self.project_profile = bundle.project
        self.site_profile = bundle.site
        self.project_workspace = workspace
        self.report_center_workspace.setdefault("filters", {})["project"] = self.project_profile.name or "褰撳墠椤圭洰"
        self.metadata_store.upsert_project(self.project_profile)
        self.metadata_store.upsert_site(self.site_profile)

    def _persist_metadata_bundle(self) -> None:
        payload = self.metadata_bundle().to_dict()
        self.metadata_store.save_metadata_document("active_metadata", payload)
        active_profile = (
            self.project_workspace.get("metadata", {})
            .get("alternative_metadata", {})
            .get("active_profile")
            or self.project_profile.code
            or "default"
        )
        self.metadata_store.save_metadata_document("dynamic_metadata", payload.get("dynamic_metadata", {}))
        self.metadata_store.save_metadata_document("biomet_source", payload.get("biomet", {}))
        self.metadata_store.save_metadata_document("active_profile", {"profile_name": active_profile})
        self.metadata_store.save_alternative_metadata(str(active_profile), payload)

    def _ensure_metadata_workspace(self, payload: dict) -> dict:
        metadata = payload.setdefault("metadata", {})
        site_info = payload.setdefault("site_info", {})
        instrument_layout = payload.setdefault("instrument_layout", {})
        sampling_chain = payload.setdefault("sampling_chain", {})
        timing = payload.setdefault("timing", {})
        overview = payload.setdefault("overview", {})
        dynamic_doc = self.metadata_store.load_metadata_document("dynamic_metadata") or {}
        biomet_doc = self.metadata_store.load_metadata_document("biomet_source") or {}
        active_profile_doc = self.metadata_store.load_metadata_document("active_profile") or {}
        metadata.setdefault(
            "station",
            {
                "latitude": self.site_profile.latitude,
                "longitude": self.site_profile.longitude,
                "displacement_height": self.site_profile.displacement_height,
                "roughness_length": self.site_profile.roughness_length,
                "timestamp_refers_to": self.site_profile.timestamp_refers_to,
                "file_duration": self.site_profile.file_duration,
            },
        )
        metadata.setdefault(
            "instruments",
            {
                "sonic_model": instrument_layout.get("sonic_mount", ""),
                "analyzer_model": instrument_layout.get("analyzer_mount", ""),
                "sonic_serial": "",
                "analyzer_serial": "",
                "sonic_manufacturer": "",
                "analyzer_manufacturer": "",
                "sonic_firmware": "",
                "analyzer_firmware": "",
                "sonic_instrument_id": "",
                "analyzer_instrument_id": "",
                "mount_description": instrument_layout.get("layout_note", ""),
                "geometry_detail": "",
            },
        )
        metadata.setdefault(
            "raw_file_description",
            {
                "source_name": overview.get("project_name", ""),
                "source_type": "hf_frame",
                "file_pattern": payload.get("output_template", {}).get("file_pattern", ""),
                "timestamp_column": "timestamp",
                "timezone": timing.get("timezone", self.site_profile.timezone),
                "notes": overview.get("notes", ""),
                "column_mappings_json": "[]",
            },
        )
        metadata.setdefault(
            "raw_file_settings",
            {
                "sample_hz": timing.get("sample_hz", 10.0),
                "delimiter": ",",
                "decimal": ".",
                "header_rows": 1,
                "encoding": "utf-8",
                "missing_tokens": ",NA,NaN",
            },
        )
        metadata.setdefault(
            "biomet_source",
            {
                "source_mode": biomet_doc.get("source_mode", "none"),
                "source_path": biomet_doc.get("source_path", ""),
                "time_column": biomet_doc.get("time_column", "timestamp"),
                "aggregation_method": biomet_doc.get("aggregation_method", "mean"),
                "fields": ",".join(biomet_doc.get("fields", [])),
                "directory_glob": biomet_doc.get("directory_glob", "*.csv"),
                "notes": biomet_doc.get("notes", ""),
            },
        )
        metadata.setdefault(
            "dynamic_metadata",
            {
                "source_path": dynamic_doc.get("source_path", ""),
                "start_column": dynamic_doc.get("start_column", "start_time"),
                "end_column": dynamic_doc.get("end_column", "end_time"),
                "timezone": dynamic_doc.get("timezone", self.site_profile.timezone),
                "records": dynamic_doc.get("records", []),
            },
        )
        metadata.setdefault(
            "alternative_metadata",
            {
                "active_profile": active_profile_doc.get("profile_name", self.project_profile.code or "default"),
                "available_profiles": self.metadata_store.list_alternative_metadata(),
            },
        )
        return payload

    def _parse_column_mappings(self, text: str) -> list[RawColumnMapping]:
        if not str(text).strip():
            return []
        try:
            payload = json.loads(str(text))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [RawColumnMapping.from_dict(dict(item)) for item in payload if isinstance(item, dict)]

    def _column_mappings_to_text(self, mappings: list[RawColumnMapping]) -> str:
        return json.dumps([asdict(item) for item in mappings], ensure_ascii=False, indent=2)

    def _split_csv_values(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() or item == ""]
        return [item.strip() for item in str(value).split(",") if item.strip() or item == ""]

    def _coerce_optional_float(self, value: object, fallback: float | None = None) -> float | None:
        if value in (None, ""):
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def new_project_workspace(self) -> None:
        workspace = self._build_default_project_workspace(template_name="空白起步模板")
        workspace["overview"]["project_name"] = ""
        workspace["overview"]["project_code"] = ""
        workspace["overview"]["principal"] = ""
        workspace["overview"]["status"] = "新建"
        workspace["overview"]["notes"] = "请先补齐项目、站点、布设与采样链路信息，再执行完整性检查。"
        workspace["site_info"]["station_name"] = ""
        workspace["site_info"]["station_code"] = ""
        workspace["site_info"]["location"] = ""
        workspace["instrument_layout"]["layout_note"] = ""
        workspace["sampling_chain"]["chain_note"] = ""
        self.project_workspace = workspace
        self.project_nav_section = "overview"
        self._append_log("info", "已新建空白项目工作区，可按目录逐项补齐参数。")
        self.project_changed.emit()
        self.selection_changed.emit()

    def import_project_template(self) -> None:
        self.project_workspace = self._build_default_project_workspace(template_name="草地通量站模板")
        self._append_log("info", "已导入项目模板，可继续按现场情况调整参数。")
        self.project_changed.emit()

    def duplicate_project_workspace(self) -> None:
        duplicated = deepcopy(self.project_workspace)
        overview = duplicated.setdefault("overview", {})
        overview["project_name"] = f"{overview.get('project_name', '新项目')} - 副本"
        overview["project_code"] = f"{overview.get('project_code', 'PRJ-001')}-COPY"
        self.project_workspace = duplicated
        self._append_log("info", "已复制当前项目配置，建议随后调整项目编号和站点信息。")
        self.project_changed.emit()

    def project_completeness_report(self) -> dict:
        state = self._ensure_metadata_workspace(deepcopy(self.project_workspace))
        metadata_report = metadata_completeness(self.metadata_bundle())
        checks = [
            ("项目名称", bool(state["overview"].get("project_name"))),
            ("项目编号", bool(state["overview"].get("project_code"))),
            ("站点名称", bool(state["site_info"].get("station_name"))),
            ("站点位置", bool(state["site_info"].get("location"))),
            ("分析仪布设高度", bool(state["instrument_layout"].get("analyzer_height_m"))),
            ("超声布设高度", bool(state["instrument_layout"].get("sonic_height_m"))),
            ("采样管长", bool(state["sampling_chain"].get("tube_length_m"))),
            ("流量设置", bool(state["sampling_chain"].get("flow_lpm"))),
            ("采样频率", bool(state["timing"].get("sample_hz"))),
            ("输出模板", bool(state["output_template"].get("template_name"))),
            ("运行模板", bool(state["runtime_template"].get("template_name"))),
        ]
        ui_score = int(sum(1 for _name, ok in checks if ok) / max(1, len(checks)) * 100)
        score = int(round((ui_score + metadata_report["score"]) / 2))
        missing = [name for name, ok in checks if not ok] + [f"metadata:{name}" for name in metadata_report["missing_items"]]
        notes = {
            "overview": "项目概览决定数据归档位置、模板来源和后续运行身份。",
            "site_info": "站点基础信息会影响报告抬头、元数据和后续处理上下文。",
            "instrument_layout": "仪器布设决定传感器相对关系，后续 lag 和修正步骤都会引用。",
            "sampling_chain": "采样链路会影响响应时间、损耗评估和伴热策略判断。",
            "timing": "时间与采样决定窗口划分、对齐方式和高频数据重建方式。",
            "output_template": "输出模板影响导出字段、文件命名和报告抬头。",
            "runtime_template": "运行模板决定上线前预检查、归档和回放策略。",
        }
        risks = []
        if not state["sampling_chain"].get("heat_traced") and float(state["sampling_chain"].get("tube_length_m") or 0.0) > 15.0:
            risks.append("采样管路较长但未启用伴热，潮湿环境下可能增加冷凝风险。")
        if float(state["instrument_layout"].get("height_delta_m") or 0.0) > 0.8:
            risks.append("分析仪与超声安装高度差偏大，建议确认后续时滞和空间代表性设置。")
        if int(state["timing"].get("sample_hz") or 0) < 10:
            risks.append("当前采样频率偏低，可能限制后续湍流与谱分析质量。")
        if not risks:
            risks.append("当前配置整体可用，但仍建议在上线前执行一次完整性检查。")
        return {
            "score": score,
            "missing_items": missing,
            "parameter_note": notes.get(self.project_nav_section, notes["overview"]),
            "risks": risks,
            "metadata_score": metadata_report["score"],
            "metadata_missing_items": metadata_report["missing_items"],
        }

    def save_ec_processing(self, payload: dict) -> None:
        self.ec_processing = deepcopy(payload)
        self._sync_ec_processing_workspace_from_state()
        self._append_log("info", "EC 处理配置已保存。")
        self.processing_changed.emit()

    def restore_default_ec_processing(self) -> None:
        self.ec_processing = self._build_default_ec_processing()
        self.ec_processing_workspace = self._build_default_ec_processing_workspace()
        self._sync_ec_processing_workspace_from_state()
        self._append_log("info", "已恢复默认 EC 处理设置。")
        self.processing_changed.emit()

    def save_ec_template(self) -> None:
        self._append_log("info", "已保存当前 EC 处理模板，可在后续项目中复用。")
        self.processing_changed.emit()

    def run_ec_processing(self, *, precheck_only: bool = False) -> dict:
        rows = self._collect_rp_rows()
        config_snapshot = self._rp_config_snapshot(precheck_only=precheck_only)
        run_cfg = self.ec_processing.get("run", {})
        result = self.ec_rp_pipeline.run(
            rows=rows,
            project=self.project_profile,
            site=self.site_profile,
            config=config_snapshot,
            data_source=str(run_cfg.get("data_source", "runtime_buffer")),
            time_range=str(run_cfg.get("time_range", "current_window")),
        )
        self.rp_runs = [row for row in self.rp_runs if row.run_id != result.run_id]
        self.rp_runs.insert(0, result)
        self.rp_runs.sort(key=lambda row: row.created_at, reverse=True)
        self._sync_ec_processing_workspace_from_result(result, precheck_only=precheck_only)

        selected = self.selected_device()
        if result.summary.get("status") == "empty":
            message = str(result.summary.get("message", "Not enough HF data to produce an RP result."))
        else:
            mode = "预检查" if precheck_only else "正式运行"
            message = f"{mode}完成，已生成 {len(result.windows)} 个 RP 窗口结果。"
        self._append_log("info", message)
        self._push_event(
            device_uid=selected.config.uid if selected else "workspace",
            device_id=selected.config.device_id if selected else "N/A",
            severity="info",
            title="EC RP 结果已刷新",
            message=message,
            category="ec_processing",
        )
        self.processing_changed.emit()
        return {"message": message}

    def ec_processing_report(self) -> dict:
        step = self.ec_processing["steps"][self.ec_nav_step]
        summary = self.ec_processing_workspace.get("summary", {})
        section = self.ec_processing_workspace.get("sections", {}).get(self.ec_nav_step, {})
        status = str(summary.get("status", "empty"))
        score = 95 if status == "ok" else (58 if status == "empty" else 70)
        risks = list(section.get("risks", []))
        if not risks:
            risks = [str(summary.get("message", "No RP result is available yet."))]
        return {
            "score": score,
            "current_method": step.get("method", "标准方法"),
            "applicable": step.get("applicable", "适用于常规涡动协方差处理场景。"),
            "recommended": step.get("recommended", "优先使用推荐参数，必要时再进行工程师级调整。"),
            "risks": risks,
        }

    def save_spectral_qc_workspace(self, payload: dict) -> None:
        self.spectral_qc_workspace["run"].update(deepcopy(payload.get("run", {})))
        self.spectral_qc_workspace["sections"].update(deepcopy(payload.get("sections", {})))
        self._append_log("info", "谱修正与 QC 配置已保存。")
        self.spectral_qc_changed.emit()

    def restore_default_spectral_qc(self) -> None:
        active_run = self.current_spectral_run()
        export_status = self.spectral_qc_workspace.get("run", {}).get("export_status", "尚未导出证据包")
        self.spectral_qc_workspace = self._build_default_spectral_qc_workspace()
        self.spectral_qc_workspace["run"]["export_status"] = export_status
        if active_run is not None:
            self._sync_spectral_workspace_from_result(active_run)
        self.spectral_qc_nav_section = "overview"
        self._append_log("info", "已恢复默认谱修正与 QC 设置。")
        self.spectral_qc_changed.emit()
        self.selection_changed.emit()

    def save_spectral_qc_template(self) -> None:
        self._append_log("info", "已保存当前谱修正与 QC 模板，可在后续批次中复用。")
        self.spectral_qc_changed.emit()

    def run_spectral_qc(self, *, qc_only: bool = False) -> dict:
        rows = self._collect_spectral_rows()
        workspace_run = self.spectral_qc_workspace.setdefault("run", {})
        config_snapshot = self._spectral_config_snapshot()
        result = self.ec_fcc_pipeline.run(
            rows=rows,
            project=self.project_profile,
            site=self.site_profile,
            config=config_snapshot,
            data_source=str(workspace_run.get("data_source", "runtime_buffer")),
            time_range=str(workspace_run.get("time_range", "current_window")),
            qc_only=qc_only,
        )
        self.run_result_store.save_spectral_run(result)
        self.spectral_runs = [row for row in self.spectral_runs if row.run_id != result.run_id]
        self.spectral_runs.insert(0, result)
        self.spectral_runs.sort(key=lambda row: row.created_at, reverse=True)
        self.latest_batch_compare = None
        self.report_center_workspace["batch_compare"] = self._empty_batch_compare_payload(run_result=result)
        self._sync_spectral_workspace_from_result(result)
        self._sync_report_center_from_results()
        workspace_run["last_result_status"] = str(result.summary.get("status", "unknown"))
        message = (
            "QC summary generated. Review windows and evidence export next."
            if qc_only and result.windows
            else ("Not enough HF data to produce a usable spectral result." if not result.windows else "Spectral analysis completed and real results were refreshed.")
        )
        self._append_log("info", message)
        self.report_changed.emit()
        self.spectral_qc_changed.emit()
        return {"message": message}

    def export_spectral_evidence(self) -> dict:
        run_result = self.current_spectral_run()
        if run_result is None:
            raise RuntimeError("No spectral result is available for evidence export yet.")
        config_snapshot = self._spectral_config_snapshot()
        manifest = self.evidence_exporter.export_spectral_qc_evidence(
            run_result=run_result,
            config_snapshot=config_snapshot,
            project=self.project_profile,
            site=self.site_profile,
        )
        self.run_result_store.save_evidence_manifest(manifest)
        self.latest_evidence_manifest = manifest
        run_result.artifacts["evidence_bundle"] = manifest.to_dict()
        self.run_result_store.save_spectral_run(run_result)
        self.spectral_qc_workspace.setdefault("run", {})["export_status"] = manifest.summary_text
        self.report_center_workspace["export_status"] = manifest.summary_text
        self._sync_report_center_from_results()
        self._append_log("info", "Spectral QC evidence bundle exported.")
        self.report_changed.emit()
        self.spectral_qc_changed.emit()
        return {"message": manifest.summary_text}

    def spectral_qc_report(self) -> dict:
        run_result = self.current_spectral_run()
        current_window = self.current_window_result()
        section_notes = {
            "overview": "先看总体风险与异常分布，再决定是否深入到单窗复核。",
            "lag_phase": "lag 峰值是否集中，决定了后续相位与通量解释是否可靠。",
            "power_spectrum": "高频端滚降过快时，修正因子通常会变大。",
            "cross_spectrum": "互谱若在主能量带失配，往往意味着采样链路或相位存在问题。",
            "ogive": "Ogive 平台收敛慢，通常表示窗口不稳或低频尚未闭合。",
            "transfer_function": "传递函数让用户看到修正来自哪里，而不是只看到一个倍数。",
            "correction_factor": "修正因子大并不一定错误，但必须能追溯到频谱损失来源。",
            "qc_overview": "QC 总览适合快速定位问题窗口，再进入明细核查。",
            "window_detail": "窗口明细用于把异常类型、质量等级和证据联动起来。",
        }
        if run_result is None:
            return {
                "section": self.spectral_qc_nav_section,
                "section_note": section_notes.get(self.spectral_qc_nav_section, section_notes["overview"]),
                "lag_confidence": "--",
                "high_freq_loss_risk": "未知",
                "good_windows": 0,
                "attention_windows": 0,
                "current_window": "未运行谱分析",
                "current_grade": "--",
                "recent_reason": "请先运行谱分析以生成真实谱结果。",
                "correction_factor": "--",
                "risks": ["当前还没有可用的谱分析批次。"],
                "actions": ["先运行谱分析，再查看 lag、互谱、Ogive 与 QC 条带。"],
            }

        summary = run_result.summary
        window_label = self._window_label(current_window) if current_window else "未选择"
        risks = [
            f"平均 lag 可信度：{self._format_confidence(float(summary.get('average_lag_confidence', 0.0)))}。",
            f"高频损失风险：{summary.get('high_freq_loss_risk', '--')}。",
            f"当前窗口 {window_label} 的最近异常原因为“{current_window.reason if current_window else '暂无'}”。",
        ]
        actions = [
            "先核对协方差峰值与预期 lag 是否一致，再决定是否扩大搜索窗口。",
            "若修正因子持续大于 1.20，优先复核采样链路、截止频率与滤波设置。",
            "对 B/C 级窗口先看异常类型，再决定是剔除还是保留为需关注样本。",
        ]
        return {
            "section": self.spectral_qc_nav_section,
            "section_note": section_notes.get(self.spectral_qc_nav_section, section_notes["overview"]),
            "lag_confidence": self._format_confidence(float(summary.get("average_lag_confidence", 0.0))),
            "high_freq_loss_risk": summary.get("high_freq_loss_risk", "--"),
            "good_windows": int(summary.get("good_window_count", 0)),
            "attention_windows": int(summary.get("attention_window_count", 0)),
            "current_window": window_label,
            "current_grade": current_window.qc_grade if current_window else "--",
            "recent_reason": current_window.reason if current_window else "暂无异常",
            "correction_factor": f"{current_window.correction_factor:.2f}" if current_window else "--",
            "risks": risks,
            "actions": actions,
        }

    def refresh_report_center(self) -> dict:
        if str(self.report_center_workspace.get("selected_report", "")) == "benchmark_cockpit":
            return self.rerun_benchmark_cockpit(trigger="refresh")
        self.report_center_workspace.setdefault("filters", {})["project"] = self.project_profile.name or "当前项目"
        self._sync_report_center_from_results(mark_refreshed=True)
        self._append_log("info", "报告中心已刷新当前项目与批次视图。")
        self.report_changed.emit()
        return {"message": "当前项目与批次视图已刷新。"}

    def generate_report_center_report(self) -> dict:
        self._sync_report_center_from_results(mark_generated=True)
        self._append_log("info", "报告中心已生成新的汇总报告。")
        self.report_changed.emit()
        return {"message": "已生成新的报告草稿，可继续导出或批次对比。"}

    def rerun_benchmark_cockpit(
        self,
        *,
        reference_id: str | None = None,
        flux_rel_threshold: float | None = None,
        lag_abs_threshold_s: float | None = None,
        trigger: str = "rerun",
    ) -> dict:
        benchmark_state = dict(self._effective_benchmark_config())
        if reference_id is not None:
            benchmark_state["reference_id"] = reference_id.strip()
        if flux_rel_threshold is not None:
            benchmark_state["flux_rel_threshold"] = float(flux_rel_threshold)
        if lag_abs_threshold_s is not None:
            benchmark_state["lag_abs_threshold_s"] = float(lag_abs_threshold_s)
        if benchmark_state.get("reference_id"):
            benchmark_state["status"] = "active"
        self.report_center_workspace["benchmark"] = benchmark_state
        rerun_result = self.run_ec_processing(precheck_only=False)
        self._sync_report_center_from_results(mark_refreshed=True)
        export_message = ""
        if self.current_rp_run() is not None:
            export_result = self.export_current_report()
            export_message = f" {export_result['message']}"
        self._append_log("info", f"Benchmark cockpit {trigger} executed against the RP pipeline.")
        self.report_changed.emit()
        return {"message": f"{rerun_result['message']}{export_message}".strip()}

    def export_current_report(self) -> dict:
        report_key = str(self.report_center_workspace.get("selected_report", "run_summary"))
        reports = self.report_center_workspace.get("reports", {})
        current = reports.get(report_key, {})
        spectral_result = self.current_spectral_run()
        rp_result = self.current_rp_run()
        if spectral_result is not None and not spectral_result.artifacts.get("evidence_bundle"):
            evidence_manifest = self.evidence_exporter.export_spectral_qc_evidence(
                run_result=spectral_result,
                config_snapshot=self._spectral_config_snapshot(),
                project=self.project_profile,
                site=self.site_profile,
            )
            self.run_result_store.save_evidence_manifest(evidence_manifest)
            self.latest_evidence_manifest = evidence_manifest
            spectral_result.artifacts["evidence_bundle"] = evidence_manifest.to_dict()
            self.run_result_store.save_spectral_run(spectral_result)
        export_path = export_report_snapshot(
            runtime_root=self.runtime_root,
            report_key=report_key,
            run_id=spectral_result.run_id if spectral_result else (rp_result.run_id if rp_result else None),
            report_payload=current,
        )
        bundle = self.result_exporter.export_minimal_bundle(
            rp_result=rp_result,
            spectral_result=spectral_result,
            rp_config_snapshot=self._rp_config_snapshot(precheck_only=False),
            spectral_config_snapshot=self._spectral_config_snapshot(),
            project=self.project_profile,
            site=self.site_profile,
            report_payload=current,
            report_key="report_snapshot",
            full_output_mode=str(self.ec_processing.get("steps", {}).get("output", {}).get("full_output_mode", "only_available")),
        )
        formal_report = export_formal_report(
            runtime_root=self.runtime_root,
            project_snapshot={
                "profile": asdict(self.project_profile),
                "workspace": deepcopy(self.project_workspace),
            },
            site_snapshot=asdict(self.site_profile),
            device_snapshots=[
                {
                    "label": entry.config.label,
                    "port": entry.config.port,
                    "device_id": entry.config.device_id,
                    "status": "在线" if entry.runtime.connected else "离线",
                }
                for entry in self.devices.values()
            ],
            rp_result=rp_result,
            spectral_result=spectral_result,
            eddypro_compare=deepcopy(self.report_center_workspace.get("eddypro_compare", {})),
            attribution_result=deepcopy(self.report_center_workspace.get("eddypro_attribution", {})),
            rp_config_snapshot=self._rp_config_snapshot(precheck_only=False),
            spectral_config_snapshot=self._spectral_config_snapshot(),
            latest_export_status=str(self.report_center_workspace.get("export_status", "尚未导出")),
            result_bundle=bundle,
        )
        delivery_package = export_delivery_package(
            runtime_root=self.runtime_root,
            formal_report=formal_report,
            result_bundle=bundle,
            evidence_bundle=dict(spectral_result.artifacts.get("evidence_bundle", {})) if spectral_result is not None else {},
            compare_manifest=deepcopy(self.latest_eddypro_compare_manifest or {}),
            attribution_result=deepcopy(self.report_center_workspace.get("eddypro_attribution", {})),
            current_batch_id=spectral_result.run_id if spectral_result else (rp_result.run_id if rp_result else ""),
        )
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        export_status_text = f"交付包已导出（{timestamp}）：{delivery_package['export_root']}"
        self.report_center_workspace["export_status"] = export_status_text
        file_info = current.setdefault("file_info", {})
        file_info["状态"] = "已导出"
        file_info["最近导出"] = timestamp
        file_info["目标文件"] = str(export_path)
        file_info["结果包目录"] = str(bundle["export_root"])
        file_info["正式报告HTML"] = str(formal_report["files"]["html"])
        file_info["正式报告快照"] = str(formal_report["files"]["snapshot"])
        file_info["正式报告Manifest"] = str(formal_report["files"]["manifest"])
        file_info["交付包目录"] = str(delivery_package["export_root"])
        file_info["交付包Manifest"] = str(delivery_package["files"]["package_manifest"])
        file_info["交付包README"] = str(delivery_package["files"]["readme"])
        file_info["交付包Audit"] = str(delivery_package["files"]["delivery_audit"])
        file_info["交付包ZIP"] = str(delivery_package["files"]["zip"])
        if spectral_result is not None:
            report_exports = spectral_result.artifacts.setdefault("report_exports", {})
            report_exports[report_key] = {"path": str(export_path), "exported_at": timestamp}
            report_exports["formal_report"] = {
                "html": str(formal_report["files"]["html"]),
                "snapshot": str(formal_report["files"]["snapshot"]),
                "manifest": str(formal_report["files"]["manifest"]),
                "pdf_status": str(formal_report.get("pdf_status", "fallback_html_only")),
                "exported_at": timestamp,
            }
            report_exports["delivery_package"] = {
                "export_root": str(delivery_package["export_root"]),
                "package_manifest": str(delivery_package["files"]["package_manifest"]),
                "readme": str(delivery_package["files"]["readme"]),
                "delivery_audit": str(delivery_package["files"]["delivery_audit"]),
                "zip": str(delivery_package["files"]["zip"]),
                "exported_at": timestamp,
            }
            result_exports = spectral_result.artifacts.setdefault("result_exports", {})
            result_exports["latest"] = {
                "export_root": str(bundle["export_root"]),
                "summary_text": str(bundle["summary_text"]),
                "files": dict(bundle["files"]),
                "exported_at": timestamp,
            }
            self.run_result_store.save_spectral_run(spectral_result)
        if rp_result is not None:
            rp_report_exports = rp_result.artifacts.setdefault("report_exports", {})
            rp_report_exports[report_key] = {"path": str(export_path), "exported_at": timestamp}
            rp_report_exports["formal_report"] = {
                "html": str(formal_report["files"]["html"]),
                "snapshot": str(formal_report["files"]["snapshot"]),
                "manifest": str(formal_report["files"]["manifest"]),
                "pdf_status": str(formal_report.get("pdf_status", "fallback_html_only")),
                "exported_at": timestamp,
            }
            rp_report_exports["delivery_package"] = {
                "export_root": str(delivery_package["export_root"]),
                "package_manifest": str(delivery_package["files"]["package_manifest"]),
                "readme": str(delivery_package["files"]["readme"]),
                "delivery_audit": str(delivery_package["files"]["delivery_audit"]),
                "zip": str(delivery_package["files"]["zip"]),
                "exported_at": timestamp,
            }
            rp_result.artifacts.setdefault("result_exports", {})["latest"] = {
                "export_root": str(bundle["export_root"]),
                "summary_text": str(bundle["summary_text"]),
                "files": dict(bundle["files"]),
                "exported_at": timestamp,
            }
        self._sync_report_center_from_results()
        workspace_reports = self.report_center_workspace.setdefault("reports", {})
        workspace_current = workspace_reports.setdefault(report_key, current)
        workspace_current.setdefault("file_info", {}).update(file_info)
        self.report_center_workspace["export_status"] = export_status_text
        self._append_log("info", f"已导出正式报告与真实结果包：{current.get('title', '报告中心')}")
        self.report_changed.emit()
        return {"message": self.report_center_workspace["export_status"]}

    def export_report_evidence(self) -> dict:
        result = self.export_spectral_evidence()
        self._append_log("info", "报告中心证据包已同步导出。")
        return result

    def compare_report_batches(self) -> dict:
        current = self.current_spectral_run()
        compare = self._previous_spectral_run(current.run_id if current else None)
        if current is None or compare is None:
            self.latest_batch_compare = None
            self.report_center_workspace["batch_compare"] = self._empty_batch_compare_payload(current=current, compare=compare)
            self._sync_report_center_from_results()
            self.report_changed.emit()
            return {"message": "Not enough real batches are available yet; prepared an empty compare state."}
        result = self._compare_spectral_runs(current, compare)
        self.latest_batch_compare = result
        self.report_center_workspace["batch_compare"] = result.to_dict()
        self._sync_report_center_from_results()
        self._append_log("info", f"Batch compare target updated: {result.compare_batch}")
        self.report_changed.emit()
        return {"message": f"Compared with {result.compare_batch}."}

    def report_center_report(self) -> dict:
        self._sync_report_center_from_results()
        workspace = self.report_center_workspace
        reports = workspace.get("reports", {})
        report_key = str(workspace.get("selected_report", "run_summary"))
        current = reports.get(report_key, {})
        summary = workspace.get("summary", {})
        return {
            "view_mode": workspace.get("filters", {}).get("view_mode", "工程诊断"),
            "report_key": report_key,
            "title": current.get("title", "报告"),
            "source": current.get("source", f"{self.project_profile.name} / 当前批次"),
            "updated_at": current.get("updated_at", summary.get("last_generated_at", "--")),
            "export_status": workspace.get("export_status", "尚未导出"),
            "export_options": current.get("export_options", []),
            "file_info": current.get("file_info", {}),
            "versions": current.get("versions", []),
            "usage": current.get("usage", []),
            "conclusions": current.get("conclusions", []),
            "batch_compare": workspace.get("batch_compare", {}),
            "eddypro_compare": workspace.get("eddypro_compare", {}),
            "eddypro_attribution": workspace.get("eddypro_attribution", {}),
        }

    def current_eddypro_compare_result(self) -> EddyProCompareResult | None:
        return self.latest_eddypro_compare_result

    def current_eddypro_attribution_result(self) -> CompareAttributionResult | None:
        return self.latest_eddypro_attribution_result

    def compare_with_eddypro(self, reference_dir: Path | str, mapping: dict | None = None) -> dict:
        current_export_dir = self._latest_result_export_dir()
        if current_export_dir is None:
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            self.report_center_workspace["eddypro_compare"] = self._empty_eddypro_compare_payload()
            self.report_center_workspace["eddypro_attribution"] = self._empty_eddypro_attribution_payload()
            self._sync_report_center_from_results()
            self.report_changed.emit()
            return {"message": "当前还没有可用于对标的真实结果导出目录。"}

        reference_root = Path(reference_dir)
        if not reference_root.exists():
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            self.report_center_workspace["eddypro_compare"] = self._empty_eddypro_compare_payload()
            self.report_center_workspace["eddypro_attribution"] = self._empty_eddypro_attribution_payload()
            self._sync_report_center_from_results()
            self.report_changed.emit()
            return {"message": f"EddyPro 参考结果目录不存在：{reference_root}"}

        try:
            comparator = EddyProComparator(self.runtime_root)
            current = comparator.load_current_results(current_export_dir)
            reference = comparator.load_reference_results(reference_root, mapping=mapping)
            result = comparator.compare(current, reference)
            manifest = comparator.export(result, comparator.default_export_root())
        except FileNotFoundError as exc:
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            self.report_center_workspace["eddypro_compare"] = self._empty_eddypro_compare_payload()
            self.report_center_workspace["eddypro_attribution"] = self._empty_eddypro_attribution_payload()
            self._sync_report_center_from_results()
            self.report_changed.emit()
            return {"message": str(exc)}

        self.latest_eddypro_compare_result = result
        self.latest_eddypro_compare_manifest = manifest
        self.latest_eddypro_attribution_result = self._build_eddypro_attribution_result(result)
        self.report_center_workspace["eddypro_compare"] = self._eddypro_compare_payload_from_result(result, manifest)
        self.report_center_workspace["eddypro_attribution"] = self._eddypro_attribution_workspace_state()
        self._sync_report_center_from_results()
        self._append_log("info", f"EddyPro 对标已更新：{result.compare_id}")
        self.report_changed.emit()
        return {"message": f"EddyPro 对标完成：{result.compare_id}"}

    def _load_persisted_results(self) -> None:
        self.spectral_runs = self.run_result_store.list_recent_runs()
        self.latest_evidence_manifest = self.run_result_store.latest_evidence_manifest()
        self.latest_batch_compare = None
        self._load_latest_eddypro_compare()
        if self.spectral_runs:
            self._sync_spectral_workspace_from_result(self.spectral_runs[0])
        else:
            self.spectral_qc_workspace = self._build_default_spectral_qc_workspace()
        self._sync_ec_processing_workspace_from_state()
        self._sync_report_center_from_results()

    def current_rp_run(self) -> RPRunResult | None:
        return self.rp_runs[0] if self.rp_runs else None

    def current_rp_window(self) -> WindowRPResult | None:
        run = self.current_rp_run()
        if run is None or not run.windows:
            return None
        selected_id = self.ec_processing_workspace.get("selected_window_id")
        if selected_id:
            for window in run.windows:
                if window.window_id == selected_id:
                    return window
        return run.windows[0]

    def _effective_benchmark_config(self) -> dict[str, object]:
        defaults = dict(self._build_default_report_center_workspace()["benchmark"])
        effective = dict(defaults)
        current = self.current_rp_run()
        if current is not None and isinstance(current.summary, dict):
            effective["status"] = current.summary.get("benchmark_status", effective.get("status", ""))
            effective["target"] = current.summary.get("benchmark_target", effective.get("target", "eddypro_v7"))
            effective["reference_id"] = current.summary.get("benchmark_reference_id", effective.get("reference_id", ""))
            current_thresholds = current.summary.get("benchmark_thresholds", {})
            if isinstance(current_thresholds, dict):
                effective.update({key: value for key, value in current_thresholds.items() if value not in (None, "")})
        workspace_config = dict(self.report_center_workspace.get("benchmark", {}))
        effective.update({key: value for key, value in workspace_config.items() if value not in (None, "")})
        return effective

    def _infer_timezone_offset_hours(self) -> float:
        timezone_name = str(self.site_profile.timezone or "").strip()
        if not timezone_name:
            return 0.0
        try:
            offset = datetime.now(ZoneInfo(timezone_name)).utcoffset()
        except Exception:
            return 0.0
        if offset is None:
            return 0.0
        return round(offset.total_seconds() / 3600.0, 2)

    def _network_output_snapshot(self) -> dict[str, object]:
        defaults = dict(self._build_default_report_center_workspace()["network_output"])
        workspace_network = dict(self.report_center_workspace.get("network_output", {}))
        current = self.current_rp_run()
        current_summary = current.summary if current is not None and isinstance(current.summary, dict) else {}
        timestamp_refers_to = str(
            workspace_network.get("timestamp_refers_to")
            or current_summary.get("fluxnet_timestamp_refers_to")
            or ("end" if "end" in str(self.site_profile.timestamp_refers_to or "").lower() else "start")
        )
        if "end" in timestamp_refers_to.lower():
            timestamp_refers_to = "end"
        else:
            timestamp_refers_to = "start"
        timezone_offset_hours = workspace_network.get("timezone_offset_hours", current_summary.get("fluxnet_timezone_offset_h"))
        if timezone_offset_hours in (None, ""):
            timezone_offset_hours = self._infer_timezone_offset_hours()
        gap_fill_value = workspace_network.get("gap_fill_value", current_summary.get("fluxnet_gap_fill_value", defaults["gap_fill_value"]))
        return {
            "schema_target": str(workspace_network.get("schema_target") or current_summary.get("schema_target") or defaults["schema_target"]),
            "timezone_offset_hours": float(timezone_offset_hours or 0.0),
            "timestamp_refers_to": timestamp_refers_to,
            "gap_fill_value": float(gap_fill_value or defaults["gap_fill_value"]),
        }

    def _fcc_measured_cospectra_snapshot(self) -> dict[str, object]:
        spectral_run = self.current_spectral_run()
        if spectral_run is None:
            return {"use_fcc_measured_cospectrum": False, "fcc_source_run_id": "", "fcc_measured_cospectra": []}
        cospectra: list[dict[str, object]] = []
        for window in spectral_run.windows:
            if len(window.cross_freq) < 8 or len(window.cross_value) < 8:
                continue
            cospectra.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "cross_freq": [float(value) for value in window.cross_freq],
                    "cross_value": [float(value) for value in window.cross_value],
                    "source_run_id": spectral_run.run_id,
                    "source_qc_grade": window.qc_grade,
                    "provenance_notes": list(window.provenance_notes),
                }
            )
        return {
            "use_fcc_measured_cospectrum": bool(cospectra),
            "fcc_source_run_id": spectral_run.run_id,
            "fcc_measured_cospectra": cospectra,
        }

    def _collect_rp_rows(self) -> list[NormalizedHFFrame]:
        selected = self.selected_device()
        rows = self.realtime_rows(device_uid=selected.config.uid) if selected else self.realtime_rows()
        if rows:
            return rows
        return self.selected_device_realtime_rows() if selected else []

    def _rp_config_snapshot(self, *, precheck_only: bool) -> dict:
        config = deepcopy(self.ec_processing.get("steps", {}))
        timing = deepcopy(self.project_workspace.get("timing", {}))
        selected = self.selected_device()
        footprint_step = dict(config.get("footprint", {}) or {})
        uncertainty_step = dict(config.get("uncertainty", {}) or {})
        spectral_step = dict(config.get("spectral_correction", {}) or {})
        method_compare_step = dict(config.get("method_compare", {}) or {})
        sample_hz = config.get("window_sampling", {}).get("sample_hz") or timing.get("sample_hz")
        if not sample_hz and selected is not None:
            sample_hz = selected.runtime.ftd_hz
        block_minutes = config.get("window_sampling", {}).get("window_minutes") or timing.get("block_minutes") or 30.0
        config["sample_hz"] = float(sample_hz or 10.0)
        config["block_minutes"] = float(block_minutes or 30.0)
        config["rotation_mode"] = str(config.get("rotation", {}).get("rotation_mode", "double"))
        config["detrend_mode"] = str(config.get("detrend", {}).get("detrend_mode", "block_mean"))
        config["density_correction_mode"] = str(config.get("density_correction", {}).get("correction_mode", "WPL"))
        config["lag_phase"] = {
            "search_window_s": float(config.get("lag", {}).get("search_window_s", 4.0) or 4.0),
            "expected_lag_s": float(config.get("lag", {}).get("expected_lag_s", 0.0) or 0.0),
            "strategy": str(config.get("lag", {}).get("lag_strategy", "covariance_max")),
        }
        absolute_limits_text = str(config.get("screening", {}).get("absolute_limits_text", "")).strip()
        config["screening"] = {
            "skewness_threshold": float(config.get("screening", {}).get("skewness_threshold", 2.0) or 2.0),
            "kurtosis_threshold": float(config.get("screening", {}).get("kurtosis_threshold", 7.0) or 7.0),
            "dropout_min_run": int(config.get("screening", {}).get("dropout_min_run", 10) or 10),
            "spike_sigma": float(config.get("screening", {}).get("spike_sigma", 5.0) or 5.0),
            "discontinuity_sigma": float(config.get("screening", {}).get("discontinuity_sigma", 8.0) or 8.0),
        }
        if absolute_limits_text:
            try:
                config["screening"]["absolute_limits"] = json.loads(absolute_limits_text)
            except (json.JSONDecodeError, ValueError):
                pass
        footprint_method = str(footprint_step.get("method", "kljun") or "kljun").strip()
        config["footprint"] = {
            "enabled": bool(footprint_step.get("enabled", footprint_method not in {"", "disabled"})),
            "method": footprint_method,
            "z_m": float(footprint_step.get("z_m", 3.0) or 3.0),
            "canopy_height_m": float(footprint_step.get("canopy_height_m", 5.0) or 5.0),
            "z0": float(footprint_step.get("z0", 0.12) or 0.12),
            "ol": float(footprint_step.get("ol", 0.0) or 0.0),
            "grid_enabled": bool(footprint_step.get("grid_enabled", True)),
            "grid_x_bins": int(footprint_step.get("grid_x_bins", 32) or 32),
            "grid_y_bins": int(footprint_step.get("grid_y_bins", 25) or 25),
            "grid_max_downwind_m": footprint_step.get("grid_max_downwind_m"),
            "grid_max_crosswind_m": footprint_step.get("grid_max_crosswind_m"),
        }
        uncertainty_method = str(
            uncertainty_step.get("method")
            or uncertainty_step.get("uncertainty_mode")
            or "mann_lenschow"
        ).strip()
        config["uncertainty"] = {
            "method": uncertainty_method,
            "integral_timescale_s": float(uncertainty_step.get("integral_timescale_s", 5.0) or 5.0),
            "confidence_level": float(uncertainty_step.get("confidence_level", 0.95) or 0.95),
        }
        spectral_method = str(spectral_step.get("method", "massman") or "massman").strip()
        fcc_cospectrum_snapshot = self._fcc_measured_cospectra_snapshot()
        config["spectral_correction"] = {
            "enabled": bool(spectral_step.get("enabled", spectral_method not in {"", "disabled"})),
            "method": spectral_method,
            "path_length_m": float(spectral_step.get("path_length_m", 0.15) or 0.15),
            "sensor_sep_m": float(spectral_step.get("sensor_sep_m", 0.20) or 0.20),
            "response_time_s": float(spectral_step.get("response_time_s", 0.1) or 0.1),
            "z_m": float(spectral_step.get("z_m", 3.0) or 3.0),
            "ol": float(spectral_step.get("ol", 0.0) or 0.0),
            "use_fcc_measured_cospectrum": bool(
                spectral_step.get("use_fcc_measured_cospectrum", True)
                and fcc_cospectrum_snapshot.get("use_fcc_measured_cospectrum", False)
            ),
            "fcc_source_run_id": str(fcc_cospectrum_snapshot.get("fcc_source_run_id", "")),
            "fcc_measured_cospectra": list(fcc_cospectrum_snapshot.get("fcc_measured_cospectra", [])),
        }
        config["method_compare"] = {
            "enabled": bool(method_compare_step.get("enabled", True)),
            "families": list(method_compare_step.get("families", ["footprint", "uncertainty", "spectral_correction"])),
            "deviation_threshold": float(method_compare_step.get("deviation_threshold", 0.25) or 0.25),
            "max_samples": int(method_compare_step.get("max_samples", 4096) or 4096),
            "footprint_methods": list(method_compare_step.get("footprint_methods", ["kljun", "kormann_meixner", "hsieh"])),
            "uncertainty_methods": list(method_compare_step.get("uncertainty_methods", ["mann_lenschow", "finkelstein_sims"])),
            "spectral_correction_methods": list(method_compare_step.get("spectral_correction_methods", ["massman", "horst", "ibrom", "fratini"])),
        }
        benchmark_config = self._effective_benchmark_config()
        if benchmark_config.get("reference_id"):
            benchmark_config["status"] = benchmark_config.get("status") or "active"
        config["benchmark"] = {
            "status": str(benchmark_config.get("status", "")),
            "target": str(benchmark_config.get("target", "eddypro_v7")),
            "reference_id": str(benchmark_config.get("reference_id", "")),
            "flux_rel_threshold": float(benchmark_config.get("flux_rel_threshold", 0.10)),
            "lag_abs_threshold_s": float(benchmark_config.get("lag_abs_threshold_s", 0.5)),
            "wpl_rel_threshold": float(benchmark_config.get("wpl_rel_threshold", 0.20)),
            "qc_grade_must_match": bool(benchmark_config.get("qc_grade_must_match", False)),
        }
        self.report_center_workspace["benchmark"] = dict(config["benchmark"])
        config["network_output"] = dict(self._network_output_snapshot())
        self.report_center_workspace["network_output"] = dict(config["network_output"])
        config["full_output_mode"] = str(config.get("output", {}).get("full_output_mode", "only_available"))
        config["run_mode"] = "precheck" if precheck_only else "standard"
        config["metadata_bundle"] = self.metadata_bundle().to_dict()
        config["project_context"] = {
            "project_name": self.project_profile.name,
            "project_code": self.project_profile.code,
            "site_name": self.site_profile.station_name,
            "site_code": self.site_profile.station_code,
        }
        return config

    def _sync_ec_processing_workspace_from_state(self) -> None:
        run = self.current_rp_run()
        if run is None:
            self.ec_processing_workspace = self._build_default_ec_processing_workspace()
            self.ec_processing_workspace["run"]["data_source"] = str(self.ec_processing.get("run", {}).get("data_source", ""))
            self.ec_processing_workspace["run"]["time_range"] = str(self.ec_processing.get("run", {}).get("time_range", ""))
            self.ec_processing_workspace["summary"]["message"] = "尚未生成真实 RP 结果。"
            return
        self._sync_ec_processing_workspace_from_result(run, precheck_only=self.ec_processing_workspace.get("run", {}).get("last_run_mode") == "precheck")

    def _sync_ec_processing_workspace_from_result(self, result: RPRunResult, *, precheck_only: bool) -> None:
        workspace = self._build_default_ec_processing_workspace()
        current_window = result.windows[0] if result.windows else None
        summary = workspace["summary"]
        summary.update(
            {
                "status": str(result.summary.get("status", "empty")),
                "message": str(result.summary.get("message", "")),
                "window_count": int(result.summary.get("window_count", len(result.windows))),
                "valid_window_count": int(result.summary.get("valid_window_count", 0)),
                "good_window_count": int(result.summary.get("good_window_count", 0)),
                "attention_window_count": int(result.summary.get("attention_window_count", 0)),
                "average_lag_seconds": float(result.summary.get("average_lag_seconds", 0.0) or 0.0),
                "average_lag_confidence": float(result.summary.get("average_lag_confidence", 0.0) or 0.0),
                "average_raw_flux": float(result.summary.get("average_raw_flux", 0.0) or 0.0),
                "average_density_corrected_flux": float(result.summary.get("average_density_corrected_flux", 0.0) or 0.0),
            }
        )
        workspace["run"].update(
            {
                "data_source": result.data_source,
                "time_range": result.time_range,
                "last_run_mode": "precheck" if precheck_only else "standard",
                "last_run_time": result.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "last_result_status": summary["status"],
                "message": summary["message"],
                "active_run_id": result.run_id,
            }
        )
        workspace["active_run_id"] = result.run_id
        workspace["selected_window_id"] = current_window.window_id if current_window else None
        workspace["windows"] = [window.to_dict() for window in result.windows]
        workspace["sections"] = self._build_ec_sections_from_result(result, current_window)
        self.ec_processing_workspace = workspace

    def _build_ec_sections_from_result(self, result: RPRunResult, current_window: WindowRPResult | None) -> dict:
        steps = deepcopy(self.ec_processing.get("steps", {}))
        summary = result.summary
        status = str(summary.get("status", "empty"))
        if current_window is None:
            empty_message = str(summary.get("message", "尚未生成真实 RP 结果。"))
            for key, step in steps.items():
                step["real_summary"] = empty_message
                step["intermediate"] = {}
                step["risks"] = [empty_message]
            return steps

        diagnostics = current_window.diagnostics or {}
        density_factor = float(diagnostics.get("density_correction_factor", 1.0))
        steps["window_sampling"]["real_summary"] = (
            f"生成 {len(result.windows)} 个窗口，当前窗口 {current_window.sample_count} 样本，连续性 {current_window.continuity_ratio:.1%}。"
        )
        steps["window_sampling"]["intermediate"] = {
            "sample_count": current_window.sample_count,
            "valid_sample_count": current_window.valid_sample_count,
            "continuity_ratio": current_window.continuity_ratio,
        }
        steps["window_sampling"]["risks"] = [f"当前结果状态：{status}", f"窗口缺失率 {current_window.missing_ratio:.1%}。"]

        steps["data_cleaning"]["real_summary"] = (
            f"有效样本 {current_window.valid_sample_count}/{current_window.sample_count}，缺失率 {current_window.missing_ratio:.1%}。"
        )
        steps["data_cleaning"]["intermediate"] = {
            "missing_ratio": current_window.missing_ratio,
            "valid_sample_count": current_window.valid_sample_count,
            "issues": diagnostics.get("issues", []),
        }
        steps["data_cleaning"]["removed_ratio"] = f"{current_window.missing_ratio * 100:.1f}%"
        steps["data_cleaning"]["risks"] = [current_window.reason]

        steps["lag"]["real_summary"] = f"lag={current_window.lag_seconds:.3f} s，confidence={current_window.lag_confidence:.2f}，strategy={diagnostics.get('lag_strategy', 'covariance_max')}。"
        steps["lag"]["intermediate"] = {
            "lag_seconds": current_window.lag_seconds,
            "lag_confidence": current_window.lag_confidence,
            "lag_strategy": diagnostics.get("lag_strategy", "covariance_max"),
            "lag_curve_x": diagnostics.get("lag_curve_x", []),
            "lag_curve_y": diagnostics.get("lag_curve_y", []),
            "screening_detail": diagnostics.get("screening_detail", {}),
            "screening_config": diagnostics.get("screening_config", {}),
        }
        steps["lag"]["risks"] = [current_window.reason]

        steps["screening"]["real_summary"] = (
            f"screening issues={len(diagnostics.get('issues', []))}，"
            f"skewness_threshold={diagnostics.get('screening_config', {}).get('skewness_threshold', 2.0)}，"
            f"kurtosis_threshold={diagnostics.get('screening_config', {}).get('kurtosis_threshold', 7.0)}，"
            f"spike_sigma={diagnostics.get('screening_config', {}).get('spike_sigma', 5.0)}，"
            f"discontinuity_sigma={diagnostics.get('screening_config', {}).get('discontinuity_sigma', 8.0)}，"
            f"dropout_min_run={diagnostics.get('screening_config', {}).get('dropout_min_run', 10)}。"
        )
        steps["screening"]["intermediate"] = {
            "screening_detail": diagnostics.get("screening_detail", {}),
            "screening_config": diagnostics.get("screening_config", {}),
            "diagnostics_issues": diagnostics.get("issues", []),
        }
        steps["screening"]["risks"] = [
            str(issue) for issue in diagnostics.get("issues", [])
        ] or ["窗口通过统计筛选。"]

        steps["rotation"]["real_summary"] = (
            f"请求旋转模式 {diagnostics.get('requested_rotation_mode', current_window.rotation_mode)}，"
            f"实际实现 {diagnostics.get('applied_rotation_impl', current_window.rotation_mode)}。"
        )
        steps["rotation"]["intermediate"] = {
            "rotation_mode": current_window.rotation_mode,
            "requested_rotation_mode": diagnostics.get("requested_rotation_mode", current_window.rotation_mode),
            "applied_rotation_impl": diagnostics.get("applied_rotation_impl", current_window.rotation_mode),
            "rotation_applied": diagnostics.get("rotation_applied", False),
            "rotation_reason": diagnostics.get("rotation_reason", ""),
        }
        steps["rotation"]["risks"] = [str(diagnostics.get("rotation_reason", current_window.reason))]

        steps["detrend"]["real_summary"] = f"当前去趋势模式为 {current_window.detrend_mode}。"
        steps["detrend"]["intermediate"] = {"detrend_mode": current_window.detrend_mode}
        steps["detrend"]["risks"] = [current_window.reason]

        steps["covariance"]["real_summary"] = (
            f"cov(w,co2)={current_window.cov_w_co2:.6f}，cov(w,h2o)={current_window.cov_w_h2o:.6f}。"
        )
        steps["covariance"]["intermediate"] = {
            "cov_w_co2": current_window.cov_w_co2,
            "cov_w_h2o": current_window.cov_w_h2o,
            "raw_flux": current_window.raw_flux,
        }
        steps["covariance"]["risks"] = [current_window.reason]

        steps["density_correction"]["real_summary"] = (
            f"主输出通量 {current_window.primary_flux:.6f}（来源={current_window.primary_flux_source}），"
            f"原始通量 {current_window.raw_flux:.6f}，密度修正后 {current_window.density_corrected_flux:.6f}，"
            f"混合比通量 {current_window.mixing_ratio_flux:.6f}，因子 {density_factor:.2f}x。"
        )
        steps["density_correction"]["intermediate"] = {
            "raw_flux": current_window.raw_flux,
            "mixing_ratio_flux": current_window.mixing_ratio_flux,
            "density_corrected_flux": current_window.density_corrected_flux,
            "primary_flux": current_window.primary_flux,
            "primary_flux_source": current_window.primary_flux_source,
            "density_correction_factor": density_factor,
            "density_correction_mode": diagnostics.get("density_correction_mode", "wpl"),
            "density_correction_reason": diagnostics.get("density_correction_reason", ""),
        }
        steps["density_correction"]["risks"] = [current_window.reason]

        steps["steadiness"]["real_summary"] = (
            f"当前窗口 QC={current_window.qc_grade}，异常类型 {current_window.anomaly_type}。"
        )
        steps["steadiness"]["intermediate"] = {
            "qc_grade": current_window.qc_grade,
            "anomaly_type": current_window.anomaly_type,
            "reason": current_window.reason,
        }
        steps["steadiness"]["risks"] = [current_window.reason]

        steps["turbulence"]["real_summary"] = "最小 RP 主链未输出独立 turbulence 指标，当前显示窗口级 QC 摘要。"
        turbulence_detail = current_window.turbulence_detail or {}
        steps["turbulence"]["real_summary"] = (
            f"u*={current_window.ustar or 0.0:.3f} m/s, score={current_window.turbulence_score or 0.0:.1f}, "
            f"status={turbulence_detail.get('status', 'unknown')}."
        )
        steps["turbulence"]["intermediate"] = {
            "ustar": current_window.ustar,
            "turbulence_score": current_window.turbulence_score,
            "detail": turbulence_detail,
        }
        steps["turbulence"]["risks"] = [str(turbulence_detail.get("reason", current_window.reason))]

        uncertainty_detail = current_window.uncertainty_detail or {}
        if "footprint" in steps:
            footprint_detail = dict(diagnostics.get("footprint_detail", {}) or {})
            footprint_contrib = dict(diagnostics.get("footprint_contribution_distances", {}) or {})
            steps["footprint"]["real_summary"] = (
                f"method={diagnostics.get('footprint_method', 'disabled')}, "
                f"peak={diagnostics.get('footprint_peak_distance_m', 0.0) or 0.0:.1f} m, "
                f"x50={footprint_contrib.get('x50', '--')} m."
            )
            steps["footprint"]["intermediate"] = {
                "method": diagnostics.get("footprint_method", ""),
                "peak_distance_m": diagnostics.get("footprint_peak_distance_m"),
                "offset_distance_m": diagnostics.get("footprint_offset_distance_m"),
                "contribution_distances": footprint_contrib,
                "footprint_2d_grid_status": diagnostics.get("footprint_2d_grid_status", ""),
                "footprint_2d_peak_downwind_m": diagnostics.get("footprint_2d_peak_downwind_m"),
                "footprint_2d_peak_crosswind_m": diagnostics.get("footprint_2d_peak_crosswind_m"),
                "footprint_2d_half_width_m": diagnostics.get("footprint_2d_half_width_m"),
                "detail": footprint_detail,
            }
            steps["footprint"]["risks"] = list(footprint_detail.get("limitations", []))[:3] or [current_window.reason]
        steps["uncertainty"]["real_summary"] = (
            f"method={diagnostics.get('uncertainty_method', uncertainty_detail.get('selected_method', 'composite_empirical'))}, "
            f"relative={float(uncertainty_detail.get('primary_flux_relative_uncertainty', uncertainty_detail.get('relative_uncertainty', 0.0)) or 0.0):.3f}, "
            f"band={float(uncertainty_detail.get('primary_flux_uncertainty_band', 0.0) or 0.0):.6f}."
        )
        steps["uncertainty"]["intermediate"] = dict(uncertainty_detail)
        steps["uncertainty"]["risks"] = [
            f"random_error={float(uncertainty_detail.get('primary_flux_random_error', 0.0) or 0.0):.6f}",
            f"ci=({uncertainty_detail.get('primary_flux_ci_lower', '--')}, {uncertainty_detail.get('primary_flux_ci_upper', '--')})",
            f"method={diagnostics.get('uncertainty_method', uncertainty_detail.get('selected_method', 'composite_empirical'))}",
        ]
        if "spectral_correction" in steps:
            spectral_detail = dict(diagnostics.get("spectral_correction_detail", {}) or {})
            measured_source = diagnostics.get("spectral_correction_measured_cospectrum_source", "")
            steps["spectral_correction"]["real_summary"] = (
                f"method={diagnostics.get('spectral_correction_method', 'disabled')}, "
                f"factor={float(diagnostics.get('spectral_correction_factor', 1.0) or 1.0):.3f}, "
                f"cospectrum={measured_source or 'disabled'}."
            )
            steps["spectral_correction"]["intermediate"] = {
                "method": diagnostics.get("spectral_correction_method", ""),
                "correction_factor": diagnostics.get("spectral_correction_factor"),
                "measured_cospectrum_enabled": diagnostics.get("spectral_correction_measured_cospectrum_enabled", False),
                "measured_cospectrum_used": diagnostics.get("spectral_correction_measured_cospectrum_used", False),
                "measured_cospectrum_source": measured_source,
                "cospectrum_match": diagnostics.get("spectral_correction_cospectrum_match", {}),
                "detail": spectral_detail,
            }
            steps["spectral_correction"]["risks"] = list(diagnostics.get("spectral_correction_limitations", []))[:3] or [current_window.reason]
        if "method_compare" in steps:
            method_compare = diagnostics.get("method_compare_summary", {})
            recommendations = diagnostics.get("method_compare_recommendations", {})
            steps["method_compare"]["real_summary"] = (
                f"enabled={bool(diagnostics.get('method_compare_enabled', False))}, "
                f"families={len(method_compare) if isinstance(method_compare, dict) else 0}, "
                f"flags={len(diagnostics.get('method_compare_deviation_flags', []) or [])}."
            )
            steps["method_compare"]["intermediate"] = {
                "method_compare_summary": method_compare,
                "method_compare_recommendations": recommendations,
                "method_compare_deviation_flags": diagnostics.get("method_compare_deviation_flags", []),
            }
            steps["method_compare"]["risks"] = [
                str(flag)
                for flag in diagnostics.get("method_compare_deviation_flags", [])[:3]
            ] or ["Method compare produced no high-deviation flags."]

        steps["output"]["real_summary"] = (
            f"当前运行 {result.run_id}，输出 {len(result.windows)} 个窗口结果，状态 {status}。"
        )
        steps["output"]["intermediate"] = {
            "run_id": result.run_id,
            "window_count": len(result.windows),
            "status": status,
            "full_output_mode": steps.get("output", {}).get("full_output_mode", "only_available"),
            "primary_flux_random_error": diagnostics.get("primary_flux_random_error"),
            "primary_flux_uncertainty_band": diagnostics.get("primary_flux_uncertainty_band"),
            "schema_target": diagnostics.get("schema_target", ""),
        }
        steps["output"]["risks"] = [summary.get("message", current_window.reason)]
        return steps

    def _spectral_config_snapshot(self) -> dict:
        config = deepcopy(self.spectral_qc_workspace.get("sections", {}))
        timing = deepcopy(self.project_workspace.get("timing", {}))
        selected_device = self.selected_device()
        sample_hz = timing.get("sample_hz")
        if not sample_hz and selected_device is not None:
            sample_hz = selected_device.runtime.ftd_hz
        config["timing"] = {
            "sample_hz": float(sample_hz or 10.0),
            "block_minutes": float(timing.get("block_minutes", 30.0) or 30.0),
            "timezone": str(timing.get("timezone") or self.site_profile.timezone),
        }
        config["sample_hz"] = config["timing"]["sample_hz"]
        config["instrument_layout"] = deepcopy(self.project_workspace.get("instrument_layout", {}))
        config["sampling_chain"] = deepcopy(self.project_workspace.get("sampling_chain", {}))
        config["metadata_bundle"] = self.metadata_bundle().to_dict()
        transfer_section = config.get("transfer_function", {})
        if isinstance(transfer_section, dict):
            transfer_section["model"] = transfer_section.get("model") or transfer_section.get("transfer_model") or "component_product"
            transfer_section["transfer_model"] = transfer_section["model"]
            config["transfer_function"] = transfer_section
        correction_section = config.get("correction_factor", {})
        if isinstance(correction_section, dict):
            correction_section["mode"] = correction_section.get("mode") or correction_section.get("correction_mode") or "provenance_weighted"
            correction_section["correction_mode"] = correction_section["mode"]
            config["correction_factor"] = correction_section
        config["project_context"] = {
            "project_name": self.project_profile.name,
            "site_name": self.site_profile.station_name,
            "site_code": self.site_profile.station_code,
        }
        return config

    def _sync_spectral_workspace_from_result(self, result: SpectralRunResult) -> None:
        selected_window_id = self.spectral_qc_workspace.get("selected_window_id")
        run = self.spectral_qc_workspace.setdefault("run", {})
        export_status = (
            result.artifacts.get("evidence_bundle", {}).get("summary_text")
            or run.get("export_status")
            or "尚未导出证据包"
        )
        run.update(
            {
                "data_source": result.data_source,
                "time_range": result.time_range,
                "last_run_mode": "仅生成 QC 摘要" if result.qc_only else "运行谱分析",
                "last_run_time": result.created_at.strftime("%Y-%m-%d %H:%M"),
                "export_status": export_status,
            }
        )
        summary = result.summary
        self.spectral_qc_workspace["summary"] = {
            "lag_confidence": self._format_confidence(float(summary.get("average_lag_confidence", 0.0))),
            "high_freq_loss_risk": str(summary.get("high_freq_loss_risk", "--")),
            "qc_good_windows": int(summary.get("good_window_count", 0)),
            "attention_windows": int(summary.get("attention_window_count", 0)),
        }
        provenance_notes: list[str] = []
        model_versions: list[str] = []
        for window in result.windows:
            provenance_notes.extend([str(note) for note in window.provenance_notes if str(note).strip()])
            if str(window.model_version).strip():
                model_versions.append(str(window.model_version).strip())
        self.spectral_qc_workspace["provenance_summary"] = {
            "average_tube_component": float(summary.get("average_tube_component", 1.0)),
            "average_separation_component": float(summary.get("average_separation_component", 1.0)),
            "average_path_component": float(summary.get("average_path_component", 1.0)),
            "average_phase_component": float(summary.get("average_phase_component", 1.0)),
            "average_correction_factor": float(summary.get("average_correction_factor", 1.0)),
            "provenance_notes": list(dict.fromkeys(provenance_notes)),
            "model_version": model_versions[0] if model_versions else "",
        }
        self.spectral_qc_workspace["windows"] = [
            self._serialize_window_for_workspace(window) for window in result.windows
        ]
        self.spectral_qc_workspace["active_run_id"] = result.run_id
        if result.windows:
            valid_selected = next(
                (window.window_id for window in result.windows if window.window_id == selected_window_id),
                result.windows[0].window_id,
            )
            self.spectral_qc_workspace["selected_window_id"] = valid_selected
        else:
            self.spectral_qc_workspace["selected_window_id"] = None

    def _sync_report_center_from_results(
        self,
        *,
        mark_refreshed: bool = False,
        mark_generated: bool = False,
    ) -> None:
        workspace = self.report_center_workspace
        filters = workspace.setdefault("filters", {})
        filters["project"] = self.project_profile.name or "当前项目"
        filters.setdefault("view_mode", "工程诊断")
        batch_lookup = {self._batch_label(result): result.run_id for result in self.spectral_runs}
        workspace["batch_lookup"] = batch_lookup
        workspace["eddypro_compare"] = self._eddypro_compare_workspace_state()
        workspace["eddypro_attribution"] = self._eddypro_attribution_workspace_state()

        active_run_id = workspace.get("active_run_id")
        batch_filter = str(filters.get("batch", "")).strip()
        if batch_filter and batch_filter in batch_lookup:
            active_run_id = batch_lookup[batch_filter]
        if active_run_id is None and self.spectral_runs:
            active_run_id = self.spectral_runs[0].run_id
        workspace["active_run_id"] = active_run_id

        run_result = next((result for result in self.spectral_runs if result.run_id == active_run_id), None)
        if run_result is None:
            workspace["summary"] = {
                "recent_status": "尚未生成真实运行结果",
                "exportable_reports": 0,
                "attention_count": 0,
                "last_generated_at": "--",
            }
            filters["batch"] = ""
            workspace["reports"] = self._empty_report_payloads()
            workspace["reports"]["eddypro_compare"] = self._eddypro_report_payload()
            workspace["batch_compare"] = (
                self.latest_batch_compare.to_dict()
                if self.latest_batch_compare is not None
                else self._empty_batch_compare_payload()
            )
            workspace["export_status"] = (
                self.latest_evidence_manifest.summary_text if self.latest_evidence_manifest else "尚未导出"
            )
            return

        filters["batch"] = self._batch_label(run_result)
        reports = self._build_report_payloads_from_run(run_result)
        reports["eddypro_compare"] = self._eddypro_report_payload()
        selected_report = str(workspace.get("selected_report", "run_summary"))
        if selected_report not in reports:
            selected_report = "run_summary"
        workspace["selected_report"] = selected_report
        workspace["reports"] = reports

        report_exports = run_result.artifacts.get("report_exports", {})
        result_exports = run_result.artifacts.get("result_exports", {})
        evidence = run_result.artifacts.get("evidence_bundle", {})
        export_status = workspace.get("export_status", "尚未导出")
        delivery_export = report_exports.get("delivery_package", {})
        if delivery_export.get("export_root"):
            export_status = f"交付包已导出（{delivery_export.get('exported_at', '--')}）：{delivery_export.get('export_root', '--')}"
        elif evidence.get("summary_text"):
            export_status = str(evidence["summary_text"])
        elif result_exports.get("latest", {}).get("summary_text"):
            latest_export = result_exports.get("latest", {})
            export_status = f"真实结果包已导出（{latest_export.get('exported_at', '--')}）"
        elif report_exports:
            latest_export = max(report_exports.values(), key=lambda item: item.get("exported_at", ""))
            export_status = f"当前报告已导出（{latest_export.get('exported_at', '--')}）"
        workspace["export_status"] = export_status

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M") if mark_generated else run_result.created_at.strftime(
            "%Y-%m-%d %H:%M"
        )
        recent_status = "最近批次已完成" if run_result.windows else "当前高频数据不足"
        if mark_refreshed:
            recent_status = f"{recent_status}，视图已刷新"
        workspace["summary"] = {
            "recent_status": recent_status,
            "exportable_reports": sum(1 for report in reports.values() if report.get("title")),
            "attention_count": int(run_result.summary.get("attention_window_count", 0)),
            "last_generated_at": generated_at,
        }
        workspace["batch_compare"] = (
            self.latest_batch_compare.to_dict()
            if self.latest_batch_compare is not None
            else self._empty_batch_compare_payload(run_result=run_result)
        )

    def _rp_method_summary(self, rp_result: RPRunResult | None) -> dict[str, object]:
        default = {
            "footprint_method": "未启用",
            "footprint_provenance": "",
            "footprint_limitations": [],
            "footprint_peak_distance_m": None,
            "footprint_offset_distance_m": None,
            "footprint_contribution_distances": {},
            "footprint_2d_summary": {},
            "uncertainty_method": "未启用",
            "uncertainty_provenance": "",
            "uncertainty_limitations": [],
            "uncertainty_components": {},
            "uncertainty_relative_uncertainty": None,
            "uncertainty_random_error": None,
            "uncertainty_band": None,
            "spectral_correction_method": "未启用",
            "spectral_correction_provenance": "",
            "spectral_correction_limitations": [],
            "spectral_correction_factor": None,
            "spectral_correction_measured_cospectrum_source": "",
            "spectral_correction_cospectrum_match_summary": {},
            "method_compare_summary": {},
            "method_compare_recommendations": {},
            "clock_sync_status": "disabled",
            "clock_sync_method": "",
            "clock_sync_source": "",
            "clock_sync_mean_offset_s": None,
            "clock_sync_provenance": "",
            "clock_sync_summary": {},
            "runtime_watchdog_status": "not_run",
            "runtime_watchdog_profile": "",
            "runtime_watchdog_fail_count": None,
            "runtime_watchdog_warn_count": None,
            "runtime_watchdog_provenance": "",
            "runtime_watchdog_recommended_actions": [],
            "runtime_watchdog_summary": {},
            "runtime_service_status": "not_run",
            "runtime_service_id": "",
            "runtime_service_delivery_state": "",
            "runtime_service_quarantine_count": None,
            "runtime_service_restart_count": None,
            "runtime_service_provenance": "",
            "runtime_service_summary": {},
        }
        if rp_result is None:
            return default
        summary = dict(rp_result.summary or {})
        artifacts = dict(rp_result.artifacts.get("method_rollup", {}) or rp_result.artifacts.get("method_provenance", {}) or {})
        footprint_summary = dict(summary.get("footprint_summary", {}) or artifacts.get("footprint_summary", {}) or {})
        footprint_2d_summary = dict(summary.get("footprint_2d_summary", {}) or artifacts.get("footprint_2d_summary", {}) or footprint_summary.get("footprint_2d_summary", {}) or {})
        uncertainty_summary = dict(summary.get("uncertainty_summary", {}) or artifacts.get("uncertainty_summary", {}) or {})
        spectral_summary = dict(summary.get("spectral_correction_summary", {}) or artifacts.get("spectral_correction_summary", {}) or {})
        method_compare_summary = dict(summary.get("method_compare_summary", {}) or artifacts.get("method_compare_summary", {}) or {})
        method_compare_recommendations = dict(summary.get("method_compare_recommendations", {}) or artifacts.get("method_compare_recommendations", {}) or method_compare_summary.get("recommendations", {}) or {})
        clock_sync_summary = dict(summary.get("clock_sync_summary", {}) or rp_result.artifacts.get("clock_sync", {}) or {})
        runtime_watchdog_summary = dict(summary.get("runtime_watchdog_summary", {}) or rp_result.artifacts.get("runtime_watchdog", {}) or {})
        runtime_service_summary = dict(summary.get("runtime_service_summary", {}) or rp_result.artifacts.get("runtime_service", {}) or {})
        if not clock_sync_summary and rp_result.windows:
            clock_sync_summary = dict(rp_result.windows[0].diagnostics.get("clock_sync_detail", {}) if rp_result.windows[0].diagnostics else {})
        if (not footprint_summary or not uncertainty_summary or not spectral_summary) and rp_result.windows:
            first = rp_result.windows[0]
            diag = first.diagnostics or {}
            if not footprint_summary:
                footprint_detail = dict(diag.get("footprint_detail", {}) or {})
                footprint_summary = {
                    "method": diag.get("footprint_method", ""),
                    "peak_distance_m": diag.get("footprint_peak_distance_m"),
                    "offset_distance_m": diag.get("footprint_offset_distance_m"),
                    "contribution_distances": dict(diag.get("footprint_contribution_distances", {}) or {}),
                    "provenance": footprint_detail.get("provenance", ""),
                    "limitations": footprint_detail.get("limitations", []),
                }
            if not footprint_2d_summary:
                footprint_2d_summary = {
                    "status": diag.get("footprint_2d_grid_status", ""),
                    "peak_downwind_m": diag.get("footprint_2d_peak_downwind_m"),
                    "peak_crosswind_m": diag.get("footprint_2d_peak_crosswind_m"),
                    "half_width_m": diag.get("footprint_2d_half_width_m"),
                }
            if not uncertainty_summary:
                uncertainty_detail = dict(diag.get("uncertainty_method_detail", {}) or first.uncertainty_detail or {})
                uncertainty_summary = {
                    "method": diag.get("uncertainty_method", ""),
                    "relative_uncertainty": uncertainty_detail.get("relative_uncertainty", uncertainty_detail.get("relative_error")),
                    "primary_flux_random_error": uncertainty_detail.get("primary_flux_random_error"),
                    "uncertainty_band": uncertainty_detail.get("primary_flux_uncertainty_band"),
                    "components": dict(uncertainty_detail.get("components", {}) or {}),
                    "provenance": uncertainty_detail.get("provenance", ""),
                    "limitations": uncertainty_detail.get("limitations", []),
                }
            if not spectral_summary:
                spectral_summary = {
                    "method": diag.get("spectral_correction_method", ""),
                    "correction_factor": diag.get("spectral_correction_factor"),
                    "provenance": diag.get("spectral_correction_provenance", ""),
                    "measured_cospectrum_source": diag.get("spectral_correction_measured_cospectrum_source", ""),
                    "cospectrum_match_summary": dict(diag.get("spectral_correction_cospectrum_match", {}) or {}),
                    "limitations": diag.get("spectral_correction_limitations", []),
                }
            if not method_compare_summary:
                method_compare_summary = dict(diag.get("method_compare_summary", {}) or {})
            if not method_compare_recommendations:
                method_compare_recommendations = dict(diag.get("method_compare_recommendations", {}) or {})
        footprint_peak = summary.get("footprint_peak_distance_m", footprint_summary.get("peak_distance_m"))
        footprint_offset = summary.get("footprint_offset_distance_m", footprint_summary.get("offset_distance_m"))
        footprint_contrib = dict(summary.get("footprint_contribution_distances") or footprint_summary.get("contribution_distances") or {})
        footprint_provenance = str(summary.get("footprint_provenance") or footprint_summary.get("provenance") or "")
        if footprint_peak is not None and footprint_offset is not None:
            footprint_provenance = (
                f"{footprint_provenance}; peak={float(footprint_peak):.1f} m; offset={float(footprint_offset):.1f} m; "
                f"x50={footprint_contrib.get('x50', '--')} m; x90={footprint_contrib.get('x90', '--')} m"
            ).strip("; ")

        uncertainty_relative = summary.get("uncertainty_relative_uncertainty", uncertainty_summary.get("relative_uncertainty"))
        uncertainty_random_error = summary.get("uncertainty_random_error", uncertainty_summary.get("primary_flux_random_error"))
        uncertainty_band = summary.get("uncertainty_band", uncertainty_summary.get("uncertainty_band"))
        uncertainty_components = dict(summary.get("uncertainty_components") or uncertainty_summary.get("components") or {})
        uncertainty_provenance = str(summary.get("uncertainty_provenance") or uncertainty_summary.get("provenance") or "")
        if uncertainty_relative is not None:
            uncertainty_provenance = (
                f"{uncertainty_provenance}; relative={float(uncertainty_relative):.3f}; "
                f"components={json.dumps(uncertainty_components, ensure_ascii=False)}"
            ).strip("; ")
        if uncertainty_random_error is not None:
            uncertainty_provenance = f"{uncertainty_provenance}; random_error={float(uncertainty_random_error):.6f}".strip("; ")
        if uncertainty_band is not None:
            uncertainty_provenance = f"{uncertainty_provenance}; band={float(uncertainty_band):.6f}".strip("; ")

        spectral_factor = summary.get("spectral_correction_factor", spectral_summary.get("correction_factor"))
        spectral_provenance = str(summary.get("spectral_correction_provenance") or spectral_summary.get("provenance") or "")
        spectral_measured_cospectrum_source = str(
            summary.get("spectral_correction_measured_cospectrum_source")
            or spectral_summary.get("measured_cospectrum_source")
            or ""
        )
        cospectrum_match_summary = dict(
            summary.get("spectral_correction_cospectrum_match_summary")
            or spectral_summary.get("cospectrum_match_summary")
            or {}
        )
        if spectral_factor is not None:
            spectral_provenance = f"{spectral_provenance}; factor={float(spectral_factor):.3f}".strip("; ")
        if spectral_measured_cospectrum_source:
            spectral_provenance = f"{spectral_provenance}; cospectrum={spectral_measured_cospectrum_source}".strip("; ")
        clock_status = str(summary.get("clock_sync_status") or clock_sync_summary.get("status") or default["clock_sync_status"])
        clock_method = str(summary.get("clock_sync_method") or clock_sync_summary.get("method") or "")
        clock_source = str(summary.get("clock_sync_source") or clock_sync_summary.get("clock_source") or "")
        clock_mean_offset = summary.get("clock_sync_mean_offset_s", clock_sync_summary.get("mean_offset_seconds"))
        clock_provenance = str(clock_sync_summary.get("provenance", ""))
        if clock_mean_offset is not None:
            clock_provenance = f"{clock_provenance}; mean_offset_s={float(clock_mean_offset):.6f}".strip("; ")
        runtime_status = str(summary.get("runtime_watchdog_status") or runtime_watchdog_summary.get("status") or default["runtime_watchdog_status"])
        runtime_profile = str(runtime_watchdog_summary.get("profile_id", ""))
        runtime_fail_count = runtime_watchdog_summary.get("fail_count")
        runtime_warn_count = runtime_watchdog_summary.get("warn_count")
        runtime_provenance = str(runtime_watchdog_summary.get("provenance", ""))
        if runtime_profile:
            runtime_provenance = f"{runtime_provenance}; profile={runtime_profile}".strip("; ")
        if runtime_fail_count is not None or runtime_warn_count is not None:
            runtime_provenance = (
                f"{runtime_provenance}; fail={runtime_fail_count if runtime_fail_count is not None else '--'}; "
                f"warn={runtime_warn_count if runtime_warn_count is not None else '--'}"
            ).strip("; ")
        service_status = str(summary.get("runtime_service_status") or runtime_service_summary.get("status") or default["runtime_service_status"])
        service_id = str(runtime_service_summary.get("service_id", ""))
        service_delivery_state = str(summary.get("runtime_service_delivery_state") or runtime_service_summary.get("delivery_state") or "")
        service_quarantine_count = len(runtime_service_summary.get("quarantine_records", []) or [])
        service_restart_count = len(runtime_service_summary.get("restart_records", []) or [])
        service_provenance = str(runtime_service_summary.get("provenance", ""))
        if service_id:
            service_provenance = f"{service_provenance}; service={service_id}".strip("; ")
        if service_delivery_state:
            service_provenance = f"{service_provenance}; delivery={service_delivery_state}".strip("; ")
        if runtime_service_summary:
            service_provenance = f"{service_provenance}; quarantine={service_quarantine_count}; restarts={service_restart_count}".strip("; ")

        return {
            "footprint_method": str(summary.get("footprint_method") or footprint_summary.get("method") or default["footprint_method"]),
            "footprint_provenance": footprint_provenance,
            "footprint_limitations": list(summary.get("footprint_limitations") or footprint_summary.get("limitations") or []),
            "footprint_peak_distance_m": footprint_peak,
            "footprint_offset_distance_m": footprint_offset,
            "footprint_contribution_distances": footprint_contrib,
            "footprint_2d_summary": footprint_2d_summary,
            "uncertainty_method": str(summary.get("uncertainty_method") or uncertainty_summary.get("method") or default["uncertainty_method"]),
            "uncertainty_provenance": uncertainty_provenance,
            "uncertainty_limitations": list(summary.get("uncertainty_limitations") or uncertainty_summary.get("limitations") or []),
            "uncertainty_components": uncertainty_components,
            "uncertainty_relative_uncertainty": uncertainty_relative,
            "uncertainty_random_error": uncertainty_random_error,
            "uncertainty_band": uncertainty_band,
            "spectral_correction_method": str(summary.get("spectral_correction_method") or spectral_summary.get("method") or default["spectral_correction_method"]),
            "spectral_correction_provenance": spectral_provenance,
            "spectral_correction_limitations": list(summary.get("spectral_correction_limitations") or spectral_summary.get("limitations") or []),
            "spectral_correction_factor": spectral_factor,
            "spectral_correction_measured_cospectrum_source": spectral_measured_cospectrum_source,
            "spectral_correction_cospectrum_match_summary": cospectrum_match_summary,
            "method_compare_summary": method_compare_summary,
            "method_compare_recommendations": method_compare_recommendations,
            "clock_sync_status": clock_status,
            "clock_sync_method": clock_method,
            "clock_sync_source": clock_source,
            "clock_sync_mean_offset_s": clock_mean_offset,
            "clock_sync_provenance": clock_provenance,
            "clock_sync_summary": clock_sync_summary,
            "runtime_watchdog_status": runtime_status,
            "runtime_watchdog_profile": runtime_profile,
            "runtime_watchdog_fail_count": runtime_fail_count,
            "runtime_watchdog_warn_count": runtime_warn_count,
            "runtime_watchdog_provenance": runtime_provenance,
            "runtime_watchdog_recommended_actions": list(runtime_watchdog_summary.get("recommended_actions", []) or []),
            "runtime_watchdog_summary": runtime_watchdog_summary,
            "runtime_service_status": service_status,
            "runtime_service_id": service_id,
            "runtime_service_delivery_state": service_delivery_state,
            "runtime_service_quarantine_count": service_quarantine_count if runtime_service_summary else None,
            "runtime_service_restart_count": service_restart_count if runtime_service_summary else None,
            "runtime_service_provenance": service_provenance,
            "runtime_service_summary": runtime_service_summary,
        }

    def _empty_report_payloads(self) -> dict:
        return {
            key: {
                "title": title,
                "source": "暂无真实批次",
                "updated_at": "--",
                "metrics": [("状态", "未运行"), ("批次", "--"), ("窗口", "0"), ("导出", "未生成")],
                "plot_series": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("状态", "未生成", "请先运行谱分析生成真实批次结果。")],
                "conclusions": ["当前页面仅显示真实运行结果，请先运行谱分析。"],
                "export_options": ["导出当前报告", "导出证据包"],
                "file_info": {"状态": "尚未导出"},
                "versions": [],
                "usage": ["操作员先运行谱分析，再查看结论。"],
            }
            for key, title in (
                ("run_summary", "运行摘要"),
                ("device_status", "设备状态报告"),
                ("acquisition_quality", "采集质量报告"),
                ("ec_results", "EC 结果报告"),
                ("spectral_qc", "谱修正与 QC 报告"),
                ("anomaly_events", "异常事件报告"),
                ("site_method", "站点方法说明"),
                ("evidence_pack", "证据包"),
                ("benchmark_cockpit", "Benchmark 驾驶舱"),
                ("method_provenance", "方法溯源"),
                ("method_compare", "Method Compare"),
            )
        }

    def _build_report_payloads_from_run(self, run_result: SpectralRunResult) -> dict:
        reports = self._empty_report_payloads()
        batch_label = self._batch_label(run_result)
        summary = run_result.summary
        windows = run_result.windows
        window_rows = [self._serialize_window_for_workspace(window) for window in windows]
        device_cards = self.device_cards()
        device_online = sum(1 for card in device_cards if card["connected"])
        anomalous_windows = [window for window in windows if window.qc_grade in {"B", "C"}]
        anomaly_counts: dict[str, int] = defaultdict(int)
        for window in anomalous_windows:
            anomaly_counts[window.anomaly_type] += 1

        lag_series = [round(window.lag_seconds, 3) for window in windows]
        factor_series = [round(window.correction_factor, 3) for window in windows]
        flux_series = [round(window.corrected_flux_after, 4) for window in windows]
        qc_band_series = [round(window.qc_band_value, 3) for window in windows]
        completion_series = []
        expected_samples = max((window.sample_count for window in windows), default=0)
        if expected_samples > 0:
            completion_series = [round(window.sample_count / expected_samples, 3) for window in windows]

        good_ratio = (
            float(summary.get("good_window_count", 0)) / max(1, int(summary.get("window_count", len(windows))))
            if windows
            else 0.0
        )
        mean_flux_before = sum(window.corrected_flux_before for window in windows) / max(1, len(windows))
        mean_flux_after = sum(window.corrected_flux_after for window in windows) / max(1, len(windows))
        sample_rate_hz = float(run_result.artifacts.get("sample_rate_hz", summary.get("sample_rate_hz", 0.0)) or 0.0)
        project_source = f"{self.project_profile.name} / {batch_label}"
        updated_at = run_result.created_at.strftime("%Y-%m-%d %H:%M")
        report_root = self.runtime_root / "exports" / "reports"
        report_exports = run_result.artifacts.get("report_exports", {})
        result_export_files = dict(run_result.artifacts.get("result_exports", {}).get("latest", {}).get("files", {}) or {})
        evidence = run_result.artifacts.get("evidence_bundle", {})

        def file_info_for(report_key: str) -> dict:
            exported = report_exports.get(report_key, {})
            if exported:
                return {
                    "状态": "已导出",
                    "最近导出": exported.get("exported_at", "--"),
                    "目标文件": exported.get("path", "--"),
                }
            return {
                "状态": "尚未导出",
                "目标文件": str(report_root / f"{report_key}_{run_result.run_id}.json"),
            }

        top_anomaly = anomalous_windows[0] if anomalous_windows else None
        reports["run_summary"] = {
            "title": "运行摘要",
            "source": project_source,
            "updated_at": updated_at,
            "metrics": [
                ("有效窗口", f"{int(summary.get('valid_window_count', 0))} / {int(summary.get('window_count', len(windows)))}"),
                ("优良窗口", str(int(summary.get("good_window_count", 0)))),
                ("待关注异常", str(int(summary.get("attention_window_count", 0)))),
                ("最近生成", updated_at[-5:]),
            ],
            "plot_series": factor_series,
            "table_headers": ["项目", "当前值", "说明"],
            "table_rows": [
                ("运行状态", "已完成" if windows else "数据不足", "只展示真实批次结果"),
                ("平均 lag", f"{float(summary.get('average_lag_seconds', 0.0)):.2f} s", "来自窗口级实测协方差峰位"),
                ("平均修正因子", f"{float(summary.get('average_correction_factor', 1.0)):.3f}", "由频谱高频损失推导"),
                ("主异常", top_anomaly.anomaly_type if top_anomaly else "无", top_anomaly.reason if top_anomaly else "当前未发现异常窗口"),
            ],
            "conclusions": [
                f"当前批次共生成 {len(windows)} 个真实窗口结果，优良比例 {good_ratio:.0%}。",
                "若需要追溯原因，可继续进入谱修正与 QC 报告查看 lag、互谱、Ogive 与修正前后证据。",
            ],
            "export_options": ["导出当前报告", "导出证据包", "批次对比摘要"],
            "file_info": file_info_for("run_summary"),
            "versions": [f"运行 ID：{run_result.run_id}", f"数据来源：{run_result.data_source}", f"时间范围：{run_result.time_range}"],
            "usage": ["操作员先看结论与异常数量。", "工程师再定位异常窗口与配置差异。", "管理汇报可直接引用此页摘要。"],
        }

        reports["device_status"] = {
            "title": "设备状态报告",
            "source": f"设备中心 / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("在线设备", str(device_online)),
                ("设备总数", str(len(device_cards))),
                ("异常设备", str(sum(1 for card in device_cards if card["is_abnormal"]))),
                ("状态", "稳定" if device_online else "待连接"),
            ],
            "plot_series": [1.0 if card["connected"] else 0.0 for card in device_cards],
            "table_headers": ["设备", "状态", "说明"],
            "table_rows": [
                (
                    card["label"],
                    "在线" if card["connected"] else "离线",
                    card["last_message"],
                )
                for card in device_cards
            ]
            or [("暂无设备", "--", "当前没有设备状态记录")],
            "conclusions": ["设备状态报告来自当前工作台真实设备状态，不再使用固定示例文本。"],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": file_info_for("device_status"),
            "versions": [f"最近批次：{batch_label}", f"在线设备：{device_online}/{len(device_cards)}"],
            "usage": ["适合现场交接班和设备健康复盘。"],
        }

        rp_result = self.current_rp_run()
        rp_method_summary = self._rp_method_summary(rp_result)
        reports["acquisition_quality"] = {
            "title": "采集质量报告",
            "source": f"高频缓冲 / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("采样率", f"{sample_rate_hz:.1f} Hz"),
                ("窗口数量", str(len(windows))),
                ("平均样本数", f"{(sum(window.sample_count for window in windows) / max(1, len(windows))):.0f}"),
                ("结论", "稳定" if completion_series and min(completion_series) >= 0.8 else "需关注"),
            ],
            "plot_series": completion_series,
            "table_headers": ["指标", "数值", "说明"],
            "table_rows": [
                ("时间范围", run_result.time_range, "与谱分析批次一致"),
                ("数据来源", run_result.data_source, "来自当前高频缓冲/批次"),
                ("Clock sync", rp_method_summary["clock_sync_status"], rp_method_summary["clock_sync_provenance"]),
                ("Runtime watchdog", rp_method_summary["runtime_watchdog_status"], rp_method_summary["runtime_watchdog_provenance"]),
                ("Runtime service", rp_method_summary["runtime_service_status"], rp_method_summary["runtime_service_provenance"]),
                ("窗口完整度", f"{(sum(completion_series) / max(1, len(completion_series))):.0%}" if completion_series else "--", "按窗口样本数估算"),
                ("关注窗口", str(len(anomalous_windows)), "窗口级 QC 结果来自 core 层"),
            ],
            "conclusions": ["采集质量报告直接消费真实窗口样本数和采样率结果。"],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": file_info_for("acquisition_quality"),
            "versions": [f"采样率：{sample_rate_hz:.1f} Hz", f"窗口数：{len(windows)}"],
            "usage": ["工程师可用来判断问题来自采集链还是谱修正链。"],
        }

        reports["ec_results"] = {
            "title": "EC 结果报告",
            "source": f"谱修正后通量摘要 / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("修正前均值", f"{mean_flux_before:.4f}"),
                ("修正后均值", f"{mean_flux_after:.4f}"),
                ("平均修正", f"{float(summary.get('average_correction_factor', 1.0)):.3f}"),
                ("优良比例", f"{good_ratio:.0%}"),
            ],
            "plot_series": flux_series,
            "table_headers": ["结果项", "数值", "说明"],
            "table_rows": [
                ("平均 lag", f"{float(summary.get('average_lag_seconds', 0.0)):.2f} s", "窗口级 lag 均值"),
                ("高频损失风险", str(summary.get("high_freq_loss_risk", "--")), "由功率谱损失推导"),
                ("修正前后差异", f"{(mean_flux_after - mean_flux_before):.4f}", "当前窗口平均通量差"),
                ("窗口有效数", str(int(summary.get("valid_window_count", 0))), "A/B 等级窗口数"),
                ("Footprint 方法", rp_method_summary["footprint_method"], rp_method_summary["footprint_provenance"]),
                ("不确定度方法", rp_method_summary["uncertainty_method"], rp_method_summary["uncertainty_provenance"]),
                ("谱修正方法", rp_method_summary["spectral_correction_method"], rp_method_summary["spectral_correction_provenance"]),
            ],
            "conclusions": ["此页使用当前谱修正批次汇总出的真实通量前后对比，不再展示占位型 EC 产物。"],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": file_info_for("ec_results"),
            "versions": [f"运行 ID：{run_result.run_id}", "结果来自谱修正窗口汇总"],
            "usage": ["操作员看结论，工程师看修正幅度和有效窗口变化。"],
        }

        reports["spectral_qc"] = {
            "title": "谱修正与 QC 报告",
            "source": f"谱修正与 QC / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("lag 可信度", self._format_confidence(float(summary.get("average_lag_confidence", 0.0)))),
                ("高频损失风险", str(summary.get("high_freq_loss_risk", "--"))),
                ("优良窗口", str(int(summary.get("good_window_count", 0)))),
                ("关注窗口", str(int(summary.get("attention_window_count", 0)))),
            ],
            "plot_series": qc_band_series,
            "table_headers": ["窗口", "等级", "原因"],
            "table_rows": [
                (self._window_label(window), window.qc_grade, window.reason)
                for window in anomalous_windows[:6]
            ]
            or [("全部窗口", "A", "当前未发现需要重点关注的异常窗口。")],
            "conclusions": [
                "当前谱修正与 QC 报告完全来自 core 层真实窗口结果对象。",
                "lag、互谱、Ogive 和修正前后幅度可在谱修正页逐窗追溯。",
            ],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": file_info_for("spectral_qc"),
            "versions": [f"QC 规则：{self.spectral_qc_workspace['sections']['qc_overview']['grade_rule']}", f"运行 ID：{run_result.run_id}"],
            "usage": ["工程师优先查看此页。", "管理汇报时保留风险等级和数量即可。"],
        }

        reports["anomaly_events"] = {
            "title": "异常事件报告",
            "source": f"异常窗口与事件流 / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("异常窗口", str(len(anomalous_windows))),
                ("事件条目", str(len(self.recent_events(limit=20)))),
                ("主异常", next(iter(anomaly_counts.keys()), "无")),
                ("状态", "需关注" if anomalous_windows else "稳定"),
            ],
            "plot_series": [1.0 if window.qc_grade in {"B", "C"} else 0.0 for window in windows],
            "table_headers": ["时间/窗口", "级别", "说明"],
            "table_rows": [
                (self._window_label(window), window.qc_grade, window.reason)
                for window in anomalous_windows[:6]
            ]
            or [("当前批次", "正常", "未发现异常事件或异常窗口。")],
            "conclusions": ["异常事件报告直接复用真实异常窗口和当前事件流。"],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": file_info_for("anomaly_events"),
            "versions": [f"异常类型数：{len(anomaly_counts)}", f"窗口总数：{len(windows)}"],
            "usage": ["适合复盘、审计和交接说明。"],
        }

        config_snapshot = run_result.summary.get("config_snapshot") or run_result.artifacts.get("config_snapshot", {})
        reports["site_method"] = {
            "title": "站点方法说明",
            "source": f"{self.project_profile.name} / 站点与方法",
            "updated_at": updated_at,
            "metrics": [
                ("站点", self.site_profile.station_name),
                ("采样率", f"{sample_rate_hz:.1f} Hz"),
                ("窗口", f"{float(config_snapshot.get('timing', {}).get('block_minutes', 30.0)):.0f} 分钟"),
                ("站点代码", self.site_profile.station_code),
            ],
            "plot_series": [
                float(sample_rate_hz or 0.0),
                float(config_snapshot.get("transfer_function", {}).get("tube_length_m", 0.0) or 0.0),
                float(config_snapshot.get("lag_phase", {}).get("expected_lag_s", 0.0) or 0.0),
                float(config_snapshot.get("correction_factor", {}).get("factor_cap", 0.0) or 0.0),
            ],
            "table_headers": ["方法项", "当前配置", "说明"],
            "table_rows": [
                ("数据来源", run_result.data_source, "真实运行批次来源"),
                ("站点位置", self.site_profile.location, "来自项目/站点配置"),
                ("预期 lag", f"{float(config_snapshot.get('lag_phase', {}).get('expected_lag_s', 0.0)):.2f} s", "谱分析配置"),
                ("修正上限", f"{float(config_snapshot.get('correction_factor', {}).get('factor_cap', 1.0)):.2f}", "当前谱修正参数"),
                ("Footprint 方法", rp_method_summary["footprint_method"], rp_method_summary["footprint_provenance"]),
                ("不确定度方法", rp_method_summary["uncertainty_method"], rp_method_summary["uncertainty_provenance"]),
                ("谱修正方法", rp_method_summary["spectral_correction_method"], rp_method_summary["spectral_correction_provenance"]),
            ],
            "conclusions": ["站点方法说明页直接引用当前批次实际使用的项目、站点和谱修正配置快照。"],
            "export_options": ["导出当前报告"],
            "file_info": file_info_for("site_method"),
            "versions": [f"项目：{self.project_profile.name}", f"站点：{self.site_profile.station_name}"],
            "usage": ["适合作为正式报告附录或方法页。"],
        }

        reports["method_provenance"] = {
            "title": "方法溯源",
            "source": f"Footprint / 不确定度 / 谱修正方法溯源 / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("Footprint", rp_method_summary["footprint_method"]),
                ("不确定度", rp_method_summary["uncertainty_method"]),
                ("谱修正", rp_method_summary["spectral_correction_method"]),
                ("Clock sync", rp_method_summary["clock_sync_status"]),
                ("Runtime", rp_method_summary["runtime_watchdog_status"]),
                ("Service", rp_method_summary["runtime_service_status"]),
                ("窗口数", str(len(rp_result.windows) if rp_result else 0)),
            ],
            "plot_series": [],
            "table_headers": ["方法族", "方法名", "溯源"],
            "table_rows": [
                ("Footprint", rp_method_summary["footprint_method"], rp_method_summary["footprint_provenance"]),
                ("Footprint 2D", str(rp_method_summary["footprint_2d_summary"]), "2D footprint grid artifact summary"),
                ("FCC match", str(rp_method_summary["spectral_correction_cospectrum_match_summary"]), "FCC/RP cospectrum match provenance"),
                ("Method compare", str(rp_method_summary["method_compare_recommendations"]), "method-family compare recommendations"),
                ("不确定度", rp_method_summary["uncertainty_method"], rp_method_summary["uncertainty_provenance"]),
                ("谱修正", rp_method_summary["spectral_correction_method"], rp_method_summary["spectral_correction_provenance"]),
                ("不确定度带宽", str(rp_method_summary["uncertainty_band"]), "primary flux uncertainty band"),
                ("FCC cospectrum", rp_method_summary["spectral_correction_measured_cospectrum_source"], "Fratini/FCC 自动注入路径"),
                ("Clock sync", rp_method_summary["clock_sync_method"], rp_method_summary["clock_sync_provenance"]),
                ("Runtime watchdog", rp_method_summary["runtime_watchdog_profile"], rp_method_summary["runtime_watchdog_provenance"]),
                ("Runtime service", rp_method_summary["runtime_service_id"], rp_method_summary["runtime_service_provenance"]),
            ],
            "conclusions": [
                "方法溯源页集中展示当前批次使用的 Footprint、不确定度、谱修正方法来源和局限性。",
                "建议作为正式报告附录，说明结论来自哪些方法配置。",
            ],
            "export_options": ["导出当前报告"],
            "file_info": {
                **file_info_for("method_provenance"),
                **({"Method Rollup Artifact": str(result_export_files.get("method_rollup_artifact"))} if result_export_files.get("method_rollup_artifact") else {}),
                **({"Footprint 2D Artifact": str(result_export_files.get("footprint_2d_artifact"))} if result_export_files.get("footprint_2d_artifact") else {}),
                **({"Method Compare Artifact": str(result_export_files.get("method_compare_artifact"))} if result_export_files.get("method_compare_artifact") else {}),
                **({"Runtime Watchdog Artifact": str(result_export_files.get("runtime_watchdog_artifact"))} if result_export_files.get("runtime_watchdog_artifact") else {}),
                **({"Runtime Service Artifact": str(result_export_files.get("runtime_service_artifact"))} if result_export_files.get("runtime_service_artifact") else {}),
                **({"Clock Sync Artifact": str(result_export_files.get("clock_sync_artifact"))} if result_export_files.get("clock_sync_artifact") else {}),
            },
            "versions": [
                f"运行 ID：{run_result.run_id}",
                "方法溯源优先来自 RP run-level method rollup artifact",
            ],
            "usage": ["工程师查看方法来源和局限性。", "管理汇报时引用此页说明方法依据。"],
        }

        method_compare_summary = dict(rp_method_summary.get("method_compare_summary", {}) or {})
        method_compare_families = dict(method_compare_summary.get("families", {}) or {})
        method_compare_rows = []
        for family, family_summary in sorted(method_compare_families.items()):
            payload = dict(family_summary or {})
            methods_run = payload.get("methods_run", [])
            if isinstance(methods_run, list):
                methods_text = ", ".join(str(item) for item in methods_run)
            else:
                methods_text = str(methods_run)
            method_compare_rows.append(
                (
                    str(family),
                    str(payload.get("recommendation", "")),
                    f"max deviation={payload.get('max_abs_relative_deviation', '--')}; methods={methods_text}",
                )
            )
        if not method_compare_rows:
            method_compare_rows = [
                (
                    "method_compare",
                    str(method_compare_summary.get("status", "disabled")),
                    "No method-family comparison payload is available for this run.",
                )
            ]
        performance_profile = dict((rp_result.summary or {}).get("performance_profile", {}) if rp_result else {})
        performance_sections = dict(performance_profile.get("sections_ms", {}) or {})
        runtime_watchdog_summary = dict(rp_method_summary.get("runtime_watchdog_summary", {}) or {})
        runtime_checks = list(runtime_watchdog_summary.get("checks", []) or [])
        runtime_service_summary = dict(rp_method_summary.get("runtime_service_summary", {}) or {})
        runtime_service_checks = list(runtime_service_summary.get("checks", []) or [])
        for section_name, section_summary in sorted(performance_sections.items()):
            payload = dict(section_summary or {})
            method_compare_rows.append(
                (
                    f"performance:{section_name}",
                    f"avg={payload.get('average_ms', '--')} ms",
                    f"max={payload.get('max_ms', '--')} ms; windows={payload.get('window_count', '--')}",
                )
            )
        for check in runtime_checks[:8]:
            payload = dict(check or {})
            method_compare_rows.append(
                (
                    f"runtime:{payload.get('check_id', '')}",
                    str(payload.get("status", "")),
                    f"measured={payload.get('measured', '--')}; threshold={payload.get('threshold', '--')}",
                )
            )
        for check in runtime_service_checks[:8]:
            payload = dict(check or {})
            method_compare_rows.append(
                (
                    f"service:{payload.get('check_id', '')}",
                    str(payload.get("status", "")),
                    f"measured={payload.get('measured', '--')}; threshold={payload.get('threshold', '--')}",
                )
            )
        method_parity_payload: dict[str, object] = {}
        method_parity_path = result_export_files.get("method_parity_matrix_artifact")
        if method_parity_path:
            try:
                method_parity_payload = json.loads(Path(str(method_parity_path)).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                method_parity_payload = {}
        for row in list(method_parity_payload.get("rows", []) if isinstance(method_parity_payload, dict) else [])[:8]:
            payload = dict(row or {})
            method_compare_rows.append(
                (
                    f"parity:{payload.get('family', '')}",
                    str(payload.get("status", "")),
                    (
                        f"gas={payload.get('normalized_gas_ec_studio_method', payload.get('gas_ec_studio_method', ''))}; "
                        f"eddypro={payload.get('normalized_eddypro_method', payload.get('eddypro_method', ''))}; "
                        f"source={payload.get('reference_evidence_source', '')}"
                    ),
                )
            )
        metadata_coverage = dict(method_parity_payload.get("metadata_coverage", {}) if isinstance(method_parity_payload, dict) else {})
        method_compare_files = {
            **file_info_for("method_compare"),
            **({"Method Compare Artifact": str(result_export_files.get("method_compare_artifact"))} if result_export_files.get("method_compare_artifact") else {}),
            **({"Method Parity Matrix": str(result_export_files.get("method_parity_matrix_artifact"))} if result_export_files.get("method_parity_matrix_artifact") else {}),
            **({"Method Parity CSV": str(result_export_files.get("method_parity_matrix_csv"))} if result_export_files.get("method_parity_matrix_csv") else {}),
            **({"Footprint 2D Contour": str(result_export_files.get("footprint_2d_contour_svg"))} if result_export_files.get("footprint_2d_contour_svg") else {}),
            **({"Footprint 2D Grid CSV": str(result_export_files.get("footprint_2d_grid_csv"))} if result_export_files.get("footprint_2d_grid_csv") else {}),
            **({"Performance Profile": str(result_export_files.get("performance_profile_artifact"))} if result_export_files.get("performance_profile_artifact") else {}),
            **({"Runtime Watchdog": str(result_export_files.get("runtime_watchdog_artifact"))} if result_export_files.get("runtime_watchdog_artifact") else {}),
            **({"Runtime Service": str(result_export_files.get("runtime_service_artifact"))} if result_export_files.get("runtime_service_artifact") else {}),
        }
        reports["method_compare"] = {
            "title": "Method Compare",
            "source": f"Method parity / footprint contour / performance profile / {batch_label}",
            "updated_at": updated_at,
            "metrics": [
                ("status", str(method_compare_summary.get("status", "disabled"))),
                ("families", str(len(method_compare_families))),
                ("reference_fields", f"{metadata_coverage.get('reported_count', 0)} / {metadata_coverage.get('total_count', 0)}"),
                ("profiled_windows", str(performance_profile.get("profiled_window_count", 0))),
                ("runtime_watchdog", str(runtime_watchdog_summary.get("status", "not_run"))),
                ("runtime_service", str(runtime_service_summary.get("status", "not_run"))),
                ("runtime_ms", str(performance_profile.get("run_elapsed_ms", "--"))),
            ],
            "plot_series": [
                float(performance_profile.get("average_window_elapsed_ms", 0.0) or 0.0),
                float(performance_profile.get("max_window_elapsed_ms", 0.0) or 0.0),
                float(performance_profile.get("run_elapsed_ms", 0.0) or 0.0),
            ],
            "table_headers": ["family / artifact", "recommendation / metric", "detail"],
            "table_rows": method_compare_rows,
            "conclusions": [
                "This report is backed by the run-level method_compare artifact and method parity matrix, not by a view-only refresh.",
                "EddyPro method fields that are absent from the reference metadata remain marked as not_reported in the exported matrix.",
            ],
            "export_options": ["导出当前报告", "导出证据包"],
            "file_info": method_compare_files,
            "versions": [
                f"运行 ID：{run_result.run_id}",
                "Artifacts: method_compare_artifact.json, method_parity_matrix.json, footprint_2d_contour.svg, performance_profile.json, runtime_watchdog_artifact.json, runtime_service_artifact.json",
            ],
            "usage": [
                "工程师用此页快速检查三族方法对比、EddyPro 方法元数据覆盖情况和长窗口耗时。",
                "交付时优先引用 artifact 文件，页面仅作为统一入口。",
            ],
        }

        included_files = evidence.get("included_files", [])
        evidence_plot = []
        if included_files:
            evidence_plot = [
                sum(1 for path in included_files if str(path).endswith(".json")),
                sum(1 for path in included_files if str(path).endswith(".csv")),
                sum(1 for path in included_files if str(path).endswith(".png")),
            ]
        reports["evidence_pack"] = {
            "title": "证据包",
            "source": f"runtime_data / exports / evidence / {batch_label}",
            "updated_at": evidence.get("export_time", updated_at),
            "metrics": [
                ("导出文件数", str(len(included_files))),
                ("窗口数", str(len(windows))),
                ("状态", "已导出" if included_files else "未导出"),
                ("目录", evidence.get("root_dir", "--")),
            ],
            "plot_series": evidence_plot,
            "table_headers": ["证据项", "数值", "说明"],
            "table_rows": [
                ("manifest", "1", "记录文件清单与摘要") if included_files else ("manifest", "0", "尚未导出"),
                ("lag/谱图 CSV", str(sum(1 for path in included_files if str(path).endswith(".csv"))), "用于追溯窗口级证据"),
                ("JSON 快照", str(sum(1 for path in included_files if str(path).endswith(".json"))), "包含 summary、配置与站点快照"),
                ("导出目录", evidence.get("root_dir", "--"), "位于 runtime_root/export 目录"),
            ],
            "conclusions": [
                evidence.get("summary_text", "当前尚未导出证据包，导出后这里会展示真实落盘目录与文件清单。")
            ],
            "export_options": ["导出证据包"],
            "file_info": {
                "状态": "已导出" if included_files else "尚未导出",
                "目标目录": evidence.get("root_dir", "--"),
                "文件数": len(included_files),
            },
            "versions": [f"运行 ID：{run_result.run_id}", f"批次：{batch_label}"],
            "usage": ["工程诊断和审计留痕优先导出此项。"],
        }

        reports["benchmark_cockpit"] = self._benchmark_cockpit_payload(run_result)

        return reports

    def _compare_spectral_runs(
        self,
        current: SpectralRunResult,
        compare: SpectralRunResult,
    ) -> BatchCompareResult:
        current_summary = current.summary
        compare_summary = compare.summary
        current_total = max(1, int(current_summary.get("window_count", len(current.windows))))
        compare_total = max(1, int(compare_summary.get("window_count", len(compare.windows))))
        current_good_ratio = float(current_summary.get("good_window_count", 0)) / current_total
        compare_good_ratio = float(compare_summary.get("good_window_count", 0)) / compare_total
        current_attention = int(current_summary.get("attention_window_count", 0))
        compare_attention = int(compare_summary.get("attention_window_count", 0))

        config_changes = self._diff_config_snapshot(
            current_summary.get("config_snapshot") or current.artifacts.get("config_snapshot", {}),
            compare_summary.get("config_snapshot") or compare.artifacts.get("config_snapshot", {}),
        )
        changed_windows = self._changed_windows(current, compare)
        deltas = {
            "valid_window_delta": float(current_summary.get("valid_window_count", 0) - compare_summary.get("valid_window_count", 0)),
            "average_lag_delta": float(current_summary.get("average_lag_seconds", 0.0) - compare_summary.get("average_lag_seconds", 0.0)),
            "average_correction_factor_delta": float(
                current_summary.get("average_correction_factor", 1.0)
                - compare_summary.get("average_correction_factor", 1.0)
            ),
            "good_ratio_delta": float(current_good_ratio - compare_good_ratio),
            "attention_window_delta": float(current_attention - compare_attention),
            "config_change_count": float(len(config_changes)),
        }

        difference_summary = [
            f"有效窗口变化 {int(deltas['valid_window_delta']):+d}。",
            f"平均 lag 变化 {deltas['average_lag_delta']:+.2f} s。",
            f"平均修正因子变化 {deltas['average_correction_factor_delta']:+.3f}。",
            f"QC 优良比例变化 {deltas['good_ratio_delta']:+.1%}。",
            f"异常窗口数变化 {int(deltas['attention_window_delta']):+d}。",
        ]
        if config_changes:
            difference_summary.append(f"配置存在 {len(config_changes)} 处差异，已纳入批次对比。")

        risk_summary: list[str] = []
        if deltas["average_correction_factor_delta"] > 0.05:
            risk_summary.append("当前批次平均修正因子明显升高，建议复核采样链与截止频率设置。")
        if deltas["good_ratio_delta"] < -0.1:
            risk_summary.append("当前批次优良窗口比例下降，建议优先查看 QC 时间条带和异常窗口。")
        if deltas["attention_window_delta"] > 0:
            risk_summary.append("当前批次待关注窗口增加，建议先核对 lag 可信度与高频损失。")
        if config_changes:
            risk_summary.append(f"发现配置差异：{'；'.join(config_changes[:3])}")
        if not risk_summary:
            risk_summary.append("当前批次与对比批次整体表现接近，未见明显风险抬升。")

        return BatchCompareResult(
            current_batch=self._batch_label(current),
            compare_batch=self._batch_label(compare),
            metric_deltas=deltas,
            difference_summary=difference_summary,
            changed_windows=changed_windows,
            risk_summary=risk_summary,
        )

    def _diff_config_snapshot(self, current: dict, compare: dict) -> list[str]:
        current_flat = self._flatten_dict(current)
        compare_flat = self._flatten_dict(compare)
        changes: list[str] = []
        for key in sorted(set(current_flat) | set(compare_flat)):
            if current_flat.get(key) == compare_flat.get(key):
                continue
            changes.append(f"{key}: {compare_flat.get(key, '--')} -> {current_flat.get(key, '--')}")
        return changes

    def _flatten_dict(self, payload: dict, prefix: str = "") -> dict[str, object]:
        flat: dict[str, object] = {}
        for key, value in payload.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(self._flatten_dict(value, full_key))
            else:
                flat[full_key] = value
        return flat

    def _changed_windows(self, current: SpectralRunResult, compare: SpectralRunResult) -> list[dict]:
        compare_lookup = {
            (
                window.start_time.strftime("%m-%d %H:%M"),
                window.end_time.strftime("%H:%M"),
            ): window
            for window in compare.windows
        }
        changed: list[dict] = []
        for window in current.windows:
            key = (window.start_time.strftime("%m-%d %H:%M"), window.end_time.strftime("%H:%M"))
            previous = compare_lookup.get(key)
            if previous is None:
                changed.append(
                    {
                        "window": self._window_label(window),
                        "change": "新增窗口",
                        "current_grade": window.qc_grade,
                        "compare_grade": "--",
                    }
                )
                continue
            if (
                window.qc_grade != previous.qc_grade
                or abs(window.correction_factor - previous.correction_factor) >= 0.05
                or abs(window.lag_seconds - previous.lag_seconds) >= 0.2
                or window.anomaly_type != previous.anomaly_type
            ):
                changed.append(
                    {
                        "window": self._window_label(window),
                        "change": f"{previous.qc_grade}->{window.qc_grade} / {previous.anomaly_type}->{window.anomaly_type}",
                        "current_grade": window.qc_grade,
                        "compare_grade": previous.qc_grade,
                        "lag_delta": round(window.lag_seconds - previous.lag_seconds, 3),
                        "correction_delta": round(window.correction_factor - previous.correction_factor, 3),
                    }
                )
        return changed[:12]

    def _previous_spectral_run(self, current_run_id: str | None) -> SpectralRunResult | None:
        previous = self.run_result_store.get_previous_batch(current_run_id)
        if previous is not None:
            return previous
        if not self.spectral_runs:
            return None
        if current_run_id is None:
            return self.spectral_runs[1] if len(self.spectral_runs) > 1 else None
        for index, result in enumerate(self.spectral_runs):
            if result.run_id == current_run_id:
                return self.spectral_runs[index + 1] if index + 1 < len(self.spectral_runs) else None
        return None

    def _empty_batch_compare_payload(
        self,
        *,
        current: SpectralRunResult | None = None,
        compare: SpectralRunResult | None = None,
        run_result: SpectralRunResult | None = None,
    ) -> dict:
        active = current or run_result
        return {
            "current_batch": self._batch_label(active) if active is not None else "",
            "compare_batch": self._batch_label(compare) if compare is not None else "",
            "difference_summary": ["No previous batch is available for comparison yet."],
            "metric_deltas": {},
            "changed_windows": [],
            "risk_summary": ["Generate at least two real batches before comparing them."],
        }

    def _collect_spectral_rows(self) -> list[NormalizedHFFrame]:
        selected_uid = self.selected_device_uid
        if selected_uid is not None:
            rows = self.realtime_rows(device_uid=selected_uid)
            if rows:
                return rows
        return self.realtime_rows()

    def _serialize_window_for_workspace(self, window: WindowSpectralResult) -> dict:
        period = f"{window.start_time:%H:%M}-{window.end_time:%H:%M}"
        dominant_components = [
            f"{label}: {value:.3f}"
            for label, value in sorted(
                (
                    ("tube", float(window.correction_factor_components.get("tube_component", 1.0))),
                    ("separation", float(window.correction_factor_components.get("separation_component", 1.0))),
                    ("path", float(window.correction_factor_components.get("path_component", 1.0))),
                    ("phase", float(window.correction_factor_components.get("phase_component", 1.0))),
                ),
                key=lambda item: abs(item[1] - 1.0),
                reverse=True,
            )
            if abs(value - 1.0) > 1e-6
        ]
        return {
            "window_id": window.window_id,
            "label": self._window_label(window),
            "period": period,
            "qc_grade": window.qc_grade,
            "anomaly_type": window.anomaly_type,
            "lag_s": f"{window.lag_seconds:.2f} s",
            "correction_factor": f"{window.correction_factor:.3f}",
            "reason": window.reason,
            "dominant_correction_components": dominant_components,
            "correction_factor_detail": deepcopy(window.correction_factor_detail),
            "effective_cutoff_info": deepcopy(window.effective_cutoff_info),
            "provenance_notes": list(window.provenance_notes),
            "model_version": window.model_version,
        }

    def _batch_label(self, result: SpectralRunResult) -> str:
        label = result.summary.get("batch_label")
        if label:
            return str(label)
        return f"{result.created_at:%Y-%m-%d %H:%M} / {result.run_id[-6:]}"

    def _window_label(self, window: WindowSpectralResult) -> str:
        return f"{window.start_time:%Y-%m-%d %H:%M}-{window.end_time:%H:%M}"

    def _format_confidence(self, value: float) -> str:
        if value >= 0.8:
            tone = "高"
        elif value >= 0.55:
            tone = "中"
        else:
            tone = "低"
        return f"{tone} ({value:.2f})"

    def set_mode(self, device_uid: str, mode: int) -> TransactionRecord:
        entry = self._get_device(device_uid)
        record = self._execute_transaction(
            entry,
            label=f"切换到 MODE{mode}",
            command_text=entry.builder.set_mode(mode, target_id=entry.config.device_id),
        )
        if record.status.value == "SUCCEEDED":
            entry.runtime.mode = int(mode)
        self.devices_changed.emit()
        return record

    def set_comm_way(self, device_uid: str, active_send: bool) -> TransactionRecord:
        entry = self._get_device(device_uid)
        label = "切换到主动发送" if active_send else "切换到按需读取"
        record = self._execute_transaction(
            entry,
            label=label,
            command_text=entry.builder.set_comm_way(active_send, target_id=entry.config.device_id),
        )
        if record.status.value == "SUCCEEDED":
            entry.runtime.active_send = bool(active_send)
            self.acquisition.update_session(device_uid, active_send=entry.runtime.active_send)
        self.devices_changed.emit()
        return record

    def set_ftd_frequency(self, device_uid: str, hz: int) -> TransactionRecord:
        entry = self._get_device(device_uid)
        record = self._execute_transaction(
            entry,
            label="设置输出频率",
            command_text=entry.builder.set_ftd_frequency(hz, target_id=entry.config.device_id),
        )
        if record.status.value == "SUCCEEDED":
            entry.runtime.ftd_hz = int(hz)
            self.acquisition.update_session(device_uid, ftd_hz=entry.runtime.ftd_hz)
        self.devices_changed.emit()
        return record

    def set_average_params(self, device_uid: str, *, avg_co2: int, avg_h2o: int) -> list[TransactionRecord]:
        entry = self._get_device(device_uid)
        commands = [
            ("设置水汽平均参数", entry.builder.set_average(1, avg_h2o, target_id=entry.config.device_id)),
            ("设置二氧化碳平均参数", entry.builder.set_average(2, avg_co2, target_id=entry.config.device_id)),
        ]
        records = [self._execute_transaction(entry, label=label, command_text=command) for label, command in commands]
        if all(record.status.value == "SUCCEEDED" for record in records):
            entry.runtime.average_co2 = int(avg_co2)
            entry.runtime.average_h2o = int(avg_h2o)
        self.devices_changed.emit()
        return records

    def set_filter_params(self, device_uid: str, *, window_n: int) -> list[TransactionRecord]:
        entry = self._get_device(device_uid)
        record = self._execute_transaction(
            entry,
            label="设置滤波参数",
            command_text=entry.builder.set_filter(window_n, target_id=entry.config.device_id),
        )
        if record.status.value == "SUCCEEDED":
            entry.runtime.filter_window = int(window_n)
        self.devices_changed.emit()
        return [record]

    def read_frame_once(self, device_uid: str) -> TransactionRecord:
        entry = self._get_device(device_uid)
        record = self._execute_transaction(
            entry,
            label="读取一帧",
            command_text=entry.builder.read_frame(target_id=entry.config.device_id),
            timeout_s=0.45,
        )
        self.devices_changed.emit()
        return record

    def read_frame_selected(self) -> TransactionRecord:
        if not self.selected_device_uid:
            raise RuntimeError("请先选择设备。")
        return self.read_frame_once(self.selected_device_uid)

    def broadcast_probe(self, device_uid: str) -> TransactionRecord:
        entry = self._get_device(device_uid)
        return self._execute_transaction(
            entry,
            label="FFF 广播配置探测",
            command_text=entry.builder.broadcast_probe(),
            dangerous=True,
        )

    def broadcast_config_selected(self) -> TransactionRecord:
        if not self.selected_device_uid:
            raise RuntimeError("请先选择设备，再执行广播配置。")
        return self.broadcast_probe(self.selected_device_uid)

    def read_coefficients(self, device_uid: str, group_index: int) -> tuple[TransactionRecord, dict[str, float] | None]:
        entry = self._get_device(device_uid)
        record = self._execute_transaction(
            entry,
            label=f"读取系数组 {group_index}",
            command_text=entry.builder.read_coefficients(group_index, target_id=entry.config.device_id),
            timeout_s=0.5,
        )
        return record, parse_coefficient_line(record.response_text)

    def write_coefficients(self, device_uid: str, *, group_index: int, values: list[float]) -> TransactionRecord:
        entry = self._get_device(device_uid)
        return self._execute_transaction(
            entry,
            label=f"写入系数组 {group_index}",
            command_text=entry.builder.write_coefficients(
                group_index,
                encode_coefficients(values),
                target_id=entry.config.device_id,
            ),
            dangerous=True,
            timeout_s=0.5,
        )

    def write_device_id(self, device_uid: str, *, new_device_id: str) -> TransactionRecord:
        entry = self._get_device(device_uid)
        normalized_id = normalize_device_id(new_device_id)
        record = self._execute_transaction(
            entry,
            label="写入设备 ID",
            command_text=entry.builder.write_device_id(normalized_id, target_id="FFF"),
            dangerous=True,
            timeout_s=0.5,
        )
        if record.status.value == "SUCCEEDED":
            entry.config.device_id = normalized_id
            self.metadata_store.upsert_device(entry.config)
            self.acquisition.update_session(device_uid, device_id=normalized_id)
        self.devices_changed.emit()
        return record

    def export_realtime_buffer(self, target_path: Path) -> Path:
        if not self.selected_device_uid:
            raise RuntimeError("请先选择设备，再导出缓存。")
        rows = [frame.to_record() for frame in self.realtime_buffer.snapshot(device_uid=self.selected_device_uid)]
        if not rows:
            raise RuntimeError("当前没有可导出的缓存数据，请先开始采集或读取一帧。")
        path = self.hf_store.export_buffer_to_csv(rows, target_path)
        self._append_log("info", f"已导出缓存数据到 {path}")
        return path

    def export_realtime_segment(self, target_path: Path, *, device_uid: str, seconds: float) -> Path:
        rows = [frame.to_record() for frame in self.realtime_buffer.snapshot(device_uid=device_uid, seconds=seconds)]
        if not rows:
            raise RuntimeError("当前时间窗内没有可导出的片段。")
        path = self.hf_store.export_buffer_to_csv(rows, target_path)
        self._append_log("info", f"已导出最近 {int(seconds)} 秒数据片段到 {path}")
        return path

    def clear_realtime_buffer(self, device_uid: str | None = None) -> None:
        self.realtime_buffer.clear(device_uid=device_uid)
        message = "已清空全部实时缓存。" if device_uid is None else "已清空当前设备的实时显示缓存。"
        self._append_log("info", message)
        self.frame_received.emit(None)

    def mark_anomaly(self, device_uid: str, note: str) -> EventRecord:
        entry = self._get_device(device_uid)
        latest_frame = self.recent_raw_frames(device_uid=device_uid, limit=1)
        related = latest_frame[0].received_at if latest_frame else datetime.now()
        event = EventRecord(
            event_id=uuid4().hex[:10],
            created_at=datetime.now(),
            device_uid=device_uid,
            device_id=entry.config.device_id,
            severity="warning",
            title="人工标记异常",
            message=note.strip() or "现场人员标记了可疑数据，请结合图表和原始帧复核。",
            category="manual_mark",
            related_timestamp=related,
            raw_text=latest_frame[0].raw_text if latest_frame else "",
            parsed_snapshot=dict(latest_frame[0].parsed) if latest_frame else {},
        )
        self.events.appendleft(event)
        self._append_log("warning", f"{entry.config.label} 已标记异常：{event.message}")
        self.events_changed.emit()
        return event

    def device_cards(self) -> list[dict]:
        cards: list[dict] = []
        with self._lock:
            for uid, entry in self.devices.items():
                latest = self._latest_numeric_frame(uid)
                status_level, status_text = self._device_health(entry, latest)
                cards.append(
                    {
                        "uid": uid,
                        "label": entry.config.label,
                        "port": entry.config.port,
                        "baudrate": entry.config.baudrate,
                        "device_id": entry.config.device_id,
                        "connected": entry.runtime.connected,
                        "mode": entry.runtime.mode,
                        "active_send": entry.runtime.active_send,
                        "ftd_hz": entry.runtime.ftd_hz,
                        "average_co2": entry.runtime.average_co2,
                        "average_h2o": entry.runtime.average_h2o,
                        "filter_window": entry.runtime.filter_window,
                        "co2_ppm": latest.co2_ppm if latest else None,
                        "h2o_mmol": latest.h2o_mmol if latest else None,
                        "pressure_kpa": latest.pressure_kpa if latest else None,
                        "last_frame_time": entry.runtime.last_frame_time,
                        "last_frame_quality": entry.runtime.last_frame_quality.value,
                        "last_message": entry.runtime.last_message,
                        "status_level": status_level,
                        "status_text": status_text,
                        "is_collecting": self._is_collecting(entry),
                        "is_abnormal": status_level in {"warning", "danger"},
                        "is_selected": uid == self.selected_device_uid,
                    }
                )
        cards.sort(key=lambda row: (not row["is_selected"], row["label"]))
        return cards

    def status_summary(self) -> dict:
        cards = self.device_cards()
        online_devices = sum(1 for card in cards if card["connected"])
        abnormal_devices = sum(1 for card in cards if card["is_abnormal"])
        sampling_devices = sum(1 for card in cards if card["is_collecting"])
        latest_event = next((event for event in self.events if event.severity in {"warning", "error"}), None)
        last_update = self._latest_update_time()
        return {
            "total_devices": len(cards),
            "online_devices": online_devices,
            "abnormal_devices": abnormal_devices,
            "sampling_devices": sampling_devices,
            "selected_device": self.selected_device().config.label if self.selected_device() else "未选择设备",
            "view_mode": "工程师视图" if self.view_mode == "engineer" else "操作员视图",
            "recent_alarm": latest_event.message if latest_event else "暂无需要处理的告警。",
            "last_updated_at": last_update.strftime("%H:%M:%S") if last_update else "尚未收到数据",
        }

    def recent_transactions(self, *, device_uid: str | None = None, limit: int | None = None) -> list[TransactionRecord]:
        rows = self.transaction_manager.recent()
        if device_uid is not None:
            rows = [row for row in rows if row.device_uid == device_uid]
        if limit is None:
            return rows
        return rows[:limit]

    def recent_raw_frames(self, *, device_uid: str | None = None, limit: int = 20) -> list[ProtocolFrame]:
        if device_uid is None:
            return list(self.raw_frames)[:limit]
        return list(self.device_frame_history.get(device_uid, deque()))[:limit]

    def recent_events(self, *, device_uid: str | None = None, limit: int = 20) -> list[EventRecord]:
        rows = list(self.events)
        if device_uid is not None:
            rows = [row for row in rows if row.device_uid == device_uid]
        return rows[:limit]

    def selected_device(self) -> ManagedDevice | None:
        if not self.selected_device_uid:
            return None
        return self.devices.get(self.selected_device_uid)

    def selected_device_realtime_rows(self, *, seconds: float | None = None) -> list[NormalizedHFFrame]:
        return self.realtime_rows(device_uid=self.selected_device_uid, seconds=seconds)

    def realtime_rows(self, *, device_uid: str | None = None, seconds: float | None = None) -> list[NormalizedHFFrame]:
        if device_uid is None:
            return self.realtime_buffer.snapshot(seconds=seconds)
        return self.realtime_buffer.snapshot(device_uid=device_uid, seconds=seconds)

    def realtime_statistics(self, device_uid: str, *, window_s: float) -> dict[str, float | int | str]:
        rows = self.realtime_rows(device_uid=device_uid, seconds=window_s)
        frames = self.recent_raw_frames(device_uid=device_uid, limit=240)
        if not rows and not frames:
            return {
                "sample_rate": 0.0,
                "valid_frame_rate": 0.0,
                "residual_frame_rate": 0.0,
                "anomaly_count": 0,
            }

        if rows:
            end_time = rows[-1].timestamp
            threshold = end_time.timestamp() - max(1.0, float(window_s))
        else:
            end_time = frames[0].received_at
            threshold = end_time.timestamp() - max(1.0, float(window_s))

        window_frames = [frame for frame in frames if frame.received_at.timestamp() >= threshold]
        span_s = max(1.0, min(float(window_s), (end_time.timestamp() - threshold)))
        valid_count = sum(1 for frame in window_frames if frame.quality in {FrameQuality.FULL, FrameQuality.PARTIAL})
        residual_count = sum(1 for frame in window_frames if frame.quality in {FrameQuality.TRUNCATED, FrameQuality.CORRUPTED, FrameQuality.UNKNOWN})
        anomaly_count = sum(
            1
            for event in self.recent_events(device_uid=device_uid, limit=60)
            if event.created_at.timestamp() >= threshold and event.severity in {"warning", "error"}
        )
        return {
            "sample_rate": len(window_frames) / span_s,
            "valid_frame_rate": valid_count / span_s,
            "residual_frame_rate": residual_count / span_s,
            "anomaly_count": anomaly_count,
        }

    def diagnostic_suggestions(self, device_uid: str | None) -> list[str]:
        if device_uid is None:
            return [
                "先在设备卡片中选择一台设备，再进入详情或实时采集。",
                "如果现场没有真机，可先用 SIM 设备验证交互流程。",
            ]
        entry = self._get_device(device_uid)
        suggestions: list[str] = []
        if not entry.runtime.connected:
            suggestions.append("先连接设备，再读取一帧确认链路是否通畅。")
            suggestions.append("如果持续离线，请核对 COM 口、波特率和供电状态。")
            return suggestions
        if not self._latest_numeric_frame(device_uid):
            suggestions.append("设备已连接但还没有有效数据，建议先读取一帧。")
        quality = entry.runtime.last_frame_quality
        if quality == FrameQuality.CORRUPTED:
            suggestions.append("最近出现损坏帧，优先检查波特率配置和串口接线干扰。")
        elif quality == FrameQuality.TRUNCATED:
            suggestions.append("最近出现截断帧，建议降低输出频率或检查线路稳定性。")
        elif quality == FrameQuality.PARTIAL:
            suggestions.append("最近收到不完整帧，建议切换到工程师视图查看解析结果。")
        if entry.runtime.active_send:
            suggestions.append("当前为主动发送模式，适合连续观察趋势。")
        else:
            suggestions.append("当前为按需读取模式，适合调试配置和单帧核验。")
        suggestions.append("如需深度排障，可进入单设备详情页查看事务链路和原始帧。")
        return suggestions[:4]

    def error_attribution(self, device_uid: str) -> list[str]:
        entry = self._get_device(device_uid)
        latest_frame = self.recent_raw_frames(device_uid=device_uid, limit=1)
        latest = latest_frame[0] if latest_frame else None
        notes: list[str] = []
        if not entry.runtime.connected:
            notes.append("设备处于离线状态，当前无法判断数据质量。")
            notes.append("优先检查串口连接、波特率和仪器供电。")
            return notes
        if latest is None:
            return ["尚未接收到原始帧，建议先读取一帧或开始采集。"]
        if latest.quality == FrameQuality.CORRUPTED:
            notes.append("最近一次原始帧已损坏，常见原因是波特率不匹配或线路干扰。")
        elif latest.quality == FrameQuality.TRUNCATED:
            notes.append("最近一次原始帧被截断，可能是输出频率过高或接收窗口过短。")
        elif latest.quality == FrameQuality.ACK_ONLY:
            notes.append("最近一次响应是设备确认应答，这通常表示配置命令已被接收。")
        elif latest.quality == FrameQuality.PARTIAL:
            notes.append("最近一次原始帧字段不完整，主测量值可用，但建议继续核验。")
        else:
            notes.append("最近数据质量稳定，没有发现明显的协议层异常。")
        for event in self.recent_events(device_uid=device_uid, limit=2):
            if event.severity in {"warning", "error"}:
                notes.append(event.message)
        return notes[:4]

    def device_detail_snapshot(self, device_uid: str) -> dict:
        entry = self._get_device(device_uid)
        latest_frame = self.recent_raw_frames(device_uid=device_uid, limit=1)
        latest_numeric = self._latest_numeric_frame(device_uid)
        return {
            "entry": entry,
            "latest_frame": latest_frame[0] if latest_frame else None,
            "latest_numeric": latest_numeric,
            "transactions": self.recent_transactions(device_uid=device_uid, limit=24),
            "events": self.recent_events(device_uid=device_uid, limit=16),
            "suggestions": self.diagnostic_suggestions(device_uid),
            "attribution": self.error_attribution(device_uid),
            "stats": self.realtime_statistics(device_uid, window_s=120.0),
        }

    def context_snapshot(self) -> dict:
        if self.selected_page == "project_site":
            report = self.project_completeness_report()
            return {
                "page": self.selected_page,
                "project": self.project_profile,
                "site": self.site_profile,
                "project_inspector": {
                    "score": report["score"],
                    "missing_items": report["missing_items"],
                    "parameter_note": report["parameter_note"],
                    "risks": report["risks"],
                    "section": self.project_nav_section,
                },
                "logs": list(self.logs)[:12],
            }
        if self.selected_page == "ec_processing":
            report = self.ec_processing_report()
            return {
                "page": self.selected_page,
                "ec_inspector": {
                    "score": report["score"],
                    "current_method": report["current_method"],
                    "applicable": report["applicable"],
                    "recommended": report["recommended"],
                    "risks": report["risks"],
                    "step": self.ec_nav_step,
                },
                "logs": list(self.logs)[:12],
            }
        if self.selected_page == "spectral_qc":
            report = self.spectral_qc_report()
            return {
                "page": self.selected_page,
                "spectral_qc_inspector": {
                    "section": report["section"],
                    "section_note": report["section_note"],
                    "lag_confidence": report["lag_confidence"],
                    "high_freq_loss_risk": report["high_freq_loss_risk"],
                    "good_windows": report["good_windows"],
                    "attention_windows": report["attention_windows"],
                    "current_window": report["current_window"],
                    "current_grade": report["current_grade"],
                    "recent_reason": report["recent_reason"],
                    "correction_factor": report["correction_factor"],
                    "risks": report["risks"],
                    "actions": report["actions"],
                },
                "logs": list(self.logs)[:12],
            }
        if self.selected_page == "report_center":
            report = self.report_center_report()
            if report["report_key"] == "eddypro_compare":
                compare = report.get("eddypro_compare", {})
                attribution = report.get("eddypro_attribution", {})
                summary = compare.get("summary_metrics", {})
                result: dict = {
                    "page": self.selected_page,
                    "eddypro_compare_inspector": {
                        "status": "就绪" if compare.get("status") == "ready" else "空状态",
                        "compare_id": compare.get("compare_id", ""),
                        "current_source": compare.get("current_source", "未加载当前结果"),
                        "reference_source": compare.get("reference_source", "未加载参考结果"),
                        "matched_window_count": summary.get("matched_window_count", 0),
                        "avg_lag_delta": self._format_optional_float(summary.get("avg_lag_delta"), 3),
                        "avg_flux_delta": self._format_optional_float(summary.get("avg_flux_delta"), 6),
                        "qc_match_ratio": f"{float(summary.get('qc_match_ratio') or 0.0):.1%}",
                        "risk_summary": compare.get("risk_summary", []),
                        "actions": [
                            "查看窗口差异表前 10 项",
                            "检查 lag 偏差较大的窗口",
                            "检查 flux 偏差较大的窗口",
                            "核对字段映射与时间窗口对齐方式",
                        ],
                    },
                }
                if attribution.get("status") == "ready":
                    window_rows = list(attribution.get("window_rows", []))
                    recommendations = [
                        str(row.get("recommendation", "")).strip()
                        for row in window_rows
                        if str(row.get("recommendation", "")).strip()
                    ]
                    result["eddypro_attribution_inspector"] = {
                        "status": "就绪",
                        "dominant_causes": attribution.get("dominant_causes", []),
                        "risk_level": attribution.get("risk_level", "未知"),
                        "summary_text": attribution.get("summary_text", "当前还没有对标归因结果"),
                        "recommendations": recommendations[:4],
                        "window_coverage_count": attribution.get("coverage", {}).get("window_coverage_count", 0),
                        "attribution_count": attribution.get("coverage", {}).get("attribution_count", 0),
                        "actions": [
                            "优先检查 lag 偏差较大的窗口",
                            "优先检查管路衰减相关元数据",
                            "优先检查站点/字段映射完整性",
                            "复核 stationarity / turbulence 评分较差窗口",
                        ],
                    }
                result["logs"] = list(self.logs)[:12]
                return result
            return {
                "page": self.selected_page,
                "report_inspector": {
                    "view_mode": report["view_mode"],
                    "title": report["title"],
                    "source": report["source"],
                    "updated_at": report["updated_at"],
                    "export_status": report["export_status"],
                    "export_options": report["export_options"],
                    "file_info": report["file_info"],
                    "versions": report["versions"],
                    "usage": report["usage"],
                    "conclusions": report["conclusions"],
                    "batch_compare": report["batch_compare"],
                },
                "logs": list(self.logs)[:12],
            }
        entry = self.selected_device()
        device_uid = entry.config.uid if entry else None
        last_frame_rows = self.recent_raw_frames(device_uid=device_uid, limit=1) if device_uid else self.recent_raw_frames(limit=1)
        last_tx_rows = self.recent_transactions(device_uid=device_uid, limit=1) if device_uid else self.recent_transactions(limit=1)
        return {
            "page": self.selected_page,
            "view_mode": self.view_mode,
            "device": entry,
            "last_frame": last_frame_rows[0] if last_frame_rows else None,
            "last_transaction": last_tx_rows[0] if last_tx_rows else None,
            "recent_transactions": self.recent_transactions(device_uid=device_uid, limit=5) if device_uid else self.recent_transactions(limit=5),
            "suggestions": self.diagnostic_suggestions(device_uid),
            "recent_events": self.recent_events(device_uid=device_uid, limit=5) if device_uid else self.recent_events(limit=5),
            "project": self.project_profile,
            "site": self.site_profile,
            "logs": list(self.logs)[:12],
        }

    def _empty_report_payloads(self) -> dict:
        payloads = {
            "run_summary": "运行摘要",
            "device_status": "设备状态报告",
            "acquisition_quality": "采集质量报告",
            "ec_results": "EC 结果报告",
            "spectral_qc": "谱修正与 QC 报告",
            "anomaly_events": "异常事件报告",
            "site_method": "站点方法说明",
            "evidence_pack": "证据包",
            "eddypro_compare": "EddyPro 对标报告",
            "method_provenance": "方法溯源",
            "method_compare": "Method Compare",
        }
        return {
            key: {
                "title": title,
                "source": "暂无真实批次",
                "updated_at": "--",
                "metrics": [("状态", "未运行"), ("批次", "--"), ("窗口", "0"), ("导出", "未生成")],
                "plot_series": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("状态", "未生成", "请先运行谱分析或准备 EddyPro 对标结果。")],
                "conclusions": ["当前页面仅显示真实运行结果，请先运行谱分析或生成 EddyPro 对标结果。"],
                "export_options": ["导出当前报告", "导出证据包"],
                "file_info": {"状态": "尚未导出"},
                "versions": [],
                "usage": ["先生成真实结果，再在报告中心查看摘要。"],
            }
            for key, title in payloads.items()
        }

    def _empty_eddypro_compare_payload(self) -> dict:
        return {
            "status": "empty",
            "compare_id": "",
            "current_source": "未加载当前结果",
            "reference_source": "未加载参考结果",
            "summary_metrics": {
                "current_window_count": 0,
                "reference_window_count": 0,
                "matched_window_count": 0,
                "unmatched_current_count": 0,
                "unmatched_reference_count": 0,
                "avg_lag_delta": None,
                "avg_flux_delta": None,
                "avg_correction_factor_delta": None,
                "qc_match_ratio": 0.0,
            },
            "risk_summary": ["当前还没有 EddyPro 对标结果"],
            "window_rows": [],
            "files": {},
            "notes": ["当前还没有 EddyPro 对标结果", "请先选择参考结果并运行对标比较"],
            "message": "当前还没有 EddyPro 对标结果\n请先选择参考结果并运行对标比较",
        }

    def _empty_eddypro_attribution_payload(self) -> dict:
        return {
            "status": "empty",
            "attribution_id": "",
            "compare_id": "",
            "dominant_causes": [],
            "secondary_causes": [],
            "risk_level": "未知",
            "summary_text": "当前还没有对标归因结果",
            "notes": ["当前还没有对标归因结果", "请先运行 EddyPro 对标比较"],
            "window_rows": [],
            "coverage": {
                "attribution_count": 0,
                "window_coverage_count": 0,
            },
            "message": "当前还没有对标归因结果\n请先运行 EddyPro 对标比较",
        }

    def _eddypro_compare_workspace_state(self) -> dict:
        if self.latest_eddypro_compare_result is None:
            return self._empty_eddypro_compare_payload()
        return self._eddypro_compare_payload_from_result(
            self.latest_eddypro_compare_result,
            self.latest_eddypro_compare_manifest or {},
        )

    def _build_eddypro_attribution_result(
        self,
        compare_result: EddyProCompareResult | None,
    ) -> CompareAttributionResult | None:
        if compare_result is None:
            return None
        try:
            comparator = EddyProComparator(self.runtime_root)
            return comparator.build_attribution(
                compare_result,
                current_runs={
                    "rp_run": self.current_rp_run(),
                    "spectral_run": self.current_spectral_run(),
                },
                reference_meta=dict(compare_result.reference_source or {}),
            )
        except Exception:
            return None

    def _eddypro_attribution_workspace_state(self) -> dict:
        compare_result = self.latest_eddypro_compare_result
        if compare_result is None:
            self.latest_eddypro_attribution_result = None
            return self._empty_eddypro_attribution_payload()
        if (
            self.latest_eddypro_attribution_result is None
            or self.latest_eddypro_attribution_result.compare_id != compare_result.compare_id
        ):
            self.latest_eddypro_attribution_result = self._build_eddypro_attribution_result(compare_result)
        if self.latest_eddypro_attribution_result is None:
            return self._empty_eddypro_attribution_payload()
        return self._eddypro_attribution_payload_from_result(self.latest_eddypro_attribution_result)

    def _eddypro_compare_payload_from_result(
        self,
        result: EddyProCompareResult,
        manifest: dict[str, object],
    ) -> dict:
        summary_metrics = dict(result.summary_metrics)
        window_rows = []
        for window in result.window_results[:10]:
            row = window.to_dict()
            row["notes"] = " | ".join(window.notes)
            window_rows.append(row)
        return {
            "status": "ready",
            "compare_id": result.compare_id,
            "current_source": self._describe_compare_source(result.current_source),
            "reference_source": self._describe_compare_source(result.reference_source),
            "summary_metrics": summary_metrics,
            "risk_summary": list(result.risk_summary),
            "window_rows": window_rows,
            "files": dict(manifest.get("files", {})) if isinstance(manifest, dict) else {},
            "notes": list(result.notes),
            "message": "",
        }

    def _eddypro_attribution_payload_from_result(self, result: CompareAttributionResult) -> dict:
        window_rows = []
        for window in result.window_attributions[:10]:
            window_rows.append(
                {
                    "window_key": window.window_key,
                    "dominant_cause": window.dominant_cause,
                    "secondary_causes": list(window.secondary_causes),
                    "confidence": round(float(window.confidence), 3),
                    "recommendation": window.recommendation,
                    "notes": " | ".join(window.notes),
                }
            )
        return {
            "status": "ready",
            "attribution_id": result.attribution_id,
            "compare_id": result.compare_id,
            "dominant_causes": list(result.dominant_causes),
            "secondary_causes": list(result.secondary_causes),
            "risk_level": result.risk_level,
            "summary_text": result.summary_text,
            "notes": list(result.notes),
            "window_rows": window_rows,
            "coverage": {
                "attribution_count": len(result.window_attributions),
                "window_coverage_count": len(result.window_attributions),
            },
            "message": "",
        }

    def _eddypro_report_payload(self) -> dict:
        compare = self.report_center_workspace.get("eddypro_compare", self._empty_eddypro_compare_payload())
        attribution = self.report_center_workspace.get("eddypro_attribution", self._empty_eddypro_attribution_payload())
        if compare.get("status") != "ready":
            compare_message = str(compare.get("message") or "当前还没有 EddyPro 对标结果\n请先选择参考结果并运行对标比较")
            attribution_message = str(attribution.get("message") or "当前还没有对标归因结果\n请先运行 EddyPro 对标比较")
            return {
                "title": "EddyPro 对标报告",
                "source": "对标摘要",
                "updated_at": "--",
                "report_key": "eddypro_compare",
                "metrics": [("状态", "空"), ("已匹配", "0"), ("窗口差异", "0"), ("QC 一致率", "0.0%")],
                "plot_series": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("状态", "未生成", compare_message), ("归因状态", "未生成", attribution_message)],
                "conclusions": [compare_message, attribution_message],
                "export_options": ["运行 EddyPro 对标后查看摘要", "核对参考文件映射"],
                "file_info": {"状态": "尚无 EddyPro 对标导出"},
                "versions": [],
                "usage": ["请先运行 EddyPro 对标比较。"],
            }

        summary = compare.get("summary_metrics", {})
        qc_ratio = float(summary.get("qc_match_ratio") or 0.0)
        risk_summary = [str(item) for item in compare.get("risk_summary", [])]
        window_rows = list(compare.get("window_rows", []))
        dominant_causes = [str(item) for item in attribution.get("dominant_causes", [])]
        secondary_causes = [str(item) for item in attribution.get("secondary_causes", [])]
        attribution_rows = list(attribution.get("window_rows", []))
        table_rows = [
            ("compare_id", compare.get("compare_id", "--"), "最近一次 EddyPro 对标任务 ID"),
            ("当前来源", compare.get("current_source", "--"), "本软件当前真实导出结果目录"),
            ("参考来源", compare.get("reference_source", "--"), "EddyPro 参考结果目录或映射"),
            ("current_window_count", summary.get("current_window_count", 0), "当前结果窗口数量"),
            ("reference_window_count", summary.get("reference_window_count", 0), "参考结果窗口数量"),
            ("matched_window_count", summary.get("matched_window_count", 0), "成功匹配的窗口数量"),
            ("unmatched_current_count", summary.get("unmatched_current_count", 0), "当前结果未匹配窗口数量"),
            ("unmatched_reference_count", summary.get("unmatched_reference_count", 0), "参考结果未匹配窗口数量"),
            ("avg_lag_delta", self._format_optional_float(summary.get("avg_lag_delta"), 3), "平均 lag 绝对偏差"),
            ("avg_flux_delta", self._format_optional_float(summary.get("avg_flux_delta"), 6), "平均 flux 绝对偏差"),
            (
                "avg_correction_factor_delta",
                self._format_optional_float(summary.get("avg_correction_factor_delta"), 4),
                "平均修正因子绝对偏差",
            ),
            ("qc_match_ratio", f"{qc_ratio:.1%}", "QC 等级一致率"),
            ("risk_summary", " / ".join(risk_summary) if risk_summary else "--", "自动风险摘要"),
        ]
        if attribution.get("status") == "ready":
            table_rows.extend(
                [
                    ("dominant_causes", " / ".join(dominant_causes) if dominant_causes else "--", "优先展示的主要归因"),
                    ("secondary_causes", " / ".join(secondary_causes) if secondary_causes else "--", "次级归因"),
                    ("risk_level", attribution.get("risk_level", "--"), "归因层风险等级"),
                    ("summary_text", attribution.get("summary_text", "--"), "归因摘要解释"),
                    ("notes", " / ".join(str(item) for item in attribution.get("notes", [])) or "--", "归因说明"),
                ]
            )
        else:
            table_rows.append(
                ("归因状态", "未生成", str(attribution.get("message") or "当前还没有对标归因结果\n请先运行 EddyPro 对标比较"))
            )
        for row in window_rows:
            table_rows.append(
                (
                    row.get("window_key", "--"),
                    f"lagΔ={self._format_optional_float(row.get('lag_delta'), 3)} | fluxΔ={self._format_optional_float(row.get('flux_delta'), 6)}",
                    row.get("notes", ""),
                )
            )
        for row in attribution_rows:
            secondary_text = ", ".join(row.get("secondary_causes", [])) or "--"
            table_rows.append(
                (
                    row.get("window_key", "--"),
                    f"{row.get('dominant_cause', '--')} | conf={self._format_optional_float(row.get('confidence'), 3)}",
                    f"secondary={secondary_text} | {row.get('recommendation', '')}",
                )
            )
        return {
            "title": "EddyPro 对标报告",
            "source": compare.get("current_source", "--"),
            "updated_at": str(summary.get("created_at", "--")),
            "report_key": "eddypro_compare",
            "metrics": [
                ("主要归因", " / ".join(dominant_causes[:1]) if dominant_causes else "未生成"),
                ("风险等级", str(attribution.get("risk_level", "--"))),
                ("已匹配窗口", str(summary.get("matched_window_count", 0))),
                ("QC 一致率", f"{qc_ratio:.1%}"),
            ],
            "plot_series": [
                abs(float(row.get("lag_delta"))) if row.get("lag_delta") not in (None, "") else 0.0 for row in window_rows
            ],
            "table_headers": ["项目", "数值", "说明"],
            "table_rows": table_rows[:33],
            "conclusions": (
                [str(attribution.get("summary_text"))]
                + risk_summary
                + [str(item) for item in attribution.get("notes", [])[:2]]
            )[:4]
            or ["当前未发现显著 EddyPro 对标风险。"],
            "export_options": ["查看窗口差异表前 10 项", "检查 lag 偏差较大的窗口", "检查 flux 偏差较大的窗口"],
            "file_info": {"状态": "已生成 EddyPro 对标结果", **{key: str(value) for key, value in compare.get("files", {}).items()}},
            "versions": [
                f"compare_id：{compare.get('compare_id', '--')}",
                f"attribution_id：{attribution.get('attribution_id', '--')}",
                f"当前来源：{compare.get('current_source', '--')}",
                f"参考来源：{compare.get('reference_source', '--')}",
            ],
            "usage": [
                "优先看归因摘要，再回看窗口差异表前 10 项。",
                "若 lag 归因靠前，优先检查 lag 偏差较大的窗口。",
                "若传递函数分项归因靠前，优先检查对应元数据与 provenance。",
            ],
        }

    def _benchmark_cockpit_payload(self, run_result: SpectralRunResult) -> dict:
        from core.ec_rp.analysis import list_available_references, generate_reference_provenance
        rp_runs = self.rp_runs
        rp_result = rp_runs[-1] if rp_runs else None
        available_refs = list_available_references()
        ref_options = [r["reference_id"] for r in available_refs]
        ref_details = {r["reference_id"]: r for r in available_refs}
        ref_provenance_map: dict[str, dict] = {}
        for ref in available_refs:
            ref_id = ref["reference_id"]
            json_path = ref.get("json_path", "")
            if json_path:
                try:
                    prov = generate_reference_provenance(json_path)
                    ref_provenance_map[ref_id] = prov
                except Exception:
                    pass
        if rp_result is None or not rp_result.windows:
            return {
                "report_key": "benchmark_cockpit",
                "title": "Benchmark 驾驶舱",
                "source": "无 RP 运行结果",
                "updated_at": "--",
                "metrics": [("状态", "无数据"), ("参考", "--"), ("通过率", "--"), ("最大偏差", "--")],
                "plot_series": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("状态", "无 RP 结果", "请先运行 EC 处理生成 RP 结果")],
                "conclusions": ["当前尚无 RP 运行结果，无法展示 benchmark 对标。"],
                "export_options": ["导出 benchmark summary artifact", "导出 cross-software parity artifact", "导出 reference provenance artifact"],
                "file_info": {"状态": "无数据"},
                "versions": [],
                "usage": ["请先运行 EC 处理。"],
                "available_references": ref_options,
                "reference_details": ref_details,
                "current_thresholds": {},
                "per_window_detail": [],
                "ref_provenance": ref_provenance_map,
                "failed_fields_filter": [],
            }
        first_diag = rp_result.windows[0].diagnostics or {}
        bm_status = str(first_diag.get("benchmark_status", ""))
        bm_target = str(first_diag.get("benchmark_target", ""))
        bm_ref_id = str(first_diag.get("benchmark_reference_id", ""))
        bm_thresholds = first_diag.get("benchmark_thresholds", {})
        total_windows = len(rp_result.windows)
        pass_count = 0
        fail_count = 0
        no_ref_count = 0
        max_abs_error = 0.0
        max_rel_error = 0.0
        failed_fields: list[str] = []
        per_window_rows: list[tuple] = []
        per_window_detail: list[dict] = []
        for window in rp_result.windows:
            diag = window.diagnostics or {}
            dev_summary = diag.get("benchmark_deviation_summary", {})
            if not dev_summary or dev_summary.get("status") == "reference_not_found":
                no_ref_count += 1
                per_window_rows.append((window.window_id, "no_ref", "--", "--"))
                per_window_detail.append({
                    "window_id": window.window_id,
                    "overall_pass": True,
                    "match_strategy": "none",
                    "matched_reference_window_id": "",
                    "comparisons": [],
                    "primary_flux": window.primary_flux,
                    "qc_grade": window.qc_grade,
                    "primary_flux_random_error": diag.get("primary_flux_random_error"),
                    "primary_flux_relative_uncertainty": diag.get("primary_flux_relative_uncertainty"),
                    "primary_flux_uncertainty_band": diag.get("primary_flux_uncertainty_band"),
                    "primary_flux_ci_lower": diag.get("primary_flux_ci_lower"),
                    "primary_flux_ci_upper": diag.get("primary_flux_ci_upper"),
                    "footprint_method": diag.get("footprint_method", ""),
                    "uncertainty_method": diag.get("uncertainty_method", ""),
                    "spectral_correction_method": diag.get("spectral_correction_method", ""),
                    "spectral_correction_measured_cospectrum_source": diag.get("spectral_correction_measured_cospectrum_source", ""),
                    "method_deviation_notes": list(dev_summary.get("method_deviation_notes", [])),
                })
                continue
            overall_pass = dev_summary.get("overall_pass", True)
            match_strategy = dev_summary.get("match_strategy", "")
            matched_ref_id = dev_summary.get("matched_reference_window_id", "")
            if overall_pass:
                pass_count += 1
            else:
                fail_count += 1
            window_max_abs = 0.0
            window_max_rel = 0.0
            for comp in dev_summary.get("comparisons", []):
                abs_err = comp.get("absolute_error")
                rel_err = comp.get("relative_error")
                if abs_err is not None:
                    max_abs_error = max(max_abs_error, abs_err)
                    window_max_abs = max(window_max_abs, abs_err)
                if rel_err is not None:
                    max_rel_error = max(max_rel_error, rel_err)
                    window_max_rel = max(window_max_rel, rel_err)
                if not comp.get("passed", True) and comp.get("field_name", "") not in failed_fields:
                    failed_fields.append(comp["field_name"])
            per_window_rows.append((
                window.window_id,
                "pass" if overall_pass else "fail",
                f"{window_max_abs:.4e}" if window_max_abs else "--",
                f"{window_max_rel:.4f}" if window_max_rel else "--",
            ))
            per_window_detail.append({
                "window_id": window.window_id,
                "overall_pass": overall_pass,
                "match_strategy": match_strategy,
                "matched_reference_window_id": matched_ref_id,
                "comparisons": dev_summary.get("comparisons", []),
                "primary_flux": window.primary_flux,
                "qc_grade": window.qc_grade,
                "primary_flux_random_error": diag.get("primary_flux_random_error"),
                "primary_flux_relative_uncertainty": diag.get("primary_flux_relative_uncertainty"),
                "primary_flux_uncertainty_band": diag.get("primary_flux_uncertainty_band"),
                "primary_flux_ci_lower": diag.get("primary_flux_ci_lower"),
                "primary_flux_ci_upper": diag.get("primary_flux_ci_upper"),
                "footprint_method": diag.get("footprint_method", ""),
                "uncertainty_method": diag.get("uncertainty_method", ""),
                "spectral_correction_method": diag.get("spectral_correction_method", ""),
                "spectral_correction_measured_cospectrum_source": diag.get("spectral_correction_measured_cospectrum_source", ""),
                "method_deviation_notes": list(dev_summary.get("method_deviation_notes", [])),
            })
        pass_rate = pass_count / max(1, pass_count + fail_count) if (pass_count + fail_count) > 0 else 0.0
        active_provenance = ref_provenance_map.get(bm_ref_id, {})
        trace_gas_summary = dict(summary.get("trace_gas_summary", {}) or {})
        table_rows = [
            ("reference_id", bm_ref_id or "--", "参考数据集 ID"),
            ("target", bm_target or "--", "对标目标软件"),
            ("status", bm_status or "inactive", "benchmark 状态"),
            ("pass_rate", f"{pass_rate:.1%}", "窗口通过率"),
            ("windows_total", str(total_windows), "总窗口数"),
            ("windows_pass", str(pass_count), "通过窗口数"),
            ("windows_fail", str(fail_count), "失败窗口数"),
            ("windows_no_ref", str(no_ref_count), "无参考窗口数"),
            ("max_abs_error", f"{max_abs_error:.4e}", "最大绝对偏差"),
            ("max_rel_error", f"{max_rel_error:.4f}", "最大相对偏差"),
            ("failed_fields", " / ".join(failed_fields) if failed_fields else "无", "未通过的字段"),
        ]
        for key, val in (bm_thresholds or {}).items():
            table_rows.append((f"threshold.{key}", str(val), "benchmark 阈值"))
        if active_provenance:
            table_rows.append(("provenance.source", active_provenance.get("original_file_name", "--"), "原始参考文件"))
            table_rows.append(("provenance.normalization_time", active_provenance.get("normalization_time", "--"), "归一化时间"))
            table_rows.append(("provenance.qc_mapping", active_provenance.get("qc_mapping_strategy", "--"), "QC 映射策略"))
            for lim in active_provenance.get("known_limitations", [])[:3]:
                table_rows.append(("provenance.limitation", lim[:60], "已知限制"))
        if trace_gas_summary:
            table_rows.append(("trace_gas.ch4_status", trace_gas_summary.get("status", "--") or "--", "CH4 trace gas processing status"))
            table_rows.append(("trace_gas.ch4_method", trace_gas_summary.get("method", "--") or "--", "CH4 LI-7700 method"))
            table_rows.append(("trace_gas.ch4_coefficient_profile", trace_gas_summary.get("coefficient_profile_id", "--") or "--", "CH4 LI-7700 coefficient profile"))
            table_rows.append(("trace_gas.ch4_coefficient_source", trace_gas_summary.get("coefficient_profile_source_file", "--") or "--", "CH4 coefficient source file"))
            table_rows.append(("trace_gas.ch4_windows", str(trace_gas_summary.get("ch4_computed_window_count", 0)), "CH4 computed windows"))
            table_rows.append(("trace_gas.ch4_avg_flux", str(trace_gas_summary.get("average_ch4_flux_nmol_m2_s", "--")), "Average corrected CH4 flux"))
        for detail in per_window_detail:
            ms = detail.get("match_strategy", "")
            table_rows.append((
                detail["window_id"],
                "pass" if detail.get("overall_pass") else "fail",
                f"match={ms}" + (f" ref={detail.get('matched_reference_window_id', '')}" if ms != "none" else ""),
            ))
        return {
            "report_key": "benchmark_cockpit",
            "title": "Benchmark 驾驶舱",
            "source": bm_target or "无对标目标",
            "updated_at": run_result.created_at.strftime("%Y-%m-%d %H:%M") if run_result.created_at else "--",
            "metrics": [
                ("参考", bm_ref_id or "无"),
                ("通过率", f"{pass_rate:.1%}"),
                ("最大偏差", f"{max_abs_error:.4e}"),
                ("失败字段", str(len(failed_fields))),
            ],
            "plot_series": [1.0 if row[1] == "pass" else 0.0 for row in per_window_rows],
            "table_headers": ["项目", "数值", "说明"],
            "table_rows": table_rows,
            "conclusions": [
                f"Benchmark 对标通过率：{pass_rate:.1%}",
                f"最大绝对偏差：{max_abs_error:.4e}",
                f"失败字段：{' / '.join(failed_fields) if failed_fields else '无'}",
            ] if bm_status == "active" else ["Benchmark 未激活，请在配置中设置 benchmark.status=active"],
            "export_options": [
                "导出 benchmark summary artifact",
                "导出 cross-software parity artifact",
                "导出 reference provenance artifact",
            ],
            "file_info": {
                "状态": "已生成" if bm_status == "active" else "未激活",
                "参考文件": active_provenance.get("original_file_name", "--") if active_provenance else "--",
                "归一化时间": active_provenance.get("normalization_time", "--") if active_provenance else "--",
            },
            "versions": [
                f"reference_id：{bm_ref_id or '--'}",
                f"target：{bm_target or '--'}",
                f"qc_mapping：{active_provenance.get('qc_mapping_strategy', '--') if active_provenance else '--'}",
            ],
            "usage": [
                "查看 benchmark 对标结果摘要和逐窗口偏差。",
                "选择参考数据集切换对标目标（下拉框选择 reference）。",
                "调整阈值后点击 Rerun 刷新结果。",
                "点击窗口行查看逐字段偏差明细和匹配策略。",
                "使用 failed fields filter 仅显示未通过窗口。",
            ],
            "available_references": ref_options,
            "reference_details": ref_details,
            "current_thresholds": bm_thresholds or {},
            "per_window_detail": per_window_detail,
            "ref_provenance": ref_provenance_map,
            "failed_fields_filter": failed_fields,
        }

    def _benchmark_cockpit_payload(self, run_result: SpectralRunResult) -> dict:
        from core.ec_rp.analysis import generate_reference_provenance, list_available_references

        rp_result = self.current_rp_run()
        available_refs = list_available_references()
        ref_options = [ref["reference_id"] for ref in available_refs]
        ref_details = {ref["reference_id"]: ref for ref in available_refs}
        ref_provenance_map: dict[str, dict] = {}
        for ref in available_refs:
            json_path = ref.get("json_path", "")
            if not json_path:
                continue
            try:
                provenance = generate_reference_provenance(json_path)
            except Exception:
                continue
            provenance_path = Path(str(json_path)).parent / f"{Path(str(json_path)).stem}_provenance.json"
            provenance["source_file"] = provenance.get("original_file", "")
            provenance["qc_mapping"] = provenance.get("qc_mapping_strategy", "")
            provenance["normalization_command"] = (
                f'python {provenance.get("normalization_script", "references/eddypro/normalize_reference.py")} '
                f'"{provenance.get("original_file", "")}" "{provenance.get("json_source", json_path)}" --provenance "{provenance_path}"'
            )
            ref_provenance_map[ref["reference_id"]] = provenance

        if rp_result is None or not rp_result.windows:
            return {
                "report_key": "benchmark_cockpit",
                "title": "Benchmark 驾驶舱",
                "source": "无 RP 运行结果",
                "updated_at": "--",
                "metrics": [("状态", "无数据"), ("参考", "--"), ("通过率", "--"), ("最大偏差", "--")],
                "plot_series": [],
                "table_headers": ["项目", "数值", "说明"],
                "table_rows": [("状态", "无 RP 结果", "请先运行 EC 处理生成 RP 结果")],
                "conclusions": ["当前尚无 RP 运行结果，无法展示 benchmark 对标。"],
                "export_options": [
                    "导出 benchmark summary artifact",
                    "导出 cross-software parity artifact",
                    "导出 reference provenance artifact",
                ],
                "file_info": {"状态": "无数据"},
                "versions": [],
                "usage": ["请先运行 EC 处理。"],
                "available_references": ref_options,
                "reference_details": ref_details,
                "current_thresholds": {},
                "per_window_detail": [],
                "ref_provenance": ref_provenance_map,
                "failed_fields_filter": [],
            }

        summary = dict(rp_result.summary or {})
        first_diag = rp_result.windows[0].diagnostics or {}
        latest_export = dict(run_result.artifacts.get("result_exports", {}).get("latest", {}))
        export_files = dict(latest_export.get("files", {}))
        manifest_payload: dict[str, object] = {}
        export_manifest = export_files.get("export_manifest")
        if export_manifest and Path(str(export_manifest)).exists():
            try:
                manifest_payload = json.loads(Path(str(export_manifest)).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest_payload = {}

        bm_status = str(summary.get("benchmark_status") or first_diag.get("benchmark_status", ""))
        bm_target = str(summary.get("benchmark_target") or first_diag.get("benchmark_target", ""))
        bm_ref_id = str(summary.get("benchmark_reference_id") or first_diag.get("benchmark_reference_id", ""))
        bm_thresholds = dict(summary.get("benchmark_thresholds") or first_diag.get("benchmark_thresholds", {}) or {})

        pass_count = 0
        fail_count = 0
        no_ref_count = 0
        max_abs_error = 0.0
        max_rel_error = 0.0
        failed_fields: list[str] = []
        per_window_rows: list[tuple[str, str, str, str]] = []
        per_window_detail: list[dict] = []
        for window in rp_result.windows:
            diagnostics = window.diagnostics or {}
            deviation = diagnostics.get("benchmark_deviation_summary", {})
            if not deviation or deviation.get("status") == "reference_not_found":
                no_ref_count += 1
                per_window_rows.append((window.window_id, "no_ref", "--", "--"))
                per_window_detail.append(
                    {
                        "window_id": window.window_id,
                        "overall_pass": True,
                        "match_strategy": "none",
                        "matched_reference_window_id": "",
                        "comparisons": [],
                        "primary_flux": window.primary_flux,
                        "qc_grade": window.qc_grade,
                        "primary_flux_random_error": diagnostics.get("primary_flux_random_error"),
                        "primary_flux_relative_uncertainty": diagnostics.get("primary_flux_relative_uncertainty"),
                        "primary_flux_uncertainty_band": diagnostics.get("primary_flux_uncertainty_band"),
                        "primary_flux_ci_lower": diagnostics.get("primary_flux_ci_lower"),
                        "primary_flux_ci_upper": diagnostics.get("primary_flux_ci_upper"),
                        "footprint_method": diagnostics.get("footprint_method", ""),
                        "footprint_2d_grid_status": diagnostics.get("footprint_2d_grid_status", ""),
                        "footprint_2d_peak_downwind_m": diagnostics.get("footprint_2d_peak_downwind_m"),
                        "footprint_2d_peak_crosswind_m": diagnostics.get("footprint_2d_peak_crosswind_m"),
                        "uncertainty_method": diagnostics.get("uncertainty_method", ""),
                        "spectral_correction_method": diagnostics.get("spectral_correction_method", ""),
                        "spectral_correction_measured_cospectrum_source": diagnostics.get("spectral_correction_measured_cospectrum_source", ""),
                        "spectral_correction_cospectrum_match": diagnostics.get("spectral_correction_cospectrum_match", {}),
                        "sonic_correction_method": diagnostics.get("sonic_correction_method", ""),
                        "sonic_correction_status": diagnostics.get("sonic_correction_status", ""),
                        "crosswind_correction_method": diagnostics.get("crosswind_correction_method", ""),
                        "crosswind_correction_status": diagnostics.get("crosswind_correction_status", ""),
                        "clock_sync_status": diagnostics.get("clock_sync_status", ""),
                        "clock_sync_method": diagnostics.get("clock_sync_method", ""),
                        "clock_sync_source": diagnostics.get("clock_sync_source", ""),
                        "clock_sync_mean_offset_s": diagnostics.get("clock_sync_mean_offset_s"),
                        "ch4_method": diagnostics.get("ch4_method", ""),
                        "ch4_flux_nmol_m2_s": diagnostics.get("ch4_flux_nmol_m2_s"),
                        "ch4_flux_level0_nmol_m2_s": diagnostics.get("ch4_flux_level0_nmol_m2_s"),
                        "ch4_correction_sequence": diagnostics.get("ch4_correction_sequence", {}),
                        "ch4_coefficient_profile_id": diagnostics.get("ch4_coefficient_profile_id", ""),
                        "ch4_coefficient_registry_status": diagnostics.get("ch4_coefficient_registry_status", ""),
                        "ch4_coefficient_profile_provenance": diagnostics.get("ch4_coefficient_profile_provenance", ""),
                        "method_compare_summary": diagnostics.get("method_compare_summary", {}),
                        "method_compare_recommendations": diagnostics.get("method_compare_recommendations", {}),
                        "method_deviation_notes": list(deviation.get("method_deviation_notes", [])),
                    }
                )
                continue
            overall_pass = bool(deviation.get("overall_pass", True))
            if overall_pass:
                pass_count += 1
            else:
                fail_count += 1
            window_max_abs = 0.0
            window_max_rel = 0.0
            for comparison in deviation.get("comparisons", []):
                absolute_error = comparison.get("absolute_error")
                relative_error = comparison.get("relative_error")
                if absolute_error is not None:
                    window_max_abs = max(window_max_abs, float(absolute_error))
                    max_abs_error = max(max_abs_error, float(absolute_error))
                if relative_error is not None:
                    window_max_rel = max(window_max_rel, float(relative_error))
                    max_rel_error = max(max_rel_error, float(relative_error))
                field_name = str(comparison.get("field_name", ""))
                if field_name and not comparison.get("passed", True) and field_name not in failed_fields:
                    failed_fields.append(field_name)
            per_window_rows.append(
                (
                    window.window_id,
                    "pass" if overall_pass else "fail",
                    f"{window_max_abs:.4e}" if window_max_abs else "--",
                    f"{window_max_rel:.4f}" if window_max_rel else "--",
                )
            )
            per_window_detail.append(
                {
                    "window_id": window.window_id,
                    "overall_pass": overall_pass,
                    "match_strategy": deviation.get("match_strategy", ""),
                    "matched_reference_window_id": deviation.get("matched_reference_window_id", ""),
                    "comparisons": deviation.get("comparisons", []),
                    "primary_flux": window.primary_flux,
                    "qc_grade": window.qc_grade,
                    "primary_flux_random_error": diagnostics.get("primary_flux_random_error"),
                    "primary_flux_relative_uncertainty": diagnostics.get("primary_flux_relative_uncertainty"),
                    "primary_flux_uncertainty_band": diagnostics.get("primary_flux_uncertainty_band"),
                    "primary_flux_ci_lower": diagnostics.get("primary_flux_ci_lower"),
                    "primary_flux_ci_upper": diagnostics.get("primary_flux_ci_upper"),
                    "footprint_method": deviation.get("footprint_method", diagnostics.get("footprint_method", "")),
                    "footprint_2d_grid_status": deviation.get("footprint_2d_grid_status", diagnostics.get("footprint_2d_grid_status", "")),
                    "footprint_2d_peak_downwind_m": deviation.get("footprint_2d_peak_downwind_m", diagnostics.get("footprint_2d_peak_downwind_m")),
                    "footprint_2d_peak_crosswind_m": deviation.get("footprint_2d_peak_crosswind_m", diagnostics.get("footprint_2d_peak_crosswind_m")),
                    "uncertainty_method": deviation.get("uncertainty_method", diagnostics.get("uncertainty_method", "")),
                    "spectral_correction_method": deviation.get("spectral_correction_method", diagnostics.get("spectral_correction_method", "")),
                    "spectral_correction_measured_cospectrum_source": diagnostics.get("spectral_correction_measured_cospectrum_source", ""),
                    "spectral_correction_cospectrum_match": deviation.get("spectral_correction_cospectrum_match", diagnostics.get("spectral_correction_cospectrum_match", {})),
                    "sonic_correction_method": deviation.get("sonic_correction_method", diagnostics.get("sonic_correction_method", "")),
                    "sonic_correction_status": deviation.get("sonic_correction_status", diagnostics.get("sonic_correction_status", "")),
                    "crosswind_correction_method": deviation.get("crosswind_correction_method", diagnostics.get("crosswind_correction_method", "")),
                    "crosswind_correction_status": deviation.get("crosswind_correction_status", diagnostics.get("crosswind_correction_status", "")),
                    "clock_sync_status": deviation.get("clock_sync_status", diagnostics.get("clock_sync_status", "")),
                    "clock_sync_method": deviation.get("clock_sync_method", diagnostics.get("clock_sync_method", "")),
                    "clock_sync_source": deviation.get("clock_sync_source", diagnostics.get("clock_sync_source", "")),
                    "clock_sync_mean_offset_s": deviation.get("clock_sync_mean_offset_s", diagnostics.get("clock_sync_mean_offset_s")),
                    "ch4_method": deviation.get("ch4_method", diagnostics.get("ch4_method", "")),
                    "ch4_flux_nmol_m2_s": deviation.get("ch4_flux_nmol_m2_s", diagnostics.get("ch4_flux_nmol_m2_s")),
                    "ch4_flux_level0_nmol_m2_s": deviation.get("ch4_flux_level0_nmol_m2_s", diagnostics.get("ch4_flux_level0_nmol_m2_s")),
                    "ch4_correction_sequence": deviation.get("ch4_correction_sequence", diagnostics.get("ch4_correction_sequence", {})),
                    "ch4_coefficient_profile_id": deviation.get("ch4_coefficient_profile_id", diagnostics.get("ch4_coefficient_profile_id", "")),
                    "ch4_coefficient_registry_status": deviation.get("ch4_coefficient_registry_status", diagnostics.get("ch4_coefficient_registry_status", "")),
                    "ch4_coefficient_profile_provenance": deviation.get("ch4_coefficient_profile_provenance", diagnostics.get("ch4_coefficient_profile_provenance", "")),
                    "method_compare_summary": deviation.get("method_compare_summary", diagnostics.get("method_compare_summary", {})),
                    "method_compare_recommendations": deviation.get("method_compare_recommendations", diagnostics.get("method_compare_recommendations", {})),
                    "method_deviation_notes": list(deviation.get("method_deviation_notes", [])),
                }
            )

        benchmark_deviation_summary = dict(summary.get("benchmark_deviation_summary") or manifest_payload.get("benchmark_deviation_summary") or {})
        pass_rate = float(manifest_payload.get("pass_rate", summary.get("pass_rate", 0.0)) or 0.0)
        if pass_rate == 0.0 and (pass_count + fail_count) > 0:
            pass_rate = pass_count / max(1, pass_count + fail_count)
        failed_fields = list(manifest_payload.get("failed_fields", summary.get("failed_fields", failed_fields)) or failed_fields)
        windows_total = int(benchmark_deviation_summary.get("window_count", len(rp_result.windows)) or len(rp_result.windows))
        windows_pass = int(benchmark_deviation_summary.get("pass_window_count", benchmark_deviation_summary.get("windows_pass", pass_count)) or pass_count)
        windows_fail = int(benchmark_deviation_summary.get("failed_window_count", benchmark_deviation_summary.get("windows_fail", fail_count)) or fail_count)
        windows_no_ref = int(benchmark_deviation_summary.get("missing_reference_window_count", no_ref_count) or no_ref_count)
        max_abs_error = float(benchmark_deviation_summary.get("max_abs_error", max_abs_error) or max_abs_error)
        max_rel_error = float(benchmark_deviation_summary.get("max_rel_error", max_rel_error) or max_rel_error)
        active_provenance = (
            dict(manifest_payload.get("reference_provenance", {}) or {})
            or dict(rp_result.artifacts.get("reference_provenance", {}) or {})
            or ref_provenance_map.get(bm_ref_id, {})
        )
        network_summary = dict(manifest_payload.get("network_validation_summary", {}) or {})
        if not network_summary:
            network_summary = {
                "schema_target": summary.get("schema_target", first_diag.get("schema_target", "")),
                "validation_status": manifest_payload.get("network_validation_status", "not_requested"),
                "missing_fields": list(manifest_payload.get("network_missing_fields", [])),
                "timestamp_refers_to": summary.get("fluxnet_timestamp_refers_to", first_diag.get("fluxnet_timestamp_refers_to", "start")),
                "timezone_offset_hours": summary.get("fluxnet_timezone_offset_h", first_diag.get("fluxnet_timezone_offset_h", 0.0)),
            }
        trace_gas_summary = dict(manifest_payload.get("trace_gas_summary", {}) or summary.get("trace_gas_summary", {}) or {})
        clock_summary = dict(
            manifest_payload.get("clock_sync_summary", {})
            or summary.get("clock_sync_summary", {})
            or rp_result.artifacts.get("clock_sync", {})
            or first_diag.get("clock_sync_detail", {})
            or {}
        )
        runtime_summary = dict(
            manifest_payload.get("runtime_watchdog_summary", {})
            or summary.get("runtime_watchdog_summary", {})
            or rp_result.artifacts.get("runtime_watchdog", {})
            or {}
        )
        service_summary = dict(
            manifest_payload.get("runtime_service_summary", {})
            or summary.get("runtime_service_summary", {})
            or rp_result.artifacts.get("runtime_service", {})
            or {}
        )

        table_rows = [
            ("reference_id", bm_ref_id or "--", "参考数据集 ID"),
            ("target", bm_target or "--", "对标目标软件"),
            ("status", bm_status or "inactive", "benchmark 状态"),
            ("pass_rate", f"{pass_rate:.1%}", "窗口通过率"),
            ("windows_total", str(windows_total), "总窗口数"),
            ("windows_pass", str(windows_pass), "通过窗口数"),
            ("windows_fail", str(windows_fail), "失败窗口数"),
            ("windows_no_ref", str(windows_no_ref), "无参考窗口数"),
            ("max_abs_error", f"{max_abs_error:.4e}", "最大绝对偏差"),
            ("max_rel_error", f"{max_rel_error:.4f}", "最大相对偏差"),
            ("failed_fields", " / ".join(failed_fields) if failed_fields else "无", "未通过的字段"),
        ]
        for key, value in (bm_thresholds or {}).items():
            table_rows.append((f"threshold.{key}", str(value), "benchmark 阈值"))
        if active_provenance:
            table_rows.append(("provenance.source", active_provenance.get("original_file_name", "--"), "原始参考文件"))
            table_rows.append(("provenance.normalization_time", active_provenance.get("normalization_time", "--"), "归一化时间"))
            table_rows.append(("provenance.qc_mapping", active_provenance.get("qc_mapping_strategy", "--"), "QC 映射策略"))
            table_rows.append(("provenance.command", active_provenance.get("normalization_command", "--"), "归一化命令"))
            for limitation in active_provenance.get("known_limitations", [])[:3]:
                table_rows.append(("provenance.limitation", str(limitation)[:60], "已知限制"))
        table_rows.append(("network.schema_target", network_summary.get("schema_target", "--") or "--", "网络导出目标"))
        table_rows.append(("network.validation_status", network_summary.get("validation_status", "--") or "--", "网络校验状态"))
        table_rows.append(("network.missing_fields", " / ".join(network_summary.get("missing_fields", [])) or "无", "网络缺失字段"))
        if clock_summary:
            table_rows.append(("clock_sync.status", clock_summary.get("status", "--"), "采集时钟同步状态"))
            table_rows.append(("clock_sync.method", clock_summary.get("method", "--"), "GPS/PTP 同步方法"))
            table_rows.append(("clock_sync.source", clock_summary.get("clock_source", "--"), "采集时钟来源"))
            table_rows.append(("clock_sync.mean_offset_s", str(clock_summary.get("mean_offset_seconds", "--")), "平均时间戳修正"))
        if runtime_summary:
            table_rows.append(("runtime_watchdog.status", runtime_summary.get("status", "--"), "现场运行守护状态"))
            table_rows.append(("runtime_watchdog.profile", runtime_summary.get("profile_id", "--"), "运行 profile"))
            table_rows.append(("runtime_watchdog.fail_count", str(runtime_summary.get("fail_count", "--")), "失败检查数"))
            for action in list(runtime_summary.get("recommended_actions", []) or [])[:3]:
                table_rows.append(("runtime_watchdog.action", str(action)[:80], "建议处理"))
        if service_summary:
            table_rows.append(("runtime_service.status", service_summary.get("status", "--"), "服务运行状态"))
            table_rows.append(("runtime_service.delivery_state", service_summary.get("delivery_state", "--"), "交付就绪状态"))
            table_rows.append(("runtime_service.quarantine_count", str(len(service_summary.get("quarantine_records", []) or [])), "隔离批次数"))
            table_rows.append(("runtime_service.restart_count", str(len(service_summary.get("restart_records", []) or [])), "重试/重启记录数"))
        for detail in per_window_detail:
            match_strategy = detail.get("match_strategy", "")
            table_rows.append(
                (
                    detail["window_id"],
                    "pass" if detail.get("overall_pass") else "fail",
                    f"match={match_strategy}" + (f" ref={detail.get('matched_reference_window_id', '')}" if match_strategy != "none" else ""),
                )
            )

        file_info = {
            "状态": "已生成" if bm_status == "active" else "未激活",
            "参考文件": active_provenance.get("original_file_name", "--") if active_provenance else "--",
            "归一化时间": active_provenance.get("normalization_time", "--") if active_provenance else "--",
            "QC 映射": active_provenance.get("qc_mapping_strategy", "--") if active_provenance else "--",
            "网络目标": network_summary.get("schema_target", "--") or "--",
            "网络校验": network_summary.get("validation_status", "--") or "--",
            "缺失字段": " / ".join(network_summary.get("missing_fields", [])) or "无",
            "Clock sync": clock_summary.get("status", "--") if clock_summary else "--",
            "Runtime watchdog": runtime_summary.get("status", "--") if runtime_summary else "--",
            "Runtime service": service_summary.get("status", "--") if service_summary else "--",
        }
        for key, label in (
            ("benchmark_summary_artifact", "Benchmark Summary"),
            ("method_rollup_artifact", "Method Rollup"),
            ("parity_artifact", "Parity Artifact"),
            ("reference_provenance_artifact", "Provenance Artifact"),
            ("network_validation_summary", "Network Validation"),
            ("runtime_watchdog_artifact", "Runtime Watchdog"),
            ("runtime_service_artifact", "Runtime Service"),
            ("clock_sync_artifact", "Clock Sync Artifact"),
        ):
            if export_files.get(key):
                file_info[label] = str(export_files[key])

        return {
            "report_key": "benchmark_cockpit",
            "title": "Benchmark 驾驶舱",
            "source": bm_target or "无对标目标",
            "updated_at": run_result.created_at.strftime("%Y-%m-%d %H:%M") if run_result.created_at else "--",
            "metrics": [
                ("参考", bm_ref_id or "无"),
                ("通过率", f"{pass_rate:.1%}"),
                ("最大偏差", f"{max_abs_error:.4e}"),
                ("失败字段", str(len(failed_fields))),
            ],
            "plot_series": [1.0 if row[1] == "pass" else 0.0 for row in per_window_rows],
            "table_headers": ["项目", "数值", "说明"],
            "table_rows": table_rows,
            "conclusions": [
                f"Benchmark 对标通过率：{pass_rate:.1%}",
                f"最大绝对偏差：{max_abs_error:.4e}",
                f"失败字段：{' / '.join(failed_fields) if failed_fields else '无'}",
                f"网络校验：{network_summary.get('schema_target', '--') or '--'} / {network_summary.get('validation_status', '--') or '--'}",
            ] if bm_status == "active" else ["Benchmark 未激活，请先选择 reference 并触发 rerun。"],
            "export_options": [
                "导出 benchmark summary artifact",
                "导出 cross-software parity artifact",
                "导出 reference provenance artifact",
                "同步 network validation summary 到 manifest / delivery package",
            ],
            "file_info": file_info,
            "versions": [
                f"reference_id：{bm_ref_id or '--'}",
                f"target：{bm_target or '--'}",
                f"qc_mapping：{active_provenance.get('qc_mapping_strategy', '--') if active_provenance else '--'}",
                f"normalization_command：{active_provenance.get('normalization_command', '--') if active_provenance else '--'}",
            ],
            "usage": [
                "查看 benchmark 对标结果摘要和逐窗口偏差。",
                "选择参考数据集或调整阈值后会真实 rerun RP pipeline。",
                "Rerun 会同步刷新 cockpit KPI、per-window detail、manifest 和交付导出状态。",
                "点击窗口行可查看逐字段偏差明细和匹配策略。",
                "使用 failed fields filter 仅显示未通过窗口。",
            ],
            "available_references": ref_options,
            "reference_details": ref_details,
            "current_thresholds": bm_thresholds or {},
            "per_window_detail": per_window_detail,
            "ref_provenance": ref_provenance_map,
            "failed_fields_filter": failed_fields,
        }

    def _load_latest_eddypro_compare(self) -> None:
        compare_root = self.runtime_root / "exports" / "eddypro_compare"
        if not compare_root.exists():
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            return
        manifest_paths = sorted(compare_root.glob("compare_*/compare_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not manifest_paths:
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            return
        try:
            payload = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.latest_eddypro_compare_result = None
            self.latest_eddypro_compare_manifest = None
            self.latest_eddypro_attribution_result = None
            return
        self.latest_eddypro_compare_manifest = payload
        self.latest_eddypro_compare_result = EddyProCompareResult(
            compare_id=str(payload.get("compare_id", "")),
            created_at=self._parse_iso_datetime(payload.get("created_at")) or datetime.now(),
            current_source=dict(payload.get("current_source", {})),
            reference_source=dict(payload.get("reference_source", {})),
            summary_metrics=dict(payload.get("summary_metrics", {})),
            window_results=self._load_compare_windows(Path(str(payload.get("files", {}).get("compare_windows", "")))),
            risk_summary=[str(item) for item in payload.get("risk_summary", [])],
            notes=[str(item) for item in payload.get("notes", [])],
        )
        self.latest_eddypro_attribution_result = None

    def _load_compare_windows(self, csv_path: Path) -> list[WindowCompareResult]:
        if not csv_path.exists():
            return []
        import csv as _csv

        rows: list[WindowCompareResult] = []
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = _csv.DictReader(handle)
            for row in reader:
                rows.append(
                    WindowCompareResult(
                        window_key=str(row.get("window_key", "")),
                        start_time=self._parse_iso_datetime(row.get("start_time")),
                        end_time=self._parse_iso_datetime(row.get("end_time")),
                        current_lag_seconds=self._parse_optional_float(row.get("current_lag_seconds")),
                        reference_lag_seconds=self._parse_optional_float(row.get("reference_lag_seconds")),
                        lag_delta=self._parse_optional_float(row.get("lag_delta")),
                        current_flux=self._parse_optional_float(row.get("current_flux")),
                        reference_flux=self._parse_optional_float(row.get("reference_flux")),
                        flux_delta=self._parse_optional_float(row.get("flux_delta")),
                        current_correction_factor=self._parse_optional_float(row.get("current_correction_factor")),
                        reference_correction_factor=self._parse_optional_float(row.get("reference_correction_factor")),
                        correction_factor_delta=self._parse_optional_float(row.get("correction_factor_delta")),
                        current_qc_grade=row.get("current_qc_grade") or None,
                        reference_qc_grade=row.get("reference_qc_grade") or None,
                        qc_match=self._parse_optional_bool(row.get("qc_match")),
                        notes=[item.strip() for item in str(row.get("notes", "")).split("|") if item.strip()],
                    )
                )
        return rows

    def _latest_result_export_dir(self) -> Path | None:
        candidates: list[Path] = []
        for run in self.spectral_runs:
            latest = run.artifacts.get("result_exports", {}).get("latest", {})
            export_root = latest.get("export_root")
            if export_root:
                path = Path(str(export_root))
                if path.exists():
                    candidates.append(path)
        results_root = self.runtime_root / "exports" / "results"
        if results_root.exists():
            candidates.extend(path for path in results_root.iterdir() if path.is_dir())
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _describe_compare_source(self, source: dict[str, object]) -> str:
        if source.get("export_dir"):
            return str(source["export_dir"])
        if source.get("reference_dir"):
            return str(source["reference_dir"])
        mapping = source.get("mapping")
        if isinstance(mapping, dict) and mapping:
            return ", ".join(f"{key}={value}" for key, value in mapping.items())
        return str(source.get("source_type", "--"))

    def _format_optional_float(self, value: object, digits: int) -> str:
        if value in (None, ""):
            return "--"
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "--"

    def _parse_iso_datetime(self, value: object) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _parse_optional_float(self, value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_optional_bool(self, value: object) -> bool | None:
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return None

    def log_lines(self) -> list[str]:
        return [f"[{row['time']}] {row['level'].upper()}  {row['message']}" for row in self.logs]

    def _execute_transaction(
        self,
        entry: ManagedDevice,
        *,
        label: str,
        command_text: str,
        dangerous: bool = False,
        timeout_s: float = 0.35,
    ) -> TransactionRecord:
        record = self.transaction_manager.begin(
            label=label,
            command_text=command_text,
            device_uid=entry.config.uid,
            device_id=entry.config.device_id,
            dangerous=dangerous,
        )
        try:
            response_text = self.acquisition.execute_command(entry.config.uid, command_text, timeout_s=timeout_s)
        except Exception as exc:
            response_text = self._humanize_exception(str(exc))
            finished = self.transaction_manager.finish(
                record.transaction_id,
                response_text=response_text,
                timeout="超时" in response_text,
            )
            self.metadata_store.append_transaction(finished)
            self._append_log("error", f"{label}失败：{finished.response_summary or response_text}")
            self._push_event(
                device_uid=entry.config.uid,
                device_id=entry.config.device_id,
                severity="error",
                title=label,
                message=f"{label}失败：{finished.response_summary or response_text}",
                category="transaction_failure",
            )
            self.transactions_changed.emit()
            return finished

        for frame in self.acquisition.decode_payload(
            response_text,
            source="manual",
            fallback_device_id=entry.config.device_id,
        ):
            self._handle_frame(entry.config.uid, frame)

        finished = self.transaction_manager.finish(record.transaction_id, response_text=response_text)
        self.metadata_store.append_transaction(finished)
        entry.runtime.last_transaction_id = finished.transaction_id
        self.transactions_changed.emit()
        tone = "warning" if finished.status.value in {"FAILED", "TIMEOUT"} else "info"
        self._append_log(tone, f"{label}：{finished.response_summary or '已完成'}")
        if finished.status.value in {"FAILED", "TIMEOUT"}:
            self._push_event(
                device_uid=entry.config.uid,
                device_id=entry.config.device_id,
                severity="error" if finished.status.value == "FAILED" else "warning",
                title=label,
                message=finished.response_summary or "设备没有返回可用结果。",
                category="transaction_failure",
                raw_text=finished.response_text,
            )
        return finished

    def _handle_frame(self, device_uid: str, frame: ProtocolFrame) -> None:
        with self._lock:
            entry = self.devices.get(device_uid)
            if entry is None:
                return
            entry.runtime.extra["last_seen_at"] = frame.received_at
            entry.runtime.last_frame_quality = frame.quality
            entry.runtime.last_raw_frame = frame.raw_text
            entry.runtime.last_message = self._operator_summary(frame)
            self.raw_frames.appendleft(frame)
            self.device_frame_history[device_uid].appendleft(frame)

        self.raw_store.append(frame)

        if frame.parsed and frame.parsed.get("co2_ppm") is not None:
            normalized = NormalizedHFFrame(
                timestamp=frame.received_at,
                device_uid=device_uid,
                device_id=str(frame.device_id or entry.config.device_id),
                mode=int(frame.parsed.get("mode") or entry.runtime.mode or 2),
                frame_quality=frame.quality,
                co2_ppm=frame.parsed.get("co2_ppm"),
                h2o_mmol=frame.parsed.get("h2o_mmol"),
                pressure_kpa=frame.parsed.get("pressure_kpa"),
                chamber_temp_c=frame.parsed.get("chamber_temp_c"),
                case_temp_c=frame.parsed.get("case_temp_c"),
                status_text=frame.status_text or frame.parsed.get("status_text"),
                raw_text=frame.raw_text,
            )
            self.realtime_buffer.append(normalized)
            self.hf_store.append_csv(normalized)
            entry.runtime.mode = normalized.mode
            entry.runtime.last_frame_time = frame.received_at
            entry.runtime.extra["latest_numeric"] = normalized

        self._register_frame_event(device_uid, entry, frame)
        self.frame_received.emit(frame)
        self.devices_changed.emit()

    def _register_frame_event(self, device_uid: str, entry: ManagedDevice, frame: ProtocolFrame) -> None:
        key = f"{frame.quality.value}:{frame.status_text or ''}"
        now = datetime.now()
        last = self._event_cooldowns.get((device_uid, key))
        if last and (now - last).total_seconds() < 2.0:
            return

        if frame.quality == FrameQuality.FULL:
            status_text = str(frame.status_text or "").strip().upper()
            if status_text and status_text not in {"OK", "NORMAL"}:
                self._event_cooldowns[(device_uid, key)] = now
                self._push_event(
                    device_uid=device_uid,
                    device_id=entry.config.device_id,
                    severity="warning",
                    title="状态字提示需要关注",
                    message=f"设备状态字为 {frame.status_text}，建议核对现场工况与配置。",
                    category="status_text",
                    related_timestamp=frame.received_at,
                    raw_text=frame.raw_text,
                    parsed_snapshot=dict(frame.parsed),
                )
            return

        if frame.quality == FrameQuality.ACK_ONLY and frame.source == "manual":
            self._event_cooldowns[(device_uid, key)] = now
            self._push_event(
                device_uid=device_uid,
                device_id=entry.config.device_id,
                severity="info",
                title="设备已确认指令",
                message="设备返回了确认应答，说明配置命令已经被接收。",
                category="ack",
                related_timestamp=frame.received_at,
                raw_text=frame.raw_text,
            )
            return

        message_map = {
            FrameQuality.PARTIAL: ("warning", "收到不完整数据帧，主测量值可用，但建议进一步核验。", "partial_frame"),
            FrameQuality.TRUNCATED: ("error", "数据帧被截断，请优先检查串口接线、输出频率和接收窗口。", "truncated_frame"),
            FrameQuality.CORRUPTED: ("error", "收到损坏的数据内容，常见原因是波特率不匹配或线路噪声。", "corrupted_frame"),
            FrameQuality.UNKNOWN: ("warning", "收到无法识别的响应内容，建议切换到工程师视图查看原始帧。", "unknown_frame"),
        }
        if frame.quality not in message_map:
            return
        severity, message, category = message_map[frame.quality]
        self._event_cooldowns[(device_uid, key)] = now
        self._push_event(
            device_uid=device_uid,
            device_id=entry.config.device_id,
            severity=severity,
            title="协议数据异常" if severity == "error" else "数据质量提示",
            message=message,
            category=category,
            related_timestamp=frame.received_at,
            raw_text=frame.raw_text,
            parsed_snapshot=dict(frame.parsed),
        )

    def _push_event(
        self,
        *,
        device_uid: str,
        device_id: str,
        severity: str,
        title: str,
        message: str,
        category: str,
        related_timestamp: datetime | None = None,
        raw_text: str = "",
        parsed_snapshot: dict | None = None,
    ) -> None:
        event = EventRecord(
            event_id=uuid4().hex[:10],
            created_at=datetime.now(),
            device_uid=device_uid,
            device_id=device_id,
            severity=severity,
            title=title,
            message=message,
            category=category,
            related_timestamp=related_timestamp,
            raw_text=raw_text,
            parsed_snapshot=dict(parsed_snapshot or {}),
        )
        self.events.appendleft(event)
        self.events_changed.emit()

    def _build_default_project_workspace(self, *, template_name: str = "标准农田站模板") -> dict:
        return {
            "overview": {
                "project_name": "东区试验田通量观测",
                "project_code": "PRJ-EC-001",
                "principal": "现场工程组",
                "archive_root": str(self.runtime_root),
                "status": "草稿",
                "template_name": template_name,
                "notes": "用于管理站点元数据、采样链路和输出模板。",
            },
            "site_info": {
                "station_name": "试验站 A",
                "station_code": "SITE-A",
                "location": "江苏省盐城市",
                "land_cover": "冬小麦",
                "canopy_height_m": 1.8,
                "altitude_m": 12.0,
                "timezone": "Asia/Shanghai",
            },
            "instrument_layout": {
                "mast_height_m": 3.5,
                "analyzer_height_m": 2.8,
                "sonic_height_m": 3.2,
                "height_delta_m": 0.4,
                "orientation_deg": 180,
                "analyzer_mount": "主塔北侧保温机箱",
                "sonic_mount": "主塔顶部",
                "reference_sensor": "温压一体参考模块",
                "layout_note": "分析仪与采样泵同箱安装，便于现场维护。",
            },
            "sampling_chain": {
                "tube_length_m": 18.0,
                "tube_diameter_mm": 4.0,
                "tube_material": "PFA",
                "heat_traced": True,
                "insulated": True,
                "pump_model": "KNF N86",
                "flow_lpm": 8.5,
                "filter_model": "2 um PTFE",
                "chain_note": "入口前设置一级过滤，管路带伴热与保温。",
            },
            "timing": {
                "timezone": "Asia/Shanghai",
                "sample_hz": 20,
                "block_minutes": 30,
                "clock_source": "GNSS + NTP",
                "start_rule": "整点对齐",
                "sample_mode": "连续高频",
            },
            "output_template": {
                "template_name": "标准通量导出",
                "include_diagnostics": True,
                "include_qc": True,
                "file_pattern": "{site}_{date}_{window}.csv",
                "report_header": "Gas EC Studio",
            },
            "runtime_template": {
                "template_name": "现场默认运行",
                "precheck_mode": "严格",
                "auto_archive": True,
                "replay_ready": True,
                "operator_note": "每天开始采集前执行一次完整性检查。",
            },
            "metadata": {
                "station": {
                    "latitude": 33.387,
                    "longitude": 120.157,
                    "displacement_height": 1.2,
                    "roughness_length": 0.18,
                    "timestamp_refers_to": "end_of_averaging_period",
                    "file_duration": 30.0,
                },
                "instruments": {
                    "sonic_model": "CSAT3A",
                    "analyzer_model": "LI-7200RS",
                    "sonic_serial": "CSAT3A-001",
                    "analyzer_serial": "LI7200-001",
                    "sonic_manufacturer": "Campbell Scientific",
                    "analyzer_manufacturer": "LI-COR",
                    "sonic_firmware": "1.2.0",
                    "analyzer_firmware": "8.0.5",
                    "sonic_instrument_id": "sonic-main",
                    "analyzer_instrument_id": "gas-main",
                    "mount_description": "主塔顶端与北侧分析仪机箱一体布设。",
                    "geometry_detail": "sonic 正北朝向，analyzer inlet 与 sonic 距离约 0.4 m。",
                },
                "raw_file_description": {
                    "source_name": "东区试验田通量观测",
                    "source_type": "hf_frame",
                    "file_pattern": "{site}_{date}_{window}.csv",
                    "timestamp_column": "timestamp",
                    "timezone": "Asia/Shanghai",
                    "notes": "默认以当前工作区高频文件作为 RP/FCC 输入。",
                    "column_mappings_json": json.dumps(
                        [
                            {
                                "column_name": "timestamp",
                                "ignore": False,
                                "numeric": False,
                                "variable": "timestamp",
                                "instrument": "logger",
                                "measurement_type": "time",
                                "input_unit": "iso8601",
                                "output_unit": "iso8601",
                                "scaling": None,
                                "nominal_lag": None,
                                "min_lag": None,
                                "max_lag": None,
                            },
                            {
                                "column_name": "co2_ppm",
                                "ignore": False,
                                "numeric": True,
                                "variable": "co2",
                                "instrument": "gas-main",
                                "measurement_type": "mole_fraction",
                                "input_unit": "ppm",
                                "output_unit": "ppm",
                                "scaling": 1.0,
                                "nominal_lag": 2.4,
                                "min_lag": 0.5,
                                "max_lag": 6.0,
                            },
                        ],
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
                "raw_file_settings": {
                    "sample_hz": 20.0,
                    "delimiter": ",",
                    "decimal": ".",
                    "header_rows": 1,
                    "encoding": "utf-8",
                    "missing_tokens": ",NA,NaN,-9999",
                },
                "biomet_source": {
                    "source_mode": "none",
                    "source_path": "",
                    "time_column": "timestamp",
                    "aggregation_method": "mean",
                    "fields": "ta,rh,swc",
                    "directory_glob": "*.csv",
                    "notes": "",
                },
                "dynamic_metadata": {
                    "source_path": "",
                    "start_column": "start_time",
                    "end_column": "end_time",
                    "timezone": "Asia/Shanghai",
                    "records": [],
                },
                "alternative_metadata": {
                    "active_profile": "PRJ-EC-001",
                    "available_profiles": [],
                },
            },
        }

    def _build_default_ec_processing(self) -> dict:
        return {
            "run": {
                "data_source": "当前项目高频目录",
                "time_range": "最近 24 小时",
                "run_mode": "标准运行",
            },
            "steps": {
                "window_sampling": {
                    "title": "窗口与采样",
                    "method": "30 分钟固定窗口",
                    "applicable": "适用于常规通量站连续观测。",
                    "recommended": "优先使用 30 分钟窗口和原始采样频率。",
                    "window_minutes": 30,
                    "sample_hz": 20,
                    "preview": "窗口边界会与整点对齐，便于后续站点级汇总。",
                },
                "data_cleaning": {
                    "title": "数据清洗",
                    "method": "范围阈值 + 尖峰剔除",
                    "applicable": "适用于现场高频数据存在偶发毛刺和缺测的场景。",
                    "recommended": "先使用温和阈值，再结合剔除统计复核。",
                    "spike_sigma": 5.0,
                    "missing_policy": "线性插补仅用于辅助变量",
                    "removed_ratio": "2.4%",
                },
                "screening": {
                    "title": "统计筛选",
                    "method": "偏度/峰度/dropout/尖峰/不连续检测",
                    "applicable": "适用于窗口级统计异常诊断。",
                    "recommended": "先用默认阈值运行，再根据站点特征微调。",
                    "skewness_threshold": 2.0,
                    "kurtosis_threshold": 7.0,
                    "dropout_min_run": 10,
                    "spike_sigma": 5.0,
                    "discontinuity_sigma": 8.0,
                    "absolute_limits_text": "",
                },
                "lag": {
                    "title": "lag",
                    "method": "协方差峰值搜索",
                    "applicable": "适用于闭路分析仪存在稳定时滞的采样链路。",
                    "recommended": "优先使用经验窗口 + 峰值验证。",
                    "lag_strategy": "协方差最大",
                    "search_window_s": 8.0,
                    "expected_lag_s": 2.4,
                },
                "rotation": {
                    "title": "坐标旋转",
                    "method": "双旋转",
                    "applicable": "适用于塔基固定、地形相对平坦的常规站点。",
                    "recommended": "默认使用双旋转，复杂地形再评估平面拟合。",
                    "rotation_mode": "双旋转",
                },
                "detrend": {
                    "title": "去趋势",
                    "method": "块均值去趋势",
                    "applicable": "适用于常规 30 分钟窗口。",
                    "recommended": "先用块均值去趋势，再结合频谱表现决定是否换高阶方法。",
                    "detrend_mode": "块均值",
                },
                "covariance": {
                    "title": "协方差",
                    "method": "窗口内协方差估计",
                    "applicable": "适用于通量主链路。",
                    "recommended": "保持与窗口设置一致，避免额外重采样。",
                    "covariance_mode": "标准协方差",
                },
                "density_correction": {
                    "title": "密度/混合比修正",
                    "method": "WPL 修正",
                    "applicable": "适用于需要从密度量恢复混合比或通量的场景。",
                    "recommended": "确认温压与水汽信号稳定后再启用。",
                    "correction_mode": "WPL",
                },
                "steadiness": {
                    "title": "稳态检验",
                    "method": "窗口分段对比",
                    "applicable": "适用于通量有效性分级。",
                    "recommended": "与湍流检验配合查看，不要只看单一指标。",
                    "steadiness_rule": "Foken-like",
                },
                "turbulence": {
                    "title": "湍流检验",
                    "method": "u* 与谱形联合判断",
                    "applicable": "适用于夜间筛选和稳定度分析。",
                    "recommended": "先按默认门限运行，再结合站点季节性特征调整。",
                    "ustar_rule": "站点阈值",
                },
                "footprint": {
                    "title": "Footprint",
                    "method": "kljun",
                    "applicable": "适用于窗口级源区距离摘要与站点代表性判断。",
                    "recommended": "默认推荐 kljun，z_m=3.0 m，canopy_height_m=5.0 m；复杂稳定度场景再切换到其他方法。",
                    "enabled": True,
                    "z_m": 3.0,
                    "canopy_height_m": 5.0,
                    "z0": 0.12,
                    "ol": 0.0,
                    "grid_enabled": True,
                    "grid_x_bins": 32,
                    "grid_y_bins": 25,
                },
                "uncertainty": {
                    "title": "不确定度",
                    "method": "mann_lenschow",
                    "applicable": "适用于结果归档与报告摘要。",
                    "recommended": "默认推荐 mann_lenschow，integral_timescale_s=5.0 s，confidence_level=0.95。",
                    "uncertainty_mode": "mann_lenschow",
                    "integral_timescale_s": 5.0,
                    "confidence_level": 0.95,
                },
                "spectral_correction": {
                    "title": "谱修正",
                    "method": "massman",
                    "applicable": "适用于路径平均、响应时间和传感器间距导致的高频损失修正。",
                    "recommended": "默认推荐 massman；Fratini 路径会自动优先注入 FCC measured cospectrum。",
                    "enabled": True,
                    "path_length_m": 0.15,
                    "sensor_sep_m": 0.2,
                    "response_time_s": 0.1,
                    "z_m": 3.0,
                    "ol": 0.0,
                    "use_fcc_measured_cospectrum": True,
                },
                "method_compare": {
                    "title": "Method compare",
                    "method": "enabled",
                    "applicable": "Compare footprint / uncertainty / spectral correction method families on identical RP windows.",
                    "recommended": "Enable for parity review; keep selected processing method unchanged unless review flags require action.",
                    "enabled": True,
                    "families": ["footprint", "uncertainty", "spectral_correction"],
                    "deviation_threshold": 0.25,
                    "max_samples": 4096,
                    "footprint_methods": ["kljun", "kormann_meixner", "hsieh"],
                    "uncertainty_methods": ["mann_lenschow", "finkelstein_sims"],
                    "spectral_correction_methods": ["massman", "horst", "ibrom", "fratini"],
                },
                "output": {
                    "title": "输出",
                    "method": "标准结果 + 诊断摘要",
                    "applicable": "适用于项目交付与后续归档。",
                    "recommended": "默认保留诊断字段和质量等级。",
                    "output_fields": "flux,qc,lag,ustar,diagnostics",
                    "full_output_mode": "only_available",
                },
            },
        }

    def _build_default_ec_processing_workspace(self) -> dict:
        return {
            "run": {
                "data_source": str(self.ec_processing.get("run", {}).get("data_source", "")) if hasattr(self, "ec_processing") else "",
                "time_range": str(self.ec_processing.get("run", {}).get("time_range", "")) if hasattr(self, "ec_processing") else "",
                "last_run_mode": "",
                "last_run_time": "",
                "last_result_status": "empty",
                "message": "尚未生成真实 RP 结果。",
                "active_run_id": None,
            },
            "summary": {
                "status": "empty",
                "message": "尚未生成真实 RP 结果。",
                "window_count": 0,
                "valid_window_count": 0,
                "good_window_count": 0,
                "attention_window_count": 0,
                "average_lag_seconds": 0.0,
                "average_lag_confidence": 0.0,
                "average_raw_flux": 0.0,
                "average_density_corrected_flux": 0.0,
            },
            "sections": deepcopy(self.ec_processing.get("steps", {})) if hasattr(self, "ec_processing") else {},
            "windows": [],
            "active_run_id": None,
            "selected_window_id": None,
        }

    def _build_default_spectral_qc_workspace(self) -> dict:
        return {
            "run": {
                "data_source": "",
                "time_range": "",
                "last_run_mode": "",
                "last_run_time": "",
                "last_result_status": "empty",
                "export_status": "not_exported",
            },
            "summary": {
                "lag_confidence": "--",
                "high_freq_loss_risk": "--",
                "qc_good_windows": 0,
                "attention_windows": 0,
            },
            "provenance_summary": {
                "average_tube_component": 1.0,
                "average_separation_component": 1.0,
                "average_path_component": 1.0,
                "average_phase_component": 1.0,
                "average_correction_factor": 1.0,
                "provenance_notes": [],
                "model_version": "",
            },
            "sections": {
                "overview": {
                    "focus_window": "",
                    "interpretation": "Run spectral analysis to populate this workspace with real results.",
                },
                "lag_phase": {
                    "search_window_s": 8.0,
                    "expected_lag_s": 2.4,
                    "phase_method": "cross-correlation / covariance",
                },
                "power_spectrum": {
                    "reference_model": "Welch",
                    "hf_limit_hz": 10.0,
                    "smoothing": "none",
                },
                "cross_spectrum": {
                    "averaging": "Welch segments",
                    "coherence_threshold": 0.72,
                },
                "ogive": {
                    "normalization": "integrated cross spectrum",
                    "integration_limit_hz": 3.0,
                },
                "transfer_function": {
                    "model": "minimal",
                    "tube_length_m": 0.0,
                    "cutoff_hz": 0.0,
                },
                "correction_factor": {
                    "mode": "spectral-loss-derived",
                    "factor_cap": 1.35,
                },
                "qc_overview": {
                    "grade_rule": "simple real qc",
                    "attention_threshold": 1.20,
                },
                "window_detail": {
                    "time_filter": "all",
                    "qc_filter": "all",
                    "anomaly_filter": "all",
                },
            },
            "windows": [],
            "active_run_id": None,
            "selected_window_id": None,
        }

    def _build_default_report_center_workspace(self) -> dict:
        return {
            "filters": {
                "project": self.project_profile.name or "Current Project",
                "batch": "",
                "view_mode": "engineering",
            },
            "benchmark": {
                "status": "",
                "target": "eddypro_v7",
                "reference_id": "",
                "flux_rel_threshold": 0.10,
                "lag_abs_threshold_s": 0.5,
                "wpl_rel_threshold": 0.20,
                "qc_grade_must_match": False,
            },
            "network_output": {
                "schema_target": "FLUXNET",
                "timezone_offset_hours": 0.0,
                "timestamp_refers_to": "start",
                "gap_fill_value": -9999.0,
            },
            "summary": {
                "recent_status": "No real run result has been generated yet.",
                "exportable_reports": 0,
                "attention_count": 0,
                "last_generated_at": "--",
            },
            "selected_report": "run_summary",
            "active_run_id": None,
            "export_status": "not_exported",
            "reports": self._empty_report_payloads(),
            "batch_lookup": {},
            "batch_compare": self._empty_batch_compare_payload(),
            "eddypro_compare": self._empty_eddypro_compare_payload(),
            "eddypro_attribution": self._empty_eddypro_attribution_payload(),
        }

    def _append_log(self, level: str, message: str) -> None:
        self.logs.appendleft(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
        )
        self.logs_changed.emit()

    def _latest_numeric_frame(self, device_uid: str) -> NormalizedHFFrame | None:
        rows = self.realtime_rows(device_uid=device_uid)
        return rows[-1] if rows else None

    def _device_health(self, entry: ManagedDevice, latest: NormalizedHFFrame | None) -> tuple[str, str]:
        if not entry.runtime.connected:
            return "warning", "设备离线"
        if not self._is_collecting(entry):
            return "warning", "最近没有新数据"
        quality = entry.runtime.last_frame_quality
        if quality == FrameQuality.CORRUPTED:
            return "danger", "存在损坏帧"
        if quality == FrameQuality.TRUNCATED:
            return "danger", "存在截断帧"
        if quality == FrameQuality.PARTIAL:
            return "warning", "数据帧不完整"
        if latest is None:
            return "warning", "尚未收到有效测量值"
        return "success", "数据稳定"

    def _is_collecting(self, entry: ManagedDevice) -> bool:
        if not entry.runtime.connected:
            return False
        last_seen = entry.runtime.extra.get("last_seen_at")
        if not isinstance(last_seen, datetime):
            return False
        return (datetime.now() - last_seen).total_seconds() <= 3.0

    def _latest_update_time(self) -> datetime | None:
        candidates: list[datetime] = []
        for entry in self.devices.values():
            last_seen = entry.runtime.extra.get("last_seen_at")
            if isinstance(last_seen, datetime):
                candidates.append(last_seen)
        if self.events:
            candidates.append(self.events[0].created_at)
        return max(candidates) if candidates else None

    def _operator_summary(self, frame: ProtocolFrame) -> str:
        if frame.is_ack:
            return "设备已确认当前指令。"
        if frame.parsed and frame.parsed.get("co2_ppm") is not None:
            co2 = frame.parsed.get("co2_ppm")
            h2o = frame.parsed.get("h2o_mmol")
            pressure = frame.parsed.get("pressure_kpa")
            return f"CO2 {co2:.2f} ppm · H2O {h2o:.2f} mmol · 压力 {pressure:.2f} kPa"
        if frame.quality == FrameQuality.TRUNCATED:
            return "收到截断帧，建议检查串口链路。"
        if frame.quality == FrameQuality.CORRUPTED:
            return "收到损坏帧，建议检查波特率或线路干扰。"
        return "已收到设备响应。"

    def _humanize_exception(self, message: str) -> str:
        text = str(message or "").strip()
        lowered = text.lower()
        if "timeout" in lowered:
            return "设备在等待时间内没有给出响应，请检查连线和设备状态。"
        if "open" in lowered and "serial" in lowered:
            return "串口无法打开，请检查 COM 口是否被占用。"
        if "not connected" in lowered or "尚未连接" in text:
            return "设备尚未连接，请先建立连接。"
        return text or "发生未识别的设备错误。"

    def _get_device(self, device_uid: str) -> ManagedDevice:
        entry = self.devices.get(device_uid)
        if entry is None:
            raise RuntimeError("未找到目标设备，请先在设备中心选择设备。")
        return entry
