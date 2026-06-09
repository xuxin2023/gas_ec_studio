from __future__ import annotations

import json

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, PLOT_SERIES_COLORS, TOKENS, chip, configure_plot_theme, section_title


EC_STEPS = [
    ("window_sampling", "窗口与采样", "先定义处理窗口和采样节奏，后续步骤才能对齐。"),
    ("data_cleaning", "数据清洗", "把缺测、尖峰和异常值处理策略说清楚。"),
    ("screening", "统计筛选", "配置偏度、峰度、dropout 等统计筛选阈值，控制 QC 诊断灵敏度。"),
    ("lag", "lag", "让用户看到时滞搜索范围与协方差曲线，不把 lag 做成黑箱。"),
    ("rotation", "坐标旋转", "明确使用哪种旋转方法以及适用场景。"),
    ("crosswind_correction", "Crosswind", "Configure sonic-temperature crosswind correction with explicit manufacturer/model provenance."),
    ("detrend", "去趋势", "说明使用哪种去趋势策略，避免隐藏对结果的影响。"),
    ("covariance", "协方差", "把核心协方差估计方式显式展示出来。"),
    ("density_correction", "密度/混合比修正", "展示修正前后变化，避免只给最终结果。"),
    ("steadiness", "稳态检验", "为有效性分级提供可理解的判据。"),
    ("turbulence", "湍流检验", "把稳定度与 u* 判断放在同一语境中。"),
    ("uncertainty", "不确定度", "保留来源拆分，降低黑箱感。"),
    ("output", "输出", "控制最终字段、诊断摘要和结果去向。"),
]

WORKFLOW_LENSES = [
    ("project", "项目与元数据", "原始格式、分析仪元数据、清洗和统计筛选入口。", ["window_sampling", "data_cleaning", "screening"]),
    ("core", "核心通量链", "时滞、旋转、去趋势、协方差和密度修正。", ["lag", "rotation", "detrend", "covariance", "density_correction"]),
    ("advanced", "高级方法族", "横风、稳态、湍流、足迹、不确定度和谱修正。", ["crosswind_correction", "steadiness", "turbulence", "uncertainty"]),
    ("delivery", "输出与交付", "完整输出、诊断摘要、对标和网络格式闭合。", ["output"]),
]


class ECProcessingPage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.step_indexes: dict[str, int] = {}
        self.step_items: dict[str, QTreeWidgetItem] = {}
        self.workflow_lens_buttons: dict[str, QPushButton] = {}
        self.workflow_lens_notes: dict[str, QLabel] = {}
        self.coverage_values: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "EC 处理",
                "把流程拆成可理解的步骤，并在关键节点保留中间结果，让操作员与工程师都能看懂当前在做什么。",
            )
        )

        self.run_bar = self._build_run_bar()
        layout.addWidget(self.run_bar)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        layout.addWidget(body, 1)

        self.tree_card = CardFrame(muted=True, role="rail")
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_md)
        tree_layout.addWidget(section_title("处理树", "按步骤理解配置与结果，中间结果始终和参数同屏出现。"))
        self.step_tree = QTreeWidget()
        self.step_tree.setObjectName("workflowTree")
        self.step_tree.setHeaderHidden(True)
        self.step_tree.setIndentation(10)
        self.step_tree.itemSelectionChanged.connect(self._on_step_changed)
        tree_layout.addWidget(self.step_tree, 1)
        self.tree_card.setMinimumWidth(260)
        self.tree_card.setMaximumWidth(320)
        body.addWidget(self.tree_card)

        self.content_stack = QStackedWidget()
        body.addWidget(self.content_stack)

        self.desktop_rail = self._build_desktop_rail()
        body.addWidget(self.desktop_rail)
        body.setSizes([260, 840, 340])

        self._build_tree()
        self._build_pages()
        self._bind_preview_signals()

        self.controller.processing_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self._sync_step_from_controller)
        self.refresh()

    def refresh(self) -> None:
        run_cfg = self.controller.ec_processing["run"]
        steps = self.controller.ec_processing["steps"]

        self._set_combo_text(self.data_source_combo, str(run_cfg.get("data_source", "当前项目高频目录")))
        self._set_combo_text(self.time_range_combo, str(run_cfg.get("time_range", "最近 24 小时")))

        window_step = steps["window_sampling"]
        self.window_minutes_spin.setValue(int(window_step.get("window_minutes", 30) or 30))
        self.window_sample_hz_spin.setValue(int(window_step.get("sample_hz", 20) or 20))

        cleaning_step = steps["data_cleaning"]
        self.clean_spike_sigma_spin.setValue(float(cleaning_step.get("spike_sigma", 5.0) or 5.0))
        self._set_combo_text(self.clean_missing_policy_combo, str(cleaning_step.get("missing_policy", "")))
        self.clean_removed_ratio_label.setText(str(cleaning_step.get("removed_ratio", "--")))

        screening_step = steps.get("screening", {})
        self.screening_skewness_spin.setValue(float(screening_step.get("skewness_threshold", 2.0) or 2.0))
        self.screening_kurtosis_spin.setValue(float(screening_step.get("kurtosis_threshold", 7.0) or 7.0))
        self.screening_dropout_min_run_spin.setValue(int(screening_step.get("dropout_min_run", 10) or 10))
        self.screening_spike_sigma_spin.setValue(float(screening_step.get("spike_sigma", 5.0) or 5.0))
        self.screening_discontinuity_sigma_spin.setValue(float(screening_step.get("discontinuity_sigma", 8.0) or 8.0))
        abs_limits_text = screening_step.get("absolute_limits_text", "")
        if abs_limits_text:
            self.screening_absolute_limits_edit.setText(str(abs_limits_text))

        lag_step = steps["lag"]
        self.lag_search_window_spin.setValue(float(lag_step.get("search_window_s", 8.0) or 8.0))
        self.lag_expected_spin.setValue(float(lag_step.get("expected_lag_s", 2.4) or 2.4))
        self._set_combo_text(self.lag_strategy_combo, str(lag_step.get("lag_strategy", "协方差最大")))

        self._set_combo_text(self.rotation_mode_combo, str(steps["rotation"].get("rotation_mode", "双旋转")))
        crosswind_step = steps.get("crosswind_correction", {})
        self.crosswind_enable_combo.setCurrentIndex(0 if crosswind_step.get("enabled", False) else 1)
        self._set_combo_text(self.crosswind_method_combo, str(crosswind_step.get("method", "liu_2001_crosswind_v1")))
        self._set_combo_text(self.crosswind_manufacturer_combo, str(crosswind_step.get("sonic_manufacturer", "gill")))
        self._set_combo_text(self.crosswind_model_combo, str(crosswind_step.get("sonic_model", "wm")))
        self.crosswind_temp_divisor_spin.setValue(float(crosswind_step.get("temperature_divisor", 1209.0) or 1209.0))
        coefficients_text = str(crosswind_step.get("coefficients_text", "") or "").strip()
        if not coefficients_text and isinstance(crosswind_step.get("coefficients"), dict):
            coefficients_text = json.dumps(crosswind_step.get("coefficients"), ensure_ascii=False)
        self.crosswind_coefficients_edit.setPlainText(coefficients_text)
        self._set_combo_text(self.detrend_mode_combo, str(steps["detrend"].get("detrend_mode", "块均值")))
        self._set_combo_text(self.covariance_mode_combo, str(steps["covariance"].get("covariance_mode", "标准协方差")))
        self._set_combo_text(self.density_correction_combo, str(steps["density_correction"].get("correction_mode", "WPL")))
        self._set_combo_text(self.steadiness_rule_combo, str(steps["steadiness"].get("steadiness_rule", "Foken-like")))
        self._set_combo_text(self.ustar_rule_combo, str(steps["turbulence"].get("ustar_rule", "站点阈值")))
        footprint_step = steps.get("footprint", {})
        self._set_combo_text(self.footprint_method_combo, str(footprint_step.get("method", "kljun")))
        self.footprint_enable_combo.setCurrentIndex(0 if footprint_step.get("enabled", True) else 1)
        self.footprint_zm_spin.setValue(float(footprint_step.get("z_m", 3.0) or 3.0))
        self.footprint_canopy_spin.setValue(float(footprint_step.get("canopy_height_m", 5.0) or 5.0))
        self.footprint_z0_spin.setValue(float(footprint_step.get("z0", 0.12) or 0.12))
        self.footprint_ol_spin.setValue(float(footprint_step.get("ol", 0.0) or 0.0))
        self.footprint_grid_combo.setCurrentIndex(0 if footprint_step.get("grid_enabled", True) else 1)
        self.footprint_grid_x_spin.setValue(int(footprint_step.get("grid_x_bins", 32) or 32))
        self.footprint_grid_y_spin.setValue(int(footprint_step.get("grid_y_bins", 25) or 25))

        uncertainty_step = steps.get("uncertainty", {})
        self._set_combo_text(
            self.uncertainty_mode_combo,
            str(uncertainty_step.get("method") or uncertainty_step.get("uncertainty_mode", "mann_lenschow")),
        )
        self.uncertainty_timescale_spin.setValue(float(uncertainty_step.get("integral_timescale_s", 5.0) or 5.0))
        self.uncertainty_confidence_spin.setValue(float(uncertainty_step.get("confidence_level", 0.95) or 0.95))

        spectral_step = steps.get("spectral_correction", {})
        self._set_combo_text(self.spectral_method_combo, str(spectral_step.get("method", "massman")))
        self.spectral_enable_combo.setCurrentIndex(0 if spectral_step.get("enabled", True) else 1)
        self.spectral_path_spin.setValue(float(spectral_step.get("path_length_m", 0.15) or 0.15))
        self.spectral_sep_spin.setValue(float(spectral_step.get("sensor_sep_m", 0.20) or 0.20))
        self.spectral_response_spin.setValue(float(spectral_step.get("response_time_s", 0.1) or 0.1))
        self.spectral_zm_spin.setValue(float(spectral_step.get("z_m", 3.0) or 3.0))
        self.spectral_ol_spin.setValue(float(spectral_step.get("ol", 0.0) or 0.0))
        self.spectral_cospectrum_combo.setCurrentIndex(0 if spectral_step.get("use_fcc_measured_cospectrum", True) else 1)
        primary_step = dict(steps.get("primary_analyzer", {}) or {})
        primary_snapshot = self.controller._primary_analyzer_config_snapshot(
            selected=self.controller.selected_device(),
            existing=primary_step,
        )
        primary_profile_id = str(primary_snapshot.get("profile_id", "ygas_irga"))
        self._set_combo_data(self.primary_analyzer_profile_combo, primary_profile_id)
        self.primary_analyzer_enable_combo.setCurrentIndex(0 if primary_snapshot.get("enabled", True) else 1)
        warning_value = primary_step.get(
            "min_signal_warning_pct",
            primary_step.get("min_signal_warning", primary_snapshot.get("min_signal_warning_pct", primary_snapshot.get("min_signal_warning", 0.10))),
        )
        fail_value = primary_step.get(
            "min_signal_fail_pct",
            primary_step.get("min_signal_fail", primary_snapshot.get("min_signal_fail_pct", primary_snapshot.get("min_signal_fail", 0.0))),
        )
        warning_pct = float(warning_value or 0.0)
        fail_pct = float(fail_value or 0.0)
        if primary_profile_id == "ygas_irga":
            warning_pct = warning_pct * 100.0 if warning_pct <= 1.0 else warning_pct
            fail_pct = fail_pct * 100.0 if fail_pct <= 1.0 else fail_pct
        self.primary_signal_warning_spin.setValue(warning_pct)
        self.primary_signal_fail_spin.setValue(fail_pct)
        self.primary_require_status_combo.setCurrentIndex(0 if primary_snapshot.get("require_status_ok", True) else 1)
        if "require_cell_thermodynamics" in primary_step:
            self.primary_cell_thermo_combo.setCurrentText("required" if primary_snapshot.get("require_cell_thermodynamics") else "not_required")
        else:
            self.primary_cell_thermo_combo.setCurrentText("auto")
        allowed_words = primary_snapshot.get("allowed_diagnostic_words", [0])
        if isinstance(allowed_words, (list, tuple)):
            self.primary_allowed_diag_words_edit.setText(",".join(str(value) for value in allowed_words))
        else:
            self.primary_allowed_diag_words_edit.setText(str(allowed_words or "0"))
        self.primary_calibration_profile_edit.setText(str(primary_snapshot.get("calibration_profile_id", "")))
        self.primary_source_file_edit.setText(str(primary_snapshot.get("source_file", "")))
        self.primary_normalization_command_edit.setText(str(primary_snapshot.get("normalization_command", "")))
        method_compare_step = steps.get("method_compare", {})
        self.method_compare_combo.setCurrentIndex(0 if method_compare_step.get("enabled", True) else 1)
        self.method_compare_threshold_spin.setValue(float(method_compare_step.get("deviation_threshold", 0.25) or 0.25))
        self.output_fields_edit.setText(str(steps["output"].get("output_fields", "")))
        self._set_combo_text(self.full_output_mode_combo, str(steps["output"].get("full_output_mode", "only_available")))

        self._refresh_run_bar()
        self._refresh_processing_cockpit()
        self._refresh_window_preview()
        self._refresh_cleaning_preview()
        self._refresh_screening_preview()
        self._refresh_lag_preview()
        self._refresh_covariance_preview()
        self._refresh_density_preview()
        self._refresh_rotation_preview()
        self._refresh_crosswind_preview()
        self._refresh_detrend_preview()
        self._refresh_steadiness_preview()
        self._refresh_turbulence_preview()
        self._refresh_uncertainty_preview()
        self._refresh_primary_analyzer_preview()
        self._refresh_output_preview()
        self._refresh_output_coverage_panel()
        self._sync_step_from_controller()

    def _build_run_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        intro = section_title("运行条", "先选择数据来源与时间范围，再决定正式运行还是仅做预检查。")
        layout.addWidget(intro)
        layout.addStretch(1)

        self.data_source_combo = QComboBox()
        self.data_source_combo.setEditable(True)
        self.data_source_combo.addItems(["当前项目高频目录", "最近归档批次", "回放文件夹"])
        self.time_range_combo = QComboBox()
        self.time_range_combo.setEditable(True)
        self.time_range_combo.addItems(["最近 24 小时", "今天", "最近 7 天", "自定义时间窗"])
        layout.addWidget(QLabel("数据来源"))
        layout.addWidget(self.data_source_combo)
        layout.addWidget(QLabel("时间范围"))
        layout.addWidget(self.time_range_combo)

        self.run_status_chip = chip("标准运行", "accent")
        layout.addWidget(self.run_status_chip)
        self.run_summary_label = QLabel("尚未生成真实 RP 结果。")
        self.run_summary_label.setObjectName("subtitle")
        self.run_summary_label.setWordWrap(True)
        self.run_summary_label.setMinimumWidth(260)
        layout.addWidget(self.run_summary_label)

        run_button = QPushButton("运行处理")
        run_button.setProperty("variant", "primary")
        run_button.clicked.connect(lambda: self._run_processing(precheck_only=False))
        precheck_button = QPushButton("仅预检查")
        precheck_button.clicked.connect(lambda: self._run_processing(precheck_only=True))
        save_template_button = QPushButton("保存模板")
        save_template_button.clicked.connect(self._save_template)
        restore_button = QPushButton("恢复默认")
        restore_button.clicked.connect(self._restore_default)
        for button in (run_button, precheck_button, save_template_button, restore_button):
            layout.addWidget(button)
        return card

    def _build_desktop_rail(self) -> CardFrame:
        rail = CardFrame(muted=True, role="rail")
        rail.setMinimumWidth(300)
        rail.setMaximumWidth(380)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("EC Workbench", "固定显示当前运行闭合状态，不再藏在长页面底部。"))
        self.workflow_lens_card = self._build_workflow_lens_panel()
        layout.addWidget(self.workflow_lens_card)
        self.cockpit_card = self._build_processing_cockpit()
        layout.addWidget(self.cockpit_card)
        self.readiness_card = self._build_readiness_panel()
        layout.addWidget(self.readiness_card)
        self.output_coverage_card = self._build_output_coverage_panel()
        layout.addWidget(self.output_coverage_card)
        layout.addStretch(1)
        return rail

    def _build_workflow_lens_panel(self) -> CardFrame:
        card = CardFrame(role="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title("工作流分层", "把项目、核心计算、高级方法和交付输出压缩成可跳转的四段导航。"))

        for lens_key, title, subtitle, steps in WORKFLOW_LENSES:
            button = QPushButton(title)
            button.setToolTip(" / ".join(dict((key, label) for key, label, _sub in EC_STEPS).get(step, step) for step in steps))
            button.clicked.connect(lambda _checked=False, key=lens_key: self._select_workflow_lens(key))
            note = QLabel(subtitle)
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            self.workflow_lens_buttons[lens_key] = button
            self.workflow_lens_notes[lens_key] = note
            layout.addWidget(button)
            layout.addWidget(note)
        return card

    def _build_output_coverage_panel(self) -> CardFrame:
        card = CardFrame(role="panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        header = QHBoxLayout()
        header.setSpacing(TOKENS.spacing_sm)
        header.addWidget(section_title("输出覆盖", "把交付链压缩成检查矩阵，不再让字段状态拖成一条长清单。"))
        header.addStretch(1)
        self.coverage_gate_chip = chip("待运行", "warning")
        header.addWidget(self.coverage_gate_chip)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_sm)
        for index, (key, title) in enumerate((
            ("metadata", "元数据"),
            ("processing", "处理选项"),
            ("statistics", "统计检验"),
            ("spectral", "谱修正"),
            ("methods", "方法族"),
            ("network", "网络交付"),
        )):
            tile = CardFrame(muted=True, role="tile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
            tile_layout.setSpacing(TOKENS.spacing_xs)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel("--")
            value_label.setObjectName("subtitle")
            value_label.setWordWrap(True)
            self.coverage_values[key] = value_label
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            grid.addWidget(tile, index // 2, index % 2)
        layout.addLayout(grid)

        self.coverage_next_value = QLabel("--")
        self.coverage_next_value.setObjectName("metricValue")
        self.coverage_next_value.setWordWrap(True)
        self.coverage_next_note = QLabel("--")
        self.coverage_next_note.setObjectName("subtitle")
        self.coverage_next_note.setWordWrap(True)
        layout.addWidget(self.coverage_next_value)
        layout.addWidget(self.coverage_next_note)
        return card

    def _build_processing_cockpit(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        header = QHBoxLayout()
        header.setSpacing(TOKENS.spacing_sm)
        header.addWidget(section_title("处理 Cockpit", "当前 RP 运行、方法和交付状态。"))
        header.addStretch(1)
        self.cockpit_status_chip = chip("等待运行", "warning")
        header.addWidget(self.cockpit_status_chip)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.cockpit_method_value, self.cockpit_method_note = self._build_cockpit_tile(grid, 0, 0, "方法栈")
        self.cockpit_result_value, self.cockpit_result_note = self._build_cockpit_tile(grid, 1, 0, "主通量")
        self.cockpit_uncertainty_value, self.cockpit_uncertainty_note = self._build_cockpit_tile(grid, 2, 0, "不确定度")
        self.cockpit_benchmark_value, self.cockpit_benchmark_note = self._build_cockpit_tile(grid, 3, 0, "Benchmark")
        self.cockpit_delivery_value, self.cockpit_delivery_note = self._build_cockpit_tile(grid, 4, 0, "交付出口")
        layout.addLayout(grid)
        return card

    def _build_readiness_panel(self) -> CardFrame:
        card = CardFrame(role="panel")
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title("运行闭合度", "采样规模、方法族和出口状态。"), 0, 0)
        self.window_readiness_value, self.window_readiness_note = self._build_cockpit_tile(layout, 1, 0, "窗口规模")
        self.method_readiness_value, self.method_readiness_note = self._build_cockpit_tile(layout, 2, 0, "方法闭合")
        self.delivery_readiness_value, self.delivery_readiness_note = self._build_cockpit_tile(layout, 3, 0, "交付闭合")
        return card

    def _build_cockpit_tile(
        self,
        layout: QGridLayout,
        row: int,
        column: int,
        title: str,
        *,
        column_span: int = 1,
    ) -> tuple[QLabel, QLabel]:
        tile = CardFrame(muted=True, role="tile")
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        tile_layout.setSpacing(TOKENS.spacing_xs)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel("--")
        value_label.setObjectName("metricValue")
        value_label.setWordWrap(True)
        note_label = QLabel("--")
        note_label.setObjectName("subtitle")
        note_label.setWordWrap(True)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(value_label)
        tile_layout.addWidget(note_label)
        layout.addWidget(tile, row, column, 1, column_span)
        return value_label, note_label

    def _select_workflow_lens(self, lens_key: str) -> None:
        steps = next((items for key, _title, _subtitle, items in WORKFLOW_LENSES if key == lens_key), [])
        if not steps:
            return
        target_step = steps[0]
        item = self.step_items.get(target_step)
        if item is not None:
            self.step_tree.setCurrentItem(item)
        else:
            self.controller.set_ec_nav_step(target_step)
            self._sync_step_from_controller()
        self._refresh_workflow_lens()

    def _refresh_workflow_lens(self) -> None:
        if not self.workflow_lens_buttons:
            return
        active_step = self.controller.ec_nav_step
        active_lens = ""
        for lens_key, _title, _subtitle, steps in WORKFLOW_LENSES:
            if active_step in steps:
                active_lens = lens_key
                break
        for lens_key, button in self.workflow_lens_buttons.items():
            button.setProperty("variant", "primary" if lens_key == active_lens else "")
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_method_family(self, family: str) -> None:
        if not hasattr(self, "method_family_sections"):
            return
        card = self.method_family_sections.get(family)
        if card is None:
            return
        self.method_family_stack.setCurrentWidget(card)
        for key, button in self.method_family_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == family)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_method_gate_chip(self, text: str, tone: str) -> None:
        if not hasattr(self, "method_family_gate_chip"):
            return
        self.method_family_gate_chip.setText(text)
        self.method_family_gate_chip.setProperty("chipTone", tone)
        self.method_family_gate_chip.style().unpolish(self.method_family_gate_chip)
        self.method_family_gate_chip.style().polish(self.method_family_gate_chip)

    def _compact_method_form(self, fields: list[tuple[str, QWidget]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_md)
        grid.setVerticalSpacing(TOKENS.spacing_sm)
        for index, (label_text, widget) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            label = QLabel(label_text)
            label.setObjectName("subtitle")
            grid.addWidget(label, row, column)
            grid.addWidget(widget, row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return grid

    def _refresh_method_control_summary(self) -> None:
        if not hasattr(self, "method_snapshot_label"):
            return
        footprint_enabled = self._current_combo_text("footprint_enable_combo", "enabled")
        footprint_method = self._current_combo_text("footprint_method_combo", "kljun")
        uncertainty_method = self._current_combo_text("uncertainty_mode_combo", "mann_lenschow")
        spectral_enabled = self._current_combo_text("spectral_enable_combo", "enabled")
        spectral_method = self._current_combo_text("spectral_method_combo", "massman")
        cospectrum = self._current_combo_text("spectral_cospectrum_combo", "fcc_auto")
        compare = self._current_combo_text("method_compare_combo", "disabled")

        issues: list[str] = []
        z_m = self.footprint_zm_spin.value()
        canopy = self.footprint_canopy_spin.value()
        z0 = self.footprint_z0_spin.value()
        if footprint_enabled == "enabled":
            if z_m <= canopy:
                issues.append("z_m > canopy_height_m should be reviewed for above-canopy footprint runs.")
            if z0 >= z_m:
                issues.append("z0 must stay below z_m for footprint scaling.")
            if self.footprint_grid_combo.currentText().strip() == "enabled" and (
                self.footprint_grid_x_spin.value() < 16 or self.footprint_grid_y_spin.value() < 15
            ):
                issues.append("2D footprint grid is very coarse; use at least 16x15 for delivery review.")

        confidence = self.uncertainty_confidence_spin.value()
        if confidence < 0.80:
            issues.append("confidence_level below 0.80 is allowed but should be justified in the run notes.")

        if spectral_enabled == "enabled":
            if self.spectral_response_spin.value() > 2.0:
                issues.append("response_time_s is high; spectral attenuation may dominate the correction.")
            if spectral_method == "fratini" and cospectrum != "fcc_auto":
                issues.append("Fratini should use fcc_auto measured_cospectrum when FCC output is available.")

        if compare == "enabled" and self.method_compare_threshold_spin.value() > 1.0:
            issues.append("method_compare deviation_threshold above 1.0 weakens parity review.")

        snapshot = (
            f"footprint={footprint_method}({footprint_enabled}, z_m={z_m:.2f}, canopy={canopy:.2f}) | "
            f"uncertainty={uncertainty_method}(confidence={confidence:.2f}) | "
            f"spectral={spectral_method}({spectral_enabled}, cospectrum={cospectrum}) | "
            f"compare={compare}(threshold={self.method_compare_threshold_spin.value():.2f})"
        )
        self.method_snapshot_label.setText(snapshot)
        if issues:
            self._set_method_gate_chip("Review", "warning")
            self.method_validation_label.setText(" | ".join(issues[:4]))
        else:
            self._set_method_gate_chip("Ready", "success")
            self.method_validation_label.setText("Ranges ok; UI snapshot keys match pipeline config names.")

    def _refresh_output_coverage_panel(self) -> None:
        if not self.coverage_values:
            return
        current = self._current_window()
        diagnostics = dict(current.diagnostics or {}) if current is not None else {}
        network = dict(self.controller.report_center_workspace.get("network_output", {}) or {})

        primary_profile = self.primary_analyzer_profile_combo.currentData() if hasattr(self, "primary_analyzer_profile_combo") else None
        if not primary_profile and hasattr(self, "primary_analyzer_profile_combo"):
            primary_profile = self.primary_analyzer_profile_combo.currentText().strip()
        calibration = self.primary_calibration_profile_edit.text().strip() if hasattr(self, "primary_calibration_profile_edit") else ""
        self.coverage_values["metadata"].setText(
            f"profile={primary_profile or '--'}，calibration={calibration or 'not set'}"
        )
        metadata_ready = bool(primary_profile)

        rotation = self._current_combo_text("rotation_mode_combo", "--")
        detrend = self._current_combo_text("detrend_mode_combo", "--")
        density = self._current_combo_text("density_correction_combo", "--")
        self.coverage_values["processing"].setText(f"rotation={rotation}，detrend={detrend}，density={density}")
        processing_ready = all(value and value != "--" for value in (rotation, detrend, density))

        self.coverage_values["statistics"].setText(
            f"skew≤{self.screening_skewness_spin.value():.1f}，"
            f"kurt≤{self.screening_kurtosis_spin.value():.1f}，"
            f"dropout≥{self.screening_dropout_min_run_spin.value()}"
        )
        statistics_ready = (
            self.screening_skewness_spin.value() > 0
            and self.screening_kurtosis_spin.value() > 0
            and self.screening_dropout_min_run_spin.value() > 0
        )

        spectral_method = self._current_combo_text("spectral_method_combo", "massman")
        cospectrum = self._current_combo_text("spectral_cospectrum_combo", "fcc_auto")
        spectral_status = diagnostics.get("spectral_correction_measured_cospectrum_source", cospectrum)
        self.coverage_values["spectral"].setText(f"method={spectral_method}，cospectrum={spectral_status}")
        spectral_ready = self._current_combo_text("spectral_enable_combo", "enabled") == "enabled"

        footprint_method = self._current_combo_text("footprint_method_combo", "kljun")
        uncertainty_method = self._current_combo_text("uncertainty_mode_combo", "mann_lenschow")
        compare = self._current_combo_text("method_compare_combo", "disabled")
        self.coverage_values["methods"].setText(
            f"footprint={footprint_method}，uncertainty={uncertainty_method}，compare={compare}"
        )
        methods_ready = bool(footprint_method and uncertainty_method and spectral_method)

        schema_target = diagnostics.get("schema_target") or network.get("schema_target", "FLUXNET")
        validation_status = diagnostics.get("validation_status", diagnostics.get("network_validation_status", "--"))
        missing_fields = diagnostics.get("missing_fields", diagnostics.get("network_missing_fields", []))
        if isinstance(missing_fields, str):
            missing_fields = [missing_fields]
        self.coverage_values["network"].setText(
            f"schema={schema_target}，validation={validation_status}，missing={len(missing_fields or [])}"
        )
        network_ready = bool(schema_target) and len(missing_fields or []) == 0

        ready_count = sum(
            1
            for ready in (
                metadata_ready,
                processing_ready,
                statistics_ready,
                spectral_ready,
                methods_ready,
                network_ready,
            )
            if ready
        )
        if current is not None and ready_count == 6:
            gate_text, gate_tone = "可交付", "success"
            next_value = "导出结果"
            next_note = "RP 结果、方法族和网络字段均已闭合，可进入报告中心或交付包导出。"
        elif current is None and ready_count == 6:
            gate_text, gate_tone = "可运行", "accent"
            next_value = "运行处理"
            next_note = "配置已基本闭合，建议先运行 RP 处理生成窗口结果和交付校验。"
        else:
            gate_text, gate_tone = "待补齐", "warning"
            next_value = "补齐配置"
            next_note = f"当前闭合 {ready_count}/6；优先检查分析仪 profile、方法族和网络交付字段。"
        self._set_coverage_gate_chip(gate_text, gate_tone)
        self.coverage_next_value.setText(next_value)
        self.coverage_next_note.setText(next_note)

    def _set_coverage_gate_chip(self, text: str, tone: str) -> None:
        self.coverage_gate_chip.setText(text)
        self.coverage_gate_chip.setProperty("chipTone", tone)
        self.coverage_gate_chip.style().unpolish(self.coverage_gate_chip)
        self.coverage_gate_chip.style().polish(self.coverage_gate_chip)

    def _build_tree(self) -> None:
        root = QTreeWidgetItem(["处理流程"])
        root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
        self.step_tree.addTopLevelItem(root)
        for key, title, _subtitle in EC_STEPS:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, key)
            item.setToolTip(0, title)
            root.addChild(item)
            self.step_items[key] = item
        root.setExpanded(True)

    def _build_pages(self) -> None:
        for key, title, subtitle in EC_STEPS:
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
            scroll.setWidget(container)
            self.step_indexes[key] = self.content_stack.addWidget(scroll)

    def _build_window_sampling_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("参数设置", "窗口越清晰，后续 lag、去趋势和检验的解释越容易统一。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.window_minutes_spin = QSpinBox()
        self.window_minutes_spin.setRange(1, 180)
        self.window_minutes_spin.setSuffix(" 分钟")
        self.window_sample_hz_spin = QSpinBox()
        self.window_sample_hz_spin.setRange(1, 100)
        self.window_sample_hz_spin.setSuffix(" Hz")
        form.addRow("窗口长度", self.window_minutes_spin)
        form.addRow("采样频率", self.window_sample_hz_spin)
        param_layout.addLayout(form)
        row.addWidget(param_card, 3)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "先把窗口规模换算成直观采样量，便于操作员理解。"))
        self.window_samples_label = QLabel("--")
        self.window_samples_label.setObjectName("metricValue")
        preview_layout.addWidget(self.window_samples_label)
        self.window_preview_note = QLabel("--")
        self.window_preview_note.setObjectName("subtitle")
        self.window_preview_note.setWordWrap(True)
        preview_layout.addWidget(self.window_preview_note)
        row.addWidget(preview_card, 2)

        timeline_card = CardFrame(muted=True)
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        timeline_layout.setSpacing(TOKENS.spacing_sm)
        timeline_layout.addWidget(section_title("窗口时间轴", "桌面端用图形先确认窗口规模和批次结构，再进入细节步骤。"))
        self.window_plan_plot = pg.PlotWidget()
        configure_plot_theme(self.window_plan_plot, left_label="samples", bottom_label="window")
        self.window_plan_curve = self.window_plan_plot.plot(
            pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.0),
            symbol="o",
            symbolBrush=PLOT_SERIES_COLORS["primary"],
            symbolPen=pg.mkPen("#ffffff", width=1),
        )
        timeline_layout.addWidget(self.window_plan_plot, 1)
        self.window_plan_note = QLabel("--")
        self.window_plan_note.setObjectName("subtitle")
        self.window_plan_note.setWordWrap(True)
        timeline_layout.addWidget(self.window_plan_note)
        layout.addWidget(timeline_card)

    def _build_data_cleaning_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("清洗策略", "用业务语言描述剔除强度和缺测补齐策略。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.clean_spike_sigma_spin = self._double_spin(1.0, 10.0, 1)
        self.clean_missing_policy_combo = QComboBox()
        self.clean_missing_policy_combo.addItems(["辅助变量线性插补", "整窗保留缺测", "严格剔除整窗"])
        form.addRow("尖峰阈值", self.clean_spike_sigma_spin)
        form.addRow("缺测处理", self.clean_missing_policy_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 3)

        stats_card = CardFrame(muted=True)
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        stats_layout.setSpacing(TOKENS.spacing_md)
        stats_layout.addWidget(section_title("剔除统计区", "让用户看到清洗会带来多大影响，而不是只看到一个开关。"))
        self.clean_removed_ratio_label = QLabel("--")
        self.clean_removed_ratio_label.setObjectName("metricValue")
        stats_layout.addWidget(self.clean_removed_ratio_label)
        self.clean_retained_label = QLabel("--")
        self.clean_retained_label.setObjectName("subtitle")
        self.clean_retained_label.setWordWrap(True)
        stats_layout.addWidget(self.clean_retained_label)
        row.addWidget(stats_card, 2)

    def _build_screening_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("统计筛选阈值", "控制偏度、峰度、dropout 等诊断灵敏度。阈值越严格，更多窗口被标记。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.screening_skewness_spin = self._double_spin(0.5, 10.0, 1, suffix="")
        self.screening_skewness_spin.setValue(2.0)
        self.screening_kurtosis_spin = self._double_spin(2.0, 30.0, 1, suffix="")
        self.screening_kurtosis_spin.setValue(7.0)
        self.screening_dropout_min_run_spin = QSpinBox()
        self.screening_dropout_min_run_spin.setRange(2, 1000)
        self.screening_dropout_min_run_spin.setValue(10)
        self.screening_spike_sigma_spin = self._double_spin(1.0, 20.0, 1, suffix=" σ")
        self.screening_spike_sigma_spin.setValue(5.0)
        self.screening_discontinuity_sigma_spin = self._double_spin(1.0, 30.0, 1, suffix=" σ")
        self.screening_discontinuity_sigma_spin.setValue(8.0)
        self.screening_absolute_limits_edit = QTextEdit()
        self.screening_absolute_limits_edit.setPlaceholderText('{"co2_ppm": [0, 1500], "h2o_mmol": [0, 50]}')
        self.screening_absolute_limits_edit.setMaximumHeight(60)
        form.addRow("偏度阈值", self.screening_skewness_spin)
        form.addRow("峰度阈值", self.screening_kurtosis_spin)
        form.addRow("dropout 最小连续点", self.screening_dropout_min_run_spin)
        form.addRow("尖峰 σ", self.screening_spike_sigma_spin)
        form.addRow("不连续 σ", self.screening_discontinuity_sigma_spin)
        form.addRow("绝对值范围 (JSON)", self.screening_absolute_limits_edit)
        param_layout.addLayout(form)
        row.addWidget(param_card, 3)

        summary_card = CardFrame(muted=True)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        summary_layout.setSpacing(TOKENS.spacing_md)
        summary_layout.addWidget(section_title("筛选摘要", "当前窗口的筛选结果概览。"))
        self.screening_summary_label = QLabel("--")
        self.screening_summary_label.setObjectName("subtitle")
        self.screening_summary_label.setWordWrap(True)
        summary_layout.addWidget(self.screening_summary_label)
        row.addWidget(summary_card, 2)

    def _build_lag_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("时滞搜索参数", "把搜索范围和预期 lag 明确写出来，避免误把偶然峰值当结果。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.lag_strategy_combo = QComboBox()
        self.lag_strategy_combo.addItems(["协方差最大", "协方差最大带默认", "固定滞后", "无滞后"])
        self.lag_search_window_spin = self._double_spin(1.0, 30.0, 1, suffix=" s")
        self.lag_expected_spin = self._double_spin(0.0, 20.0, 1, suffix=" s")
        form.addRow("滞后策略", self.lag_strategy_combo)
        form.addRow("搜索窗口", self.lag_search_window_spin)
        form.addRow("预期 lag", self.lag_expected_spin)
        self.lag_strategy_combo.currentIndexChanged.connect(self._on_lag_strategy_changed)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        plot_card = CardFrame(muted=True)
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        plot_layout.setSpacing(TOKENS.spacing_md)
        plot_layout.addWidget(section_title("Covariance 曲线区", "预留协方差曲线区，让 lag 的峰值选择可见可解释。"))
        self.lag_plot = pg.PlotWidget()
        configure_plot_theme(self.lag_plot, left_label="归一化协方差", bottom_label="时滞 (s)")
        self.lag_curve = self.lag_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.1))
        plot_layout.addWidget(self.lag_plot, 1)
        self.lag_note_label = QLabel("--")
        self.lag_note_label.setObjectName("subtitle")
        self.lag_note_label.setWordWrap(True)
        plot_layout.addWidget(self.lag_note_label)
        row.addWidget(plot_card, 3)

    def _build_rotation_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("旋转设置", "不同地形和安装方式适合不同的旋转方法。"))
        form = QFormLayout()
        self.rotation_mode_combo = QComboBox()
        self.rotation_mode_combo.addItems(["双旋转", "三重旋转", "平面拟合", "不旋转"])
        form.addRow("旋转方法", self.rotation_mode_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "这里保留方法说明，便于工程师解释为何采用当前旋转方式。"))
        self.rotation_preview_label = QLabel("--")
        self.rotation_preview_label.setObjectName("subtitle")
        self.rotation_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.rotation_preview_label)
        row.addWidget(preview_card, 3)

    def _build_crosswind_correction_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(
            section_title(
                "Crosswind Correction",
                "Reference-aligned sonic-temperature correction before thermodynamic flux calculations.",
            )
        )
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)

        self.crosswind_enable_combo = QComboBox()
        self.crosswind_enable_combo.addItems(["enabled", "disabled"])
        self.crosswind_method_combo = QComboBox()
        self.crosswind_method_combo.addItems(["liu_2001_crosswind_v1"])
        self.crosswind_manufacturer_combo = QComboBox()
        self.crosswind_manufacturer_combo.setEditable(True)
        self.crosswind_manufacturer_combo.addItems(["gill", "metek", "campbell_scientific", "r_m_young"])
        self.crosswind_model_combo = QComboBox()
        self.crosswind_model_combo.setEditable(True)
        self.crosswind_model_combo.addItems(["wm", "wmpro", "r3", "r2", "usa1", "csat3", "81000"])
        self.crosswind_temp_divisor_spin = self._double_spin(100.0, 5000.0, 1)
        self.crosswind_coefficients_edit = QTextEdit()
        self.crosswind_coefficients_edit.setPlaceholderText('{"u": 0.0, "v": 0.0, "uv": 0.0}')
        self.crosswind_coefficients_edit.setMaximumHeight(86)

        form.addRow("enabled", self.crosswind_enable_combo)
        form.addRow("method", self.crosswind_method_combo)
        form.addRow("sonic_manufacturer", self.crosswind_manufacturer_combo)
        form.addRow("sonic_model", self.crosswind_model_combo)
        form.addRow("temperature_divisor", self.crosswind_temp_divisor_spin)
        form.addRow("coefficients JSON", self.crosswind_coefficients_edit)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(
            section_title(
                "Provenance",
                "Shows selected sonic family, custom coefficient status, and run-level correction diagnostics.",
            )
        )
        self.crosswind_preview_label = QLabel("--")
        self.crosswind_preview_label.setObjectName("subtitle")
        self.crosswind_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.crosswind_preview_label)
        row.addWidget(preview_card, 3)

    def _build_detrend_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("去趋势设置", "明确去趋势方法，帮助用户理解频谱和均值会被怎样影响。"))
        form = QFormLayout()
        self.detrend_mode_combo = QComboBox()
        self.detrend_mode_combo.addItems(["块均值", "线性去趋势", "滑动均值", "指数滑动均值"])
        form.addRow("去趋势方法", self.detrend_mode_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "当前仅保留说明区，后续可接入频谱与残差预览。"))
        self.detrend_preview_label = QLabel("--")
        self.detrend_preview_label.setObjectName("subtitle")
        self.detrend_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.detrend_preview_label)
        self.detrend_flux_plot = pg.PlotWidget()
        configure_plot_theme(self.detrend_flux_plot, left_label="flux", bottom_label="window")
        self.detrend_raw_curve = self.detrend_flux_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.6))
        self.detrend_primary_curve = self.detrend_flux_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.1))
        preview_layout.addWidget(self.detrend_flux_plot, 1)
        row.addWidget(preview_card, 3)

    def _build_covariance_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("协方差设置", "把最终协方差的估计方式讲清楚，便于解释结果来源。"))
        form = QFormLayout()
        self.covariance_mode_combo = QComboBox()
        self.covariance_mode_combo.addItems(["标准协方差", "稳健协方差", "窗口内加权协方差"])
        form.addRow("协方差方法", self.covariance_mode_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QGridLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setHorizontalSpacing(TOKENS.spacing_md)
        preview_layout.setVerticalSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "预留主要协方差结果位，便于后续接入真实中间量。"), 0, 0, 1, 3)
        self.covariance_metric_flux = QLabel("--")
        self.covariance_metric_h2o = QLabel("--")
        self.covariance_metric_temp = QLabel("--")
        for col, (title, value) in enumerate(
            (
                ("w'c'", self.covariance_metric_flux),
                ("w'q'", self.covariance_metric_h2o),
                ("w'T'", self.covariance_metric_temp),
            )
        ):
            preview_layout.addWidget(self._metric_box(title, value), 1, col)
        row.addWidget(preview_card, 3)

    def _build_density_correction_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("修正设置", "让用户看到当前选用的密度或混合比修正方法。"))
        form = QFormLayout()
        self.density_correction_combo = QComboBox()
        self.density_correction_combo.addItems(["WPL", "混合比优先", "不修正"])
        form.addRow("修正方法", self.density_correction_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        compare_card = CardFrame(muted=True)
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        compare_layout.setSpacing(TOKENS.spacing_md)
        compare_layout.addWidget(section_title("修正前后对比区", "预留修正前后对比区，帮助用户理解修正影响。"))
        metrics_row = QHBoxLayout()
        self.density_before_label = QLabel("--")
        self.density_after_label = QLabel("--")
        metrics_row.addWidget(self._metric_box("修正前", self.density_before_label), 1)
        metrics_row.addWidget(self._metric_box("修正后", self.density_after_label), 1)
        compare_layout.addLayout(metrics_row)
        self.density_plot = pg.PlotWidget()
        configure_plot_theme(self.density_plot, left_label="通量", bottom_label="窗口序号")
        self.density_before_curve = self.density_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.8))
        self.density_after_curve = self.density_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        compare_layout.addWidget(self.density_plot, 1)
        self.density_note_label = QLabel("--")
        self.density_note_label.setObjectName("subtitle")
        self.density_note_label.setWordWrap(True)
        compare_layout.addWidget(self.density_note_label)
        row.addWidget(compare_card, 3)

    def _build_steadiness_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("稳态检验设置", "把稳态规则写清楚，方便解释窗口质量等级。"))
        form = QFormLayout()
        self.steadiness_rule_combo = QComboBox()
        self.steadiness_rule_combo.addItems(["Foken-like", "经验窗口对比", "项目自定义"])
        form.addRow("检验规则", self.steadiness_rule_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "预留稳态等级和解释区。"))
        self.steadiness_preview_label = QLabel("--")
        self.steadiness_preview_label.setObjectName("subtitle")
        self.steadiness_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.steadiness_preview_label)
        self.steadiness_score_plot = pg.PlotWidget()
        configure_plot_theme(self.steadiness_score_plot, left_label="stationarity score", bottom_label="window")
        self.steadiness_score_curve = self.steadiness_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        preview_layout.addWidget(self.steadiness_score_plot, 1)
        row.addWidget(preview_card, 3)

    def _build_turbulence_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("湍流检验设置", "把稳定度和 u* 判定条件显式化。"))
        form = QFormLayout()
        self.ustar_rule_combo = QComboBox()
        self.ustar_rule_combo.addItems(["站点阈值", "分季节阈值", "经验默认值"])
        form.addRow("判定规则", self.ustar_rule_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "先保留文字解释区，后续可接入稳定度散点图。"))
        self.turbulence_preview_label = QLabel("--")
        self.turbulence_preview_label.setObjectName("subtitle")
        self.turbulence_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.turbulence_preview_label)
        self.turbulence_score_plot = pg.PlotWidget()
        configure_plot_theme(self.turbulence_score_plot, left_label="u* / turbulence score", bottom_label="window")
        self.turbulence_ustar_curve = self.turbulence_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["warning"], width=1.8))
        self.turbulence_score_curve = self.turbulence_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        preview_layout.addWidget(self.turbulence_score_plot, 1)
        row.addWidget(preview_card, 3)

    def _build_uncertainty_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("方法控制", "三族方法配置共用一页，保证 UI、config snapshot 和 pipeline 参数名一致。"))

        self.method_family_card = CardFrame(muted=True, role="cockpit")
        method_shell_layout = QVBoxLayout(self.method_family_card)
        method_shell_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        method_shell_layout.setSpacing(TOKENS.spacing_sm)
        method_header = QHBoxLayout()
        method_header.setSpacing(TOKENS.spacing_sm)
        method_header.addWidget(section_title("Method console", "Switch between method families, review the live config snapshot, then run the RP pipeline."))
        method_header.addStretch(1)
        self.method_family_gate_chip = chip("Review", "warning")
        method_header.addWidget(self.method_family_gate_chip)
        method_shell_layout.addLayout(method_header)

        method_switch_row = QHBoxLayout()
        method_switch_row.setContentsMargins(0, 0, 0, 0)
        method_switch_row.setSpacing(TOKENS.spacing_xs)
        self.method_family_buttons: dict[str, QToolButton] = {}
        for family, text in (
            ("footprint", "Footprint"),
            ("uncertainty", "Uncertainty"),
            ("spectral", "Spectral"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, key=family: self._show_method_family(key))
            self.method_family_buttons[family] = button
            method_switch_row.addWidget(button)
        method_switch_row.addStretch(1)
        method_shell_layout.addLayout(method_switch_row)

        self.method_family_stack = QStackedWidget()
        method_shell_layout.addWidget(self.method_family_stack)
        self.method_snapshot_label = QLabel("--")
        self.method_snapshot_label.setObjectName("subtitle")
        self.method_snapshot_label.setWordWrap(True)
        self.method_validation_label = QLabel("--")
        self.method_validation_label.setObjectName("subtitle")
        self.method_validation_label.setWordWrap(True)
        method_shell_layout.addWidget(self.method_snapshot_label)
        method_shell_layout.addWidget(self.method_validation_label)
        param_layout.addWidget(self.method_family_card)

        self.footprint_card = CardFrame(muted=True, role="console")
        footprint_layout = QVBoxLayout(self.footprint_card)
        footprint_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        footprint_layout.setSpacing(TOKENS.spacing_sm)
        footprint_layout.addWidget(section_title("Footprint", "推荐：kljun / z_m=3.0 / canopy_height_m=5.0"))
        self.footprint_enable_combo = QComboBox()
        self.footprint_enable_combo.addItems(["enabled", "disabled"])
        self.footprint_method_combo = QComboBox()
        self.footprint_method_combo.addItems(["kljun", "kormann_meixner", "hsieh"])
        self.footprint_zm_spin = self._double_spin(0.1, 50.0, 2, suffix=" m")
        self.footprint_canopy_spin = self._double_spin(0.1, 60.0, 2, suffix=" m")
        self.footprint_z0_spin = self._double_spin(0.001, 5.0, 3, suffix=" m")
        self.footprint_ol_spin = self._double_spin(-2000.0, 2000.0, 1, suffix=" m")
        self.footprint_grid_combo = QComboBox()
        self.footprint_grid_combo.addItems(["enabled", "disabled"])
        self.footprint_grid_x_spin = QSpinBox()
        self.footprint_grid_x_spin.setRange(8, 96)
        self.footprint_grid_y_spin = QSpinBox()
        self.footprint_grid_y_spin.setRange(7, 81)
        footprint_layout.addLayout(
            self._compact_method_form(
                [
                    ("enabled", self.footprint_enable_combo),
                    ("method", self.footprint_method_combo),
                    ("z_m", self.footprint_zm_spin),
                    ("canopy_height_m", self.footprint_canopy_spin),
                    ("z0", self.footprint_z0_spin),
                    ("ol", self.footprint_ol_spin),
                    ("grid_2d", self.footprint_grid_combo),
                    ("grid_x_bins", self.footprint_grid_x_spin),
                    ("grid_y_bins", self.footprint_grid_y_spin),
                ]
            )
        )
        self.footprint_summary_label = QLabel("--")
        self.footprint_summary_label.setObjectName("subtitle")
        self.footprint_summary_label.setWordWrap(True)
        footprint_layout.addWidget(self.footprint_summary_label)
        self.method_family_stack.addWidget(self.footprint_card)

        self.uncertainty_card = CardFrame(muted=True, role="console")
        uncertainty_layout = QVBoxLayout(self.uncertainty_card)
        uncertainty_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        uncertainty_layout.setSpacing(TOKENS.spacing_sm)
        uncertainty_layout.addWidget(section_title("Uncertainty", "推荐：mann_lenschow / integral_timescale_s=5.0 / confidence_level=0.95"))
        self.uncertainty_mode_combo = QComboBox()
        self.uncertainty_mode_combo.addItems(["mann_lenschow", "finkelstein_sims", "composite_empirical"])
        self.uncertainty_timescale_spin = self._double_spin(0.5, 120.0, 1, suffix=" s")
        self.uncertainty_confidence_spin = self._double_spin(0.50, 0.99, 2)
        uncertainty_layout.addLayout(
            self._compact_method_form(
                [
                    ("method", self.uncertainty_mode_combo),
                    ("integral_timescale_s", self.uncertainty_timescale_spin),
                    ("confidence_level", self.uncertainty_confidence_spin),
                ]
            )
        )
        self.uncertainty_summary_label = QLabel("--")
        self.uncertainty_summary_label.setObjectName("subtitle")
        self.uncertainty_summary_label.setWordWrap(True)
        uncertainty_layout.addWidget(self.uncertainty_summary_label)
        self.method_family_stack.addWidget(self.uncertainty_card)

        self.spectral_card = CardFrame(muted=True, role="console")
        spectral_layout = QVBoxLayout(self.spectral_card)
        spectral_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        spectral_layout.setSpacing(TOKENS.spacing_sm)
        spectral_layout.addWidget(section_title("Spectral Correction", "推荐：massman；Fratini 默认自动尝试 FCC measured cospectrum"))
        self.spectral_enable_combo = QComboBox()
        self.spectral_enable_combo.addItems(["enabled", "disabled"])
        self.spectral_method_combo = QComboBox()
        self.spectral_method_combo.addItems(["massman", "horst", "ibrom", "fratini"])
        self.spectral_path_spin = self._double_spin(0.01, 10.0, 3, suffix=" m")
        self.spectral_sep_spin = self._double_spin(0.0, 10.0, 3, suffix=" m")
        self.spectral_response_spin = self._double_spin(0.001, 10.0, 3, suffix=" s")
        self.spectral_zm_spin = self._double_spin(0.1, 50.0, 2, suffix=" m")
        self.spectral_ol_spin = self._double_spin(-2000.0, 2000.0, 1, suffix=" m")
        self.spectral_cospectrum_combo = QComboBox()
        self.spectral_cospectrum_combo.addItems(["fcc_auto", "local_only"])
        spectral_layout.addLayout(
            self._compact_method_form(
                [
                    ("enabled", self.spectral_enable_combo),
                    ("method", self.spectral_method_combo),
                    ("path_length_m", self.spectral_path_spin),
                    ("sensor_sep_m", self.spectral_sep_spin),
                    ("response_time_s", self.spectral_response_spin),
                    ("z_m", self.spectral_zm_spin),
                    ("ol", self.spectral_ol_spin),
                    ("measured_cospectrum", self.spectral_cospectrum_combo),
                ]
            )
        )
        self.spectral_summary_label = QLabel("--")
        self.spectral_summary_label.setObjectName("subtitle")
        self.spectral_summary_label.setWordWrap(True)
        spectral_layout.addWidget(self.spectral_summary_label)
        self.method_family_stack.addWidget(self.spectral_card)
        self.method_family_sections = {
            "footprint": self.footprint_card,
            "uncertainty": self.uncertainty_card,
            "spectral": self.spectral_card,
        }
        self._show_method_family("footprint")

        primary_card = CardFrame(muted=True)
        primary_layout = QVBoxLayout(primary_card)
        primary_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        primary_layout.setSpacing(TOKENS.spacing_sm)
        primary_layout.addWidget(section_title("Primary Analyzer QC", "Profile-aware CO2/H2O analyzer provenance and diagnostic thresholds."))
        self.primary_analyzer_enable_combo = QComboBox()
        self.primary_analyzer_enable_combo.addItems(["enabled", "disabled"])
        self.primary_analyzer_profile_combo = QComboBox()
        for profile in self.controller.available_gas_analyzer_profiles():
            self.primary_analyzer_profile_combo.addItem(str(profile["label"]), str(profile["profile_id"]))
        self.primary_signal_warning_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        self.primary_signal_fail_spin = self._double_spin(0.0, 100.0, 1, suffix=" %")
        self.primary_require_status_combo = QComboBox()
        self.primary_require_status_combo.addItems(["required", "not_required"])
        self.primary_cell_thermo_combo = QComboBox()
        self.primary_cell_thermo_combo.addItems(["auto", "required", "not_required"])
        self.primary_allowed_diag_words_edit = QLineEdit()
        self.primary_allowed_diag_words_edit.setPlaceholderText("0")
        self.primary_calibration_profile_edit = QLineEdit()
        self.primary_calibration_profile_edit.setPlaceholderText("site_zero_span_2026")
        self.primary_source_file_edit = QLineEdit()
        self.primary_source_file_edit.setPlaceholderText("source calibration or normalized diagnostic file")
        self.primary_normalization_command_edit = QLineEdit()
        self.primary_normalization_command_edit.setPlaceholderText("gas_ec_studio normalize-licor --input ...")
        primary_layout.addLayout(
            self._compact_method_form(
                [
                    ("enabled", self.primary_analyzer_enable_combo),
                    ("profile_id", self.primary_analyzer_profile_combo),
                    ("signal_warning", self.primary_signal_warning_spin),
                    ("signal_fail", self.primary_signal_fail_spin),
                    ("status_ok", self.primary_require_status_combo),
                    ("cell_thermodynamics", self.primary_cell_thermo_combo),
                    ("allowed_diag_words", self.primary_allowed_diag_words_edit),
                    ("calibration_profile_id", self.primary_calibration_profile_edit),
                    ("source_file", self.primary_source_file_edit),
                    ("normalization_command", self.primary_normalization_command_edit),
                ]
            )
        )
        self.primary_analyzer_summary_label = QLabel("--")
        self.primary_analyzer_summary_label.setObjectName("subtitle")
        self.primary_analyzer_summary_label.setWordWrap(True)
        primary_layout.addWidget(self.primary_analyzer_summary_label)
        param_layout.addWidget(primary_card)

        compare_card = CardFrame(muted=True)
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        compare_layout.setSpacing(TOKENS.spacing_sm)
        compare_layout.addWidget(section_title("Method Compare", "Run method families side-by-side without changing selected processing outputs"))
        self.method_compare_combo = QComboBox()
        self.method_compare_combo.addItems(["enabled", "disabled"])
        self.method_compare_threshold_spin = self._double_spin(0.01, 2.0, 2)
        compare_layout.addLayout(
            self._compact_method_form(
                [
                    ("enabled", self.method_compare_combo),
                    ("deviation_threshold", self.method_compare_threshold_spin),
                ]
            )
        )
        param_layout.addWidget(compare_card)

        row.addWidget(param_card, 3)

        preview_card = CardFrame(muted=True)
        preview_layout = QGridLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setHorizontalSpacing(TOKENS.spacing_md)
        preview_layout.setVerticalSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "显示 method summary、uncertainty band 和 Fratini/FCC 路径状态。"), 0, 0, 1, 3)
        self.uncertainty_sampling_label = QLabel("--")
        self.uncertainty_sensor_label = QLabel("--")
        self.uncertainty_processing_label = QLabel("--")
        for col, (title, value) in enumerate(
            (
                ("random_error", self.uncertainty_sampling_label),
                ("relative", self.uncertainty_sensor_label),
                ("band", self.uncertainty_processing_label),
            )
        ):
            preview_layout.addWidget(self._metric_box(title, value), 1, col)
        self.uncertainty_preview_note = QLabel("--")
        self.uncertainty_preview_note.setObjectName("subtitle")
        self.uncertainty_preview_note.setWordWrap(True)
        preview_layout.addWidget(self.uncertainty_preview_note, 2, 0, 1, 3)
        row.addWidget(preview_card, 3)

    def _build_output_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("输出设置", "把最终导出的关键字段列出来，减少交付阶段返工。"))
        form = QFormLayout()
        self.output_fields_edit = QLineEdit()
        self.full_output_mode_combo = QComboBox()
        self.full_output_mode_combo.addItems(["only_available", "standard_schema"])
        form.addRow("输出字段", self.output_fields_edit)
        form.addRow("Full output mode", self.full_output_mode_combo)
        param_layout.addLayout(form)
        row.addWidget(param_card, 2)

        preview_card = CardFrame(muted=True)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        preview_layout.setSpacing(TOKENS.spacing_md)
        preview_layout.addWidget(section_title("中间结果", "在正式运行前先预览输出重点，避免漏掉关键诊断字段。"))
        self.output_preview_label = QLabel("--")
        self.output_preview_label.setObjectName("subtitle")
        self.output_preview_label.setWordWrap(True)
        preview_layout.addWidget(self.output_preview_label)
        row.addWidget(preview_card, 3)

    def _bind_preview_signals(self) -> None:
        self.window_minutes_spin.valueChanged.connect(self._refresh_window_preview)
        self.window_sample_hz_spin.valueChanged.connect(self._refresh_window_preview)
        self.clean_spike_sigma_spin.valueChanged.connect(self._refresh_cleaning_preview)
        self.clean_missing_policy_combo.currentIndexChanged.connect(self._refresh_cleaning_preview)
        self.screening_skewness_spin.valueChanged.connect(self._refresh_screening_preview)
        self.screening_kurtosis_spin.valueChanged.connect(self._refresh_screening_preview)
        self.screening_dropout_min_run_spin.valueChanged.connect(self._refresh_screening_preview)
        self.screening_spike_sigma_spin.valueChanged.connect(self._refresh_screening_preview)
        self.screening_discontinuity_sigma_spin.valueChanged.connect(self._refresh_screening_preview)
        self.screening_absolute_limits_edit.textChanged.connect(self._refresh_screening_preview)
        self.lag_search_window_spin.valueChanged.connect(self._refresh_lag_preview)
        self.lag_expected_spin.valueChanged.connect(self._refresh_lag_preview)
        self.lag_strategy_combo.currentIndexChanged.connect(self._refresh_lag_preview)
        self.covariance_mode_combo.currentIndexChanged.connect(self._refresh_covariance_preview)
        self.density_correction_combo.currentIndexChanged.connect(self._refresh_density_preview)
        self.rotation_mode_combo.currentIndexChanged.connect(self._refresh_rotation_preview)
        self.crosswind_enable_combo.currentIndexChanged.connect(self._refresh_crosswind_preview)
        self.crosswind_method_combo.currentIndexChanged.connect(self._refresh_crosswind_preview)
        self.crosswind_manufacturer_combo.currentTextChanged.connect(self._refresh_crosswind_preview)
        self.crosswind_model_combo.currentTextChanged.connect(self._refresh_crosswind_preview)
        self.crosswind_temp_divisor_spin.valueChanged.connect(self._refresh_crosswind_preview)
        self.crosswind_coefficients_edit.textChanged.connect(self._refresh_crosswind_preview)
        self.detrend_mode_combo.currentIndexChanged.connect(self._refresh_detrend_preview)
        self.steadiness_rule_combo.currentIndexChanged.connect(self._refresh_steadiness_preview)
        self.ustar_rule_combo.currentIndexChanged.connect(self._refresh_turbulence_preview)
        self.footprint_enable_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_method_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_zm_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_canopy_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_z0_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_ol_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_grid_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_grid_x_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.footprint_grid_y_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.uncertainty_mode_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.uncertainty_timescale_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.uncertainty_confidence_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_enable_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_method_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_path_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_sep_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_response_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_zm_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_ol_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.spectral_cospectrum_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.primary_analyzer_enable_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_analyzer_profile_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_signal_warning_spin.valueChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_signal_fail_spin.valueChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_require_status_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_cell_thermo_combo.currentIndexChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_allowed_diag_words_edit.textChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_calibration_profile_edit.textChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_source_file_edit.textChanged.connect(self._refresh_primary_analyzer_preview)
        self.primary_normalization_command_edit.textChanged.connect(self._refresh_primary_analyzer_preview)
        self.method_compare_combo.currentIndexChanged.connect(self._refresh_uncertainty_preview)
        self.method_compare_threshold_spin.valueChanged.connect(self._refresh_uncertainty_preview)
        self.output_fields_edit.textChanged.connect(self._refresh_output_preview)
        self.full_output_mode_combo.currentIndexChanged.connect(self._refresh_output_preview)

    def _on_step_changed(self) -> None:
        item = self.step_tree.currentItem()
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        self.content_stack.setCurrentIndex(self.step_indexes[key])
        self.controller.set_ec_nav_step(key)
        self._refresh_run_bar()

    def _sync_step_from_controller(self) -> None:
        key = self.controller.ec_nav_step
        item = self.step_items.get(key)
        if item is None:
            return
        if self.step_tree.currentItem() is not item:
            self.step_tree.blockSignals(True)
            self.step_tree.setCurrentItem(item)
            self.step_tree.blockSignals(False)
        self.content_stack.setCurrentIndex(self.step_indexes[key])
        self._refresh_workflow_lens()

    def _collect_payload(self) -> dict:
        return {
            "run": {
                "data_source": self.data_source_combo.currentText().strip(),
                "time_range": self.time_range_combo.currentText().strip(),
                "run_mode": self.controller.ec_processing.get("run", {}).get("run_mode", "标准运行"),
            },
            "steps": {
                "window_sampling": {
                    "title": "窗口与采样",
                    "method": f"{self.window_minutes_spin.value()} 分钟固定窗口",
                    "applicable": "适用于常规连续观测窗口划分。",
                    "recommended": "优先保持与现场高频采样设置一致。",
                    "window_minutes": self.window_minutes_spin.value(),
                    "sample_hz": self.window_sample_hz_spin.value(),
                    "preview": self.window_preview_note.text(),
                },
                "data_cleaning": {
                    "title": "数据清洗",
                    "method": f"{self.clean_spike_sigma_spin.value():.1f}σ 尖峰剔除",
                    "applicable": "适用于存在偶发尖峰与短时缺测的高频数据。",
                    "recommended": "先温和剔除，再看剔除统计是否合理。",
                    "spike_sigma": self.clean_spike_sigma_spin.value(),
                    "missing_policy": self.clean_missing_policy_combo.currentText().strip(),
                    "removed_ratio": self.clean_removed_ratio_label.text().strip(),
                },
                "screening": {
                    "title": "统计筛选",
                    "method": "偏度/峰度/dropout/尖峰/不连续检测",
                    "applicable": "适用于窗口级统计异常诊断。",
                    "recommended": "先用默认阈值运行，再根据站点特征微调。",
                    "skewness_threshold": self.screening_skewness_spin.value(),
                    "kurtosis_threshold": self.screening_kurtosis_spin.value(),
                    "dropout_min_run": self.screening_dropout_min_run_spin.value(),
                    "spike_sigma": self.screening_spike_sigma_spin.value(),
                    "discontinuity_sigma": self.screening_discontinuity_sigma_spin.value(),
                    "absolute_limits_text": self.screening_absolute_limits_edit.toPlainText().strip(),
                },
                "lag": {
                    "title": "lag",
                    "method": self.lag_strategy_combo.currentText().strip(),
                    "applicable": "适用于采样链路存在稳定时滞的闭路分析仪。",
                    "recommended": "先用经验窗口，再结合曲线峰值复核。",
                    "lag_strategy": self.lag_strategy_combo.currentText().strip(),
                    "search_window_s": self.lag_search_window_spin.value(),
                    "expected_lag_s": self.lag_expected_spin.value(),
                },
                "rotation": {
                    "title": "坐标旋转",
                    "method": self.rotation_mode_combo.currentText().strip(),
                    "applicable": "适用于需要统一风场坐标定义的常规场景。",
                    "recommended": "默认使用双旋转；存在明显侧向偏置时可切到三重旋转，复杂地形再考虑平面拟合。",
                    "rotation_mode": self.rotation_mode_combo.currentText().strip(),
                },
                "crosswind_correction": self._collect_crosswind_payload(),
                "detrend": {
                    "title": "去趋势",
                    "method": self.detrend_mode_combo.currentText().strip(),
                    "applicable": "适用于窗口内均值与低频漂移处理。",
                    "recommended": "先使用块均值，再根据频谱表现调整。",
                    "detrend_mode": self.detrend_mode_combo.currentText().strip(),
                },
                "covariance": {
                    "title": "协方差",
                    "method": self.covariance_mode_combo.currentText().strip(),
                    "applicable": "适用于主通量计算链路。",
                    "recommended": "优先使用标准协方差并保持与窗口设置一致。",
                    "covariance_mode": self.covariance_mode_combo.currentText().strip(),
                },
                "density_correction": {
                    "title": "密度/混合比修正",
                    "method": self.density_correction_combo.currentText().strip(),
                    "applicable": "适用于从密度量恢复混合比与通量的场景。",
                    "recommended": "确认温压和水汽来源稳定后再启用。",
                    "correction_mode": self.density_correction_combo.currentText().strip(),
                },
                "steadiness": {
                    "title": "稳态检验",
                    "method": self.steadiness_rule_combo.currentText().strip(),
                    "applicable": "适用于结果有效性分级。",
                    "recommended": "建议与湍流检验结果结合解释。",
                    "steadiness_rule": self.steadiness_rule_combo.currentText().strip(),
                },
                "turbulence": {
                    "title": "湍流检验",
                    "method": self.ustar_rule_combo.currentText().strip(),
                    "applicable": "适用于稳定度分析与夜间筛选。",
                    "recommended": "先按站点阈值运行，再按季节复核。",
                    "ustar_rule": self.ustar_rule_combo.currentText().strip(),
                },
                "footprint": {
                    "title": "Footprint",
                    "method": self.footprint_method_combo.currentText().strip(),
                    "applicable": "适用于源区贡献距离摘要与代表性判断。",
                    "recommended": "默认推荐 kljun / z_m=3.0 / canopy_height_m=5.0。",
                    "enabled": self.footprint_enable_combo.currentText().strip() == "enabled",
                    "z_m": self.footprint_zm_spin.value(),
                    "canopy_height_m": self.footprint_canopy_spin.value(),
                    "z0": self.footprint_z0_spin.value(),
                    "ol": self.footprint_ol_spin.value(),
                    "grid_enabled": self.footprint_grid_combo.currentText().strip() == "enabled",
                    "grid_x_bins": self.footprint_grid_x_spin.value(),
                    "grid_y_bins": self.footprint_grid_y_spin.value(),
                    "preview": self.footprint_summary_label.text().strip(),
                },
                "uncertainty": {
                    "title": "不确定度",
                    "method": self.uncertainty_mode_combo.currentText().strip(),
                    "applicable": "适用于随机误差传播与最终通量 band 交付。",
                    "recommended": "默认推荐 mann_lenschow / integral_timescale_s=5.0 / confidence_level=0.95。",
                    "uncertainty_mode": self.uncertainty_mode_combo.currentText().strip(),
                    "integral_timescale_s": self.uncertainty_timescale_spin.value(),
                    "confidence_level": self.uncertainty_confidence_spin.value(),
                    "preview": self.uncertainty_summary_label.text().strip(),
                },
                "spectral_correction": {
                    "title": "谱修正",
                    "method": self.spectral_method_combo.currentText().strip(),
                    "applicable": "适用于高频损失修正与 Fratini/FCC measured cospectrum 注入。",
                    "recommended": "默认推荐 massman；Fratini 默认启用 fcc_auto。",
                    "enabled": self.spectral_enable_combo.currentText().strip() == "enabled",
                    "path_length_m": self.spectral_path_spin.value(),
                    "sensor_sep_m": self.spectral_sep_spin.value(),
                    "response_time_s": self.spectral_response_spin.value(),
                    "z_m": self.spectral_zm_spin.value(),
                    "ol": self.spectral_ol_spin.value(),
                    "use_fcc_measured_cospectrum": self.spectral_cospectrum_combo.currentText().strip() == "fcc_auto",
                    "preview": self.spectral_summary_label.text().strip(),
                },
                "primary_analyzer": self._collect_primary_analyzer_payload(),
                "method_compare": {
                    "title": "Method compare",
                    "method": "enabled" if self.method_compare_combo.currentText().strip() == "enabled" else "disabled",
                    "applicable": "Compare footprint / uncertainty / spectral correction method families on identical RP windows.",
                    "recommended": "Use for parity review and method provenance; selected processing methods are not changed automatically.",
                    "enabled": self.method_compare_combo.currentText().strip() == "enabled",
                    "families": ["footprint", "uncertainty", "spectral_correction"],
                    "deviation_threshold": self.method_compare_threshold_spin.value(),
                    "max_samples": 4096,
                    "footprint_methods": ["kljun", "kormann_meixner", "hsieh"],
                    "uncertainty_methods": ["mann_lenschow", "finkelstein_sims"],
                    "spectral_correction_methods": ["massman", "horst", "ibrom", "fratini"],
                },
                "output": {
                    "title": "输出",
                    "method": "标准结果 + 诊断摘要",
                    "applicable": "适用于项目归档与后续 QC。",
                    "recommended": "保留关键质量字段与诊断摘要。",
                    "output_fields": self.output_fields_edit.text().strip(),
                    "full_output_mode": self.full_output_mode_combo.currentText().strip(),
                },
            },
        }

    def _parse_int_list(self, text: str) -> list[int]:
        values: list[int] = []
        for token in text.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            values.append(int(token, 0))
        return values

    def _collect_primary_analyzer_payload(self) -> dict:
        profile_id = str(self.primary_analyzer_profile_combo.currentData() or "ygas_irga")
        warning_pct = float(self.primary_signal_warning_spin.value())
        fail_pct = float(self.primary_signal_fail_spin.value())
        cell_mode = self.primary_cell_thermo_combo.currentText().strip()
        allowed_text = self.primary_allowed_diag_words_edit.text().strip()
        payload = {
            "title": "Primary analyzer QC",
            "method": profile_id,
            "applicable": "CO2/H2O analyzer diagnostic screening and calibration provenance for RP processing.",
            "recommended": "Use the selected acquisition profile; keep source_file and normalization_command tied to the real calibration or diagnostic input.",
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
            "preview": self.primary_analyzer_summary_label.text().strip(),
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
        if allowed_text:
            try:
                payload["allowed_diagnostic_words"] = self._parse_int_list(allowed_text)
            except ValueError as exc:
                payload["allowed_diagnostic_words_text"] = allowed_text
                payload["allowed_diagnostic_words_parse_error"] = str(exc)
        return payload

    def _collect_crosswind_payload(self) -> dict:
        coefficients_text = self.crosswind_coefficients_edit.toPlainText().strip()
        payload = {
            "title": "Crosswind",
            "method": self.crosswind_method_combo.currentText().strip() or "liu_2001_crosswind_v1",
            "applicable": "Applies sonic-temperature crosswind correction before density and flux calculations.",
            "recommended": "Enable when the sonic/anemometer family requires crosswind temperature correction; keep disabled otherwise.",
            "enabled": self.crosswind_enable_combo.currentText().strip() == "enabled",
            "sonic_manufacturer": self.crosswind_manufacturer_combo.currentText().strip(),
            "sonic_model": self.crosswind_model_combo.currentText().strip(),
            "temperature_divisor": self.crosswind_temp_divisor_spin.value(),
            "coefficients_text": coefficients_text,
            "preview": self.crosswind_preview_label.text().strip(),
        }
        if coefficients_text:
            try:
                payload["coefficients"] = json.loads(coefficients_text)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                payload["coefficients_parse_error"] = str(exc)
        return payload

    def _run_processing(self, *, precheck_only: bool) -> None:
        if not self._save_processing(show_message=False):
            return
        try:
            result = self.controller.run_ec_processing(precheck_only=precheck_only)
        except Exception as exc:
            QMessageBox.warning(self, "运行失败", str(exc))
            return
        title = "预检查完成" if precheck_only else "处理已启动"
        QMessageBox.information(self, title, result["message"])

    def _save_processing(self, *, show_message: bool = True) -> bool:
        try:
            self.controller.save_ec_processing(self._collect_payload())
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        if show_message:
            QMessageBox.information(self, "保存完成", "EC 处理配置已保存，可继续运行或保存为模板。")
        return True

    def _save_template(self) -> None:
        if not self._save_processing(show_message=False):
            return
        self.controller.save_ec_template()
        QMessageBox.information(self, "模板已保存", "当前处理流程已保存为模板，可供后续项目复用。")

    def _restore_default(self) -> None:
        if (
            QMessageBox.question(
                self,
                "恢复默认",
                "将恢复默认处理流程。当前未保存的修改可能丢失，是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        self.controller.restore_default_ec_processing()

    def _refresh_run_bar(self, *_args) -> None:
        workspace = self.controller.ec_processing_workspace
        summary = workspace.get("summary", {})
        step_title = dict((key, title) for key, title, _subtitle in EC_STEPS).get(self.controller.ec_nav_step, "当前步骤")
        status = str(summary.get("status", "empty"))
        tone = "success" if status == "ok" else ("warning" if status == "empty" else "accent")
        self.run_status_chip.setText(f"{step_title} · {status}")
        self.run_status_chip.setProperty("chipTone", tone)
        self.run_status_chip.style().unpolish(self.run_status_chip)
        self.run_status_chip.style().polish(self.run_status_chip)
        self.run_summary_label.setText(str(summary.get("message", "尚未生成真实 RP 结果。")))
        self._refresh_workflow_lens()

    def _refresh_processing_cockpit(self, *_args) -> None:
        if not hasattr(self, "cockpit_method_value"):
            return
        workspace = self.controller.ec_processing_workspace
        summary = dict(workspace.get("summary", {}) or {})
        status = str(summary.get("status", "empty") or "empty")
        status_tone = "success" if status == "ok" else ("warning" if status == "empty" else "danger")
        self._set_cockpit_chip(f"RP {status}", status_tone)

        footprint_method = self._current_combo_text("footprint_method_combo", "kljun")
        uncertainty_method = self._current_combo_text("uncertainty_mode_combo", "mann_lenschow")
        spectral_method = self._current_combo_text("spectral_method_combo", "massman")
        method_compare = self._current_combo_text("method_compare_combo", "disabled")
        cospectrum = self._current_combo_text("spectral_cospectrum_combo", "fcc_auto")
        self.cockpit_method_value.setText(f"{footprint_method} / {uncertainty_method} / {spectral_method}")
        self.cockpit_method_note.setText(
            f"footprint={self._current_combo_text('footprint_enable_combo', 'enabled')}，"
            f"spectral={self._current_combo_text('spectral_enable_combo', 'enabled')}，"
            f"cospectrum={cospectrum}，compare={method_compare}"
        )

        run = self.controller.current_rp_run()
        current = self._current_window()
        diagnostics = dict(current.diagnostics or {}) if current is not None else {}
        if current is None:
            self.cockpit_result_value.setText("尚未运行")
            self.cockpit_result_note.setText(str(summary.get("message", "运行处理后显示 primary_flux 与 QC。")))
            self.cockpit_uncertainty_value.setText("待生成")
            self.cockpit_uncertainty_note.setText("运行后显示 random error、relative uncertainty 和 confidence band。")
        else:
            self.cockpit_result_value.setText(self._format_metric(current.primary_flux, digits=4))
            self.cockpit_result_note.setText(
                f"window={current.window_id}，source={current.primary_flux_source or '--'}，"
                f"QC={current.qc_grade}，windows={summary.get('valid_window_count', 0)}/{summary.get('window_count', 0)}"
            )
            band = diagnostics.get("primary_flux_uncertainty_band")
            random_error = diagnostics.get("primary_flux_random_error")
            relative = diagnostics.get("primary_flux_relative_uncertainty")
            ci_lower = diagnostics.get("primary_flux_ci_lower")
            ci_upper = diagnostics.get("primary_flux_ci_upper")
            self.cockpit_uncertainty_value.setText(f"±{self._format_metric(band, digits=4)}")
            self.cockpit_uncertainty_note.setText(
                f"random={self._format_metric(random_error, digits=4)}，"
                f"relative={self._format_percent(relative)}，"
                f"CI=[{self._format_metric(ci_lower, digits=4)}, {self._format_metric(ci_upper, digits=4)}]"
            )

        run_summary = dict(run.summary if run is not None else {})
        benchmark_state = dict(self.controller.report_center_workspace.get("benchmark", {}) or {})
        benchmark_status = str(
            run_summary.get("benchmark_status")
            or diagnostics.get("benchmark_status")
            or benchmark_state.get("status")
            or "inactive"
        )
        deviation = dict(
            run_summary.get("benchmark_deviation_summary")
            or diagnostics.get("benchmark_deviation_summary")
            or {}
        )
        pass_rate = run_summary.get("pass_rate", deviation.get("pass_rate"))
        failed_fields = run_summary.get("failed_fields", deviation.get("failed_fields", []))
        if isinstance(failed_fields, str):
            failed_fields = [failed_fields]
        benchmark_value = self._format_percent(pass_rate) if isinstance(pass_rate, (int, float)) else benchmark_status
        self.cockpit_benchmark_value.setText(benchmark_value)
        self.cockpit_benchmark_note.setText(
            f"status={benchmark_status}，ref={run_summary.get('benchmark_reference_id') or benchmark_state.get('reference_id') or '--'}，"
            f"failed={len(failed_fields or [])}"
        )

        network = dict(self.controller.report_center_workspace.get("network_output", {}) or {})
        export_status = str(self.controller.report_center_workspace.get("export_status", "not_exported") or "not_exported")
        schema_target = diagnostics.get("schema_target") or network.get("schema_target", "FLUXNET")
        validation_status = diagnostics.get("validation_status", diagnostics.get("network_validation_status", "--"))
        missing_fields = diagnostics.get("missing_fields", diagnostics.get("network_missing_fields", []))
        if isinstance(missing_fields, str):
            missing_fields = [missing_fields]
        self.cockpit_delivery_value.setText(str(schema_target))
        self.cockpit_delivery_note.setText(
            f"validation={validation_status}，missing={len(missing_fields or [])}，export={export_status[:48]}"
        )

    def _set_cockpit_chip(self, text: str, tone: str) -> None:
        self.cockpit_status_chip.setText(text)
        self.cockpit_status_chip.setProperty("chipTone", tone)
        self.cockpit_status_chip.style().unpolish(self.cockpit_status_chip)
        self.cockpit_status_chip.style().polish(self.cockpit_status_chip)

    def _current_combo_text(self, attr_name: str, default: str) -> str:
        combo = getattr(self, attr_name, None)
        if combo is None:
            return default
        text = combo.currentText().strip()
        return text or default

    def _format_metric(self, value: object, *, digits: int = 3) -> str:
        if not isinstance(value, (int, float)):
            return "--"
        return f"{float(value):.{digits}g}"

    def _format_percent(self, value: object) -> str:
        if not isinstance(value, (int, float)):
            return "--"
        numeric = float(value)
        if abs(numeric) <= 1.0:
            numeric *= 100.0
        return f"{numeric:.1f}%"

    def _refresh_readiness_panel(self) -> None:
        if not hasattr(self, "window_readiness_value"):
            return
        current = self._current_window()
        if current is None:
            samples = self.window_minutes_spin.value() * self.window_sample_hz_spin.value() * 60
            self.window_readiness_value.setText(f"{samples:,}")
            self.window_readiness_note.setText(
                f"{self.window_minutes_spin.value()} min × {self.window_sample_hz_spin.value()} Hz，等待 RP 运行验证。"
            )
        else:
            self.window_readiness_value.setText(f"{current.sample_count:,}")
            self.window_readiness_note.setText(
                f"window={current.window_id}，lag={current.lag_seconds:.3f}s，missing={current.missing_ratio * 100:.1f}%"
            )

        footprint_method = self._current_combo_text("footprint_method_combo", "kljun")
        uncertainty_method = self._current_combo_text("uncertainty_mode_combo", "mann_lenschow")
        spectral_method = self._current_combo_text("spectral_method_combo", "massman")
        self.method_readiness_value.setText(f"{footprint_method} / {uncertainty_method}")
        self.method_readiness_note.setText(
            f"spectral={spectral_method}，cospectrum={self._current_combo_text('spectral_cospectrum_combo', 'fcc_auto')}，"
            f"compare={self._current_combo_text('method_compare_combo', 'disabled')}"
        )

        diagnostics = dict(current.diagnostics or {}) if current is not None else {}
        network = dict(self.controller.report_center_workspace.get("network_output", {}) or {})
        schema_target = diagnostics.get("schema_target") or network.get("schema_target", "FLUXNET")
        export_status = str(self.controller.report_center_workspace.get("export_status", "not_exported") or "not_exported")
        validation_status = diagnostics.get("validation_status", diagnostics.get("network_validation_status", "--"))
        self.delivery_readiness_value.setText(str(schema_target))
        self.delivery_readiness_note.setText(f"validation={validation_status}，export={export_status[:56]}")
        self._refresh_output_coverage_panel()

    def _refresh_window_preview(self, *_args) -> None:
        section = self._section_workspace("window_sampling")
        current = self._current_window()
        if current is None:
            samples = self.window_minutes_spin.value() * self.window_sample_hz_spin.value() * 60
            self.window_samples_label.setText(f"{samples:,} 点 / 窗口")
            self.window_preview_note.setText("暂无真实 RP 结果，运行处理后显示窗口切分与连续性摘要。")
            xs = np.arange(1, 5, dtype=float)
            ys = np.full_like(xs, float(samples), dtype=float)
            self.window_plan_curve.setData(xs, ys)
            self.window_plan_note.setText("预览 4 个待处理窗口；运行后会显示真实窗口样本量和连续性。")
            self._refresh_readiness_panel()
            return
        self.window_samples_label.setText(f"{current.sample_count:,} 点 / 当前窗口")
        self.window_preview_note.setText(str(section.get("real_summary", "窗口摘要不可用。")))
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if windows:
            xs = np.arange(1, len(windows) + 1, dtype=float)
            ys = np.array([float(window.get("sample_count", current.sample_count) or 0.0) for window in windows], dtype=float)
        else:
            xs = np.array([1.0], dtype=float)
            ys = np.array([float(current.sample_count)], dtype=float)
        self.window_plan_curve.setData(xs, ys)
        self.window_plan_note.setText(
            f"真实窗口 {len(xs)} 个；当前窗口 {current.window_id}，缺测率 {current.missing_ratio * 100:.1f}%。"
        )
        self._refresh_readiness_panel()

    def _refresh_cleaning_preview(self, *_args) -> None:
        section = self._section_workspace("data_cleaning")
        current = self._current_window()
        if current is None:
            self.clean_removed_ratio_label.setText("--")
            self.clean_retained_label.setText("暂无真实 RP 结果，运行处理后显示缺失率和有效样本摘要。")
            return
        self.clean_removed_ratio_label.setText(f"{current.missing_ratio * 100:.1f}%")
        self.clean_retained_label.setText(str(section.get("real_summary", current.reason)))

    def _refresh_screening_preview(self, *_args) -> None:
        config_summary = (
            f"当前配置：偏度阈值={self.screening_skewness_spin.value():.1f}，"
            f"峰度阈值={self.screening_kurtosis_spin.value():.1f}，"
            f"dropout最小连续点={self.screening_dropout_min_run_spin.value()}，"
            f"尖峰σ={self.screening_spike_sigma_spin.value():.1f}，"
            f"不连续σ={self.screening_discontinuity_sigma_spin.value():.1f}。"
        )
        abs_text = self.screening_absolute_limits_edit.toPlainText().strip()
        if abs_text:
            config_summary += f" 绝对值范围：{abs_text}"
        current = self._current_window()
        if current is None:
            self.screening_summary_label.setText(f"{config_summary}\n暂无真实 RP 结果，运行处理后显示筛选摘要。")
            return
        diagnostics = current.diagnostics or {}
        screening_detail = diagnostics.get("screening_detail", {})
        issues = diagnostics.get("issues", [])
        screening_issues = [i for i in issues if not i.startswith("spike_") or "screening" in str(diagnostics.get("screening_config", {}))]
        if screening_detail:
            lines = []
            for var_name, detail in screening_detail.items():
                if isinstance(detail, dict):
                    var_issues = detail.get("issues", [])
                    if var_issues:
                        lines.append(f"{var_name}: {', '.join(var_issues)}")
            if lines:
                self.screening_summary_label.setText(f"{config_summary}\n检测到问题: {'; '.join(lines)}")
            else:
                self.screening_summary_label.setText(f"{config_summary}\n所有变量通过统计筛选。")
        else:
            self.screening_summary_label.setText(f"{config_summary}\nissues={len(issues)}")

    def _refresh_lag_preview(self, *_args) -> None:
        section = self._section_workspace("lag")
        current = self._current_window()
        if current is None:
            self.lag_curve.setData([], [])
            self.lag_note_label.setText("暂无真实 RP 结果，运行处理后显示 lag 协方差曲线。")
            return
        x_values = section.get("intermediate", {}).get("lag_curve_x", [])
        y_values = section.get("intermediate", {}).get("lag_curve_y", [])
        self.lag_curve.setData(x_values, y_values)
        lag_strategy = current.diagnostics.get("lag_strategy", "covariance_max") if current.diagnostics else "covariance_max"
        screening_detail = current.diagnostics.get("screening_detail", {}) if current.diagnostics else {}
        screening_summary = ""
        if screening_detail:
            issue_vars = [k for k, v in screening_detail.items() if isinstance(v, dict) and v.get("valid_count", 0) > 0]
            screening_summary = f"；screening: {', '.join(issue_vars)}" if issue_vars else ""
        self.lag_note_label.setText(
            f"strategy={lag_strategy}, lag={current.lag_seconds:.3f}s, conf={current.lag_confidence:.2f}{screening_summary}。"
        )

    def _refresh_rotation_preview(self, *_args) -> None:
        section = self._section_workspace("rotation")
        if self._current_window() is None:
            self.rotation_preview_label.setText("暂无真实 RP 结果，运行处理后显示旋转模式与回退原因。")
            return
        self.rotation_preview_label.setText(str(section.get("real_summary", "旋转摘要不可用。")))

    def _refresh_crosswind_preview(self, *_args) -> None:
        enabled = self.crosswind_enable_combo.currentText().strip() == "enabled"
        method = self.crosswind_method_combo.currentText().strip() or "liu_2001_crosswind_v1"
        manufacturer = self.crosswind_manufacturer_combo.currentText().strip() or "unknown"
        model = self.crosswind_model_combo.currentText().strip() or "unknown"
        coefficients_text = self.crosswind_coefficients_edit.toPlainText().strip()
        coefficient_status = "custom coefficients" if coefficients_text else "built-in coefficients"
        config_summary = (
            f"enabled={enabled} / method={method} / sonic={manufacturer}/{model} / "
            f"temperature_divisor={self.crosswind_temp_divisor_spin.value():.1f} / {coefficient_status}"
        )
        current = self._current_window()
        if current is None:
            self.crosswind_preview_label.setText(
                f"{config_summary}\nNo RP result yet; run processing to inspect correction status and temperature delta."
            )
            return
        diagnostics = current.diagnostics or {}
        status = diagnostics.get("crosswind_correction_status", "not_available")
        run_method = diagnostics.get("crosswind_correction_method", method)
        mean_delta = diagnostics.get("crosswind_correction_mean_delta_c")
        max_delta = diagnostics.get("crosswind_correction_max_abs_delta_c")
        delta_text = (
            f"mean_delta_c={float(mean_delta):.6f}, max_abs_delta_c={float(max_delta or 0.0):.6f}"
            if isinstance(mean_delta, (int, float))
            else "delta not available"
        )
        self.crosswind_preview_label.setText(
            f"{config_summary}\nrun_status={status} / run_method={run_method} / {delta_text}"
        )

    def _refresh_detrend_preview(self, *_args) -> None:
        section = self._section_workspace("detrend")
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if self._current_window() is None:
            self.detrend_raw_curve.setData([], [])
            self.detrend_primary_curve.setData([], [])
            self.detrend_preview_label.setText("暂无真实 RP 结果，运行处理后显示去趋势模式摘要。")
            return
        xs, raw_flux = self._series_from_windows(windows, "raw_flux")
        _, primary_flux = self._series_from_windows(windows, "primary_flux", fallback_key="density_corrected_flux")
        self.detrend_raw_curve.setData(xs, raw_flux)
        self.detrend_primary_curve.setData(xs, primary_flux)
        self.detrend_preview_label.setText(str(section.get("real_summary", "去趋势摘要不可用。")))

    def _refresh_covariance_preview(self, *_args) -> None:
        current = self._current_window()
        if current is None:
            self.covariance_metric_flux.setText("--")
            self.covariance_metric_h2o.setText("--")
            self.covariance_metric_temp.setText("--")
            return
        self.covariance_metric_flux.setText(f"{current.cov_w_co2:.6f}")
        self.covariance_metric_h2o.setText(f"{current.cov_w_h2o:.6f}")
        self.covariance_metric_temp.setText(f"{current.raw_flux:.6f}")

    def _refresh_density_preview(self, *_args) -> None:
        windows = self.controller.ec_processing_workspace.get("windows", [])
        section = self._section_workspace("density_correction")
        current = self._current_window()
        if not windows or current is None:
            self.density_before_curve.setData([], [])
            self.density_after_curve.setData([], [])
            self.density_before_label.setText("--")
            self.density_after_label.setText("--")
            self.density_note_label.setText("暂无真实 RP 结果，运行处理后显示密度/混合比修正摘要。")
            return
        xs = np.arange(1, len(windows) + 1, dtype=float)
        before = np.array([float(window.get("raw_flux", 0.0)) for window in windows], dtype=float)
        after = np.array([float(window.get("primary_flux", window.get("density_corrected_flux", 0.0))) for window in windows], dtype=float)
        self.density_before_curve.setData(xs, before)
        self.density_after_curve.setData(xs, after)
        self.density_before_label.setText(f"{current.raw_flux:.6f}")
        primary_flux_val = current.primary_flux if current.primary_flux != 0.0 else current.density_corrected_flux
        primary_source = current.primary_flux_source or "wpl"
        self.density_after_label.setText(f"{primary_flux_val:.6f} [{primary_source}]")
        self.density_note_label.setText(str(section.get("real_summary", current.reason)))

    def _refresh_steadiness_preview(self, *_args) -> None:
        section = self._section_workspace("steadiness")
        current = self._current_window()
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if current is None:
            self.steadiness_score_curve.setData([], [])
            self.steadiness_preview_label.setText("暂无真实 RP 结果，运行处理后显示窗口级 QC 与异常原因。")
            return
        xs, scores = self._series_from_windows(windows, "stationarity_score")
        self.steadiness_score_curve.setData(xs, scores)
        self.steadiness_preview_label.setText(str(section.get("real_summary", current.reason)))

    def _refresh_turbulence_preview(self, *_args) -> None:
        section = self._section_workspace("turbulence")
        current = self._current_window()
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if current is None:
            self.turbulence_ustar_curve.setData([], [])
            self.turbulence_score_curve.setData([], [])
            self.turbulence_preview_label.setText("暂无真实 RP 结果。")
            return
        xs, ustar = self._series_from_windows(windows, "ustar")
        _, score = self._series_from_windows(windows, "turbulence_score")
        self.turbulence_ustar_curve.setData(xs, ustar)
        self.turbulence_score_curve.setData(xs, score)
        detail = current.turbulence_detail or {}
        self.turbulence_preview_label.setText(
            str(
                section.get(
                    "real_summary",
                    f"u*={current.ustar or 0.0:.3f} m/s, score={current.turbulence_score or 0.0:.1f}, status={detail.get('status', 'unknown')}.",
                )
            )
        )

    def _refresh_uncertainty_preview(self, *_args) -> None:
        current = self._current_window()
        self.footprint_summary_label.setText(
            " / ".join(
                [
                    f"enabled={self.footprint_enable_combo.currentText().strip()}",
                    f"method={self.footprint_method_combo.currentText().strip()}",
                    f"z_m={self.footprint_zm_spin.value():.2f}",
                    f"canopy={self.footprint_canopy_spin.value():.2f}",
                    f"grid2d={self.footprint_grid_combo.currentText().strip()}",
                    f"grid={self.footprint_grid_x_spin.value()}x{self.footprint_grid_y_spin.value()}",
                ]
            )
        )
        self.uncertainty_summary_label.setText(
            " / ".join(
                [
                    f"method={self.uncertainty_mode_combo.currentText().strip()}",
                    f"integral_timescale_s={self.uncertainty_timescale_spin.value():.1f}",
                    f"confidence_level={self.uncertainty_confidence_spin.value():.2f}",
                ]
            )
        )
        self.spectral_summary_label.setText(
            " / ".join(
                [
                    f"enabled={self.spectral_enable_combo.currentText().strip()}",
                    f"method={self.spectral_method_combo.currentText().strip()}",
                    f"path_length_m={self.spectral_path_spin.value():.3f}",
                    f"cospectrum={self.spectral_cospectrum_combo.currentText().strip()}",
                    f"compare={self.method_compare_combo.currentText().strip()}",
                ]
            )
        )
        self._refresh_method_control_summary()
        if current is None:
            values = ("--", "--", "--")
            note = "暂无真实 RP 结果，运行处理后显示 primary flux uncertainty band 和 Fratini/FCC 路径。"
        else:
            detail = current.uncertainty_detail or {}
            diagnostics = current.diagnostics or {}
            values = (
                f"{float(diagnostics.get('primary_flux_random_error', detail.get('primary_flux_random_error', 0.0)) or 0.0):.6f}",
                f"{float(diagnostics.get('primary_flux_relative_uncertainty', detail.get('primary_flux_relative_uncertainty', detail.get('relative_uncertainty', 0.0))) or 0.0):.3f}",
                f"{float(diagnostics.get('primary_flux_uncertainty_band', detail.get('primary_flux_uncertainty_band', 0.0)) or 0.0):.6f}",
            )
            note = (
                f"footprint={diagnostics.get('footprint_method', '--')} / "
                f"uncertainty={diagnostics.get('uncertainty_method', detail.get('selected_method', '--'))} / "
                f"spectral={diagnostics.get('spectral_correction_method', '--')} / "
                f"cospectrum={diagnostics.get('spectral_correction_measured_cospectrum_source', 'disabled') or 'disabled'} / "
                f"method_compare={len(diagnostics.get('method_compare_summary', {}) or {})}"
            )
        self.uncertainty_sampling_label.setText(values[0])
        self.uncertainty_sensor_label.setText(values[1])
        self.uncertainty_processing_label.setText(values[2])
        self.uncertainty_preview_note.setText(note)
        self._refresh_processing_cockpit()
        self._refresh_readiness_panel()

    def _refresh_primary_analyzer_preview(self, *_args) -> None:
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
            if isinstance(command, dict) and str(command.get("mode", "")).lower().find("read") >= 0
        ]
        raw_fields = list(profile.get("raw_output_fields", []) or [])
        source_file = self.primary_source_file_edit.text().strip()
        normalization = self.primary_normalization_command_edit.text().strip()
        threshold_text = (
            f"warning={self.primary_signal_warning_spin.value():.1f}% / "
            f"fail={self.primary_signal_fail_spin.value():.1f}%"
        )
        config_summary = (
            f"profile={profile_id} / enabled={self.primary_analyzer_enable_combo.currentText().strip()} / "
            f"{threshold_text} / status_ok={self.primary_require_status_combo.currentText().strip()} / "
            f"cell={self.primary_cell_thermo_combo.currentText().strip()} / "
            f"commands={','.join(commands) or '--'} / fields={len(raw_fields)}"
        )
        current = self._current_window()
        if current is None:
            self.primary_analyzer_summary_label.setText(
                f"{config_summary}\nsource={source_file or '--'} / normalization={normalization or '--'}"
            )
            return
        diagnostics = current.diagnostics or {}
        detail = dict(diagnostics.get("primary_analyzer_detail", {}) or {})
        status = diagnostics.get("primary_analyzer_status", detail.get("status", "not_available"))
        telemetry = detail.get("telemetry_detected", diagnostics.get("primary_analyzer_telemetry_detected", False))
        fault_count = len(detail.get("active_faults", []) or [])
        self.primary_analyzer_summary_label.setText(
            f"{config_summary}\nrun_status={status} / telemetry={telemetry} / faults={fault_count} / "
            f"calibration_profile={detail.get('calibration_profile_id', self.primary_calibration_profile_edit.text().strip()) or '--'}"
        )

    def _refresh_output_preview(self, *_args) -> None:
        workspace = self.controller.ec_processing_workspace
        current = self._current_window()
        text = self.output_fields_edit.text().strip()
        fields = [field.strip() for field in text.split(",") if field.strip()]
        if current is None:
            self.output_preview_label.setText("暂无真实 RP 结果。")
            self._refresh_processing_cockpit()
            self._refresh_readiness_panel()
            return
        summary = workspace.get("summary", {})
        field_text = "、".join(fields[:6]) if fields else "未设置输出字段"
        diagnostics = current.diagnostics or {}
        self.output_preview_label.setText(
            f"运行状态 {summary.get('status', 'empty')}，窗口数 {summary.get('window_count', 0)}，"
            f"full_output={self.full_output_mode_combo.currentText().strip()}，字段：{field_text}，"
            f"uncertainty_band={diagnostics.get('primary_flux_uncertainty_band', '--')}，"
            f"schema_target={diagnostics.get('schema_target', '--')}。"
        )
        self._refresh_processing_cockpit()
        self._refresh_readiness_panel()

    def _section_workspace(self, key: str) -> dict:
        return dict(self.controller.ec_processing_workspace.get("sections", {}).get(key, {}))

    def _series_from_windows(self, windows: list[dict], key: str, *, fallback_key: str | None = None) -> tuple[np.ndarray, np.ndarray]:
        if not windows:
            return np.array([], dtype=float), np.array([], dtype=float)
        xs = np.arange(1, len(windows) + 1, dtype=float)
        values: list[float] = []
        for window in windows:
            value = window.get(key)
            if value is None and fallback_key:
                value = window.get(fallback_key)
            try:
                values.append(float(value if value is not None else 0.0))
            except (TypeError, ValueError):
                values.append(0.0)
        return xs, np.array(values, dtype=float)

    def _current_window(self):
        return self.controller.current_rp_window()

    def _metric_box(self, title: str, widget: QWidget) -> CardFrame:
        card = CardFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_xs)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        layout.addWidget(label)
        if isinstance(widget, QLabel):
            widget.setObjectName("metricValue")
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        layout.addWidget(widget)
        return card

    def _on_lag_strategy_changed(self) -> None:
        strategy = self.lag_strategy_combo.currentText().strip()
        is_constant = strategy in ("固定滞后", "constant")
        is_none = strategy in ("无滞后", "none")
        self.lag_expected_spin.setEnabled(is_constant)
        self.lag_search_window_spin.setEnabled(not is_none and not is_constant)

    def _double_spin(self, low: float, high: float, decimals: int, *, suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        text = value.strip()
        if not text:
            return
        index = combo.findText(text)
        if index < 0:
            combo.addItem(text)
            index = combo.findText(text)
        combo.setCurrentIndex(index)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        text = value.strip()
        if not text:
            return
        index = combo.findData(text)
        if index < 0:
            index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)
