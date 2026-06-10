from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, PLOT_SERIES_COLORS, TOKENS, chip, configure_plot_theme, section_title


class RealtimePage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.display_paused = False
        self.metric_buttons: dict[str, QToolButton] = {}
        self.window_options = {
            "最近 30 秒": 30.0,
            "最近 2 分钟": 120.0,
            "最近 10 分钟": 600.0,
        }
        self._plot_rows = []
        self._last_view_key: tuple[str | None, float] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "实时采集",
                "一眼看趋势，一步看异常，再一步追到原始帧。时间窗、曲线、事件和原始解析都围绕同一条时间轴组织。",
            )
        )

        self.control_card = self._build_control_bar()
        layout.addWidget(self.control_card)

        self.summary_card = self._build_summary_bar()
        layout.addWidget(self.summary_card)

        self.plot_card = self._build_plot_area()
        layout.addWidget(self.plot_card, 1)

        self.bottom_card = self._build_bottom_area()
        layout.addWidget(self.bottom_card, 1)

        self.controller.frame_received.connect(lambda _frame: self.refresh())
        self.controller.devices_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self.refresh)
        self.controller.events_changed.connect(self.refresh)
        self.controller.view_mode_changed.connect(lambda _mode: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self._refresh_device_selector()
        entry = self.controller.selected_device()
        if entry is None:
            return
        window_s = self.current_window_seconds()
        rows = self.controller.selected_device_realtime_rows(seconds=window_s)
        self._plot_rows = rows
        view_key = (entry.config.uid, window_s)

        stats = self.controller.realtime_statistics(entry.config.uid, window_s=window_s)
        self.summary_values["sample_rate"].setText(f"{stats['sample_rate']:.2f} 帧/秒")
        self.summary_values["valid_frame_rate"].setText(f"{stats['valid_frame_rate']:.2f} 帧/秒")
        self.summary_values["residual_frame_rate"].setText(f"{stats['residual_frame_rate']:.2f} 帧/秒")
        self.summary_values["anomaly_count"].setText(str(stats["anomaly_count"]))
        self._refresh_session_deck(entry, rows, stats)

        if not self.display_paused:
            self._refresh_plot(rows, reset_view=view_key != self._last_view_key)
            self._last_view_key = view_key
        self._refresh_events()
        self._refresh_frames()

    def current_window_seconds(self) -> float:
        return self.window_options.get(self.window_combo.currentText(), 120.0)

    def _refresh_session_deck(self, entry, rows, stats: dict) -> None:
        connected = bool(entry.runtime.connected)
        row_count = len(rows)
        anomaly_count = int(stats.get("anomaly_count", 0) or 0)
        valid_rate = float(stats.get("valid_frame_rate", 0.0) or 0.0)
        residual_rate = float(stats.get("residual_frame_rate", 0.0) or 0.0)
        if not connected:
            self._set_session_chip("待连接", "warning")
        elif anomaly_count > 0 or residual_rate > valid_rate:
            self._set_session_chip("需关注", "danger")
        elif row_count > 0:
            self._set_session_chip("采集中", "success")
        else:
            self._set_session_chip("等待帧", "warning")
        self.session_device_value.setText(entry.config.label)
        self.session_window_note.setText(
            f"{entry.config.port} · {self.window_combo.currentText()} · buffer={row_count} frames"
        )
        self.session_health_note.setText(
            f"valid={valid_rate:.2f}/s，residual={residual_rate:.2f}/s，anomaly={anomaly_count}"
        )

    def _set_session_chip(self, text: str, tone: str) -> None:
        self.session_state_chip.setText(text)
        self.session_state_chip.setProperty("chipTone", tone)
        self.session_state_chip.style().unpolish(self.session_state_chip)
        self.session_state_chip.style().polish(self.session_state_chip)

    def _build_control_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setMinimumHeight(154)
        card.setMaximumHeight(172)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(section_title("控制条", "设备、时间窗和指标都在这一层完成，不需要离开当前页。"))
        header.addStretch(1)
        self.capture_command_chip = chip("实时控制台", "accent")
        header.addWidget(self.capture_command_chip)
        layout.addLayout(header)

        deck = QHBoxLayout()
        deck.setContentsMargins(0, 0, 0, 0)
        deck.setSpacing(TOKENS.spacing_md)

        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.window_combo = QComboBox()
        self.window_combo.addItems(list(self.window_options.keys()))
        self.window_combo.setCurrentText("最近 2 分钟")
        self.window_combo.currentIndexChanged.connect(lambda _index: self.refresh())

        self.capture_target_panel = CardFrame(muted=True, role="tile")
        target_layout = QGridLayout(self.capture_target_panel)
        target_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        target_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        target_layout.setVerticalSpacing(TOKENS.spacing_xs)
        target_title = QLabel("采集目标")
        target_title.setObjectName("metricLabel")
        target_layout.addWidget(target_title, 0, 0, 1, 2)
        device_label = QLabel("设备")
        device_label.setObjectName("metricLabel")
        window_label = QLabel("时间窗")
        window_label.setObjectName("metricLabel")
        target_layout.addWidget(device_label, 1, 0)
        target_layout.addWidget(self.device_combo, 2, 0)
        target_layout.addWidget(window_label, 1, 1)
        target_layout.addWidget(self.window_combo, 2, 1)
        target_layout.setColumnStretch(0, 1)
        target_layout.setColumnStretch(1, 1)
        deck.addWidget(self.capture_target_panel, 3)

        metrics_wrapper = QWidget()
        metrics_layout = QHBoxLayout(metrics_wrapper)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(TOKENS.spacing_xs)
        for key, label in (("co2", "CO2"), ("h2o", "H2O"), ("pressure", "压力")):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(True)
            button.clicked.connect(self._update_metric_visibility)
            self.metric_buttons[key] = button
            metrics_layout.addWidget(button)
        self.capture_metric_panel = CardFrame(muted=True, role="tile")
        metric_layout = QVBoxLayout(self.capture_metric_panel)
        metric_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        metric_layout.setSpacing(TOKENS.spacing_xs)
        metric_title = QLabel("曲线指标")
        metric_title.setObjectName("metricLabel")
        metric_layout.addWidget(metric_title)
        metric_layout.addWidget(metrics_wrapper)
        metric_layout.addStretch(1)
        deck.addWidget(self.capture_metric_panel, 2)

        self.start_button = QPushButton("开始")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self._start_capture)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setCheckable(True)
        self.pause_button.clicked.connect(self._toggle_pause)
        mark_button = QPushButton("标记异常")
        mark_button.clicked.connect(self._mark_anomaly)
        export_button = QPushButton("导出片段")
        export_button.clicked.connect(self._export_segment)
        clear_button = QPushButton("清空显示")
        clear_button.clicked.connect(self._clear_selected_buffer)
        restore_button = QPushButton("恢复视图")
        restore_button.clicked.connect(self._reset_view)
        self.capture_action_panel = CardFrame(muted=True, role="tile")
        action_layout = QGridLayout(self.capture_action_panel)
        action_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        action_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        action_layout.setVerticalSpacing(TOKENS.spacing_xs)
        action_title = QLabel("采集动作")
        action_title.setObjectName("metricLabel")
        action_layout.addWidget(action_title, 0, 0, 1, 6)
        for index, button in enumerate((self.start_button, self.pause_button, mark_button, export_button, clear_button, restore_button)):
            button.setMinimumWidth(0)
            action_layout.addWidget(button, 1, index)
        deck.addWidget(self.capture_action_panel, 4)
        layout.addLayout(deck)
        return card

    def _build_summary_bar(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        card.setProperty("deckRole", "realtimeSummaryDeck")
        card.setMaximumHeight(116)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)
        session_card = CardFrame(muted=True, role="tile")
        session_card.setMinimumHeight(72)
        session_card.setMaximumHeight(94)
        session_layout = QVBoxLayout(session_card)
        session_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        session_layout.setSpacing(TOKENS.spacing_xs)
        session_header = QHBoxLayout()
        session_header.setSpacing(TOKENS.spacing_sm)
        session_title = QLabel("采集会话")
        session_title.setObjectName("metricLabel")
        self.session_state_chip = chip("等待设备", "warning")
        session_header.addWidget(session_title)
        session_header.addStretch(1)
        session_header.addWidget(self.session_state_chip)
        session_layout.addLayout(session_header)
        self.session_device_value = QLabel("--")
        self.session_device_value.setObjectName("metricValue")
        self.session_device_value.setProperty("compactMetric", True)
        self.session_device_value.setWordWrap(True)
        self.session_window_note = QLabel("--")
        self.session_window_note.setObjectName("subtitle")
        self.session_window_note.setWordWrap(True)
        self.session_health_note = QLabel("--")
        self.session_health_note.setObjectName("subtitle")
        self.session_health_note.setWordWrap(True)
        session_layout.addWidget(self.session_device_value)
        session_layout.addWidget(self.session_window_note)
        session_layout.addWidget(self.session_health_note)
        layout.addWidget(session_card, 2)
        self.summary_values: dict[str, QLabel] = {}
        self.summary_metric_cards: list[CardFrame] = []
        for key, title in (
            ("sample_rate", "当前采样率"),
            ("valid_frame_rate", "有效帧率"),
            ("residual_frame_rate", "残帧率"),
            ("anomaly_count", "最近异常次数"),
        ):
            metric_card = CardFrame(muted=True, role="tile")
            metric_card.setMinimumHeight(72)
            metric_card.setMaximumHeight(94)
            metric_layout = QVBoxLayout(metric_card)
            metric_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            metric_layout.setSpacing(TOKENS.spacing_xs)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            metric_layout.addWidget(label)
            metric_layout.addWidget(value)
            self.summary_values[key] = value
            self.summary_metric_cards.append(metric_card)
            layout.addWidget(metric_card, 1)
        return card

    def _build_plot_area(self) -> CardFrame:
        card = CardFrame(role="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("主图表区", "支持多曲线实时显示、悬停读数、缩放和恢复视图。"))
        self.hover_label = QLabel("将鼠标移动到图表区域，可查看对应时间点的测量值。")
        self.hover_label.setObjectName("subtitle")
        layout.addWidget(self.hover_label)

        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("transparent")
        self.co2_plot = self.graphics.addPlot(row=0, col=0)
        self.h2o_plot = self.graphics.addPlot(row=1, col=0)
        self.pressure_plot = self.graphics.addPlot(row=2, col=0)
        self.h2o_plot.setXLink(self.co2_plot)
        self.pressure_plot.setXLink(self.co2_plot)
        self._configure_plot(self.co2_plot, "CO2 (ppm)")
        self._configure_plot(self.h2o_plot, "H2O (mmol)")
        self._configure_plot(self.pressure_plot, "Pressure (kPa)", show_bottom=True)
        self.co2_curve = self.co2_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.1))
        self.h2o_curve = self.h2o_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        self.pressure_curve = self.pressure_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["slate"], width=2.0))

        self.crosshair_lines = {}
        for key, plot in (("co2", self.co2_plot), ("h2o", self.h2o_plot), ("pressure", self.pressure_plot)):
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1))
            plot.addItem(line, ignoreBounds=True)
            self.crosshair_lines[key] = line

        self.mouse_proxy = pg.SignalProxy(self.graphics.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved)
        layout.addWidget(self.graphics, 1)
        return card

    def _build_bottom_area(self) -> CardFrame:
        card = CardFrame(muted=True, role="rail")
        card.setMinimumHeight(162)
        card.setMaximumHeight(180)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)

        event_column = QVBoxLayout()
        event_column.setSpacing(TOKENS.spacing_sm)
        event_column.addWidget(section_title("事件与告警", "点击某条事件，图表会自动跳到对应时间点。"))
        self.event_list = QListWidget()
        self.event_list.setMinimumHeight(76)
        self.event_list.itemClicked.connect(self._focus_event)
        event_column.addWidget(self.event_list)

        frame_column = QVBoxLayout()
        frame_column.setSpacing(TOKENS.spacing_sm)
        frame_column.addWidget(section_title("原始帧与解析", "左侧看帧列表，右侧同时看解析结果和原始内容。"))
        frame_split = QHBoxLayout()
        frame_split.setSpacing(TOKENS.spacing_md)
        self.frame_list = QListWidget()
        self.frame_list.setMinimumHeight(76)
        self.frame_list.itemClicked.connect(self._show_frame_detail)
        frame_split.addWidget(self.frame_list, 2)
        detail_split = QHBoxLayout()
        detail_split.setSpacing(TOKENS.spacing_sm)
        parsed_column = QVBoxLayout()
        parsed_column.setSpacing(TOKENS.spacing_xs)
        parsed_label = QLabel("解析结果")
        parsed_label.setObjectName("metricLabel")
        parsed_column.addWidget(parsed_label)
        self.parsed_text = QTextEdit()
        self.parsed_text.setReadOnly(True)
        self.parsed_text.setMinimumHeight(70)
        parsed_column.addWidget(self.parsed_text, 1)
        raw_column = QVBoxLayout()
        raw_column.setSpacing(TOKENS.spacing_xs)
        raw_label = QLabel("原始内容")
        raw_label.setObjectName("metricLabel")
        raw_column.addWidget(raw_label)
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setMinimumHeight(70)
        raw_column.addWidget(self.raw_text, 1)
        detail_split.addLayout(parsed_column, 3)
        detail_split.addLayout(raw_column, 2)
        frame_split.addLayout(detail_split, 3)
        frame_column.addLayout(frame_split, 1)

        layout.addLayout(event_column, 2)
        layout.addLayout(frame_column, 3)
        return card

    def _configure_plot(self, plot: pg.PlotItem, label: str, *, show_bottom: bool = False) -> None:
        configure_plot_theme(plot, left_label=label, bottom_label="时间 (秒)", show_bottom=show_bottom)
        plot.setDownsampling(mode="peak")
        plot.setClipToView(True)

    def _refresh_device_selector(self) -> None:
        current_uid = self.controller.selected_device_uid
        if self.device_combo.count() == len(self.controller.device_cards()):
            matched = False
            for index in range(self.device_combo.count()):
                if self.device_combo.itemData(index) == current_uid:
                    matched = True
                    if self.device_combo.currentIndex() != index:
                        self.device_combo.blockSignals(True)
                        self.device_combo.setCurrentIndex(index)
                        self.device_combo.blockSignals(False)
                    break
            if matched:
                return
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for card in self.controller.device_cards():
            self.device_combo.addItem(card["label"], card["uid"])
        if current_uid:
            for index in range(self.device_combo.count()):
                if self.device_combo.itemData(index) == current_uid:
                    self.device_combo.setCurrentIndex(index)
                    break
        self.device_combo.blockSignals(False)

    def _refresh_plot(self, rows, *, reset_view: bool) -> None:
        if not rows:
            self.co2_curve.setData([], [])
            self.h2o_curve.setData([], [])
            self.pressure_curve.setData([], [])
            return

        start_time = rows[0].timestamp
        xs = np.array([(row.timestamp - start_time).total_seconds() for row in rows], dtype=float)
        co2 = np.array([row.co2_ppm if row.co2_ppm is not None else np.nan for row in rows], dtype=float)
        h2o = np.array([row.h2o_mmol if row.h2o_mmol is not None else np.nan for row in rows], dtype=float)
        pressure = np.array([row.pressure_kpa if row.pressure_kpa is not None else np.nan for row in rows], dtype=float)
        self.co2_curve.setData(xs, co2)
        self.h2o_curve.setData(xs, h2o)
        self.pressure_curve.setData(xs, pressure)
        self._update_metric_visibility()
        if reset_view:
            self._reset_view()

    def _refresh_events(self) -> None:
        self.event_list.clear()
        entry = self.controller.selected_device()
        if entry is None:
            return
        for event in self.controller.recent_events(device_uid=entry.config.uid, limit=24):
            item = QListWidgetItem(f"[{event.created_at:%H:%M:%S}] {event.title} · {event.message}")
            item.setData(Qt.UserRole, event)
            self.event_list.addItem(item)

    def _refresh_frames(self) -> None:
        self.frame_list.clear()
        entry = self.controller.selected_device()
        if entry is None:
            return
        frames = self.controller.recent_raw_frames(device_uid=entry.config.uid, limit=24)
        for frame in frames:
            item = QListWidgetItem(f"[{frame.received_at:%H:%M:%S}] {frame.quality.value} · {frame.summary()}")
            item.setData(Qt.UserRole, frame)
            self.frame_list.addItem(item)
        if frames:
            self._set_frame_detail(frames[0])
        else:
            self.parsed_text.setPlainText("暂无解析结果。")
            self.raw_text.setPlainText("暂无原始帧。")

    def _set_frame_detail(self, frame) -> None:
        import json

        self.parsed_text.setPlainText(json.dumps(frame.parsed, ensure_ascii=False, indent=2) if frame.parsed else "当前帧没有可展示的解析结果。")
        self.raw_text.setPlainText(frame.raw_text or "当前帧没有原始内容。")

    def _update_metric_visibility(self) -> None:
        visible = {
            "co2": self.metric_buttons["co2"].isChecked(),
            "h2o": self.metric_buttons["h2o"].isChecked(),
            "pressure": self.metric_buttons["pressure"].isChecked(),
        }
        self.co2_plot.setVisible(visible["co2"])
        self.h2o_plot.setVisible(visible["h2o"])
        self.pressure_plot.setVisible(visible["pressure"])

    def _on_mouse_moved(self, event) -> None:
        if not self._plot_rows:
            return
        pos = event[0]
        view_box = self.co2_plot.vb
        if not self.co2_plot.sceneBoundingRect().contains(pos):
            if not self.h2o_plot.sceneBoundingRect().contains(pos) and not self.pressure_plot.sceneBoundingRect().contains(pos):
                return
            target_plot = self.h2o_plot if self.h2o_plot.sceneBoundingRect().contains(pos) else self.pressure_plot
            point = target_plot.vb.mapSceneToView(pos)
        else:
            point = view_box.mapSceneToView(pos)

        x_value = max(0.0, float(point.x()))
        start_time = self._plot_rows[0].timestamp
        xs = np.array([(row.timestamp - start_time).total_seconds() for row in self._plot_rows], dtype=float)
        index = int(np.clip(np.searchsorted(xs, x_value), 0, len(xs) - 1))
        row = self._plot_rows[index]
        actual_x = xs[index]
        for line in self.crosshair_lines.values():
            line.setPos(actual_x)
        self.hover_label.setText(
            f"时间 {row.timestamp:%H:%M:%S} · CO2 {row.co2_ppm:.2f} ppm · "
            f"H2O {row.h2o_mmol:.2f} mmol · 压力 {row.pressure_kpa:.2f} kPa"
        )

    def _on_device_changed(self, _index: int) -> None:
        uid = self.device_combo.currentData()
        if uid:
            self.controller.select_device(uid)

    def _start_capture(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "未选择设备", "请先选择设备，再开始采集。")
            return
        try:
            if not entry.runtime.connected:
                self.controller.connect_device(entry.config.uid)
            self.display_paused = False
            self.pause_button.setChecked(False)
            self.pause_button.setText("暂停")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "开始失败", str(exc))

    def _toggle_pause(self) -> None:
        self.display_paused = self.pause_button.isChecked()
        self.pause_button.setText("恢复" if self.display_paused else "暂停")
        if not self.display_paused:
            self.refresh()

    def _mark_anomaly(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "未选择设备", "请先选择设备，再标记异常。")
            return
        note, ok = QInputDialog.getText(self, "标记异常", "请输入异常说明：")
        if not ok:
            return
        self.controller.mark_anomaly(entry.config.uid, note)
        self.refresh()

    def _export_segment(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "未选择设备", "请先选择设备，再导出片段。")
            return
        default = Path(self.controller.runtime_root) / "exports" / f"{entry.config.label}_segment.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出片段", str(default), "CSV Files (*.csv)")
        if not path:
            return
        try:
            result = self.controller.export_realtime_segment(
                Path(path),
                device_uid=entry.config.uid,
                seconds=self.current_window_seconds(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"时间窗片段已导出到：\n{result}")

    def _clear_selected_buffer(self) -> None:
        entry = self.controller.selected_device()
        if entry is None:
            QMessageBox.information(self, "未选择设备", "请先选择设备，再清空显示。")
            return
        self.controller.clear_realtime_buffer(device_uid=entry.config.uid)
        self.refresh()

    def _reset_view(self) -> None:
        if not self._plot_rows:
            return
        xs = [(row.timestamp - self._plot_rows[0].timestamp).total_seconds() for row in self._plot_rows]
        if not xs:
            return
        self.co2_plot.setXRange(min(xs), max(xs), padding=0.02)
        self.h2o_plot.setXRange(min(xs), max(xs), padding=0.02)
        self.pressure_plot.setXRange(min(xs), max(xs), padding=0.02)
        self.co2_plot.enableAutoRange(axis="y", enable=True)
        self.h2o_plot.enableAutoRange(axis="y", enable=True)
        self.pressure_plot.enableAutoRange(axis="y", enable=True)

    def _focus_event(self, item: QListWidgetItem) -> None:
        event = item.data(Qt.UserRole)
        if event is None or event.related_timestamp is None or not self._plot_rows:
            return
        start = self._plot_rows[0].timestamp
        x_value = (event.related_timestamp - start).total_seconds()
        window = max(5.0, self.current_window_seconds() / 8.0)
        for plot in (self.co2_plot, self.h2o_plot, self.pressure_plot):
            plot.setXRange(max(0.0, x_value - window), x_value + window, padding=0.02)
        self.hover_label.setText(f"已定位到事件时间点：{event.related_timestamp:%H:%M:%S} · {event.message}")

    def _show_frame_detail(self, item: QListWidgetItem) -> None:
        frame = item.data(Qt.UserRole)
        if frame is None:
            return
        self._set_frame_detail(frame)
