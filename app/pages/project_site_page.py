from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, TOKENS, chip, section_title


PROJECT_SECTIONS = [
    ("overview", "项目概览", "从项目级信息开始，先确定归档位置、负责人和当前状态。"),
    ("site_info", "站点基础信息", "补齐站点元数据，为报告头信息和处理上下文打底。"),
    ("instrument_layout", "仪器布设", "用示意图与参数并列的方式说明安装关系与空间位置。"),
    ("sampling_chain", "采样链路", "把管路、过滤、泵与流量关系讲清楚，减少后续黑箱感。"),
    ("timing", "时间与采样", "定义时钟来源、采样频率与窗口划分方式。"),
    ("output_template", "输出模板", "统一导出字段、命名规则和报告抬头。"),
    ("runtime_template", "运行模板", "把预检查、归档与回放策略固化为现场模板。"),
    ("metadata", "元数据", "统一维护站点、仪器、原始文件、Biomet、动态元数据和可切换 profile。"),
]


class ProjectSitePage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("pageSurface", True)
        self.controller = controller
        self.section_indexes: dict[str, int] = {}
        self.section_items: dict[str, QTreeWidgetItem] = {}
        self.layout_diagram_labels: dict[str, QLabel] = {}
        self.chain_preview_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "项目与站点",
                "围绕项目、站点、布设与采样链路组织信息层级，让操作员也能顺着目录完成配置。",
            )
        )

        self.top_bar = self._build_top_bar()
        layout.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setSpacing(TOKENS.spacing_md)
        layout.addLayout(body, 1)

        self.tree_card = CardFrame(muted=True, role="rail")
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_md)
        tree_layout.addWidget(section_title("配置目录", "按顺序完善信息，右侧检查器会同步给出完整性提示。"))

        self.section_tree = QTreeWidget()
        self.section_tree.setHeaderHidden(True)
        self.section_tree.setIndentation(10)
        self.section_tree.itemSelectionChanged.connect(self._on_section_changed)
        tree_layout.addWidget(self.section_tree, 1)
        body.addWidget(self.tree_card, 0)
        self.tree_card.setMinimumWidth(250)
        self.tree_card.setMaximumWidth(310)

        self.content_stack = QStackedWidget()
        body.addWidget(self.content_stack, 1)

        self.site_ops_rail = self._build_site_ops_rail()
        self.site_ops_rail.setMinimumWidth(320)
        self.site_ops_rail.setMaximumWidth(380)
        body.addWidget(self.site_ops_rail, 0)

        self._build_directory()
        self._build_pages()
        self._bind_preview_signals()

        self.controller.project_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self._sync_section_from_controller)
        self.refresh()

    def refresh(self) -> None:
        workspace = self.controller.project_workspace
        overview = workspace["overview"]
        site_info = workspace["site_info"]
        layout_cfg = workspace["instrument_layout"]
        chain = workspace["sampling_chain"]
        timing = workspace["timing"]
        output = workspace["output_template"]
        runtime = workspace["runtime_template"]
        metadata = workspace.get("metadata", {})
        station_meta = metadata.get("station", {})
        instrument_meta = metadata.get("instruments", {})
        raw_description = metadata.get("raw_file_description", {})
        raw_settings = metadata.get("raw_file_settings", {})
        biomet = metadata.get("biomet_source", {})
        dynamic = metadata.get("dynamic_metadata", {})
        alternative = metadata.get("alternative_metadata", {})

        self.project_name_edit.setText(str(overview.get("project_name", "")))
        self.project_code_edit.setText(str(overview.get("project_code", "")))
        self.principal_edit.setText(str(overview.get("principal", "")))
        self.archive_root_edit.setText(str(overview.get("archive_root", "")))
        self.template_name_edit.setText(str(overview.get("template_name", "")))
        self._set_combo_text(self.project_status_combo, str(overview.get("status", "草拟")))
        self.project_notes_edit.setPlainText(str(overview.get("notes", "")))

        self.station_name_edit.setText(str(site_info.get("station_name", "")))
        self.station_code_edit.setText(str(site_info.get("station_code", "")))
        self.location_edit.setText(str(site_info.get("location", "")))
        self.land_cover_edit.setText(str(site_info.get("land_cover", "")))
        self.canopy_height_spin.setValue(float(site_info.get("canopy_height_m", 0.0) or 0.0))
        self.altitude_spin.setValue(float(site_info.get("altitude_m", 0.0) or 0.0))
        self.site_timezone_edit.setText(str(site_info.get("timezone", "")))

        self.mast_height_spin.setValue(float(layout_cfg.get("mast_height_m", 0.0) or 0.0))
        self.analyzer_height_spin.setValue(float(layout_cfg.get("analyzer_height_m", 0.0) or 0.0))
        self.sonic_height_spin.setValue(float(layout_cfg.get("sonic_height_m", 0.0) or 0.0))
        self.height_delta_spin.setValue(float(layout_cfg.get("height_delta_m", 0.0) or 0.0))
        self.orientation_spin.setValue(int(layout_cfg.get("orientation_deg", 0) or 0))
        self.analyzer_mount_edit.setText(str(layout_cfg.get("analyzer_mount", "")))
        self.sonic_mount_edit.setText(str(layout_cfg.get("sonic_mount", "")))
        self.reference_sensor_edit.setText(str(layout_cfg.get("reference_sensor", "")))
        self.layout_note_edit.setPlainText(str(layout_cfg.get("layout_note", "")))

        self.tube_length_spin.setValue(float(chain.get("tube_length_m", 0.0) or 0.0))
        self.tube_diameter_spin.setValue(float(chain.get("tube_diameter_mm", 0.0) or 0.0))
        self.tube_material_edit.setText(str(chain.get("tube_material", "")))
        self._set_bool_combo(self.heat_traced_combo, bool(chain.get("heat_traced", False)))
        self._set_bool_combo(self.insulated_combo, bool(chain.get("insulated", False)))
        self.pump_model_edit.setText(str(chain.get("pump_model", "")))
        self.flow_spin.setValue(float(chain.get("flow_lpm", 0.0) or 0.0))
        self.filter_model_edit.setText(str(chain.get("filter_model", "")))
        self.chain_note_edit.setPlainText(str(chain.get("chain_note", "")))

        self.timing_timezone_edit.setText(str(timing.get("timezone", "")))
        self.sample_hz_spin.setValue(int(timing.get("sample_hz", 20) or 20))
        self.block_minutes_spin.setValue(int(timing.get("block_minutes", 30) or 30))
        self._set_combo_text(self.clock_source_combo, str(timing.get("clock_source", "GNSS + NTP")))
        self._set_combo_text(self.start_rule_combo, str(timing.get("start_rule", "整点对齐")))
        self._set_combo_text(self.sample_mode_combo, str(timing.get("sample_mode", "连续高频")))

        self.output_template_name_edit.setText(str(output.get("template_name", "")))
        self._set_bool_combo(self.include_diagnostics_combo, bool(output.get("include_diagnostics", True)))
        self._set_bool_combo(self.include_qc_combo, bool(output.get("include_qc", True)))
        self.file_pattern_edit.setText(str(output.get("file_pattern", "")))
        self.report_header_edit.setText(str(output.get("report_header", "")))

        self.runtime_template_name_edit.setText(str(runtime.get("template_name", "")))

        if hasattr(self, "station_latitude_spin"):
            self.station_latitude_spin.setValue(float(station_meta.get("latitude", 0.0) or 0.0))
            self.station_longitude_spin.setValue(float(station_meta.get("longitude", 0.0) or 0.0))
            self.station_displacement_spin.setValue(float(station_meta.get("displacement_height", 0.0) or 0.0))
            self.station_roughness_spin.setValue(float(station_meta.get("roughness_length", 0.0) or 0.0))
            self._set_combo_text(self.station_timestamp_ref_combo, str(station_meta.get("timestamp_refers_to", "end_of_averaging_period")))
            self.station_file_duration_spin.setValue(float(station_meta.get("file_duration", 0.0) or 0.0))
            self.sonic_model_meta_edit.setText(str(instrument_meta.get("sonic_model", "")))
            self.analyzer_model_meta_edit.setText(str(instrument_meta.get("analyzer_model", "")))
            self.sonic_mfr_edit.setText(str(instrument_meta.get("sonic_manufacturer", "")))
            self.analyzer_mfr_edit.setText(str(instrument_meta.get("analyzer_manufacturer", "")))
            self.sonic_fw_edit.setText(str(instrument_meta.get("sonic_firmware", "")))
            self.analyzer_fw_edit.setText(str(instrument_meta.get("analyzer_firmware", "")))
            self.sonic_id_edit.setText(str(instrument_meta.get("sonic_instrument_id", "")))
            self.analyzer_id_edit.setText(str(instrument_meta.get("analyzer_instrument_id", "")))
            self.sonic_serial_meta_edit.setText(str(instrument_meta.get("sonic_serial", "")))
            self.analyzer_serial_meta_edit.setText(str(instrument_meta.get("analyzer_serial", "")))
            self.geometry_detail_edit.setPlainText(str(instrument_meta.get("geometry_detail", "")))
            self.raw_source_name_edit.setText(str(raw_description.get("source_name", "")))
            self._set_combo_text(self.raw_source_type_combo, str(raw_description.get("source_type", "hf_frame")))
            self.raw_timestamp_column_edit.setText(str(raw_description.get("timestamp_column", "timestamp")))
            self.raw_timezone_edit.setText(str(raw_description.get("timezone", "")))
            self.raw_notes_edit.setPlainText(str(raw_description.get("notes", "")))
            self.raw_column_mappings_edit.setPlainText(str(raw_description.get("column_mappings_json", "[]")))
            self.raw_sample_hz_spin.setValue(float(raw_settings.get("sample_hz", 0.0) or 0.0))
            self.raw_delimiter_edit.setText(str(raw_settings.get("delimiter", ",")))
            self.raw_decimal_edit.setText(str(raw_settings.get("decimal", ".")))
            self.raw_header_rows_spin.setValue(int(raw_settings.get("header_rows", 1) or 1))
            self.raw_encoding_edit.setText(str(raw_settings.get("encoding", "utf-8")))
            self.raw_missing_tokens_edit.setText(str(raw_settings.get("missing_tokens", ",NA,NaN")))
            self._set_combo_text(self.biomet_mode_combo, str(biomet.get("source_mode", "none")))
            self.biomet_source_path_edit.setText(str(biomet.get("source_path", "")))
            self.biomet_time_column_edit.setText(str(biomet.get("time_column", "timestamp")))
            self._set_combo_text(self.biomet_agg_combo, str(biomet.get("aggregation_method", "mean")))
            self.biomet_fields_edit.setText(str(biomet.get("fields", "")))
            self.biomet_glob_edit.setText(str(biomet.get("directory_glob", "*.csv")))
            self.biomet_notes_edit.setPlainText(str(biomet.get("notes", "")))
            self.dynamic_csv_path_edit.setText(str(dynamic.get("source_path", "")))
            self.dynamic_start_column_edit.setText(str(dynamic.get("start_column", "start_time")))
            self.dynamic_end_column_edit.setText(str(dynamic.get("end_column", "end_time")))
            self.dynamic_timezone_edit.setText(str(dynamic.get("timezone", "Asia/Shanghai")))
            self._dynamic_metadata_records = list(dynamic.get("records", []))
            self.dynamic_record_count_label.setText(f"{len(self._dynamic_metadata_records)} record(s)")
            self._refresh_metadata_profiles()
            self.metadata_profile_combo.setEditText(str(alternative.get("active_profile", "")))
        self._set_combo_text(self.precheck_mode_combo, str(runtime.get("precheck_mode", "严格")))
        self._set_bool_combo(self.auto_archive_combo, bool(runtime.get("auto_archive", True)))
        self._set_bool_combo(self.replay_ready_combo, bool(runtime.get("replay_ready", True)))
        self.operator_note_edit.setPlainText(str(runtime.get("operator_note", "")))

        self._refresh_layout_diagram()
        self._refresh_chain_preview()
        self._refresh_timing_preview()
        self._refresh_output_preview()
        self._refresh_runtime_preview()
        if hasattr(self, "metadata_status_label"):
            self._refresh_metadata_status()
        self._refresh_top_bar()
        self._sync_section_from_controller()

    def _build_top_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setProperty("projectSiteCommandDock", True)
        card.setMaximumHeight(86)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_xs, TOKENS.spacing_lg, TOKENS.spacing_xs)
        layout.setSpacing(TOKENS.spacing_sm)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(TOKENS.spacing_sm)
        self.current_project_value = QLabel("--")
        self.current_site_value = QLabel("--")
        self.current_status_chip = chip("草拟", "warning")
        self.integrity_value = QLabel("--")
        self.project_summary_metric_cards: list[CardFrame] = []
        for title, widget in (
            ("当前项目", self.current_project_value),
            ("当前站点", self.current_site_value),
            ("状态", self.current_status_chip),
            ("完整性", self.integrity_value),
        ):
            metric_card = self._metric_box(title, widget, compact=True)
            self.project_summary_metric_cards.append(metric_card)
            summary_row.addWidget(metric_card, 1)
        layout.addLayout(summary_row, 1)

        button_column = QVBoxLayout()
        button_column.setSpacing(TOKENS.spacing_xs)
        self.project_command_buttons: list[QPushButton] = []

        row1 = QHBoxLayout()
        row1.setSpacing(TOKENS.spacing_xs)
        new_button = QPushButton("新建")
        new_button.clicked.connect(self._new_workspace)
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(self._duplicate_workspace)
        template_button = QPushButton("导入模板")
        template_button.clicked.connect(self._import_template)
        for button in (new_button, copy_button, template_button):
            button.setProperty("projectSiteCommandButton", True)
            button.setMaximumHeight(26)
            self.project_command_buttons.append(button)
        row1.addWidget(new_button)
        row1.addWidget(copy_button)
        row1.addWidget(template_button)

        row2 = QHBoxLayout()
        row2.setSpacing(TOKENS.spacing_xs)
        save_button = QPushButton("保存")
        save_button.setProperty("variant", "primary")
        save_button.clicked.connect(self._save)
        check_button = QPushButton("完整性检查")
        check_button.clicked.connect(self._check_completeness)
        for button in (save_button, check_button):
            button.setProperty("projectSiteCommandButton", True)
            button.setMaximumHeight(26)
            self.project_command_buttons.append(button)
        row2.addWidget(save_button)
        row2.addWidget(check_button)

        button_column.addLayout(row1)
        button_column.addLayout(row2)
        layout.addLayout(button_column)
        return card

    def _build_site_ops_rail(self) -> CardFrame:
        card = CardFrame(muted=True, role="rail")
        card.setProperty("projectSiteOpsRail", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title("现场闭合控制轨", "把站点上下文、采样链路、元数据和交付状态压缩到可操作的右侧轨道。"))
        self.site_ops_chip = chip("待检查", "warning")
        layout.addWidget(self.site_ops_chip)

        self.site_ops_action_bar = CardFrame(muted=True, role="console")
        self.site_ops_action_bar.setProperty("deckRole", "projectSiteActionDock")
        self.site_ops_action_bar.setProperty("projectSiteActionDock", True)
        self.site_ops_action_bar.setMaximumHeight(72)
        action_layout = QGridLayout(self.site_ops_action_bar)
        action_layout.setContentsMargins(TOKENS.spacing_sm, 2, TOKENS.spacing_sm, 2)
        action_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        action_layout.setVerticalSpacing(0)
        action_label = QLabel("现场动作")
        action_label.setObjectName("metricLabel")
        action_label.setMaximumHeight(16)
        action_layout.addWidget(action_label, 0, 0, 1, 3)

        self.site_ops_next_action_button = self._site_ops_action_button("下一动作", "按当前缺口跳到最需要处理的配置区段。")
        self.site_ops_next_action_button.clicked.connect(self._activate_site_ops_next_action)
        self.site_ops_save_button = self._site_ops_action_button("保存", "保存当前项目与站点配置快照。")
        self.site_ops_save_button.clicked.connect(self._save_site_ops_snapshot)
        self.site_ops_check_button = self._site_ops_action_button("检查", "执行完整性检查并更新闭合提示。")
        self.site_ops_check_button.clicked.connect(self._run_site_ops_completeness_check)
        self.site_ops_chain_button = self._site_ops_action_button("采样链路", "跳转到采样链路区段。")
        self.site_ops_chain_button.clicked.connect(lambda: self._activate_site_ops_target("sampling_chain"))
        self.site_ops_metadata_button = self._site_ops_action_button("元数据", "跳转到元数据区段。")
        self.site_ops_metadata_button.clicked.connect(lambda: self._activate_site_ops_target("metadata"))
        for index, button in enumerate((
            self.site_ops_next_action_button,
            self.site_ops_save_button,
            self.site_ops_check_button,
            self.site_ops_chain_button,
            self.site_ops_metadata_button,
        )):
            action_layout.addWidget(button, 1 + index // 3, index % 3)
        layout.addWidget(self.site_ops_action_bar)

        self.site_ops_last_action_note = QLabel("尚未执行现场动作。")
        self.site_ops_last_action_note.setObjectName("subtitle")
        self.site_ops_last_action_note.setWordWrap(False)
        self.site_ops_last_action_note.setMaximumHeight(24)
        layout.addWidget(self.site_ops_last_action_note)

        self.site_ops_values: dict[str, tuple[QLabel, QLabel]] = {}
        self.site_ops_tiles: list[CardFrame] = []
        self.site_ops_grid = QGridLayout()
        self.site_ops_grid.setContentsMargins(0, 0, 0, 0)
        self.site_ops_grid.setHorizontalSpacing(0)
        self.site_ops_grid.setVerticalSpacing(TOKENS.spacing_xs)
        for index, (key, title) in enumerate((
            ("readiness", "完整性"),
            ("geometry", "站点几何"),
            ("chain", "采样链路"),
            ("timing", "时间窗"),
            ("delivery", "交付模板"),
            ("metadata", "元数据"),
        )):
            tile = self._site_ops_tile(key, title)
            self.site_ops_tiles.append(tile)
            self.site_ops_grid.addWidget(tile, index, 0)
        layout.addLayout(self.site_ops_grid)

        next_card = CardFrame(muted=True, role="tile")
        self.site_ops_next_card = next_card
        next_card.setProperty("projectSiteNextCard", True)
        next_card.setMinimumHeight(70)
        next_card.setMaximumHeight(80)
        next_layout = QVBoxLayout(next_card)
        next_layout.setContentsMargins(TOKENS.spacing_md, 3, TOKENS.spacing_md, 3)
        next_layout.setSpacing(1)
        next_label = QLabel("下一步")
        next_label.setObjectName("metricLabel")
        self.site_ops_next_value = QLabel("--")
        self.site_ops_next_value.setObjectName("metricValue")
        self.site_ops_next_value.setProperty("compactMetric", True)
        self.site_ops_next_value.setWordWrap(True)
        self.site_ops_next_note = QLabel("--")
        self.site_ops_next_note.setObjectName("subtitle")
        self.site_ops_next_note.setWordWrap(True)
        next_layout.addWidget(next_label)
        next_layout.addWidget(self.site_ops_next_value)
        next_layout.addWidget(self.site_ops_next_note)
        layout.addWidget(next_card)
        layout.addStretch(1)
        return card

    def _site_ops_action_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setProperty("railAction", True)
        button.setProperty("projectSiteRailAction", True)
        button.setMinimumWidth(0)
        button.setMaximumHeight(24)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return button

    def _site_ops_tile(self, key: str, title: str) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        card.setProperty("projectSiteOpsTile", True)
        card.setMinimumHeight(24)
        card.setMaximumHeight(26)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, 1, TOKENS.spacing_sm, 1)
        layout.setSpacing(TOKENS.spacing_xs)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        label.setMinimumWidth(54)
        label.setMaximumWidth(62)
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setProperty("compactMetric", True)
        value.setWordWrap(False)
        value.setMinimumWidth(74)
        note = QLabel("--")
        note.setObjectName("subtitle")
        note.setWordWrap(False)
        note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(label)
        layout.addWidget(value)
        layout.addWidget(note, 1)
        self.site_ops_values[key] = (value, note)
        return card

    def _build_directory(self) -> None:
        root = QTreeWidgetItem(["项目配置"])
        root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
        self.section_tree.addTopLevelItem(root)
        for key, title, _subtitle in PROJECT_SECTIONS:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, key)
            item.setToolTip(0, title)
            root.addChild(item)
            self.section_items[key] = item
        root.setExpanded(True)

    def _build_pages(self) -> None:
        for key, title, subtitle in PROJECT_SECTIONS:
            container = QWidget()
            page_layout = QVBoxLayout(container)
            page_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            page_layout.setSpacing(TOKENS.spacing_md)
            page_layout.addWidget(section_title(title, subtitle))

            builder = getattr(self, f"_build_{key}_page")
            builder(page_layout)
            page_layout.addStretch(1)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(container)
            self.section_indexes[key] = self.content_stack.addWidget(scroll)

    def _build_overview_page(self, layout: QVBoxLayout) -> None:
        summary_card = CardFrame(muted=True)
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        summary_layout.setSpacing(TOKENS.spacing_md)
        self.overview_metric_project_code = QLabel("--")
        self.overview_metric_principal = QLabel("--")
        self.overview_metric_archive_root = QLabel("--")
        for title, value in (
            ("项目编号", self.overview_metric_project_code),
            ("负责人", self.overview_metric_principal),
            ("归档根目录", self.overview_metric_archive_root),
        ):
            summary_layout.addWidget(self._metric_box(title, value), 1)
        layout.addWidget(summary_card)

        form_card = CardFrame()
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        form_layout.setSpacing(TOKENS.spacing_md)
        form_layout.addWidget(section_title("项目基础设置", "先固定项目身份与归档位置，后续站点与模板才能稳定复用。"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)

        self.project_name_edit = QLineEdit()
        self.project_code_edit = QLineEdit()
        self.principal_edit = QLineEdit()
        self.archive_root_edit = QLineEdit()
        self.project_status_combo = QComboBox()
        self.project_status_combo.addItems(["新建", "草拟", "待部署", "运行中", "已归档"])
        self.template_name_edit = QLineEdit()
        self.project_notes_edit = QTextEdit()
        self.project_notes_edit.setMinimumHeight(120)

        form.addRow("项目名称", self.project_name_edit)
        form.addRow("项目编号", self.project_code_edit)
        form.addRow("负责人", self.principal_edit)
        form.addRow("归档根目录", self.archive_root_edit)
        form.addRow("项目状态", self.project_status_combo)
        form.addRow("引用模板", self.template_name_edit)
        form.addRow("项目说明", self.project_notes_edit)
        form_card.layout().addLayout(form)
        layout.addWidget(form_card)

    def _build_site_info_page(self, layout: QVBoxLayout) -> None:
        form_card = CardFrame()
        form_layout = QHBoxLayout(form_card)
        form_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        form_layout.setSpacing(TOKENS.spacing_md)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(TOKENS.spacing_md)
        left_layout.addWidget(section_title("站点基础信息", "这些信息会直接进入报告头信息、运行元数据和后续处理上下文。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.station_name_edit = QLineEdit()
        self.station_code_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.land_cover_edit = QLineEdit()
        self.canopy_height_spin = self._double_spin(0.0, 50.0, 2, suffix=" m")
        self.altitude_spin = self._double_spin(-500.0, 9000.0, 1, suffix=" m")
        self.site_timezone_edit = QLineEdit()
        form.addRow("站点名称", self.station_name_edit)
        form.addRow("站点编码", self.station_code_edit)
        form.addRow("地理位置", self.location_edit)
        form.addRow("地表覆盖", self.land_cover_edit)
        form.addRow("冠层高度", self.canopy_height_spin)
        form.addRow("海拔", self.altitude_spin)
        form.addRow("时区", self.site_timezone_edit)
        left_layout.addLayout(form)
        form_layout.addWidget(left, 3)

        guide_card = CardFrame(muted=True)
        guide_layout = QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        guide_layout.setSpacing(TOKENS.spacing_sm)
        guide_layout.addWidget(section_title("填写提示", "先写清站点身份，再补地表与高度信息。"))
        for text in (
            "站点名称与编码建议和归档目录保持一致，避免后期多人维护时出现混乱。",
            "地表覆盖和冠层高度会影响后续湍流检验和结果解释。",
            "时区建议明确写入，便于跨设备时间对齐与外部数据联动。",
        ):
            note = QLabel(f"• {text}")
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            guide_layout.addWidget(note)
        form_layout.addWidget(guide_card, 2)
        layout.addWidget(form_card)

    def _build_instrument_layout_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        diagram_card = CardFrame(muted=True)
        diagram_layout = QVBoxLayout(diagram_card)
        diagram_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        diagram_layout.setSpacing(TOKENS.spacing_md)
        diagram_layout.addWidget(section_title("布设示意图", "示意图用于快速理解相对位置，不替代现场安装图。"))

        for key, title, tone in (
            ("sonic", "超声风温", "accent"),
            ("analyzer", "气体分析仪", "success"),
            ("reference", "参考传感器", "warning"),
        ):
            block = CardFrame()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            block_layout.setSpacing(TOKENS.spacing_xs)
            block_layout.addWidget(chip(title, tone))
            value = QLabel("--")
            value.setObjectName("subtitle")
            value.setWordWrap(True)
            block_layout.addWidget(value)
            self.layout_diagram_labels[key] = value
            diagram_layout.addWidget(block)

        self.layout_diagram_labels["orientation"] = QLabel("--")
        self.layout_diagram_labels["orientation"].setObjectName("subtitle")
        self.layout_diagram_labels["orientation"].setWordWrap(True)
        diagram_layout.addWidget(self.layout_diagram_labels["orientation"])
        row.addWidget(diagram_card, 2)

        config_card = CardFrame()
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        config_layout.setSpacing(TOKENS.spacing_md)
        config_layout.addWidget(section_title("布设参数", "尽量把安装高度差、朝向和挂载位置写清楚，便于后续复核。"))

        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.mast_height_spin = self._double_spin(0.0, 50.0, 2, suffix=" m")
        self.analyzer_height_spin = self._double_spin(0.0, 50.0, 2, suffix=" m")
        self.sonic_height_spin = self._double_spin(0.0, 50.0, 2, suffix=" m")
        self.height_delta_spin = self._double_spin(0.0, 10.0, 2, suffix=" m")
        self.orientation_spin = QSpinBox()
        self.orientation_spin.setRange(0, 359)
        self.orientation_spin.setSuffix(" °")
        self.analyzer_mount_edit = QLineEdit()
        self.sonic_mount_edit = QLineEdit()
        self.reference_sensor_edit = QLineEdit()
        self.layout_note_edit = QTextEdit()
        self.layout_note_edit.setMinimumHeight(120)
        form.addRow("主塔高度", self.mast_height_spin)
        form.addRow("分析仪高度", self.analyzer_height_spin)
        form.addRow("超声高度", self.sonic_height_spin)
        form.addRow("高度差", self.height_delta_spin)
        form.addRow("朝向", self.orientation_spin)
        form.addRow("分析仪挂载位", self.analyzer_mount_edit)
        form.addRow("超声挂载位", self.sonic_mount_edit)
        form.addRow("参考传感器", self.reference_sensor_edit)
        form.addRow("现场说明", self.layout_note_edit)
        config_layout.addLayout(form)
        row.addWidget(config_card, 3)

    def _build_sampling_chain_page(self, layout: QVBoxLayout) -> None:
        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("采样链路示意", "让现场工程师一眼看清进样到分析的路径与关键器件。"))

        flow_row = QHBoxLayout()
        flow_row.setSpacing(TOKENS.spacing_sm)
        for key, title, tone in (
            ("inlet", "进样口", "accent"),
            ("filter", "过滤器", "warning"),
            ("pump", "泵", "success"),
            ("analyzer", "分析仪", "accent"),
        ):
            card = CardFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            card_layout.setSpacing(TOKENS.spacing_xs)
            card_layout.addWidget(chip(title, tone))
            value = QLabel("--")
            value.setObjectName("subtitle")
            value.setWordWrap(True)
            card_layout.addWidget(value)
            self.chain_preview_labels[key] = value
            flow_row.addWidget(card, 1)
            if key != "analyzer":
                arrow = QLabel("→")
                arrow.setObjectName("sectionTitle")
                flow_row.addWidget(arrow)
        preview_layout.addLayout(flow_row)
        layout.addWidget(preview_card)

        config_card = CardFrame()
        config_layout = QHBoxLayout(config_card)
        config_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        config_layout.setSpacing(TOKENS.spacing_md)

        left = QWidget()
        left_layout = QFormLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setHorizontalSpacing(TOKENS.spacing_md)
        left_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.tube_length_spin = self._double_spin(0.0, 200.0, 1, suffix=" m")
        self.tube_diameter_spin = self._double_spin(0.0, 50.0, 1, suffix=" mm")
        self.tube_material_edit = QLineEdit()
        self.heat_traced_combo = self._bool_combo("启用伴热", "未启用伴热")
        self.insulated_combo = self._bool_combo("已保温", "未保温")
        self.pump_model_edit = QLineEdit()
        self.flow_spin = self._double_spin(0.0, 100.0, 1, suffix=" L/min")
        self.filter_model_edit = QLineEdit()
        self.chain_note_edit = QTextEdit()
        self.chain_note_edit.setMinimumHeight(120)
        left_layout.addRow("管长", self.tube_length_spin)
        left_layout.addRow("管径", self.tube_diameter_spin)
        left_layout.addRow("管材", self.tube_material_edit)
        left_layout.addRow("伴热", self.heat_traced_combo)
        left_layout.addRow("保温", self.insulated_combo)
        left_layout.addRow("泵", self.pump_model_edit)
        left_layout.addRow("流量", self.flow_spin)
        left_layout.addRow("过滤器", self.filter_model_edit)
        left_layout.addRow("链路说明", self.chain_note_edit)
        config_layout.addWidget(left, 3)

        guide_card = CardFrame(muted=True)
        guide_layout = QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        guide_layout.setSpacing(TOKENS.spacing_sm)
        guide_layout.addWidget(section_title("链路关注点", "长管路、低流量和未伴热通常是现场问题的高发组合。"))
        for text in (
            "管长、管径和流量会共同影响时滞与频率响应。",
            "伴热与保温建议明确写入，便于后续解释冷凝风险。",
            "过滤器型号尽量写全，方便维护时确认压损与更换周期。",
        ):
            note = QLabel(f"• {text}")
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            guide_layout.addWidget(note)
        config_layout.addWidget(guide_card, 2)
        layout.addWidget(config_card)

    def _build_timing_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        config_card = CardFrame()
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        config_layout.setSpacing(TOKENS.spacing_md)
        config_layout.addWidget(section_title("时间与采样设置", "这里定义窗口切分、时钟来源与采样节奏。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.timing_timezone_edit = QLineEdit()
        self.sample_hz_spin = QSpinBox()
        self.sample_hz_spin.setRange(1, 100)
        self.block_minutes_spin = QSpinBox()
        self.block_minutes_spin.setRange(1, 180)
        self.clock_source_combo = QComboBox()
        self.clock_source_combo.addItems(["GNSS + NTP", "本地时钟", "工控机对时"])
        self.start_rule_combo = QComboBox()
        self.start_rule_combo.addItems(["整点对齐", "采集启动即开始", "按计划任务对齐"])
        self.sample_mode_combo = QComboBox()
        self.sample_mode_combo.addItems(["连续高频", "分时采样", "事件触发"])
        form.addRow("时区", self.timing_timezone_edit)
        form.addRow("采样频率", self.sample_hz_spin)
        form.addRow("窗口长度", self.block_minutes_spin)
        form.addRow("时钟来源", self.clock_source_combo)
        form.addRow("起始规则", self.start_rule_combo)
        form.addRow("采样模式", self.sample_mode_combo)
        config_layout.addLayout(form)
        row.addWidget(config_card, 3)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("窗口预览", "把窗口规模和采样量转成直观结果，减少配置歧义。"))
        self.samples_per_window_label = QLabel("--")
        self.samples_per_window_label.setObjectName("metricValue")
        preview_layout.addWidget(self.samples_per_window_label)
        self.timing_preview_note = QLabel("--")
        self.timing_preview_note.setObjectName("subtitle")
        self.timing_preview_note.setWordWrap(True)
        preview_layout.addWidget(self.timing_preview_note)
        row.addWidget(preview_card, 2)

    def _build_output_template_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        config_card = CardFrame()
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        config_layout.setSpacing(TOKENS.spacing_md)
        config_layout.addWidget(section_title("输出模板", "统一结果文件和报告头部，避免项目交付时字段漂移。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.output_template_name_edit = QLineEdit()
        self.include_diagnostics_combo = self._bool_combo("包含诊断字段", "不包含诊断字段")
        self.include_qc_combo = self._bool_combo("包含 QC 字段", "不包含 QC 字段")
        self.file_pattern_edit = QLineEdit()
        self.report_header_edit = QLineEdit()
        form.addRow("模板名称", self.output_template_name_edit)
        form.addRow("诊断字段", self.include_diagnostics_combo)
        form.addRow("QC 字段", self.include_qc_combo)
        form.addRow("文件命名", self.file_pattern_edit)
        form.addRow("报告抬头", self.report_header_edit)
        config_layout.addLayout(form)
        row.addWidget(config_card, 3)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("输出预览", "先确认导出长相，再进入正式处理与归档。"))
        self.output_preview_name = QLabel("--")
        self.output_preview_name.setObjectName("metricValue")
        preview_layout.addWidget(self.output_preview_name)
        self.output_preview_note = QLabel("--")
        self.output_preview_note.setObjectName("subtitle")
        self.output_preview_note.setWordWrap(True)
        preview_layout.addWidget(self.output_preview_note)
        row.addWidget(preview_card, 2)

    def _build_runtime_template_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        config_card = CardFrame()
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        config_layout.setSpacing(TOKENS.spacing_md)
        config_layout.addWidget(section_title("运行模板", "把上线前检查与数据落盘策略沉淀成模板，减少现场临时判断。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.runtime_template_name_edit = QLineEdit()
        self.precheck_mode_combo = QComboBox()
        self.precheck_mode_combo.addItems(["严格", "标准", "快速"])
        self.auto_archive_combo = self._bool_combo("自动归档", "手动归档")
        self.replay_ready_combo = self._bool_combo("保留回放材料", "只保留最小材料")
        self.operator_note_edit = QTextEdit()
        self.operator_note_edit.setMinimumHeight(120)
        form.addRow("模板名称", self.runtime_template_name_edit)
        form.addRow("预检查级别", self.precheck_mode_combo)
        form.addRow("归档策略", self.auto_archive_combo)
        form.addRow("回放准备", self.replay_ready_combo)
        form.addRow("操作提示", self.operator_note_edit)
        config_layout.addLayout(form)
        row.addWidget(config_card, 3)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("运行摘要", "让值守人员知道这套模板会自动做什么。"))
        self.runtime_preview_status = QLabel("--")
        self.runtime_preview_status.setObjectName("metricValue")
        preview_layout.addWidget(self.runtime_preview_status)
        self.runtime_preview_note = QLabel("--")
        self.runtime_preview_note.setObjectName("subtitle")
        self.runtime_preview_note.setWordWrap(True)
        preview_layout.addWidget(self.runtime_preview_note)
        row.addWidget(preview_card, 2)

    def _build_metadata_page(self, layout: QVBoxLayout) -> None:
        card = CardFrame()
        card.setProperty("metadataEditorShell", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        card_layout.setSpacing(TOKENS.spacing_md)
        card_layout.addWidget(section_title("Metadata Editor", "集中维护站点、仪器、原始文件、Biomet 与动态元数据。"))

        self.metadata_cockpit_card = CardFrame(role="cockpit")
        self.metadata_cockpit_card.setProperty("metadataCockpitDock", True)
        self.metadata_cockpit_card.setMaximumHeight(88)
        cockpit_layout = QHBoxLayout(self.metadata_cockpit_card)
        cockpit_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_xs, TOKENS.spacing_lg, TOKENS.spacing_xs)
        cockpit_layout.setSpacing(TOKENS.spacing_sm)
        self.metadata_summary_values: dict[str, QLabel] = {}
        self.metadata_summary_tiles: list[CardFrame] = []
        for key, title in (
            ("station", "Station"),
            ("instrument", "Instrument"),
            ("raw", "Raw file"),
            ("dynamic", "Dynamic"),
            ("profile", "Profile"),
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("metadataSummaryTile", True)
            tile.setMaximumHeight(56)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
            tile_layout.setSpacing(1)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(False)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            tile_layout.addWidget(label)
            tile_layout.addWidget(value)
            self.metadata_summary_values[key] = value
            self.metadata_summary_tiles.append(tile)
            cockpit_layout.addWidget(tile, 1)
        card_layout.addWidget(self.metadata_cockpit_card)

        self.metadata_editor_cards: list[CardFrame] = []
        self.metadata_panel_buttons: dict[str, QToolButton] = {}
        self.metadata_panel_order: list[str] = []
        self.metadata_panel_switch = QWidget()
        self.metadata_panel_switch.setProperty("metadataPanelSwitch", True)
        self.metadata_panel_switch_layout = QGridLayout(self.metadata_panel_switch)
        self.metadata_panel_switch_layout.setContentsMargins(0, 0, 0, 0)
        self.metadata_panel_switch_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        self.metadata_panel_switch_layout.setVerticalSpacing(TOKENS.spacing_xs)
        self.metadata_editor_stack = QStackedWidget()
        self.metadata_editor_stack.setProperty("metadataEditorStack", True)
        card_layout.addWidget(self.metadata_panel_switch)
        card_layout.addWidget(self.metadata_editor_stack)

        station_card = CardFrame(muted=True)
        station_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(station_card)
        station_layout = QFormLayout(station_card)
        station_layout.setHorizontalSpacing(TOKENS.spacing_md)
        station_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.station_latitude_spin = self._double_spin(-90.0, 90.0, 6)
        self.station_longitude_spin = self._double_spin(-180.0, 180.0, 6)
        self.station_displacement_spin = self._double_spin(0.0, 50.0, 3, suffix=" m")
        self.station_roughness_spin = self._double_spin(0.0, 10.0, 3, suffix=" m")
        self.station_timestamp_ref_combo = QComboBox()
        self.station_timestamp_ref_combo.addItems(["end_of_averaging_period", "beginning_of_averaging_period", "instantaneous"])
        self.station_file_duration_spin = self._double_spin(0.0, 1440.0, 1, suffix=" min")
        station_layout.addRow("Station latitude", self.station_latitude_spin)
        station_layout.addRow("Station longitude", self.station_longitude_spin)
        station_layout.addRow("Displacement height", self.station_displacement_spin)
        station_layout.addRow("Roughness length", self.station_roughness_spin)
        station_layout.addRow("Timestamp refers to", self.station_timestamp_ref_combo)
        station_layout.addRow("File duration", self.station_file_duration_spin)
        self._add_metadata_panel("station", "Station", station_card)

        instruments_card = CardFrame(muted=True)
        instruments_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(instruments_card)
        instruments_layout = QFormLayout(instruments_card)
        instruments_layout.setHorizontalSpacing(TOKENS.spacing_md)
        instruments_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.sonic_model_meta_edit = QLineEdit()
        self.analyzer_model_meta_edit = QLineEdit()
        self.sonic_mfr_edit = QLineEdit()
        self.analyzer_mfr_edit = QLineEdit()
        self.sonic_fw_edit = QLineEdit()
        self.analyzer_fw_edit = QLineEdit()
        self.sonic_id_edit = QLineEdit()
        self.analyzer_id_edit = QLineEdit()
        self.sonic_serial_meta_edit = QLineEdit()
        self.analyzer_serial_meta_edit = QLineEdit()
        self.geometry_detail_edit = QTextEdit()
        self.geometry_detail_edit.setMinimumHeight(90)
        instruments_layout.addRow("Sonic model", self.sonic_model_meta_edit)
        instruments_layout.addRow("Analyzer model", self.analyzer_model_meta_edit)
        instruments_layout.addRow("Sonic manufacturer", self.sonic_mfr_edit)
        instruments_layout.addRow("Analyzer manufacturer", self.analyzer_mfr_edit)
        instruments_layout.addRow("Sonic firmware", self.sonic_fw_edit)
        instruments_layout.addRow("Analyzer firmware", self.analyzer_fw_edit)
        instruments_layout.addRow("Sonic instrument id", self.sonic_id_edit)
        instruments_layout.addRow("Analyzer instrument id", self.analyzer_id_edit)
        instruments_layout.addRow("Sonic serial", self.sonic_serial_meta_edit)
        instruments_layout.addRow("Analyzer serial", self.analyzer_serial_meta_edit)
        instruments_layout.addRow("Geometry detail", self.geometry_detail_edit)
        self._add_metadata_panel("instrument", "Instrument", instruments_card)

        raw_card = CardFrame(muted=True)
        raw_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(raw_card)
        raw_layout = QFormLayout(raw_card)
        raw_layout.setHorizontalSpacing(TOKENS.spacing_md)
        raw_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.raw_source_name_edit = QLineEdit()
        self.raw_source_type_combo = QComboBox()
        self.raw_source_type_combo.setEditable(True)
        self.raw_source_type_combo.addItems(["hf_frame", "csv", "ascii"])
        self.raw_timestamp_column_edit = QLineEdit()
        self.raw_timezone_edit = QLineEdit()
        self.raw_notes_edit = QTextEdit()
        self.raw_notes_edit.setMinimumHeight(70)
        self.raw_column_mappings_edit = QTextEdit()
        self.raw_column_mappings_edit.setMinimumHeight(180)
        raw_layout.addRow("Raw source name", self.raw_source_name_edit)
        raw_layout.addRow("Raw source type", self.raw_source_type_combo)
        raw_layout.addRow("Timestamp column", self.raw_timestamp_column_edit)
        raw_layout.addRow("Raw timezone", self.raw_timezone_edit)
        raw_layout.addRow("Column mappings (JSON)", self.raw_column_mappings_edit)
        raw_layout.addRow("Raw notes", self.raw_notes_edit)
        self._add_metadata_panel("raw", "Raw file", raw_card)

        raw_settings_card = CardFrame(muted=True)
        raw_settings_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(raw_settings_card)
        raw_settings_layout = QFormLayout(raw_settings_card)
        raw_settings_layout.setHorizontalSpacing(TOKENS.spacing_md)
        raw_settings_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.raw_sample_hz_spin = self._double_spin(0.1, 100.0, 2, suffix=" Hz")
        self.raw_delimiter_edit = QLineEdit()
        self.raw_decimal_edit = QLineEdit()
        self.raw_header_rows_spin = QSpinBox()
        self.raw_header_rows_spin.setRange(0, 100)
        self.raw_encoding_edit = QLineEdit()
        self.raw_missing_tokens_edit = QLineEdit()
        raw_settings_layout.addRow("Raw sample rate", self.raw_sample_hz_spin)
        raw_settings_layout.addRow("Delimiter", self.raw_delimiter_edit)
        raw_settings_layout.addRow("Decimal mark", self.raw_decimal_edit)
        raw_settings_layout.addRow("Header rows", self.raw_header_rows_spin)
        raw_settings_layout.addRow("Encoding", self.raw_encoding_edit)
        raw_settings_layout.addRow("Missing tokens", self.raw_missing_tokens_edit)
        self._add_metadata_panel("raw_settings", "Raw settings", raw_settings_card)

        biomet_card = CardFrame(muted=True)
        biomet_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(biomet_card)
        biomet_layout = QFormLayout(biomet_card)
        biomet_layout.setHorizontalSpacing(TOKENS.spacing_md)
        biomet_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.biomet_mode_combo = QComboBox()
        self.biomet_mode_combo.addItems(["none", "external_file", "external_directory", "ghg_bundle"])
        self.biomet_source_path_edit = QLineEdit()
        biomet_path_row = QHBoxLayout()
        biomet_path_row.addWidget(self.biomet_source_path_edit, 1)
        biomet_file_button = QPushButton("Select file")
        biomet_file_button.setProperty("metadataActionButton", True)
        biomet_file_button.setMaximumHeight(26)
        biomet_file_button.clicked.connect(lambda: self._choose_biomet_path(directory=False))
        biomet_dir_button = QPushButton("Select directory")
        biomet_dir_button.setProperty("metadataActionButton", True)
        biomet_dir_button.setMaximumHeight(26)
        biomet_dir_button.clicked.connect(lambda: self._choose_biomet_path(directory=True))
        biomet_path_row.addWidget(biomet_file_button)
        biomet_path_row.addWidget(biomet_dir_button)
        self.biomet_time_column_edit = QLineEdit()
        self.biomet_agg_combo = QComboBox()
        self.biomet_agg_combo.addItems(["mean", "last", "max", "min"])
        self.biomet_fields_edit = QLineEdit()
        self.biomet_glob_edit = QLineEdit()
        self.biomet_notes_edit = QTextEdit()
        self.biomet_notes_edit.setMinimumHeight(70)
        biomet_layout.addRow("Biomet source mode", self.biomet_mode_combo)
        biomet_layout.addRow("Biomet path", biomet_path_row)
        biomet_layout.addRow("Biomet time column", self.biomet_time_column_edit)
        biomet_layout.addRow("Aggregation", self.biomet_agg_combo)
        biomet_layout.addRow("Fields", self.biomet_fields_edit)
        biomet_layout.addRow("Directory glob", self.biomet_glob_edit)
        biomet_layout.addRow("Biomet notes", self.biomet_notes_edit)
        self._add_metadata_panel("biomet", "Biomet", biomet_card)

        dynamic_card = CardFrame(muted=True)
        dynamic_card.setProperty("metadataEditorPanel", True)
        self.metadata_editor_cards.append(dynamic_card)
        dynamic_layout = QFormLayout(dynamic_card)
        dynamic_layout.setHorizontalSpacing(TOKENS.spacing_md)
        dynamic_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.dynamic_csv_path_edit = QLineEdit()
        dynamic_path_row = QHBoxLayout()
        dynamic_path_row.addWidget(self.dynamic_csv_path_edit, 1)
        dynamic_import_button = QPushButton("Import CSV")
        dynamic_import_button.setProperty("metadataActionButton", True)
        dynamic_import_button.setMaximumHeight(26)
        dynamic_import_button.clicked.connect(self._import_dynamic_csv)
        dynamic_path_row.addWidget(dynamic_import_button)
        self.dynamic_start_column_edit = QLineEdit()
        self.dynamic_end_column_edit = QLineEdit()
        self.dynamic_timezone_edit = QLineEdit()
        self.dynamic_record_count_label = QLabel("0 record(s)")
        dynamic_layout.addRow("Dynamic metadata CSV", dynamic_path_row)
        dynamic_layout.addRow("Start column", self.dynamic_start_column_edit)
        dynamic_layout.addRow("End column", self.dynamic_end_column_edit)
        dynamic_layout.addRow("Dynamic timezone", self.dynamic_timezone_edit)
        dynamic_layout.addRow("Imported records", self.dynamic_record_count_label)
        self._add_metadata_panel("dynamic", "Dynamic", dynamic_card)

        profile_card = CardFrame()
        profile_card.setProperty("metadataProfileDock", True)
        self.metadata_profile_card = profile_card
        profile_layout = QFormLayout(profile_card)
        profile_layout.setHorizontalSpacing(TOKENS.spacing_md)
        profile_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.metadata_profile_combo = QComboBox()
        self.metadata_profile_combo.setEditable(True)
        profile_buttons = QHBoxLayout()
        self.metadata_profile_buttons: list[QPushButton] = []
        profile_save_button = QPushButton("Save profile")
        profile_save_button.setProperty("metadataActionButton", True)
        profile_save_button.setMaximumHeight(26)
        profile_save_button.clicked.connect(self._save_metadata_profile)
        profile_load_button = QPushButton("Load profile")
        profile_load_button.setProperty("metadataActionButton", True)
        profile_load_button.setMaximumHeight(26)
        profile_load_button.clicked.connect(self._load_metadata_profile)
        profile_refresh_button = QPushButton("Refresh list")
        profile_refresh_button.setProperty("metadataActionButton", True)
        profile_refresh_button.setMaximumHeight(26)
        profile_refresh_button.clicked.connect(self._refresh_metadata_profiles)
        self.metadata_profile_buttons.extend((profile_save_button, profile_load_button, profile_refresh_button))
        profile_buttons.addWidget(profile_save_button)
        profile_buttons.addWidget(profile_load_button)
        profile_buttons.addWidget(profile_refresh_button)
        self.metadata_status_label = QLabel("--")
        self.metadata_status_label.setObjectName("subtitle")
        self.metadata_status_label.setWordWrap(True)
        profile_layout.addRow("Alternative metadata profile", self.metadata_profile_combo)
        profile_layout.addRow("Profile actions", profile_buttons)
        profile_layout.addRow("Completeness", self.metadata_status_label)
        self._add_metadata_panel("profile", "Profile", profile_card)
        layout.addWidget(card)

    def _add_metadata_panel(self, key: str, title: str, panel: CardFrame) -> None:
        index = self.metadata_editor_stack.addWidget(panel)
        self.metadata_panel_order.append(key)
        button = QToolButton()
        button.setText(title)
        button.setCheckable(True)
        button.setProperty("metadataPanelSwitchButton", True)
        button.setMaximumHeight(28)
        button.clicked.connect(lambda _checked=False, panel_key=key: self._set_metadata_panel(panel_key))
        self.metadata_panel_buttons[key] = button
        self.metadata_panel_switch_layout.addWidget(button, index // 4, index % 4)
        if index == 0:
            self._set_metadata_panel(key)

    def _set_metadata_panel(self, key: str) -> None:
        if key not in self.metadata_panel_order:
            return
        self.metadata_editor_stack.setCurrentIndex(self.metadata_panel_order.index(key))
        for panel_key, button in self.metadata_panel_buttons.items():
            button.setChecked(panel_key == key)

    def _metadata_payload(self) -> dict:
        return {
            "station": {
                "latitude": self.station_latitude_spin.value(),
                "longitude": self.station_longitude_spin.value(),
                "displacement_height": self.station_displacement_spin.value(),
                "roughness_length": self.station_roughness_spin.value(),
                "timestamp_refers_to": self.station_timestamp_ref_combo.currentText().strip(),
                "file_duration": self.station_file_duration_spin.value(),
            },
            "instruments": {
                "sonic_model": self.sonic_model_meta_edit.text().strip(),
                "analyzer_model": self.analyzer_model_meta_edit.text().strip(),
                "sonic_manufacturer": self.sonic_mfr_edit.text().strip(),
                "analyzer_manufacturer": self.analyzer_mfr_edit.text().strip(),
                "sonic_firmware": self.sonic_fw_edit.text().strip(),
                "analyzer_firmware": self.analyzer_fw_edit.text().strip(),
                "sonic_instrument_id": self.sonic_id_edit.text().strip(),
                "analyzer_instrument_id": self.analyzer_id_edit.text().strip(),
                "sonic_serial": self.sonic_serial_meta_edit.text().strip(),
                "analyzer_serial": self.analyzer_serial_meta_edit.text().strip(),
                "mount_description": self.layout_note_edit.toPlainText().strip(),
                "geometry_detail": self.geometry_detail_edit.toPlainText().strip(),
            },
            "raw_file_description": {
                "source_name": self.raw_source_name_edit.text().strip(),
                "source_type": self.raw_source_type_combo.currentText().strip(),
                "file_pattern": self.file_pattern_edit.text().strip(),
                "timestamp_column": self.raw_timestamp_column_edit.text().strip(),
                "timezone": self.raw_timezone_edit.text().strip(),
                "notes": self.raw_notes_edit.toPlainText().strip(),
                "column_mappings_json": self.raw_column_mappings_edit.toPlainText().strip(),
            },
            "raw_file_settings": {
                "sample_hz": self.raw_sample_hz_spin.value(),
                "delimiter": self.raw_delimiter_edit.text(),
                "decimal": self.raw_decimal_edit.text(),
                "header_rows": self.raw_header_rows_spin.value(),
                "encoding": self.raw_encoding_edit.text().strip(),
                "missing_tokens": self.raw_missing_tokens_edit.text().strip(),
            },
            "biomet_source": {
                "source_mode": self.biomet_mode_combo.currentText().strip(),
                "source_path": self.biomet_source_path_edit.text().strip(),
                "time_column": self.biomet_time_column_edit.text().strip(),
                "aggregation_method": self.biomet_agg_combo.currentText().strip(),
                "fields": self.biomet_fields_edit.text().strip(),
                "directory_glob": self.biomet_glob_edit.text().strip(),
                "notes": self.biomet_notes_edit.toPlainText().strip(),
            },
            "dynamic_metadata": {
                "source_path": self.dynamic_csv_path_edit.text().strip(),
                "start_column": self.dynamic_start_column_edit.text().strip(),
                "end_column": self.dynamic_end_column_edit.text().strip(),
                "timezone": self.dynamic_timezone_edit.text().strip(),
                "records": getattr(self, "_dynamic_metadata_records", []),
            },
            "alternative_metadata": {
                "active_profile": self.metadata_profile_combo.currentText().strip(),
                "available_profiles": [self.metadata_profile_combo.itemText(index) for index in range(self.metadata_profile_combo.count())],
            },
        }

    def _refresh_metadata_profiles(self) -> None:
        current = self.metadata_profile_combo.currentText().strip()
        names = self.controller.metadata_profile_names()
        self.metadata_profile_combo.blockSignals(True)
        self.metadata_profile_combo.clear()
        self.metadata_profile_combo.addItems(names)
        if current:
            self.metadata_profile_combo.setEditText(current)
        self.metadata_profile_combo.blockSignals(False)

    def _refresh_metadata_status(self) -> None:
        try:
            mappings = json.loads(self.raw_column_mappings_edit.toPlainText().strip() or '[]')
            mapping_count = len(mappings) if isinstance(mappings, list) else 0
        except json.JSONDecodeError:
            mapping_count = 0
        dynamic_count = len(getattr(self, '_dynamic_metadata_records', []))
        active_profile = self.metadata_profile_combo.currentText().strip() or "--"
        self.metadata_status_label.setText(
            f"column mappings={mapping_count}, dynamic records={dynamic_count}, profile={active_profile}"
        )
        if hasattr(self, "metadata_summary_values"):
            station_ready = sum(
                1
                for value in (
                    self.station_latitude_spin.value(),
                    self.station_longitude_spin.value(),
                    self.station_file_duration_spin.value(),
                )
                if value
            )
            instrument_ready = sum(
                1
                for text in (
                    self.sonic_model_meta_edit.text().strip(),
                    self.analyzer_model_meta_edit.text().strip(),
                    self.sonic_serial_meta_edit.text().strip(),
                    self.analyzer_serial_meta_edit.text().strip(),
                )
                if text
            )
            raw_ready = sum(
                1
                for ok in (
                    bool(self.raw_source_name_edit.text().strip()),
                    bool(self.raw_timestamp_column_edit.text().strip()),
                    bool(self.raw_sample_hz_spin.value()),
                    mapping_count > 0,
                )
                if ok
            )
            profile_display = active_profile if len(active_profile) <= 14 else f"{active_profile[:13]}..."
            self.metadata_summary_values["station"].setText(f"{station_ready}/3")
            self.metadata_summary_values["instrument"].setText(f"{instrument_ready}/4")
            self.metadata_summary_values["raw"].setText(f"{raw_ready}/4")
            self.metadata_summary_values["dynamic"].setText(f"{dynamic_count} rec")
            self.metadata_summary_values["profile"].setText(profile_display)
            self.metadata_summary_values["profile"].setToolTip(active_profile)

    def _choose_biomet_path(self, *, directory: bool) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select biomet directory") if directory else QFileDialog.getOpenFileName(self, "Select biomet file", filter="CSV Files (*.csv);;All Files (*.*)")[0]
        if not path:
            return
        self.biomet_source_path_edit.setText(path)
        self.biomet_mode_combo.setCurrentText("external_directory" if directory else "external_file")

    def _import_dynamic_csv(self) -> None:
        path = QFileDialog.getOpenFileName(self, "Import dynamic metadata CSV", filter="CSV Files (*.csv);;All Files (*.*)")[0]
        if not path:
            return
        if not self._save(show_message=False):
            return
        payload = self.controller.import_dynamic_metadata_csv(
            path,
            start_column=self.dynamic_start_column_edit.text().strip() or "start_time",
            end_column=self.dynamic_end_column_edit.text().strip() or "end_time",
            timezone=self.dynamic_timezone_edit.text().strip() or "Asia/Shanghai",
        )
        self.dynamic_csv_path_edit.setText(path)
        self._dynamic_metadata_records = list(payload.get("records", []))
        self.dynamic_record_count_label.setText(f"{len(self._dynamic_metadata_records)} record(s)")
        self._refresh_metadata_status()

    def _save_metadata_profile(self) -> None:
        if not self._save(show_message=False):
            return
        name = self.controller.save_metadata_profile(self.metadata_profile_combo.currentText().strip())
        self._refresh_metadata_profiles()
        self.metadata_profile_combo.setEditText(name)
        self._refresh_metadata_status()
        QMessageBox.information(self, "Metadata profile", f"Saved profile: {name}")

    def _load_metadata_profile(self) -> None:
        name = self.metadata_profile_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Metadata profile", "Please choose a metadata profile name.")
            return
        if not self.controller.load_metadata_profile(name):
            QMessageBox.warning(self, "Metadata profile", f"Profile not found: {name}")
            return
        self._refresh_metadata_profiles()
        self._refresh_metadata_status()
        QMessageBox.information(self, "Metadata profile", f"Loaded profile: {name}")

    def _bind_preview_signals(self) -> None:
        for widget in (
            self.project_name_edit,
            self.project_code_edit,
            self.principal_edit,
            self.archive_root_edit,
            self.template_name_edit,
        ):
            widget.textChanged.connect(self._refresh_top_bar)
        self.project_status_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.project_notes_edit.textChanged.connect(self._refresh_top_bar)

        for widget in (
            self.station_name_edit,
            self.station_code_edit,
            self.location_edit,
            self.land_cover_edit,
            self.site_timezone_edit,
        ):
            widget.textChanged.connect(self._refresh_top_bar)

        for widget in (
            self.mast_height_spin,
            self.analyzer_height_spin,
            self.sonic_height_spin,
            self.height_delta_spin,
            self.orientation_spin,
        ):
            widget.valueChanged.connect(self._refresh_layout_diagram)
            widget.valueChanged.connect(self._refresh_top_bar)
        for widget in (self.analyzer_mount_edit, self.sonic_mount_edit, self.reference_sensor_edit):
            widget.textChanged.connect(self._refresh_layout_diagram)
            widget.textChanged.connect(self._refresh_top_bar)

        for widget in (self.tube_length_spin, self.tube_diameter_spin, self.flow_spin):
            widget.valueChanged.connect(self._refresh_chain_preview)
            widget.valueChanged.connect(self._refresh_top_bar)
        for widget in (self.tube_material_edit, self.pump_model_edit, self.filter_model_edit):
            widget.textChanged.connect(self._refresh_chain_preview)
            widget.textChanged.connect(self._refresh_top_bar)
        self.heat_traced_combo.currentIndexChanged.connect(self._refresh_chain_preview)
        self.heat_traced_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.insulated_combo.currentIndexChanged.connect(self._refresh_chain_preview)
        self.insulated_combo.currentIndexChanged.connect(self._refresh_top_bar)

        self.sample_hz_spin.valueChanged.connect(self._refresh_timing_preview)
        self.sample_hz_spin.valueChanged.connect(self._refresh_top_bar)
        self.block_minutes_spin.valueChanged.connect(self._refresh_timing_preview)
        self.block_minutes_spin.valueChanged.connect(self._refresh_top_bar)
        self.clock_source_combo.currentIndexChanged.connect(self._refresh_timing_preview)
        self.clock_source_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.start_rule_combo.currentIndexChanged.connect(self._refresh_timing_preview)
        self.start_rule_combo.currentIndexChanged.connect(self._refresh_top_bar)

        self.include_diagnostics_combo.currentIndexChanged.connect(self._refresh_output_preview)
        self.include_diagnostics_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.include_qc_combo.currentIndexChanged.connect(self._refresh_output_preview)
        self.include_qc_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.output_template_name_edit.textChanged.connect(self._refresh_top_bar)
        self.file_pattern_edit.textChanged.connect(self._refresh_output_preview)
        self.file_pattern_edit.textChanged.connect(self._refresh_top_bar)
        self.report_header_edit.textChanged.connect(self._refresh_output_preview)
        self.report_header_edit.textChanged.connect(self._refresh_top_bar)

        self.precheck_mode_combo.currentIndexChanged.connect(self._refresh_runtime_preview)
        self.precheck_mode_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.auto_archive_combo.currentIndexChanged.connect(self._refresh_runtime_preview)
        self.auto_archive_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.replay_ready_combo.currentIndexChanged.connect(self._refresh_runtime_preview)
        self.replay_ready_combo.currentIndexChanged.connect(self._refresh_top_bar)
        self.runtime_template_name_edit.textChanged.connect(self._refresh_top_bar)

        if hasattr(self, "metadata_status_label"):
            for widget in (
                self.sonic_model_meta_edit, self.analyzer_model_meta_edit, self.raw_source_name_edit, self.raw_timestamp_column_edit,
                self.raw_timezone_edit, self.raw_delimiter_edit, self.raw_decimal_edit, self.raw_encoding_edit,
                self.raw_missing_tokens_edit, self.biomet_source_path_edit, self.biomet_time_column_edit, self.biomet_fields_edit,
                self.biomet_glob_edit, self.dynamic_csv_path_edit, self.dynamic_start_column_edit, self.dynamic_end_column_edit,
                self.dynamic_timezone_edit, self.geometry_detail_edit, self.raw_column_mappings_edit, self.raw_notes_edit,
                self.biomet_notes_edit, self.sonic_mfr_edit, self.analyzer_mfr_edit, self.sonic_fw_edit, self.analyzer_fw_edit,
                self.sonic_id_edit, self.analyzer_id_edit, self.sonic_serial_meta_edit, self.analyzer_serial_meta_edit,
            ):
                signal = getattr(widget, "textChanged", None)
                if signal is not None:
                    signal.connect(self._refresh_metadata_status)
            for widget in (self.station_latitude_spin, self.station_longitude_spin, self.station_displacement_spin, self.station_roughness_spin, self.station_file_duration_spin, self.raw_sample_hz_spin):
                widget.valueChanged.connect(self._refresh_metadata_status)
            for combo in (self.station_timestamp_ref_combo, self.raw_source_type_combo, self.biomet_mode_combo, self.biomet_agg_combo, self.metadata_profile_combo):
                combo.currentIndexChanged.connect(self._refresh_metadata_status)

    def _on_section_changed(self) -> None:
        item = self.section_tree.currentItem()
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        self.content_stack.setCurrentIndex(self.section_indexes[key])
        self.controller.set_project_nav_section(key)
        self._refresh_top_bar()

    def _sync_section_from_controller(self) -> None:
        key = self.controller.project_nav_section
        item = self.section_items.get(key)
        if item is None:
            return
        if self.section_tree.currentItem() is not item:
            self.section_tree.blockSignals(True)
            self.section_tree.setCurrentItem(item)
            self.section_tree.blockSignals(False)
        self.content_stack.setCurrentIndex(self.section_indexes[key])
        self._refresh_top_bar()

    def _collect_payload(self) -> dict:
        return {
            "overview": {
                "project_name": self.project_name_edit.text().strip(),
                "project_code": self.project_code_edit.text().strip(),
                "principal": self.principal_edit.text().strip(),
                "archive_root": self.archive_root_edit.text().strip(),
                "status": self.project_status_combo.currentText().strip(),
                "template_name": self.template_name_edit.text().strip(),
                "notes": self.project_notes_edit.toPlainText().strip(),
            },
            "site_info": {
                "station_name": self.station_name_edit.text().strip(),
                "station_code": self.station_code_edit.text().strip(),
                "location": self.location_edit.text().strip(),
                "land_cover": self.land_cover_edit.text().strip(),
                "canopy_height_m": self.canopy_height_spin.value(),
                "altitude_m": self.altitude_spin.value(),
                "timezone": self.site_timezone_edit.text().strip(),
            },
            "instrument_layout": {
                "mast_height_m": self.mast_height_spin.value(),
                "analyzer_height_m": self.analyzer_height_spin.value(),
                "sonic_height_m": self.sonic_height_spin.value(),
                "height_delta_m": self.height_delta_spin.value(),
                "orientation_deg": self.orientation_spin.value(),
                "analyzer_mount": self.analyzer_mount_edit.text().strip(),
                "sonic_mount": self.sonic_mount_edit.text().strip(),
                "reference_sensor": self.reference_sensor_edit.text().strip(),
                "layout_note": self.layout_note_edit.toPlainText().strip(),
            },
            "sampling_chain": {
                "tube_length_m": self.tube_length_spin.value(),
                "tube_diameter_mm": self.tube_diameter_spin.value(),
                "tube_material": self.tube_material_edit.text().strip(),
                "heat_traced": self._combo_bool(self.heat_traced_combo),
                "insulated": self._combo_bool(self.insulated_combo),
                "pump_model": self.pump_model_edit.text().strip(),
                "flow_lpm": self.flow_spin.value(),
                "filter_model": self.filter_model_edit.text().strip(),
                "chain_note": self.chain_note_edit.toPlainText().strip(),
            },
            "timing": {
                "timezone": self.timing_timezone_edit.text().strip(),
                "sample_hz": self.sample_hz_spin.value(),
                "block_minutes": self.block_minutes_spin.value(),
                "clock_source": self.clock_source_combo.currentText().strip(),
                "start_rule": self.start_rule_combo.currentText().strip(),
                "sample_mode": self.sample_mode_combo.currentText().strip(),
            },
            "output_template": {
                "template_name": self.output_template_name_edit.text().strip(),
                "include_diagnostics": self._combo_bool(self.include_diagnostics_combo),
                "include_qc": self._combo_bool(self.include_qc_combo),
                "file_pattern": self.file_pattern_edit.text().strip(),
                "report_header": self.report_header_edit.text().strip(),
            },
            "runtime_template": {
                "template_name": self.runtime_template_name_edit.text().strip(),
                "precheck_mode": self.precheck_mode_combo.currentText().strip(),
                "auto_archive": self._combo_bool(self.auto_archive_combo),
                "replay_ready": self._combo_bool(self.replay_ready_combo),
                "operator_note": self.operator_note_edit.toPlainText().strip(),
            },
            "metadata": self._metadata_payload() if hasattr(self, "metadata_status_label") else {},
        }

    def _save(self, *, show_message: bool = True) -> bool:
        try:
            self.controller.save_project_workspace(self._collect_payload())
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        if show_message:
            QMessageBox.information(self, "保存完成", "项目与站点配置已保存，可继续进行完整性检查或进入 EC 处理。")
        return True

    def _new_workspace(self) -> None:
        if (
            QMessageBox.question(
                self,
                "新建项目",
                "将切换到新的空白项目工作区。当前未保存的修改可能被覆盖，是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        self.controller.new_project_workspace()

    def _duplicate_workspace(self) -> None:
        self.controller.duplicate_project_workspace()
        QMessageBox.information(self, "已复制", "已基于当前配置生成副本，请优先修改项目编号与站点标识。")

    def _import_template(self) -> None:
        self.controller.import_project_template()
        QMessageBox.information(self, "模板已导入", "模板参数已加载，请结合现场安装情况逐项复核。")

    def _check_completeness(self) -> None:
        if not self._save(show_message=False):
            return
        report = self.controller.project_completeness_report()
        missing = "、".join(report["missing_items"]) if report["missing_items"] else "无"
        QMessageBox.information(
            self,
            "完整性检查",
            f"完整性评分：{report['score']} 分\n\n缺失项：{missing}\n\n当前提示：{report['parameter_note']}",
        )
        self._refresh_top_bar()

    def _refresh_top_bar(self, *_args) -> None:
        workspace = self._collect_payload()
        overview = workspace["overview"]
        site_info = workspace["site_info"]
        self.current_project_value.setText(overview["project_name"] or "未命名项目")
        self.current_project_value.setObjectName("metricValue")
        self.current_project_value.style().unpolish(self.current_project_value)
        self.current_project_value.style().polish(self.current_project_value)
        self.current_site_value.setText(site_info["station_name"] or "未设置站点")
        self.current_site_value.setObjectName("metricValue")
        self.current_site_value.style().unpolish(self.current_site_value)
        self.current_site_value.style().polish(self.current_site_value)
        score = self._local_completeness_score(workspace)
        self.integrity_value.setText(f"{score} 分")
        self.integrity_value.setObjectName("metricValue")
        self.integrity_value.style().unpolish(self.integrity_value)
        self.integrity_value.style().polish(self.integrity_value)

        status_text = overview["status"] or "草拟"
        tone = "success" if status_text in {"运行中", "已归档"} else ("accent" if score >= 85 else "warning")
        self.current_status_chip.setText(status_text)
        self.current_status_chip.setProperty("chipTone", tone)
        self.current_status_chip.style().unpolish(self.current_status_chip)
        self.current_status_chip.style().polish(self.current_status_chip)

        self.overview_metric_project_code.setText(overview["project_code"] or "待填写")
        self.overview_metric_principal.setText(overview["principal"] or "待填写")
        self.overview_metric_archive_root.setText(overview["archive_root"] or "待填写")
        self._refresh_site_ops_rail(workspace, score=score)

    def _refresh_site_ops_rail(self, workspace: dict, *, score: int | None = None) -> None:
        if not hasattr(self, "site_ops_values"):
            return
        if score is None:
            score = self._local_completeness_score(workspace)
        section_key = self.controller.project_nav_section
        section_title_text = next((title for key, title, _subtitle in PROJECT_SECTIONS if key == section_key), "项目配置")
        overview = workspace["overview"]
        site_info = workspace["site_info"]
        layout_cfg = workspace["instrument_layout"]
        chain = workspace["sampling_chain"]
        timing = workspace["timing"]
        output = workspace["output_template"]
        runtime = workspace["runtime_template"]
        metadata = workspace.get("metadata", {}) or {}

        self._set_site_ops_row(
            "readiness",
            f"{score} 分",
            f"当前：{section_title_text} · {overview.get('status') or '草拟'}",
        )

        canopy_height = float(site_info.get("canopy_height_m", 0.0) or 0.0)
        mast_height = float(layout_cfg.get("mast_height_m", 0.0) or 0.0)
        sonic_height = float(layout_cfg.get("sonic_height_m", 0.0) or 0.0)
        analyzer_height = float(layout_cfg.get("analyzer_height_m", 0.0) or 0.0)
        height_delta = float(layout_cfg.get("height_delta_m", 0.0) or 0.0)
        orientation = int(layout_cfg.get("orientation_deg", 0) or 0)
        self._set_site_ops_row(
            "geometry",
            f"{canopy_height:.1f} m 冠层",
            f"塔 {mast_height:.1f} m · 声风 {sonic_height:.1f} m · Δ{height_delta:.2f} m · {orientation}°",
        )

        tube_length = float(chain.get("tube_length_m", 0.0) or 0.0)
        tube_diameter = float(chain.get("tube_diameter_mm", 0.0) or 0.0)
        flow_lpm = float(chain.get("flow_lpm", 0.0) or 0.0)
        chain_flags = []
        if chain.get("heat_traced"):
            chain_flags.append("伴热")
        if chain.get("insulated"):
            chain_flags.append("保温")
        chain_flag_text = " / ".join(chain_flags) if chain_flags else "未设温控"
        self._set_site_ops_row(
            "chain",
            f"{flow_lpm:.1f} L/min",
            f"{tube_length:.1f} m / {tube_diameter:.1f} mm · {chain_flag_text}",
        )

        sample_hz = float(timing.get("sample_hz", 0.0) or 0.0)
        block_minutes = float(timing.get("block_minutes", 0.0) or 0.0)
        samples_per_window = int(sample_hz * block_minutes * 60)
        self._set_site_ops_row(
            "timing",
            f"{sample_hz:g} Hz",
            f"{block_minutes:g} min · {samples_per_window:,} 点/窗口",
        )

        delivery_parts = []
        delivery_parts.append("诊断" if output.get("include_diagnostics") else "无诊断")
        delivery_parts.append("QC" if output.get("include_qc") else "无 QC")
        delivery_value = " + ".join(delivery_parts)
        runtime_mode = runtime.get("precheck_mode") or "预检待定"
        self._set_site_ops_row(
            "delivery",
            delivery_value,
            f"{output.get('template_name') or '模板待填'} · {runtime_mode}",
        )

        station_meta = metadata.get("station", {}) or {}
        instruments = metadata.get("instruments", {}) or {}
        raw_description = metadata.get("raw_file_description", {}) or {}
        raw_settings = metadata.get("raw_file_settings", {}) or {}
        metadata_checks = [
            bool(station_meta.get("latitude")) and bool(station_meta.get("longitude")),
            bool(instruments.get("sonic_model")) and bool(instruments.get("analyzer_model")),
            bool(raw_description.get("source_name")),
            bool(raw_description.get("timestamp_column")),
            bool(raw_settings.get("sample_hz")),
        ]
        ready_metadata = sum(1 for item in metadata_checks if item)
        alternative_metadata = metadata.get("alternative_metadata", {}) or {}
        active_profile = alternative_metadata.get("active_profile") if isinstance(alternative_metadata, dict) else ""
        self._set_site_ops_row(
            "metadata",
            f"{ready_metadata}/{len(metadata_checks)} ready",
            f"profile={active_profile or 'active'} · raw={raw_description.get('source_type') or 'hf_frame'}",
        )

        if score < 70:
            chip_text, tone = "待补齐", "warning"
            next_value = "补齐项目身份"
            next_note = "优先补项目、站点、归档根目录和基础高度，后续处理才有可靠上下文。"
            next_target = "overview"
        elif not tube_length or not flow_lpm:
            chip_text, tone = "链路待核", "warning"
            next_value = "复核采样链路"
            next_note = "管路长度、流量和温控会影响滞后与谱修正，建议在运行前闭合。"
            next_target = "sampling_chain"
        elif not output.get("template_name"):
            chip_text, tone = "交付待定", "accent"
            next_value = "确认导出模板"
            next_note = "补齐模板名和文件命名规则，便于报告中心和批处理复用。"
            next_target = "output_template"
        else:
            chip_text, tone = "可进入处理", "success"
            next_value = "保存并运行"
            next_note = "站点上下文已具备进入处理页的基础条件，建议先保存再执行预检。"
            next_target = "save"
        self._set_site_ops_chip(chip_text, tone)
        self.site_ops_next_value.setText(next_value)
        self.site_ops_next_note.setText(next_note)
        self._set_site_ops_next_action(next_value, next_target, tone, next_note)

    def _set_site_ops_row(self, key: str, value: str, note: str) -> None:
        value_label, note_label = self.site_ops_values[key]
        value_label.setText(value)
        note_label.setText(note)
        tooltip = f"{value}\n{note}"
        value_label.setToolTip(tooltip)
        note_label.setToolTip(tooltip)

    def _set_site_ops_next_action(self, text: str, target: str, tone: str, note: str) -> None:
        if not hasattr(self, "site_ops_next_action_button"):
            return
        button_text = "保存快照" if target == "save" else text
        self.site_ops_next_action_button.setText(button_text)
        self.site_ops_next_action_button.setToolTip(f"{text}: {note}")
        self.site_ops_next_action_button.setProperty("targetSection", target)
        self.site_ops_next_action_button.setProperty("actionTone", tone)
        self.site_ops_next_action_button.style().unpolish(self.site_ops_next_action_button)
        self.site_ops_next_action_button.style().polish(self.site_ops_next_action_button)

    def _set_site_ops_chip(self, text: str, tone: str) -> None:
        self.site_ops_chip.setText(text)
        self.site_ops_chip.setProperty("chipTone", tone)
        self.site_ops_chip.style().unpolish(self.site_ops_chip)
        self.site_ops_chip.style().polish(self.site_ops_chip)

    def _activate_site_ops_target(self, section_key: str) -> None:
        item = self.section_items.get(section_key)
        if item is None:
            return
        self.section_tree.setCurrentItem(item)
        self.controller.set_project_nav_section(section_key)
        self.content_stack.setCurrentIndex(self.section_indexes[section_key])
        self.site_ops_last_action_note.setText(f"已定位到：{item.text(0)}。")
        self._refresh_top_bar()

    def _activate_site_ops_next_action(self) -> None:
        target = str(self.site_ops_next_action_button.property("targetSection") or "overview")
        if target == "save":
            self._save_site_ops_snapshot()
            return
        self._activate_site_ops_target(target)

    def _save_site_ops_snapshot(self) -> None:
        if not self._save(show_message=False):
            return
        self.site_ops_last_action_note.setText("已保存当前项目与站点配置快照。")
        self._refresh_top_bar()

    def _run_site_ops_completeness_check(self) -> None:
        if not self._save(show_message=False):
            return
        report = self.controller.project_completeness_report()
        missing_count = len(report.get("missing_items", []))
        self.site_ops_last_action_note.setText(f"完整性检查完成：{report.get('score', 0)} 分 · 缺失 {missing_count} 项。")
        self._refresh_top_bar()

    def _refresh_layout_diagram(self, *_args) -> None:
        self.layout_diagram_labels["sonic"].setText(
            f"安装高度 {self.sonic_height_spin.value():.2f} m\n位置 {self.sonic_mount_edit.text().strip() or '待填写'}"
        )
        self.layout_diagram_labels["analyzer"].setText(
            f"安装高度 {self.analyzer_height_spin.value():.2f} m\n位置 {self.analyzer_mount_edit.text().strip() or '待填写'}"
        )
        self.layout_diagram_labels["reference"].setText(
            f"参考元件 {self.reference_sensor_edit.text().strip() or '待填写'}\n高度差 {self.height_delta_spin.value():.2f} m"
        )
        self.layout_diagram_labels["orientation"].setText(
            f"主塔高度 {self.mast_height_spin.value():.2f} m，朝向 {self.orientation_spin.value()}°。"
        )

    def _refresh_chain_preview(self, *_args) -> None:
        self.chain_preview_labels["inlet"].setText(
            f"管长 {self.tube_length_spin.value():.1f} m\n管径 {self.tube_diameter_spin.value():.1f} mm"
        )
        self.chain_preview_labels["filter"].setText(
            self.filter_model_edit.text().strip() or "请填写过滤器型号"
        )
        self.chain_preview_labels["pump"].setText(
            f"{self.pump_model_edit.text().strip() or '请填写泵型号'}\n流量 {self.flow_spin.value():.1f} L/min"
        )
        flags = []
        if self._combo_bool(self.heat_traced_combo):
            flags.append("伴热")
        if self._combo_bool(self.insulated_combo):
            flags.append("保温")
        flag_text = " / ".join(flags) if flags else "未设置保温措施"
        self.chain_preview_labels["analyzer"].setText(
            f"管材 {self.tube_material_edit.text().strip() or '待填写'}\n{flag_text}"
        )

    def _refresh_timing_preview(self, *_args) -> None:
        samples = self.sample_hz_spin.value() * self.block_minutes_spin.value() * 60
        self.samples_per_window_label.setText(f"{samples:,} 点 / 窗口")
        self.timing_preview_note.setText(
            f"时钟来源：{self.clock_source_combo.currentText()}，起始规则：{self.start_rule_combo.currentText()}。"
        )

    def _refresh_output_preview(self, *_args) -> None:
        self.output_preview_name.setText(
            self.file_pattern_edit.text().strip() or "{site}_{date}_{window}.csv"
        )
        parts = []
        parts.append("含诊断字段" if self._combo_bool(self.include_diagnostics_combo) else "不含诊断字段")
        parts.append("含 QC 字段" if self._combo_bool(self.include_qc_combo) else "不含 QC 字段")
        self.output_preview_note.setText(
            f"报告抬头：{self.report_header_edit.text().strip() or '待填写'}，{', '.join(parts)}。"
        )

    def _refresh_runtime_preview(self, *_args) -> None:
        self.runtime_preview_status.setText(self.precheck_mode_combo.currentText())
        archive_text = "自动归档" if self._combo_bool(self.auto_archive_combo) else "手动归档"
        replay_text = "保留回放材料" if self._combo_bool(self.replay_ready_combo) else "最小材料保留"
        self.runtime_preview_note.setText(f"{archive_text}，{replay_text}。")

    def _metric_box(self, title: str, widget: QWidget, *, compact: bool = False) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        if compact:
            card.setProperty("projectSiteMetric", True)
            card.setMaximumHeight(56)
        layout = QVBoxLayout(card)
        vertical_margin = TOKENS.spacing_xs if compact else TOKENS.spacing_sm
        layout.setContentsMargins(TOKENS.spacing_md, vertical_margin, TOKENS.spacing_md, vertical_margin)
        layout.setSpacing(1 if compact else TOKENS.spacing_xs)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        layout.addWidget(label)
        if isinstance(widget, QLabel):
            widget.setMinimumWidth(0)
            widget.setWordWrap(True)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(widget)
        return card

    def _double_spin(self, low: float, high: float, decimals: int, *, suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _bool_combo(self, true_text: str, false_text: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(true_text, True)
        combo.addItem(false_text, False)
        return combo

    def _combo_bool(self, combo: QComboBox) -> bool:
        data = combo.currentData()
        return bool(True if data is None else data)

    def _set_bool_combo(self, combo: QComboBox, value: bool) -> None:
        index = 0 if value else 1
        combo.setCurrentIndex(index)

    def _local_completeness_score(self, workspace: dict) -> int:
        checks = [
            bool(workspace["overview"].get("project_name")),
            bool(workspace["overview"].get("project_code")),
            bool(workspace["site_info"].get("station_name")),
            bool(workspace["site_info"].get("location")),
            bool(workspace["instrument_layout"].get("analyzer_height_m")),
            bool(workspace["instrument_layout"].get("sonic_height_m")),
            bool(workspace["sampling_chain"].get("tube_length_m")),
            bool(workspace["sampling_chain"].get("flow_lpm")),
            bool(workspace["timing"].get("sample_hz")),
            bool(workspace["output_template"].get("template_name")),
            bool(workspace["runtime_template"].get("template_name")),
        ]
        return int(sum(1 for ok in checks if ok) / max(1, len(checks)) * 100)

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        text = value.strip()
        if not text:
            return
        index = combo.findText(text)
        if index < 0:
            combo.addItem(text)
            index = combo.findText(text)
        combo.setCurrentIndex(index)
