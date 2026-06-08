from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, TOKENS, chip, section_title


class DeviceDetailPage(QWidget):
    back_requested = Signal()
    open_realtime_requested = Signal()

    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._coeff_result_text = "最近一次读取结果会显示在这里。操作员视图默认只显示结论，工程师视图可直接核对系数值。"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        self.header_card = CardFrame()
        header_layout = QHBoxLayout(self.header_card)
        header_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        header_layout.setSpacing(TOKENS.spacing_md)

        title_box = QVBoxLayout()
        self.page_title = QLabel("单设备详情")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("用于完成单台设备的配置、采集和诊断。")
        self.page_subtitle.setObjectName("subtitle")
        self.page_subtitle.setWordWrap(True)
        title_box.addWidget(self.page_title)
        title_box.addWidget(self.page_subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        back_button = QPushButton("返回设备中心")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button)

        mode_group = QButtonGroup(self.header_card)
        self.operator_btn = QToolButton()
        self.operator_btn.setText("操作员视图")
        self.operator_btn.setCheckable(True)
        self.operator_btn.clicked.connect(lambda: self.controller.set_view_mode("operator"))
        self.engineer_btn = QToolButton()
        self.engineer_btn.setText("工程师视图")
        self.engineer_btn.setCheckable(True)
        self.engineer_btn.clicked.connect(lambda: self.controller.set_view_mode("engineer"))
        mode_group.addButton(self.operator_btn)
        mode_group.addButton(self.engineer_btn)
        header_layout.addWidget(self.operator_btn)
        header_layout.addWidget(self.engineer_btn)
        layout.addWidget(self.header_card)

        self.summary_card = CardFrame()
        self.summary_layout = QHBoxLayout(self.summary_card)
        self.summary_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        self.summary_layout.setSpacing(TOKENS.spacing_md)
        self.summary_values: dict[str, QLabel] = {}
        for key, title in (
            ("online", "在线状态"),
            ("mode", "模式"),
            ("device_id", "设备 ID"),
            ("comm", "输出方式"),
            ("frequency", "输出频率"),
            ("last_frame", "最近有效帧"),
            ("data_state", "数据状态"),
        ):
            card = CardFrame(muted=True)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setWordWrap(True)
            inner.addWidget(label)
            inner.addWidget(value)
            self.summary_values[key] = value
            self.summary_layout.addWidget(card, 1)
        layout.addWidget(self.summary_card)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.overview_tab = QWidget()
        self.config_tab = QWidget()
        self.coeff_tab = QWidget()
        self.diagnostic_tab = QWidget()
        self.tabs.addTab(self.overview_tab, "概览")
        self.tabs.addTab(self.config_tab, "配置")
        self.tabs.addTab(self.coeff_tab, "系数")
        self.tabs.addTab(self.diagnostic_tab, "诊断")

        self._build_overview_tab()
        self._build_config_tab()
        self._build_coeff_tab()
        self._build_diagnostic_tab()

        self.controller.devices_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self.refresh)
        self.controller.transactions_changed.connect(self.refresh)
        self.controller.events_changed.connect(self.refresh)
        self.controller.view_mode_changed.connect(lambda _mode: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        entry = self.controller.selected_device()
        self.operator_btn.setChecked(self.controller.view_mode == "operator")
        self.engineer_btn.setChecked(self.controller.view_mode == "engineer")
        if entry is None:
            self.page_title.setText("单设备详情")
            self.page_subtitle.setText("请先在设备中心选择一台设备。")
            return

        snapshot = self.controller.device_detail_snapshot(entry.config.uid)
        latest_numeric = snapshot["latest_numeric"]
        latest_frame = snapshot["latest_frame"]
        analyzer_profile = snapshot.get("gas_analyzer_profile", {})

        self.page_title.setText(f"{entry.config.label} · 单设备详情")
        self.page_subtitle.setText(
            f"{analyzer_profile.get('label', 'Gas analyzer')} · 操作员可在这里完成常用配置和采集；切换到工程师视图后，可以继续查看原始帧、解析结果、事务历史和错误归因。"
        )

        self.summary_values["online"].setText("在线" if entry.runtime.connected else "离线")
        self.summary_values["mode"].setText(f"MODE{entry.runtime.mode}")
        self.summary_values["device_id"].setText(entry.config.device_id)
        self.summary_values["comm"].setText("主动输出" if entry.runtime.active_send else "按需读取")
        self.summary_values["frequency"].setText(f"{entry.runtime.ftd_hz} Hz")
        self.summary_values["last_frame"].setText(
            entry.runtime.last_frame_time.strftime("%H:%M:%S") if entry.runtime.last_frame_time else "暂无"
        )
        self.summary_values["data_state"].setText(entry.runtime.last_message)

        self.overview_status_chip.setText("在线" if entry.runtime.connected else "离线")
        self.overview_status_chip.setProperty("chipTone", "success" if entry.runtime.connected else "warning")
        self.overview_status_chip.style().unpolish(self.overview_status_chip)
        self.overview_status_chip.style().polish(self.overview_status_chip)

        if latest_numeric:
            self.overview_metrics["co2"].setText(f"{latest_numeric.co2_ppm:.2f} ppm")
            self.overview_metrics["h2o"].setText(f"{latest_numeric.h2o_mmol:.2f} mmol")
            self.overview_metrics["pressure"].setText(f"{latest_numeric.pressure_kpa:.2f} kPa")
        else:
            self.overview_metrics["co2"].setText("--")
            self.overview_metrics["h2o"].setText("--")
            self.overview_metrics["pressure"].setText("--")

        self.suggestion_list.clear()
        for text in snapshot["suggestions"]:
            self.suggestion_list.addItem(text)

        self.config_device_title.setText(f"当前配置对象：{entry.config.label}")
        self.ftd_spin.setValue(entry.runtime.ftd_hz)
        self.avg_co2_spin.setValue(entry.runtime.average_co2)
        self.avg_h2o_spin.setValue(entry.runtime.average_h2o)
        self.filter_spin.setValue(entry.runtime.filter_window)
        self.device_id_input.setText(entry.config.device_id)
        self._populate_primary_analyzer_config(dict(snapshot.get("primary_analyzer_config", {}) or {}))
        self._populate_trace_gas_config(dict(snapshot.get("trace_gas_config", {}) or {}))

        self.coeff_warning_label.setVisible(self.controller.view_mode == "engineer")
        self.coeff_result.setPlainText(self._coeff_result_text)

        self.raw_frame_list.clear()
        for frame in self.controller.recent_raw_frames(device_uid=entry.config.uid, limit=20):
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(f"[{frame.received_at:%H:%M:%S}] {frame.quality.value} · {frame.summary()}")
            item.setData(Qt.UserRole, frame)
            self.raw_frame_list.addItem(item)
        if latest_frame:
            self.raw_frame_text.setPlainText(latest_frame.raw_text)
            self.parsed_text.setPlainText(json.dumps(latest_frame.parsed, ensure_ascii=False, indent=2) if latest_frame.parsed else "没有可展示的解析结果。")
        else:
            self.raw_frame_text.setPlainText("尚未收到原始帧。")
            self.parsed_text.setPlainText("尚未收到可解析的数据。")

        self.transaction_table.setRowCount(len(snapshot["transactions"]))
        for row_index, record in enumerate(snapshot["transactions"]):
            values = [
                record.created_at.strftime("%H:%M:%S"),
                record.label,
                record.status.value,
                record.response_summary or "",
            ]
            for col_index, value in enumerate(values):
                self.transaction_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))

        self.attribution_list.clear()
        for note in snapshot["attribution"]:
            self.attribution_list.addItem(note)

        engineer = self.controller.view_mode == "engineer"
        self.raw_frame_group.setVisible(engineer)
        self.transaction_group.setVisible(engineer)
        self.parsed_result_title.setText("解析结果" if engineer else "业务摘要")

    def _build_overview_tab(self) -> None:
        layout = QVBoxLayout(self.overview_tab)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        top_row = QHBoxLayout()
        self.overview_status_chip = chip("离线", "warning")
        top_row.addWidget(self.overview_status_chip)
        top_row.addStretch(1)
        read_button = QPushButton("读取一帧")
        read_button.clicked.connect(lambda: self._with_selected(self.controller.read_frame_once, show_result=True))
        realtime_button = QPushButton("进入实时采集")
        realtime_button.setProperty("variant", "primary")
        realtime_button.clicked.connect(self.open_realtime_requested.emit)
        top_row.addWidget(read_button)
        top_row.addWidget(realtime_button)
        layout.addLayout(top_row)

        metric_row = QHBoxLayout()
        self.overview_metrics: dict[str, QLabel] = {}
        for key, title in (("co2", "CO2"), ("h2o", "H2O"), ("pressure", "压力")):
            card = CardFrame(muted=True)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("sectionTitle")
            inner.addWidget(label)
            inner.addWidget(value)
            self.overview_metrics[key] = value
            metric_row.addWidget(card, 1)
        layout.addLayout(metric_row)

        advice_card = CardFrame()
        advice_layout = QVBoxLayout(advice_card)
        advice_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        advice_layout.setSpacing(TOKENS.spacing_md)
        advice_layout.addWidget(section_title("建议操作", "优先使用业务语义提示现场人员下一步该做什么。"))
        self.suggestion_list = QListWidget()
        advice_layout.addWidget(self.suggestion_list)
        layout.addWidget(advice_card)

    def _build_config_tab(self) -> None:
        layout = QVBoxLayout(self.config_tab)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        config_card = CardFrame()
        card_layout = QVBoxLayout(config_card)
        card_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        card_layout.setSpacing(TOKENS.spacing_md)
        self.config_device_title = QLabel("当前配置对象")
        self.config_device_title.setObjectName("sectionTitle")
        card_layout.addWidget(self.config_device_title)
        card_layout.addWidget(QLabel("操作员视图使用业务语义，不直接把底层协议词汇当成主文案。"))

        connect_row = QHBoxLayout()
        connect_btn = QPushButton("连接设备")
        connect_btn.setProperty("variant", "primary")
        connect_btn.clicked.connect(lambda: self._with_selected(self.controller.connect_device))
        disconnect_btn = QPushButton("停止采集")
        disconnect_btn.clicked.connect(lambda: self._with_selected(self.controller.disconnect_device))
        mode1_btn = QPushButton("切换到 MODE1")
        mode1_btn.clicked.connect(lambda: self._with_selected(self.controller.set_mode, 1, show_result=True))
        mode2_btn = QPushButton("切换到 MODE2")
        mode2_btn.clicked.connect(lambda: self._with_selected(self.controller.set_mode, 2, show_result=True))
        connect_row.addWidget(connect_btn)
        connect_row.addWidget(disconnect_btn)
        connect_row.addWidget(mode1_btn)
        connect_row.addWidget(mode2_btn)
        card_layout.addLayout(connect_row)

        way_row = QHBoxLayout()
        active_btn = QPushButton("持续输出")
        active_btn.clicked.connect(lambda: self._with_selected(self.controller.set_comm_way, True, show_result=True))
        passive_btn = QPushButton("按需读取")
        passive_btn.clicked.connect(lambda: self._with_selected(self.controller.set_comm_way, False, show_result=True))
        way_row.addWidget(active_btn)
        way_row.addWidget(passive_btn)
        card_layout.addWidget(self._labeled_row("数据输出方式", way_row))

        ftd_row = QHBoxLayout()
        self.ftd_spin = QSpinBox()
        self.ftd_spin.setRange(1, 20)
        ftd_button = QPushButton("应用输出频率")
        ftd_button.clicked.connect(lambda: self._with_selected(self.controller.set_ftd_frequency, self.ftd_spin.value(), show_result=True))
        ftd_row.addWidget(self.ftd_spin)
        ftd_row.addWidget(ftd_button)
        card_layout.addWidget(self._labeled_row("输出频率 (Hz)", ftd_row))

        avg_row = QHBoxLayout()
        self.avg_co2_spin = QSpinBox()
        self.avg_co2_spin.setRange(1, 399)
        self.avg_h2o_spin = QSpinBox()
        self.avg_h2o_spin.setRange(1, 399)
        avg_button = QPushButton("应用平均参数")
        avg_button.clicked.connect(self._apply_average)
        avg_row.addWidget(QLabel("二氧化碳"))
        avg_row.addWidget(self.avg_co2_spin)
        avg_row.addWidget(QLabel("水汽"))
        avg_row.addWidget(self.avg_h2o_spin)
        avg_row.addWidget(avg_button)
        card_layout.addWidget(self._labeled_row("平滑平均", avg_row))

        filter_row = QHBoxLayout()
        self.filter_spin = QSpinBox()
        self.filter_spin.setRange(1, 399)
        filter_button = QPushButton("应用滤波参数")
        filter_button.clicked.connect(lambda: self._with_selected(self.controller.set_filter_params, window_n=self.filter_spin.value(), show_result=True))
        filter_row.addWidget(self.filter_spin)
        filter_row.addWidget(filter_button)
        card_layout.addWidget(self._labeled_row("滤波窗口", filter_row))

        id_row = QHBoxLayout()
        self.device_id_input = QLineEdit()
        id_button = QPushButton("写入设备 ID")
        id_button.setProperty("variant", "danger")
        id_button.clicked.connect(self._write_device_id)
        id_row.addWidget(self.device_id_input)
        id_row.addWidget(id_button)
        card_layout.addWidget(self._labeled_row("设备编号维护", id_row))
        layout.addWidget(config_card)
        layout.addWidget(self._build_primary_analyzer_card())
        layout.addWidget(self._build_trace_gas_card())
        layout.addStretch(1)

    def _build_primary_analyzer_card(self) -> CardFrame:
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "Primary Analyzer QC",
                "Device-level CO2/H2O analyzer profile, diagnostic thresholds, and calibration provenance used by EC processing.",
            )
        )

        profile_row = QHBoxLayout()
        self.primary_analyzer_profile_combo = QComboBox()
        for profile in self.controller.available_gas_analyzer_profiles():
            self.primary_analyzer_profile_combo.addItem(str(profile["label"]), str(profile["profile_id"]))
        self.primary_analyzer_enable_combo = QComboBox()
        self.primary_analyzer_enable_combo.addItems(["enabled", "disabled"])
        apply_button = QPushButton("Apply to EC processing")
        apply_button.setProperty("variant", "primary")
        apply_button.clicked.connect(self._apply_primary_analyzer_config)
        profile_row.addWidget(QLabel("profile_id"))
        profile_row.addWidget(self.primary_analyzer_profile_combo, 2)
        profile_row.addWidget(QLabel("enabled"))
        profile_row.addWidget(self.primary_analyzer_enable_combo)
        profile_row.addWidget(apply_button)
        layout.addLayout(profile_row)

        threshold_row = QHBoxLayout()
        self.primary_signal_warning_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        self.primary_signal_fail_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        self.primary_require_status_combo = QComboBox()
        self.primary_require_status_combo.addItems(["required", "not_required"])
        self.primary_cell_thermo_combo = QComboBox()
        self.primary_cell_thermo_combo.addItems(["auto", "required", "not_required"])
        threshold_row.addWidget(QLabel("warning"))
        threshold_row.addWidget(self.primary_signal_warning_spin)
        threshold_row.addWidget(QLabel("fail"))
        threshold_row.addWidget(self.primary_signal_fail_spin)
        threshold_row.addWidget(QLabel("status_ok"))
        threshold_row.addWidget(self.primary_require_status_combo)
        threshold_row.addWidget(QLabel("cell"))
        threshold_row.addWidget(self.primary_cell_thermo_combo)
        layout.addLayout(threshold_row)

        self.primary_allowed_diag_words_edit = QLineEdit()
        self.primary_allowed_diag_words_edit.setPlaceholderText("0")
        self.primary_calibration_profile_edit = QLineEdit()
        self.primary_calibration_profile_edit.setPlaceholderText("site_zero_span_2026")
        self.primary_source_file_edit = QLineEdit()
        self.primary_source_file_edit.setPlaceholderText("source calibration or normalized diagnostic file")
        self.primary_normalization_command_edit = QLineEdit()
        self.primary_normalization_command_edit.setPlaceholderText("gas_ec_studio normalize-licor --input ...")
        for title, widget in (
            ("allowed_diagnostic_words", self.primary_allowed_diag_words_edit),
            ("calibration_profile_id", self.primary_calibration_profile_edit),
            ("source_file", self.primary_source_file_edit),
            ("normalization_command", self.primary_normalization_command_edit),
        ):
            row = QHBoxLayout()
            row.addWidget(widget)
            layout.addWidget(self._labeled_row(title, row))

        self.primary_analyzer_summary_label = QLabel("--")
        self.primary_analyzer_summary_label.setObjectName("subtitle")
        self.primary_analyzer_summary_label.setWordWrap(True)
        layout.addWidget(self.primary_analyzer_summary_label)
        self.primary_analyzer_profile_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_analyzer_enable_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_signal_warning_spin.valueChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_signal_fail_spin.valueChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_require_status_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_cell_thermo_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_allowed_diag_words_edit.textChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_calibration_profile_edit.textChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_source_file_edit.textChanged.connect(self._refresh_primary_analyzer_summary)
        self.primary_normalization_command_edit.textChanged.connect(self._refresh_primary_analyzer_summary)
        return card

    def _build_trace_gas_card(self) -> CardFrame:
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "Trace Gas CH4 / LI-7700",
                "Device-level methane coefficient profile, LI-7700 diagnostics, and correction provenance used by RP trace-gas processing.",
            )
        )

        top_row = QHBoxLayout()
        self.trace_gas_enable_combo = QComboBox()
        self.trace_gas_enable_combo.addItems(["enabled", "disabled"])
        self.trace_gas_spectroscopic_mode_combo = QComboBox()
        self.trace_gas_spectroscopic_mode_combo.addItems(["input_corrected", "empirical", "wms_line_shape"])
        self.trace_gas_self_heating_mode_combo = QComboBox()
        self.trace_gas_self_heating_mode_combo.addItems(["not_configured", "empirical"])
        apply_button = QPushButton("Apply CH4 profile")
        apply_button.setProperty("variant", "primary")
        apply_button.clicked.connect(self._apply_trace_gas_config)
        top_row.addWidget(QLabel("enabled"))
        top_row.addWidget(self.trace_gas_enable_combo)
        top_row.addWidget(QLabel("spectroscopic"))
        top_row.addWidget(self.trace_gas_spectroscopic_mode_combo)
        top_row.addWidget(QLabel("self_heating"))
        top_row.addWidget(self.trace_gas_self_heating_mode_combo)
        top_row.addWidget(apply_button)
        layout.addLayout(top_row)

        correction_row = QHBoxLayout()
        self.trace_gas_water_vapor_combo = QComboBox()
        self.trace_gas_water_vapor_combo.addItems(["enabled", "disabled"])
        self.trace_gas_spectral_factor_combo = QComboBox()
        self.trace_gas_spectral_factor_combo.addItems(["enabled", "disabled"])
        self.trace_gas_require_lock_combo = QComboBox()
        self.trace_gas_require_lock_combo.addItems(["not_required", "required"])
        self.trace_gas_rssi_warning_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        self.trace_gas_rssi_fail_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        correction_row.addWidget(QLabel("H2O dilution"))
        correction_row.addWidget(self.trace_gas_water_vapor_combo)
        correction_row.addWidget(QLabel("spectral factor"))
        correction_row.addWidget(self.trace_gas_spectral_factor_combo)
        correction_row.addWidget(QLabel("lock"))
        correction_row.addWidget(self.trace_gas_require_lock_combo)
        correction_row.addWidget(QLabel("RSSI warn"))
        correction_row.addWidget(self.trace_gas_rssi_warning_spin)
        correction_row.addWidget(QLabel("RSSI fail"))
        correction_row.addWidget(self.trace_gas_rssi_fail_spin)
        layout.addLayout(correction_row)

        self.trace_gas_coefficient_profile_edit = QLineEdit()
        self.trace_gas_coefficient_profile_edit.setPlaceholderText("li7700_factory_compensated")
        self.trace_gas_source_file_edit = QLineEdit()
        self.trace_gas_source_file_edit.setPlaceholderText("builtin:li7700_factory_compensated or normalized coefficient artifact")
        self.trace_gas_normalization_command_edit = QLineEdit()
        self.trace_gas_normalization_command_edit.setPlaceholderText("gas_ec_studio normalize-li7700 --profile ...")
        for title, widget in (
            ("coefficient_profile_id", self.trace_gas_coefficient_profile_edit),
            ("source_file", self.trace_gas_source_file_edit),
            ("normalization_command", self.trace_gas_normalization_command_edit),
        ):
            row = QHBoxLayout()
            row.addWidget(widget)
            layout.addWidget(self._labeled_row(title, row))

        self.trace_gas_summary_label = QLabel("--")
        self.trace_gas_summary_label.setObjectName("subtitle")
        self.trace_gas_summary_label.setWordWrap(True)
        layout.addWidget(self.trace_gas_summary_label)
        self.trace_gas_enable_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_spectroscopic_mode_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_self_heating_mode_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_water_vapor_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_spectral_factor_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_require_lock_combo.currentIndexChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_rssi_warning_spin.valueChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_rssi_fail_spin.valueChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_coefficient_profile_edit.textChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_source_file_edit.textChanged.connect(self._refresh_trace_gas_summary)
        self.trace_gas_normalization_command_edit.textChanged.connect(self._refresh_trace_gas_summary)
        return card

    def _build_coeff_tab(self) -> None:
        layout = QVBoxLayout(self.coeff_tab)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        coeff_card = CardFrame()
        coeff_layout = QVBoxLayout(coeff_card)
        coeff_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        coeff_layout.setSpacing(TOKENS.spacing_md)
        coeff_layout.addWidget(section_title("系数维护", "读取和写入系数都属于高影响操作，默认只展示必要信息。"))

        group_row = QHBoxLayout()
        self.coeff_group_spin = QSpinBox()
        self.coeff_group_spin.setRange(1, 9)
        self.coeff_values_input = QLineEdit("1.0, 0.0, 0.0, 0.0, 0.0, 0.0")
        read_button = QPushButton("读取系数")
        read_button.clicked.connect(self._read_coefficients)
        write_button = QPushButton("写入系数")
        write_button.setProperty("variant", "danger")
        write_button.clicked.connect(self._write_coefficients)
        group_row.addWidget(self.coeff_group_spin)
        group_row.addWidget(self.coeff_values_input, 1)
        group_row.addWidget(read_button)
        group_row.addWidget(write_button)
        coeff_layout.addWidget(self._labeled_row("系数组", group_row))

        self.coeff_warning_label = QLabel("工程师视图会直接展示系数值，请确认版本来源和影响范围。")
        self.coeff_warning_label.setObjectName("subtitle")
        self.coeff_warning_label.setWordWrap(True)
        coeff_layout.addWidget(self.coeff_warning_label)

        self.coeff_result = QTextEdit()
        self.coeff_result.setReadOnly(True)
        coeff_layout.addWidget(self.coeff_result)
        layout.addWidget(coeff_card)
        layout.addStretch(1)

    def _build_diagnostic_tab(self) -> None:
        layout = QHBoxLayout(self.diagnostic_tab)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        self.raw_frame_group = CardFrame()
        raw_layout = QVBoxLayout(self.raw_frame_group)
        raw_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        raw_layout.setSpacing(TOKENS.spacing_md)
        raw_layout.addWidget(section_title("原始帧", "工程师视图下可以直接看到最近原始帧和解析快照。"))
        self.raw_frame_list = QListWidget()
        self.raw_frame_list.itemClicked.connect(self._show_frame_item)
        raw_layout.addWidget(self.raw_frame_list)
        self.parsed_result_title = QLabel("解析结果")
        self.parsed_result_title.setObjectName("metricLabel")
        raw_layout.addWidget(self.parsed_result_title)
        self.parsed_text = QTextEdit()
        self.parsed_text.setReadOnly(True)
        raw_layout.addWidget(self.parsed_text)
        raw_layout.addWidget(QLabel("原始内容"))
        self.raw_frame_text = QTextEdit()
        self.raw_frame_text.setReadOnly(True)
        raw_layout.addWidget(self.raw_frame_text)

        self.transaction_group = CardFrame(muted=True)
        tx_layout = QVBoxLayout(self.transaction_group)
        tx_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        tx_layout.setSpacing(TOKENS.spacing_md)
        tx_layout.addWidget(section_title("事务历史与错误归因", "把事务真相和人能理解的错误归因放在同一个视角里。"))
        self.transaction_table = QTableWidget(0, 4)
        self.transaction_table.setHorizontalHeaderLabels(["时间", "事务", "状态", "结论"])
        self.transaction_table.horizontalHeader().setStretchLastSection(True)
        self.transaction_table.verticalHeader().setVisible(False)
        tx_layout.addWidget(self.transaction_table)
        tx_layout.addWidget(QLabel("错误归因"))
        self.attribution_list = QListWidget()
        tx_layout.addWidget(self.attribution_list)

        layout.addWidget(self.raw_frame_group, 3)
        layout.addWidget(self.transaction_group, 2)

    def _apply_average(self) -> None:
        self._with_selected(
            self.controller.set_average_params,
            avg_co2=self.avg_co2_spin.value(),
            avg_h2o=self.avg_h2o_spin.value(),
            show_result=True,
        )

    def _read_coefficients(self) -> None:
        def runner(device_uid: str) -> None:
            record, parsed = self.controller.read_coefficients(device_uid, self.coeff_group_spin.value())
            if parsed:
                self._coeff_result_text = json.dumps(parsed, ensure_ascii=False, indent=2)
            else:
                self._coeff_result_text = record.response_summary or record.response_text
            self.coeff_result.setPlainText(self._coeff_result_text)

        self._with_selected(runner)

    def _write_coefficients(self) -> None:
        values = [float(item.strip()) for item in self.coeff_values_input.text().split(",") if item.strip()]
        if not self._danger_confirm(
            "写入系数",
            "写入系数会直接改变设备计算结果和后续高频数据，请确认当前系数版本已经经过审核。",
        ):
            return
        self._with_selected(
            self.controller.write_coefficients,
            group_index=self.coeff_group_spin.value(),
            values=values,
            show_result=True,
        )

    def _write_device_id(self) -> None:
        if not self._danger_confirm(
            "写入设备 ID",
            "改写设备 ID 可能影响现场寻址关系、台账和后续维护，请确认相关文档会同步更新。",
        ):
            return
        self._with_selected(
            self.controller.write_device_id,
            new_device_id=self.device_id_input.text(),
            show_result=True,
        )

    def _populate_primary_analyzer_config(self, config: dict[str, object]) -> None:
        profile_id = str(config.get("profile_id") or config.get("gas_analyzer_profile_id") or "ygas_irga")
        self._set_combo_data(self.primary_analyzer_profile_combo, profile_id)
        self.primary_analyzer_enable_combo.setCurrentIndex(0 if config.get("enabled", True) else 1)
        warning_value = config.get("min_signal_warning_pct", config.get("min_signal_warning", 0.10))
        fail_value = config.get("min_signal_fail_pct", config.get("min_signal_fail", 0.0))
        warning_pct = float(warning_value or 0.0)
        fail_pct = float(fail_value or 0.0)
        if profile_id == "ygas_irga":
            warning_pct = warning_pct * 100.0 if warning_pct <= 1.0 else warning_pct
            fail_pct = fail_pct * 100.0 if fail_pct <= 1.0 else fail_pct
        self.primary_signal_warning_spin.setValue(warning_pct)
        self.primary_signal_fail_spin.setValue(fail_pct)
        self.primary_require_status_combo.setCurrentIndex(0 if config.get("require_status_ok", True) else 1)
        if "require_cell_thermodynamics" in config:
            self.primary_cell_thermo_combo.setCurrentText("required" if config.get("require_cell_thermodynamics") else "not_required")
        else:
            self.primary_cell_thermo_combo.setCurrentText(str(config.get("cell_thermodynamics_mode", "auto") or "auto"))
        allowed_words = config.get("allowed_diagnostic_words", [0])
        if isinstance(allowed_words, (list, tuple)):
            self.primary_allowed_diag_words_edit.setText(",".join(str(value) for value in allowed_words))
        else:
            self.primary_allowed_diag_words_edit.setText(str(allowed_words or "0"))
        self.primary_calibration_profile_edit.setText(str(config.get("calibration_profile_id", "")))
        self.primary_source_file_edit.setText(str(config.get("source_file", config.get("calibration_source_file", "")) or ""))
        self.primary_normalization_command_edit.setText(
            str(config.get("normalization_command", config.get("calibration_normalization_command", "")) or "")
        )
        self._refresh_primary_analyzer_summary()

    def _parse_int_list(self, text: str) -> list[int]:
        values: list[int] = []
        for token in text.replace(";", ",").split(","):
            token = token.strip()
            if token:
                values.append(int(token, 0))
        return values

    def _collect_primary_analyzer_payload(self) -> dict[str, object]:
        profile_id = str(self.primary_analyzer_profile_combo.currentData() or "ygas_irga")
        warning_pct = float(self.primary_signal_warning_spin.value())
        fail_pct = float(self.primary_signal_fail_spin.value())
        cell_mode = self.primary_cell_thermo_combo.currentText().strip()
        payload: dict[str, object] = {
            "enabled": self.primary_analyzer_enable_combo.currentText().strip() == "enabled",
            "profile_id": profile_id,
            "gas_analyzer_profile_id": profile_id,
            "calibration_profile_id": self.primary_calibration_profile_edit.text().strip(),
            "source_file": self.primary_source_file_edit.text().strip(),
            "calibration_source_file": self.primary_source_file_edit.text().strip(),
            "normalization_command": self.primary_normalization_command_edit.text().strip(),
            "calibration_normalization_command": self.primary_normalization_command_edit.text().strip(),
            "require_status_ok": self.primary_require_status_combo.currentText().strip() == "required",
            "cell_thermodynamics_mode": cell_mode,
        }
        if profile_id == "ygas_irga":
            payload["min_signal_warning"] = warning_pct / 100.0
            payload["min_signal_fail"] = fail_pct / 100.0
        else:
            payload["min_signal_warning_pct"] = warning_pct
            payload["min_signal_fail_pct"] = fail_pct
        if cell_mode == "required":
            payload["require_cell_thermodynamics"] = True
        elif cell_mode == "not_required":
            payload["require_cell_thermodynamics"] = False
        allowed_text = self.primary_allowed_diag_words_edit.text().strip()
        if allowed_text:
            try:
                payload["allowed_diagnostic_words"] = self._parse_int_list(allowed_text)
            except ValueError as exc:
                payload["allowed_diagnostic_words_text"] = allowed_text
                payload["allowed_diagnostic_words_parse_error"] = str(exc)
        return payload

    def _apply_primary_analyzer_config(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "No device selected", "Select a device before applying analyzer QC settings.")
            return
        try:
            snapshot = self.controller.apply_device_primary_analyzer_config(
                entry.config.uid,
                self._collect_primary_analyzer_payload(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Primary analyzer QC", str(exc))
            return
        self._populate_primary_analyzer_config(dict(snapshot))
        QMessageBox.information(
            self,
            "Primary analyzer QC",
            f"Applied profile {snapshot.get('profile_id', '')} to EC processing.",
        )

    def _refresh_primary_analyzer_summary(self, *_args) -> None:
        profile_id = str(self.primary_analyzer_profile_combo.currentData() or "ygas_irga")
        profile = next(
            (
                item
                for item in self.controller.available_gas_analyzer_profiles()
                if str(item.get("profile_id", "")) == profile_id
            ),
            {},
        )
        commands = [
            str(command.get("command", ""))
            for command in profile.get("command_specs", [])
            if isinstance(command, dict) and "read" in str(command.get("mode", "")).lower()
        ]
        raw_fields = list(profile.get("raw_output_fields", []) or [])
        limitations = list(profile.get("known_limitations", []) or [])
        self.primary_analyzer_summary_label.setText(
            f"profile={profile_id}; enabled={self.primary_analyzer_enable_combo.currentText().strip()}; "
            f"warning={self.primary_signal_warning_spin.value():.1f}%; fail={self.primary_signal_fail_spin.value():.1f}%; "
            f"commands={','.join(commands) or '--'}; raw_fields={len(raw_fields)}; "
            f"calibration={self.primary_calibration_profile_edit.text().strip() or '--'}; "
            f"source={self.primary_source_file_edit.text().strip() or '--'}; "
            f"limitation={limitations[0] if limitations else '--'}"
        )

    def _populate_trace_gas_config(self, config: dict[str, object]) -> None:
        self.trace_gas_enable_combo.setCurrentText("enabled" if config.get("enabled", False) else "disabled")
        self.trace_gas_coefficient_profile_edit.setText(
            str(config.get("coefficient_profile_id") or "li7700_factory_compensated")
        )
        self.trace_gas_source_file_edit.setText(str(config.get("source_file", "") or ""))
        self.trace_gas_normalization_command_edit.setText(str(config.get("normalization_command", "") or ""))
        self.trace_gas_spectroscopic_mode_combo.setCurrentText(
            str(config.get("spectroscopic_correction_mode") or "input_corrected")
        )
        self.trace_gas_self_heating_mode_combo.setCurrentText(str(config.get("self_heating_mode") or "not_configured"))
        self.trace_gas_water_vapor_combo.setCurrentText(
            "enabled" if config.get("apply_water_vapor_dilution", True) else "disabled"
        )
        self.trace_gas_spectral_factor_combo.setCurrentText(
            "enabled" if config.get("use_spectral_correction_factor", True) else "disabled"
        )
        self.trace_gas_require_lock_combo.setCurrentText("required" if config.get("require_lock", False) else "not_required")
        self.trace_gas_rssi_warning_spin.setValue(float(config.get("min_rssi_warning_pct", 20.0) or 20.0))
        self.trace_gas_rssi_fail_spin.setValue(float(config.get("min_rssi_fail_pct", 10.0) or 10.0))
        self._refresh_trace_gas_summary()

    def _collect_trace_gas_payload(self) -> dict[str, object]:
        coefficient_profile_id = self.trace_gas_coefficient_profile_edit.text().strip() or "li7700_factory_compensated"
        return {
            "enabled": self.trace_gas_enable_combo.currentText().strip() == "enabled",
            "gas": "ch4",
            "method": "li_7700_correction_sequence_v1",
            "analyzer_profile_id": "licor_li7700_family",
            "coefficient_profile_id": coefficient_profile_id,
            "source_file": self.trace_gas_source_file_edit.text().strip(),
            "normalization_command": self.trace_gas_normalization_command_edit.text().strip(),
            "spectroscopic_correction_mode": self.trace_gas_spectroscopic_mode_combo.currentText().strip(),
            "self_heating_mode": self.trace_gas_self_heating_mode_combo.currentText().strip(),
            "apply_water_vapor_dilution": self.trace_gas_water_vapor_combo.currentText().strip() == "enabled",
            "use_spectral_correction_factor": self.trace_gas_spectral_factor_combo.currentText().strip() == "enabled",
            "require_lock": self.trace_gas_require_lock_combo.currentText().strip() == "required",
            "min_rssi_warning_pct": float(self.trace_gas_rssi_warning_spin.value()),
            "min_rssi_fail_pct": float(self.trace_gas_rssi_fail_spin.value()),
            "status_diagnostics": {
                "min_rssi_warning_pct": float(self.trace_gas_rssi_warning_spin.value()),
                "min_rssi_fail_pct": float(self.trace_gas_rssi_fail_spin.value()),
                "require_lock": self.trace_gas_require_lock_combo.currentText().strip() == "required",
            },
        }

    def _apply_trace_gas_config(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "No device selected", "Select a device before applying trace-gas settings.")
            return
        try:
            snapshot = self.controller.apply_device_trace_gas_config(
                entry.config.uid,
                self._collect_trace_gas_payload(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Trace gas CH4 / LI-7700", str(exc))
            return
        self._populate_trace_gas_config(dict(snapshot))
        QMessageBox.information(
            self,
            "Trace gas CH4 / LI-7700",
            f"Applied CH4 coefficient profile {snapshot.get('coefficient_profile_id', '')} to EC processing.",
        )

    def _refresh_trace_gas_summary(self, *_args) -> None:
        source_file = self.trace_gas_source_file_edit.text().strip() or "--"
        normalization = self.trace_gas_normalization_command_edit.text().strip() or "--"
        self.trace_gas_summary_label.setText(
            f"gas=ch4; analyzer=licor_li7700_family; enabled={self.trace_gas_enable_combo.currentText().strip()}; "
            f"coefficient_profile={self.trace_gas_coefficient_profile_edit.text().strip() or 'li7700_factory_compensated'}; "
            f"spectroscopic={self.trace_gas_spectroscopic_mode_combo.currentText().strip()}; "
            f"self_heating={self.trace_gas_self_heating_mode_combo.currentText().strip()}; "
            f"h2o_dilution={self.trace_gas_water_vapor_combo.currentText().strip()}; "
            f"spectral_factor={self.trace_gas_spectral_factor_combo.currentText().strip()}; "
            f"rssi_warn={self.trace_gas_rssi_warning_spin.value():.1f}%; "
            f"rssi_fail={self.trace_gas_rssi_fail_spin.value():.1f}%; source={source_file}; "
            f"normalization={normalization}"
        )

    def _labeled_row(self, title: str, row_layout: QHBoxLayout) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(TOKENS.spacing_xs)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        layout.addWidget(label)
        layout.addLayout(row_layout)
        return wrapper

    def _double_spin(self, low: float, high: float, decimals: int, *, suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        text = value.strip()
        if not text:
            return
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _with_selected(self, fn, *args, show_result: bool = False, **kwargs) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "未选择设备", "请先返回设备中心选择设备。")
            return

        def runner() -> None:
            result = fn(entry.config.uid, *args, **kwargs)
            if show_result:
                self._show_result(result)

        try:
            runner()
        except Exception as exc:
            QMessageBox.warning(self, "操作失败", str(exc))

    def _show_result(self, result) -> None:
        if isinstance(result, list):
            summary = "\n".join(f"{record.label}：{record.response_summary or record.status.value}" for record in result)
            QMessageBox.information(self, "操作结果", summary)
            return
        message = getattr(result, "response_summary", str(result))
        QMessageBox.information(self, "操作结果", str(message))

    def _danger_confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.warning(
                self,
                title,
                message,
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Ok
        )

    def _show_frame_item(self, item) -> None:
        frame = item.data(Qt.UserRole)
        if frame is None:
            return
        self.raw_frame_text.setPlainText(frame.raw_text or "当前帧没有原始内容。")
        self.parsed_text.setPlainText(
            json.dumps(frame.parsed, ensure_ascii=False, indent=2) if frame.parsed else "当前帧没有可展示的解析结果。"
        )
