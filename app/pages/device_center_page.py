from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, TOKENS, chip, section_title


class DeviceCenterPage(QWidget):
    open_detail_requested = Signal(str)
    open_realtime_requested = Signal()

    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        self.layout.setSpacing(TOKENS.spacing_md)
        scroll.setWidget(content)

        self.layout.addWidget(
            section_title(
                "设备中心",
                "首页聚焦设备总体态势、快捷动作和卡片式面板，让现场工程师第一眼就能判断当前是否可采、哪台异常、下一步该做什么。",
            )
        )

        self.status_card = CardFrame()
        self.status_layout = QHBoxLayout(self.status_card)
        self.status_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        self.status_layout.setSpacing(TOKENS.spacing_md)
        self.metric_labels: dict[str, QLabel] = {}
        for key, title in (
            ("online_devices", "在线设备数"),
            ("abnormal_devices", "异常设备数"),
            ("sampling_devices", "正在采集设备数"),
            ("recent_alarm", "最近告警"),
            ("last_updated_at", "最后更新时间"),
        ):
            card = self._status_metric_card(title)
            self.metric_labels[key] = card.findChild(QLabel, "metricValue")
            self.status_layout.addWidget(card, 1 if key != "recent_alarm" else 2)
        self.layout.addWidget(self.status_card)

        self.quick_card = self._build_quick_actions()
        self.layout.addWidget(self.quick_card)

        self.device_grid_card = CardFrame()
        device_grid_layout = QVBoxLayout(self.device_grid_card)
        device_grid_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        device_grid_layout.setSpacing(TOKENS.spacing_md)
        device_grid_layout.addWidget(section_title("设备面板", "每张卡片都同时承载运行状态、关键测量值和快捷入口，避免首页退化成纯表格。"))
        self.device_grid = QGridLayout()
        self.device_grid.setHorizontalSpacing(TOKENS.spacing_md)
        self.device_grid.setVerticalSpacing(TOKENS.spacing_md)
        device_grid_layout.addLayout(self.device_grid)
        self.layout.addWidget(self.device_grid_card)

        self.activity_card = CardFrame(muted=True)
        activity_layout = QHBoxLayout(self.activity_card)
        activity_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        activity_layout.setSpacing(TOKENS.spacing_md)

        tx_block = QVBoxLayout()
        tx_block.addWidget(section_title("最近事务", "帮助工程师快速回看刚刚下发过哪些关键操作。"))
        self.transaction_table = QTableWidget(0, 4)
        self.transaction_table.setHorizontalHeaderLabels(["时间", "设备", "事务", "结论"])
        self.transaction_table.horizontalHeader().setStretchLastSection(True)
        self.transaction_table.verticalHeader().setVisible(False)
        self.transaction_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tx_block.addWidget(self.transaction_table)

        event_block = QVBoxLayout()
        event_block.addWidget(section_title("现场动态", "最近告警、人工标记和协议异常会汇总到这里。"))
        self.event_list = QListWidget()
        event_block.addWidget(self.event_list)

        activity_layout.addLayout(tx_block, 3)
        activity_layout.addLayout(event_block, 2)
        self.layout.addWidget(self.activity_card)
        self.layout.addStretch(1)

        self.controller.devices_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self.refresh)
        self.controller.transactions_changed.connect(self.refresh)
        self.controller.events_changed.connect(self.refresh)
        self.controller.view_mode_changed.connect(lambda _mode: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        summary = self.controller.status_summary()
        self.metric_labels["online_devices"].setText(str(summary["online_devices"]))
        self.metric_labels["abnormal_devices"].setText(str(summary["abnormal_devices"]))
        self.metric_labels["sampling_devices"].setText(str(summary["sampling_devices"]))
        self.metric_labels["recent_alarm"].setText(summary["recent_alarm"])
        self.metric_labels["last_updated_at"].setText(summary["last_updated_at"])

        selected = self.controller.selected_device()
        if selected:
            self.current_target.setText(f"当前设备：{selected.config.label} · {selected.config.port}")
        else:
            self.current_target.setText("当前设备：尚未选择")

        self._rebuild_device_cards()
        self._refresh_recent_activity()
        self.activity_card.setVisible(self.controller.view_mode == "engineer")

    def _status_metric_card(self, title: str) -> CardFrame:
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value)
        return card

    def _build_quick_actions(self) -> CardFrame:
        card = CardFrame()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        layout.setSpacing(TOKENS.spacing_lg)

        add_block = QVBoxLayout()
        add_block.setSpacing(TOKENS.spacing_sm)
        add_block.addWidget(section_title("快捷新增", "快速录入设备名称、端口、波特率和设备 ID。"))
        self.label_input = QLineEdit("新分析仪")
        self.port_input = QLineEdit("COM3")
        self.baudrate_spin = QSpinBox()
        self.baudrate_spin.setRange(1200, 921600)
        self.baudrate_spin.setValue(115200)
        self.device_id_input = QLineEdit("002")
        self.analyzer_profile_combo = QComboBox()
        for profile in self.controller.available_gas_analyzer_profiles():
            self.analyzer_profile_combo.addItem(str(profile["label"]), str(profile["profile_id"]))
        self.analyzer_profile_combo.setCurrentIndex(max(0, self.analyzer_profile_combo.findData("ygas_irga")))
        for title, widget in (
            ("设备名称", self.label_input),
            ("气体分析仪型号", self.analyzer_profile_combo),
            ("COM 口 / 模拟端口", self.port_input),
            ("波特率", self.baudrate_spin),
            ("设备 ID", self.device_id_input),
        ):
            add_block.addWidget(QLabel(title))
            add_block.addWidget(widget)
        add_button = QPushButton("添加设备")
        add_button.setProperty("variant", "primary")
        add_button.clicked.connect(self._add_device)
        add_block.addWidget(add_button)
        hint = QLabel("提示：输入 `SIM2` 可快速创建第二台演示设备。")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        add_block.addWidget(hint)

        actions_block = QVBoxLayout()
        actions_block.setSpacing(TOKENS.spacing_md)
        actions_block.addWidget(section_title("快捷操作", "针对当前选中设备执行最常见动作，必要时再进入单设备详情页。"))
        self.current_target = QLabel("当前设备：尚未选择")
        self.current_target.setObjectName("subtitle")
        self.current_target.setWordWrap(True)
        actions_block.addWidget(self.current_target)

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        button_grid.setVerticalSpacing(TOKENS.spacing_sm)
        actions = [
            ("连接全部", self.controller.connect_all_devices, "primary"),
            ("停止全部", self.controller.disconnect_all_devices, ""),
            ("读取一帧", self.controller.read_frame_selected, ""),
            ("广播配置", self._broadcast_config, "danger"),
            ("进入实时采集", self.open_realtime_requested.emit, "primary"),
            ("打开单设备详情", self._open_detail, ""),
        ]
        for index, (label, action, variant) in enumerate(actions):
            button = QPushButton(label)
            if variant:
                button.setProperty("variant", variant)
            button.clicked.connect(lambda _checked=False, fn=action: self._safe_call(fn))
            button_grid.addWidget(button, index // 2, index % 2)
        actions_block.addLayout(button_grid)

        tip_card = CardFrame(muted=True)
        tip_layout = QVBoxLayout(tip_card)
        tip_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tip_layout.setSpacing(6)
        tip_layout.addWidget(section_title("首页原则", "操作员先看态势与动作，工程师再看事务和原始帧。"))
        for text in (
            "如果异常设备数上升，先看右侧检查器给出的建议操作。",
            "如果需要深入追查某一台设备，请进入单设备详情页。",
            "危险动作会弹出二次确认，不会在首页直接静默执行。",
        ):
            note = QLabel(f"• {text}")
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            tip_layout.addWidget(note)
        actions_block.addWidget(tip_card)

        layout.addLayout(add_block, 2)
        layout.addLayout(actions_block, 3)
        return card

    def _rebuild_device_cards(self) -> None:
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        cards = self.controller.device_cards()
        if not cards:
            empty = CardFrame(muted=True)
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
            empty_layout.addWidget(section_title("暂无设备", "先添加一台设备，首页卡片会在这里自动生成。"))
            self.device_grid.addWidget(empty, 0, 0)
            return

        for index, data in enumerate(cards):
            card = CardFrame(muted=not data["is_selected"])
            layout = QVBoxLayout(card)
            layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            layout.setSpacing(TOKENS.spacing_sm)

            title_row = QHBoxLayout()
            title = QLabel(data["label"])
            title.setObjectName("sectionTitle")
            title_row.addWidget(title)
            title_row.addStretch(1)
            title_row.addWidget(chip(data["status_text"], data["status_level"]))
            layout.addLayout(title_row)

            meta = QLabel(
                f"{data['analyzer_profile_label']} · {data['port']} · {data['baudrate']} bps · 设备 ID {data['device_id']} · "
                f"MODE{data['mode']} · {'主动输出' if data['active_send'] else '按需读取'}"
            )
            meta.setObjectName("subtitle")
            meta.setWordWrap(True)
            layout.addWidget(meta)

            metric_row = QHBoxLayout()
            metric_row.setSpacing(TOKENS.spacing_sm)
            for label, value in (
                ("CO2", f"{data['co2_ppm']:.2f} ppm" if data["co2_ppm"] is not None else "--"),
                ("H2O", f"{data['h2o_mmol']:.2f} mmol" if data["h2o_mmol"] is not None else "--"),
                ("压力", f"{data['pressure_kpa']:.2f} kPa" if data["pressure_kpa"] is not None else "--"),
            ):
                metric_row.addWidget(self._mini_metric(label, value), 1)
            layout.addLayout(metric_row)

            last_time = data["last_frame_time"].strftime("%H:%M:%S") if data["last_frame_time"] else "暂无有效帧"
            info = QLabel(
                f"最近有效帧：{last_time}\n"
                f"当前提示：{data['last_message']}"
            )
            info.setObjectName("subtitle")
            info.setWordWrap(True)
            layout.addWidget(info)

            button_row = QHBoxLayout()
            select_btn = QPushButton("设为当前")
            select_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self.controller.select_device(uid))
            link_btn = QPushButton("断开" if data["connected"] else "连接")
            action = self.controller.disconnect_device if data["connected"] else self.controller.connect_device
            link_btn.clicked.connect(lambda _checked=False, uid=data["uid"], fn=action: self._safe_call(lambda: fn(uid)))
            read_btn = QPushButton("读取一帧")
            read_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self._safe_call(lambda: self.controller.read_frame_once(uid)))
            detail_btn = QPushButton("查看详情")
            detail_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self.open_detail_requested.emit(uid))
            button_row.addWidget(select_btn)
            button_row.addWidget(link_btn)
            button_row.addWidget(read_btn)
            button_row.addWidget(detail_btn)
            layout.addLayout(button_row)

            self.device_grid.addWidget(card, index // 2, index % 2)

    def _mini_metric(self, title: str, value: str) -> CardFrame:
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card

    def _refresh_recent_activity(self) -> None:
        records = self.controller.recent_transactions(limit=10)
        self.transaction_table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            values = [
                record.created_at.strftime("%H:%M:%S"),
                record.device_id,
                record.label,
                record.response_summary or record.status.value,
            ]
            for col_index, value in enumerate(values):
                self.transaction_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))

        self.event_list.clear()
        for event in self.controller.recent_events(limit=12):
            self.event_list.addItem(f"[{event.created_at:%H:%M:%S}] {event.title} · {event.message}")

    def _add_device(self) -> None:
        try:
            uid = self.controller.add_device(
                label=self.label_input.text(),
                port=self.port_input.text(),
                baudrate=self.baudrate_spin.value(),
                device_id=self.device_id_input.text(),
                analyzer_profile=str(self.analyzer_profile_combo.currentData() or "ygas_irga"),
            )
            self.controller.select_device(uid)
            QMessageBox.information(self, "设备已添加", "设备卡片已经创建，现在可以直接连接或进入详情页继续配置。")
        except Exception as exc:
            QMessageBox.warning(self, "添加失败", str(exc))

    def _broadcast_config(self) -> None:
        if not self.controller.selected_device():
            raise RuntimeError("请先选择设备，再执行广播配置。")
        confirmed = (
            QMessageBox.warning(
                self,
                "广播配置",
                "广播配置会向总线上的兼容设备发送统一探测指令，请确认现场允许广播操作。",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Ok
        )
        if not confirmed:
            return
        self.controller.broadcast_config_selected()

    def _open_detail(self) -> None:
        selected = self.controller.selected_device()
        if not selected:
            raise RuntimeError("请先选择设备，再打开单设备详情。")
        self.open_detail_requested.emit(selected.config.uid)

    def _safe_call(self, action) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.warning(self, "操作失败", str(exc))
