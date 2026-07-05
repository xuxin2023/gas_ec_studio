from __future__ import annotations

import json

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
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
    QSizePolicy,
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
        self.setProperty("pageSurface", True)
        self.controller = controller
        self.step_indexes: dict[str, int] = {}
        self.step_items: dict[str, QTreeWidgetItem] = {}
        self.step_status_labels: dict[str, str] = {}
        self.workflow_lens_buttons: dict[str, QPushButton] = {}
        self.workflow_lens_notes: dict[str, QLabel] = {}
        self.desktop_rail_mode_buttons: dict[str, QToolButton] = {}
        self.coverage_values: dict[str, QLabel] = {}
        self.step_command_strips: dict[str, CardFrame] = {}
        self.step_command_tiles: dict[str, dict[str, CardFrame]] = {}
        self.step_command_values: dict[str, dict[str, QLabel]] = {}
        self.step_command_notes: dict[str, dict[str, QLabel]] = {}
        self.step_command_buttons: dict[str, dict[str, QToolButton]] = {}
        self.step_phase_buttons: dict[str, QToolButton] = {}
        self.method_shortcut_buttons: dict[str, QToolButton] = {}
        self.method_shortcut_labels: dict[str, str] = {}
        self.method_shortcut_pills: dict[str, QLabel] = {}
        self.method_console_mode_buttons: dict[str, QToolButton] = {}
        self.method_family_control_strips: dict[str, QWidget] = {}
        self.method_family_control_tiles: dict[str, dict[str, CardFrame]] = {}
        self.method_family_control_values: dict[str, dict[str, QLabel]] = {}
        self.method_family_control_notes: dict[str, dict[str, QLabel]] = {}
        self.window_console_switches: dict[str, QToolButton] = {}
        self.rp_closure_mode_buttons: dict[str, QToolButton] = {}

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
        self.rp_closure_deck = self._build_rp_closure_deck()
        layout.addWidget(self.rp_closure_deck)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        layout.addWidget(body, 1)

        self.tree_card = CardFrame(muted=True, role="rail")
        self.tree_card.setProperty("ecProcessRail", True)
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_sm)
        step_header = QHBoxLayout()
        step_header.setContentsMargins(0, 0, 0, 0)
        step_header.setSpacing(TOKENS.spacing_xs)
        step_header.addWidget(section_title("处理流程", "按步骤导航，状态同屏。"), 1)
        self.step_count_chip = chip("0 步", "accent")
        self.step_count_chip.setMinimumHeight(22)
        self.step_count_chip.setMaximumHeight(24)
        self.step_active_chip = chip("窗口", "success")
        self.step_active_chip.setMinimumHeight(22)
        self.step_active_chip.setMaximumHeight(24)
        step_header.addWidget(self.step_count_chip)
        step_header.addWidget(self.step_active_chip)
        tree_layout.addLayout(step_header)
        self.step_nav_summary_card = CardFrame(muted=True, role="tile")
        self.step_nav_summary_card.setProperty("deckRole", "ecStepNavigationStatus")
        self.step_nav_summary_card.setMaximumHeight(42)
        summary_layout = QHBoxLayout(self.step_nav_summary_card)
        summary_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        summary_layout.setSpacing(TOKENS.spacing_xs)
        summary_title = QLabel("步骤状态")
        summary_title.setObjectName("metricLabel")
        self.step_nav_summary_value = QLabel("--")
        self.step_nav_summary_value.setObjectName("metricValue")
        self.step_nav_summary_value.setProperty("compactMetric", True)
        self.step_nav_summary_value.setMinimumWidth(0)
        self.step_nav_summary_value.setWordWrap(False)
        self.step_nav_summary_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.step_nav_summary_value, 1)
        tree_layout.addWidget(self.step_nav_summary_card)
        self.step_phase_map = QWidget()
        self.step_phase_map.setProperty("stepPhaseMap", True)
        self.step_phase_map.setMaximumHeight(78)
        phase_layout = QGridLayout(self.step_phase_map)
        phase_layout.setContentsMargins(0, 0, 0, 0)
        phase_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        phase_layout.setVerticalSpacing(TOKENS.spacing_xs)
        phase_titles = {
            "project": "项目",
            "core": "核心",
            "advanced": "高级",
            "delivery": "交付",
        }
        for index, (lens_key, title, _subtitle, _steps) in enumerate(WORKFLOW_LENSES):
            button = QToolButton()
            button.setText(phase_titles.get(lens_key, title))
            button.setCheckable(True)
            button.setProperty("stepPhaseTile", True)
            button.setProperty("phaseKey", lens_key)
            button.setProperty("phaseTone", "warning")
            button.setMaximumHeight(34)
            button.clicked.connect(lambda _checked=False, key=lens_key: self._select_workflow_lens(key))
            self.step_phase_buttons[lens_key] = button
            phase_layout.addWidget(button, index // 2, index % 2)
        tree_layout.addWidget(self.step_phase_map)

        self.step_tree = QTreeWidget()
        self.step_tree.setObjectName("workflowTree")
        self.step_tree.setColumnCount(2)
        self.step_tree.setColumnWidth(0, 122)
        self.step_tree.setColumnWidth(1, 52)
        self.step_tree.setHeaderHidden(True)
        self.step_tree.setIndentation(0)
        self.step_tree.setRootIsDecorated(False)
        self.step_tree.setUniformRowHeights(True)
        self.step_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.step_tree.itemSelectionChanged.connect(self._on_step_changed)
        tree_layout.addWidget(self.step_tree, 1)
        self.tree_card.setMinimumWidth(210)
        self.tree_card.setMaximumWidth(260)
        body.addWidget(self.tree_card)

        self.content_stack = QStackedWidget()
        body.addWidget(self.content_stack)

        self.desktop_rail = self._build_desktop_rail()
        body.addWidget(self.desktop_rail)
        body.setSizes([220, 820, 300])

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
        self.footprint_zm_spin.setValue(float(footprint_step.get("z_m", 6.0) or 6.0))
        self.footprint_canopy_spin.setValue(float(footprint_step.get("canopy_height_m", 3.0) or 3.0))
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
        self._refresh_step_tree_statuses()
        self._sync_step_from_controller()

    def _build_run_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setProperty("deckRole", "runCommandRibbon")
        card.setProperty("runCommandDock", True)
        card.setProperty("processingRunCommandDock", True)
        card.setMaximumHeight(74)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_xs, TOKENS.spacing_lg, TOKENS.spacing_xs)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(1)

        intro = section_title("运行条", "先选择数据来源与时间范围，再决定正式运行还是仅做预检查。")
        intro.setMaximumWidth(210)
        intro.setMaximumHeight(48)
        layout.addWidget(intro, 0, 0, 2, 1)

        self.data_source_combo = QComboBox()
        self.data_source_combo.setEditable(True)
        self.data_source_combo.addItems(["当前项目高频目录", "最近归档批次", "回放文件夹"])
        self.data_source_combo.setMinimumWidth(170)
        self.data_source_combo.setMaximumHeight(28)
        self.data_source_combo.setProperty("runRibbonField", True)
        self.time_range_combo = QComboBox()
        self.time_range_combo.setEditable(True)
        self.time_range_combo.addItems(["最近 24 小时", "今天", "最近 7 天", "自定义时间窗"])
        self.time_range_combo.setMinimumWidth(150)
        self.time_range_combo.setMaximumHeight(28)
        self.time_range_combo.setProperty("runRibbonField", True)
        layout.addWidget(QLabel("数据来源"), 0, 1)
        layout.addWidget(self.data_source_combo, 0, 2)
        layout.addWidget(QLabel("时间范围"), 0, 3)
        layout.addWidget(self.time_range_combo, 0, 4)

        self.run_status_chip = chip("标准运行", "accent")
        layout.addWidget(self.run_status_chip, 0, 5)

        self.run_mission_strip = CardFrame(muted=True, role="tile")
        self.run_mission_strip.setProperty("runMissionStrip", True)
        self.run_mission_strip.setMaximumHeight(28)
        mission_layout = QHBoxLayout(self.run_mission_strip)
        mission_layout.setContentsMargins(TOKENS.spacing_sm, 0, TOKENS.spacing_sm, 0)
        mission_layout.setSpacing(TOKENS.spacing_xs)
        self.run_mission_values: dict[str, QLabel] = {}
        for key, title in (("step", "步骤"), ("status", "运行"), ("gate", "交付")):
            label = QLabel(title)
            label.setObjectName("metricLabel")
            label.setProperty("runMissionLabel", True)
            value = QLabel("--")
            value.setObjectName("subtitle")
            value.setProperty("runMissionValue", True)
            value.setWordWrap(False)
            value.setMinimumWidth(36)
            value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.run_mission_values[key] = value
            mission_layout.addWidget(label)
            mission_layout.addWidget(value)
        self.run_summary_label = QLabel("尚未生成真实 RP 结果。")
        self.run_summary_label.setObjectName("subtitle")
        self.run_summary_label.setProperty("runMissionText", True)
        self.run_summary_label.setWordWrap(False)
        self.run_summary_label.setMinimumWidth(180)
        self.run_summary_label.setMaximumHeight(22)
        mission_layout.addWidget(self.run_summary_label, 2)
        layout.addWidget(self.run_mission_strip, 1, 1, 1, 3)

        run_button = QPushButton("运行处理")
        run_button.setProperty("variant", "primary")
        run_button.clicked.connect(lambda: self._run_processing(precheck_only=False))
        precheck_button = QPushButton("仅预检查")
        precheck_button.clicked.connect(lambda: self._run_processing(precheck_only=True))
        save_template_button = QPushButton("保存模板")
        save_template_button.clicked.connect(self._save_template)
        restore_button = QPushButton("恢复默认")
        restore_button.clicked.connect(self._restore_default)
        for column, button in enumerate((run_button, precheck_button, save_template_button, restore_button), start=4):
            button.setMinimumWidth(0)
            button.setMaximumHeight(28)
            button.setProperty("runRibbonAction", True)
            layout.addWidget(button, 1, column)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(4, 1)
        return card

    def _build_rp_closure_deck(self) -> CardFrame:
        card = CardFrame(role="cockpit")
        self.rp_closure_deck = card
        card.setProperty("deckRole", "rpClosureDeck")
        card.setProperty("processingClosureDeck", True)
        card.setMaximumHeight(92)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)

        intro = QVBoxLayout()
        intro.setSpacing(TOKENS.spacing_xs)
        intro_title = section_title("RP 闭环总控", "通量、方法、对标和网络交付固定在首屏。")
        intro_title.setMaximumWidth(160)
        intro.addWidget(intro_title)
        self.rp_closure_chip = chip("待运行", "warning")
        intro.addWidget(self.rp_closure_chip)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(TOKENS.spacing_xs)
        for mode, text in (("compact", "压缩"), ("detail", "详情")):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.setProperty("closureModeSwitch", True)
            button.setMinimumWidth(48)
            button.setMaximumHeight(24)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_rp_closure_mode(key))
            self.rp_closure_mode_buttons[mode] = button
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        intro.addLayout(mode_row)
        layout.addLayout(intro)

        self.rp_closure_stack = QStackedWidget()
        self.rp_closure_stack.setMinimumWidth(0)
        self.rp_closure_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.rp_closure_compact_strip = QWidget()
        self.rp_closure_compact_strip.setProperty("deckRole", "rpClosureCompactStrip")
        compact_layout = QGridLayout(self.rp_closure_compact_strip)
        compact_layout.setContentsMargins(0, 0, 0, 0)
        compact_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        compact_layout.setVerticalSpacing(TOKENS.spacing_xs)
        self.rp_closure_compact_tiles: dict[str, CardFrame] = {}
        self.rp_closure_compact_values: dict[str, QLabel] = {}
        self.rp_closure_method_pills: dict[str, QLabel] = {}

        detail_widget = QWidget()
        detail_widget.setProperty("deckRole", "rpClosureDetailGrid")
        grid = QGridLayout(detail_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        self.rp_closure_tiles: dict[str, CardFrame] = {}
        self.rp_closure_values: dict[str, QLabel] = {}
        self.rp_closure_notes: dict[str, QLabel] = {}
        self.rp_closure_chips: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(
            (
                ("run", "运行"),
                ("flux", "主通量"),
                ("uncertainty", "不确定度"),
                ("methods", "方法"),
                ("benchmark", "对标"),
                ("network", "网络"),
            )
        ):
            compact_layout.addWidget(self._rp_closure_compact_tile(key, title), 0, index)
            grid.addWidget(self._rp_closure_tile(key, title), index // 3, index % 3)
            compact_layout.setColumnStretch(index, 1)
        self.rp_closure_stack.addWidget(self.rp_closure_compact_strip)
        self.rp_closure_stack.addWidget(detail_widget)
        layout.addWidget(self.rp_closure_stack, 1)
        self._show_rp_closure_mode("compact")
        return card

    def _rp_closure_compact_tile(self, key: str, title: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("closureCompactTile", True)
        tile.setProperty("evidenceKey", key)
        if key in {"methods", "benchmark", "network"}:
            tile.setProperty("deliveryGateTile", True)
        tile.setMinimumWidth(0)
        tile.setMaximumHeight(48)
        tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        tile_layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        title_label.setWordWrap(False)
        value_label = QLabel("--")
        value_label.setObjectName("metricValue")
        value_label.setProperty("compactMetric", True)
        value_label.setWordWrap(False)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tile_layout.addWidget(title_label)
        if key == "methods":
            value_label.setVisible(False)
            pill_strip = QWidget()
            pill_strip.setProperty("rpClosureMethodPillStrip", True)
            pill_strip.setMaximumHeight(18)
            pill_layout = QHBoxLayout(pill_strip)
            pill_layout.setContentsMargins(0, 0, 0, 0)
            pill_layout.setSpacing(2)
            for family, label_text in (
                ("footprint", "足"),
                ("uncertainty", "误"),
                ("spectral", "谱"),
            ):
                pill = QLabel(f"{label_text} --")
                pill.setObjectName("subtitle")
                pill.setProperty("rpClosureMethodPill", True)
                pill.setProperty("methodFamily", family)
                pill.setProperty("methodTone", "accent")
                pill.setWordWrap(False)
                pill.setMinimumWidth(0)
                pill.setMaximumHeight(18)
                pill.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                self.rp_closure_method_pills[family] = pill
                pill_layout.addWidget(pill, 1)
            tile_layout.addWidget(pill_strip)
        else:
            tile_layout.addWidget(value_label)
        self.rp_closure_compact_tiles[key] = tile
        self.rp_closure_compact_values[key] = value_label
        return tile

    def _rp_closure_tile(self, key: str, title: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("evidenceKey", key)
        tile.setMinimumWidth(0)
        tile.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        tile.setMinimumHeight(58)
        tile.setMaximumHeight(62)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        tile_layout.setSpacing(1)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(TOKENS.spacing_xs)
        label = QLabel(title)
        label.setObjectName("metricLabel")
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        status_chip = chip("待检查", "warning")
        status_chip.setProperty("closureStage", True)
        status_chip.setAlignment(Qt.AlignCenter)
        status_chip.setMinimumWidth(52)
        status_chip.setMaximumWidth(66)
        status_chip.setMinimumHeight(22)
        status_chip.setMaximumHeight(24)
        status_chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(status_chip)
        value = QLabel("--")
        value.setObjectName("metricValue")
        value.setProperty("compactMetric", True)
        value.setMinimumWidth(0)
        value.setMaximumHeight(20)
        value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        value.setWordWrap(False)
        note = QLabel("--")
        note.setObjectName("subtitle")
        note.setMinimumWidth(0)
        note.setMaximumHeight(16)
        note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        note.setWordWrap(False)
        tile_layout.addLayout(header)
        tile_layout.addWidget(value)
        tile_layout.addWidget(note)
        self.rp_closure_tiles[key] = tile
        self.rp_closure_values[key] = value
        self.rp_closure_notes[key] = note
        self.rp_closure_chips[key] = status_chip
        return tile

    def _build_desktop_rail(self) -> CardFrame:
        rail = CardFrame(muted=True, role="rail")
        rail.setProperty("ecProcessingMissionRail", True)
        rail.setMinimumWidth(280)
        rail.setMaximumWidth(340)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("EC 工作台", "固定显示当前运行闭合状态，不再藏在长页面底部。"))

        self.desktop_rail_scroll = QScrollArea()
        self.desktop_rail_scroll.setObjectName("railScroll")
        self.desktop_rail_scroll.setWidgetResizable(True)
        self.desktop_rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.desktop_rail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        rail_body = QWidget()
        rail_body.setMinimumWidth(0)
        rail_body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.desktop_rail_body = rail_body
        body_layout = QVBoxLayout(rail_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(TOKENS.spacing_md)

        self.desktop_rail_inspector = CardFrame(role="panel")
        self.desktop_rail_inspector.setProperty("deckRole", "ecRailInspector")
        self.desktop_rail_inspector.setProperty("ecRailInspectorCockpit", True)
        self.desktop_rail_inspector.setMinimumWidth(0)
        self.desktop_rail_inspector.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        inspector_layout = QVBoxLayout(self.desktop_rail_inspector)
        inspector_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        inspector_layout.setSpacing(TOKENS.spacing_sm)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(TOKENS.spacing_xs)
        for mode, text in (
            ("summary", "总览"),
            ("workflow", "流程"),
            ("cockpit", "状态"),
            ("closure", "闭合"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_desktop_rail_mode(key))
            self.desktop_rail_mode_buttons[mode] = button
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        inspector_layout.addLayout(mode_row)

        self.method_shortcut_card = self._build_method_shortcut_panel()
        inspector_layout.addWidget(self.method_shortcut_card)
        self.desktop_rail_status_strip = self._build_desktop_rail_status_strip()
        inspector_layout.addWidget(self.desktop_rail_status_strip)

        self.desktop_rail_stack = QStackedWidget()
        self.desktop_rail_stack.setMinimumWidth(0)
        self.desktop_rail_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.workflow_lens_card = self._build_workflow_lens_panel()
        self.cockpit_card = self._build_processing_cockpit()
        self.rail_focus_card = self._build_rail_focus_panel()
        self.desktop_rail_sections = {
            "workflow": self.workflow_lens_card,
            "cockpit": self.cockpit_card,
            "closure": self.rail_focus_card,
        }
        for card in self.desktop_rail_sections.values():
            self.desktop_rail_stack.addWidget(card)
        inspector_layout.addWidget(self.desktop_rail_stack)
        inspector_layout.addStretch(1)
        self._show_desktop_rail_mode("summary")
        body_layout.addWidget(self.desktop_rail_inspector)
        body_layout.addStretch(1)
        self.desktop_rail_scroll.setWidget(rail_body)
        layout.addWidget(self.desktop_rail_scroll, 1)
        return rail

    def _build_desktop_rail_status_strip(self) -> CardFrame:
        card = CardFrame(muted=True, role="rail")
        card.setProperty("deckRole", "ecRailStatusStrip")
        card.setProperty("railMissionDeck", True)
        card.setProperty("ecRailStatusConsole", True)
        card.setMaximumHeight(108)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(TOKENS.spacing_xs)

        header = QLabel("状态针盘")
        header.setObjectName("metricLabel")
        header.setProperty("railMissionHeader", True)
        header.setMaximumHeight(16)
        layout.addWidget(header)

        action_row = QGridLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setHorizontalSpacing(TOKENS.spacing_xs)
        action_row.setVerticalSpacing(2)
        self.desktop_rail_action_button = QToolButton()
        self.desktop_rail_action_button.setText("下一步")
        self.desktop_rail_action_button.setProperty("railAction", True)
        self.desktop_rail_action_button.setProperty("railMissionAction", True)
        self.desktop_rail_action_button.clicked.connect(self._activate_desktop_rail_action)
        self.desktop_rail_risk_button = QToolButton()
        self.desktop_rail_risk_button.setText("风险")
        self.desktop_rail_risk_button.setProperty("railAction", True)
        self.desktop_rail_risk_button.setProperty("railMissionAction", True)
        self.desktop_rail_risk_button.clicked.connect(self._activate_desktop_rail_risk)
        self.desktop_rail_run_button = QToolButton()
        self.desktop_rail_run_button.setText("运行")
        self.desktop_rail_run_button.setProperty("railAction", True)
        self.desktop_rail_run_button.setProperty("railMissionAction", True)
        self.desktop_rail_run_button.clicked.connect(lambda: self._activate_desktop_rail_target(self.desktop_rail_run_button))
        self.desktop_rail_coverage_button = QToolButton()
        self.desktop_rail_coverage_button.setText("覆盖")
        self.desktop_rail_coverage_button.setProperty("railAction", True)
        self.desktop_rail_coverage_button.setProperty("railMissionAction", True)
        self.desktop_rail_coverage_button.clicked.connect(lambda: self._activate_desktop_rail_target(self.desktop_rail_coverage_button))
        for index, button in enumerate((
            self.desktop_rail_action_button,
            self.desktop_rail_risk_button,
            self.desktop_rail_run_button,
            self.desktop_rail_coverage_button,
        )):
            button.setMinimumWidth(52)
            button.setMaximumHeight(24)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            action_row.addWidget(button, 0, index)
        layout.addLayout(action_row)

        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(TOKENS.spacing_xs)
        status_grid.setVerticalSpacing(0)
        self.desktop_rail_status_tiles: dict[str, CardFrame] = {}
        self.desktop_rail_status_values: dict[str, QLabel] = {}
        self.desktop_rail_status_notes: dict[str, QLabel] = {}
        for column, (key, title) in enumerate((
            ("step", "当前步骤"),
            ("run", "运行状态"),
            ("closure", "闭合度"),
        )):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("railMissionTile", True)
            tile.setMaximumHeight(42)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, 1, TOKENS.spacing_sm, 1)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel("--")
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setMinimumWidth(0)
            value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            note_label = QLabel("--")
            note_label.setVisible(False)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            self.desktop_rail_status_tiles[key] = tile
            self.desktop_rail_status_values[key] = value_label
            self.desktop_rail_status_notes[key] = note_label
            status_grid.addWidget(tile, 0, column)
            status_grid.setColumnStretch(column, 1)
        layout.addLayout(status_grid)
        return card

    def _build_method_shortcut_panel(self) -> CardFrame:
        card = CardFrame(muted=True, role="console")
        card.setProperty("deckRole", "ecMethodShortcutDeck")
        card.setProperty("ecMethodShortcutDeck", True)
        card.setProperty("methodShortcutCommandDeck", True)
        card.setMaximumHeight(90)
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        layout.setSpacing(TOKENS.spacing_xs)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("方法族捷径")
        title.setObjectName("metricLabel")
        self.method_shortcut_chip = chip("首屏", "accent")
        self.method_shortcut_chip.setMaximumHeight(20)
        header.addWidget(title)
        self.method_shortcut_value = QLabel("--")
        self.method_shortcut_value.setObjectName("metricValue")
        self.method_shortcut_value.setProperty("compactMetric", True)
        self.method_shortcut_value.setProperty("methodShortcutValue", True)
        self.method_shortcut_value.setWordWrap(False)
        self.method_shortcut_value.setMaximumHeight(20)
        self.method_shortcut_value.setMinimumWidth(0)
        self.method_shortcut_value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        header.addWidget(self.method_shortcut_value, 1)
        header.addStretch(1)
        header.addWidget(self.method_shortcut_chip)
        layout.addLayout(header)

        row = QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(TOKENS.spacing_xs)
        row.setVerticalSpacing(TOKENS.spacing_xs)
        for column, (family, text) in enumerate(
            (
                ("footprint", "足迹"),
                ("uncertainty", "随机误差"),
                ("spectral", "谱修正"),
            )
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.setProperty("methodShortcut", True)
            button.setProperty("activeMethodShortcut", family == "footprint")
            button.setProperty("methodTone", "accent")
            button.setMinimumWidth(66)
            button.setMaximumHeight(26)
            button.clicked.connect(lambda _checked=False, key=family: self._activate_method_shortcut(key))
            self.method_shortcut_buttons[family] = button
            self.method_shortcut_labels[family] = text
            row.addWidget(button, 0, column)
        layout.addLayout(row)
        self.method_shortcut_pill_strip = QWidget()
        self.method_shortcut_pill_strip.setProperty("methodShortcutPillStrip", True)
        self.method_shortcut_pill_strip.setMaximumHeight(18)
        pill_layout = QHBoxLayout(self.method_shortcut_pill_strip)
        pill_layout.setContentsMargins(0, 0, 0, 0)
        pill_layout.setSpacing(TOKENS.spacing_xs)
        self.method_shortcut_pills = {}
        for family, label_text in (
            ("footprint", "足"),
            ("uncertainty", "误"),
            ("spectral", "谱"),
        ):
            pill = QLabel(f"{label_text} --")
            pill.setObjectName("subtitle")
            pill.setProperty("methodShortcutPill", True)
            pill.setProperty("methodFamily", family)
            pill.setProperty("methodTone", "accent")
            pill.setProperty("activeMethodShortcut", family == "footprint")
            pill.setWordWrap(False)
            pill.setMinimumWidth(0)
            pill.setMaximumHeight(18)
            pill.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.method_shortcut_pills[family] = pill
            pill_layout.addWidget(pill, 1)
        layout.addWidget(self.method_shortcut_pill_strip)
        self.method_shortcut_note = QLabel("--", card)
        self.method_shortcut_note.setObjectName("subtitle")
        self.method_shortcut_note.setProperty("methodShortcutNote", True)
        self.method_shortcut_note.setWordWrap(False)
        self.method_shortcut_note.setMaximumHeight(16)
        self.method_shortcut_note.setVisible(False)
        return card

    def _build_workflow_lens_panel(self) -> CardFrame:
        card = CardFrame(role="panel")
        card.setProperty("deckRole", "workflowLensCompact")
        card.setProperty("processingWorkflowLensDeck", True)
        card.setMinimumWidth(0)
        card.setMaximumHeight(170)
        card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        title = section_title("工作流分层", "项目、核心、高级和交付四段导航。")
        title.setMinimumWidth(0)
        title.setMaximumWidth(300)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(title)

        lens_grid = QGridLayout()
        lens_grid.setContentsMargins(0, 0, 0, 0)
        lens_grid.setHorizontalSpacing(TOKENS.spacing_xs)
        lens_grid.setVerticalSpacing(TOKENS.spacing_xs)
        compact_titles = {
            "project": "项目",
            "core": "核心",
            "advanced": "高级",
            "delivery": "交付",
        }
        for index, (lens_key, title, subtitle, steps) in enumerate(WORKFLOW_LENSES):
            button = QPushButton(compact_titles.get(lens_key, title))
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.setMaximumHeight(42)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            step_hint = " / ".join(dict((key, label) for key, label, _sub in EC_STEPS).get(step, step) for step in steps)
            button.setToolTip(f"{title}: {step_hint}")
            button.clicked.connect(lambda _checked=False, key=lens_key: self._select_workflow_lens(key))
            note = QLabel(subtitle)
            note.setObjectName("subtitle")
            note.setWordWrap(True)
            note.setVisible(False)
            self.workflow_lens_buttons[lens_key] = button
            self.workflow_lens_notes[lens_key] = note
            lens_grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(lens_grid)
        self.workflow_lens_active_note = QLabel("--")
        self.workflow_lens_active_note.setObjectName("subtitle")
        self.workflow_lens_active_note.setWordWrap(True)
        self.workflow_lens_active_note.setMaximumHeight(32)
        layout.addWidget(self.workflow_lens_active_note)
        return card

    def _build_rail_focus_panel(self) -> CardFrame:
        card = CardFrame(role="panel")
        card.setProperty("processingClosureFocusDeck", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title("闭合聚合", "把运行闭合度和输出覆盖压缩成同一张右侧工作台卡片。"))

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(TOKENS.spacing_xs)
        self.rail_focus_buttons: dict[str, QToolButton] = {}
        for key, text in (
            ("readiness", "闭合度"),
            ("coverage", "覆盖矩阵"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, focus=key: self._show_rail_focus(focus))
            self.rail_focus_buttons[key] = button
            switch_row.addWidget(button)
        switch_row.addStretch(1)
        layout.addLayout(switch_row)

        self.rail_focus_stack = QStackedWidget()
        self.readiness_card = self._build_readiness_panel()
        self.output_coverage_card = self._build_output_coverage_panel()
        self.rail_focus_sections = {
            "readiness": self.readiness_card,
            "coverage": self.output_coverage_card,
        }
        self.rail_focus_stack.addWidget(self.readiness_card)
        self.rail_focus_stack.addWidget(self.output_coverage_card)
        layout.addWidget(self.rail_focus_stack)
        self._show_rail_focus("readiness")
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
        card.setProperty("deckRole", "processingCockpitDeck")
        card.setProperty("processingCockpitWorkbench", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        header = QHBoxLayout()
        header.setSpacing(TOKENS.spacing_sm)
        header_text = QVBoxLayout()
        header_text.setSpacing(0)
        title = QLabel("处理 Cockpit")
        title.setObjectName("metricValue")
        title.setProperty("compactMetric", True)
        subtitle = QLabel("当前 RP 运行、方法和交付状态。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        self.cockpit_status_chip = chip("等待运行", "warning")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_text.addWidget(self.cockpit_status_chip, 0, Qt.AlignLeft)
        header.addLayout(header_text, 1)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.cockpit_method_value, self.cockpit_method_note = self._build_cockpit_tile(grid, 0, 0, "方法栈")
        self.cockpit_result_value, self.cockpit_result_note = self._build_cockpit_tile(grid, 1, 0, "主通量")
        self.cockpit_uncertainty_value, self.cockpit_uncertainty_note = self._build_cockpit_tile(grid, 2, 0, "不确定度")
        self.cockpit_benchmark_value, self.cockpit_benchmark_note = self._build_cockpit_tile(grid, 3, 0, "Benchmark")
        self.cockpit_delivery_value, self.cockpit_delivery_note = self._build_cockpit_tile(grid, 4, 0, "交付出口")
        grid.setColumnStretch(0, 1)
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
        value_label.setProperty("compactMetric", True)
        value_label.setWordWrap(True)
        note_label = QLabel("--")
        note_label.setObjectName("subtitle")
        note_label.setWordWrap(True)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(value_label)
        tile_layout.addWidget(note_label)
        layout.addWidget(tile, row, column, 1, column_span)
        return value_label, note_label

    def _build_method_console_tile(self, layout: QGridLayout, column: int, key: str, title: str) -> None:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("methodTile", True)
        tile.setProperty("methodConsoleTile", True)
        tile.setProperty("methodConsoleWorkbenchTile", True)
        tile.setProperty("methodKey", key)
        tile.setProperty("evidenceTone", "warning")
        tile.setProperty("methodTone", "warning")
        tile.setMaximumHeight(42)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        tile_layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel("--")
        value_label.setObjectName("metricValue")
        value_label.setProperty("compactMetric", True)
        value_label.setWordWrap(False)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        note_label = QLabel("--")
        note_label.setObjectName("subtitle")
        note_label.setWordWrap(False)
        note_label.setMinimumWidth(0)
        note_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(value_label)
        tile_layout.addWidget(note_label)
        layout.addWidget(tile, 0, column)
        self.method_console_tiles[key] = tile
        self.method_console_values[key] = value_label
        self.method_console_notes[key] = note_label

    def _add_method_family_control_strip(self, layout: QVBoxLayout, family: str, recommended: str) -> None:
        strip = QWidget()
        strip.setProperty("methodFamilyControlStrip", True)
        strip.setProperty("methodFamily", family)
        strip.setMaximumHeight(52)
        strip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        strip_layout = QGridLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        strip_layout.setVerticalSpacing(0)
        self.method_family_control_strips[family] = strip
        self.method_family_control_tiles[family] = {}
        self.method_family_control_values[family] = {}
        self.method_family_control_notes[family] = {}
        for column, (key, title, value) in enumerate(
            (
                ("recommended", "recommended", recommended),
                ("current", "current", "--"),
                ("gate", "gate", "review"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("methodFamilyControlTile", True)
            tile.setProperty("methodFamily", family)
            tile.setProperty("summaryKey", key)
            tile.setProperty("methodTone", "accent" if key == "recommended" else "warning")
            tile.setMaximumHeight(48)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            title_label.setWordWrap(False)
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(False)
            value_label.setMinimumWidth(0)
            value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            note_label = QLabel("--")
            note_label.setObjectName("subtitle")
            note_label.setWordWrap(False)
            note_label.setMinimumWidth(0)
            note_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            tile_layout.addWidget(note_label)
            strip_layout.addWidget(tile, 0, column)
            strip_layout.setColumnStretch(column, 1)
            self.method_family_control_tiles[family][key] = tile
            self.method_family_control_values[family][key] = value_label
            self.method_family_control_notes[family][key] = note_label
        layout.addWidget(strip)

    def _set_method_family_control_tile(
        self,
        family: str,
        key: str,
        value: str,
        note: str,
        tone: str,
    ) -> None:
        value_label = self.method_family_control_values.get(family, {}).get(key)
        note_label = self.method_family_control_notes.get(family, {}).get(key)
        tile = self.method_family_control_tiles.get(family, {}).get(key)
        display_value = self._compact_text(value, 18)
        display_note = self._compact_text(note, 28)
        tooltip = f"{family}.{key}: {value}\n{note}"
        if value_label is not None:
            value_label.setText(display_value)
            value_label.setToolTip(tooltip)
        if note_label is not None:
            note_label.setText(display_note)
            note_label.setToolTip(tooltip)
        if tile is not None:
            tile.setToolTip(tooltip)
            tile.setProperty("methodTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _add_method_group_strip(self, layout: QVBoxLayout, family: str, groups: tuple[str, ...]) -> None:
        strip = QWidget()
        strip.setProperty("methodGroupStrip", True)
        strip.setMaximumHeight(0)
        strip.setVisible(False)
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(TOKENS.spacing_xs)
        if not hasattr(self, "method_group_pills"):
            self.method_group_pills: dict[str, list[QLabel]] = {}
        self.method_group_pills[family] = []
        for text in groups:
            label = QLabel(text)
            label.setProperty("methodGroupPill", True)
            label.setMaximumHeight(18)
            label.setToolTip(text)
            self.method_group_pills[family].append(label)
            strip_layout.addWidget(label)
        strip_layout.addStretch(1)
        layout.addWidget(strip)

    def _select_workflow_lens(self, lens_key: str) -> None:
        self._show_desktop_rail_mode("workflow")
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
        self._refresh_desktop_rail_status_strip()

    def _refresh_workflow_lens(self) -> None:
        if not self.workflow_lens_buttons:
            return
        active_step = self.controller.ec_nav_step
        active_lens = ""
        active_note = ""
        for lens_key, _title, _subtitle, steps in WORKFLOW_LENSES:
            if active_step in steps:
                active_lens = lens_key
                active_note = _subtitle
                break
        for lens_key, button in self.workflow_lens_buttons.items():
            button.blockSignals(True)
            button.setChecked(lens_key == active_lens)
            button.blockSignals(False)
            button.setProperty("variant", "primary" if lens_key == active_lens else "")
            button.style().unpolish(button)
            button.style().polish(button)
        if hasattr(self, "workflow_lens_active_note"):
            self.workflow_lens_active_note.setText(active_note or "选择左侧步骤后显示对应工作流分层。")

    def _show_desktop_rail_mode(self, mode: str) -> None:
        if not hasattr(self, "desktop_rail_sections"):
            return
        summary_mode = mode == "summary"
        card = self.desktop_rail_sections.get(mode)
        if not summary_mode and card is None:
            return
        if summary_mode:
            default_card = self.desktop_rail_sections.get("workflow")
            if default_card is not None:
                self.desktop_rail_stack.setCurrentWidget(default_card)
        else:
            self.desktop_rail_stack.setCurrentWidget(card)
        if hasattr(self, "desktop_rail_status_strip"):
            self.desktop_rail_status_strip.setVisible(not summary_mode)
        self.desktop_rail_stack.setVisible(not summary_mode)
        mode_heights = {
            "summary": 0,
            "workflow": 210,
            "cockpit": 420,
            "closure": 470,
        }
        self.desktop_rail_stack.setMaximumHeight(mode_heights.get(mode, 420))
        for key, button in self.desktop_rail_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_rail_focus(self, focus: str) -> None:
        if not hasattr(self, "rail_focus_sections"):
            return
        card = self.rail_focus_sections.get(focus)
        if card is None:
            return
        self.rail_focus_stack.setCurrentWidget(card)
        self._show_desktop_rail_mode("closure")
        for key, button in self.rail_focus_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == focus)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_rp_closure_mode(self, mode: str) -> None:
        if mode not in {"compact", "detail"}:
            mode = "compact"
        if not hasattr(self, "rp_closure_stack"):
            return
        index = 1 if mode == "detail" else 0
        self.rp_closure_stack.setCurrentIndex(index)
        self.rp_closure_deck.setMaximumHeight(146 if mode == "detail" else 92)
        self.rp_closure_deck.setProperty("closureMode", mode)
        for key, button in self.rp_closure_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)
        self.rp_closure_deck.style().unpolish(self.rp_closure_deck)
        self.rp_closure_deck.style().polish(self.rp_closure_deck)

    def _activate_method_shortcut(self, family: str) -> None:
        item = self.step_items.get("uncertainty")
        if item is not None:
            self.step_tree.setCurrentItem(item)
        else:
            self.controller.set_ec_nav_step("uncertainty")
            self._sync_step_from_controller()
        self._show_method_family(family)
        self._show_desktop_rail_mode("cockpit")

    def _refresh_method_shortcut_panel(
        self,
        *,
        active_family: str,
        footprint_method: str,
        uncertainty_method: str,
        spectral_method: str,
        family_tones: dict[str, str] | None = None,
        issue_count: int,
    ) -> None:
        if not hasattr(self, "method_shortcut_buttons"):
            return
        methods = {
            "footprint": footprint_method,
            "uncertainty": uncertainty_method,
            "spectral": spectral_method,
        }
        family_tones = family_tones or {}
        for family, button in self.method_shortcut_buttons.items():
            method = methods.get(family, "--")
            button.setToolTip(f"{family}: {method}")
            button.setProperty("activeMethodShortcut", family == active_family)
            button.setProperty("methodTone", family_tones.get(family, "accent"))
            button.blockSignals(True)
            button.setChecked(family == active_family)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)
        self._set_method_shortcut_pills(methods, active_family, family_tones)
        tone = "warning" if issue_count else "success"
        if hasattr(self, "method_shortcut_chip"):
            self.method_shortcut_chip.setText("复核" if issue_count else "就绪")
            self.method_shortcut_chip.setProperty("chipTone", tone)
            self.method_shortcut_chip.style().unpolish(self.method_shortcut_chip)
            self.method_shortcut_chip.style().polish(self.method_shortcut_chip)
        if hasattr(self, "method_shortcut_value"):
            active_method = methods.get(active_family, "--")
            active_label = self.method_shortcut_labels.get(active_family, active_family)
            value = f"{active_label} · {active_method}"
            self.method_shortcut_value.setText(self._compact_text(value, 22))
            self.method_shortcut_value.setToolTip(value)
        if hasattr(self, "method_shortcut_note"):
            note = f"{footprint_method} / {uncertainty_method} / {spectral_method} · issues={issue_count}"
            self.method_shortcut_note.setText(note)
            self.method_shortcut_note.setToolTip(note)

    def _activate_desktop_rail_action(self) -> None:
        self._activate_desktop_rail_target(getattr(self, "desktop_rail_action_button", None))

    def _activate_desktop_rail_risk(self) -> None:
        self._activate_desktop_rail_target(getattr(self, "desktop_rail_risk_button", None))

    def _activate_desktop_rail_target(self, button: QToolButton | None) -> None:
        if button is None:
            return
        target = str(button.property("targetStep") or "")
        if target == "coverage":
            self._show_rail_focus("coverage")
            return
        if target == "run_processing":
            self._run_processing(precheck_only=False)
            return
        item = self.step_items.get(target)
        if item is not None:
            self.step_tree.setCurrentItem(item)
            self._show_desktop_rail_mode("workflow")

    def _show_method_family(self, family: str) -> None:
        if not hasattr(self, "method_family_sections"):
            return
        card = self.method_family_sections.get(family)
        if card is None:
            return
        self.method_family_stack.setCurrentWidget(card)
        self._show_method_console_mode("family")
        for key, button in self.method_family_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == family)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)
        for key, button in getattr(self, "method_shortcut_buttons", {}).items():
            button.blockSignals(True)
            button.setChecked(key == family)
            button.setProperty("activeMethodShortcut", key == family)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)
        self._update_method_shortcut_active_value(family)

    def _update_method_shortcut_active_value(self, family: str) -> None:
        value_label = getattr(self, "method_shortcut_value", None)
        if value_label is None:
            return
        methods = {
            "footprint": self._current_combo_text("footprint_method_combo", "kljun"),
            "uncertainty": self._current_combo_text("uncertainty_mode_combo", "mann_lenschow"),
            "spectral": self._current_combo_text("spectral_method_combo", "massman"),
        }
        if family == "footprint" and self._current_combo_text("footprint_enable_combo", "enabled") != "enabled":
            methods["footprint"] = "disabled"
        if family == "spectral" and self._current_combo_text("spectral_enable_combo", "enabled") != "enabled":
            methods["spectral"] = "disabled"
        active_label = self.method_shortcut_labels.get(family, family)
        value = f"{active_label} · {methods.get(family, '--')}"
        value_label.setText(self._compact_text(value, 22))
        value_label.setToolTip(value)
        self._set_method_shortcut_pills(methods, family)

    def _set_method_shortcut_pills(
        self,
        methods: dict[str, str],
        active_family: str,
        family_tones: dict[str, str] | None = None,
    ) -> None:
        family_tones = family_tones or {}
        family_labels = {
            "footprint": "足",
            "uncertainty": "误",
            "spectral": "谱",
        }
        full_family_labels = {
            "footprint": "足迹",
            "uncertainty": "随机误差",
            "spectral": "谱修正",
        }
        for family, pill in getattr(self, "method_shortcut_pills", {}).items():
            method = methods.get(family, "--")
            pill.setText(f"{family_labels.get(family, family)} {self._method_badge_text(method)}")
            pill.setToolTip(f"{full_family_labels.get(family, family)}方法: {method}")
            pill.setProperty("methodTone", family_tones.get(family, "accent"))
            pill.setProperty("activeMethodShortcut", family == active_family)
            pill.style().unpolish(pill)
            pill.style().polish(pill)

    def _method_badge_text(self, method: object) -> str:
        text = str(method or "--").strip()
        key = text.lower()
        labels = {
            "kljun": "Kljun",
            "kormann_meixner": "K-M",
            "hsieh": "Hsieh",
            "mann_lenschow": "M&L",
            "finkelstein_sims": "F&S",
            "massman": "Mass",
            "horst": "Horst",
            "ibrom": "Ibrom",
            "fratini": "Fratini",
            "disabled": "off",
        }
        return labels.get(key, text.replace("_", " "))

    def _show_method_console_mode(self, mode: str) -> None:
        if mode not in {"family", "primary", "compare"}:
            mode = "family"
        support_visible = mode in {"primary", "compare"}
        for widget_name in (
            "method_family_switch_bar",
            "method_family_tile_strip",
            "method_family_stack",
            "method_snapshot_label",
            "method_validation_label",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setVisible(not support_visible)
        support_card = getattr(self, "method_support_card", None)
        if support_card is not None:
            support_card.setVisible(support_visible)
        if support_visible:
            self._show_method_support(mode, switch_console=False)
        for key, button in self.method_console_mode_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_method_support(self, support: str, *, switch_console: bool = True) -> None:
        if not hasattr(self, "method_support_sections"):
            return
        card = self.method_support_sections.get(support)
        if card is None:
            return
        if switch_console:
            self._show_method_console_mode(support)
            return
        self.method_support_stack.setCurrentWidget(card)
        for key, button in self.method_support_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == support)
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

    def _set_method_console_tile(self, key: str, value: str, note: str, tone: str) -> None:
        if not hasattr(self, "method_console_values"):
            return
        value_label = self.method_console_values.get(key)
        note_label = self.method_console_notes.get(key)
        tile = self.method_console_tiles.get(key)
        display_value = self._compact_text(value, 18)
        display_note = self._compact_text(note, 34)
        tooltip = f"{value}\n{note}"
        if value_label is not None:
            value_label.setText(display_value)
            value_label.setToolTip(tooltip)
        if note_label is not None:
            note_label.setText(display_note)
            note_label.setToolTip(tooltip)
        if tile is not None:
            tile.setToolTip(tooltip)
            tile.setProperty("evidenceTone", tone)
            tile.setProperty("methodTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _compact_method_form(self, fields: list[tuple[str, QWidget]]) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(TOKENS.spacing_sm)
        grid.setVerticalSpacing(TOKENS.spacing_xs)
        for index, (label_text, widget) in enumerate(fields):
            row = index // 2
            column = (index % 2) * 2
            label = QLabel(label_text)
            label.setObjectName("metricLabel")
            label.setProperty("methodFieldLabel", True)
            label.setToolTip(label_text)
            label.setMinimumWidth(112)
            label.setMaximumWidth(148)
            label.setMaximumHeight(20)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            if not hasattr(self, "method_field_labels"):
                self.method_field_labels: list[QLabel] = []
            self.method_field_labels.append(label)
            widget.setProperty("methodFieldInput", True)
            widget.setMinimumWidth(96)
            widget.setMaximumHeight(28)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if not hasattr(self, "method_field_inputs"):
                self.method_field_inputs: list[QWidget] = []
            self.method_field_inputs.append(widget)
            grid.addWidget(label, row, column)
            grid.addWidget(widget, row, column + 1)
        grid.setColumnMinimumWidth(0, 112)
        grid.setColumnMinimumWidth(1, 0)
        grid.setColumnMinimumWidth(2, 112)
        grid.setColumnMinimumWidth(3, 0)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
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
        footprint_issues: list[str] = []
        uncertainty_issues: list[str] = []
        spectral_issues: list[str] = []

        def add_issue(message: str, family: str) -> None:
            issues.append(message)
            if family == "footprint":
                footprint_issues.append(message)
            elif family == "uncertainty":
                uncertainty_issues.append(message)
            elif family == "spectral":
                spectral_issues.append(message)

        z_m = self.footprint_zm_spin.value()
        canopy = self.footprint_canopy_spin.value()
        z0 = self.footprint_z0_spin.value()
        if footprint_enabled == "enabled":
            if z_m <= canopy:
                add_issue("z_m > canopy_height_m should be reviewed for above-canopy footprint runs.", "footprint")
            if z0 >= z_m:
                add_issue("z0 must stay below z_m for footprint scaling.", "footprint")
            if self.footprint_grid_combo.currentText().strip() == "enabled" and (
                self.footprint_grid_x_spin.value() < 16 or self.footprint_grid_y_spin.value() < 15
            ):
                add_issue("2D footprint grid is very coarse; use at least 16x15 for delivery review.", "footprint")

        confidence = self.uncertainty_confidence_spin.value()
        if confidence < 0.80:
            add_issue("confidence_level below 0.80 is allowed but should be justified in the run notes.", "uncertainty")

        if spectral_enabled == "enabled":
            if self.spectral_response_spin.value() > 2.0:
                add_issue("response_time_s is high; spectral attenuation may dominate the correction.", "spectral")
            if spectral_method == "fratini" and cospectrum != "fcc_auto":
                add_issue("Fratini should use fcc_auto measured_cospectrum when FCC output is available.", "spectral")

        if compare == "enabled" and self.method_compare_threshold_spin.value() > 1.0:
            add_issue("method_compare deviation_threshold above 1.0 weakens parity review.", "spectral")

        snapshot = (
            f"footprint={footprint_method}({footprint_enabled}, z_m={z_m:.2f}, canopy={canopy:.2f}) | "
            f"uncertainty={uncertainty_method}(confidence={confidence:.2f}) | "
            f"spectral={spectral_method}({spectral_enabled}, cospectrum={cospectrum}) | "
            f"compare={compare}(threshold={self.method_compare_threshold_spin.value():.2f})"
        )
        self.method_snapshot_label.setText(snapshot)
        self.method_snapshot_label.setToolTip(snapshot)

        footprint_hard_issue = any("z_m" in item or "z0" in item for item in footprint_issues)
        if footprint_enabled != "enabled":
            footprint_tone = "accent"
        elif footprint_hard_issue:
            footprint_tone = "danger"
        elif footprint_issues:
            footprint_tone = "warning"
        else:
            footprint_tone = "success"
        uncertainty_tone = "warning" if uncertainty_issues else "success"
        if spectral_enabled != "enabled":
            spectral_tone = "accent"
        elif spectral_issues:
            spectral_tone = "warning"
        else:
            spectral_tone = "success"
        footprint_gate = "disabled" if footprint_enabled != "enabled" else ("review" if footprint_tone in {"warning", "danger"} else "ready")
        uncertainty_gate = "review" if uncertainty_tone == "warning" else "ready"
        spectral_gate = "disabled" if spectral_enabled != "enabled" else ("review" if spectral_tone == "warning" else "ready")
        self._set_method_family_control_tile(
            "footprint",
            "recommended",
            "kljun / z_m=6.0",
            "default canopy_height_m=3.0; use dynamic canopy metadata when present",
            "accent",
        )
        self._set_method_family_control_tile(
            "footprint",
            "current",
            footprint_method if footprint_enabled == "enabled" else "disabled",
            f"z_m={z_m:.2f}; canopy={canopy:.2f}; z0={z0:.3f}; grid={self.footprint_grid_x_spin.value()}x{self.footprint_grid_y_spin.value()}",
            footprint_tone,
        )
        self._set_method_family_control_tile(
            "footprint",
            "gate",
            footprint_gate,
            "range check: z_m > canopy_height_m, z0 < z_m, grid >= 16x15",
            footprint_tone,
        )
        self._set_method_family_control_tile(
            "uncertainty",
            "recommended",
            "mann_lenschow / 0.95",
            "default integral_timescale_s=5.0 with 95% confidence band",
            "accent",
        )
        self._set_method_family_control_tile(
            "uncertainty",
            "current",
            uncertainty_method,
            f"tau={self.uncertainty_timescale_spin.value():.1f}s; confidence={confidence:.2f}",
            uncertainty_tone,
        )
        self._set_method_family_control_tile(
            "uncertainty",
            "gate",
            uncertainty_gate,
            "range check: confidence_level >= 0.80 recommended for delivery review",
            uncertainty_tone,
        )
        self._set_method_family_control_tile(
            "spectral",
            "recommended",
            "massman / fcc_auto",
            "Fratini should auto-inject FCC measured_cospectrum when available",
            "accent",
        )
        self._set_method_family_control_tile(
            "spectral",
            "current",
            spectral_method if spectral_enabled == "enabled" else "disabled",
            f"response={self.spectral_response_spin.value():.3f}s; path={self.spectral_path_spin.value():.3f}m; cospectrum={cospectrum}",
            spectral_tone,
        )
        self._set_method_family_control_tile(
            "spectral",
            "gate",
            spectral_gate,
            "range check: response_time_s and Fratini measured_cospectrum path",
            spectral_tone,
        )
        self._set_method_console_tile(
            "footprint",
            footprint_method if footprint_enabled == "enabled" else "disabled",
            f"z_m={z_m:.2f} / canopy={canopy:.2f} / grid={self.footprint_grid_x_spin.value()}x{self.footprint_grid_y_spin.value()}",
            footprint_tone,
        )
        self._set_method_console_tile(
            "uncertainty",
            uncertainty_method,
            f"confidence={confidence:.2f} / tau={self.uncertainty_timescale_spin.value():.1f}s",
            uncertainty_tone,
        )
        self._set_method_console_tile(
            "spectral",
            spectral_method if spectral_enabled == "enabled" else "disabled",
            f"cospectrum={cospectrum} / response={self.spectral_response_spin.value():.3f}s",
            spectral_tone,
        )
        active_family = "footprint"
        for family, card in getattr(self, "method_family_sections", {}).items():
            if getattr(self, "method_family_stack", None) is not None and self.method_family_stack.currentWidget() is card:
                active_family = family
                break
        self._refresh_method_shortcut_panel(
            active_family=active_family,
            footprint_method=footprint_method if footprint_enabled == "enabled" else "disabled",
            uncertainty_method=uncertainty_method,
            spectral_method=spectral_method if spectral_enabled == "enabled" else "disabled",
            family_tones={
                "footprint": footprint_tone,
                "uncertainty": uncertainty_tone,
                "spectral": spectral_tone,
            },
            issue_count=len(issues),
        )

        if issues:
            self._set_method_gate_chip("复核", "warning")
            validation_text = " | ".join(issues[:4])
            self.method_validation_label.setText(validation_text)
            self.method_validation_label.setToolTip(" | ".join(issues))
        else:
            self._set_method_gate_chip("就绪", "success")
            validation_text = "Ranges ok; UI snapshot keys match pipeline config names."
            self.method_validation_label.setText(validation_text)
            self.method_validation_label.setToolTip(validation_text)

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
        self._refresh_desktop_rail_status_strip()

    def _set_coverage_gate_chip(self, text: str, tone: str) -> None:
        self.coverage_gate_chip.setText(text)
        self.coverage_gate_chip.setProperty("chipTone", tone)
        self.coverage_gate_chip.style().unpolish(self.coverage_gate_chip)
        self.coverage_gate_chip.style().polish(self.coverage_gate_chip)

    def _refresh_desktop_rail_status_strip(self) -> None:
        if not hasattr(self, "desktop_rail_status_values"):
            return
        summary = dict(self.controller.ec_processing_workspace.get("summary", {}) or {})
        statuses = self._step_tree_status_model()
        step_titles = dict((key, title) for key, title, _subtitle in EC_STEPS)
        step_title = dict((key, title) for key, title, _subtitle in EC_STEPS).get(
            self.controller.ec_nav_step,
            "当前步骤",
        )
        current = self._current_window()
        status = str(summary.get("status", "empty") or "empty")
        status_tone = "success" if status == "ok" else ("warning" if status == "empty" else "accent")
        run_value = "已运行" if current is not None else self._ui_status_label(status)
        run_note = (
            f"windows={summary.get('valid_window_count', 0)}/{summary.get('window_count', 0)}"
            if current is not None
            else str(summary.get("message", "运行处理后生成窗口结果。"))
        )
        closure_value = self.coverage_gate_chip.text() if hasattr(self, "coverage_gate_chip") else "--"
        closure_note = self.coverage_next_value.text() if hasattr(self, "coverage_next_value") else "--"
        closure_tone = (
            str(self.coverage_gate_chip.property("chipTone") or "warning")
            if hasattr(self, "coverage_gate_chip")
            else "warning"
        )
        risk_steps = [(key, data) for key, data in statuses.items() if data[1] == "danger"]
        if risk_steps:
            risk_key, (_risk_label, _risk_tone, risk_note) = risk_steps[0]
            action_value = "处理复核"
            action_note = f"{step_titles.get(risk_key, risk_key)}: {risk_note}"
            action_tone = "danger"
            action_target = risk_key
            risk_value = f"复核 {len(risk_steps)}"
            risk_target = risk_key
            risk_tone = "danger"
            risk_display_note = action_note
        elif current is None:
            action_value = "运行入口"
            action_note = "确认窗口、方法和输出后运行处理。"
            action_tone = "warning"
            action_target = self.controller.ec_nav_step or "window_sampling"
            risk_value = "无风险"
            risk_target = "output"
            risk_tone = "success"
            risk_display_note = "当前没有阻断型复核项。"
        elif closure_tone == "success":
            action_value = "交付出口"
            action_note = "进入输出页复核 manifest、network export 和报告中心。"
            action_tone = "success"
            action_target = "output"
            risk_value = "无风险"
            risk_target = "output"
            risk_tone = "success"
            risk_display_note = "运行闭合项未发现阻断风险。"
        else:
            action_value = "查看闭合"
            action_note = closure_note
            action_tone = closure_tone
            action_target = "coverage"
            risk_value = "待复核"
            risk_target = "coverage"
            risk_tone = closure_tone
            risk_display_note = closure_note

        action_value = "下一步"
        risk_value = "就绪" if risk_tone == "success" else "风险"
        self._set_desktop_rail_status_tile("step", step_title, self.controller.ec_nav_step, "accent")
        self._set_desktop_rail_status_tile("run", run_value, run_note, status_tone)
        self._set_desktop_rail_status_tile("closure", closure_value, closure_note, closure_tone)
        self._configure_desktop_rail_action_button(self.desktop_rail_action_button, action_value, action_note, action_target, action_tone)
        self._configure_desktop_rail_action_button(self.desktop_rail_risk_button, risk_value, risk_display_note, risk_target, risk_tone)
        run_tone = "success" if current is not None else ("warning" if risk_steps else "accent")
        self._configure_desktop_rail_action_button(
            self.desktop_rail_run_button,
            "运行",
            "保存当前配置并正式运行 RP 处理。",
            "run_processing",
            run_tone,
        )
        self._configure_desktop_rail_action_button(
            self.desktop_rail_coverage_button,
            "覆盖",
            closure_note,
            "coverage",
            closure_tone,
        )
        self._refresh_step_command_strips(
            step_titles=step_titles,
            run_value=run_value,
            run_note=run_note,
            run_tone=status_tone,
            closure_value=closure_value,
            closure_note=closure_note,
            closure_tone=closure_tone,
            run_button_tone=run_tone,
        )

    def _set_desktop_rail_status_tile(self, key: str, value: str, note: str, tone: str) -> None:
        value_label = self.desktop_rail_status_values[key]
        note_label = self.desktop_rail_status_notes[key]
        tile = self.desktop_rail_status_tiles[key]
        display_value = self._compact_text(value, 16)
        display_note = self._compact_text(note, 42)
        value_label.setText(display_value)
        note_label.setText(display_note)
        tooltip = f"{value}\n{note}"
        value_label.setToolTip(tooltip)
        tile.setToolTip(tooltip)
        tile.setProperty("evidenceTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def _refresh_step_command_strips(
        self,
        *,
        step_titles: dict[str, str],
        run_value: str,
        run_note: str,
        run_tone: str,
        closure_value: str,
        closure_note: str,
        closure_tone: str,
        run_button_tone: str,
    ) -> None:
        if not self.step_command_strips:
            return
        statuses = self._step_tree_status_model()
        active_key = self.controller.ec_nav_step
        for step_key, strip in self.step_command_strips.items():
            step_title = step_titles.get(step_key, step_key)
            status_label, step_tone, step_note = statuses.get(step_key, ("--", "warning", "--"))
            self._set_step_command_tile(step_key, "step", step_title, status_label, step_note, step_tone)
            self._set_step_command_tile(step_key, "run", run_value, "RP 状态", run_note, run_tone)
            self._set_step_command_tile(step_key, "closure", closure_value, "交付门", closure_note, closure_tone)
            strip_tone = "accent" if step_key == active_key else step_tone
            strip.setProperty("evidenceTone", strip_tone)
            strip.style().unpolish(strip)
            strip.style().polish(strip)
            buttons = self.step_command_buttons.get(step_key, {})
            run_button = buttons.get("run")
            if run_button is not None:
                self._configure_desktop_rail_action_button(
                    run_button,
                    "运行",
                    "保存当前配置并正式运行 RP 处理。",
                    "run_processing",
                    run_button_tone,
                )
            coverage_button = buttons.get("coverage")
            if coverage_button is not None:
                self._configure_desktop_rail_action_button(
                    coverage_button,
                    "覆盖",
                    closure_note,
                    "coverage",
                    closure_tone,
                )

    def _set_step_command_tile(self, step_key: str, metric_key: str, value: str, note: str, tooltip: str, tone: str) -> None:
        values = self.step_command_values.get(step_key, {})
        notes = self.step_command_notes.get(step_key, {})
        tiles = self.step_command_tiles.get(step_key, {})
        value_label = values.get(metric_key)
        note_label = notes.get(metric_key)
        tile = tiles.get(metric_key)
        display_value = self._compact_text(value, 18)
        display_note = self._compact_text(note, 26)
        full_tooltip = f"{value}\n{tooltip}"
        if value_label is not None:
            value_label.setText(display_value)
            value_label.setToolTip(full_tooltip)
        if note_label is not None:
            note_label.setText(display_note)
            note_label.setToolTip(full_tooltip)
        if tile is not None:
            tile.setToolTip(full_tooltip)
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _configure_desktop_rail_action_button(
        self,
        button: QToolButton,
        value: str,
        note: str,
        target: str,
        tone: str,
    ) -> None:
        button.setText(self._compact_text(value, 8))
        button.setToolTip(note)
        button.setProperty("targetStep", target)
        button.setProperty("actionTone", tone)
        button.setEnabled(bool(target))
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh_step_tree_statuses(self) -> None:
        if not hasattr(self, "step_nav_summary_value"):
            return
        statuses = self._step_tree_status_model()
        self.step_status_labels = {key: label for key, (label, _tone, _note) in statuses.items()}
        counts = {"ready": 0, "pending": 0, "risk": 0}
        palette = {
            "success": ("#0f7d5b", "#e8f7ee"),
            "accent": ("#0b7285", "#e5f6f8"),
            "warning": ("#9a5a00", "#fff5df"),
            "danger": ("#b42318", "#fdeaea"),
        }
        for key, item in self.step_items.items():
            label, tone, note = statuses.get(key, ("待运行", "warning", "运行处理后生成状态。"))
            if tone == "danger":
                counts["risk"] += 1
            elif label == "待运行":
                counts["pending"] += 1
            else:
                counts["ready"] += 1
            foreground, background = palette.get(tone, palette["warning"])
            display_label = {
                "待运行": "待跑",
                "可交付": "交付",
            }.get(label, label)
            item.setText(1, display_label)
            item.setData(1, Qt.UserRole, tone)
            item.setData(1, Qt.UserRole + 1, label)
            item.setToolTip(0, note)
            item.setToolTip(1, note)
            item.setForeground(1, QBrush(QColor(foreground)))
            item.setBackground(1, QBrush(QColor(background)))
        self.step_tree.setColumnWidth(0, 122)
        self.step_tree.setColumnWidth(1, 52)
        self.step_nav_summary_value.setText(
            f"就绪 {counts['ready']} / 待运行 {counts['pending']} / 复核 {counts['risk']}"
        )
        summary_tone = "danger" if counts["risk"] else ("warning" if counts["pending"] else "success")
        self.step_count_chip.setText(f"{len(EC_STEPS)} 步")
        self._refresh_step_active_chip(self.controller.ec_nav_step)
        self.step_active_chip.setProperty("chipTone", summary_tone)
        self.step_active_chip.style().unpolish(self.step_active_chip)
        self.step_active_chip.style().polish(self.step_active_chip)
        self.step_nav_summary_card.setProperty("evidenceTone", summary_tone)
        self.step_nav_summary_card.style().unpolish(self.step_nav_summary_card)
        self.step_nav_summary_card.style().polish(self.step_nav_summary_card)
        self._refresh_step_phase_map(statuses)
        self._refresh_desktop_rail_status_strip()

    def _refresh_step_phase_map(self, statuses: dict[str, tuple[str, str, str]]) -> None:
        if not hasattr(self, "step_phase_buttons"):
            return
        active_step = self.controller.ec_nav_step
        phase_titles = {
            "project": "项目",
            "core": "核心",
            "advanced": "高级",
            "delivery": "交付",
        }
        for lens_key, title, subtitle, steps in WORKFLOW_LENSES:
            button = self.step_phase_buttons.get(lens_key)
            if button is None:
                continue
            tones = [statuses.get(step, ("", "warning", ""))[1] for step in steps]
            ready_count = sum(1 for tone in tones if tone in {"success", "accent"})
            pending_count = sum(1 for tone in tones if tone == "warning")
            risk_count = sum(1 for tone in tones if tone == "danger")
            phase_tone = "danger" if risk_count else ("warning" if pending_count else "success")
            active = active_step in steps
            label = phase_titles.get(lens_key, title)
            button.setText(f"{label}\n{ready_count}/{len(steps)}")
            button.setToolTip(
                f"{title}: ready={ready_count}; pending={pending_count}; risk={risk_count}\n{subtitle}"
            )
            button.blockSignals(True)
            button.setChecked(active)
            button.blockSignals(False)
            button.setProperty("phaseTone", phase_tone)
            button.setProperty("phaseActive", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _refresh_step_active_chip(self, key: str) -> None:
        if not hasattr(self, "step_active_chip"):
            return
        title = dict((step_key, title) for step_key, title, _subtitle in EC_STEPS).get(key, "当前步骤")
        display = title if len(title) <= 4 else f"{title[:3]}…"
        self.step_active_chip.setText(display)
        self.step_active_chip.setToolTip(title)

    def _step_tree_status_model(self) -> dict[str, tuple[str, str, str]]:
        current = self._current_window()
        workspace = self.controller.ec_processing_workspace
        summary = dict(workspace.get("summary", {}) or {})
        status = str(summary.get("status", "empty") or "empty")
        configured_steps = {"window_sampling", "data_cleaning", "screening", "rotation", "detrend", "output"}
        statuses: dict[str, tuple[str, str, str]] = {}
        if current is not None and status == "ok":
            for key, title, _subtitle in EC_STEPS:
                statuses[key] = ("完成", "success", f"{title}: 已生成真实 RP 窗口结果。")
            statuses["output"] = ("可交付", "success", "输出字段和网络交付检查已进入报告中心。")
        else:
            for key, title, _subtitle in EC_STEPS:
                if key in configured_steps:
                    statuses[key] = ("就绪", "accent", f"{title}: 配置已可用于下一次 RP 运行。")
                else:
                    statuses[key] = ("待运行", "warning", f"{title}: 运行 RP 后显示计算结果状态。")
        validation_label = getattr(self, "method_validation_label", None)
        validation_text = validation_label.text() if validation_label is not None else ""
        if "review" in validation_text.lower() or "复核" in validation_text or "z_m > canopy_height_m" in validation_text:
            statuses["uncertainty"] = ("复核", "danger", validation_text or "方法族参数需要复核。")
            statuses["output"] = ("复核", "danger", "方法族复核完成前不建议进入交付导出。")
        if status not in {"empty", "ok"} and current is None:
            for key in ("lag", "covariance", "density_correction", "steadiness", "turbulence"):
                statuses[key] = ("复核", "danger", str(summary.get("message", "运行状态需要复核。")))
        return statuses

    def _build_tree(self) -> None:
        for key, title, _subtitle in EC_STEPS:
            item = QTreeWidgetItem([title, "--"])
            item.setData(0, Qt.UserRole, key)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            item.setToolTip(0, title)
            self.step_tree.addTopLevelItem(item)
            self.step_items[key] = item
        self.step_count_chip.setText(f"{len(EC_STEPS)} 步")
        self._refresh_step_tree_statuses()

    def _build_pages(self) -> None:
        for key, title, subtitle in EC_STEPS:
            container = QWidget()
            page_layout = QVBoxLayout(container)
            page_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
            page_layout.setSpacing(TOKENS.spacing_md)
            page_layout.addWidget(section_title(title, subtitle))
            page_layout.addWidget(self._build_step_command_strip(key, title))
            builder = getattr(self, f"_build_{key}_page")
            builder(page_layout)
            page_layout.addStretch(1)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(container)
            self.step_indexes[key] = self.content_stack.addWidget(scroll)

    def _build_step_command_strip(self, step_key: str, title: str) -> CardFrame:
        strip = CardFrame(muted=True, role="tile")
        strip.setProperty("deckRole", "ecStepCommandStrip")
        strip.setProperty("stepCommandDock", True)
        strip.setProperty("stepKey", step_key)
        strip.setMaximumHeight(68)
        strip.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(strip)
        layout.setContentsMargins(TOKENS.spacing_sm, 2, TOKENS.spacing_sm, 2)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(0)

        self.step_command_tiles[step_key] = {}
        self.step_command_values[step_key] = {}
        self.step_command_notes[step_key] = {}
        for column, (metric_key, metric_title) in enumerate(
            (
                ("step", "当前步骤"),
                ("run", "运行状态"),
                ("closure", "闭合建议"),
            )
        ):
            layout.addWidget(self._step_command_tile(step_key, metric_key, metric_title, title), 0, column)

        action_panel = QWidget()
        action_panel.setProperty("stepCommandActions", True)
        action_layout = QGridLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setHorizontalSpacing(TOKENS.spacing_xs)
        action_layout.setVerticalSpacing(0)
        run_button = QToolButton()
        run_button.setText("运行")
        run_button.setProperty("railAction", True)
        run_button.setProperty("stepCommandAction", True)
        run_button.setProperty("targetStep", "run_processing")
        run_button.clicked.connect(lambda _checked=False, button=run_button: self._activate_desktop_rail_target(button))
        coverage_button = QToolButton()
        coverage_button.setText("覆盖")
        coverage_button.setProperty("railAction", True)
        coverage_button.setProperty("stepCommandAction", True)
        coverage_button.setProperty("targetStep", "coverage")
        coverage_button.clicked.connect(lambda _checked=False, button=coverage_button: self._activate_desktop_rail_target(button))
        for column, button in enumerate((run_button, coverage_button)):
            button.setMinimumWidth(50)
            button.setMaximumHeight(24)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            action_layout.addWidget(button, 0, column)
        self.step_command_buttons[step_key] = {
            "run": run_button,
            "coverage": coverage_button,
        }
        layout.addWidget(action_panel, 0, 3)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 0)
        self.step_command_strips[step_key] = strip
        return strip

    def _step_command_tile(self, step_key: str, metric_key: str, title: str, initial_value: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setProperty("stepCommandTile", True)
        tile.setProperty("evidenceTone", "warning")
        tile.setMaximumHeight(54)
        tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, 2, TOKENS.spacing_sm, 2)
        tile_layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel(initial_value)
        value_label.setObjectName("metricValue")
        value_label.setProperty("compactMetric", True)
        value_label.setWordWrap(False)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        note_label = QLabel("--")
        note_label.setObjectName("subtitle")
        note_label.setWordWrap(False)
        note_label.setMinimumWidth(0)
        note_label.setMaximumHeight(14)
        note_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(value_label)
        tile_layout.addWidget(note_label)
        self.step_command_tiles[step_key][metric_key] = tile
        self.step_command_values[step_key][metric_key] = value_label
        self.step_command_notes[step_key][metric_key] = note_label
        return tile

    def _build_window_sampling_page(self, layout: QVBoxLayout) -> None:
        self.window_cockpit_card = CardFrame(role="cockpit")
        self.window_cockpit_card.setProperty("deckRole", "windowSamplingCockpit")
        self.window_cockpit_card.setMaximumHeight(118)
        cockpit_layout = QHBoxLayout(self.window_cockpit_card)
        cockpit_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_sm, TOKENS.spacing_lg, TOKENS.spacing_sm)
        cockpit_layout.setSpacing(TOKENS.spacing_md)
        intro = QWidget()
        intro.setMaximumWidth(170)
        intro.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(0, 0, 0, 0)
        intro_layout.setSpacing(TOKENS.spacing_xs)
        intro_title = QLabel("窗口驾驶舱")
        intro_title.setObjectName("metricValue")
        intro_title.setProperty("compactMetric", True)
        intro_note = QLabel("先读规模、频率和批次轮廓，再调参数。")
        intro_note.setObjectName("subtitle")
        intro_note.setWordWrap(True)
        intro_layout.addWidget(intro_title)
        intro_layout.addWidget(intro_note)
        intro_layout.addWidget(self._build_window_console_switcher())
        self.window_console_hint_label = QLabel("--")
        self.window_console_hint_label.setObjectName("subtitle")
        self.window_console_hint_label.setMaximumHeight(18)
        self.window_console_hint_label.setWordWrap(False)
        intro_layout.addWidget(self.window_console_hint_label)
        intro_layout.addStretch(1)
        cockpit_layout.addWidget(intro, 0)

        cockpit_grid = QGridLayout()
        cockpit_grid.setContentsMargins(0, 0, 0, 0)
        cockpit_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        cockpit_grid.setVerticalSpacing(TOKENS.spacing_xs)
        self.window_cockpit_tiles: dict[str, CardFrame] = {}
        self.window_cockpit_values: dict[str, QLabel] = {}
        self.window_cockpit_notes: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(
            (
                ("duration", "窗口时长"),
                ("frequency", "采样频率"),
                ("samples", "样本量"),
                ("batches", "批次轮廓"),
            )
        ):
            cockpit_grid.addWidget(self._window_cockpit_tile(key, title), index // 2, index % 2)
        cockpit_layout.addLayout(cockpit_grid, 1)
        layout.addWidget(self.window_cockpit_card)

        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        self.window_param_card = CardFrame()
        self.window_param_card.setProperty("deckRole", "windowConsoleParamsPane")
        param_layout = QVBoxLayout(self.window_param_card)
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
        row.addWidget(self.window_param_card, 3)

        self.window_preview_card = CardFrame(muted=True)
        self.window_preview_card.setProperty("deckRole", "windowConsolePreviewPane")
        preview_layout = QVBoxLayout(self.window_preview_card)
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
        row.addWidget(self.window_preview_card, 2)

        timeline_card = CardFrame(muted=True, role="panel")
        timeline_card.setProperty("deckRole", "windowTimelinePanel")
        timeline_card.setMaximumHeight(274)
        self.window_timeline_card = timeline_card
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        timeline_layout.setSpacing(TOKENS.spacing_sm)
        timeline_layout.addWidget(section_title("窗口时间轴", "桌面端用图形先确认窗口规模和批次结构，再进入细节步骤。"))
        self.window_timeline_chip = chip("preview", "warning")
        timeline_layout.addWidget(self.window_timeline_chip, 0, Qt.AlignRight)
        self.window_plan_plot = pg.PlotWidget()
        configure_plot_theme(self.window_plan_plot, left_label="samples", bottom_label="window")
        self.window_plan_plot.setMinimumHeight(148)
        self.window_plan_plot.setMaximumHeight(168)
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
        self.window_plan_note.setMaximumHeight(36)
        timeline_layout.addWidget(self.window_plan_note)
        layout.insertWidget(3, timeline_card)
        self.window_console_cards = {
            "params": self.window_param_card,
            "preview": self.window_preview_card,
            "timeline": self.window_timeline_card,
        }
        self._show_window_console_pane("params")

    def _build_window_console_switcher(self) -> QWidget:
        switcher = QWidget()
        switcher.setProperty("deckRole", "windowConsoleSwitcher")
        switcher.setMaximumHeight(28)
        layout = QHBoxLayout(switcher)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(TOKENS.spacing_xs)
        for pane, text in (
            ("params", "参数"),
            ("preview", "预览"),
            ("timeline", "时间轴"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.setProperty("windowConsoleSwitch", True)
            button.setMinimumWidth(48)
            button.setMaximumHeight(26)
            button.clicked.connect(lambda _checked=False, key=pane: self._show_window_console_pane(key))
            self.window_console_switches[pane] = button
            layout.addWidget(button)
        return switcher

    def _show_window_console_pane(self, pane: str) -> None:
        if pane not in {"params", "preview", "timeline"}:
            pane = "params"
        for key, card in getattr(self, "window_console_cards", {}).items():
            card.setVisible(key == pane)
        pane_notes = {
            "params": "当前显示窗口参数；切到预览可看采样量，切到时间轴看批次节奏。",
            "preview": "当前显示采样规模；切到参数可调窗口，切到时间轴看批次轮廓。",
            "timeline": "当前显示时间轴；切到参数可调窗口，切到预览看采样量。",
        }
        if hasattr(self, "window_console_hint_label"):
            self.window_console_hint_label.setText(pane_notes[pane])
        if hasattr(self, "window_cockpit_card"):
            self.window_cockpit_card.setProperty("activePane", pane)
            self.window_cockpit_card.style().unpolish(self.window_cockpit_card)
            self.window_cockpit_card.style().polish(self.window_cockpit_card)
        for key, button in self.window_console_switches.items():
            button.blockSignals(True)
            button.setChecked(key == pane)
            button.blockSignals(False)
            button.style().unpolish(button)
            button.style().polish(button)

    def _window_cockpit_tile(self, key: str, title: str) -> CardFrame:
        tile = CardFrame(muted=True, role="tile")
        tile.setMaximumHeight(46)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        tile_layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        value_label = QLabel("--")
        value_label.setObjectName("metricValue")
        value_label.setProperty("compactMetric", True)
        value_label.setWordWrap(False)
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        note_label = QLabel("--")
        note_label.setVisible(False)
        tile_layout.addWidget(title_label)
        tile_layout.addWidget(value_label)
        self.window_cockpit_tiles[key] = tile
        self.window_cockpit_values[key] = value_label
        self.window_cockpit_notes[key] = note_label
        return tile

    def _set_lag_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.lag_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.lag_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_rotation_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.rotation_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.rotation_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_detrend_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.detrend_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.detrend_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_covariance_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.covariance_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.covariance_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_density_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.density_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.density_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_steadiness_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.steadiness_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.steadiness_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_turbulence_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.turbulence_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.turbulence_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _set_output_metric(self, key: str, value: str, tone: str = "warning") -> None:
        label = self.output_metric_values.get(key)
        if label is not None:
            label.setText(value)
        tile = self.output_metric_tiles.get(key)
        if tile is not None:
            tile.setProperty("evidenceTone", tone)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

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
        param_card.setProperty("deckRole", "lagParameterPanel")
        param_card.setMaximumHeight(330)
        self.lag_param_card = param_card
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

        plot_card = CardFrame(muted=True, role="panel")
        plot_card.setProperty("deckRole", "lagCovariancePanel")
        plot_card.setMaximumHeight(360)
        self.lag_covariance_card = plot_card
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        plot_layout.setSpacing(TOKENS.spacing_sm)
        plot_layout.addWidget(section_title("Covariance 曲线区", "预留协方差曲线区，让 lag 的峰值选择可见可解释。"))
        self.lag_status_chip = chip("preview", "warning")
        plot_layout.addWidget(self.lag_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.lag_metric_tiles: dict[str, CardFrame] = {}
        self.lag_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("lag", "lag", "--"),
                ("confidence", "confidence", "--"),
                ("search", "search", "--"),
                ("strategy", "strategy", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.lag_metric_tiles[key] = tile
            self.lag_metric_values[key] = value_label
        plot_layout.addLayout(metric_grid)
        self.lag_plot = pg.PlotWidget()
        configure_plot_theme(self.lag_plot, left_label="归一化协方差", bottom_label="时滞 (s)")
        self.lag_plot.setMinimumHeight(188)
        self.lag_plot.setMaximumHeight(216)
        self.lag_curve = self.lag_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.1))
        plot_layout.addWidget(self.lag_plot, 1)
        self.lag_note_label = QLabel("--")
        self.lag_note_label.setObjectName("subtitle")
        self.lag_note_label.setWordWrap(True)
        self.lag_note_label.setMaximumHeight(42)
        plot_layout.addWidget(self.lag_note_label)
        row.addWidget(plot_card, 3)

    def _build_rotation_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "rotationParameterPanel")
        param_card.setMaximumHeight(260)
        self.rotation_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "rotationEvidencePanel")
        preview_card.setMaximumHeight(290)
        self.rotation_evidence_card = preview_card
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "这里保留方法说明，便于工程师解释为何采用当前旋转方式。"))
        self.rotation_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.rotation_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.rotation_metric_tiles: dict[str, CardFrame] = {}
        self.rotation_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("requested", "requested", "--"),
                ("applied", "applied", "--"),
                ("alpha", "alpha", "--"),
                ("beta", "beta", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.rotation_metric_tiles[key] = tile
            self.rotation_metric_values[key] = value_label
        preview_layout.addLayout(metric_grid)
        self.rotation_preview_label = QLabel("--")
        self.rotation_preview_label.setObjectName("subtitle")
        self.rotation_preview_label.setWordWrap(True)
        self.rotation_preview_label.setMaximumHeight(76)
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
        param_card.setProperty("deckRole", "detrendParameterPanel")
        param_card.setMaximumHeight(260)
        self.detrend_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "detrendEvidencePanel")
        preview_card.setMaximumHeight(360)
        self.detrend_evidence_card = preview_card
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "当前仅保留说明区，后续可接入频谱与残差预览。"))
        self.detrend_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.detrend_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.detrend_metric_tiles: dict[str, CardFrame] = {}
        self.detrend_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("method", "method", "--"),
                ("windows", "windows", "--"),
                ("raw", "raw", "--"),
                ("primary", "primary", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.detrend_metric_tiles[key] = tile
            self.detrend_metric_values[key] = value_label
        preview_layout.addLayout(metric_grid)
        self.detrend_preview_label = QLabel("--")
        self.detrend_preview_label.setObjectName("subtitle")
        self.detrend_preview_label.setWordWrap(True)
        self.detrend_preview_label.setMaximumHeight(42)
        self.detrend_flux_plot = pg.PlotWidget()
        configure_plot_theme(self.detrend_flux_plot, left_label="flux", bottom_label="window")
        self.detrend_flux_plot.setMinimumHeight(168)
        self.detrend_flux_plot.setMaximumHeight(190)
        self.detrend_raw_curve = self.detrend_flux_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.6))
        self.detrend_primary_curve = self.detrend_flux_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.1))
        preview_layout.addWidget(self.detrend_flux_plot, 1)
        preview_layout.addWidget(self.detrend_preview_label)
        row.addWidget(preview_card, 3)

    def _build_covariance_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "covarianceParameterPanel")
        param_card.setMaximumHeight(240)
        self.covariance_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "covarianceEvidencePanel")
        preview_card.setMaximumHeight(280)
        self.covariance_evidence_card = preview_card
        preview_layout = QGridLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        preview_layout.setVerticalSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "预留主要协方差结果位，便于后续接入真实中间量。"), 0, 0, 1, 3)
        self.covariance_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.covariance_status_chip, 0, 3, Qt.AlignRight)
        self.covariance_metric_tiles: dict[str, CardFrame] = {}
        self.covariance_metric_values: dict[str, QLabel] = {}
        for col, (key, title, value) in enumerate(
            (
                ("method", "method", "--"),
                ("w_co2", "w'co2", "--"),
                ("w_h2o", "w'h2o", "--"),
                ("raw", "raw flux", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(68)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            preview_layout.addWidget(tile, 1, col)
            self.covariance_metric_tiles[key] = tile
            self.covariance_metric_values[key] = value_label
        self.covariance_metric_flux = self.covariance_metric_values["w_co2"]
        self.covariance_metric_h2o = self.covariance_metric_values["w_h2o"]
        self.covariance_metric_temp = self.covariance_metric_values["raw"]
        self.covariance_note_label = QLabel("--")
        self.covariance_note_label.setObjectName("subtitle")
        self.covariance_note_label.setWordWrap(True)
        self.covariance_note_label.setMaximumHeight(48)
        preview_layout.addWidget(self.covariance_note_label, 2, 0, 1, 4)
        row.addWidget(preview_card, 3)

    def _build_density_correction_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "densityParameterPanel")
        param_card.setMaximumHeight(260)
        self.density_param_card = param_card
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

        compare_card = CardFrame(muted=True, role="panel")
        compare_card.setProperty("deckRole", "densityEvidencePanel")
        compare_card.setMaximumHeight(360)
        self.density_evidence_card = compare_card
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        compare_layout.setSpacing(TOKENS.spacing_sm)
        compare_layout.addWidget(section_title("修正前后对比区", "预留修正前后对比区，帮助用户理解修正影响。"))
        self.density_status_chip = chip("preview", "warning")
        compare_layout.addWidget(self.density_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.density_metric_tiles: dict[str, CardFrame] = {}
        self.density_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("source", "source", "--"),
                ("factor", "factor", "--"),
                ("raw", "raw", "--"),
                ("primary", "primary", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.density_metric_tiles[key] = tile
            self.density_metric_values[key] = value_label
        compare_layout.addLayout(metric_grid)
        self.density_before_label = self.density_metric_values["raw"]
        self.density_after_label = self.density_metric_values["primary"]
        self.density_plot = pg.PlotWidget()
        configure_plot_theme(self.density_plot, left_label="通量", bottom_label="窗口序号")
        self.density_plot.setMinimumHeight(168)
        self.density_plot.setMaximumHeight(190)
        self.density_before_curve = self.density_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.8))
        self.density_after_curve = self.density_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        compare_layout.addWidget(self.density_plot, 1)
        self.density_note_label = QLabel("--")
        self.density_note_label.setObjectName("subtitle")
        self.density_note_label.setWordWrap(True)
        self.density_note_label.setMaximumHeight(42)
        compare_layout.addWidget(self.density_note_label)
        row.addWidget(compare_card, 3)

    def _build_steadiness_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "steadinessParameterPanel")
        param_card.setMaximumHeight(260)
        self.steadiness_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "steadinessEvidencePanel")
        preview_card.setMaximumHeight(360)
        self.steadiness_evidence_card = preview_card
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "预留稳态等级和解释区。"))
        self.steadiness_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.steadiness_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.steadiness_metric_tiles: dict[str, CardFrame] = {}
        self.steadiness_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("rule", "rule", "--"),
                ("qc", "QC", "--"),
                ("score", "score", "--"),
                ("windows", "windows", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.steadiness_metric_tiles[key] = tile
            self.steadiness_metric_values[key] = value_label
        preview_layout.addLayout(metric_grid)
        self.steadiness_preview_label = QLabel("--")
        self.steadiness_preview_label.setObjectName("subtitle")
        self.steadiness_preview_label.setWordWrap(True)
        self.steadiness_score_plot = pg.PlotWidget()
        configure_plot_theme(self.steadiness_score_plot, left_label="stationarity score", bottom_label="window")
        self.steadiness_score_plot.setMinimumHeight(168)
        self.steadiness_score_plot.setMaximumHeight(190)
        self.steadiness_score_curve = self.steadiness_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        preview_layout.addWidget(self.steadiness_score_plot, 1)
        self.steadiness_preview_label.setMaximumHeight(42)
        preview_layout.addWidget(self.steadiness_preview_label)
        row.addWidget(preview_card, 3)

    def _build_turbulence_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "turbulenceParameterPanel")
        param_card.setMaximumHeight(260)
        self.turbulence_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "turbulenceEvidencePanel")
        preview_card.setMaximumHeight(360)
        self.turbulence_evidence_card = preview_card
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "先保留文字解释区，后续可接入稳定度散点图。"))
        self.turbulence_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.turbulence_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.turbulence_metric_tiles: dict[str, CardFrame] = {}
        self.turbulence_metric_values: dict[str, QLabel] = {}
        for column, (key, title, value) in enumerate(
            (
                ("rule", "rule", "--"),
                ("ustar", "u*", "--"),
                ("score", "score", "--"),
                ("status", "status", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, 0, column)
            self.turbulence_metric_tiles[key] = tile
            self.turbulence_metric_values[key] = value_label
        preview_layout.addLayout(metric_grid)
        self.turbulence_preview_label = QLabel("--")
        self.turbulence_preview_label.setObjectName("subtitle")
        self.turbulence_preview_label.setWordWrap(True)
        self.turbulence_score_plot = pg.PlotWidget()
        configure_plot_theme(self.turbulence_score_plot, left_label="u* / turbulence score", bottom_label="window")
        self.turbulence_score_plot.setMinimumHeight(168)
        self.turbulence_score_plot.setMaximumHeight(190)
        self.turbulence_ustar_curve = self.turbulence_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["warning"], width=1.8))
        self.turbulence_score_curve = self.turbulence_score_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.1))
        preview_layout.addWidget(self.turbulence_score_plot, 1)
        self.turbulence_preview_label.setMaximumHeight(42)
        preview_layout.addWidget(self.turbulence_preview_label)
        row.addWidget(preview_card, 3)

    def _build_uncertainty_page(self, layout: QVBoxLayout) -> None:
        row = QVBoxLayout()
        row.setSpacing(TOKENS.spacing_sm)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "methodConsoleDeck")
        param_card.setMinimumWidth(0)
        param_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        param_layout.setSpacing(TOKENS.spacing_sm)
        param_layout.addWidget(section_title("方法控制", "三族方法配置共用一页，保证 UI、config snapshot 和 pipeline 参数名一致。"))

        compact_heading = param_layout.itemAt(param_layout.count() - 1).widget()
        if compact_heading is not None:
            compact_heading.setVisible(False)
            compact_heading.setMaximumHeight(0)

        self.method_family_card = CardFrame(muted=True, role="cockpit")
        self.method_family_card.setProperty("deckRole", "methodFamilyCockpit")
        self.method_family_card.setProperty("methodConsoleCompact", True)
        self.method_family_card.setMinimumWidth(0)
        self.method_family_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        method_shell_layout = QVBoxLayout(self.method_family_card)
        method_shell_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        method_shell_layout.setSpacing(TOKENS.spacing_xs)
        method_header = QHBoxLayout()
        method_header.setSpacing(TOKENS.spacing_sm)
        method_header.addWidget(section_title("方法控制台", "切换足迹、不确定度和谱修正方法族，复核实时配置快照后再运行 RP pipeline。"))
        method_header.addStretch(1)
        self.method_family_gate_chip = chip("复核", "warning")
        method_header.addWidget(self.method_family_gate_chip)
        method_shell_layout.addLayout(method_header)
        method_heading = method_header.itemAt(0).widget()
        if method_heading is not None:
            method_heading.setVisible(False)
            method_heading.setMaximumHeight(0)
        compact_method_heading = QLabel("方法控制台")
        compact_method_heading.setObjectName("sectionTitle")
        compact_method_heading.setMaximumHeight(24)
        method_header.insertWidget(0, compact_method_heading)

        method_mode_row = QHBoxLayout()
        method_mode_row.setContentsMargins(0, 0, 0, 0)
        method_mode_row.setSpacing(TOKENS.spacing_xs)
        for mode, text in (
            ("family", "方法族"),
            ("primary", "分析仪 QC"),
            ("compare", "方法对比"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.setProperty("methodTaskSwitch", True)
            button.setMinimumWidth(76)
            button.setMaximumHeight(24)
            button.clicked.connect(lambda _checked=False, key=mode: self._show_method_console_mode(key))
            self.method_console_mode_buttons[mode] = button
            method_mode_row.addWidget(button)
        method_mode_row.addStretch(1)
        method_shell_layout.addLayout(method_mode_row)

        self.method_family_switch_bar = QWidget()
        self.method_family_switch_bar.setProperty("deckRole", "methodFamilySwitchBar")
        self.method_family_switch_bar.setMaximumHeight(24)
        method_switch_row = QHBoxLayout(self.method_family_switch_bar)
        method_switch_row.setContentsMargins(0, 0, 0, 0)
        method_switch_row.setSpacing(TOKENS.spacing_xs)
        self.method_family_buttons: dict[str, QToolButton] = {}
        for family, text in (
            ("footprint", "足迹"),
            ("uncertainty", "不确定度"),
            ("spectral", "谱修正"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.setMaximumHeight(22)
            button.clicked.connect(lambda _checked=False, key=family: self._show_method_family(key))
            self.method_family_buttons[family] = button
            method_switch_row.addWidget(button)
        method_switch_row.addStretch(1)
        method_shell_layout.addWidget(self.method_family_switch_bar)

        self.method_family_tile_strip = QWidget()
        self.method_family_tile_strip.setProperty("deckRole", "methodFamilyTileStrip")
        self.method_family_tile_strip.setProperty("methodStateMirror", True)
        self.method_family_tile_strip.setMaximumHeight(46)
        self.method_family_tile_strip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        method_tile_grid = QGridLayout(self.method_family_tile_strip)
        method_tile_grid.setContentsMargins(0, 0, 0, 0)
        method_tile_grid.setHorizontalSpacing(TOKENS.spacing_xs)
        method_tile_grid.setVerticalSpacing(0)
        self.method_console_tiles: dict[str, CardFrame] = {}
        self.method_console_values: dict[str, QLabel] = {}
        self.method_console_notes: dict[str, QLabel] = {}
        self._build_method_console_tile(method_tile_grid, 0, "footprint", "足迹")
        self._build_method_console_tile(method_tile_grid, 1, "uncertainty", "随机误差")
        self._build_method_console_tile(method_tile_grid, 2, "spectral", "谱修正")
        for column in range(3):
            method_tile_grid.setColumnStretch(column, 1)
        method_shell_layout.addWidget(self.method_family_tile_strip)

        self.method_family_stack = QStackedWidget()
        self.method_family_stack.setProperty("stackRole", "methodFamilyStack")
        self.method_family_stack.setMinimumWidth(0)
        self.method_family_stack.setMaximumHeight(312)
        self.method_family_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        method_shell_layout.addWidget(self.method_family_stack)
        self.method_snapshot_label = QLabel("--")
        self.method_snapshot_label.setObjectName("subtitle")
        self.method_snapshot_label.setWordWrap(False)
        self.method_snapshot_label.setMaximumHeight(22)
        self.method_snapshot_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.method_validation_label = QLabel("--")
        self.method_validation_label.setObjectName("subtitle")
        self.method_validation_label.setWordWrap(False)
        self.method_validation_label.setMaximumHeight(22)
        self.method_validation_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        method_shell_layout.addWidget(self.method_snapshot_label)
        method_shell_layout.addWidget(self.method_validation_label)
        param_layout.addWidget(self.method_family_card)

        self.footprint_card = CardFrame(muted=True, role="console")
        self.footprint_card.setMinimumWidth(0)
        self.footprint_card.setMaximumHeight(304)
        self.footprint_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footprint_layout = QVBoxLayout(self.footprint_card)
        footprint_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        footprint_layout.setSpacing(TOKENS.spacing_xs)
        footprint_layout.addWidget(section_title("足迹方法", "推荐：kljun / z_m=6.0 / canopy_height_m=3.0"))
        footprint_title = footprint_layout.itemAt(0).widget()
        if footprint_title is not None:
            footprint_title.setMaximumHeight(18)
        self._add_method_family_control_strip(footprint_layout, "footprint", "kljun / z_m=6.0 / canopy=3.0")
        self._add_method_group_strip(footprint_layout, "footprint", ("开关/模型", "几何/稳定度", "网格"))
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
        self.footprint_summary_label.setMaximumHeight(42)
        footprint_layout.addWidget(self.footprint_summary_label)
        self.method_family_stack.addWidget(self.footprint_card)

        self.uncertainty_card = CardFrame(muted=True, role="console")
        self.uncertainty_card.setMinimumWidth(0)
        self.uncertainty_card.setMaximumHeight(258)
        self.uncertainty_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        uncertainty_layout = QVBoxLayout(self.uncertainty_card)
        uncertainty_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        uncertainty_layout.setSpacing(TOKENS.spacing_xs)
        uncertainty_layout.addWidget(section_title("不确定度方法", "推荐：mann_lenschow / integral_timescale_s=5.0 / confidence_level=0.95"))
        uncertainty_title = uncertainty_layout.itemAt(0).widget()
        if uncertainty_title is not None:
            uncertainty_title.setMaximumHeight(18)
        self._add_method_family_control_strip(uncertainty_layout, "uncertainty", "mann_lenschow / tau=5.0 / confidence=0.95")
        self._add_method_group_strip(uncertainty_layout, "uncertainty", ("方法", "置信区间"))
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
        self.uncertainty_summary_label.setMaximumHeight(42)
        uncertainty_layout.addWidget(self.uncertainty_summary_label)
        self.method_family_stack.addWidget(self.uncertainty_card)

        self.spectral_card = CardFrame(muted=True, role="console")
        self.spectral_card.setMinimumWidth(0)
        self.spectral_card.setMaximumHeight(310)
        self.spectral_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        spectral_layout = QVBoxLayout(self.spectral_card)
        spectral_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        spectral_layout.setSpacing(TOKENS.spacing_xs)
        spectral_layout.addWidget(section_title("谱修正方法", "推荐：massman；Fratini 默认自动尝试 FCC measured cospectrum"))
        spectral_title = spectral_layout.itemAt(0).widget()
        if spectral_title is not None:
            spectral_title.setMaximumHeight(18)
        self._add_method_family_control_strip(spectral_layout, "spectral", "massman / fcc_auto when Fratini")
        self._add_method_group_strip(spectral_layout, "spectral", ("开关/模型", "路径/响应", "共谱注入"))
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
        self.spectral_summary_label.setMaximumHeight(42)
        spectral_layout.addWidget(self.spectral_summary_label)
        self.method_family_stack.addWidget(self.spectral_card)
        self.method_family_sections = {
            "footprint": self.footprint_card,
            "uncertainty": self.uncertainty_card,
            "spectral": self.spectral_card,
        }
        self._show_method_family("footprint")

        self.method_support_card = CardFrame(muted=True, role="panel")
        self.method_support_card.setProperty("deckRole", "methodSupportDeck")
        self.method_support_card.setMinimumWidth(0)
        self.method_support_card.setMaximumHeight(286)
        self.method_support_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        support_layout = QVBoxLayout(self.method_support_card)
        support_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        support_layout.setSpacing(TOKENS.spacing_sm)
        support_layout.addWidget(section_title("方法配套", "把分析仪 QC 和方法对比收进同一个辅助面板，主方法区保持轻量。"))
        support_switch_row = QHBoxLayout()
        support_switch_row.setContentsMargins(0, 0, 0, 0)
        support_switch_row.setSpacing(TOKENS.spacing_xs)
        self.method_support_buttons: dict[str, QToolButton] = {}
        for key, text in (
            ("primary", "分析仪 QC"),
            ("compare", "方法对比"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("viewSwitch", True)
            button.clicked.connect(lambda _checked=False, support=key: self._show_method_support(support))
            self.method_support_buttons[key] = button
            support_switch_row.addWidget(button)
        support_switch_row.addStretch(1)
        support_layout.addLayout(support_switch_row)
        self.method_support_stack = QStackedWidget()
        self.method_support_stack.setMinimumWidth(0)
        self.method_support_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        support_layout.addWidget(self.method_support_stack)

        self.primary_analyzer_card = CardFrame(muted=True, role="console")
        self.primary_analyzer_card.setMinimumWidth(0)
        self.primary_analyzer_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        primary_layout = QVBoxLayout(self.primary_analyzer_card)
        primary_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        primary_layout.setSpacing(TOKENS.spacing_sm)
        primary_layout.setAlignment(Qt.AlignTop)
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
        self.primary_analyzer_summary_label.setMaximumHeight(42)
        primary_layout.addWidget(self.primary_analyzer_summary_label)
        self.method_support_stack.addWidget(self.primary_analyzer_card)

        self.method_compare_card = CardFrame(muted=True, role="console")
        self.method_compare_card.setMinimumWidth(0)
        self.method_compare_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        compare_layout = QVBoxLayout(self.method_compare_card)
        compare_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        compare_layout.setSpacing(TOKENS.spacing_sm)
        compare_layout.setAlignment(Qt.AlignTop)
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
        self.method_support_stack.addWidget(self.method_compare_card)
        self.method_support_sections = {
            "primary": self.primary_analyzer_card,
            "compare": self.method_compare_card,
        }
        self._show_method_support("primary", switch_console=False)
        self._show_method_console_mode("family")
        param_layout.addWidget(self.method_support_card)

        row.addWidget(param_card)

        self.method_result_card = CardFrame(muted=True, role="cockpit")
        self.method_result_card.setProperty("deckRole", "methodResultCompact")
        self.method_result_card.setMinimumWidth(0)
        self.method_result_card.setMaximumHeight(178)
        self.method_result_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        preview_layout = QVBoxLayout(self.method_result_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        result_header = QHBoxLayout()
        result_header.setContentsMargins(0, 0, 0, 0)
        result_header.setSpacing(TOKENS.spacing_sm)
        result_header.addWidget(section_title("方法结果仪表", "把 uncertainty band、Fratini/FCC 路径和方法 rollup 固定在同一块结果面板。"))
        result_header.addStretch(1)
        self.method_result_chip = chip("结果联动", "accent")
        result_header.addWidget(self.method_result_chip)
        preview_layout.addLayout(result_header)

        metric_grid = QGridLayout()
        metric_grid.setContentsMargins(0, 0, 0, 0)
        metric_grid.setHorizontalSpacing(TOKENS.spacing_md)
        metric_grid.setVerticalSpacing(TOKENS.spacing_md)
        self.uncertainty_sampling_label = QLabel("--")
        self.uncertainty_sensor_label = QLabel("--")
        self.uncertainty_processing_label = QLabel("--")
        for index, (title, value) in enumerate(
            (
                ("random_error", self.uncertainty_sampling_label),
                ("relative", self.uncertainty_sensor_label),
                ("band", self.uncertainty_processing_label),
            )
        ):
            metric_grid.addWidget(self._metric_box(title, value), 0, index)
            metric_grid.setColumnStretch(index, 1)
        preview_layout.addLayout(metric_grid)
        self.method_result_note_card = CardFrame(muted=True, role="console")
        self.method_result_note_card.setMaximumHeight(66)
        note_layout = QVBoxLayout(self.method_result_note_card)
        note_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_xs, TOKENS.spacing_md, TOKENS.spacing_xs)
        note_layout.setSpacing(TOKENS.spacing_xs)
        note_layout.addWidget(section_title("路径解释", "运行后这里显示 footprint / uncertainty / spectral correction 的实际来源。"))
        self.uncertainty_preview_note = QLabel("--")
        self.uncertainty_preview_note.setObjectName("subtitle")
        self.uncertainty_preview_note.setWordWrap(True)
        self.uncertainty_preview_note.setMaximumHeight(30)
        note_layout.addWidget(self.uncertainty_preview_note)
        preview_layout.addWidget(self.method_result_note_card)
        preview_layout.addStretch(1)
        row.addWidget(self.method_result_card)

    def _build_output_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)
        param_card = CardFrame()
        param_card.setProperty("deckRole", "outputParameterPanel")
        param_card.setMaximumHeight(260)
        self.output_param_card = param_card
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

        preview_card = CardFrame(muted=True, role="panel")
        preview_card.setProperty("deckRole", "outputEvidencePanel")
        preview_card.setMaximumHeight(360)
        self.output_evidence_card = preview_card
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        preview_layout.setSpacing(TOKENS.spacing_sm)
        preview_layout.addWidget(section_title("中间结果", "在正式运行前先预览输出重点，避免漏掉关键诊断字段。"))
        self.output_status_chip = chip("preview", "warning")
        preview_layout.addWidget(self.output_status_chip, 0, Qt.AlignRight)
        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(TOKENS.spacing_sm)
        metric_grid.setVerticalSpacing(TOKENS.spacing_sm)
        self.output_metric_tiles: dict[str, CardFrame] = {}
        self.output_metric_values: dict[str, QLabel] = {}
        for index, (key, title, value) in enumerate(
            (
                ("run", "run", "--"),
                ("windows", "windows", "--"),
                ("mode", "mode", "--"),
                ("fields", "fields", "--"),
                ("uncertainty", "uncertainty", "--"),
                ("network", "network", "--"),
            )
        ):
            tile = CardFrame(muted=True, role="tile")
            tile.setProperty("evidenceTone", "warning")
            tile.setMaximumHeight(58)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
            tile_layout.setSpacing(0)
            title_label = QLabel(title)
            title_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            value_label.setProperty("compactMetric", True)
            value_label.setWordWrap(True)
            tile_layout.addWidget(title_label)
            tile_layout.addWidget(value_label)
            metric_grid.addWidget(tile, index // 3, index % 3)
            self.output_metric_tiles[key] = tile
            self.output_metric_values[key] = value_label
        preview_layout.addLayout(metric_grid)
        self.output_preview_label = QLabel("--")
        self.output_preview_label.setObjectName("subtitle")
        self.output_preview_label.setWordWrap(True)
        self.output_preview_label.setMaximumHeight(54)
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
        self._refresh_step_active_chip(str(key))
        self._refresh_step_tree_statuses()
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
        self._refresh_step_active_chip(str(key))
        self._refresh_workflow_lens()
        self._refresh_step_tree_statuses()

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
                    "recommended": "默认推荐 kljun / z_m=6.0 / canopy_height_m=3.0。",
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
        status_label = self._ui_status_label(status)
        tone = "success" if status == "ok" else ("warning" if status == "empty" else "accent")
        self.run_status_chip.setText(f"{step_title} · {status_label}")
        self.run_status_chip.setToolTip(f"内部状态: {status}")
        self.run_status_chip.setProperty("chipTone", tone)
        self.run_status_chip.style().unpolish(self.run_status_chip)
        self.run_status_chip.style().polish(self.run_status_chip)
        self.run_summary_label.setText(str(summary.get("message", "尚未生成真实 RP 结果。")))
        if hasattr(self, "run_mission_values"):
            gate = getattr(self, "coverage_gate_chip", None)
            gate_text = gate.text() if gate is not None else "--"
            self.run_mission_values["step"].setText(step_title)
            self.run_mission_values["status"].setText(status_label)
            self.run_mission_values["status"].setToolTip(f"内部状态: {status}")
            self.run_mission_values["gate"].setText(gate_text)
        self._refresh_workflow_lens()
        self._refresh_desktop_rail_status_strip()

    def _refresh_processing_cockpit(self, *_args) -> None:
        if not hasattr(self, "cockpit_method_value"):
            return
        workspace = self.controller.ec_processing_workspace
        summary = dict(workspace.get("summary", {}) or {})
        status = str(summary.get("status", "empty") or "empty")
        status_label = self._ui_status_label(status)
        status_tone = "success" if status == "ok" else ("warning" if status == "empty" else "danger")
        self._set_cockpit_chip(f"RP {status_label}", status_tone)

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
        benchmark_status_label = self._ui_status_label(benchmark_status)
        benchmark_value = self._format_percent(pass_rate) if isinstance(pass_rate, (int, float)) else benchmark_status_label
        self.cockpit_benchmark_value.setText(benchmark_value)
        self.cockpit_benchmark_note.setText(
            f"status={benchmark_status_label}，ref={run_summary.get('benchmark_reference_id') or benchmark_state.get('reference_id') or '--'}，"
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
        self._refresh_rp_closure_deck()

    def _refresh_rp_closure_deck(self) -> None:
        if not hasattr(self, "rp_closure_values"):
            return
        workspace = self.controller.ec_processing_workspace
        summary = dict(workspace.get("summary", {}) or {})
        status = str(summary.get("status", "empty") or "empty")
        current = self._current_window()
        diagnostics = dict(current.diagnostics or {}) if current is not None else {}
        run = self.controller.current_rp_run()
        run_summary = dict(run.summary if run is not None else {})

        run_tone = "success" if current is not None and status == "ok" else ("warning" if status == "empty" else "danger")
        run_value = "已运行" if current is not None else "待运行"
        run_note = f"windows={summary.get('valid_window_count', 0)}/{summary.get('window_count', 0)}，status={status}"
        self._set_rp_closure_tile("run", run_value, run_note, run_tone)

        if current is None:
            self._set_rp_closure_tile("flux", "待生成", "运行处理后显示 primary_flux 与 QC。", "warning")
            self._set_rp_closure_tile("uncertainty", "待生成", "运行后显示 random error、relative uncertainty 和 confidence band。", "warning")
        else:
            flux_tone = {"A": "success", "B": "warning", "C": "danger"}.get(str(current.qc_grade), "accent")
            self._set_rp_closure_tile(
                "flux",
                self._format_metric(current.primary_flux, digits=4),
                f"window={current.window_id}，source={current.primary_flux_source or '--'}，QC={current.qc_grade}",
                flux_tone,
            )
            band = diagnostics.get("primary_flux_uncertainty_band")
            relative = diagnostics.get("primary_flux_relative_uncertainty")
            uncertainty_tone = "success" if isinstance(band, (int, float)) else "warning"
            self._set_rp_closure_tile(
                "uncertainty",
                f"±{self._format_metric(band, digits=4)}",
                f"relative={self._format_percent(relative)}，method={diagnostics.get('uncertainty_method', self._current_combo_text('uncertainty_mode_combo', '--'))}",
                uncertainty_tone,
            )

        footprint_method = self._current_combo_text("footprint_method_combo", "kljun")
        uncertainty_method = self._current_combo_text("uncertainty_mode_combo", "mann_lenschow")
        spectral_method = self._current_combo_text("spectral_method_combo", "massman")
        spectral_cospectrum = self._current_combo_text("spectral_cospectrum_combo", "fcc_auto")
        method_validation_label = getattr(self, "method_validation_label", None)
        validation_text = method_validation_label.text() if method_validation_label is not None else ""
        methods_tone = "warning" if "review" in validation_text.lower() or "复核" in validation_text else "success"
        method_gate_status = "方法已就绪" if methods_tone == "success" else "方法待复核"
        self._set_rp_closure_tile(
            "methods",
            f"{footprint_method} / {uncertainty_method}",
            (
                f"方法交付门：{method_gate_status}；footprint={footprint_method}；"
                f"uncertainty={uncertainty_method}；spectral={spectral_method}；cospectrum={spectral_cospectrum}"
            ),
            methods_tone,
            gate_title="方法交付门",
        )
        self._set_rp_closure_method_pills(
            {
                "footprint": footprint_method,
                "uncertainty": uncertainty_method,
                "spectral": spectral_method,
            },
            methods_tone,
        )

        benchmark_state = dict(self.controller.report_center_workspace.get("benchmark", {}) or {})
        benchmark_status = str(
            run_summary.get("benchmark_status")
            or diagnostics.get("benchmark_status")
            or benchmark_state.get("status")
            or "inactive"
        )
        deviation = dict(run_summary.get("benchmark_deviation_summary") or diagnostics.get("benchmark_deviation_summary") or {})
        pass_rate = run_summary.get("pass_rate", deviation.get("pass_rate"))
        failed_fields = run_summary.get("failed_fields", deviation.get("failed_fields", []))
        if isinstance(failed_fields, str):
            failed_fields = [failed_fields]
        benchmark_status_label = self._ui_status_label(benchmark_status)
        benchmark_value = self._format_percent(pass_rate) if isinstance(pass_rate, (int, float)) else benchmark_status_label
        benchmark_active = benchmark_status.lower() not in {"", "--", "inactive", "not_requested", "no_rp_result"}
        benchmark_tone = "success" if benchmark_active and isinstance(pass_rate, (int, float)) else ("accent" if benchmark_active else "warning")
        benchmark_reference = run_summary.get("benchmark_reference_id") or benchmark_state.get("reference_id") or "--"
        failed_count = len(failed_fields or [])
        if not benchmark_active:
            benchmark_gate_status = "对标未启用"
        elif failed_count:
            benchmark_gate_status = "对标有偏差"
        elif isinstance(pass_rate, (int, float)):
            benchmark_gate_status = "对标已闭合"
        else:
            benchmark_gate_status = "对标已启用"
        self._set_rp_closure_tile(
            "benchmark",
            benchmark_value,
            f"对标交付门：{benchmark_gate_status}；status={benchmark_status_label}；ref={benchmark_reference}；failed={failed_count}",
            benchmark_tone,
            compact_value=benchmark_gate_status,
            gate_title="对标交付门",
        )

        network = dict(self.controller.report_center_workspace.get("network_output", {}) or {})
        schema_target = diagnostics.get("schema_target") or network.get("schema_target", "FLUXNET")
        validation_status = diagnostics.get("validation_status", diagnostics.get("network_validation_status", "--"))
        missing_fields = diagnostics.get("missing_fields", diagnostics.get("network_missing_fields", []))
        if isinstance(missing_fields, str):
            missing_fields = [missing_fields]
        export_status = self._export_status_display(
            str(self.controller.report_center_workspace.get("export_status", "not_exported") or "not_exported")
        )
        network_ready = bool(schema_target) and len(missing_fields or []) == 0
        export_done = self._export_status_is_done(export_status)
        network_tone = "success" if network_ready and export_done else ("accent" if network_ready else "warning")
        validation_label = self._ui_status_label(str(validation_status))
        if network_ready and export_done:
            network_gate_status = "网络已交付"
        elif network_ready:
            network_gate_status = "网络待导出"
        else:
            network_gate_status = "网络待补齐"
        self._set_rp_closure_tile(
            "network",
            str(schema_target),
            (
                f"网络交付门：{network_gate_status}；schema={schema_target}；"
                f"validation={validation_label}；missing={len(missing_fields or [])}；export={export_status}"
            ),
            network_tone,
            gate_title="网络交付门",
        )

        tones = [
            run_tone,
            self.rp_closure_tiles["flux"].property("evidenceTone"),
            self.rp_closure_tiles["uncertainty"].property("evidenceTone"),
            methods_tone,
            benchmark_tone,
            network_tone,
        ]
        success_count = sum(1 for tone in tones if tone == "success")
        if success_count >= 5:
            deck_text, deck_tone = "可交付", "success"
        elif current is not None:
            deck_text, deck_tone = "待复核", "accent"
        else:
            deck_text, deck_tone = "待运行", "warning"
        self._set_generic_chip(self.rp_closure_chip, f"{deck_text} · {success_count}/6", deck_tone)
        self.rp_closure_deck.setProperty("evidenceStatus", deck_tone)
        self.rp_closure_deck.style().unpolish(self.rp_closure_deck)
        self.rp_closure_deck.style().polish(self.rp_closure_deck)

    def _set_rp_closure_tile(
        self,
        key: str,
        value: str,
        note: str,
        tone: str,
        *,
        compact_value: str | None = None,
        gate_title: str | None = None,
    ) -> None:
        value_label = self.rp_closure_values[key]
        note_label = self.rp_closure_notes[key]
        tile = self.rp_closure_tiles[key]
        display_value = self._compact_text(value, 18)
        display_note = self._compact_text(note, 30)
        value_label.setText(display_value)
        note_label.setText(display_note)
        tooltip = f"{gate_title or value}\n{note}"
        value_label.setToolTip(tooltip)
        note_label.setToolTip(tooltip)
        status_text = {"success": "通过", "accent": "可用", "warning": "待复核", "danger": "风险"}.get(tone, "待复核")
        self._set_generic_chip(self.rp_closure_chips[key], status_text, tone)
        tile.setProperty("evidenceTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)
        compact_value_label = getattr(self, "rp_closure_compact_values", {}).get(key)
        compact_tile = getattr(self, "rp_closure_compact_tiles", {}).get(key)
        if compact_value_label is not None:
            compact_display = self._compact_text(compact_value if compact_value is not None else value, 18)
            compact_value_label.setText(compact_display)
            compact_value_label.setToolTip(tooltip)
        if compact_tile is not None:
            compact_tile.setToolTip(tooltip)
            compact_tile.setProperty("evidenceTone", tone)
            compact_tile.style().unpolish(compact_tile)
            compact_tile.style().polish(compact_tile)

    def _set_rp_closure_method_pills(self, methods: dict[str, str], tone: str) -> None:
        family_labels = {
            "footprint": "足",
            "uncertainty": "误",
            "spectral": "谱",
        }
        full_family_labels = {
            "footprint": "足迹",
            "uncertainty": "随机误差",
            "spectral": "谱修正",
        }
        for family, pill in getattr(self, "rp_closure_method_pills", {}).items():
            method = methods.get(family, "--")
            pill.setText(f"{family_labels.get(family, family)} {self._method_badge_text(method)}")
            pill.setToolTip(f"{full_family_labels.get(family, family)}方法: {method}")
            pill.setProperty("methodTone", tone)
            pill.style().unpolish(pill)
            pill.style().polish(pill)

    def _set_generic_chip(self, label: QLabel, text: str, tone: str) -> None:
        label.setText(text)
        label.setProperty("chipTone", tone)
        if label.property("closureStage") is True:
            label.setProperty("closureTone", tone)
        label.style().unpolish(label)
        label.style().polish(label)

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

    def _ui_status_label(self, status: object) -> str:
        text = str(status or "--").strip()
        key = text.lower().replace(" ", "_")
        labels = {
            "empty": "待运行",
            "ok": "已运行",
            "inactive": "未启用",
            "not_requested": "未启用",
            "no_rp_result": "无结果",
            "not_exported": "尚未导出",
            "disabled": "未启用",
            "ready": "就绪",
            "review": "复核",
        }
        return labels.get(key, text or "--")

    def _compact_text(self, value: object, max_chars: int) -> str:
        text = str(value or "--").strip() or "--"
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 3]}..."

    def _export_status_display(self, export_status: str) -> str:
        text = export_status.strip()
        if not text or text.lower() in {"not_exported", "not exported yet"}:
            return "尚未导出"
        return text

    def _export_status_is_done(self, export_status: str) -> bool:
        text = export_status.strip().lower()
        if not text or text in {"not_exported", "not exported yet", "尚未导出"}:
            return False
        return not any(token in text for token in ("not_exported", "not exported", "尚未导出", "未导出"))

    def _refresh_readiness_panel(self) -> None:
        if not hasattr(self, "window_readiness_value"):
            return
        current = self._current_window()
        if current is None:
            minutes = self.window_minutes_spin.value()
            sample_hz = self.window_sample_hz_spin.value()
            samples = minutes * sample_hz * 60
            self._set_window_cockpit_tile("duration", f"{minutes} min", "configured window length", "accent")
            self._set_window_cockpit_tile("frequency", f"{sample_hz} Hz", "configured sampling frequency", "accent")
            self._set_window_cockpit_tile("samples", f"{samples:,}", "expected samples per window", "accent")
            self._set_window_cockpit_tile("batches", "preview x4", "synthetic window preview before RP run", "warning")
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
            minutes = self.window_minutes_spin.value()
            sample_hz = self.window_sample_hz_spin.value()
            samples = minutes * sample_hz * 60
            self._set_window_cockpit_tile("duration", f"{minutes} min", "configured window length", "accent")
            self._set_window_cockpit_tile("frequency", f"{sample_hz} Hz", "configured sampling frequency", "accent")
            self._set_window_cockpit_tile("samples", f"{samples:,}", "expected samples per window", "accent")
            self._set_window_cockpit_tile("batches", "preview x4", "synthetic window preview before RP run", "warning")
            self.window_samples_label.setText(f"{samples:,} 点 / 窗口")
            self.window_preview_note.setText("暂无真实 RP 结果，运行处理后显示窗口切分与连续性摘要。")
            xs = np.arange(1, 5, dtype=float)
            ys = np.full_like(xs, float(samples), dtype=float)
            self.window_plan_curve.setData(xs, ys)
            self._set_generic_chip(self.window_timeline_chip, "preview", "warning")
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
        sample_hz = self.window_sample_hz_spin.value()
        estimated_minutes = current.sample_count / max(float(sample_hz) * 60.0, 1.0)
        missing_tone = "success" if current.missing_ratio <= 0.05 else ("warning" if current.missing_ratio <= 0.15 else "danger")
        self._set_window_cockpit_tile("duration", f"{estimated_minutes:.1f} min", f"window={current.window_id}", "success")
        self._set_window_cockpit_tile("frequency", f"{sample_hz} Hz", "active sampling setting", "success")
        self._set_window_cockpit_tile("samples", f"{current.sample_count:,}", f"missing={current.missing_ratio * 100:.1f}%", missing_tone)
        self._set_window_cockpit_tile("batches", f"{len(xs)} windows", "real RP window series", "success")
        self.window_plan_curve.setData(xs, ys)
        self._set_generic_chip(self.window_timeline_chip, "real", "success")
        self.window_plan_note.setText(
            f"真实窗口 {len(xs)} 个；当前窗口 {current.window_id}，缺测率 {current.missing_ratio * 100:.1f}%。"
        )
        self._refresh_readiness_panel()

    def _set_window_cockpit_tile(self, key: str, value: str, note: str, tone: str) -> None:
        if not hasattr(self, "window_cockpit_values") or key not in self.window_cockpit_values:
            return
        value_label = self.window_cockpit_values[key]
        note_label = self.window_cockpit_notes[key]
        tile = self.window_cockpit_tiles[key]
        display_value = self._compact_text(value, 18)
        display_note = self._compact_text(note, 44)
        value_label.setText(display_value)
        note_label.setText(display_note)
        tooltip = f"{value}\n{note}"
        value_label.setToolTip(tooltip)
        tile.setToolTip(tooltip)
        tile.setProperty("evidenceTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

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
            self._set_generic_chip(self.lag_status_chip, "preview", "warning")
            self._set_lag_metric("lag", f"{self.lag_expected_spin.value():.1f}s", "warning")
            self._set_lag_metric("confidence", "--", "warning")
            self._set_lag_metric("search", f"±{self.lag_search_window_spin.value():.1f}s", "warning")
            self._set_lag_metric("strategy", self.lag_strategy_combo.currentText().strip(), "warning")
            self.lag_note_label.setText("暂无真实 RP 结果，运行处理后显示 lag 协方差曲线。")
            return
        x_values = section.get("intermediate", {}).get("lag_curve_x", [])
        y_values = section.get("intermediate", {}).get("lag_curve_y", [])
        self.lag_curve.setData(x_values, y_values)
        lag_strategy = current.diagnostics.get("lag_strategy", "covariance_max") if current.diagnostics else "covariance_max"
        confidence_tone = "success" if current.lag_confidence >= 0.7 else "warning" if current.lag_confidence >= 0.4 else "danger"
        self._set_generic_chip(self.lag_status_chip, "real", confidence_tone)
        self._set_lag_metric("lag", f"{current.lag_seconds:.3f}s", confidence_tone)
        self._set_lag_metric("confidence", f"{current.lag_confidence:.2f}", confidence_tone)
        self._set_lag_metric("search", f"{self.lag_search_window_spin.value():.1f}s", "success")
        self._set_lag_metric("strategy", str(lag_strategy), "success")
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
        current = self._current_window()
        if current is None:
            self._set_generic_chip(self.rotation_status_chip, "preview", "warning")
            self._set_rotation_metric("requested", self.rotation_mode_combo.currentText().strip(), "warning")
            self._set_rotation_metric("applied", "--", "warning")
            self._set_rotation_metric("alpha", "--", "warning")
            self._set_rotation_metric("beta", "--", "warning")
            self.rotation_preview_label.setText("暂无真实 RP 结果，运行处理后显示旋转模式与回退原因。")
            return
        diagnostics = current.diagnostics or {}
        intermediate = dict(section.get("intermediate", {}) or {})
        requested = str(
            diagnostics.get("requested_rotation_mode")
            or intermediate.get("requested_rotation_mode")
            or current.rotation_mode
            or "--"
        )
        applied_impl = str(
            diagnostics.get("applied_rotation_impl")
            or intermediate.get("applied_rotation_impl")
            or current.rotation_mode
            or "--"
        )
        applied_flag = bool(diagnostics.get("rotation_applied", intermediate.get("rotation_applied", False)))
        fallback = requested not in {"--", applied_impl} and applied_impl != "--"
        tone = "warning" if fallback else "success" if applied_flag or requested == "none" else "danger"
        status_text = "fallback" if fallback else "applied" if applied_flag else "not applied"
        alpha = diagnostics.get("rotation_alpha_deg")
        beta = diagnostics.get("rotation_beta_deg")
        alpha_text = f"{float(alpha):.3f} deg" if isinstance(alpha, (int, float)) else "--"
        beta_text = f"{float(beta):.3f} deg" if isinstance(beta, (int, float)) else "--"
        self._set_generic_chip(self.rotation_status_chip, status_text, tone)
        self._set_rotation_metric("requested", requested, tone)
        self._set_rotation_metric("applied", applied_impl, tone)
        self._set_rotation_metric("alpha", alpha_text, tone)
        self._set_rotation_metric("beta", beta_text, tone)
        reason = str(diagnostics.get("rotation_reason") or intermediate.get("rotation_reason") or current.reason or "--")
        planar_status = str(diagnostics.get("planar_fit_library_status") or "not_requested")
        sector = str(diagnostics.get("planar_fit_selected_sector") or "--")
        summary = str(section.get("real_summary", "旋转摘要不可用。"))
        self.rotation_preview_label.setText(
            f"{summary} reason={reason}; planar_fit={planar_status}; sector={sector}."
        )

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
            self._set_generic_chip(self.detrend_status_chip, "preview", "warning")
            self._set_detrend_metric("method", self.detrend_mode_combo.currentText().strip(), "warning")
            self._set_detrend_metric("windows", "--", "warning")
            self._set_detrend_metric("raw", "--", "warning")
            self._set_detrend_metric("primary", "--", "warning")
            self.detrend_preview_label.setText("暂无真实 RP 结果，运行处理后显示去趋势模式摘要。")
            return
        current = self._current_window()
        xs, raw_flux = self._series_from_windows(windows, "raw_flux")
        _, primary_flux = self._series_from_windows(windows, "primary_flux", fallback_key="density_corrected_flux")
        self.detrend_raw_curve.setData(xs, raw_flux)
        self.detrend_primary_curve.setData(xs, primary_flux)
        raw_value = float(current.raw_flux)
        primary_value = float(current.primary_flux if current.primary_flux != 0.0 else current.density_corrected_flux)
        tone = "success" if len(xs) > 0 else "danger"
        self._set_generic_chip(self.detrend_status_chip, "real", tone)
        self._set_detrend_metric("method", str(current.detrend_mode or "--"), tone)
        self._set_detrend_metric("windows", str(len(xs)), tone)
        self._set_detrend_metric("raw", f"{raw_value:.2f}", tone)
        self._set_detrend_metric("primary", f"{primary_value:.2f}", tone)
        self.detrend_preview_label.setText(str(section.get("real_summary", "去趋势摘要不可用。")))

    def _refresh_covariance_preview(self, *_args) -> None:
        current = self._current_window()
        if current is None:
            self._set_generic_chip(self.covariance_status_chip, "preview", "warning")
            self._set_covariance_metric("method", self.covariance_mode_combo.currentText().strip(), "warning")
            self._set_covariance_metric("w_co2", "--", "warning")
            self._set_covariance_metric("w_h2o", "--", "warning")
            self._set_covariance_metric("raw", "--", "warning")
            self.covariance_note_label.setText("暂无真实 RP 结果，运行处理后显示协方差和原始通量。")
            return
        section = self._section_workspace("covariance")
        tone = "success" if current.valid_sample_count > 0 else "danger"
        self._set_generic_chip(self.covariance_status_chip, "real", tone)
        self._set_covariance_metric("method", self.covariance_mode_combo.currentText().strip(), tone)
        self._set_covariance_metric("w_co2", f"{current.cov_w_co2:.6f}", tone)
        self._set_covariance_metric("w_h2o", f"{current.cov_w_h2o:.6f}", tone)
        self._set_covariance_metric("raw", f"{current.raw_flux:.3f}", tone)
        summary = str(section.get("real_summary", "协方差摘要不可用。"))
        self.covariance_note_label.setText(f"{summary} valid_samples={current.valid_sample_count}.")

    def _refresh_density_preview(self, *_args) -> None:
        windows = self.controller.ec_processing_workspace.get("windows", [])
        section = self._section_workspace("density_correction")
        current = self._current_window()
        if not windows or current is None:
            self.density_before_curve.setData([], [])
            self.density_after_curve.setData([], [])
            self._set_generic_chip(self.density_status_chip, "preview", "warning")
            self._set_density_metric("source", self.density_correction_combo.currentText().strip(), "warning")
            self._set_density_metric("factor", "--", "warning")
            self._set_density_metric("raw", "--", "warning")
            self._set_density_metric("primary", "--", "warning")
            self.density_note_label.setText("暂无真实 RP 结果，运行处理后显示密度/混合比修正摘要。")
            return
        xs = np.arange(1, len(windows) + 1, dtype=float)
        before = np.array([float(window.get("raw_flux", 0.0)) for window in windows], dtype=float)
        after = np.array([float(window.get("primary_flux", window.get("density_corrected_flux", 0.0))) for window in windows], dtype=float)
        self.density_before_curve.setData(xs, before)
        self.density_after_curve.setData(xs, after)
        primary_flux_val = current.primary_flux if current.primary_flux != 0.0 else current.density_corrected_flux
        primary_source = current.primary_flux_source or "wpl"
        intermediate = dict(section.get("intermediate", {}) or {})
        factor = intermediate.get("density_correction_factor")
        if not isinstance(factor, (int, float)):
            factor = current.density_corrected_flux / current.raw_flux if abs(current.raw_flux) > 1e-12 else 1.0
        tone = "success" if len(xs) > 0 else "danger"
        self._set_generic_chip(self.density_status_chip, "real", tone)
        self._set_density_metric("source", str(primary_source), tone)
        self._set_density_metric("factor", f"{float(factor):.2f}x", tone)
        self._set_density_metric("raw", f"{current.raw_flux:.2f}", tone)
        self._set_density_metric("primary", f"{primary_flux_val:.2f}", tone)
        self.density_note_label.setText(str(section.get("real_summary", current.reason)))

    def _refresh_steadiness_preview(self, *_args) -> None:
        section = self._section_workspace("steadiness")
        current = self._current_window()
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if current is None:
            self.steadiness_score_curve.setData([], [])
            self._set_generic_chip(self.steadiness_status_chip, "preview", "warning")
            self._set_steadiness_metric("rule", self.steadiness_rule_combo.currentText().strip(), "warning")
            self._set_steadiness_metric("qc", "--", "warning")
            self._set_steadiness_metric("score", "--", "warning")
            self._set_steadiness_metric("windows", "--", "warning")
            self.steadiness_preview_label.setText("暂无真实 RP 结果，运行处理后显示窗口级 QC 与异常原因。")
            return
        xs, scores = self._series_from_windows(windows, "stationarity_score")
        self.steadiness_score_curve.setData(xs, scores)
        tone = {"A": "success", "B": "warning", "C": "danger"}.get(str(current.qc_grade), "warning")
        score = current.stationarity_score
        self._set_generic_chip(self.steadiness_status_chip, "real", tone)
        self._set_steadiness_metric("rule", self.steadiness_rule_combo.currentText().strip(), tone)
        self._set_steadiness_metric("qc", str(current.qc_grade or "--"), tone)
        self._set_steadiness_metric("score", f"{float(score):.1f}" if isinstance(score, (int, float)) else "--", tone)
        self._set_steadiness_metric("windows", str(len(xs)), tone)
        self.steadiness_preview_label.setText(str(section.get("real_summary", current.reason)))

    def _refresh_turbulence_preview(self, *_args) -> None:
        section = self._section_workspace("turbulence")
        current = self._current_window()
        windows = self.controller.ec_processing_workspace.get("windows", [])
        if current is None:
            self.turbulence_ustar_curve.setData([], [])
            self.turbulence_score_curve.setData([], [])
            self._set_generic_chip(self.turbulence_status_chip, "preview", "warning")
            self._set_turbulence_metric("rule", self.ustar_rule_combo.currentText().strip(), "warning")
            self._set_turbulence_metric("ustar", "--", "warning")
            self._set_turbulence_metric("score", "--", "warning")
            self._set_turbulence_metric("status", "--", "warning")
            self.turbulence_preview_label.setText("暂无真实 RP 结果。")
            return
        xs, ustar = self._series_from_windows(windows, "ustar")
        _, score = self._series_from_windows(windows, "turbulence_score")
        self.turbulence_ustar_curve.setData(xs, ustar)
        self.turbulence_score_curve.setData(xs, score)
        detail = current.turbulence_detail or {}
        status = str(detail.get("status", "unknown") or "unknown")
        if status in {"ok", "pass", "passed"}:
            tone = "success"
        elif status in {"fail", "failed", "insufficient_data"}:
            tone = "danger"
        else:
            tone = "warning"
        self._set_generic_chip(self.turbulence_status_chip, "real", tone)
        self._set_turbulence_metric("rule", self.ustar_rule_combo.currentText().strip(), tone)
        self._set_turbulence_metric("ustar", f"{float(current.ustar):.3f}" if isinstance(current.ustar, (int, float)) else "--", tone)
        self._set_turbulence_metric(
            "score",
            f"{float(current.turbulence_score):.1f}" if isinstance(current.turbulence_score, (int, float)) else "--",
            tone,
        )
        self._set_turbulence_metric("status", status, tone)
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
        self._refresh_step_tree_statuses()

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
            self._set_generic_chip(self.output_status_chip, "preview", "warning")
            self._set_output_metric("run", "not run", "warning")
            self._set_output_metric("windows", "--", "warning")
            self._set_output_metric("mode", self.full_output_mode_combo.currentText().strip(), "warning")
            self._set_output_metric("fields", f"{len(fields)} fields" if fields else "--", "warning")
            self._set_output_metric("uncertainty", "--", "warning")
            self._set_output_metric("network", "FLUXNET", "warning")
            self.output_preview_label.setText("暂无真实 RP 结果。")
            self._refresh_processing_cockpit()
            self._refresh_readiness_panel()
            return
        summary = workspace.get("summary", {})
        field_text = "、".join(fields[:6]) if fields else "未设置输出字段"
        diagnostics = current.diagnostics or {}
        network = dict(self.controller.report_center_workspace.get("network_output", {}) or {})
        schema_target = diagnostics.get("schema_target") or network.get("schema_target", "FLUXNET")
        validation_status = diagnostics.get("validation_status", diagnostics.get("network_validation_status", network.get("validation_status", "--")))
        missing_fields = diagnostics.get("missing_fields", diagnostics.get("network_missing_fields", network.get("missing_fields", [])))
        if isinstance(missing_fields, str):
            missing_items = [item.strip() for item in missing_fields.replace("/", ",").split(",") if item.strip()]
        else:
            missing_items = list(missing_fields or [])
        run_status = str(summary.get("status", "empty"))
        network_ready = bool(schema_target) and len(missing_items) == 0
        tone = "success" if run_status == "ok" and network_ready else ("warning" if current is not None else "danger")
        uncertainty_band = diagnostics.get("primary_flux_uncertainty_band", "--")
        if isinstance(uncertainty_band, (int, float)):
            uncertainty_text = f"±{float(uncertainty_band):.2f}"
        else:
            uncertainty_text = str(uncertainty_band or "--")
        self._set_generic_chip(self.output_status_chip, "real", tone)
        self._set_output_metric("run", run_status, tone)
        self._set_output_metric("windows", str(summary.get("window_count", 0)), tone)
        self._set_output_metric("mode", self.full_output_mode_combo.currentText().strip(), tone)
        self._set_output_metric("fields", f"{len(fields)} fields" if fields else "default", tone)
        self._set_output_metric("uncertainty", uncertainty_text, tone)
        self._set_output_metric("network", str(schema_target), tone)
        self.output_preview_label.setText(
            f"字段：{field_text}；validation={validation_status}；missing={len(missing_items)}；"
            f"export={self.controller.report_center_workspace.get('export_status', 'not_exported')}。"
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
