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
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, TOKENS, chip, section_title


UI_REFERENCE_REPLACEMENTS = (
    ("EddyPro", "行业参考"),
    ("EDDYPRO", "行业参考"),
    ("eddypro", "industry_reference"),
)


def _ui_safe_text(value: object) -> str:
    text = str(value)
    for old, new in UI_REFERENCE_REPLACEMENTS:
        text = text.replace(old, new)
    return text


REPORT_SECTIONS = [
    ("run_summary", "运行摘要", "适合第一眼确认本批次是否能交付。"),
    ("device_status", "设备状态报告", "把设备稳定性结论沉淀成报告视图。"),
    ("acquisition_quality", "采集质量报告", "用帧率、完整率和残余异常证明采集链路质量。"),
    ("ec_results", "EC 结果报告", "集中查看主结果、诊断字段和导出结构。"),
    ("spectral_qc", "谱修正与 QC 报告", "从谱修正和 QC 角度解释窗口质量。"),
    ("anomaly_events", "异常事件报告", "把日志与事件整理成可汇报的异常视图。"),
    ("site_method", "站点方法说明", "作为正式报告附录，说明结论来自哪些方法配置。"),
    ("evidence_pack", "证据包", "统一导出图表、表格与日志证据。"),
    ("fixture_pack", "Fixture Pack", "验证行业参考集、raw-to-final readiness、合成回归集与 YGAS 协议样例。"),
    ("eddypro_compare", "行业参考对标报告", "集中查看当前结果与行业参考结果的对标摘要和窗口差异。"),
    ("benchmark_cockpit", "Benchmark 驾驶舱", "查看 benchmark 参考对标结果：pass rate、阈值、偏差详情。"),
    ("method_provenance", "方法溯源", "查看 Footprint、不确定度、谱修正的方法来源、局限性和溯源信息。"),
    ("method_compare", "Method Compare", "查看方法族对比、参考方法 parity matrix、2D footprint contour 与长窗口性能 profile。"),
    ("computation_surface", "Computation Surface", "查看行业参考计算核心族 ready/blocked 状态、stress suite 与声明边界。"),
]


class ReportCenterPage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.report_items: dict[str, QTreeWidgetItem] = {}

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

        self.summary_row = self._build_summary_row()
        layout.addWidget(self.summary_row)

        body = QHBoxLayout()
        body.setSpacing(TOKENS.spacing_md)
        layout.addLayout(body, 1)

        self.tree_card = CardFrame(muted=True)
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_md)
        tree_layout.addWidget(section_title("报告目录", "按使用场景组织目录，让预览更像真正的报告中心。"))
        self.report_tree = QTreeWidget()
        self.report_tree.setHeaderHidden(True)
        self.report_tree.setIndentation(10)
        self.report_tree.itemSelectionChanged.connect(self._on_report_changed)
        tree_layout.addWidget(self.report_tree, 1)
        self.tree_card.setMinimumWidth(250)
        self.tree_card.setMaximumWidth(320)
        body.addWidget(self.tree_card, 0)

        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(TOKENS.spacing_md)
        center_scroll.setWidget(center_container)
        body.addWidget(center_scroll, 1)

        self.preview_header_card = CardFrame()
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

        self.preview_metrics_row = QWidget()
        metrics_layout = QGridLayout(self.preview_metrics_row)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setHorizontalSpacing(TOKENS.spacing_md)
        metrics_layout.setVerticalSpacing(TOKENS.spacing_md)
        self.preview_metric_values: list[QLabel] = []
        self.preview_metric_labels: list[QLabel] = []
        for index in range(4):
            card = CardFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            card_layout.setSpacing(TOKENS.spacing_xs)
            title = QLabel("--")
            title.setObjectName("metricLabel")
            value = QLabel("--")
            value.setObjectName("metricValue")
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            self.preview_metric_labels.append(title)
            self.preview_metric_values.append(value)
            metrics_layout.addWidget(card, 0, index)
        center_layout.addWidget(self.preview_metrics_row)

        self.preview_content_card = CardFrame()
        content_layout = QVBoxLayout(self.preview_content_card)
        content_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        content_layout.setSpacing(TOKENS.spacing_md)
        content_layout.addWidget(section_title("图表或表格预览", "让结果预览像报告，而不是文件清单。"))
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setBackground("transparent")
        self.preview_plot.showGrid(x=True, y=True, alpha=0.15)
        self.preview_plot.setLabel("left", "指标")
        self.preview_plot.setLabel("bottom", "序列")
        self.preview_curve = self.preview_plot.plot(pen=pg.mkPen("#2b6cbf", width=2.2))
        content_layout.addWidget(self.preview_plot, 1)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        content_layout.addWidget(self.preview_table)
        self.preview_plot_note = QLabel("--")
        self.preview_plot_note.setObjectName("subtitle")
        self.preview_plot_note.setWordWrap(True)
        content_layout.addWidget(self.preview_plot_note)
        center_layout.addWidget(self.preview_content_card, 1)

        self.conclusion_card = CardFrame(muted=True)
        conclusion_layout = QVBoxLayout(self.conclusion_card)
        conclusion_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        conclusion_layout.setSpacing(TOKENS.spacing_md)
        conclusion_layout.addWidget(section_title("关键结论说明", "操作员看结论，工程师看细节，管理层看可以直接汇报的话术。"))
        self.conclusion_content = QVBoxLayout()
        self.conclusion_content.setSpacing(TOKENS.spacing_sm)
        conclusion_layout.addLayout(self.conclusion_content)
        center_layout.addWidget(self.conclusion_card)

        self.inner_inspector = QWidget()
        inspector_layout = QVBoxLayout(self.inner_inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(TOKENS.spacing_md)
        self.inner_inspector.setMinimumWidth(320)
        self.inner_inspector.setMaximumWidth(360)
        body.addWidget(self.inner_inspector, 0)

        self.export_card, self.export_content = self._inspector_card("导出选项", "把当前报告的导出方式和出口统一放在这里。")
        self.file_card, self.file_content = self._inspector_card("文件信息", "不只显示路径，还要说明状态和用途。")
        self.version_card, self.version_content = self._inspector_card("版本与来源", "说明模板版本、来源批次和方法依据。")
        self.usage_card, self.usage_content = self._inspector_card("使用建议", "按操作员、工程师、管理汇报三个场景给出建议。")
        for card in (self.export_card, self.file_card, self.version_card, self.usage_card):
            inspector_layout.addWidget(card)
        inspector_layout.addStretch(1)

        self.batch_card = CardFrame()
        batch_layout = QVBoxLayout(self.batch_card)
        batch_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        batch_layout.setSpacing(TOKENS.spacing_md)
        batch_layout.addWidget(section_title("批次对比", "统一展示当前批次、对比批次和差异摘要。"))
        batch_row = QHBoxLayout()
        batch_row.setSpacing(TOKENS.spacing_md)
        self.batch_current_value = QLabel("--")
        self.batch_compare_value = QLabel("--")
        self.batch_diff_value = QLabel("--")
        batch_row.addWidget(self._metric_card("当前批次", self.batch_current_value), 1)
        batch_row.addWidget(self._metric_card("对比批次", self.batch_compare_value), 1)
        batch_row.addWidget(self._metric_card("差异摘要", self.batch_diff_value), 1)
        batch_layout.addLayout(batch_row)
        self.batch_summary_layout = QVBoxLayout()
        self.batch_summary_layout.setSpacing(TOKENS.spacing_sm)
        batch_layout.addLayout(self.batch_summary_layout)
        layout.addWidget(self.batch_card)

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
        self._set_combo_text(self.project_combo, str(filters.get("project", self.controller.project_profile.name or "Current Project")))
        self._set_combo_text(self.batch_combo, str(filters.get("batch", "")))
        self._set_combo_text(self.view_mode_combo, str(filters.get("view_mode", "Engineering")))

        self.recent_status_value.setText(str(summary.get("recent_status", "--")))
        self.exportable_count_value.setText(str(summary.get("exportable_reports", "--")))
        self.attention_count_value.setText(str(summary.get("attention_count", "--")))
        self.last_generated_value.setText(str(summary.get("last_generated_at", "--")))

        self._set_chip(self.summary_chips["recent_status"], "Run Ready", "success")
        self._set_chip(self.summary_chips["exportable"], "Exportable", "accent")
        attention_tone = "warning" if int(summary.get("attention_count", 0)) > 0 else "success"
        self._set_chip(self.summary_chips["attention"], "Review Needed" if attention_tone == "warning" else "Risk Controlled", attention_tone)
        self._set_chip(self.summary_chips["generated"], "Updated", "accent")

        selected_report = str(workspace.get("selected_report", "run_summary"))
        self._sync_tree(selected_report)
        report = workspace["reports"][selected_report]
        view_mode = str(filters.get("view_mode", "Engineering"))
        self._refresh_preview(report, view_mode, filters)
        self._refresh_inner_inspector(report, workspace.get("export_status", "Not exported yet"), view_mode)
        self._refresh_batch_compare(workspace.get("batch_compare", {}))
        self._sanitize_visible_labels()

    def _build_filter_bar(self) -> CardFrame:
        card = CardFrame()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("Report Filters", "Drive preview and export from the real project and run batches."))
        layout.addStretch(1)

        self.project_combo = QComboBox()
        self.project_combo.setEditable(True)
        self.batch_combo = QComboBox()
        self.batch_combo.setEditable(True)
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["Operations", "Engineering", "Management"])

        layout.addWidget(QLabel("Project"))
        layout.addWidget(self.project_combo)
        layout.addWidget(QLabel("Run Batch"))
        layout.addWidget(self.batch_combo)
        layout.addWidget(QLabel("View"))
        layout.addWidget(self.view_mode_combo)

        buttons = [
            ("Refresh", self._refresh_workspace, False),
            ("Generate Report", self._generate_report, True),
            ("Export Report", self._export_current_report, False),
            ("Export Evidence", self._export_evidence, False),
            ("Compare Batches", self._compare_batches, False),
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

    def _build_summary_row(self) -> QWidget:
        wrapper = QWidget()
        layout = QGridLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(TOKENS.spacing_md)
        layout.setVerticalSpacing(TOKENS.spacing_md)

        self.recent_status_value = QLabel("--")
        self.exportable_count_value = QLabel("--")
        self.attention_count_value = QLabel("--")
        self.last_generated_value = QLabel("--")
        self.summary_chips: dict[str, QLabel] = {}
        cards = [
            ("recent_status", "最近运行状态", self.recent_status_value),
            ("exportable", "可导出报告数量", self.exportable_count_value),
            ("attention", "待关注异常数量", self.attention_count_value),
            ("generated", "最近生成时间", self.last_generated_value),
        ]
        for index, (key, title, value) in enumerate(cards):
            card = CardFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            card_layout.setSpacing(TOKENS.spacing_sm)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            card_layout.addWidget(label)
            value.setObjectName("metricValue")
            value.setWordWrap(True)
            card_layout.addWidget(value)
            tone_chip = chip("就绪", "accent" if index != 2 else "warning")
            self.summary_chips[key] = tone_chip
            card_layout.addWidget(tone_chip)
            layout.addWidget(card, 0, index)
        return wrapper

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

    def _refresh_preview(self, report: dict, view_mode: str, filters: dict) -> None:
        self._set_chip(self.preview_mode_chip, view_mode, "accent")
        self.preview_title_label.setText(_ui_safe_text(report.get("title", "Report Preview")))
        self.preview_source_label.setText(
            _ui_safe_text(
                f"Source: {report.get('source', '--')}\nBatch: {filters.get('batch', '--')}  |  Time: {report.get('updated_at', '--')}"
            )
        )

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
        if is_benchmark_cockpit:
            self.preview_plot_note.setText("Per-window pass/fail (1=pass, 0=fail)")
        else:
            self.preview_plot_note.setText(self._plot_note_for_mode(view_mode))

        headers = report.get("table_headers", ["Item", "Value", "Note"])
        rows = list(report.get("table_rows", []))
        is_eddypro_compare = str(report.get("report_key", "")) == "eddypro_compare"
        if not is_eddypro_compare and not is_benchmark_cockpit:
            if view_mode == "Operations":
                rows = rows[:3]
            elif view_mode == "Management":
                rows = rows[:2]
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels([_ui_safe_text(header) for header in headers])
        self.preview_table.setRowCount(len(rows))
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
            self._benchmark_controls_layout.addWidget(section_title("Benchmark 操作", "选择参考、调整阈值、刷新结果"))
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

    def _build_official_raw_bundle_controls(self, report: dict) -> None:
        if not hasattr(self, "_official_bundle_controls_card"):
            self._official_bundle_controls_card = CardFrame(muted=True)
            self._official_bundle_controls_layout = QVBoxLayout(self._official_bundle_controls_card)
            self._official_bundle_controls_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            self._official_bundle_controls_layout.setSpacing(TOKENS.spacing_sm)
            self._official_bundle_controls_layout.addWidget(
                section_title("Official Raw Bundle", "Inspect or register a real industry-reference raw-to-final fixture bundle.")
            )
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(TOKENS.spacing_md)
            ctrl_row.addWidget(QLabel("Bundle:"))
            self._official_bundle_path = QLineEdit()
            self._official_bundle_path.setPlaceholderText("references/industry_reference/official_raw/site_001")
            ctrl_row.addWidget(self._official_bundle_path, 1)
            self._official_bundle_browse = QPushButton("Browse")
            self._official_bundle_build_manifest = QPushButton("Build Manifest")
            self._official_bundle_inspect = QPushButton("Inspect")
            self._official_bundle_validate = QPushButton("Validate P0")
            self._official_bundle_evidence_pack = QPushButton("Evidence Pack")
            self._official_bundle_acceptance = QPushButton("Run Acceptance")
            self._official_bundle_register = QPushButton("Register")
            self._official_bundle_register.setProperty("variant", "primary")
            self._official_bundle_build_tree_manifests = QPushButton("Build Tree Manifests")
            self._official_bundle_inspect_tree = QPushButton("Inspect Tree")
            self._official_bundle_register_tree = QPushButton("Register Tree")
            self._public_fixture_refresh = QPushButton("Refresh Public Fixtures")
            self._public_fixture_overwrite = QCheckBox("Overwrite Public")
            self._official_bundle_replace = QCheckBox("Replace")
            ctrl_row.addWidget(self._official_bundle_browse)
            ctrl_row.addWidget(self._official_bundle_build_manifest)
            ctrl_row.addWidget(self._official_bundle_inspect)
            ctrl_row.addWidget(self._official_bundle_validate)
            ctrl_row.addWidget(self._official_bundle_evidence_pack)
            ctrl_row.addWidget(self._official_bundle_acceptance)
            ctrl_row.addWidget(self._official_bundle_register)
            ctrl_row.addWidget(self._official_bundle_build_tree_manifests)
            ctrl_row.addWidget(self._official_bundle_inspect_tree)
            ctrl_row.addWidget(self._official_bundle_register_tree)
            ctrl_row.addWidget(self._public_fixture_refresh)
            ctrl_row.addWidget(self._public_fixture_overwrite)
            ctrl_row.addWidget(self._official_bundle_replace)
            self._official_bundle_controls_layout.addLayout(ctrl_row)
            run_row = QHBoxLayout()
            run_row.setSpacing(TOKENS.spacing_md)
            run_row.addWidget(QLabel("Reference Run:"))
            self._official_run_command = QLineEdit()
            self._official_run_command.setPlaceholderText("reference_processor.exe --run reference/project.config")
            self._official_run_version = QLineEdit()
            self._official_run_version.setPlaceholderText("7.0.9")
            self._official_run_outputs = QLineEdit()
            self._official_run_outputs.setPlaceholderText("reference/reference_full_output.csv")
            self._official_run_capture = QPushButton("Capture Run")
            self._official_closure_run = QPushButton("Closure Run")
            self._official_closure_run.setProperty("variant", "primary")
            run_row.addWidget(self._official_run_command, 2)
            run_row.addWidget(QLabel("Version"))
            run_row.addWidget(self._official_run_version)
            run_row.addWidget(QLabel("Outputs"))
            run_row.addWidget(self._official_run_outputs)
            run_row.addWidget(self._official_run_capture)
            run_row.addWidget(self._official_closure_run)
            self._official_bundle_controls_layout.addLayout(run_row)
            filter_row = QHBoxLayout()
            filter_row.setSpacing(TOKENS.spacing_md)
            filter_row.addWidget(QLabel("Matrix:"))
            self._official_matrix_format = QComboBox()
            self._official_matrix_site = QComboBox()
            self._official_matrix_parity = QComboBox()
            self._official_matrix_fixture = QComboBox()
            self._official_matrix_apply = QPushButton("Apply Filter")
            self._official_fixture_detail = QPushButton("Detail")
            self._official_fixture_rerun = QPushButton("Rerun Fixture")
            self._official_fixture_disable = QPushButton("Disable Fixture")
            self._official_fixture_replace = QPushButton("Replace Fixture")
            filter_row.addWidget(QLabel("Format"))
            filter_row.addWidget(self._official_matrix_format)
            filter_row.addWidget(QLabel("Site"))
            filter_row.addWidget(self._official_matrix_site)
            filter_row.addWidget(QLabel("Parity"))
            filter_row.addWidget(self._official_matrix_parity)
            filter_row.addWidget(QLabel("Fixture"))
            filter_row.addWidget(self._official_matrix_fixture, 1)
            filter_row.addWidget(self._official_matrix_apply)
            filter_row.addWidget(self._official_fixture_detail)
            filter_row.addWidget(self._official_fixture_rerun)
            filter_row.addWidget(self._official_fixture_disable)
            filter_row.addWidget(self._official_fixture_replace)
            self._official_bundle_controls_layout.addLayout(filter_row)
            self._official_bundle_status = QLabel("--")
            self._official_bundle_status.setObjectName("subtitle")
            self._official_bundle_status.setWordWrap(True)
            self._official_bundle_controls_layout.addWidget(self._official_bundle_status)
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
            ["All"] + sorted({str(row.get("raw_format", "")) for row in matrix_rows if row.get("raw_format")}),
            keep_text=str(filters.get("raw_format", "") or "All"),
        )
        self._replace_combo_items(
            self._official_matrix_site,
            ["All"] + sorted({str(row.get("site_class", "")) for row in matrix_rows if row.get("site_class")}),
            keep_text=str(filters.get("site_class", "") or "All"),
        )
        self._replace_combo_items(
            self._official_matrix_parity,
            ["All"] + sorted({str(row.get("parity_status", "") or row.get("status", "")) for row in matrix_rows if row.get("parity_status") or row.get("status")}),
            keep_text=str(filters.get("parity_status", "") or "All"),
        )
        fixture_ids = [str(row.get("fixture_id", "")) for row in matrix_rows if row.get("fixture_id")]
        self._replace_combo_items(
            self._official_matrix_fixture,
            fixture_ids,
            keep_text=selected_fixture or (fixture_ids[0] if fixture_ids else ""),
        )
        public_state = dict(self.controller.report_center_workspace.get("public_eddypro_fixtures", {}) or {})
        status_parts = [str(state.get("message", "No official raw bundle has been inspected yet."))]
        if public_state.get("message"):
            status_parts.append(str(public_state.get("message")))
        self._official_bundle_status.setText(" | ".join(status_parts))
        self._official_bundle_controls_card.setVisible(True)
        parent = self._official_bundle_controls_card.parent()
        if parent is None and hasattr(self, "preview_content_card"):
            parent_layout = self.preview_content_card.parent().layout()
            if parent_layout:
                idx = parent_layout.indexOf(self.preview_content_card)
                if idx >= 0:
                    parent_layout.insertWidget(idx + 1, self._official_bundle_controls_card)

    def _append_official_raw_fixture_detail(self, report: dict) -> None:
        detail = dict(report.get("official_raw_selected_fixture_detail", {}) or {})
        if not detail:
            selected = str(report.get("official_raw_selected_fixture_id", "") or "").strip()
            if selected:
                hint = QLabel(f"Selected fixture: {selected}. Click Detail to generate the single-fixture audit artifact.")
                hint.setObjectName("subtitle")
                hint.setWordWrap(True)
                self.conclusion_content.addWidget(hint)
            return

        fixture_id = str(detail.get("fixture_id", "") or "--")
        header = QLabel(f"Official Raw Fixture Detail: {fixture_id}")
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
        selected = QFileDialog.getExistingDirectory(self, "Select official reference raw bundle")
        if selected:
            self._set_official_bundle_path_display(selected)

    def _on_official_bundle_inspect(self) -> None:
        result = self.controller.inspect_official_raw_bundle_for_report_center(self._official_bundle_path_value())
        self._show_info("Official Raw Bundle", result["message"])
        self.refresh()

    def _on_official_bundle_validate(self) -> None:
        result = self.controller.validate_official_raw_bundle_for_report_center(self._official_bundle_path_value())
        self._show_info("Official Raw P0 Gate", result["message"])
        self.refresh()

    def _on_official_bundle_evidence_pack(self) -> None:
        result = self.controller.export_official_raw_evidence_pack_for_report_center(self._official_bundle_path_value())
        self._show_info("Official Raw Evidence Pack", result["message"])
        self.refresh()

    def _on_official_bundle_acceptance(self) -> None:
        result = self.controller.run_official_raw_evidence_acceptance_for_report_center(self._official_bundle_path_value())
        self._show_info("Official Raw Acceptance", result["message"])
        self.refresh()

    def _on_official_run_capture(self) -> None:
        result = self.controller.capture_official_eddypro_run_for_report_center(
            self._official_bundle_path_value(),
            command=self._raw_line_edit_value(self._official_run_command),
            software_version=self._official_run_version.text(),
            output_files=self._raw_line_edit_value(self._official_run_outputs),
        )
        self._show_info("Official Reference Run", result["message"])
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
        self._show_info("Official Raw Closure", result["message"])
        self.refresh()

    def _on_official_bundle_build_manifest(self) -> None:
        result = self.controller.build_official_raw_bundle_manifest_for_report_center(
            self._official_bundle_path_value(),
            overwrite=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("Official Raw Manifest", result["message"])
        self.refresh()

    def _on_official_bundle_register(self) -> None:
        result = self.controller.register_official_raw_bundle_for_report_center(
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("Official Raw Bundle", result["message"])
        self.refresh()

    def _on_official_bundle_inspect_tree(self) -> None:
        result = self.controller.inspect_official_raw_bundle_tree_for_report_center(self._official_bundle_path_value())
        self._show_info("Official Raw Bundle Tree", result["message"])
        self.refresh()

    def _on_official_bundle_build_tree_manifests(self) -> None:
        result = self.controller.build_official_raw_bundle_tree_manifests_for_report_center(
            self._official_bundle_path_value(),
            overwrite=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("Official Raw Bundle Tree", result["message"])
        self.refresh()

    def _on_official_bundle_register_tree(self) -> None:
        result = self.controller.register_official_raw_bundle_tree_for_report_center(
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("Official Raw Bundle Tree", result["message"])
        self.refresh()

    def _on_public_fixture_refresh(self) -> None:
        result = self.controller.refresh_public_eddypro_fixtures_for_report_center(
            overwrite=bool(self._public_fixture_overwrite.isChecked())
        )
        self._show_info("Public Reference Fixtures", result["message"])
        self.refresh()

    def _on_official_matrix_filter(self) -> None:
        def value(combo: QComboBox) -> str:
            text = combo.currentText().strip()
            return "" if text == "All" else text

        result = self.controller.set_official_raw_matrix_filters_for_report_center(
            raw_format=value(self._official_matrix_format),
            site_class=value(self._official_matrix_site),
            parity_status=value(self._official_matrix_parity),
        )
        self._show_info("Official Raw Matrix", result["message"])
        self.refresh()

    def _selected_official_fixture_id(self) -> str:
        fixture_id = self._official_matrix_fixture.currentText().strip()
        if fixture_id:
            self.controller.select_official_raw_fixture_for_report_center(fixture_id)
        return fixture_id

    def _on_official_fixture_rerun(self) -> None:
        result = self.controller.rerun_official_raw_fixture_for_report_center(self._selected_official_fixture_id())
        self._show_info("Official Raw Fixture", result["message"])
        self.refresh()

    def _on_official_fixture_detail(self) -> None:
        result = self.controller.inspect_official_raw_fixture_detail_for_report_center(self._selected_official_fixture_id())
        self._show_info("Official Raw Fixture Detail", result["message"])
        self.refresh()

    def _on_official_fixture_disable(self) -> None:
        result = self.controller.disable_official_raw_fixture_for_report_center(self._selected_official_fixture_id())
        self._show_info("Official Raw Fixture", result["message"])
        self.refresh()

    def _on_official_fixture_replace(self) -> None:
        result = self.controller.replace_official_raw_fixture_for_report_center(
            self._selected_official_fixture_id(),
            self._official_bundle_path_value(),
            replace=bool(self._official_bundle_replace.isChecked()),
        )
        self._show_info("Official Raw Fixture", result["message"])
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
                        f"Valid {int(metric_deltas.get('valid_window_delta', 0.0)):+d}",
                        f"Lag {metric_deltas.get('average_lag_delta', 0.0):+.2f}s",
                        f"QC {metric_deltas.get('good_ratio_delta', 0.0):+.1%}",
                    ]
                )
            )
        else:
            self.batch_diff_value.setText(_ui_safe_text(f"{len(summary)} changes"))

        self._clear_layout(self.batch_summary_layout)
        for text in summary[:4]:
            label = QLabel(_ui_safe_text(f"- {text}"))
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.batch_summary_layout.addWidget(label)

        for text in batch_compare.get("risk_summary", [])[:2]:
            label = QLabel(_ui_safe_text(f"- {text}"))
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
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title(_ui_safe_text(title), _ui_safe_text(subtitle)))
        content = QVBoxLayout()
        content.setSpacing(TOKENS.spacing_sm)
        layout.addLayout(content)
        return card, content

    def _metric_card(self, title: str, value_widget: QLabel) -> CardFrame:
        card = CardFrame()
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
        project_name = str(filters.get("project") or self.controller.project_profile.name or "Current Project")
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
