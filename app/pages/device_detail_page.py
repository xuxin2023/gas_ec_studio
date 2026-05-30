from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
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
        layout.addStretch(1)

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
