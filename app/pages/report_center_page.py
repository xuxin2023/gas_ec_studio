from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, PLOT_SERIES_COLORS, TOKENS, chip, configure_plot_theme, section_title
from app.ui_text import ui_safe_text as _ui_safe_text


REPORT_SECTIONS = [
    ("run_summary", "运行摘要", "适合第一眼确认本批次是否能交付。"),
    ("device_status", "设备状态报告", "把设备稳定性结论沉淀成报告视图。"),
    ("acquisition_quality", "采集质量报告", "用帧率、完整率和残余异常证明采集链路质量。"),
    ("ec_results", "EC 结果报告", "集中查看主结果、诊断字段和导出结构。"),
    ("spectral_qc", "谱修正与 QC 报告", "从谱修正和 QC 角度解释窗口质量。"),
    ("anomaly_events", "异常事件报告", "把日志与事件整理成可汇报的异常视图。"),
    ("site_method", "站点方法说明", "作为正式报告附录，说明结论来自哪些方法配置。"),
    ("evidence_pack", "证据包", "统一导出图表、表格与日志证据。"),
    ("fixture_pack", "验证包", "验证行业参考集、raw-to-final readiness、合成回归集与 YGAS 协议样例。"),
    ("eddypro_compare", "行业参考对标报告", "集中查看当前结果与行业参考结果的对标摘要和窗口差异。"),
    ("benchmark_cockpit", "基准驾驶舱", "查看参考对标结果：通过率、阈值、偏差详情。"),
    ("method_provenance", "方法溯源", "查看 Footprint、不确定度、谱修正的方法来源、局限性和溯源信息。"),
    ("method_compare", "方法对比", "查看方法族对比、参考方法 parity matrix、2D footprint contour 与长窗口性能 profile。"),
    ("computation_surface", "计算能力面板", "查看行业参考计算核心族 ready/blocked 状态、stress suite 与声明边界。"),
]


class ReportCenterPage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("pageSurface", True)
        self.controller = controller
        self.report_items: dict[str, QTreeWidgetItem] = {}
        self.delivery_rail_mode_buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "报告中心",
                "集中查看处理结果、诊断结论、导出文件和运行批次对比。",
            )
        )

        self.filter_bar = self._build_filter_bar()
        layout.addWidget(self.filter_bar)
        self.report_command_deck = self._build_report_command_deck()
        layout.addWidget(self.report_command_deck)

        workbench = QSplitter(Qt.Horizontal)
        workbench.setChildrenCollapsible(False)
        workbench.setObjectName("reportWorkbench")
        layout.addWidget(workbench, 1)

        self.tree_card = CardFrame(muted=True, role="rail")
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_md)
        tree_layout.addWidget(section_title("报告目录", "按使用场景组织目录，让预览更像真正的报告中心。"))
        self.report_tree = QTreeWidget()
        self.report_tree.setObjectName("workflowTree")
        self.report_tree.setHeaderHidden(True)
        self.report_tree.setIndentation(10)
        self.report_tree.itemSelectionChanged.connect(self._on_report_changed)
        tree_layout.addWidget(self.report_tree, 1)
        self.tree_card.setMinimumWidth(210)
        self.tree_card.setMaximumWidth(280)
        workbench.addWidget(self.tree_card)

        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setMinimumWidth(500)
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(TOKENS.spacing_md)
        center_layout.setAlignment(Qt.AlignTop)
        center_scroll.setWidget(center_container)
        workbench.addWidget(center_scroll)

        self.preview_header_card = CardFrame(role="cockpit")
        preview_header_layout = QVBoxLayout(self.preview_header_card)
        preview_header_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        preview_header_layout.setSpacing(TOKENS.spacing_sm)
        self.preview_mode_chip = chip("工程诊断", "accent")
        preview_header_layout.addWidget(self.preview_mode_chip)
        self.preview_title_label = QLabel("--")
        self.preview_title_label.setObjectName("pageTitle")
        self.preview_title_label.setWordWrap(True)
        preview_header_layout.addWidget(self.preview_title_label)
        self.preview_source_label = QLabel("--")
        self.preview_source_label.setObjectName("subtitle")
        self.preview_source_label.setWordWrap(True)
        preview_header_layout.addWidget(self.preview_source_label)
        center_layout.addWidget(self.preview_header_card)

        self.preview_deck_card = CardFrame(muted=True, role="rail")
        self.preview_deck_card.setProperty("deckRole", "reportPreviewDeck")
        self.preview_deck_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        preview_deck_layout = QVBoxLayout(self.preview_deck_card)
        preview_deck_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_deck_layout.setSpacing(TOKENS.spacing_md)
        preview_deck_layout.addWidget(
            section_title(
                "报告预览台",
                "KPI、图表和支撑表格集中在一起，让中间区像交付驾驶舱一样阅读。",
            )
        )

        self.preview_metrics_row = QWidget()
        metrics_layout = QGridLayout(self.preview_metrics_row)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setHorizontalSpacing(TOKENS.spacing_md)
        metrics_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.preview_metric_values: list[QLabel] = []
        self.preview_metric_labels: list[QLabel] = []
        self.preview_metric_cards: list[CardFrame] = []
        for index in range(4):
            card = CardFrame(muted=True, role="tile")
            card.setMinimumHeight(74)
            card.setMaximumHeight(96)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            card_layout.setSpacing(TOKENS.spacing_xs)
            title = QLabel("--")
            title.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            self.preview_metric_labels.append(title)
            self.preview_metric_values.append(value)
            self.preview_metric_cards.append(card)
            metrics_layout.addWidget(card, 0, index)
        preview_deck_layout.addWidget(self.preview_metrics_row)

        self.preview_delivery_trail_card = CardFrame(muted=True, role="console")
        trail_layout = QVBoxLayout(self.preview_delivery_trail_card)
        trail_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        trail_layout.setSpacing(TOKENS.spacing_sm)
        trail_header = QHBoxLayout()
        trail_header.setContentsMargins(0, 0, 0, 0)
        trail_header.addWidget(section_title("交付线索", "把当前报告、批次、来源和更新时间固定在预览区顶部。"))
        trail_header.addStretch(1)
        self.preview_delivery_trail_chip = chip("同步", "accent")
        trail_header.addWidget(self.preview_delivery_trail_chip)
        trail_layout.addLayout(trail_header)
        self.preview_delivery_trail_value = QLabel("--")
        self.preview_delivery_trail_value.setObjectName("metricValue")
        self.preview_delivery_trail_value.setProperty("compactMetric", True)
        self.preview_delivery_trail_value.setWordWrap(True)
        self.preview_delivery_trail_note = QLabel("--")
        self.preview_delivery_trail_note.setObjectName("subtitle")
        self.preview_delivery_trail_note.setWordWrap(True)
        trail_layout.addWidget(self.preview_delivery_trail_value)
        trail_layout.addWidget(self.preview_delivery_trail_note)
        preview_deck_layout.addWidget(self.preview_delivery_trail_card)

        self.expert_review_card = CardFrame(muted=True, role="console")
        self.expert_review_card.setProperty("deckRole", "expertReviewStrip")
        self.expert_review_card.setMaximumHeight(132)
        expert_layout = QVBoxLayout(self.expert_review_card)
        expert_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        expert_layout.setSpacing(TOKENS.spacing_sm)
        expert_header = QHBoxLayout()
        expert_header.setContentsMargins(0, 0, 0, 0)
        expert_header.addWidget(section_title("专家审阅摘要", "把方法、artifact、性能和声明边界压成一行审计卡。"))
        expert_header.addStretch(1)
        self.expert_review_chip = chip("审阅", "accent")
        expert_header.addWidget(self.expert_review_chip)
        expert_layout.addLayout(expert_header)
        expert_grid = QGridLayout()
        expert_grid.setContentsMargins(0, 0, 0, 0)
        expert_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        expert_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.expert_review_tiles: list[CardFrame] = []
        self.expert_review_labels: list[QLabel] = []
        self.expert_review_values: list[QLabel] = []
        self.expert_review_notes: list[QLabel] = []
        for index in range(4):
            tile = CardFrame(muted=True, role="tile")
            tile.setMaximumHeight(66)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(1)
            label = QLabel("--")
            label.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(False)
            note = QLabel("--")
            note.setObjectName("subtitle")
            note.setWordWrap(False)
            tile_layout.addWidget(label)
            tile_layout.addWidget(value)
            tile_layout.addWidget(note)
            self.expert_review_tiles.append(tile)
            self.expert_review_labels.append(label)
            self.expert_review_values.append(value)
            self.expert_review_notes.append(note)
            expert_grid.addWidget(tile, 0, index)
        expert_layout.addLayout(expert_grid)
        self.expert_review_card.setVisible(False)
        preview_deck_layout.addWidget(self.expert_review_card)

        self.preview_content_card = CardFrame(role="panel")
        self.preview_content_card.setProperty("deckRole", "compactPreviewPane")
        content_layout = QVBoxLayout(self.preview_content_card)
        content_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        content_layout.setSpacing(TOKENS.spacing_sm)
        content_layout.setAlignment(Qt.AlignTop)
        content_layout.addWidget(section_title("图表或表格预览", "让结果预览像报告，而不是文件清单。"))
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setMinimumHeight(190)
        self.preview_plot.setMaximumHeight(260)
        configure_plot_theme(self.preview_plot, left_label="指标", bottom_label="序列")
        self.preview_curve = self.preview_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.2))
        content_layout.addWidget(self.preview_plot)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setMaximumHeight(150)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        content_layout.addWidget(self.preview_table)
        self.preview_plot_note = QLabel("--")
        self.preview_plot_note.setObjectName("subtitle")
        self.preview_plot_note.setWordWrap(True)
        content_layout.addWidget(self.preview_plot_note)
        preview_deck_layout.addWidget(self.preview_content_card)
        center_layout.addWidget(self.preview_deck_card)

        self.closure_deck_card = CardFrame(muted=True, role="rail")
        closure_deck_layout = QVBoxLayout(self.closure_deck_card)
        closure_deck_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        closure_deck_layout.setSpacing(TOKENS.spacing_md)
        closure_header = QHBoxLayout()
        closure_header.setContentsMargins(0, 0, 0, 0)
        closure_header.addWidget(
            section_title(
                "闭环路线",
                "结论文本和启动路线放在一起，让报告中心始终显示下一步闭环动作。",
            )
        )
        closure_header.addStretch(1)
        self.closure_deck_chip = chip("下一步", "warning")
        closure_header.addWidget(self.closure_deck_chip)
        closure_deck_layout.addLayout(closure_header)

        self.conclusion_card = CardFrame(muted=True, role="panel")
        conclusion_layout = QVBoxLayout(self.conclusion_card)
        conclusion_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        conclusion_layout.setSpacing(TOKENS.spacing_md)
        conclusion_layout.addWidget(section_title("关键结论说明", "操作员看结论，工程师看细节，管理层看可以直接汇报的话术。"))
        self.conclusion_content = QVBoxLayout()
        self.conclusion_content.setSpacing(TOKENS.spacing_sm)
        conclusion_layout.addLayout(self.conclusion_content)
        closure_deck_layout.addWidget(self.conclusion_card)
        self.empty_state_card = self._build_empty_state_card()
        closure_deck_layout.addWidget(self.empty_state_card)
        center_layout.addWidget(self.closure_deck_card)
        center_layout.addStretch(1)

        self.delivery_rail = CardFrame(muted=True, role="rail")
        self.delivery_rail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        delivery_layout = QVBoxLayout(self.delivery_rail)
        delivery_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        delivery_layout.setSpacing(TOKENS.spacing_sm)
        delivery_title = section_title(
            "交付驾驶舱",
            "浏览报告时持续显示交付门槛、导出状态、方法溯源和批次差异。",
        )
        delivery_title.setMaximumHeight(42)
        delivery_layout.addWidget(delivery_title)

        self.delivery_rail_inspector = CardFrame(role="panel")
        self.delivery_rail_inspector.setProperty("deckRole", "deliveryRailInspector")
        self.delivery_rail_inspector.setMinimumWidth(0)
        self.delivery_rail_inspector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rail_inspector_layout = QVBoxLayout(self.delivery_rail_inspector)
        rail_inspector_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_sm)
        rail_inspector_layout.setSpacing(TOKENS.spacing_xs)

        rail_mode_row = QHBoxLayout()
        rail_mode_row.setContentsMargins(0, 0, 0, 0)
        rail_mode_row.setSpacing(TOKENS.spacing_xs)
        for mode, text in (
            ("summary", "摘要"),
            ("delivery", "交付"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_delivery_rail_mode(key))
            self.delivery_rail_mode_buttons[mode] = button
            rail_mode_row.addWidget(button)
        rail_mode_row.addStretch(1)
        rail_inspector_layout.addLayout(rail_mode_row)

        self.delivery_rail_stack = QStackedWidget()
        self.delivery_rail_stack.setMinimumWidth(0)
        self.delivery_rail_stack.setProperty("stackRole", "deliveryRailInspectorStack")
        self.delivery_rail_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary_row = self._build_summary_row()
        self.delivery_rail_stack.addWidget(self.summary_row)

        self.delivery_focus_card = CardFrame(muted=True, role="panel")
        self.delivery_focus_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        focus_layout = QVBoxLayout(self.delivery_focus_card)
        focus_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_sm)
        focus_layout.setSpacing(TOKENS.spacing_xs)
        focus_title = section_title("交付聚焦", "在交付门槛、导出详情和批次对比之间切换，不拉长右侧栏。")
        focus_title.setVisible(False)
        focus_layout.addWidget(focus_title)
        focus_switch_row = QHBoxLayout()
        focus_switch_row.setContentsMargins(0, 0, 0, 0)
        focus_switch_row.setSpacing(TOKENS.spacing_xs)
        self.delivery_focus_buttons: dict[str, QToolButton] = {}
        for key, text in (
            ("gate", "门槛"),
            ("details", "详情"),
            ("batch", "批次"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, section=key: self._show_delivery_focus(section))
            self.delivery_focus_buttons[key] = button
            focus_switch_row.addWidget(button)
        focus_switch_row.addStretch(1)
        focus_layout.addLayout(focus_switch_row)
        self.delivery_focus_stack = QStackedWidget()
        self.delivery_focus_stack.setProperty("stackRole", "compactDeliveryInspector")
        self.delivery_focus_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        focus_layout.addWidget(self.delivery_focus_stack)
        self.delivery_rail_stack.addWidget(self.delivery_focus_card)
        rail_inspector_layout.addWidget(self.delivery_rail_stack)
        delivery_layout.addWidget(self.delivery_rail_inspector, 1)

        self.delivery_gate_card = self._build_delivery_gate_card()
        self.delivery_focus_stack.addWidget(self.delivery_gate_card)

        self.inner_inspector = CardFrame(muted=True, role="panel")
        inspector_layout = QVBoxLayout(self.inner_inspector)
        inspector_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        inspector_layout.setSpacing(TOKENS.spacing_md)
        inspector_layout.addWidget(section_title("交付详情", "导出、文件、版本和使用建议用分段面板收纳，减少右侧长页面。"))

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(TOKENS.spacing_xs)
        self.inspector_switches: dict[str, QToolButton] = {}
        for key, text in (
            ("export", "导出"),
            ("file", "文件"),
            ("version", "版本"),
            ("usage", "建议"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, section=key: self._show_inspector_section(section))
            self.inspector_switches[key] = button
            switch_row.addWidget(button)
        switch_row.addStretch(1)
        inspector_layout.addLayout(switch_row)

        self.inspector_stack = QStackedWidget()

        self.export_card, self.export_content = self._inspector_card("导出选项", "把当前报告的导出方式和出口统一放在这里。")
        self.file_card, self.file_content = self._inspector_card("文件信息", "不只显示路径，还要说明状态和用途。")
        self.version_card, self.version_content = self._inspector_card("版本与来源", "说明模板版本、来源批次和方法依据。")
        self.usage_card, self.usage_content = self._inspector_card("使用建议", "按操作员、工程师、管理汇报三个场景给出建议。")
        self.inspector_sections = {
            "export": self.export_card,
            "file": self.file_card,
            "version": self.version_card,
            "usage": self.usage_card,
        }
        for card in self.inspector_sections.values():
            self.inspector_stack.addWidget(card)
        inspector_layout.addWidget(self.inspector_stack)
        self._show_inspector_section("export")
        self.delivery_focus_stack.addWidget(self.inner_inspector)

        self.batch_card = CardFrame(muted=True, role="panel")
        batch_layout = QVBoxLayout(self.batch_card)
        batch_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        batch_layout.setSpacing(TOKENS.spacing_md)
        batch_layout.addWidget(section_title("批次对比", "统一展示当前批次、对比批次和差异摘要。"))
        batch_grid = QGridLayout()
        batch_grid.setContentsMargins(0, 0, 0, 0)
        batch_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        batch_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.batch_current_value = QLabel("--")
        self.batch_compare_value = QLabel("--")
        self.batch_diff_value = QLabel("--")
        batch_grid.addWidget(self._metric_card("当前批次", self.batch_current_value), 0, 0)
        batch_grid.addWidget(self._metric_card("对比批次", self.batch_compare_value), 0, 1)
        batch_grid.addWidget(self._metric_card("差异摘要", self.batch_diff_value), 1, 0, 1, 2)
        batch_layout.addLayout(batch_grid)
        self.batch_summary_layout = QVBoxLayout()
        self.batch_summary_layout.setSpacing(TOKENS.spacing_sm)
        batch_layout.addLayout(self.batch_summary_layout)
        self.delivery_focus_stack.addWidget(self.batch_card)
        self.delivery_focus_sections = {
            "gate": self.delivery_gate_card,
            "details": self.inner_inspector,
            "batch": self.batch_card,
        }
        self.delivery_rail_sections = {
            "summary": self.summary_row,
            "delivery": self.delivery_focus_card,
        }
        self._show_delivery_rail_mode("summary")
        self._show_delivery_focus("gate")
        delivery_layout.addStretch(1)
        self.delivery_rail.setMinimumWidth(280)
        self.delivery_rail.setMaximumWidth(360)
        workbench.addWidget(self.delivery_rail)
        workbench.setSizes([230, 720, 310])

        self._build_tree()

        self.controller.report_changed.connect(self.refresh)
        self.controller.project_changed.connect(self.refresh)
        self.controller.processing_changed.connect(self.refresh)
        self.controller.spectral_qc_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        workspace = self.controller.report_center_workspace
        filters = workspace["filters"]
        summary = workspace["summary"]

        self._refresh_filter_options(workspace)
        self._set_combo_text(self.project_combo, str(filters.get("project", self.controller.project_profile.name or "当前项目")))
        self._set_combo_text(self.batch_combo, str(filters.get("batch", "")))
        self._set_combo_text(self.view_mode_combo, self._normalize_view_mode(str(filters.get("view_mode", "工程诊断"))))

        self._set_summary_metric(self.recent_status_value, summary.get("recent_status", "--"))
        self._set_summary_metric(self.exportable_count_value, summary.get("exportable_reports", "--"))
        self._set_summary_metric(self.attention_count_value, summary.get("attention_count", "--"))
        self._set_summary_metric(self.last_generated_value, summary.get("last_generated_at", "--"))

        self._set_chip(self.summary_chips["recent_status"], "运行就绪", "success")
        self._set_chip(self.summary_chips["exportable"], "可导出", "accent")
        attention_tone = "warning" if int(summary.get("attention_count", 0)) > 0 else "success"
        self._set_chip(self.summary_chips["attention"], "需要复核" if attention_tone == "warning" else "风险受控", attention_tone)
        self._set_chip(self.summary_chips["generated"], "已更新", "accent")

        selected_report = str(workspace.get("selected_report", "run_summary"))
        self._sync_tree(selected_report)
        report = workspace["reports"][selected_report]
        view_mode = self._normalize_view_mode(str(filters.get("view_mode", "工程诊断")))
        self._refresh_preview(report, view_mode, filters)
        export_status = str(workspace.get("export_status", "尚未导出"))
        self._refresh_inner_inspector(report, export_status, view_mode)
        self._refresh_delivery_gate(workspace, report, export_status)
        self._refresh_report_command_deck(workspace, report, export_status)
        self._refresh_empty_state(workspace, report, export_status)
        self._refresh_batch_compare(workspace.get("batch_compare", {}))
        self._sanitize_visible_labels()

    def _build_filter_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("报告筛选", "从真实项目与运行批次驱动预览、导出和交付检查。"))
        layout.addStretch(1)

        self.project_combo = QComboBox()
        self.project_combo.setEditable(True)
        self.batch_combo = QComboBox()
        self.batch_combo.setEditable(True)
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["操作汇总", "工程诊断", "管理汇报"])

        layout.addWidget(QLabel("项目"))
        layout.addWidget(self.project_combo)
        layout.addWidget(QLabel("运行批次"))
        layout.addWidget(self.batch_combo)
        layout.addWidget(QLabel("视图"))
        layout.addWidget(self.view_mode_combo)

        buttons = [
            ("刷新", self._refresh_workspace, False),
            ("生成报告", self._generate_report, True),
            ("导出报告", self._export_current_report, False),
            ("导出证据包", self._export_evidence, False),
            ("对比批次", self._compare_batches, False),
        ]
        for text, callback, primary in buttons:
            button = QPushButton(text)
            if primary:
                button.setProperty("variant", "primary")
            button.clicked.connect(callback)
            layout.addWidget(button)

        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        self.batch_combo.currentTextChanged.connect(self._on_batch_changed)
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode_changed)
        return card

    def _build_report_command_deck(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        card.setProperty("deckRole", "reportCommandDeck")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        card.setMaximumHeight(124)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        intro = QVBoxLayout()
        intro.setSpacing(TOKENS.spacing_xs)
        intro.addWidget(section_title("交付总控", "报告、门槛、网络、对标、方法和导出状态固定在首屏。"))
        self.report_command_chip = chip("待生成", "warning")
        intro.addWidget(self.report_command_chip)
        layout.addLayout(intro)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        self.report_command_tiles: dict[str, CardFrame] = {}
        self.report_command_values: dict[str, QLabel] = {}
        self.report_command_notes: dict[str, QLabel] = {}
        self.report_command_chips: dict[str, QLabel] = {}
        items = [
            ("report", "报告"),
            ("gate", "门槛"),
            ("network", "网络"),
            ("benchmark", "对标"),
            ("methods", "方法"),
            ("export", "导出"),
        ]
        for index, (key, title) in enumerate(items):
            grid.addWidget(self._report_command_tile(key, title), index // 3, index % 3)
        layout.addLayout(grid, 1)
        return card

    def _report_command_tile(self, key: str, title: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("commandKey", key)
        tile.setMinimumHeight(48)
        tile.setMaximumHeight(58)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(1)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        label = QLabel(_ui_safe_text(title))
        label.setObjectName("metricLabel")
        status_chip = chip("待检查", "warning")
        top.addWidget(label)
        top.addStretch(1)
        top.addWidget(status_chip)
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setProperty("compactMetric", True)
        value.setWordWrap(False)
        note = QLabel("--")
        note.setObjectName("subtitle")
        note.setWordWrap(False)
        layout.addLayout(top)
        layout.addWidget(value)
        layout.addWidget(note)
        self.report_command_tiles[key] = tile
        self.report_command_values[key] = value
        self.report_command_notes[key] = note
        self.report_command_chips[key] = status_chip
        return tile

    def _build_summary_row(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setMaximumHeight(42)
        wrapper.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(TOKENS.spacing_sm)

        self.recent_status_value = QLabel("--")
        self.exportable_count_value = QLabel("--")
        self.attention_count_value = QLabel("--")
        self.last_generated_value = QLabel("--")
        self.summary_chips: dict[str, QLabel] = {}
        self.summary_cards: dict[str, CardFrame] = {}
        cards = [
            ("recent_status", "最近运行状态", self.recent_status_value),
            ("exportable", "可导出报告数量", self.exportable_count_value),
            ("attention", "待关注异常数量", self.attention_count_value),
            ("generated", "最近生成时间", self.last_generated_value),
        ]
        for index, (key, title, value) in enumerate(cards):
            card = CardFrame(muted=True, role="tile")
            card.setMinimumHeight(36)
            card.setMaximumHeight(40)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            card_layout.setSpacing(1)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            card_layout.addWidget(label)
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            value.setMaximumHeight(20)
            card_layout.addWidget(value)
            tone_chip = chip("就绪", "accent" if index != 2 else "warning")
            tone_chip.setMaximumHeight(20)
            tone_chip.setVisible(False)
            self.summary_chips[key] = tone_chip
            card_layout.addWidget(tone_chip)
            self.summary_cards[key] = card
            layout.addWidget(card, 0, index)
        return wrapper

    def _build_empty_state_card(self) -> CardFrame:
        card = CardFrame(muted=True, role="cockpit")
        card.setProperty("deckRole", "launchActionDeck")
        card.setMaximumHeight(228)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(section_title("启动路线", "还没有真实运行结果时，直接从这里闭合采集、报告、导出和验证包。"))
        header.addStretch(1)
        self.empty_state_chip = chip("待运行", "warning")
        header.addWidget(self.empty_state_chip)
        layout.addLayout(header)

        self.empty_state_gap_label = QLabel("--")
        self.empty_state_gap_label.setObjectName("subtitle")
        self.empty_state_gap_label.setWordWrap(True)
        self.empty_state_gap_label.setMaximumHeight(46)
        layout.addWidget(self.empty_state_gap_label)

        self.empty_state_next_card = CardFrame(muted=True, role="console")
        self.empty_state_next_card.setProperty("deckRole", "launchNextActionHero")
        self.empty_state_next_card.setMaximumHeight(58)
        next_layout = QVBoxLayout(self.empty_state_next_card)
        next_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        next_layout.setSpacing(TOKENS.spacing_xs)
        self.empty_state_next_value = QLabel("先运行处理")
        self.empty_state_next_value.setObjectName("metricValue")
        self.empty_state_next_value.setProperty("compactMetric", True)
        self.empty_state_next_note = QLabel("从当前高频缓存生成窗口、RP 结果和后续可导出报告。")
        self.empty_state_next_note.setObjectName("subtitle")
        self.empty_state_next_note.setWordWrap(True)
        next_layout.addWidget(self.empty_state_next_value)
        next_layout.addWidget(self.empty_state_next_note)
        layout.addWidget(self.empty_state_next_card)

        route_grid = QGridLayout()
        route_grid.setContentsMargins(0, 0, 0, 0)
        route_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        route_grid.setVerticalSpacing(TOKENS.spacing_sm)
        actions = [
            ("1", "运行 EC 处理", "从当前高频缓存生成真实窗口和 RP 结果。", "运行处理", self._run_ec_processing_from_report_center),
            ("2", "生成报告", "把最新运行结果同步到报告中心和右侧交付门槛。", "生成报告", self._generate_report),
            ("3", "导出交付包", "写出报告、manifest、网络校验和证据文件。", "导出", self._export_current_report),
            ("4", "检查验证包", "打开验证包页，注册或审计行业参考 raw-to-final 证据。", "打开验证包", self._open_fixture_pack_report),
        ]
        self.empty_state_action_buttons: dict[str, QPushButton] = {}
        for index, (number, title, note, button_text, callback) in enumerate(actions):
            route_grid.addWidget(
                self._empty_state_action_tile(number, title, note, button_text, callback),
                0,
                index,
            )
        layout.addLayout(route_grid)
        return card

    def _empty_state_action_tile(
        self,
        number: str,
        title: str,
        note: str,
        button_text: str,
        callback,
    ) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("routeAction", True)
        tile.setMinimumHeight(56)
        tile.setMaximumHeight(66)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        tile_layout.setSpacing(1)
        label = QLabel(_ui_safe_text(f"{number}. {title}"))
        label.setObjectName("metricLabel")
        label.setWordWrap(True)
        label.setToolTip(_ui_safe_text(note))
        button = QPushButton(_ui_safe_text(button_text))
        button.setMaximumHeight(24)
        button.setToolTip(_ui_safe_text(note))
        button.clicked.connect(callback)
        self.empty_state_action_buttons[button_text] = button
        tile_layout.addWidget(label)
        tile_layout.addWidget(button)
        return tile

    def _build_delivery_gate_card(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        card.setProperty("deckRole", "deliveryGateMatrix")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(TOKENS.spacing_xs)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        gate_title = QLabel("门槛矩阵")
        gate_title.setObjectName("metricLabel")
        gate_title.setToolTip("把交付前必须一致的状态压缩成一个检查矩阵。")
        header.addWidget(gate_title)
        header.addStretch(1)
        self.delivery_gate_chip = chip("待生成", "warning")
        header.addWidget(self.delivery_gate_chip)
        layout.addLayout(header)

        self.delivery_gate_hero_card = CardFrame(muted=True, role="console")
        self.delivery_gate_hero_card.setProperty("deckRole", "deliveryReadinessHero")
        self.delivery_gate_hero_card.setMinimumHeight(32)
        self.delivery_gate_hero_card.setMaximumHeight(36)
        hero_layout = QVBoxLayout(self.delivery_gate_hero_card)
        hero_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        hero_layout.setSpacing(1)
        hero_top = QHBoxLayout()
        hero_top.setContentsMargins(0, 0, 0, 0)
        self.delivery_gate_ready_label = QLabel("交付状态")
        self.delivery_gate_ready_label.setObjectName("metricLabel")
        hero_top.addWidget(self.delivery_gate_ready_label)
        hero_top.addStretch(1)
        self.delivery_gate_progress_badge = chip("--", "warning")
        self.delivery_gate_progress_badge.setAlignment(Qt.AlignCenter)
        hero_top.addWidget(self.delivery_gate_progress_badge)
        hero_layout.addLayout(hero_top)
        self.delivery_gate_ready_value = QLabel("--")
        self.delivery_gate_ready_value.setObjectName("metricValue")
        self.delivery_gate_ready_value.setProperty("compactMetric", True)
        self.delivery_gate_ready_value.setWordWrap(True)
        self.delivery_gate_ready_note = QLabel("--")
        self.delivery_gate_ready_note.setObjectName("subtitle")
        self.delivery_gate_ready_note.setWordWrap(True)
        self.delivery_gate_ready_note.setMaximumHeight(30)
        self.delivery_gate_ready_note.setVisible(False)
        hero_layout.addWidget(self.delivery_gate_ready_value)
        hero_layout.addWidget(self.delivery_gate_ready_note)
        layout.addWidget(self.delivery_gate_hero_card)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_xs)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        for row in range(2):
            grid.setRowMinimumHeight(row, 24)
        for column in range(3):
            grid.setColumnMinimumWidth(column, 72)
        self.delivery_gate_values: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        self.delivery_gate_tiles: dict[str, CardFrame] = {}
        gate_items = [
            ("report", "报告", "当前预览是否有真实内容"),
            ("export", "导出", "是否可导出或已经导出"),
            ("manifest", "清单", "交付清单是否落盘"),
            ("network", "网络", "schema 与缺失字段"),
            ("benchmark", "对标", "参考对标和失败字段"),
            ("methods", "方法", "三族方法溯源闭合"),
        ]
        for index, (key, title, hint) in enumerate(gate_items):
            grid.addWidget(self._delivery_gate_tile(key, title, hint), index // 3, index % 3)
        layout.addLayout(grid)

        self.delivery_gate_next_card = CardFrame(muted=True, role="tile")
        self.delivery_gate_next_card.setMaximumHeight(28)
        self.delivery_gate_next_card.setProperty("gateKey", "nextAction")
        next_layout = QHBoxLayout(self.delivery_gate_next_card)
        next_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        next_layout.setSpacing(TOKENS.spacing_xs)
        next_title = QLabel("下一步")
        next_title.setObjectName("metricLabel")
        self.delivery_gate_next_value = QLabel("--")
        self.delivery_gate_next_value.setObjectName("metricValue")
        self.delivery_gate_next_value.setProperty("compactMetric", True)
        self.delivery_gate_next_value.setWordWrap(True)
        self.delivery_gate_next_note = QLabel("--")
        self.delivery_gate_next_note.setObjectName("subtitle")
        self.delivery_gate_next_note.setWordWrap(True)
        self.delivery_gate_next_note.setMaximumHeight(24)
        self.delivery_gate_next_note.setVisible(False)
        next_layout.addWidget(next_title)
        next_layout.addStretch(1)
        next_layout.addWidget(self.delivery_gate_next_value)
        layout.addWidget(self.delivery_gate_next_card)
        return card

    def _delivery_gate_tile(self, key: str, title: str, hint: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("gateKey", key)
        tile.setMinimumHeight(22)
        tile.setMaximumHeight(24)
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(TOKENS.spacing_xs, TOKENS.spacing_xs, TOKENS.spacing_xs, TOKENS.spacing_xs)
        layout.setSpacing(0)
        title_label = QLabel(_ui_safe_text(title))
        title_label.setObjectName("metricLabel")
        status_chip = chip("检查", "warning")
        status_chip.setMaximumHeight(16)
        status_chip.setVisible(False)
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setProperty("compactMetric", True)
        value.setWordWrap(False)
        value.setMaximumHeight(18)
        note = QLabel(_ui_safe_text(hint))
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        note.setMaximumHeight(36)
        note.setVisible(False)
        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(value)
        self.delivery_gate_values[key] = (value, note, status_chip)
        self.delivery_gate_tiles[key] = tile
        return tile

    def _build_tree(self) -> None:
        root = QTreeWidgetItem(["报告中心目录"])
        root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
        self.report_tree.addTopLevelItem(root)
        for key, title, _subtitle in REPORT_SECTIONS:
            item = QTreeWidgetItem([_ui_safe_text(title)])
            item.setData(0, Qt.UserRole, key)
            item.setToolTip(0, _ui_safe_text(title))
            root.addChild(item)
            self.report_items[key] = item
        root.setExpanded(True)

    def _sync_tree(self, report_key: str) -> None:
        item = self.report_items.get(report_key)
        if item is None:
            return
        if self.report_tree.currentItem() is not item:
            self.report_tree.blockSignals(True)
            self.report_tree.setCurrentItem(item)
            self.report_tree.blockSignals(False)

    def _on_report_changed(self) -> None:
        item = self.report_tree.currentItem()
        if item is None:
            return
        report_key = item.data(0, Qt.UserRole)
        if not report_key:
            return
        self.controller.set_report_nav_section(report_key)

    def _on_project_changed(self, text: str) -> None:
        self.controller.report_center_workspace.setdefault("filters", {})["project"] = text.strip()
        self.controller.report_changed.emit()

    def _on_batch_changed(self, text: str) -> None:
        self.controller.set_report_batch_label(text.strip())
    def _on_view_mode_changed(self, text: str) -> None:
        self.controller.set_report_view_mode(text.strip())

    def _refresh_workspace(self) -> None:
        result = self.controller.refresh_report_center()
        self._show_info("已刷新", result["message"])

    def _run_ec_processing_from_report_center(self) -> None:
        result = self.controller.run_ec_processing()
        self._show_info("EC 处理", result.get("message", result))
        self.refresh()

    def _generate_report(self) -> None:
        result = self.controller.generate_report_center_report()
        self._show_info("报告已生成", result["message"])

    def _export_current_report(self) -> None:
        result = self.controller.export_current_report()
        self._show_info("导出完成", result["message"])

    def _export_evidence(self) -> None:
        result = self.controller.export_report_evidence()
        self._show_info("证据包已导出", result["message"])

    def _compare_batches(self) -> None:
        result = self.controller.compare_report_batches()
        self._show_info("批次对比已更新", result["message"])

    def _open_fixture_pack_report(self) -> None:
        self.controller.set_report_nav_section("fixture_pack")

    @staticmethod
    def _compact_report_source(source: object, *, max_chars: int = 56) -> str:
        text = _ui_safe_text(str(source or "--").strip() or "--")
        if text == "--":
            return text
        normalized = text.replace("\\", "/")
        is_path_like = "/" in normalized or "\\" in text or (len(text) > 1 and text[1] == ":")
        if not is_path_like and len(text) <= max_chars:
            return text
        if not is_path_like:
            return f"...{text[-max_chars + 3:]}"
        parts = [part for part in normalized.split("/") if part]
        if not parts:
            return text
        tail = parts[-1]
        if tail.lower() in {"results", "exports"} and len(parts) > 1:
            tail = f"{parts[-2]} / {tail}"
        return tail if len(tail) <= max_chars else f"...{tail[-max_chars + 3:]}"

    def _set_summary_metric(self, label: QLabel, value: object, *, max_chars: int = 9) -> None:
        raw = _ui_safe_text(str(value or "--").strip() or "--")
        display = raw
        if "尚未生成真实运行结果" in raw:
            display = "尚未生成"
        elif "最近批次已完成" in raw:
            display = "已完成"
        elif len(raw) >= 16 and raw[:4].isdigit() and "-" in raw[:10]:
            display = raw[5:16]
        elif len(raw) > max_chars:
            display = f"{raw[: max_chars - 1]}..."
        label.setText(display)
        label.setToolTip(raw)

    def _refresh_preview(self, report: dict, view_mode: str, filters: dict) -> None:
        self._set_chip(self.preview_mode_chip, view_mode, "accent")
        self.preview_title_label.setText(_ui_safe_text(report.get("title", "Report Preview")))
        raw_source = str(report.get("source", "--") or "--")
        source_display = self._compact_report_source(raw_source)
        self.preview_source_label.setText(
            _ui_safe_text(
                f"来源：{source_display}\n批次：{filters.get('batch', '--')}  |  时间：{report.get('updated_at', '--')}"
            )
        )
        self.preview_source_label.setToolTip(_ui_safe_text(raw_source))
        source = source_display
        batch = str(filters.get("batch", "--") or "--")
        updated_at = str(report.get("updated_at", "--") or "--")
        report_key = str(report.get("report_key", "--") or "--")
        self.preview_delivery_trail_value.setText(
            _ui_safe_text(f"{report.get('title', 'Report Preview')} · {view_mode}")
        )
        self.preview_delivery_trail_note.setText(
            _ui_safe_text(f"report={report_key} | source={source} | batch={batch} | updated={updated_at}")
        )
        self.preview_delivery_trail_note.setToolTip(_ui_safe_text(raw_source))

        is_expert_review = report_key in {"method_provenance", "method_compare", "computation_surface"}
        is_benchmark_cockpit = str(report.get("report_key", "")) == "benchmark_cockpit"
        is_fixture_pack = str(report.get("report_key", "")) == "fixture_pack"

        metrics = list(report.get("metrics", []))
        while len(metrics) < 4:
            metrics.append(("--", "--"))
        for index, (title, value) in enumerate(metrics[:4]):
            self.preview_metric_labels[index].setText(_ui_safe_text(title))
            self.preview_metric_values[index].setText(_ui_safe_text(value))

        plot_series = list(report.get("plot_series", []))
        xs = np.arange(1, len(plot_series) + 1, dtype=float)
        ys = np.array(plot_series, dtype=float) if plot_series else np.array([], dtype=float)
        self.preview_curve.setData(xs, ys)
        compact_plot = len(plot_series) <= 1
        if is_expert_review:
            self.preview_plot.setMinimumHeight(145)
            self.preview_plot.setMaximumHeight(190)
        else:
            self.preview_plot.setMinimumHeight(170 if compact_plot else 210)
            self.preview_plot.setMaximumHeight(220 if compact_plot else 280)
        if is_benchmark_cockpit:
            self.preview_plot_note.setText("逐窗口通过/失败（1=通过，0=失败）")
        else:
            self.preview_plot_note.setText(self._plot_note_for_mode(view_mode))

        headers = report.get("table_headers", ["Item", "Value", "Note"])
        rows = list(report.get("table_rows", []))
        is_eddypro_compare = str(report.get("report_key", "")) == "eddypro_compare"
        if not is_eddypro_compare and not is_benchmark_cockpit:
            if view_mode == "操作汇总":
                rows = rows[:3]
            elif view_mode == "管理汇报":
                rows = rows[:2]
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels([_ui_safe_text(header) for header in headers])
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setMaximumHeight(132 if is_expert_review else 150)
        for row_index, row in enumerate(rows):
            for col, value in enumerate(row):
                item = QTableWidgetItem(_ui_safe_text(value))
                item.setData(Qt.UserRole, str(value))
                if col == 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if is_benchmark_cockpit and col == 1:
                    val_str = str(value)
                    if val_str in ("fail", "0"):
                        item.setForeground(QColor("#ef4444"))
                    elif val_str in ("pass", "1"):
                        item.setForeground(QColor("#22c55e"))
                self.preview_table.setItem(row_index, col, item)

        if is_benchmark_cockpit:
            if not getattr(self, "_benchmark_cell_connected", False):
                self.preview_table.cellClicked.connect(self._on_benchmark_cell_clicked)
                self._benchmark_cell_connected = True
            self._build_benchmark_controls(report)
        elif hasattr(self, "_benchmark_controls_card"):
            self._benchmark_controls_card.setVisible(False)
        if is_fixture_pack:
            self._build_official_raw_bundle_controls(report)
        elif hasattr(self, "_official_bundle_controls_card"):
            self._official_bundle_controls_card.setVisible(False)

        self._clear_layout(self.conclusion_content)
        for text in self._conclusions_for_mode(report, view_mode):
            label = QLabel(_ui_safe_text(text))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.conclusion_content.addWidget(label)
        if is_fixture_pack:
            self._append_official_raw_fixture_detail(report)
        self._refresh_expert_review_card(report)

    def _refresh_expert_review_card(self, report: dict) -> None:
        report_key = str(report.get("report_key", "") or "")
        items = self._expert_review_items(report_key, report)
        self.expert_review_card.setVisible(bool(items))
        if not items:
            return
        tone = "success" if report_key == "computation_surface" else "accent"
        self._set_chip(self.expert_review_chip, "可审阅" if tone == "success" else "审阅", tone)
        for index, tile in enumerate(self.expert_review_tiles):
            visible = index < len(items)
            tile.setVisible(visible)
            if not visible:
                continue
            title, value, note, item_tone = items[index]
            self.expert_review_labels[index].setText(_ui_safe_text(title))
            self.expert_review_values[index].setText(_ui_safe_text(value))
            self.expert_review_notes[index].setText(_ui_safe_text(note))
            tooltip = _ui_safe_text(f"{title}: {value}\n{note}")
            self.expert_review_values[index].setToolTip(tooltip)
            self.expert_review_notes[index].setToolTip(tooltip)
            tile.setProperty("expertTone", item_tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _expert_review_items(self, report_key: str, report: dict) -> list[tuple[str, str, str, str]]:
        if report_key not in {"method_provenance", "method_compare", "computation_surface"}:
            return []
        metrics = {str(key): str(value) for key, value in list(report.get("metrics", []) or [])}
        file_info = dict(report.get("file_info", {}) or {})
        rows = list(report.get("table_rows", []) or [])
        if report_key == "method_compare":
            artifact_count = sum(1 for value in file_info.values() if str(value or "").strip())
            return [
                ("方法族", metrics.get("families", "--"), f"status={metrics.get('status', '--')}", "accent"),
                ("参考字段", metrics.get("reference_fields", "--"), "来自方法对标矩阵", "accent"),
                ("性能剖面", metrics.get("profiled_windows", "--"), f"runtime={metrics.get('runtime_ms', '--')} ms", "success"),
                ("Artifacts", str(artifact_count), "compare / parity / contour", "success" if artifact_count else "warning"),
            ]
        if report_key == "computation_surface":
            status = metrics.get("surface_status", "--")
            failed_cases = metrics.get("failed_cases", "--")
            scope_ready = any("Scope Audit" in str(key) or "范围" in str(key) for key in file_info)
            return [
                ("计算面", status, "stress suite backed", "success" if status == "ready" else "warning"),
                ("方法族", metrics.get("ready_families", "--"), "required families ready", "success"),
                ("压力套件", metrics.get("stress_pass_rate", "--"), f"failed={failed_cases}", "success" if failed_cases == "0" else "warning"),
                ("声明边界", "已审计" if scope_ready else "待导出", "claim boundary artifact", "success" if scope_ready else "warning"),
            ]
        method_names = {
            str(row[0]): str(row[1])
            for row in rows
            if isinstance(row, (tuple, list)) and len(row) >= 2
        }
        core_count = sum(1 for key in ("Footprint", "不确定度", "谱修正") if method_names.get(key))
        artifact_count = sum(1 for value in file_info.values() if str(value or "").strip())
        return [
            ("核心方法", f"{core_count}/3", "Footprint / 不确定度 / 谱修正", "success" if core_count == 3 else "warning"),
            ("Footprint", method_names.get("Footprint", "--"), method_names.get("Footprint 2D", "2D grid"), "accent"),
            ("谱修正", method_names.get("谱修正", "--"), method_names.get("FCC cospectrum", "FCC path"), "accent"),
            ("Artifacts", str(artifact_count), "method rollup and provenance", "success" if artifact_count else "warning"),
        ]

    def _on_benchmark_cell_clicked(self, row: int, col: int) -> None:
        item = self.preview_table.item(row, 0)
        if item is None:
            return
        window_id = str(item.data(Qt.UserRole) or item.text())
        report = self.controller.report_center_workspace.get("reports", {}).get("benchmark_cockpit", {})
        per_window_detail = report.get("per_window_detail", [])
        detail = next((d for d in per_window_detail if d.get("window_id") == window_id), None)
        if detail is None:
            return
        self._clear_layout(self.conclusion_content)
        match_strategy = detail.get("match_strategy", "none")
        matched_ref = detail.get("matched_reference_window_id", "")
        overall_pass = detail.get("overall_pass", True)
        header_label = QLabel(f"窗口 {window_id} 明细")
        header_label.setObjectName("metricValue")
        self.conclusion_content.addWidget(header_label)
        self.conclusion_content.addWidget(QLabel(f"匹配策略: {match_strategy}"))
        if matched_ref:
            self.conclusion_content.addWidget(QLabel(f"参考窗口: {matched_ref}"))
        self.conclusion_content.addWidget(QLabel(f"整体结果: {'通过' if overall_pass else '未通过'}"))
        self.conclusion_content.addWidget(QLabel(f"QC 等级: {detail.get('qc_grade', '--')}"))
        self.conclusion_content.addWidget(QLabel(f"主通量: {detail.get('primary_flux', '--')}"))
        for comp in detail.get("comparisons", []):
            fname = comp.get("field_name", "")
            passed = comp.get("passed", True)
            abs_err = comp.get("absolute_error")
            rel_err = comp.get("relative_error")
            note = comp.get("note", "")
            status_text = "通过" if passed else "未通过"
            line = f"  {fname}: {status_text}"
            if abs_err is not None:
                line += f"  abs_err={abs_err:.4e}"
            if rel_err is not None:
                line += f"  rel_err={rel_err:.4f}"
            if note:
                line += f"  ({note})"
            comp_label = QLabel(_ui_safe_text(line))
            comp_label.setObjectName("subtitle")
            comp_label.setWordWrap(True)
            self.conclusion_content.addWidget(comp_label)

    def _build_benchmark_controls(self, report: dict) -> None:
        if not hasattr(self, "_benchmark_controls_card"):
            self._benchmark_controls_card = CardFrame(muted=True)
            self._benchmark_controls_layout = QVBoxLayout(self._benchmark_controls_card)
            self._benchmark_controls_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            self._benchmark_controls_layout.setSpacing(TOKENS.spacing_sm)
            self._benchmark_controls_layout.addWidget(section_title("基准操作", "选择参考、调整阈值、刷新结果"))
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(TOKENS.spacing_md)
            ctrl_row.addWidget(QLabel("Reference:"))
            self._bm_ref_combo = QComboBox()
            ctrl_row.addWidget(self._bm_ref_combo, 1)
            ctrl_row.addWidget(QLabel("Flux Rel:"))
            self._bm_flux_thresh = QDoubleSpinBox()
            self._bm_flux_thresh.setRange(0.01, 1.0)
            self._bm_flux_thresh.setSingleStep(0.01)
            self._bm_flux_thresh.setDecimals(2)
            ctrl_row.addWidget(self._bm_flux_thresh)
            ctrl_row.addWidget(QLabel("Lag Abs(s):"))
            self._bm_lag_thresh = QDoubleSpinBox()
            self._bm_lag_thresh.setRange(0.1, 10.0)
            self._bm_lag_thresh.setSingleStep(0.1)
            self._bm_lag_thresh.setDecimals(1)
            ctrl_row.addWidget(self._bm_lag_thresh)
            self._bm_rerun_btn = QPushButton("Rerun")
            self._bm_rerun_btn.setProperty("variant", "primary")
            ctrl_row.addWidget(self._bm_rerun_btn)
            self._bm_filter_failed_btn = QPushButton("Show Failed Only")
            ctrl_row.addWidget(self._bm_filter_failed_btn)
            self._benchmark_controls_layout.addLayout(ctrl_row)
            self._bm_ref_combo.currentTextChanged.connect(self._on_bm_ref_changed)
            self._bm_flux_thresh.editingFinished.connect(self._on_bm_threshold_changed)
            self._bm_lag_thresh.editingFinished.connect(self._on_bm_threshold_changed)
            self._bm_rerun_btn.clicked.connect(self._on_bm_rerun)
            self._bm_filter_failed_btn.clicked.connect(self._on_bm_filter_failed)
        self._bm_ref_combo.blockSignals(True)
        self._bm_ref_combo.clear()
        for ref_id in report.get("available_references", []):
            self._bm_ref_combo.addItem(ref_id)
        current_ref = ""
        for row in report.get("table_rows", []):
            if row[0] == "reference_id":
                current_ref = str(row[1])
                break
        idx = self._bm_ref_combo.findText(current_ref)
        if idx >= 0:
            self._bm_ref_combo.setCurrentIndex(idx)
        self._bm_ref_combo.blockSignals(False)
        thresholds = report.get("current_thresholds", {})
        self._bm_flux_thresh.blockSignals(True)
        self._bm_flux_thresh.setValue(float(thresholds.get("flux_rel_threshold", 0.10)))
        self._bm_flux_thresh.blockSignals(False)
        self._bm_lag_thresh.blockSignals(True)
        self._bm_lag_thresh.setValue(float(thresholds.get("lag_abs_threshold_s", 0.5)))
        self._bm_lag_thresh.blockSignals(False)
        parent = self._benchmark_controls_card.parent()
        if parent is None:
            content_card_index = -1
            for i in range(self.conclusion_card.parent().layout().count()):
                item = self.conclusion_card.parent().layout().itemAt(i)
                if item and item.widget() is self.conclusion_card:
                    content_card_index = i
                    break
            if hasattr(self, "preview_content_card"):
                parent_layout = self.preview_content_card.parent().layout()
                if parent_layout:
                    idx = parent_layout.indexOf(self.preview_content_card)
                    if idx >= 0:
                        parent_layout.insertWidget(idx + 1, self._benchmark_controls_card)

    def _official_ops_metric_tile(self, key: str, title: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setMaximumHeight(72)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(1)
        label = QLabel(_ui_safe_text(title))
        label.setObjectName("metricLabel")
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setProperty("compactMetric", True)
        value.setWordWrap(False)
        note = QLabel("--")
        note.setObjectName("subtitle")
        note.setWordWrap(False)
        layout.addWidget(label)
        layout.addWidget(value)
        layout.addWidget(note)
        self._official_ops_values[key] = (tile, value, note)
        return tile

    def _official_button_group(
        self,
        title: str,
        subtitle: str,
        buttons: list[QPushButton],
        *,
        columns: int = 3,
    ) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_xs)
        layout.addWidget(section_title(title, subtitle))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_xs)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        for index, button in enumerate(buttons):
            grid.addWidget(button, index // columns, index % columns)
        layout.addLayout(grid)
        return card

    def _build_official_raw_bundle_controls(self, report: dict) -> None:
        if not hasattr(self, "_official_bundle_controls_card"):
            self._official_bundle_controls_card = CardFrame(muted=True, role="panel")
            self._official_bundle_controls_card.setProperty("deckRole", "officialRawOpsCockpit")
            self._official_bundle_controls_layout = QVBoxLayout(self._official_bundle_controls_card)
            self._official_bundle_controls_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            self._official_bundle_controls_layout.setSpacing(TOKENS.spacing_sm)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.addWidget(section_title("行业参考原始包", "检查、归档或注册真实 raw-to-final 参考验证包。"))
            header.addStretch(1)
            self._official_ops_chip = chip("待选择", "warning")
            header.addWidget(self._official_ops_chip)
            self._official_bundle_controls_layout.addLayout(header)

            self._official_ops_values: dict[str, tuple[CardFrame, QLabel, QLabel]] = {}
            ops_grid = QGridLayout()
            ops_grid.setContentsMargins(0, 0, 0, 0)
            ops_grid.setHorizontalSpacing(TOKENS.spacing_sm)
            ops_grid.setVerticalSpacing(TOKENS.spacing_sm)
            for index, (key, title) in enumerate(
                (
                    ("bundle", "验证包"),
                    ("parity", "对标状态"),
                    ("public", "公开参考"),
                    ("selected", "当前选择"),
                )
            ):
                ops_grid.addWidget(self._official_ops_metric_tile(key, title), 0, index)
            self._official_bundle_controls_layout.addLayout(ops_grid)

            source_card = CardFrame(muted=True, role="tile")
            source_layout = QVBoxLayout(source_card)
            source_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
            source_layout.setSpacing(TOKENS.spacing_xs)
            source_layout.addWidget(section_title("验证包来源", "选择单包或目录根，替换/覆盖选项在同一区域确认。"))
            source_row = QHBoxLayout()
            source_row.setContentsMargins(0, 0, 0, 0)
            source_row.setSpacing(TOKENS.spacing_sm)
            self._official_bundle_path = QLineEdit()
            self._official_bundle_path.setPlaceholderText("references/reference/official_raw/site_001")
            self._official_bundle_browse = QPushButton("浏览")
            source_row.addWidget(QLabel("路径"))
            source_row.addWidget(self._official_bundle_path, 1)
            source_row.addWidget(self._official_bundle_browse)
            source_layout.addLayout(source_row)
            option_row = QHBoxLayout()
            option_row.setContentsMargins(0, 0, 0, 0)
            option_row.setSpacing(TOKENS.spacing_sm)
            self._public_fixture_overwrite = QCheckBox("覆盖公开缓存")
            self._official_bundle_replace = QCheckBox("替换现有")
            option_row.addWidget(self._public_fixture_overwrite)
            option_row.addWidget(self._official_bundle_replace)
            option_row.addStretch(1)
            source_layout.addLayout(option_row)
            self._official_bundle_controls_layout.addWidget(source_card)

            self._official_bundle_build_manifest = QPushButton("生成清单")
            self._official_bundle_inspect = QPushButton("检查")
            self._official_bundle_validate = QPushButton("验证 P0")
            self._official_bundle_evidence_pack = QPushButton("证据包")
            self._official_bundle_acceptance = QPushButton("运行验收")
            self._official_bundle_register = QPushButton("注册")
            self._official_bundle_register.setProperty("variant", "primary")
            self._official_bundle_build_tree_manifests = QPushButton("生成目录清单")
            self._official_bundle_inspect_tree = QPushButton("检查目录")
            self._official_bundle_register_tree = QPushButton("注册目录")
            self._public_fixture_refresh = QPushButton("刷新公开参考")
            action_grid = QGridLayout()
            action_grid.setContentsMargins(0, 0, 0, 0)
            action_grid.setHorizontalSpacing(TOKENS.spacing_sm)
            action_grid.setVerticalSpacing(TOKENS.spacing_sm)
            action_grid.addWidget(
                self._official_button_group(
                    "单包闭环",
                    "从清单到注册的 raw-to-final 单包动作。",
                    [
                        self._official_bundle_build_manifest,
                        self._official_bundle_inspect,
                        self._official_bundle_validate,
                        self._official_bundle_evidence_pack,
                        self._official_bundle_acceptance,
                        self._official_bundle_register,
                    ],
                ),
                0,
                0,
            )
            action_grid.addWidget(
                self._official_button_group(
                    "目录批量",
                    "批量清单、目录检查、注册和公开参考刷新。",
                    [
                        self._official_bundle_build_tree_manifests,
                        self._official_bundle_inspect_tree,
                        self._official_bundle_register_tree,
                        self._public_fixture_refresh,
                    ],
                    columns=2,
                ),
                0,
                1,
            )
            self._official_bundle_controls_layout.addLayout(action_grid)

            run_card = CardFrame(muted=True, role="tile")
            run_layout = QVBoxLayout(run_card)
            run_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
            run_layout.setSpacing(TOKENS.spacing_xs)
            run_layout.addWidget(section_title("参考运行", "记录外部运行命令与输出，或直接触发闭环运行。"))
            self._official_run_command = QLineEdit()
            self._official_run_command.setPlaceholderText("reference_processor.exe --run reference/project.config")
            self._official_run_version = QLineEdit()
            self._official_run_version.setPlaceholderText("7.0.9")
            self._official_run_outputs = QLineEdit()
            self._official_run_outputs.setPlaceholderText("reference/reference_full_output.csv")
            self._official_run_capture = QPushButton("记录运行")
            self._official_closure_run = QPushButton("闭环运行")
            self._official_closure_run.setProperty("variant", "primary")
            run_form = QGridLayout()
            run_form.setContentsMargins(0, 0, 0, 0)
            run_form.setHorizontalSpacing(TOKENS.spacing_sm)
            run_form.setVerticalSpacing(TOKENS.spacing_xs)
            run_form.addWidget(QLabel("命令"), 0, 0)
            run_form.addWidget(self._official_run_command, 0, 1, 1, 3)
            run_form.addWidget(QLabel("版本"), 0, 4)
            run_form.addWidget(self._official_run_version, 0, 5)
            run_form.addWidget(QLabel("输出"), 1, 0)
            run_form.addWidget(self._official_run_outputs, 1, 1, 1, 3)
            run_form.addWidget(self._official_run_capture, 1, 4)
            run_form.addWidget(self._official_closure_run, 1, 5)
            run_layout.addLayout(run_form)
            self._official_bundle_controls_layout.addWidget(run_card)

            matrix_card = CardFrame(muted=True, role="tile")
            matrix_layout = QVBoxLayout(matrix_card)
            matrix_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
            matrix_layout.setSpacing(TOKENS.spacing_xs)
            matrix_layout.addWidget(section_title("验证矩阵", "筛选、查看详情、重跑、停用或替换单个验证包。"))
            self._official_matrix_format = QComboBox()
            self._official_matrix_site = QComboBox()
            self._official_matrix_parity = QComboBox()
            self._official_matrix_fixture = QComboBox()
            self._official_matrix_apply = QPushButton("应用筛选")
            self._official_fixture_detail = QPushButton("详情")
            self._official_fixture_rerun = QPushButton("重跑验证包")
            self._official_fixture_disable = QPushButton("停用验证包")
            self._official_fixture_replace = QPushButton("替换验证包")
            matrix_form = QGridLayout()
            matrix_form.setContentsMargins(0, 0, 0, 0)
            matrix_form.setHorizontalSpacing(TOKENS.spacing_sm)
            matrix_form.setVerticalSpacing(TOKENS.spacing_xs)
            matrix_form.addWidget(QLabel("格式"), 0, 0)
            matrix_form.addWidget(self._official_matrix_format, 0, 1)
            matrix_form.addWidget(QLabel("站点"), 0, 2)
            matrix_form.addWidget(self._official_matrix_site, 0, 3)
            matrix_form.addWidget(QLabel("对标"), 0, 4)
            matrix_form.addWidget(self._official_matrix_parity, 0, 5)
            matrix_form.addWidget(QLabel("验证包"), 1, 0)
            matrix_form.addWidget(self._official_matrix_fixture, 1, 1, 1, 3)
            matrix_form.addWidget(self._official_matrix_apply, 1, 4)
            matrix_form.addWidget(self._official_fixture_detail, 1, 5)
            matrix_form.addWidget(self._official_fixture_rerun, 2, 1)
            matrix_form.addWidget(self._official_fixture_disable, 2, 2)
            matrix_form.addWidget(self._official_fixture_replace, 2, 3)
            matrix_layout.addLayout(matrix_form)
            self._official_bundle_controls_layout.addWidget(matrix_card)

            self._official_bundle_status_card = CardFrame(muted=True, role="console")
            status_layout = QVBoxLayout(self._official_bundle_status_card)
            status_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            status_layout.setSpacing(1)
            self._official_bundle_status = QLabel("--")
            self._official_bundle_status.setObjectName("subtitle")
            self._official_bundle_status.setWordWrap(True)
            status_layout.addWidget(self._official_bundle_status)
            self._official_bundle_controls_layout.addWidget(self._official_bundle_status_card)
            self._official_bundle_browse.clicked.connect(self._on_official_bundle_browse)
            self._official_bundle_build_manifest.clicked.connect(self._on_official_bundle_build_manifest)
            self._official_bundle_inspect.clicked.connect(self._on_official_bundle_inspect)
            self._official_bundle_validate.clicked.connect(self._on_official_bundle_validate)
            self._official_bundle_evidence_pack.clicked.connect(self._on_official_bundle_evidence_pack)
            self._official_bundle_acceptance.clicked.connect(self._on_official_bundle_acceptance)
            self._official_bundle_register.clicked.connect(self._on_official_bundle_register)
            self._official_bundle_build_tree_manifests.clicked.connect(self._on_official_bundle_build_tree_manifests)
            self._official_bundle_inspect_tree.clicked.connect(self._on_official_bundle_inspect_tree)
            self._official_bundle_register_tree.clicked.connect(self._on_official_bundle_register_tree)
            self._public_fixture_refresh.clicked.connect(self._on_public_fixture_refresh)
            self._official_run_capture.clicked.connect(self._on_official_run_capture)
            self._official_closure_run.clicked.connect(self._on_official_closure_run)
            self._official_matrix_apply.clicked.connect(self._on_official_matrix_filter)
            self._official_fixture_detail.clicked.connect(self._on_official_fixture_detail)
            self._official_fixture_rerun.clicked.connect(self._on_official_fixture_rerun)
            self._official_fixture_disable.clicked.connect(self._on_official_fixture_disable)
            self._official_fixture_replace.clicked.connect(self._on_official_fixture_replace)
        state = self.controller.report_center_workspace.get("official_raw_bundle", {})
        current_path = str(state.get("bundle_dir", "") or state.get("bundle_root", "") or self._official_bundle_path_value()).strip()
        if current_path:
            self._set_official_bundle_path_display(current_path)
        capture = dict(state.get("official_run_capture", {}) or {})
        sidecar = dict(capture.get("sidecar", {}) or {})
        if sidecar.get("command") and not self._official_run_command.text().strip():
            self._set_raw_line_edit_display(self._official_run_command, str(sidecar.get("command", "")))
        if sidecar.get("software_version") and not self._official_run_version.text().strip():
            self._official_run_version.setText(str(sidecar.get("software_version", "")))
        if sidecar.get("output_files") and not self._official_run_outputs.text().strip():
            self._set_raw_line_edit_display(
                self._official_run_outputs,
                ",".join(str(item) for item in list(sidecar.get("output_files", []) or [])),
            )
        matrix = dict(report.get("official_raw_evidence_matrix", {}) or {})
        matrix_rows = [dict(row or {}) for row in list(matrix.get("rows", []) or [])]
        filters = dict(report.get("official_raw_matrix_filters", {}) or {})
        selected_fixture = str(report.get("official_raw_selected_fixture_id", "") or "")
        self._replace_combo_items(
            self._official_matrix_format,
            ["全部"] + sorted({str(row.get("raw_format", "")) for row in matrix_rows if row.get("raw_format")}),
            keep_text=str(filters.get("raw_format", "") or "全部"),
        )
        self._replace_combo_items(
            self._official_matrix_site,
            ["全部"] + sorted({str(row.get("site_class", "")) for row in matrix_rows if row.get("site_class")}),
            keep_text=str(filters.get("site_class", "") or "全部"),
        )
        self._replace_combo_items(
            self._official_matrix_parity,
            ["全部"] + sorted({str(row.get("parity_status", "") or row.get("status", "")) for row in matrix_rows if row.get("parity_status") or row.get("status")}),
            keep_text=str(filters.get("parity_status", "") or "全部"),
        )
        fixture_ids = [str(row.get("fixture_id", "")) for row in matrix_rows if row.get("fixture_id")]
        self._replace_combo_items(
            self._official_matrix_fixture,
            fixture_ids,
            keep_text=selected_fixture or (fixture_ids[0] if fixture_ids else ""),
        )
        public_state = dict(self.controller.report_center_workspace.get("public_eddypro_fixtures", {}) or {})
        status_parts = [str(state.get("message", "尚未检查行业参考原始包。"))]
        if public_state.get("message"):
            status_parts.append(str(public_state.get("message")))
        self._official_bundle_status.setText(" | ".join(status_parts))
        self._refresh_official_raw_ops_summary(
            state=state,
            public_state=public_state,
            selected_fixture=selected_fixture,
            current_path=current_path,
            matrix_rows=matrix_rows,
        )
        self._official_bundle_controls_card.setVisible(True)
        parent = self._official_bundle_controls_card.parent()
        if parent is None and hasattr(self, "preview_content_card"):
            parent_layout = self.preview_content_card.parent().layout()
            if parent_layout:
                idx = parent_layout.indexOf(self.preview_content_card)
                if idx >= 0:
                    parent_layout.insertWidget(idx + 1, self._official_bundle_controls_card)

    def _refresh_official_raw_ops_summary(
        self,
        *,
        state: dict,
        public_state: dict,
        selected_fixture: str,
        current_path: str,
        matrix_rows: list[dict],
    ) -> None:
        path_tail = current_path.replace("\\", "/").rstrip("/").split("/")[-1] if current_path else ""
        selected = (
            selected_fixture
            or str(state.get("selected_fixture_id", "") or "")
            or (str(matrix_rows[0].get("fixture_id", "")) if matrix_rows else "")
            or "--"
        )
        parity_payload = dict(
            state.get("parity", {})
            or state.get("selected_parity", {})
            or state.get("batch_parity", {})
            or {}
        )
        parity_status = str(
            parity_payload.get("status")
            or state.get("parity_status")
            or state.get("status")
            or "待运行"
        )
        public_status = str(public_state.get("status") or "待刷新")
        bundle_status = str(state.get("status") or ("已选择" if current_path else "未选择"))
        bundle_value = str(state.get("fixture_id") or state.get("bundle_id") or path_tail or "--")
        matrix_count = len(matrix_rows)
        summary = {
            "bundle": (bundle_value, bundle_status, self._official_status_tone(bundle_status)),
            "parity": (parity_status, f"matrix rows={matrix_count}", self._official_status_tone(parity_status)),
            "public": (public_status, str(public_state.get("fixture_count", "fixtures --")), self._official_status_tone(public_status)),
            "selected": (selected, "当前矩阵选择", "accent" if selected != "--" else "warning"),
        }
        overall_tone = "success" if summary["parity"][2] == "success" else ("accent" if current_path else "warning")
        self._set_chip(self._official_ops_chip, "闭环就绪" if overall_tone == "success" else "待复核", overall_tone)
        for key, (value, note, tone) in summary.items():
            tile, value_label, note_label = self._official_ops_values[key]
            value_label.setText(_ui_safe_text(value))
            note_label.setText(_ui_safe_text(note))
            tooltip = _ui_safe_text(f"{value}\n{note}")
            value_label.setToolTip(tooltip)
            note_label.setToolTip(tooltip)
            tile.setProperty("expertTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    @staticmethod
    def _official_status_tone(status: str) -> str:
        status_lower = status.strip().lower()
        if any(token in status_lower for token in ("pass", "ready", "registered", "complete", "normalized", "closure_ready")):
            return "success"
        if any(token in status_lower for token in ("fail", "block", "missing", "not_", "pending", "未", "待")):
            return "warning"
        return "accent"

    def _append_official_raw_fixture_detail(self, report: dict) -> None:
        detail = dict(report.get("official_raw_selected_fixture_detail", {}) or {})
        if not detail:
            selected = str(report.get("official_raw_selected_fixture_id", "") or "").strip()
            if selected:
                hint = QLabel(f"已选择验证包：{selected}。点击“详情”生成单验证包审计 artifact。")
                hint.setObjectName("subtitle")
                hint.setWordWrap(True)
                self.conclusion_content.addWidget(hint)
            return

        fixture_id = str(detail.get("fixture_id", "") or "--")
        header = QLabel(f"行业参考验证包详情：{fixture_id}")
        header.setObjectName("metricValue")
        header.setWordWrap(True)
        self.conclusion_content.addWidget(header)
        status_line = QLabel(
            f"readiness={detail.get('readiness_level', '--')} | "
            f"status={detail.get('status', '--')} | "
            f"site={detail.get('site_class', '--')} | "
            f"software={detail.get('software', '--')} {detail.get('software_version', '')}"
        )
        status_line.setObjectName("subtitle")
        status_line.setWordWrap(True)
        self.conclusion_content.addWidget(status_line)

        file_checks = dict(detail.get("file_checks", {}) or {})
        missing_groups = ", ".join(str(item) for item in list(file_checks.get("missing_required_groups", []) or [])) or "none"
        file_line = QLabel(
            f"files={file_checks.get('present_file_count', 0)}/{file_checks.get('declared_file_count', 0)} | "
            f"file_check={file_checks.get('status', '--')} | missing_groups={missing_groups}"
        )
        file_line.setObjectName("subtitle")
        file_line.setWordWrap(True)
        self.conclusion_content.addWidget(file_line)

        normalization = dict(detail.get("normalization", {}) or {})
        provenance_line = QLabel(
            f"source={normalization.get('source_file', '--')} | "
            f"normalization_time={normalization.get('normalization_time', '--')} | "
            f"qc_mapping={normalization.get('qc_mapping_strategy', '--')}"
        )
        provenance_line.setObjectName("subtitle")
        provenance_line.setWordWrap(True)
        self.conclusion_content.addWidget(provenance_line)
        if normalization.get("normalization_command"):
            command_line = QLabel(f"normalization_command={normalization.get('normalization_command', '')}")
            command_line.setObjectName("subtitle")
            command_line.setWordWrap(True)
            self.conclusion_content.addWidget(command_line)
        official_run_normalization = dict(detail.get("official_run_normalization", {}) or {})
        if official_run_normalization:
            run_norm_line = QLabel(
                f"official_run_normalization={official_run_normalization.get('status', '--')} | "
                f"time={official_run_normalization.get('normalization_time', '--')} | "
                f"qc_mapping={official_run_normalization.get('qc_mapping_strategy', '--')}"
            )
            run_norm_line.setObjectName("subtitle")
            run_norm_line.setWordWrap(True)
            self.conclusion_content.addWidget(run_norm_line)
            source_line = QLabel(
                f"official_run_source={official_run_normalization.get('source_file', '--')} | "
                f"reference={official_run_normalization.get('reference_json', '--')}"
            )
            source_line.setObjectName("subtitle")
            source_line.setWordWrap(True)
            self.conclusion_content.addWidget(source_line)

        failed_fields = " / ".join(str(item) for item in list(detail.get("failed_fields", []) or [])) or "none"
        parity_line = QLabel(
            f"pass_rate={float(detail.get('pass_rate', 0.0) or 0.0):.1%} | "
            f"failed_fields={failed_fields} | artifact={report.get('official_raw_selected_fixture_detail_artifact', '')}"
        )
        parity_line.setObjectName("subtitle")
        parity_line.setWordWrap(True)
        self.conclusion_content.addWidget(parity_line)

        parity_diagnostics = dict(detail.get("parity_diagnostics", {}) or {})
        failure_groups = " / ".join(
            str(item.get("category", ""))
            for item in list(parity_diagnostics.get("failure_groups", []) or [])[:4]
            if str(item.get("category", ""))
        ) or "none"
        top_failed_fields = " / ".join(str(item) for item in list(parity_diagnostics.get("top_failed_fields", []) or [])[:8]) or "none"
        diagnostic_line = QLabel(
            f"diagnostics={parity_diagnostics.get('status', 'not_available')} | "
            f"failure_groups={failure_groups} | top_failed_fields={top_failed_fields}"
        )
        diagnostic_line.setObjectName("subtitle")
        diagnostic_line.setWordWrap(True)
        self.conclusion_content.addWidget(diagnostic_line)

        acquisition = dict(detail.get("acquisition_validation", {}) or {})
        if acquisition:
            acquisition_line = QLabel(
                f"acquisition_gate={acquisition.get('status', '--')} | "
                f"gate={acquisition.get('gate_status', '--')} | "
                f"missing={('/'.join(str(item) for item in list(acquisition.get('missing_requirements', []) or [])[:5]) or 'none')}"
            )
            acquisition_line.setObjectName("subtitle")
            acquisition_line.setWordWrap(True)
            self.conclusion_content.addWidget(acquisition_line)

        trace_gas_parity = dict(detail.get("trace_gas_parity", {}) or {})
        trace_gas_status = str(detail.get("trace_gas_parity_status", "") or trace_gas_parity.get("status", ""))
        if trace_gas_status:
            trace_failed = " / ".join(
                str(item)
                for item in list(detail.get("trace_gas_failed_fields", trace_gas_parity.get("failed_fields", [])) or [])
            ) or "none"
            trace_line = QLabel(
                f"trace_gas_parity={trace_gas_status} | "
                f"trace_pass_rate={float(detail.get('trace_gas_pass_rate', trace_gas_parity.get('pass_rate', 0.0)) or 0.0):.1%} | "
                f"profile={detail.get('trace_gas_coefficient_profile_id', trace_gas_parity.get('coefficient_profile_id', '--')) or '--'} | "
                f"trace_failed_fields={trace_failed}"
            )
            trace_line.setObjectName("subtitle")
            trace_line.setWordWrap(True)
            self.conclusion_content.addWidget(trace_line)
            trace_provenance = dict(detail.get("trace_gas_provenance_summary", {}) or trace_gas_parity.get("provenance_summary", {}) or {})
            trace_ch4 = dict(dict(trace_provenance.get("gases", {}) or {}).get("ch4", {}) or {})
            trace_source = detail.get("trace_gas_coefficient_profile_source_file") or trace_ch4.get("coefficient_profile_source_file", "")
            trace_normalization = (
                detail.get("trace_gas_coefficient_profile_normalization_command")
                or trace_ch4.get("coefficient_profile_normalization_command", "")
            )
            trace_limits = " / ".join(
                str(item)
                for item in list(detail.get("trace_gas_known_limitations", trace_ch4.get("coefficient_profile_limitations", [])) or [])[:3]
            ) or "none"
            trace_provenance_line = QLabel(
                f"trace_profile_source={trace_source or '--'} | "
                f"normalization={trace_normalization or '--'} | limitations={trace_limits}"
            )
            trace_provenance_line.setObjectName("subtitle")
            trace_provenance_line.setWordWrap(True)
            self.conclusion_content.addWidget(trace_provenance_line)

        limitations = list(detail.get("known_limitations", []) or [])
        for limitation in limitations[:3]:
            limitation_line = QLabel(f"limitation: {str(limitation)}")
            limitation_line.setObjectName("subtitle")
            limitation_line.setWordWrap(True)
            self.conclusion_content.addWidget(limitation_line)

    def _on_official_bundle_browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择行业参考原始包")
        if selected:
            self._set_official_bundle_path_display(selected)

    def _on_official_bundle_inspect(self) -> None:
        result = self.controller.inspect_official_raw_bundle_for_report_center(self._official_bundle_path_value())
        self._show_info("行业参考原始包", result["message"])
        self.refresh()

    def _on_official_bundle_validate(self) -> None:
        result = self.controller.validate_official_raw_bundle_for_report_center(self._official_bundle_path_value())
        self._show_info("行业参考 P0 门槛", result["message"])
        self.refresh()

    def _on_official_bundle_evidence_pack(self) -> None:
        result = self.controller.export_official_raw_evidence_pack_for_report_center(self._official_bundle_path_value())
        self._show_info("行业参考证据包", result["message"])
        self.refresh()

    def _on_official_bundle_acceptance(self) -> None:
        result = self.controller.run_official_raw_evidence_acceptance_for_report_center(self._official_bundle_path_value())
        self._show_info("行业参考验收", result["message"])
        self.refresh()

    def _on_official_run_capture(self) -> None:
        result = self.controller.capture_official_eddypro_run_for_report_center(
            self._official_bundle_path_value(),
            command=self._raw_line_edit_value(self._official_run_command),
            software_version=self._official_run_version.text(),
            output_files=self._raw_line_edit_value(self._official_run_outputs),
        )
        self._show_info("行业参考运行", result["message"])
        self.refresh()

    def _on_official_closure_run(self) -> None:
        result = self.controller.run_official_raw_closure_for_report_center(
            self._official_bundle_path_value(),
            command=self._raw_line_edit_value(self._official_run_command),
            software_version=self._official_run_version.text(),
            output_files=self._raw_line_edit_value(self._official_run_outputs),
            overwrite_manifest=bool(self._official_bundle_replace.isChecked()),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考闭环", result["message"])
        self.refresh()

    def _on_official_bundle_build_manifest(self) -> None:
        result = self.controller.build_official_raw_bundle_manifest_for_report_center(
            self._official_bundle_path_value(),
            overwrite=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考清单", result["message"])
        self.refresh()

    def _on_official_bundle_register(self) -> None:
        result = self.controller.register_official_raw_bundle_for_report_center(
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考原始包", result["message"])
        self.refresh()

    def _on_official_bundle_inspect_tree(self) -> None:
        result = self.controller.inspect_official_raw_bundle_tree_for_report_center(self._official_bundle_path_value())
        self._show_info("行业参考目录", result["message"])
        self.refresh()

    def _on_official_bundle_build_tree_manifests(self) -> None:
        result = self.controller.build_official_raw_bundle_tree_manifests_for_report_center(
            self._official_bundle_path_value(),
            overwrite=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考目录", result["message"])
        self.refresh()

    def _on_official_bundle_register_tree(self) -> None:
        result = self.controller.register_official_raw_bundle_tree_for_report_center(
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考目录", result["message"])
        self.refresh()

    def _on_public_fixture_refresh(self) -> None:
        result = self.controller.refresh_public_eddypro_fixtures_for_report_center(
            overwrite=bool(self._public_fixture_overwrite.isChecked())
        )
        self._show_info("公开参考验证包", result["message"])
        self.refresh()

    def _on_official_matrix_filter(self) -> None:
        def value(combo: QComboBox) -> str:
            text = combo.currentText().strip()
            return "" if text in {"All", "全部"} else text

        result = self.controller.set_official_raw_matrix_filters_for_report_center(
            raw_format=value(self._official_matrix_format),
            site_class=value(self._official_matrix_site),
            parity_status=value(self._official_matrix_parity),
        )
        self._show_info("行业参考矩阵", result["message"])
        self.refresh()

    def _selected_official_fixture_id(self) -> str:
        fixture_id = self._official_matrix_fixture.currentText().strip()
        if fixture_id:
            self.controller.select_official_raw_fixture_for_report_center(fixture_id)
        return fixture_id

    def _on_official_fixture_rerun(self) -> None:
        result = self.controller.rerun_official_raw_fixture_for_report_center(self._selected_official_fixture_id())
        self._show_info("行业参考验证包", result["message"])
        self.refresh()

    def _on_official_fixture_detail(self) -> None:
        result = self.controller.inspect_official_raw_fixture_detail_for_report_center(self._selected_official_fixture_id())
        self._show_info("行业参考验证包详情", result["message"])
        self.refresh()

    def _on_official_fixture_disable(self) -> None:
        result = self.controller.disable_official_raw_fixture_for_report_center(self._selected_official_fixture_id())
        self._show_info("行业参考验证包", result["message"])
        self.refresh()

    def _on_official_fixture_replace(self) -> None:
        result = self.controller.replace_official_raw_fixture_for_report_center(
            self._selected_official_fixture_id(),
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("行业参考验证包", result["message"])
        self.refresh()

    def _on_bm_ref_changed(self, text: str) -> None:
        report = self.controller.report_center_workspace.get("reports", {}).get("benchmark_cockpit", {})
        provenance = report.get("ref_provenance", {})
        prov = provenance.get(text, {})
        if prov:
            self._clear_layout(self.conclusion_content)
            self.conclusion_content.addWidget(QLabel(_ui_safe_text(f"参考: {text}")))
            self.conclusion_content.addWidget(QLabel(_ui_safe_text(f"原始文件: {prov.get('original_file_name', '--')}")))
            self.conclusion_content.addWidget(QLabel(_ui_safe_text(f"归一化时间: {prov.get('normalization_time', '--')}")))
            self.conclusion_content.addWidget(QLabel(_ui_safe_text(f"QC 映射: {prov.get('qc_mapping_strategy', '--')}")))
            for lim in prov.get("known_limitations", [])[:3]:
                self.conclusion_content.addWidget(QLabel(_ui_safe_text(f"限制: {lim[:80]}")))

    def _on_bm_rerun(self) -> None:
        self.controller.refresh_report_center()
        self.refresh()

    def _on_bm_filter_failed(self) -> None:
        report = self.controller.report_center_workspace.get("reports", {}).get("benchmark_cockpit", {})
        per_window_detail = report.get("per_window_detail", [])
        failed = [d for d in per_window_detail if not d.get("overall_pass", True)]
        self._clear_layout(self.conclusion_content)
        if not failed:
            self.conclusion_content.addWidget(QLabel("所有窗口均通过，无失败窗口。"))
            return
        header = QLabel(f"失败窗口 ({len(failed)})")
        header.setObjectName("metricValue")
        self.conclusion_content.addWidget(header)
        for d in failed:
            ms = d.get("match_strategy", "none")
            ref_id = d.get("matched_reference_window_id", "")
            line = f"{d['window_id']}: match={ms}"
            if ref_id:
                line += f" ref={ref_id}"
            for comp in d.get("comparisons", []):
                if not comp.get("passed", True):
                    fname = comp.get("field_name", "")
                    abs_err = comp.get("absolute_error", 0)
                    line += f" | {fname} FAIL abs={abs_err:.4e}"
            lbl = QLabel(_ui_safe_text(line))
            lbl.setObjectName("subtitle")
            lbl.setWordWrap(True)
            self.conclusion_content.addWidget(lbl)

    def _on_bm_ref_changed(self, text: str) -> None:
        if not text.strip():
            return
        self.controller.rerun_benchmark_cockpit(reference_id=text.strip(), trigger="reference_change")
        self.refresh()

    def _on_bm_threshold_changed(self) -> None:
        self.controller.rerun_benchmark_cockpit(
            reference_id=self._bm_ref_combo.currentText().strip(),
            flux_rel_threshold=float(self._bm_flux_thresh.value()),
            lag_abs_threshold_s=float(self._bm_lag_thresh.value()),
            trigger="threshold_change",
        )
        self.refresh()

    def _on_bm_rerun(self) -> None:
        self.controller.rerun_benchmark_cockpit(
            reference_id=self._bm_ref_combo.currentText().strip(),
            flux_rel_threshold=float(self._bm_flux_thresh.value()),
            lag_abs_threshold_s=float(self._bm_lag_thresh.value()),
            trigger="rerun_button",
        )
        self.refresh()

    def _on_benchmark_cell_clicked(self, row: int, col: int) -> None:
        item = self.preview_table.item(row, 0)
        if item is None:
            return
        window_id = str(item.data(Qt.UserRole) or item.text())
        report = self.controller.report_center_workspace.get("reports", {}).get("benchmark_cockpit", {})
        per_window_detail = report.get("per_window_detail", [])
        detail = next((d for d in per_window_detail if d.get("window_id") == window_id), None)
        if detail is None:
            return
        self._clear_layout(self.conclusion_content)
        match_strategy = detail.get("match_strategy", "none")
        matched_ref = detail.get("matched_reference_window_id", "")
        overall_pass = detail.get("overall_pass", True)
        header_label = QLabel(f"窗口 {window_id} 明细")
        header_label.setObjectName("metricValue")
        self.conclusion_content.addWidget(header_label)
        self.conclusion_content.addWidget(QLabel(f"匹配策略: {match_strategy}"))
        if matched_ref:
            self.conclusion_content.addWidget(QLabel(f"参考窗口: {matched_ref}"))
        self.conclusion_content.addWidget(QLabel(f"整体结果: {'通过' if overall_pass else '未通过'}"))
        self.conclusion_content.addWidget(QLabel(f"QC 等级: {detail.get('qc_grade', '--')}"))
        self.conclusion_content.addWidget(QLabel(f"主通量: {detail.get('primary_flux', '--')}"))
        if detail.get("footprint_method"):
            self.conclusion_content.addWidget(QLabel(f"Footprint: {detail.get('footprint_method', '--')}"))
        if detail.get("uncertainty_method"):
            self.conclusion_content.addWidget(QLabel(f"Uncertainty: {detail.get('uncertainty_method', '--')}"))
        if detail.get("spectral_correction_method"):
            self.conclusion_content.addWidget(QLabel(f"Spectral correction: {detail.get('spectral_correction_method', '--')}"))
        if detail.get("clock_sync_quality_status"):
            self.conclusion_content.addWidget(
                QLabel(
                    "Clock quality: "
                    f"{detail.get('clock_sync_quality_status', '--')} "
                    f"(gate={detail.get('clock_sync_quality_gate_status', '--')}; "
                    f"metric_s={detail.get('clock_sync_quality_metric_s', '--')}; "
                    f"threshold_s={detail.get('clock_sync_quality_threshold_s', '--')})"
                )
            )
        for method_note in detail.get("method_deviation_notes", []):
            method_label = QLabel(_ui_safe_text(f"Method note: {method_note}"))
            method_label.setObjectName("subtitle")
            method_label.setWordWrap(True)
            self.conclusion_content.addWidget(method_label)
        for comp in detail.get("comparisons", []):
            fname = comp.get("field_name", "")
            passed = comp.get("passed", True)
            abs_err = comp.get("absolute_error")
            rel_err = comp.get("relative_error")
            note = comp.get("note", "")
            status_text = "通过" if passed else "未通过"
            line = f"  {fname}: {status_text}"
            if abs_err is not None:
                line += f"  abs_err={abs_err:.4e}"
            if rel_err is not None:
                line += f"  rel_err={rel_err:.4f}"
            if note:
                line += f"  ({note})"
            comp_label = QLabel(_ui_safe_text(line))
            comp_label.setObjectName("subtitle")
            comp_label.setWordWrap(True)
            self.conclusion_content.addWidget(comp_label)

    def _refresh_delivery_gate(self, workspace: dict, report: dict, export_status: str) -> None:
        reports = dict(workspace.get("reports", {}) or {})
        summary = dict(workspace.get("summary", {}) or {})
        file_values = self._delivery_file_values(reports)
        benchmark_report = dict(reports.get("benchmark_cockpit", {}) or {})
        method_report = dict(reports.get("method_provenance", {}) or {})

        exportable_count = self._safe_int(summary.get("exportable_reports", 0))
        report_ready = self._report_has_preview_payload(report) and exportable_count > 0
        export_done = self._export_status_is_done(export_status)
        manifest_path = self._first_file_value(file_values, ("manifest", "export_manifest"))
        manifest_ready = bool(manifest_path) or "交付包已导出" in export_status

        network = self._network_gate_summary(workspace, benchmark_report)
        benchmark = self._benchmark_gate_summary(workspace, benchmark_report)
        methods = self._method_gate_summary(method_report, file_values)

        self._set_delivery_gate_tile(
            "report",
            "可预览" if report_ready else "待生成",
            str(report.get("title", "当前报告")) if report_ready else "请先运行处理或生成报告。",
            "success" if report_ready else "warning",
        )
        self._set_delivery_gate_tile(
            "export",
            "已导出" if export_done else ("可导出" if exportable_count > 0 else "待运行"),
            f"状态：{export_status}",
            "success" if export_done else ("accent" if exportable_count > 0 else "warning"),
        )
        self._set_delivery_gate_tile(
            "manifest",
            "已生成" if manifest_ready else "待导出",
            manifest_path or "导出交付包后写入 manifest。",
            "success" if manifest_ready else "warning",
        )
        self._set_delivery_gate_tile("network", network["value"], network["note"], network["tone"])
        self._set_delivery_gate_tile("benchmark", benchmark["value"], benchmark["note"], benchmark["tone"])
        self._set_delivery_gate_tile("methods", methods["value"], methods["note"], methods["tone"])

        tones = [
            "success" if report_ready else "warning",
            "success" if export_done else ("accent" if exportable_count > 0 else "warning"),
            "success" if manifest_ready else "warning",
            network["tone"],
            benchmark["tone"],
            methods["tone"],
        ]
        success_count = sum(1 for tone in tones if tone == "success")
        if success_count >= 5:
            gate_text, gate_tone = "可交付", "success"
        elif report_ready or exportable_count > 0:
            gate_text, gate_tone = "待复核", "accent"
        else:
            gate_text, gate_tone = "待生成", "warning"
        self._set_chip(self.delivery_gate_chip, gate_text, gate_tone)
        self.delivery_gate_card.setProperty(
            "gateStatus",
            "ready" if gate_tone == "success" else ("review" if gate_tone == "accent" else "blocked"),
        )
        self.delivery_gate_card.style().unpolish(self.delivery_gate_card)
        self.delivery_gate_card.style().polish(self.delivery_gate_card)

        next_action, next_note = self._delivery_next_action(
            report_ready=report_ready,
            exportable_count=exportable_count,
            export_done=export_done,
            manifest_ready=manifest_ready,
            network_ready=network["tone"] == "success",
            methods_ready=methods["tone"] == "success",
            benchmark_ready=benchmark["tone"] == "success",
        )
        self.delivery_gate_next_value.setText(_ui_safe_text(next_action))
        self.delivery_gate_next_note.setText(_ui_safe_text(next_note))
        self.delivery_gate_next_value.setToolTip(_ui_safe_text(next_note))
        self.delivery_gate_next_note.setToolTip(_ui_safe_text(next_note))
        self._refresh_delivery_gate_hero(
            gate_text=gate_text,
            gate_tone=gate_tone,
            success_count=success_count,
            next_action=next_action,
            next_note=next_note,
        )

    def _refresh_report_command_deck(self, workspace: dict, report: dict, export_status: str) -> None:
        reports = dict(workspace.get("reports", {}) or {})
        summary = dict(workspace.get("summary", {}) or {})
        file_values = self._delivery_file_values(reports)
        benchmark_report = dict(reports.get("benchmark_cockpit", {}) or {})
        method_report = dict(reports.get("method_provenance", {}) or {})
        network = self._network_gate_summary(workspace, benchmark_report)
        benchmark = self._benchmark_gate_summary(workspace, benchmark_report)
        methods = self._method_gate_summary(method_report, file_values)
        exportable_count = self._safe_int(summary.get("exportable_reports", 0))
        report_ready = self._report_has_preview_payload(report) and exportable_count > 0
        export_done = self._export_status_is_done(export_status)

        gate_text = str(self.delivery_gate_chip.text() or "待生成")
        gate_tone = str(self.delivery_gate_chip.property("chipTone") or "warning")
        report_title = str(report.get("title", "当前报告") or "当前报告")
        selected_report = str(workspace.get("selected_report", "--") or "--")

        self._set_report_command_tile(
            "report",
            f"{exportable_count} 个" if exportable_count > 0 else "待生成",
            report_title,
            "success" if report_ready else "warning",
        )
        self._set_report_command_tile("gate", gate_text, self.delivery_gate_next_value.text(), gate_tone)
        self._set_report_command_tile("network", network["value"], network["note"], network["tone"])
        self._set_report_command_tile("benchmark", benchmark["value"], benchmark["note"], benchmark["tone"])
        self._set_report_command_tile("methods", methods["value"], methods["note"], methods["tone"])
        self._set_report_command_tile(
            "export",
            "已导出" if export_done else ("可导出" if exportable_count > 0 else "待运行"),
            f"report={selected_report} | {export_status}",
            "success" if export_done else ("accent" if exportable_count > 0 else "warning"),
        )

        tones = [
            "success" if report_ready else "warning",
            gate_tone,
            network["tone"],
            benchmark["tone"],
            methods["tone"],
            "success" if export_done else ("accent" if exportable_count > 0 else "warning"),
        ]
        success_count = sum(1 for tone in tones if tone == "success")
        if success_count >= 5:
            deck_text, deck_tone = "可交付", "success"
        elif exportable_count > 0 or report_ready:
            deck_text, deck_tone = "待复核", "accent"
        else:
            deck_text, deck_tone = "待生成", "warning"
        self._set_chip(self.report_command_chip, f"{deck_text} · {success_count}/6", deck_tone)
        self.report_command_deck.setProperty("commandStatus", deck_tone)
        self.report_command_deck.style().unpolish(self.report_command_deck)
        self.report_command_deck.style().polish(self.report_command_deck)

    def _set_report_command_tile(self, key: str, value: str, note: str, tone: str) -> None:
        value_label = self.report_command_values[key]
        note_label = self.report_command_notes[key]
        tile = self.report_command_tiles[key]
        value_label.setText(_ui_safe_text(value))
        note_label.setText(_ui_safe_text(note))
        value_label.setToolTip(_ui_safe_text(note))
        note_label.setToolTip(_ui_safe_text(note))
        status_text = {"success": "通过", "accent": "可用", "warning": "待复核"}.get(tone, "待复核")
        self._set_chip(self.report_command_chips[key], status_text, tone)
        tile.setProperty("commandTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def _set_delivery_gate_tile(self, key: str, value: str, note: str, tone: str) -> None:
        value_label, note_label, status_chip = self.delivery_gate_values[key]
        value_label.setText(_ui_safe_text(value))
        note_label.setText(_ui_safe_text(note))
        value_label.setToolTip(_ui_safe_text(note))
        note_label.setToolTip(_ui_safe_text(note))
        status_text = {"success": "通过", "accent": "可用", "warning": "复核"}.get(tone, "复核")
        self._set_chip(status_chip, status_text, tone)
        tile = self.delivery_gate_tiles.get(key)
        if tile is not None:
            tile.setProperty("gateTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _refresh_delivery_gate_hero(
        self,
        *,
        gate_text: str,
        gate_tone: str,
        success_count: int,
        next_action: str,
        next_note: str,
    ) -> None:
        self.delivery_gate_ready_value.setText(_ui_safe_text(gate_text))
        self._set_chip(self.delivery_gate_progress_badge, f"{success_count}/6 闭合", gate_tone)
        if gate_tone == "success":
            note = f"六项交付检查已闭合；下一步：{next_action}。"
        elif gate_tone == "accent":
            note = f"核心结果已可查看，但仍需复核；下一步：{next_action}。{next_note}"
        else:
            note = f"尚未形成完整交付链；下一步：{next_action}。{next_note}"
        self.delivery_gate_ready_note.setText(_ui_safe_text(note))
        self.delivery_gate_ready_value.setToolTip(_ui_safe_text(note))
        self.delivery_gate_ready_note.setToolTip(_ui_safe_text(next_note))

    def _delivery_next_action(
        self,
        *,
        report_ready: bool,
        exportable_count: int,
        export_done: bool,
        manifest_ready: bool,
        network_ready: bool,
        methods_ready: bool,
        benchmark_ready: bool,
    ) -> tuple[str, str]:
        if exportable_count <= 0:
            return "运行处理", "还没有可导出的真实运行结果。"
        if not report_ready:
            return "生成报告", "当前没有可预览报告，先运行处理或生成报告中心内容。"
        if not export_done:
            return "导出交付包", "报告已可用，下一步把 manifest、证据和网络校验写入交付目录。"
        if not manifest_ready:
            return "导出交付包", "当前导出状态存在，但尚未发现可追溯 manifest。"
        if not network_ready:
            return "补网络字段", "请检查 schema_target、validation_status 和 missing_fields。"
        if not methods_ready:
            return "检查方法溯源", "Footprint、不确定度、谱修正方法 rollup 还未闭合。"
        if not benchmark_ready:
            return "检查基准对标", "参考对标尚未激活或缺少通过率摘要。"
        return "交付归档", "交付链路已闭合，可以归档或打包给审阅者。"

    def _delivery_file_values(self, reports: dict) -> dict[str, str]:
        values: dict[str, str] = {}
        for payload in reports.values():
            if not isinstance(payload, dict):
                continue
            for key, value in dict(payload.get("file_info", {}) or {}).items():
                text = str(value or "").strip()
                if text:
                    values.setdefault(str(key), text)
        return values

    def _first_file_value(self, values: dict[str, str], keywords: tuple[str, ...]) -> str:
        for key, value in values.items():
            lower = key.lower()
            if any(keyword in lower for keyword in keywords):
                return value
        return ""

    def _report_has_preview_payload(self, report: dict) -> bool:
        return bool(
            report.get("title")
            and (
                report.get("metrics")
                or report.get("table_rows")
                or report.get("plot_series")
                or report.get("conclusions")
            )
        )

    def _network_gate_summary(self, workspace: dict, benchmark_report: dict) -> dict[str, str]:
        network_cfg = dict(workspace.get("network_output", {}) or {})
        schema_target = str(
            self._table_value(benchmark_report, "network.schema_target")
            or network_cfg.get("schema_target")
            or "--"
        )
        validation_status = str(self._table_value(benchmark_report, "network.validation_status") or "待校验")
        missing_text = str(self._table_value(benchmark_report, "network.missing_fields") or "待校验")
        missing_ok = missing_text.strip().lower() in {"", "--", "无", "none", "[]", "0"}
        status_lower = validation_status.strip().lower()
        validated = any(token in status_lower for token in ("valid", "pass", "ok", "ready", "success", "通过"))
        tone = "success" if validated and missing_ok else ("accent" if schema_target != "--" and missing_ok else "warning")
        return {
            "value": schema_target,
            "note": f"校验：{validation_status}；缺失：{missing_text}",
            "tone": tone,
        }

    def _benchmark_gate_summary(self, workspace: dict, benchmark_report: dict) -> dict[str, str]:
        bm_cfg = dict(workspace.get("benchmark", {}) or {})
        status = str(self._table_value(benchmark_report, "status") or bm_cfg.get("status") or "inactive")
        reference_id = str(self._table_value(benchmark_report, "reference_id") or bm_cfg.get("reference_id") or "--")
        pass_rate = str(self._table_value(benchmark_report, "pass_rate") or "--")
        failed_fields = str(self._table_value(benchmark_report, "failed_fields") or "待运行")
        status_lower = status.strip().lower()
        active = status_lower not in {"", "--", "inactive", "no_rp_result", "not_requested"}
        display_status = {
            "inactive": "未激活",
            "no_rp_result": "无 RP 结果",
            "not_requested": "未请求",
            "active": "已激活",
        }.get(status_lower, status or "未激活")
        tone = "success" if active and pass_rate != "--" else ("accent" if reference_id != "--" else "warning")
        return {
            "value": reference_id if reference_id != "--" else display_status,
            "note": f"状态：{display_status}；通过率：{pass_rate}；失败字段：{failed_fields}",
            "tone": tone,
        }

    def _method_gate_summary(self, method_report: dict, file_values: dict[str, str]) -> dict[str, str]:
        footprint = self._metric_value(method_report, "Footprint")
        uncertainty = self._metric_value(method_report, "不确定度")
        spectral = self._metric_value(method_report, "谱修正")
        method_rollup = self._first_file_value(file_values, ("method rollup", "method_rollup", "方法"))
        ready = bool(footprint and uncertainty and spectral)
        value = "已汇总" if ready else "待生成"
        methods = " / ".join(item for item in (footprint, uncertainty, spectral) if item) or "暂无方法摘要"
        note = f"{methods}" + (f"；Artifact：{method_rollup}" if method_rollup else "")
        return {"value": value, "note": note, "tone": "success" if ready else "warning"}

    def _table_value(self, report: dict, key: str) -> str:
        for row in list(report.get("table_rows", []) or []):
            if len(row) >= 2 and str(row[0]) == key:
                return str(row[1])
        return ""

    def _metric_value(self, report: dict, title: str) -> str:
        for metric_title, value in list(report.get("metrics", []) or []):
            if str(metric_title) == title:
                text = str(value or "").strip()
                return "" if text in {"--", "None"} else text
        return ""

    def _safe_int(self, value: object) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    def _normalize_view_mode(self, value: str) -> str:
        mapping = {
            "operations": "操作汇总",
            "operation": "操作汇总",
            "操作汇总": "操作汇总",
            "engineering": "工程诊断",
            "engineer": "工程诊断",
            "工程诊断": "工程诊断",
            "management": "管理汇报",
            "manager": "管理汇报",
            "管理汇报": "管理汇报",
        }
        return mapping.get(value.strip().lower(), mapping.get(value.strip(), "工程诊断"))

    def _export_status_is_done(self, export_status: str) -> bool:
        text = export_status.strip().lower()
        if not text or text in {"not_exported", "not exported yet", "尚未导出"}:
            return False
        return not any(token in text for token in ("not_exported", "not exported", "尚未导出", "未导出"))

    def _refresh_empty_state(self, workspace: dict, report: dict, export_status: str) -> None:
        summary = dict(workspace.get("summary", {}) or {})
        filters = dict(workspace.get("filters", {}) or {})
        exportable_count = self._safe_int(summary.get("exportable_reports", 0))
        has_real_result = exportable_count > 0
        self.empty_state_card.setVisible(not has_real_result)
        self._set_chip(self.empty_state_chip, "已生成" if has_real_result else "待运行", "success" if has_real_result else "warning")
        if hasattr(self, "closure_deck_chip"):
            self._set_chip(
                self.closure_deck_chip,
                "就绪" if has_real_result else "下一步",
                "success" if has_real_result else "warning",
            )

        selected_title = str(report.get("title", "当前报告") or "当前报告")
        batch_label = str(filters.get("batch", "") or "--")
        if has_real_result:
            gap_text = f"已发现 {exportable_count} 个可导出报告；当前批次：{batch_label}；导出状态：{export_status}。"
        else:
            gap_text = (
                f"当前页面：{selected_title}；尚未发现可导出的真实运行结果。"
                "建议先运行 EC 处理；生成真实窗口后，报告与导出动作会自动启用。"
            )
        self.empty_state_gap_label.setText(_ui_safe_text(gap_text))

        for key in ("生成报告", "导出"):
            button = self.empty_state_action_buttons.get(key)
            if button is not None:
                button.setEnabled(has_real_result)

    def _show_inspector_section(self, section: str) -> None:
        card = self.inspector_sections.get(section)
        if card is None:
            return
        self.inspector_stack.setCurrentWidget(card)
        for key, button in self.inspector_switches.items():
            button.blockSignals(True)
            button.setChecked(key == section)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_delivery_rail_mode(self, section: str) -> None:
        if not hasattr(self, "delivery_rail_sections"):
            return
        card = self.delivery_rail_sections.get(section)
        if card is None:
            return
        self.delivery_rail_stack.setCurrentWidget(card)
        for key, button in self.delivery_rail_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == section)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_delivery_focus(self, section: str) -> None:
        if not hasattr(self, "delivery_focus_sections"):
            return
        card = self.delivery_focus_sections.get(section)
        if card is None:
            return
        self._show_delivery_rail_mode("delivery")
        self.delivery_focus_stack.setCurrentWidget(card)
        for key, button in self.delivery_focus_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == section)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _refresh_inner_inspector(self, report: dict, export_status: str, view_mode: str) -> None:
        self._clear_layout(self.export_content)
        export_status_label = QLabel(_ui_safe_text(f"当前状态：{export_status}"))
        export_status_label.setObjectName("subtitle")
        export_status_label.setWordWrap(True)
        self.export_content.addWidget(chip(view_mode, "accent"))
        self.export_content.addWidget(export_status_label)
        for text in report.get("export_options", []):
            label = QLabel(_ui_safe_text(f"• {text}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.export_content.addWidget(label)

        self._clear_layout(self.file_content)
        for key, value in report.get("file_info", {}).items():
            label = QLabel(_ui_safe_text(f"{key}：{value}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.file_content.addWidget(label)

        self._clear_layout(self.version_content)
        for text in report.get("versions", []):
            label = QLabel(_ui_safe_text(f"• {text}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.version_content.addWidget(label)

        self._clear_layout(self.usage_content)
        for text in report.get("usage", []):
            label = QLabel(_ui_safe_text(f"• {text}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.usage_content.addWidget(label)

    def _refresh_batch_compare(self, batch_compare: dict) -> None:
        current_batch = str(batch_compare.get("current_batch", "") or "--")
        compare_batch = str(batch_compare.get("compare_batch", "") or "--")
        summary = [str(item) for item in batch_compare.get("difference_summary", [])]
        metric_deltas = dict(batch_compare.get("metric_deltas", {}))

        self.batch_current_value.setText(_ui_safe_text(current_batch))
        self.batch_compare_value.setText(_ui_safe_text(compare_batch))
        if metric_deltas:
            self.batch_diff_value.setText(
                " / ".join(
                    [
                        f"有效窗口 {int(metric_deltas.get('valid_window_delta', 0.0)):+d}",
                        f"滞后 {metric_deltas.get('average_lag_delta', 0.0):+.2f}s",
                        f"QC {metric_deltas.get('good_ratio_delta', 0.0):+.1%}",
                    ]
                )
            )
        else:
            self.batch_diff_value.setText(_ui_safe_text(f"{len(summary)} 项变化"))

        self._clear_layout(self.batch_summary_layout)
        batch_notes = summary[:2] + [str(item) for item in batch_compare.get("risk_summary", [])[:1]]
        for text in batch_notes:
            label = QLabel(_ui_safe_text(f"- {text}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.batch_summary_layout.addWidget(label)

        overflow = max(0, len(summary) + len(batch_compare.get("risk_summary", [])) - len(batch_notes))
        if overflow:
            label = QLabel(_ui_safe_text(f"另有 {overflow} 条批次说明，可在报告正文查看。"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.batch_summary_layout.addWidget(label)

    def _plot_note_for_mode(self, view_mode: str) -> str:
        notes = {
            "操作汇总": "操作视角优先保留状态趋势和是否可导出的结论，不展开过多工程细节。",
            "工程诊断": "工程视角保留更多诊断上下文，便于追溯异常来自设备、采集还是谱修正。",
            "管理汇报": "管理视角强调批次表现、风险数量和可直接汇报的话术。",
        }
        return notes.get(view_mode, notes["工程诊断"])

    def _conclusions_for_mode(self, report: dict, view_mode: str) -> list[str]:
        base = list(report.get("conclusions", []))
        if view_mode == "操作汇总":
            return base[:1] or ["当前报告可直接查看结论摘要。"]
        if view_mode == "管理汇报":
            return [base[0] if base else "当前批次整体可汇报。", "建议配合底部批次区一起说明差异。"]
        return base or ["当前报告暂无额外结论。"]

    def _inspector_card(self, title: str, subtitle: str) -> tuple[CardFrame, QVBoxLayout]:
        card = CardFrame(muted=True, role="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title(_ui_safe_text(title), _ui_safe_text(subtitle)))
        content = QVBoxLayout()
        content.setSpacing(TOKENS.spacing_sm)
        layout.addLayout(content)
        return card, content

    def _metric_card(self, title: str, value_widget: QLabel) -> CardFrame:
        card = CardFrame(muted=True, role="tile")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_xs)
        title_label = QLabel(_ui_safe_text(title))
        title_label.setObjectName("metricLabel")
        value_widget.setObjectName("metricValue")
        value_widget.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_widget)
        return card

    def _refresh_filter_options(self, workspace: dict) -> None:
        filters = workspace.get("filters", {})
        project_name = str(filters.get("project") or self.controller.project_profile.name or "当前项目")
        batch_lookup = workspace.get("batch_lookup", {})
        batch_labels = list(batch_lookup.keys())
        selected_batch = str(filters.get("batch", "")).strip()
        if selected_batch and selected_batch not in batch_labels:
            batch_labels.insert(0, selected_batch)
        self._replace_combo_items(self.project_combo, [project_name], keep_text=project_name)
        self._replace_combo_items(self.batch_combo, batch_labels, keep_text=selected_batch)

    def _replace_combo_items(self, combo: QComboBox, items: list[str], *, keep_text: str = "") -> None:
        combo.blockSignals(True)
        current_text = keep_text.strip() or combo.currentText().strip()
        combo.clear()
        for item in items:
            text = item.strip()
            if text:
                combo.addItem(text)
        if current_text:
            index = combo.findText(current_text)
            if index < 0:
                combo.addItem(current_text)
                index = combo.findText(current_text)
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        text = value.strip()
        combo.blockSignals(True)
        if not text:
            if combo.count() == 0:
                combo.setEditText("")
            combo.blockSignals(False)
            return
        index = combo.findText(text)
        if index < 0:
            combo.addItem(text)
            index = combo.findText(text)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _set_chip(self, label: QLabel, text: str, tone: str) -> None:
        label.setText(_ui_safe_text(text))
        label.setProperty("chipTone", tone)
        label.style().unpolish(label)
        label.style().polish(label)

    def _show_info(self, title: str, message: object) -> None:
        QMessageBox.information(self, _ui_safe_text(title), _ui_safe_text(message))

    def _set_official_bundle_path_display(self, path: str) -> None:
        self._official_bundle_path.setProperty("raw_path", path)
        self._official_bundle_path.setText(_ui_safe_text(path))

    def _official_bundle_path_value(self) -> str:
        raw_path = str(self._official_bundle_path.property("raw_path") or "")
        displayed_path = self._official_bundle_path.text().strip()
        if raw_path and displayed_path == _ui_safe_text(raw_path):
            return raw_path
        return displayed_path

    def _set_raw_line_edit_display(self, line_edit: QLineEdit, value: str) -> None:
        line_edit.setProperty("raw_value", value)
        line_edit.setText(_ui_safe_text(value))

    def _raw_line_edit_value(self, line_edit: QLineEdit) -> str:
        raw_value = str(line_edit.property("raw_value") or "")
        displayed_value = line_edit.text().strip()
        if raw_value and displayed_value == _ui_safe_text(raw_value):
            return raw_value
        return displayed_value

    def _sanitize_visible_labels(self) -> None:
        for label in self.findChildren(QLabel):
            safe = _ui_safe_text(label.text())
            if safe != label.text():
                label.setText(safe)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
