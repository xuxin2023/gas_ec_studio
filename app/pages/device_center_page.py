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
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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
        self.setProperty("pageSurface", True)
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

        self.status_card = CardFrame(role="cockpit")
        self.status_card.setMaximumHeight(90)
        self.status_layout = QHBoxLayout(self.status_card)
        self.status_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        self.status_layout.setSpacing(TOKENS.spacing_sm)
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

        self.field_readiness_card = self._build_field_readiness()
        self.layout.addWidget(self.field_readiness_card)

        self.quick_card = self._build_quick_actions()
        self.layout.addWidget(self.quick_card)

        self.device_grid_card = CardFrame(role="panel")
        self.device_grid_card.setMinimumHeight(176)
        self.device_grid_card.setMaximumHeight(184)
        device_grid_layout = QVBoxLayout(self.device_grid_card)
        device_grid_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        device_grid_layout.setSpacing(TOKENS.spacing_xs)
        device_grid_layout.addWidget(section_title("设备面板", "每张卡片都同时承载运行状态、关键测量值和快捷入口，避免首页退化成纯表格。"))
        device_grid_title = device_grid_layout.itemAt(0).widget()
        if device_grid_title is not None:
            device_grid_title.setMaximumHeight(36)
        self.device_grid = QGridLayout()
        self.device_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        self.device_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.device_grid.setColumnStretch(0, 1)
        device_grid_layout.addLayout(self.device_grid)
        self.layout.addWidget(self.device_grid_card)

        self.operator_mission_card = self._build_operator_mission_card()
        self.layout.addWidget(self.operator_mission_card)

        self.operator_evidence_card = self._build_operator_evidence_card()
        self.layout.addWidget(self.operator_evidence_card)

        self.activity_card = CardFrame(muted=True, role="rail")
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
        self._install_operations_deck()
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

        self._refresh_field_readiness(summary, selected)
        self._rebuild_device_cards()
        self._refresh_operator_mission(summary, selected)
        self._refresh_operator_evidence(summary, selected)
        self._refresh_recent_activity()
        self._sync_operations_mode()

    def _status_metric_card(self, title: str) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
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

    def _build_field_readiness(self) -> CardFrame:
        card = CardFrame(role="panel")
        card.setMinimumWidth(0)
        card.setMaximumHeight(142)
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title("现场就绪驾驶舱", "把设备舰队、当前目标、协议链路和下一步动作压缩到一行，减少来回找状态。"), 0, 0, 1, 5)
        self.readiness_values: dict[str, tuple[QLabel, QLabel]] = {}
        for index, (key, title) in enumerate(
            (
                ("fleet", "舰队状态"),
                ("target", "当前目标"),
                ("protocol", "协议链路"),
                ("next", "下一步"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setMinimumWidth(0)
            tile.setMaximumHeight(66)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            tile_layout.setSpacing(TOKENS.spacing_xs)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            title_label.setMinimumWidth(0)
            title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            value.setWordWrap(False)
            note = QLabel("--")
            note.setObjectName("subtitle")
            note.setMinimumWidth(0)
            note.setMaximumHeight(16)
            note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            note.setWordWrap(False)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value)
            tile_layout.addWidget(note)
            self.readiness_values[key] = (value, note)
            layout.addWidget(tile, 1, index)
            layout.setColumnStretch(index, 1)
        self.field_action_card = self._build_field_action_dock()
        layout.addWidget(self.field_action_card, 1, 4)
        layout.setColumnStretch(4, 1)
        return card

    def _build_field_action_dock(self) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        card.setProperty("deckRole", "deviceCenterActionDock")
        card.setMinimumWidth(0)
        card.setMaximumHeight(66)
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, 3, TOKENS.spacing_sm, 3)
        layout.setHorizontalSpacing(TOKENS.spacing_xs)
        layout.setVerticalSpacing(2)
        self.fleet_next_button = self._field_action_button("下一步")
        self.fleet_next_button.clicked.connect(self._activate_fleet_next_action)
        self.fleet_detail_button = self._field_action_button("详情")
        self.fleet_detail_button.clicked.connect(lambda: self._safe_call(self._open_detail))
        self.fleet_realtime_button = self._field_action_button("实时")
        self.fleet_realtime_button.clicked.connect(self.open_realtime_requested.emit)
        self.fleet_log_button = self._field_action_button("证据")
        self.fleet_log_button.clicked.connect(self._activate_fleet_log_action)
        for index, button in enumerate((
            self.fleet_next_button,
            self.fleet_detail_button,
            self.fleet_realtime_button,
            self.fleet_log_button,
        )):
            layout.addWidget(button, index // 2, index % 2)
        return card

    def _field_action_button(self, text: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setProperty("railAction", True)
        button.setMinimumWidth(0)
        button.setMaximumHeight(26)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return button

    def _refresh_field_readiness(self, summary: dict, selected) -> None:
        fleet_value, fleet_note = self.readiness_values["fleet"]
        target_value, target_note = self.readiness_values["target"]
        protocol_value, protocol_note = self.readiness_values["protocol"]
        next_value, next_note = self.readiness_values["next"]

        total = int(summary.get("total_devices", 0) or 0)
        online = int(summary.get("online_devices", 0) or 0)
        abnormal = int(summary.get("abnormal_devices", 0) or 0)
        sampling = int(summary.get("sampling_devices", 0) or 0)
        fleet_value.setText("可采" if total and abnormal == 0 and online > 0 else "待检查")
        fleet_note.setText(f"on {online}/{total} · 采 {sampling} · 异 {abnormal}")

        if selected is None:
            target_value.setText("未选择")
            target_note.setText("先选择或新增一台分析仪，再进入连接/采集。")
            protocol_value.setText("--")
            protocol_note.setText("等待设备目标。")
            next_value.setText("选择设备")
            next_note.setText("从设备面板选择目标，或使用快捷新增。")
            self._refresh_field_action_dock(summary, selected, next_value.text(), next_note.text())
            return

        runtime = selected.runtime
        target_value.setText(selected.config.label)
        target_note.setText(f"{selected.config.port} · ID {selected.config.device_id} · MODE{runtime.mode}")
        protocol_value.setText("主动输出" if runtime.active_send else "按需读取")
        protocol_note.setText(f"{selected.config.analyzer_profile} · {selected.config.baudrate} bps · {runtime.last_message}")
        if not runtime.connected:
            next_value.setText("连接设备")
            next_note.setText("先连接当前目标，再读取一帧确认协议链路。")
        elif abnormal > 0:
            next_value.setText("处理异常")
            next_note.setText("先查看右侧检查器和现场动态，再决定是否继续采集。")
        else:
            next_value.setText("进入采集")
            next_note.setText("设备已连接，可进入实时采集页检查趋势和原始帧。")
        self._refresh_field_action_dock(summary, selected, next_value.text(), next_note.text())

    def _refresh_field_action_dock(self, summary: dict, selected, next_text: str, next_note: str) -> None:
        if not hasattr(self, "fleet_next_button"):
            return
        abnormal = int(summary.get("abnormal_devices", 0) or 0)
        if selected is None:
            target_action = "add"
            tone = "warning"
        elif not selected.runtime.connected:
            target_action = "connect"
            tone = "accent"
        elif abnormal > 0:
            target_action = "activity"
            tone = "danger"
        else:
            target_action = "realtime"
            tone = "success"

        self.fleet_next_button.setText("下一步")
        self.fleet_next_button.setToolTip(f"{next_text}: {next_note}")
        self.fleet_next_button.setProperty("targetAction", target_action)
        self.fleet_next_button.setProperty("actionTone", tone)
        self.fleet_next_button.style().unpolish(self.fleet_next_button)
        self.fleet_next_button.style().polish(self.fleet_next_button)

        has_selected = selected is not None
        self.fleet_detail_button.setEnabled(has_selected)
        self.fleet_detail_button.setToolTip("打开当前设备详情。" if has_selected else "先选择或新增一台设备。")
        self.fleet_realtime_button.setToolTip("进入实时采集页复核曲线与原始帧。")
        log_text = "日志" if abnormal else "证据"
        log_target = "activity" if abnormal else "evidence"
        self.fleet_log_button.setText(log_text)
        self.fleet_log_button.setProperty("targetPanel", log_target)
        self.fleet_log_button.setToolTip("查看最近事务和现场事件。" if abnormal else "查看运行证据矩阵。")

    def _activate_fleet_next_action(self) -> None:
        target = str(self.fleet_next_button.property("targetAction") or "add")
        selected = self.controller.selected_device()
        if target == "add":
            self._show_quick_mode("add")
        elif target == "connect" and selected is not None:
            self._safe_call(lambda: self.controller.connect_device(selected.config.uid))
        elif target == "realtime":
            self.open_realtime_requested.emit()
        elif target == "activity":
            self._show_operations_mode("activity")
        self.refresh()

    def _activate_fleet_log_action(self) -> None:
        target = str(self.fleet_log_button.property("targetPanel") or "evidence")
        self._show_operations_mode("activity" if target == "activity" else "evidence")

    def _build_quick_actions(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setMinimumHeight(132)
        card.setMaximumHeight(154)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = section_title(
            "现场快捷检查器",
            "默认聚焦当前目标和高频动作；新增设备作为第二态收起，避免首屏被表单拉长。",
        )
        title.setMaximumHeight(36)
        header.addWidget(title, 1)
        self.quick_mode_buttons: dict[str, QToolButton] = {}
        for mode, text in (("actions", "操作"), ("add", "新增")):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_quick_mode(key))
            self.quick_mode_buttons[mode] = button
            header.addWidget(button)
        layout.addLayout(header)

        self.quick_stack = QStackedWidget()
        self.quick_stack.setProperty("stackRole", "deviceQuickInspectorStack")
        self.quick_stack.setMaximumHeight(96)
        self.quick_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.quick_stack)

        self.quick_actions_panel = CardFrame(muted=True, role="tile")
        self.quick_actions_panel.setMinimumHeight(92)
        self.quick_actions_panel.setMaximumHeight(96)
        self.quick_actions_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        actions_block = QVBoxLayout(self.quick_actions_panel)
        actions_block.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
        actions_block.setSpacing(TOKENS.spacing_xs)

        action_header = QHBoxLayout()
        action_header.setContentsMargins(0, 0, 0, 0)
        action_label = QLabel("快捷操作")
        action_label.setObjectName("metricLabel")
        action_header.addWidget(action_label)
        action_header.addStretch(1)
        self.current_target = QLabel("当前设备：尚未选择")
        self.current_target.setObjectName("subtitle")
        self.current_target.setWordWrap(False)
        action_header.addWidget(self.current_target, 1)
        actions_block.addLayout(action_header)

        button_grid = QGridLayout()
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        button_grid.setVerticalSpacing(TOKENS.spacing_xs)
        actions = [
            ("连接全部", self.controller.connect_all_devices, "primary"),
            ("停止全部", self.controller.disconnect_all_devices, ""),
            ("读取一帧", self.controller.read_frame_selected, ""),
            ("广播配置", self._broadcast_config, "danger"),
            ("实时采集", self.open_realtime_requested.emit, "primary"),
            ("单设备详情", self._open_detail, ""),
        ]
        for index, (label, action, variant) in enumerate(actions):
            button = QPushButton(label)
            button.setMinimumWidth(0)
            if variant:
                button.setProperty("variant", variant)
            button.clicked.connect(lambda _checked=False, fn=action: self._safe_call(fn))
            button_grid.addWidget(button, 0, index)
        actions_block.addLayout(button_grid)

        self.quick_tip_card = CardFrame(role="panel")
        self.quick_tip_card.setMaximumHeight(0)
        self.quick_tip_card.setVisible(False)
        actions_block.addWidget(self.quick_tip_card)

        self.quick_add_panel = CardFrame(muted=True, role="tile")
        self.quick_add_panel.setMinimumHeight(92)
        self.quick_add_panel.setMaximumHeight(96)
        self.quick_add_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_grid = QGridLayout(self.quick_add_panel)
        add_grid.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
        add_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        add_grid.setVerticalSpacing(TOKENS.spacing_xs)
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

        fields = [
            ("设备名", self.label_input),
            ("分析仪", self.analyzer_profile_combo),
            ("端口", self.port_input),
            ("波特率", self.baudrate_spin),
            ("设备 ID", self.device_id_input),
        ]
        for index, (label, widget) in enumerate(fields):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(1)
            field_label = QLabel(label)
            field_label.setObjectName("metricLabel")
            field_layout.addWidget(field_label)
            field_layout.addWidget(widget)
            add_grid.addWidget(field, index // 3, index % 3)
        add_button = QPushButton("添加设备")
        add_button.setProperty("variant", "primary")
        add_button.clicked.connect(self._add_device)
        add_grid.addWidget(add_button, 1, 2)

        self.quick_stack.addWidget(self.quick_actions_panel)
        self.quick_stack.addWidget(self.quick_add_panel)
        self.quick_sections = {
            "actions": self.quick_actions_panel,
            "add": self.quick_add_panel,
        }
        self._show_quick_mode("actions")
        return card

    def _show_quick_mode(self, mode: str) -> None:
        section = self.quick_sections.get(mode)
        if section is None:
            return
        self.quick_stack.setCurrentWidget(section)
        for key, button in self.quick_mode_buttons.items():
            button.setChecked(key == mode)

    def _install_operations_deck(self) -> None:
        self.operations_deck_card = CardFrame(muted=True, role="rail")
        self.operations_deck_card.setProperty("deckRole", "deviceOperationsInspector")
        self.operations_deck_card.setMinimumHeight(188)
        self.operations_deck_card.setMaximumHeight(206)
        self.operations_deck_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        deck_layout = QVBoxLayout(self.operations_deck_card)
        deck_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        deck_layout.setSpacing(TOKENS.spacing_xs)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = section_title(
            "现场闭环检查器",
            "把处理链路、证据矩阵和工程日志收进一个桌面 inspector，避免首页继续向下堆面板。",
        )
        title.setMaximumHeight(36)
        header.addWidget(title, 1)
        self.operations_mode_buttons: dict[str, QToolButton] = {}
        for mode, text in (("mission", "链路"), ("evidence", "证据"), ("activity", "日志")):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_operations_mode(key))
            self.operations_mode_buttons[mode] = button
            header.addWidget(button)
        deck_layout.addLayout(header)

        self.operations_stack = QStackedWidget()
        self.operations_stack.setProperty("stackRole", "deviceOperationsInspectorStack")
        self.operations_stack.setMaximumHeight(150)
        self.operations_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        deck_layout.addWidget(self.operations_stack)

        insert_at = self.layout.indexOf(self.operator_mission_card)
        self.layout.insertWidget(insert_at, self.operations_deck_card)
        self.operations_sections = {
            "mission": self.operator_mission_card,
            "evidence": self.operator_evidence_card,
            "activity": self.activity_card,
        }
        for widget in self.operations_sections.values():
            self.layout.removeWidget(widget)
            widget.setParent(None)
            self._compact_operations_section(widget)
            self.operations_stack.addWidget(widget)
        self._last_operations_view_mode: str | None = None
        self._show_operations_mode("mission")

    def _compact_operations_section(self, widget: QWidget) -> None:
        widget.setMinimumHeight(132)
        widget.setMaximumHeight(150)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = widget.layout()
        if isinstance(layout, QGridLayout):
            title_item = layout.itemAtPosition(0, 0)
            if title_item is not None and title_item.widget() is not None:
                title_item.widget().setVisible(False)
                title_item.widget().setMaximumHeight(0)
        for child in widget.findChildren(CardFrame):
            if child.property("cardRole") == "tile":
                child.setMinimumHeight(48)
                child.setMaximumHeight(58)
                for label in child.findChildren(QLabel):
                    if label.objectName() == "subtitle":
                        label.setVisible(False)

    def _show_operations_mode(self, mode: str) -> None:
        section = self.operations_sections.get(mode)
        if section is None:
            return
        self.operations_stack.setCurrentWidget(section)
        for key, button in self.operations_mode_buttons.items():
            button.setChecked(key == mode)

    def _sync_operations_mode(self) -> None:
        view_mode = self.controller.view_mode
        if view_mode == self._last_operations_view_mode:
            return
        self._last_operations_view_mode = view_mode
        self._show_operations_mode("activity" if view_mode == "engineer" else "mission")

    def _build_quick_actions_legacy(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setMinimumHeight(238)
        card.setMaximumHeight(270)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        self.quick_add_panel = CardFrame(muted=True, role="tile")
        self.quick_add_panel.setMinimumHeight(210)
        self.quick_add_panel.setMaximumHeight(236)
        self.quick_add_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        add_block = QVBoxLayout(self.quick_add_panel)
        add_block.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        add_block.setSpacing(TOKENS.spacing_xs)
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
        add_block.addLayout(
            self._compact_setup_grid(
                [
                    ("设备名称", self.label_input),
                    ("气体分析仪型号", self.analyzer_profile_combo),
                    ("COM 口 / 模拟端口", self.port_input),
                    ("波特率", self.baudrate_spin),
                    ("设备 ID", self.device_id_input),
                ]
            )
        )
        add_button = QPushButton("添加设备")
        add_button.setProperty("variant", "primary")
        add_button.clicked.connect(self._add_device)
        add_block.addWidget(add_button)
        hint = QLabel("提示：输入 `SIM2` 可快速创建第二台演示设备。")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        add_block.addWidget(hint)

        self.quick_actions_panel = CardFrame(muted=True, role="tile")
        self.quick_actions_panel.setMinimumHeight(210)
        self.quick_actions_panel.setMaximumHeight(236)
        self.quick_actions_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        actions_block = QVBoxLayout(self.quick_actions_panel)
        actions_block.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        actions_block.setSpacing(TOKENS.spacing_xs)
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
            button_grid.addWidget(button, index // 3, index % 3)
        actions_block.addLayout(button_grid)
        actions_block.addSpacing(TOKENS.spacing_xs)

        self.quick_tip_card = CardFrame(role="panel")
        self.quick_tip_card.setMaximumHeight(54)
        self.quick_tip_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tip_layout = QVBoxLayout(self.quick_tip_card)
        tip_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
        tip_layout.setSpacing(0)
        tip = QLabel("首页原则：操作员先看态势与动作；深查单台设备再进详情；危险动作保留二次确认。")
        tip.setObjectName("subtitle")
        tip.setWordWrap(True)
        tip_layout.addWidget(tip)
        actions_block.addWidget(self.quick_tip_card)

        layout.addWidget(self.quick_add_panel, 2)
        layout.addWidget(self.quick_actions_panel, 3)
        return card

    def _build_operator_mission_card(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        card.setProperty("deckRole", "deviceOperatorMissionDeck")
        card.setMinimumHeight(148)
        card.setMaximumHeight(186)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setHorizontalSpacing(TOKENS.spacing_md)
        layout.setVerticalSpacing(TOKENS.spacing_sm)
        layout.addWidget(
            section_title("处理链路交接台", "把设备接入、实时采集、EC 处理和报告交付压缩到一行，减少首页和计算页之间的跳转盲区。"),
            0,
            0,
            1,
            4,
        )

        self.operator_mission_tiles: dict[str, tuple[QLabel, QLabel]] = {}
        stages = (
            ("device", "设备接入"),
            ("capture", "实时采集"),
            ("processing", "EC 处理"),
            ("delivery", "报告交付"),
        )
        for index, (key, title) in enumerate(stages):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("missionStage", key)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            tile_layout.setSpacing(TOKENS.spacing_xs)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            note = QLabel("--")
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value)
            tile_layout.addWidget(note)
            self.operator_mission_tiles[key] = (value, note)
            layout.addWidget(tile, 1, index)
        return card

    def _refresh_operator_mission(self, summary: dict, selected) -> None:
        device_value, device_note = self.operator_mission_tiles["device"]
        capture_value, capture_note = self.operator_mission_tiles["capture"]
        processing_value, processing_note = self.operator_mission_tiles["processing"]
        delivery_value, delivery_note = self.operator_mission_tiles["delivery"]

        total = int(summary.get("total_devices", 0) or 0)
        online = int(summary.get("online_devices", 0) or 0)
        sampling = int(summary.get("sampling_devices", 0) or 0)
        abnormal = int(summary.get("abnormal_devices", 0) or 0)
        device_value.setText("就绪" if selected is not None and online > 0 and abnormal == 0 else "待检查")
        device_note.setText(
            f"online={online}/{total}，selected={selected.config.label if selected else '--'}，abnormal={abnormal}"
        )

        capture_value.setText("采集中" if sampling else "待启动")
        capture_note.setText("已有实时缓冲，可进入采集页复核曲线。" if sampling else "连接设备后启动实时采集，确认高频帧稳定。")

        processing_summary = dict(self.controller.ec_processing_workspace.get("summary", {}) or {})
        processing_status = str(processing_summary.get("status", "empty") or "empty")
        valid_windows = processing_summary.get("valid_window_count", 0)
        window_count = processing_summary.get("window_count", 0)
        processing_value.setText("已闭合" if processing_status == "ok" else "待运行")
        processing_note.setText(f"status={processing_status}，windows={valid_windows}/{window_count}")

        report_workspace = dict(self.controller.report_center_workspace or {})
        export_status = str(report_workspace.get("export_status", "not_exported") or "not_exported")
        delivery_value.setText("已导出" if export_status in {"exported", "ready"} else "待交付")
        delivery_note.setText(f"export={export_status}，处理完成后进入报告中心生成交付包。")

    def _build_operator_evidence_card(self) -> CardFrame:
        card = CardFrame(role="panel")
        card.setProperty("deckRole", "deviceOperatorEvidenceMatrix")
        card.setMinimumHeight(214)
        card.setMaximumHeight(262)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setHorizontalSpacing(TOKENS.spacing_md)
        layout.setVerticalSpacing(TOKENS.spacing_sm)
        layout.addWidget(
            section_title(
                "现场运行证据矩阵",
                "把最新帧、协议事务、现场事件、缓冲规模、处理闭合和交付状态放到同一屏，避免首页下半屏空白。",
            ),
            0,
            0,
            1,
            3,
        )

        self.operator_evidence_tiles: dict[str, tuple[QLabel, QLabel]] = {}
        tiles = (
            ("latest_frame", "最新有效帧"),
            ("protocol_tx", "协议事务"),
            ("site_event", "现场事件"),
            ("runtime_buffer", "缓冲规模"),
            ("processing_gate", "处理闭合"),
            ("delivery_gate", "交付出口"),
        )
        for index, (key, title) in enumerate(tiles):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceStage", key)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            tile_layout.setSpacing(TOKENS.spacing_xs)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            note = QLabel("--")
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value)
            tile_layout.addWidget(note)
            self.operator_evidence_tiles[key] = (value, note)
            layout.addWidget(tile, 1 + index // 3, index % 3)
        return card

    def _refresh_operator_evidence(self, summary: dict, selected) -> None:
        device_uid = selected.config.uid if selected is not None else None
        latest_frame_value, latest_frame_note = self.operator_evidence_tiles["latest_frame"]
        protocol_value, protocol_note = self.operator_evidence_tiles["protocol_tx"]
        event_value, event_note = self.operator_evidence_tiles["site_event"]
        buffer_value, buffer_note = self.operator_evidence_tiles["runtime_buffer"]
        processing_value, processing_note = self.operator_evidence_tiles["processing_gate"]
        delivery_value, delivery_note = self.operator_evidence_tiles["delivery_gate"]

        runtime = selected.runtime if selected is not None else None
        if runtime is not None and runtime.last_frame_time is not None:
            latest_frame_value.setText(runtime.last_frame_time.strftime("%H:%M:%S"))
            latest_frame_note.setText(
                f"quality={runtime.last_frame_quality.value}，message={runtime.last_message}"
            )
        else:
            latest_frame_value.setText("暂无")
            latest_frame_note.setText("等待设备连接并产生有效高频帧。")

        transactions = self.controller.recent_transactions(device_uid=device_uid, limit=6)
        latest_tx = transactions[0] if transactions else None
        protocol_value.setText(f"{len(transactions)} 条")
        protocol_note.setText(
            f"{latest_tx.label} · {latest_tx.response_summary or latest_tx.status.value}"
            if latest_tx
            else "暂无最近协议事务。"
        )

        events = self.controller.recent_events(device_uid=device_uid, limit=6)
        latest_event = events[0] if events else None
        event_value.setText(f"{len(events)} 条")
        event_note.setText(
            f"{latest_event.severity} · {latest_event.title}"
            if latest_event
            else str(summary.get("recent_alarm", "暂无需要处理的告警。"))
        )

        buffer_rows = self.controller.realtime_rows(device_uid=device_uid, seconds=300.0)
        buffer_value.setText(f"{len(buffer_rows)} 帧")
        buffer_note.setText("最近 5 分钟实时缓冲，用于进入采集页或 RP 预处理。")

        processing_summary = dict(self.controller.ec_processing_workspace.get("summary", {}) or {})
        processing_status = str(processing_summary.get("status", "empty") or "empty")
        processing_value.setText(processing_status)
        processing_note.setText(
            f"windows={processing_summary.get('valid_window_count', 0)}/{processing_summary.get('window_count', 0)}，"
            f"target={processing_summary.get('target', 'runtime_buffer')}"
        )

        report_workspace = dict(self.controller.report_center_workspace or {})
        export_status = str(report_workspace.get("export_status", "not_exported") or "not_exported")
        delivery_value.setText(export_status)
        delivery_note.setText(
            f"view={report_workspace.get('view_mode', 'engineering')}，"
            f"latest={report_workspace.get('updated_at', '--')}"
        )

    def _compact_setup_grid(self, fields: list[tuple[str, QWidget]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        columns = 3 if len(fields) > 4 else 2
        for index, (title, widget) in enumerate(fields):
            row = index // columns
            column = index % columns
            field = QWidget()
            field.setMinimumHeight(50)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(TOKENS.spacing_xs)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            field_layout.addWidget(label)
            field_layout.addWidget(widget)
            grid.addWidget(field, row, column)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        return grid

    def _rebuild_device_cards(self) -> None:
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        cards = self.controller.device_cards()
        if not cards:
            empty = CardFrame(muted=True, role="tile")
            empty.setMaximumHeight(92)
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            empty_layout.addWidget(section_title("暂无设备", "先添加一台设备，首页摘要卡会自动生成。"))
            self.device_grid.addWidget(empty, 0, 0)
            empty.show()
            return

        single_card = len(cards) == 1
        for index, data in enumerate(cards):
            card = self._device_summary_card(data)
            if single_card:
                self.device_grid.addWidget(card, 0, 0)
            else:
                self.device_grid.addWidget(card, index // 2, index % 2)
            card.show()

    def _device_summary_card(self, data: dict) -> CardFrame:
        card = CardFrame(muted=not data["is_selected"], role="cockpit" if data["is_selected"] else "tile")
        card.setMinimumHeight(98)
        card.setMaximumHeight(108)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(TOKENS.spacing_xs)

        title = QLabel(data["label"])
        title.setObjectName("sectionTitle")
        title.setMaximumHeight(22)
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(chip(data["status_text"], data["status_level"]), 0, 2)

        meta = QLabel(
            f"{data['analyzer_profile_label']} · {data['port']} · {data['baudrate']} bps · "
            f"ID {data['device_id']} · MODE{data['mode']} · {'主动输出' if data['active_send'] else '按需读取'}"
        )
        meta.setObjectName("subtitle")
        meta.setWordWrap(False)
        meta.setMaximumHeight(18)
        layout.addWidget(meta, 0, 3, 1, 4)

        for column, (label, value) in enumerate(
            (
                ("CO2", f"{data['co2_ppm']:.2f} ppm" if data["co2_ppm"] is not None else "--"),
                ("H2O", f"{data['h2o_mmol']:.2f} mmol" if data["h2o_mmol"] is not None else "--"),
                ("压力", f"{data['pressure_kpa']:.2f} kPa" if data["pressure_kpa"] is not None else "--"),
            )
        ):
            layout.addWidget(self._mini_metric(label, value), 1, column)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(TOKENS.spacing_xs)
        select_btn = QPushButton("设为当前")
        select_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self.controller.select_device(uid))
        link_btn = QPushButton("断开" if data["connected"] else "连接")
        action = self.controller.disconnect_device if data["connected"] else self.controller.connect_device
        link_btn.clicked.connect(lambda _checked=False, uid=data["uid"], fn=action: self._safe_call(lambda: fn(uid)))
        read_btn = QPushButton("读取一帧")
        read_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self._safe_call(lambda: self.controller.read_frame_once(uid)))
        detail_btn = QPushButton("查看详情")
        detail_btn.clicked.connect(lambda _checked=False, uid=data["uid"]: self.open_detail_requested.emit(uid))
        for button in (select_btn, link_btn, read_btn, detail_btn):
            button.setMinimumWidth(0)
            button_row.addWidget(button)
        layout.addLayout(button_row, 1, 3, 1, 4)
        for column in range(7):
            layout.setColumnStretch(column, 1)
        return card

    def _rebuild_device_cards_legacy(self) -> None:
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

        single_card = len(cards) == 1
        for index, data in enumerate(cards):
            card = CardFrame(muted=not data["is_selected"], role="cockpit" if data["is_selected"] else "tile")
            card.setMinimumHeight(138)
            card.setMaximumHeight(150)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
            layout.setSpacing(TOKENS.spacing_xs)

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
            meta.setWordWrap(False)
            meta.setMaximumHeight(18)
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
            info.setWordWrap(False)
            info.setMaximumHeight(18)
            info.setVisible(False)
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

            if single_card:
                self.device_grid.addWidget(card, 0, 0, 1, 2)
            else:
                self.device_grid.addWidget(card, index // 2, index % 2)

    def _mini_metric(self, title: str, value: str) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        card.setMinimumHeight(34)
        card.setMaximumHeight(38)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setProperty("compactMetric", True)
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
