from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.studio import StudioController
from app.theme import CardFrame, PLOT_SERIES_COLORS, TOKENS, chip, configure_plot_theme, section_title
from models.spectral_models import WindowSpectralResult


SPECTRAL_SECTIONS = [
    ("overview", "总览", "先从总体质量和主要风险入手，再决定往哪一类异常深入。"),
    ("lag_phase", "时滞与相位", "让 lag 峰值和相位变化都可见，避免只留下一个数字。"),
    ("power_spectrum", "功率谱", "判断高频端是否过早滚降，解释损失来自哪里。"),
    ("cross_spectrum", "互谱/协谱", "结合相位和主能量带，确认通量信号是否仍然可靠。"),
    ("ogive", "Ogive", "用积分曲线说明窗口是否收敛，而不是只给结论。"),
    ("transfer_function", "传递函数", "把截止频率和链路衰减显式化，解释修正因子来源。"),
    ("correction_factor", "修正因子", "展示修正前后差异，说明为什么修正会变大。"),
    ("qc_overview", "QC 总览", "用时间条带和等级统计定位问题时段。"),
    ("window_detail", "窗口明细", "按时间、等级和异常类型筛选，并联动当前窗口详情。"),
]


class SpectralQCPage(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.section_indexes: dict[str, int] = {}
        self.section_items: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(
            section_title(
                "谱修正与 QC",
                "查看时滞、频谱、互谱、修正因子与质量控制结果，定位异常窗口。",
            )
        )

        self.run_bar = self._build_run_bar()
        layout.addWidget(self.run_bar)

        self.summary_row = self._build_summary_row()
        layout.addWidget(self.summary_row)

        body = QHBoxLayout()
        body.setSpacing(TOKENS.spacing_md)
        layout.addLayout(body, 1)

        self.tree_card = CardFrame(muted=True, role="rail")
        tree_layout = QVBoxLayout(self.tree_card)
        tree_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        tree_layout.setSpacing(TOKENS.spacing_md)
        tree_layout.addWidget(section_title("分析目录", "围绕质量判断组织目录，不把用户直接丢进图表堆里。"))
        self.section_tree = QTreeWidget()
        self.section_tree.setHeaderHidden(True)
        self.section_tree.setIndentation(10)
        self.section_tree.itemSelectionChanged.connect(self._on_section_changed)
        tree_layout.addWidget(self.section_tree, 1)
        self.tree_card.setMinimumWidth(250)
        self.tree_card.setMaximumWidth(320)
        body.addWidget(self.tree_card, 0)

        self.content_stack = QStackedWidget()
        body.addWidget(self.content_stack, 1)

        self.footer_bar = self._build_footer_bar()
        layout.addWidget(self.footer_bar)

        self._build_tree()
        self._build_pages()
        self._bind_live_signals()

        self.controller.spectral_qc_changed.connect(self.refresh)
        self.controller.selection_changed.connect(self._sync_section_from_controller)
        self.refresh()

    def refresh(self) -> None:
        workspace = self.controller.spectral_qc_workspace
        run = workspace["run"]
        sections = workspace["sections"]

        self._set_combo_text(self.data_source_combo, str(run.get("data_source", "当前项目高频目录")))
        self._set_combo_text(self.time_range_combo, str(run.get("time_range", "最近 24 小时")))

        lag = sections["lag_phase"]
        self.lag_search_window_spin.setValue(float(lag.get("search_window_s", 8.0)))
        self.lag_expected_spin.setValue(float(lag.get("expected_lag_s", 2.4)))
        self._set_combo_text(self.phase_method_combo, str(lag.get("phase_method", "相位解缠 + 互谱峰位复核")))

        overview = sections["overview"]
        self._set_combo_text(self.overview_focus_combo, str(overview.get("focus_window", "凌晨高湿批次")))

        spectrum = sections["power_spectrum"]
        self._set_combo_text(self.power_reference_combo, str(spectrum.get("reference_model", "Kaimal")))
        self.power_limit_spin.setValue(float(spectrum.get("hf_limit_hz", 10.0)))
        self._set_combo_text(self.power_smoothing_combo, str(spectrum.get("smoothing", "1/6 decade")))

        cross = sections["cross_spectrum"]
        self._set_combo_text(self.cross_averaging_combo, str(cross.get("averaging", "Welch 分段平均")))
        self.cross_coherence_spin.setValue(float(cross.get("coherence_threshold", 0.72)))

        ogive = sections["ogive"]
        self._set_combo_text(self.ogive_norm_combo, str(ogive.get("normalization", "按净协方差归一化")))
        self.ogive_limit_spin.setValue(float(ogive.get("integration_limit_hz", 3.0)))

        transfer = sections["transfer_function"]
        self._set_combo_text(self.transfer_model_combo, str(transfer.get("model", "Massman + Moncrieff")))
        self.transfer_tube_spin.setValue(float(transfer.get("tube_length_m", 18.0)))
        self.transfer_cutoff_spin.setValue(float(transfer.get("cutoff_hz", 2.2)))

        correction = sections["correction_factor"]
        self._set_combo_text(self.correction_mode_combo, str(correction.get("mode", "Moncrieff 频谱修正")))
        self.correction_cap_spin.setValue(float(correction.get("factor_cap", 1.35)))

        qc = sections["qc_overview"]
        self._set_combo_text(self.qc_rule_combo, str(qc.get("grade_rule", "Foken-like + 高频损失联合")))
        self.qc_attention_spin.setValue(float(qc.get("attention_threshold", 1.20)))

        detail = sections["window_detail"]
        self._set_combo_text(self.detail_time_filter_combo, str(detail.get("time_filter", "全部窗口")))
        self._set_combo_text(self.detail_grade_filter_combo, str(detail.get("qc_filter", "全部等级")))
        self._set_combo_text(self.detail_anomaly_filter_combo, str(detail.get("anomaly_filter", "全部异常")))

        self._refresh_summary_cards()
        self._refresh_overview()
        self._refresh_lag_plot()
        self._refresh_power_plot()
        self._refresh_cross_plot()
        self._refresh_ogive_plot()
        self._refresh_transfer_plot()
        self._refresh_correction_plot()
        self._refresh_qc_plot()
        self._populate_window_table()
        self._sync_section_from_controller()
        self._refresh_footer()

    def _bind_live_signals(self) -> None:
        self.overview_focus_combo.currentIndexChanged.connect(self._refresh_overview)
        self.lag_search_window_spin.valueChanged.connect(self._refresh_lag_plot)
        self.lag_expected_spin.valueChanged.connect(self._refresh_lag_plot)
        self.phase_method_combo.currentIndexChanged.connect(self._refresh_lag_plot)
        self.power_reference_combo.currentIndexChanged.connect(self._refresh_power_plot)
        self.power_limit_spin.valueChanged.connect(self._refresh_power_plot)
        self.power_smoothing_combo.currentIndexChanged.connect(self._refresh_power_plot)
        self.cross_averaging_combo.currentIndexChanged.connect(self._refresh_cross_plot)
        self.cross_coherence_spin.valueChanged.connect(self._refresh_cross_plot)
        self.ogive_norm_combo.currentIndexChanged.connect(self._refresh_ogive_plot)
        self.ogive_limit_spin.valueChanged.connect(self._refresh_ogive_plot)
        self.transfer_model_combo.currentIndexChanged.connect(self._refresh_transfer_plot)
        self.transfer_tube_spin.valueChanged.connect(self._refresh_transfer_plot)
        self.transfer_cutoff_spin.valueChanged.connect(self._refresh_transfer_plot)
        self.correction_mode_combo.currentIndexChanged.connect(self._refresh_correction_plot)
        self.correction_cap_spin.valueChanged.connect(self._refresh_correction_plot)
        self.qc_rule_combo.currentIndexChanged.connect(self._refresh_qc_plot)
        self.qc_attention_spin.valueChanged.connect(self._refresh_qc_plot)

    def _build_run_bar(self) -> CardFrame:
        card = CardFrame(role="command")
        card.setMinimumHeight(166)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(section_title("运行条", "先选数据来源和时间范围，再决定是做完整谱分析还是快速 QC 摘要。"))
        header.addStretch(1)
        self.spectral_run_chip = chip("谱分析控制台", "accent")
        header.addWidget(self.spectral_run_chip)
        layout.addLayout(header)

        deck = QHBoxLayout()
        deck.setContentsMargins(0, 0, 0, 0)
        deck.setSpacing(TOKENS.spacing_md)

        self.data_source_combo = QComboBox()
        self.data_source_combo.setEditable(True)
        self.data_source_combo.addItems(["当前项目高频目录", "最近归档批次", "回放验证样本"])
        self.time_range_combo = QComboBox()
        self.time_range_combo.setEditable(True)
        self.time_range_combo.addItems(["最近 24 小时", "今天", "最近 7 天", "自定义时间窗"])

        self.spectral_source_panel = CardFrame(muted=True, role="tile")
        source_layout = QGridLayout(self.spectral_source_panel)
        source_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        source_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        source_layout.setVerticalSpacing(TOKENS.spacing_xs)
        source_title = QLabel("分析目标")
        source_title.setObjectName("metricLabel")
        source_layout.addWidget(source_title, 0, 0, 1, 2)
        data_label = QLabel("数据来源")
        data_label.setObjectName("metricLabel")
        time_label = QLabel("时间范围")
        time_label.setObjectName("metricLabel")
        source_layout.addWidget(data_label, 1, 0)
        source_layout.addWidget(self.data_source_combo, 2, 0)
        source_layout.addWidget(time_label, 1, 1)
        source_layout.addWidget(self.time_range_combo, 2, 1)
        source_layout.setColumnStretch(0, 1)
        source_layout.setColumnStretch(1, 1)
        deck.addWidget(self.spectral_source_panel, 3)

        buttons = [
            ("运行谱分析", True, lambda: self._run_analysis(qc_only=False)),
            ("仅生成 QC 摘要", False, lambda: self._run_analysis(qc_only=True)),
            ("导出证据包", False, self._export_evidence),
            ("保存为模板", False, self._save_template),
            ("恢复默认", False, self._restore_default),
        ]
        self.spectral_action_panel = CardFrame(muted=True, role="tile")
        action_layout = QGridLayout(self.spectral_action_panel)
        action_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        action_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        action_layout.setVerticalSpacing(TOKENS.spacing_xs)
        action_title = QLabel("谱分析动作")
        action_title.setObjectName("metricLabel")
        action_layout.addWidget(action_title, 0, 0, 1, 3)
        for index, (text, primary, callback) in enumerate(buttons):
            button = QPushButton(text)
            if primary:
                button.setProperty("variant", "primary")
            button.clicked.connect(callback)
            action_layout.addWidget(button, 1 + index // 3, index % 3)
        deck.addWidget(self.spectral_action_panel, 4)
        layout.addLayout(deck)
        return card

    def _build_summary_row(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("spectralSummaryDeck")
        wrapper.setMaximumHeight(104)
        layout = QGridLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(TOKENS.spacing_sm)
        layout.setVerticalSpacing(TOKENS.spacing_sm)

        self.lag_confidence_value = QLabel("--")
        self.high_freq_risk_value = QLabel("--")
        self.good_windows_value = QLabel("--")
        self.attention_windows_value = QLabel("--")
        self.summary_chips: dict[str, QLabel] = {}
        self.summary_metric_cards: list[CardFrame] = []
        cards = [
            ("lag_confidence", "lag 可信度", self.lag_confidence_value),
            ("high_freq_risk", "高频损失风险", self.high_freq_risk_value),
            ("good_windows", "QC 优良窗口数", self.good_windows_value),
            ("attention_windows", "需关注窗口数", self.attention_windows_value),
        ]
        for index, (key, title, value) in enumerate(cards):
            card = CardFrame(muted=True, role="tile")
            card.setMinimumHeight(74)
            card.setMaximumHeight(92)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
            card_layout.setSpacing(TOKENS.spacing_xs)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(TOKENS.spacing_xs)
            label = QLabel(title)
            label.setObjectName("metricLabel")
            header.addWidget(label)
            header.addStretch(1)
            tone = "accent" if index in {0, 2} else "warning"
            tone_chip = chip("分析中", tone)
            self.summary_chips[key] = tone_chip
            header.addWidget(tone_chip)
            card_layout.addLayout(header)
            value.setObjectName("metricValue")
            value.setProperty("compactMetric", True)
            value.setWordWrap(True)
            card_layout.addWidget(value)
            self.summary_metric_cards.append(card)
            layout.addWidget(card, 0, index)
        return wrapper

    def _build_footer_bar(self) -> CardFrame:
        card = CardFrame(muted=True, role="rail")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("摘要栏", "把当前窗口结论、等级、异常原因和导出状态固定在页面底部。"))
        layout.addStretch(1)

        self.footer_window_label = QLabel("当前窗口：--")
        self.footer_window_label.setObjectName("subtitle")
        self.footer_grade_chip = chip("QC：--", "accent")
        self.footer_reason_label = QLabel("最近异常原因：--")
        self.footer_reason_label.setObjectName("subtitle")
        self.footer_export_label = QLabel("导出状态：--")
        self.footer_export_label.setObjectName("subtitle")
        for widget in (
            self.footer_window_label,
            self.footer_grade_chip,
            self.footer_reason_label,
            self.footer_export_label,
        ):
            layout.addWidget(widget)
        return card

    def _build_tree(self) -> None:
        root = QTreeWidgetItem(["谱分析工作台"])
        root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
        self.section_tree.addTopLevelItem(root)
        for key, title, _subtitle in SPECTRAL_SECTIONS:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, key)
            item.setToolTip(0, title)
            root.addChild(item)
            self.section_items[key] = item
        root.setExpanded(True)

    def _build_pages(self) -> None:
        for key, title, subtitle in SPECTRAL_SECTIONS:
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
            self.section_indexes[key] = self.content_stack.addWidget(scroll)

    def _build_overview_page(self, layout: QVBoxLayout) -> None:
        top_row = QHBoxLayout()
        top_row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(top_row)

        focus_card = CardFrame()
        focus_layout = QVBoxLayout(focus_card)
        focus_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        focus_layout.setSpacing(TOKENS.spacing_md)
        focus_layout.addWidget(section_title("当前分析焦点", "先说明本次主要看哪一段窗口、为什么看它。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.overview_focus_combo = QComboBox()
        self.overview_focus_combo.addItems(["凌晨高湿批次", "白天稳定批次", "异常窗口回看"])
        form.addRow("关注对象", self.overview_focus_combo)
        focus_layout.addLayout(form)
        self.overview_focus_note = QLabel("--")
        self.overview_focus_note.setObjectName("subtitle")
        self.overview_focus_note.setWordWrap(True)
        focus_layout.addWidget(self.overview_focus_note)
        top_row.addWidget(focus_card, 2)

        diagnosis_card = CardFrame(muted=True)
        diagnosis_layout = QVBoxLayout(diagnosis_card)
        diagnosis_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        diagnosis_layout.setSpacing(TOKENS.spacing_md)
        diagnosis_layout.addWidget(section_title("为什么窗口质量不好", "这里先用文字把 lag、频谱和修正因子串成一句人能看懂的话。"))
        self.overview_reason_label = QLabel("--")
        self.overview_reason_label.setObjectName("subtitle")
        self.overview_reason_label.setWordWrap(True)
        diagnosis_layout.addWidget(self.overview_reason_label)
        self.overview_action_label = QLabel("--")
        self.overview_action_label.setObjectName("subtitle")
        self.overview_action_label.setWordWrap(True)
        diagnosis_layout.addWidget(self.overview_action_label)
        top_row.addWidget(diagnosis_card, 3)

        table_card = CardFrame()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        table_layout.setSpacing(TOKENS.spacing_md)
        table_layout.addWidget(section_title("重点窗口摘要", "把最需要看的窗口放在总览页，不必先钻进明细。"))
        self.overview_table = QTableWidget(0, 4)
        self.overview_table.setHorizontalHeaderLabels(["窗口", "QC", "异常类型", "修正因子"])
        self.overview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.overview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overview_table.verticalHeader().setVisible(False)
        self.overview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.overview_table)
        layout.addWidget(table_card)

    def _build_lag_phase_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("时滞与相位参数", "把搜索窗口、预期 lag 和相位处理方法放在同一张卡里。"))
        form = QFormLayout()
        form.setHorizontalSpacing(TOKENS.spacing_md)
        form.setVerticalSpacing(TOKENS.spacing_md)
        self.lag_search_window_spin = self._double_spin(2.0, 20.0, 1, suffix=" s")
        self.lag_expected_spin = self._double_spin(0.0, 10.0, 1, suffix=" s")
        self.phase_method_combo = QComboBox()
        self.phase_method_combo.addItems(["相位解缠 + 互谱峰位复核", "固定相位补偿", "仅看 lag 峰值"])
        form.addRow("搜索窗口", self.lag_search_window_spin)
        form.addRow("预期 lag", self.lag_expected_spin)
        form.addRow("相位方法", self.phase_method_combo)
        param_layout.addLayout(form)
        self.lag_phase_note = QLabel("--")
        self.lag_phase_note.setObjectName("subtitle")
        self.lag_phase_note.setWordWrap(True)
        param_layout.addWidget(self.lag_phase_note)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("lag 的 covariance 曲线", "峰值是否单峰、是否偏离预期，决定 lag 是否可信。")
        self.lag_plot = self._create_plot("归一化协方差", "时滞 (s)")
        self.lag_curve = self.lag_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.2))
        plot_card.layout().addWidget(self.lag_plot, 1)
        self.lag_plot_note = QLabel("--")
        self.lag_plot_note.setObjectName("subtitle")
        self.lag_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.lag_plot_note)
        row.addWidget(plot_card, 3)

    def _build_power_spectrum_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("功率谱参数", "操作员先看结论，工程师再看参考模型和高频截止。"))
        form = QFormLayout()
        self.power_reference_combo = QComboBox()
        self.power_reference_combo.addItems(["Kaimal", "经验参考谱", "现场自定义参考"])
        self.power_limit_spin = self._double_spin(2.0, 20.0, 1, suffix=" Hz")
        self.power_smoothing_combo = QComboBox()
        self.power_smoothing_combo.addItems(["1/6 decade", "1/3 octave", "无平滑"])
        form.addRow("参考谱", self.power_reference_combo)
        form.addRow("高频上限", self.power_limit_spin)
        form.addRow("平滑方式", self.power_smoothing_combo)
        param_layout.addLayout(form)
        self.power_note_label = QLabel("--")
        self.power_note_label.setObjectName("subtitle")
        self.power_note_label.setWordWrap(True)
        param_layout.addWidget(self.power_note_label)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("功率谱图", "高频端滚降过早时，通常会直接推高修正因子。")
        self.power_plot = self._create_plot("归一化谱能量", "频率 (Hz)")
        self.power_curve = self.power_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.2))
        self.power_ref_curve = self.power_plot.plot(
            pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.6, style=Qt.PenStyle.DashLine)
        )
        plot_card.layout().addWidget(self.power_plot, 1)
        self.power_plot_note = QLabel("--")
        self.power_plot_note.setObjectName("subtitle")
        self.power_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.power_plot_note)
        row.addWidget(plot_card, 3)

    def _build_cross_spectrum_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("互谱/协谱参数", "让互谱峰位、相位一致性和平均方式都可追溯。"))
        form = QFormLayout()
        self.cross_averaging_combo = QComboBox()
        self.cross_averaging_combo.addItems(["Welch 分段平均", "整窗平均", "多窗平均"])
        self.cross_coherence_spin = self._double_spin(0.3, 0.95, 2)
        form.addRow("平均方式", self.cross_averaging_combo)
        form.addRow("相干阈值", self.cross_coherence_spin)
        param_layout.addLayout(form)
        self.cross_note_label = QLabel("--")
        self.cross_note_label.setObjectName("subtitle")
        self.cross_note_label.setWordWrap(True)
        param_layout.addWidget(self.cross_note_label)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("互谱图", "主能量带是否对齐，是判断窗口是否可信的关键证据。")
        self.cross_plot = self._create_plot("协谱幅值", "频率 (Hz)")
        self.cross_curve = self.cross_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["warning"], width=2.0))
        plot_card.layout().addWidget(self.cross_plot, 1)
        self.cross_plot_note = QLabel("--")
        self.cross_plot_note.setObjectName("subtitle")
        self.cross_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.cross_plot_note)
        row.addWidget(plot_card, 3)

    def _build_ogive_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("Ogive 参数", "积分曲线是否收敛，往往比单个指标更容易解释窗口质量。"))
        form = QFormLayout()
        self.ogive_norm_combo = QComboBox()
        self.ogive_norm_combo.addItems(["按净协方差归一化", "按参考窗口归一化", "不归一化"])
        self.ogive_limit_spin = self._double_spin(0.5, 8.0, 1, suffix=" Hz")
        form.addRow("归一化", self.ogive_norm_combo)
        form.addRow("积分上限", self.ogive_limit_spin)
        param_layout.addLayout(form)
        self.ogive_note_label = QLabel("--")
        self.ogive_note_label.setObjectName("subtitle")
        self.ogive_note_label.setWordWrap(True)
        param_layout.addWidget(self.ogive_note_label)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("Ogive 图", "如果平台迟迟不出现，就要警惕窗口非平稳或低频未闭合。")
        self.ogive_plot = self._create_plot("累计归一化通量", "频率 (Hz)")
        self.ogive_curve = self.ogive_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["primary"], width=2.0))
        plot_card.layout().addWidget(self.ogive_plot, 1)
        self.ogive_plot_note = QLabel("--")
        self.ogive_plot_note.setObjectName("subtitle")
        self.ogive_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.ogive_plot_note)
        row.addWidget(plot_card, 3)

    def _build_transfer_function_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("传递函数参数", "让截止频率、管路长度和模型选择都能被解释。"))
        form = QFormLayout()
        self.transfer_model_combo = QComboBox()
        self.transfer_model_combo.addItems(["Massman + Moncrieff", "Moncrieff 简化版", "经验折减模型"])
        self.transfer_tube_spin = self._double_spin(5.0, 40.0, 1, suffix=" m")
        self.transfer_cutoff_spin = self._double_spin(0.5, 8.0, 1, suffix=" Hz")
        form.addRow("修正模型", self.transfer_model_combo)
        form.addRow("等效管长", self.transfer_tube_spin)
        form.addRow("截止频率", self.transfer_cutoff_spin)
        param_layout.addLayout(form)
        self.transfer_note_label = QLabel("--")
        self.transfer_note_label.setObjectName("subtitle")
        self.transfer_note_label.setWordWrap(True)
        param_layout.addWidget(self.transfer_note_label)
        self.transfer_model_version_label = QLabel("--")
        self.transfer_model_version_label.setObjectName("subtitle")
        self.transfer_model_version_label.setWordWrap(True)
        param_layout.addWidget(self.transfer_model_version_label)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("传递函数", "传递函数越早下降，后续修正因子越有可能被抬高。")
        self.transfer_plot = self._create_plot("保真度", "频率 (Hz)")
        self.transfer_curve = self.transfer_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["violet"], width=2.0))
        plot_card.layout().addWidget(self.transfer_plot, 1)
        self.transfer_plot_note = QLabel("--")
        self.transfer_plot_note.setObjectName("subtitle")
        self.transfer_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.transfer_plot_note)
        row.addWidget(plot_card, 3)

        explanation_card = CardFrame(muted=True)
        explanation_layout = QVBoxLayout(explanation_card)
        explanation_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        explanation_layout.setSpacing(TOKENS.spacing_md)
        explanation_layout.addWidget(section_title("分项修正解释区", "消费当前 spectral_qc_workspace 中的 FCC provenance 摘要。"))
        self.transfer_provenance_table = QTableWidget(0, 2)
        self.transfer_provenance_table.setHorizontalHeaderLabels(["指标", "当前值"])
        self.transfer_provenance_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.transfer_provenance_table.verticalHeader().setVisible(False)
        self.transfer_provenance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        explanation_layout.addWidget(self.transfer_provenance_table)
        self.transfer_provenance_note = QLabel("--")
        self.transfer_provenance_note.setObjectName("subtitle")
        self.transfer_provenance_note.setWordWrap(True)
        explanation_layout.addWidget(self.transfer_provenance_note)
        layout.addWidget(explanation_card)

    def _build_correction_factor_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("修正因子参数", "修正模式和上限直接决定“修正这么大”是否还能被接受。"))
        form = QFormLayout()
        self.correction_mode_combo = QComboBox()
        self.correction_mode_combo.addItems(["Moncrieff 频谱修正", "站点经验修正", "不启用修正"])
        self.correction_cap_spin = self._double_spin(1.05, 1.60, 2)
        form.addRow("修正模式", self.correction_mode_combo)
        form.addRow("修正上限", self.correction_cap_spin)
        param_layout.addLayout(form)
        self.correction_reason_label = QLabel("--")
        self.correction_reason_label.setObjectName("subtitle")
        self.correction_reason_label.setWordWrap(True)
        param_layout.addWidget(self.correction_reason_label)
        row.addWidget(param_card, 2)

        compare_card = self._plot_card("修正前后对比图", "不仅告诉用户修正值，还要告诉用户修正前后到底差了多少。")
        metric_row = QHBoxLayout()
        self.correction_before_value = QLabel("--")
        self.correction_after_value = QLabel("--")
        metric_row.addWidget(self._metric_card("修正前均值", self.correction_before_value), 1)
        metric_row.addWidget(self._metric_card("修正后均值", self.correction_after_value), 1)
        compare_card.layout().addLayout(metric_row)
        self.correction_plot = self._create_plot("通量", "窗口序号")
        self.correction_before_curve = self.correction_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["muted"], width=1.7))
        self.correction_after_curve = self.correction_plot.plot(pen=pg.mkPen(PLOT_SERIES_COLORS["secondary"], width=2.2))
        compare_card.layout().addWidget(self.correction_plot, 1)
        self.correction_plot_note = QLabel("--")
        self.correction_plot_note.setObjectName("subtitle")
        self.correction_plot_note.setWordWrap(True)
        compare_card.layout().addWidget(self.correction_plot_note)
        row.addWidget(compare_card, 3)

        contribution_card = CardFrame(muted=True)
        contribution_layout = QVBoxLayout(contribution_card)
        contribution_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        contribution_layout.setSpacing(TOKENS.spacing_md)
        contribution_layout.addWidget(section_title("分项贡献", "当前窗口最小可视化摘要。"))
        self.correction_component_table = QTableWidget(0, 2)
        self.correction_component_table.setHorizontalHeaderLabels(["分项", "因子"])
        self.correction_component_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.correction_component_table.verticalHeader().setVisible(False)
        self.correction_component_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        contribution_layout.addWidget(self.correction_component_table)
        self.correction_component_note = QLabel("--")
        self.correction_component_note.setObjectName("subtitle")
        self.correction_component_note.setWordWrap(True)
        contribution_layout.addWidget(self.correction_component_note)
        layout.addWidget(contribution_card)

    def _build_qc_overview_page(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row)

        param_card = CardFrame()
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg, TOKENS.spacing_lg)
        param_layout.setSpacing(TOKENS.spacing_md)
        param_layout.addWidget(section_title("QC 判定参数", "等级规则与关注阈值写明后，窗口好坏就不再是黑箱。"))
        form = QFormLayout()
        self.qc_rule_combo = QComboBox()
        self.qc_rule_combo.addItems(["Foken-like + 高频损失联合", "仅 Foken-like", "项目自定义规则"])
        self.qc_attention_spin = self._double_spin(1.05, 1.50, 2)
        form.addRow("判定规则", self.qc_rule_combo)
        form.addRow("关注阈值", self.qc_attention_spin)
        param_layout.addLayout(form)
        self.qc_note_label = QLabel("--")
        self.qc_note_label.setObjectName("subtitle")
        self.qc_note_label.setWordWrap(True)
        param_layout.addWidget(self.qc_note_label)
        row.addWidget(param_card, 2)

        plot_card = self._plot_card("QC 时间条带图", "用时间条带找出问题时段，再进入窗口明细逐一定位。")
        self.qc_plot = self._create_plot("QC 等级", "窗口序号")
        self.qc_bar_item = pg.BarGraphItem(x=np.array([]), height=np.array([]), width=0.8, brushes=[])
        self.qc_plot.addItem(self.qc_bar_item)
        plot_card.layout().addWidget(self.qc_plot, 1)
        self.qc_plot_note = QLabel("--")
        self.qc_plot_note.setObjectName("subtitle")
        self.qc_plot_note.setWordWrap(True)
        plot_card.layout().addWidget(self.qc_plot_note)
        row.addWidget(plot_card, 3)

        table_card = CardFrame(muted=True)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        table_layout.setSpacing(TOKENS.spacing_md)
        table_layout.addWidget(section_title("QC 等级摘要", "一眼看出 A/B/C 级窗口的数量和主因。"))
        self.qc_summary_table = QTableWidget(0, 3)
        self.qc_summary_table.setHorizontalHeaderLabels(["等级", "数量", "主因"])
        self.qc_summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.qc_summary_table.verticalHeader().setVisible(False)
        self.qc_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.qc_summary_table)
        layout.addWidget(table_card)

    def _build_window_detail_page(self, layout: QVBoxLayout) -> None:
        filter_card = CardFrame()
        filter_layout = QHBoxLayout(filter_card)
        filter_layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        filter_layout.setSpacing(TOKENS.spacing_md)
        filter_layout.addWidget(section_title("窗口筛选", "先缩小时间段和异常范围，再看单个窗口证据。"))
        filter_layout.addStretch(1)

        self.detail_time_filter_combo = QComboBox()
        self.detail_time_filter_combo.addItems(["全部窗口", "00:00-02:00", "02:00-04:00", "04:00-06:00"])
        self.detail_grade_filter_combo = QComboBox()
        self.detail_grade_filter_combo.addItems(["全部等级", "A", "B", "C"])
        self.detail_anomaly_filter_combo = QComboBox()
        self.detail_anomaly_filter_combo.addItems(["全部异常", "无异常", "高频损失", "lag 不稳", "相位偏移", "非平稳"])
        for label, widget in (
            ("时间段筛选", self.detail_time_filter_combo),
            ("QC 等级筛选", self.detail_grade_filter_combo),
            ("异常类型筛选", self.detail_anomaly_filter_combo),
        ):
            filter_layout.addWidget(QLabel(label))
            filter_layout.addWidget(widget)
        layout.addWidget(filter_card)

        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing_md)
        layout.addLayout(row, 1)

        table_card = CardFrame()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        table_layout.setSpacing(TOKENS.spacing_md)
        table_layout.addWidget(section_title("窗口明细表", "支持筛选、排序和当前窗口联动。"))
        self.window_table = QTableWidget(0, 6)
        self.window_table.setHorizontalHeaderLabels(["窗口", "时段", "QC", "异常类型", "lag", "修正因子"])
        self.window_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.window_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.window_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.window_table.verticalHeader().setVisible(False)
        self.window_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.window_table.itemSelectionChanged.connect(self._on_window_selected)
        table_layout.addWidget(self.window_table)
        row.addWidget(table_card, 3)

        detail_card = CardFrame(muted=True)
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        detail_layout.setSpacing(TOKENS.spacing_md)
        detail_layout.addWidget(section_title("当前窗口详情", "选中哪一窗，右侧就解释哪一窗为什么好或不好。"))
        self.detail_window_title = QLabel("--")
        self.detail_window_title.setObjectName("metricValue")
        detail_layout.addWidget(self.detail_window_title)
        self.detail_grade_chip = chip("QC：--", "accent")
        detail_layout.addWidget(self.detail_grade_chip)
        self.detail_reason_label = QLabel("--")
        self.detail_reason_label.setObjectName("subtitle")
        self.detail_reason_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_reason_label)
        self.detail_metrics_label = QLabel("--")
        self.detail_metrics_label.setObjectName("subtitle")
        self.detail_metrics_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_metrics_label)
        self.detail_dominant_components_label = QLabel("--")
        self.detail_dominant_components_label.setObjectName("subtitle")
        self.detail_dominant_components_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_dominant_components_label)
        self.detail_correction_detail_label = QLabel("--")
        self.detail_correction_detail_label.setObjectName("subtitle")
        self.detail_correction_detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_correction_detail_label)
        self.detail_cutoff_label = QLabel("--")
        self.detail_cutoff_label.setObjectName("subtitle")
        self.detail_cutoff_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_cutoff_label)
        self.detail_provenance_label = QLabel("--")
        self.detail_provenance_label.setObjectName("subtitle")
        self.detail_provenance_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_provenance_label)
        row.addWidget(detail_card, 2)

        self.detail_time_filter_combo.currentIndexChanged.connect(self._populate_window_table)
        self.detail_grade_filter_combo.currentIndexChanged.connect(self._populate_window_table)
        self.detail_anomaly_filter_combo.currentIndexChanged.connect(self._populate_window_table)

    def _on_section_changed(self) -> None:
        item = self.section_tree.currentItem()
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        self.content_stack.setCurrentIndex(self.section_indexes[key])
        self.controller.set_spectral_qc_nav_section(key)

    def _sync_section_from_controller(self) -> None:
        key = self.controller.spectral_qc_nav_section
        item = self.section_items.get(key)
        if item is None:
            return
        if self.section_tree.currentItem() is not item:
            self.section_tree.blockSignals(True)
            self.section_tree.setCurrentItem(item)
            self.section_tree.blockSignals(False)
        self.content_stack.setCurrentIndex(self.section_indexes[key])

    def _run_analysis(self, *, qc_only: bool) -> None:
        self.controller.save_spectral_qc_workspace(self._collect_payload())
        result = self.controller.run_spectral_qc(qc_only=qc_only)
        title = "QC 摘要已生成" if qc_only else "谱分析完成"
        QMessageBox.information(self, title, result["message"])

    def _export_evidence(self) -> None:
        result = self.controller.export_spectral_evidence()
        QMessageBox.information(self, "导出完成", result["message"])

    def _save_template(self) -> None:
        self.controller.save_spectral_qc_workspace(self._collect_payload())
        self.controller.save_spectral_qc_template()
        QMessageBox.information(self, "模板已保存", "当前谱修正与 QC 配置已保存为模板。")

    def _restore_default(self) -> None:
        if (
            QMessageBox.question(
                self,
                "恢复默认",
                "将恢复默认谱修正与 QC 设置。当前未保存的修改可能丢失，是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        self.controller.restore_default_spectral_qc()

    def _collect_payload(self) -> dict:
        workspace = self.controller.spectral_qc_workspace
        return {
            "run": {
                "data_source": self.data_source_combo.currentText().strip(),
                "time_range": self.time_range_combo.currentText().strip(),
                "last_run_mode": workspace.get("run", {}).get("last_run_mode", "完整谱分析"),
                "last_run_time": workspace.get("run", {}).get("last_run_time", "2026-04-18 15:10"),
                "export_status": workspace.get("run", {}).get("export_status", "尚未导出证据包"),
            },
            "summary": dict(workspace.get("summary", {})),
            "sections": {
                "overview": {
                    "focus_window": self.overview_focus_combo.currentText().strip(),
                    "interpretation": workspace.get("sections", {}).get("overview", {}).get("interpretation", ""),
                },
                "lag_phase": {
                    "search_window_s": self.lag_search_window_spin.value(),
                    "expected_lag_s": self.lag_expected_spin.value(),
                    "phase_method": self.phase_method_combo.currentText().strip(),
                },
                "power_spectrum": {
                    "reference_model": self.power_reference_combo.currentText().strip(),
                    "hf_limit_hz": self.power_limit_spin.value(),
                    "smoothing": self.power_smoothing_combo.currentText().strip(),
                },
                "cross_spectrum": {
                    "averaging": self.cross_averaging_combo.currentText().strip(),
                    "coherence_threshold": self.cross_coherence_spin.value(),
                },
                "ogive": {
                    "normalization": self.ogive_norm_combo.currentText().strip(),
                    "integration_limit_hz": self.ogive_limit_spin.value(),
                },
                "transfer_function": {
                    "model": self.transfer_model_combo.currentText().strip(),
                    "tube_length_m": self.transfer_tube_spin.value(),
                    "cutoff_hz": self.transfer_cutoff_spin.value(),
                },
                "correction_factor": {
                    "mode": self.correction_mode_combo.currentText().strip(),
                    "factor_cap": self.correction_cap_spin.value(),
                },
                "qc_overview": {
                    "grade_rule": self.qc_rule_combo.currentText().strip(),
                    "attention_threshold": self.qc_attention_spin.value(),
                },
                "window_detail": {
                    "time_filter": self.detail_time_filter_combo.currentText().strip(),
                    "qc_filter": self.detail_grade_filter_combo.currentText().strip(),
                    "anomaly_filter": self.detail_anomaly_filter_combo.currentText().strip(),
                },
            },
            "windows": list(workspace.get("windows", [])),
            "selected_window_id": workspace.get("selected_window_id", "w08"),
        }

    def _refresh_summary_cards(self) -> None:
        summary = self.controller.spectral_qc_workspace["summary"]
        self.lag_confidence_value.setText(str(summary.get("lag_confidence", "--")))
        self.high_freq_risk_value.setText(str(summary.get("high_freq_loss_risk", "--")))
        self.good_windows_value.setText(str(summary.get("qc_good_windows", "--")))
        self.attention_windows_value.setText(str(summary.get("attention_windows", "--")))

        self._set_chip(self.summary_chips["lag_confidence"], "峰值可复核", "success")
        risk = str(summary.get("high_freq_loss_risk", "中等"))
        risk_tone = "warning" if "中等" in risk else ("danger" if "高" in risk else "success")
        self._set_chip(self.summary_chips["high_freq_risk"], "重点关注" if risk_tone != "success" else "风险可控", risk_tone)
        self._set_chip(self.summary_chips["good_windows"], "可直接汇报", "accent")
        self._set_chip(self.summary_chips["attention_windows"], "建议复核", "warning")

    def _refresh_overview(self) -> None:
        windows = self.controller.spectral_qc_workspace.get("windows", [])
        current = self._selected_window()
        focus_text = self.overview_focus_combo.currentText().strip()
        self.overview_focus_note.setText(
            f"当前关注：{focus_text}。优先复核 lag、频谱能量和修正因子是否指向同一类问题。"
        )
        self.overview_reason_label.setText(current.get("reason", "暂无异常原因；运行谱分析后会显示主导风险。"))
        self.overview_action_label.setText("建议先查看 lag 与互谱相位，再进入 QC 总览确认等级。")

        focus_rows = [row for row in windows if row.get("qc_grade") in {"B", "C"}][:5] or windows[:5]
        self.overview_table.setRowCount(len(focus_rows))
        for row_index, row in enumerate(focus_rows):
            values = [row["label"], row["qc_grade"], row["anomaly_type"], row["correction_factor"]]
            for col, value in enumerate(values):
                item = self._table_item(value, centered=col > 0)
                self.overview_table.setItem(row_index, col, item)

    def _refresh_lag_plot(self) -> None:
        current = self._selected_window_result()
        if current is None or not current.lag_curve_x or not current.lag_curve_y:
            self._set_empty_curve(self.lag_curve)
            self.lag_phase_note.setText("暂无真实窗口 lag 曲线。")
            self.lag_plot_note.setText("运行谱分析后会显示协方差峰值与 lag 置信度。")
            return
        self.lag_curve.setData(current.lag_curve_x, current.lag_curve_y)
        self.lag_phase_note.setText(f"当前 lag {current.lag_seconds:.2f} s，置信度 {current.lag_confidence:.2f}。")
        self.lag_plot_note.setText("lag 曲线来自 WindowSpectralResult，可用于复核峰值定位。")

    def _refresh_power_plot(self) -> None:
        current = self._selected_window_result()
        if current is None or not current.power_freq:
            self._set_empty_curve(self.power_curve)
            self._set_empty_curve(self.power_ref_curve)
            self.power_note_label.setText("暂无功率谱结果。")
            self.power_plot_note.setText("运行谱分析后会叠加 measured spectrum 与 reference spectrum。")
            return
        self.power_ref_curve.setData(current.power_freq, current.power_ref)
        self.power_curve.setData(current.power_freq, current.power_measured)
        self.power_note_label.setText(f"主导异常类型：{current.anomaly_type}。")
        self.power_plot_note.setText("曲线字段：power_freq / power_measured / power_ref。")

    def _refresh_cross_plot(self) -> None:
        current = self._selected_window_result()
        if current is None or not current.cross_freq:
            self._set_empty_curve(self.cross_curve)
            self.cross_note_label.setText("暂无互谱/协谱结果。")
            self.cross_plot_note.setText("运行谱分析后会显示频率与协谱值。")
            return
        self.cross_curve.setData(current.cross_freq, current.cross_value)
        self.cross_note_label.setText(f"当前 QC {current.qc_grade}，异常类型 {current.anomaly_type}。")
        self.cross_plot_note.setText("曲线字段：cross_freq / cross_value。")

    def _refresh_ogive_plot(self) -> None:
        current = self._selected_window_result()
        if current is None or not current.ogive_freq:
            self._set_empty_curve(self.ogive_curve)
            self.ogive_note_label.setText("暂无 ogive 积分曲线。")
            self.ogive_plot_note.setText("运行谱分析后会显示窗口积分收敛情况。")
            return
        self.ogive_curve.setData(current.ogive_freq, current.ogive_value)
        self.ogive_note_label.setText(f"当前修正因子 {current.correction_factor:.3f}。")
        self.ogive_plot_note.setText("ogive 曲线字段：ogive_freq / ogive_value。")

    def _refresh_transfer_plot(self) -> None:
        current = self._selected_window_result()
        provenance = self.controller.spectral_qc_workspace.get("provenance_summary", {})
        rows = [
            ("平均总修正因子", self._format_float(provenance.get("average_correction_factor"))),
            ("tube contribution", self._format_float(provenance.get("average_tube_component"))),
            ("sensor separation contribution", self._format_float(provenance.get("average_separation_component"))),
            ("path averaging contribution", self._format_float(provenance.get("average_path_component"))),
            ("phase / lag contribution", self._format_float(provenance.get("average_phase_component"))),
            ("model_version", str(provenance.get("model_version", "--") or "--")),
        ]
        self._fill_table(self.transfer_provenance_table, rows)
        notes = [str(note) for note in provenance.get("provenance_notes", []) if str(note).strip()]
        self.transfer_provenance_note.setText(
            f"provenance_notes：{'；'.join(notes[:3])}" if notes else "当前窗口尚无分项修正说明"
        )
        self.transfer_model_version_label.setText(f"模型版本：{provenance.get('model_version', '--') or '--'}")
        if current is None:
            self._set_empty_curve(self.transfer_curve)
            self.transfer_note_label.setText("当前没有 spectral result")
            self.transfer_plot_note.setText("暂无总传递函数结果。")
            return
        if current.total_transfer_function_freq and current.total_transfer_function_value:
            self.transfer_curve.setData(current.total_transfer_function_freq, current.total_transfer_function_value)
            self.transfer_note_label.setText(f"当前窗口总传递函数已接入，平均修正因子 {current.correction_factor:.3f}")
            self.transfer_plot_note.setText("图中展示当前窗口的真实总传递函数曲线。")
            return
        self._set_empty_curve(self.transfer_curve)
        self.transfer_note_label.setText("当前窗口缺少总传递函数结果")
        self.transfer_plot_note.setText("当前窗口没有 total_transfer_function 数据，不生成演示曲线。")

    def _refresh_correction_plot(self) -> None:
        windows = self._window_results()[:8]
        current = self._selected_window_result()
        if not windows:
            self._set_empty_curve(self.correction_before_curve)
            self._set_empty_curve(self.correction_after_curve)
            self.correction_before_value.setText("--")
            self.correction_after_value.setText("--")
            self.correction_reason_label.setText("当前没有 spectral result")
            self.correction_plot_note.setText("暂无修正前后对比数据。")
            self.correction_component_table.setRowCount(0)
            self.correction_component_note.setText("当前窗口尚无分项修正说明")
            return
        xs = np.arange(1, len(windows) + 1, dtype=float)
        before = np.array([window.corrected_flux_before for window in windows], dtype=float)
        after = np.array([window.corrected_flux_after for window in windows], dtype=float)
        self.correction_before_curve.setData(xs, before)
        self.correction_after_curve.setData(xs, after)
        self.correction_before_value.setText(f"{before.mean():.3f}")
        self.correction_after_value.setText(f"{after.mean():.3f}")
        self.correction_reason_label.setText("修正前后曲线来自当前批次真实窗口结果。")
        self.correction_plot_note.setText("上方为窗口通量前后对比，下方为当前窗口分项贡献。")
        if current is None or not current.correction_factor_components:
            self.correction_component_table.setRowCount(0)
            self.correction_component_note.setText("当前窗口尚无分项修正说明")
            return
        rows = [
            ("tube_component", self._format_float(current.correction_factor_components.get("tube_component"))),
            ("separation_component", self._format_float(current.correction_factor_components.get("separation_component"))),
            ("path_component", self._format_float(current.correction_factor_components.get("path_component"))),
            ("phase_component", self._format_float(current.correction_factor_components.get("phase_component"))),
            ("total_factor", self._format_float(current.correction_factor_components.get("total_factor"))),
        ]
        self._fill_table(self.correction_component_table, rows)
        notes = [str(note) for note in current.provenance_notes if str(note).strip()]
        self.correction_component_note.setText(
            f"provenance_notes：{'；'.join(notes[:2])}" if notes else "当前窗口尚无分项修正说明"
        )

    def _refresh_qc_plot(self) -> None:
        windows = self._window_results()
        xs = np.arange(1, len(windows) + 1, dtype=float)
        heights = np.array([window.qc_band_value for window in windows], dtype=float)
        brushes = [self._grade_brush(window.qc_grade) for window in windows]
        self.qc_plot.removeItem(self.qc_bar_item)
        self.qc_bar_item = pg.BarGraphItem(x=xs, height=heights, width=0.78, brushes=brushes)
        self.qc_plot.addItem(self.qc_bar_item)
        if not windows:
            self.qc_note_label.setText("暂无窗口级 QC 结果。")
            self.qc_plot_note.setText("运行谱分析后会按窗口显示 QC 等级。")
        else:
            self.qc_note_label.setText("QC 条带来自窗口级 qc_band_value / qc_grade。")
            self.qc_plot_note.setText("颜色用于区分 A/B/C 等级。")

        grade_counts = {"A": 0, "B": 0, "C": 0}
        reasons = {"A": "可直接使用", "B": "建议复核", "C": "需重点排查"}
        for window in windows:
            grade_counts[window.qc_grade] += 1
        self.qc_summary_table.setRowCount(3)
        for row_index, grade in enumerate(("A", "B", "C")):
            self.qc_summary_table.setItem(row_index, 0, self._table_item(grade, centered=True))
            self.qc_summary_table.setItem(row_index, 1, self._table_item(str(grade_counts[grade]), centered=True))
            self.qc_summary_table.setItem(row_index, 2, self._table_item(reasons[grade]))

    def _populate_window_table(self) -> None:
        filtered = self._filtered_windows()
        self.window_table.blockSignals(True)
        self.window_table.setRowCount(len(filtered))
        for row_index, row in enumerate(filtered):
            values = [
                row["label"],
                row["period"],
                row["qc_grade"],
                row["anomaly_type"],
                row["lag_s"],
                row["correction_factor"],
            ]
            for col, value in enumerate(values):
                item = self._table_item(value, centered=col >= 2)
                item.setData(Qt.UserRole, row["window_id"])
                self.window_table.setItem(row_index, col, item)
        self.window_table.blockSignals(False)

        selected_id = self.controller.spectral_qc_workspace.get("selected_window_id")
        selected_row = next((idx for idx, row in enumerate(filtered) if row["window_id"] == selected_id), 0)
        if filtered:
            self.window_table.selectRow(selected_row)
            self._update_window_detail(filtered[selected_row])
        else:
            self._update_window_detail({})

    def _filtered_windows(self) -> list[dict]:
        windows = list(self.controller.spectral_qc_workspace.get("windows", []))
        time_filter = self.detail_time_filter_combo.currentText().strip()
        grade_filter = self.detail_grade_filter_combo.currentText().strip()
        anomaly_filter = self.detail_anomaly_filter_combo.currentText().strip()

        def match_time(row: dict) -> bool:
            if time_filter.count("-") != 1 or ":" not in time_filter:
                return True
            start = row.get("period", "")[:5]
            filter_start, filter_end = time_filter.split("-", 1)
            return filter_start <= start < filter_end

        filtered = [row for row in windows if match_time(row)]
        if grade_filter in {"A", "B", "C"}:
            filtered = [row for row in filtered if row.get("qc_grade") == grade_filter]
        known_anomalies = {"无", "高频损失", "lag 偏移", "低频未收敛", "相位异常"}
        if anomaly_filter in known_anomalies:
            filtered = [row for row in filtered if row.get("anomaly_type") == anomaly_filter]
        return filtered

    def _on_window_selected(self) -> None:
        row_index = self.window_table.currentRow()
        if row_index < 0:
            return
        item = self.window_table.item(row_index, 0)
        if item is None:
            return
        window_id = str(item.data(Qt.UserRole))
        selected = next(
            (row for row in self.controller.spectral_qc_workspace.get("windows", []) if row.get("window_id") == window_id),
            None,
        )
        if selected is None:
            return
        self.controller.spectral_qc_workspace["selected_window_id"] = window_id
        self._refresh_overview()
        self._refresh_lag_plot()
        self._refresh_power_plot()
        self._refresh_cross_plot()
        self._refresh_ogive_plot()
        self._refresh_transfer_plot()
        self._refresh_correction_plot()
        self._refresh_qc_plot()
        self._update_window_detail(selected)
        self._refresh_footer()
        self.controller.selection_changed.emit()

    def _update_window_detail(self, row: dict) -> None:
        if not row:
            self.detail_window_title.setText("没有匹配窗口")
            self._set_chip(self.detail_grade_chip, "QC：--", "warning")
            self.detail_reason_label.setText("请调整筛选条件后重试。")
            self.detail_metrics_label.setText("--")
            self.detail_dominant_components_label.setText("dominant correction components：--")
            self.detail_correction_detail_label.setText("correction_factor_detail：--")
            self.detail_cutoff_label.setText("effective_cutoff_info：--")
            self.detail_provenance_label.setText("provenance：--")
            return
        self.detail_window_title.setText(row.get("label", "--"))
        tone = self._grade_tone(row.get("qc_grade", "B"))
        self._set_chip(self.detail_grade_chip, f"QC：{row.get('qc_grade', '--')}", tone)
        self.detail_reason_label.setText(row.get("reason", "暂无说明"))
        self.detail_metrics_label.setText(
            f"异常类型：{row.get('anomaly_type', '--')}  |  lag：{row.get('lag_s', '--')}  |  修正因子：{row.get('correction_factor', '--')}"
        )
        dominant_components = row.get("dominant_correction_components") or []
        self.detail_dominant_components_label.setText(
            f"dominant correction components：{'；'.join(dominant_components[:3])}" if dominant_components else "dominant correction components：--"
        )
        detail_payload = row.get("correction_factor_detail") or {}
        self.detail_correction_detail_label.setText(
            f"correction_factor_detail：{self._format_mapping(detail_payload)}" if detail_payload else "correction_factor_detail：--"
        )
        cutoff_payload = row.get("effective_cutoff_info") or {}
        self.detail_cutoff_label.setText(
            f"effective_cutoff_info：{self._format_mapping(cutoff_payload)}" if cutoff_payload else "effective_cutoff_info：--"
        )
        notes = [str(note) for note in row.get("provenance_notes", []) if str(note).strip()]
        model_version = str(row.get("model_version", "")).strip()
        provenance_text = f"model={model_version}" if model_version else ""
        if notes:
            provenance_text = f"{provenance_text}；notes={'；'.join(notes[:2])}" if provenance_text else f"notes={'；'.join(notes[:2])}"
        self.detail_provenance_label.setText(
            f"provenance：{provenance_text}" if provenance_text else "当前窗口尚无分项修正说明"
        )

    def _refresh_footer(self) -> None:
        row = self._selected_window()
        export_status = self.controller.spectral_qc_workspace.get("run", {}).get("export_status", "尚未导出证据包")
        self.footer_window_label.setText(f"当前窗口：{row.get('label', '未选择')}")
        self._set_chip(self.footer_grade_chip, f"QC：{row.get('qc_grade', '--')}", self._grade_tone(row.get("qc_grade", "B")))
        self.footer_reason_label.setText(f"最近异常原因：{row.get('reason', '暂无异常')}")
        self.footer_export_label.setText(f"导出状态：{export_status}")

    def _selected_window(self) -> dict:
        windows = self.controller.spectral_qc_workspace.get("windows", [])
        current_id = self.controller.spectral_qc_workspace.get("selected_window_id")
        return next((row for row in windows if row.get("window_id") == current_id), windows[0] if windows else {})

    def _selected_window_result(self) -> WindowSpectralResult | None:
        current = self.controller.current_window_result()
        if current is not None:
            return current
        windows = self._window_results()
        return windows[0] if windows else None

    def _window_results(self) -> list[WindowSpectralResult]:
        run = self.controller.current_spectral_run()
        return list(run.windows) if run is not None else []

    def _set_empty_curve(self, curve) -> None:
        curve.setData([], [])

    def _fill_table(self, table: QTableWidget, rows: list[tuple[str, str]]) -> None:
        table.setRowCount(len(rows))
        for row_index, (label, value) in enumerate(rows):
            table.setItem(row_index, 0, self._table_item(label))
            table.setItem(row_index, 1, self._table_item(value, centered=True))

    def _format_float(self, value: object) -> str:
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return "--"

    def _format_mapping(self, payload: dict) -> str:
        if not payload:
            return "--"
        pairs: list[str] = []
        for key, value in payload.items():
            if isinstance(value, float):
                pairs.append(f"{key}={value:.3f}")
            else:
                pairs.append(f"{key}={value}")
        return "；".join(pairs[:4])

    def _plot_card(self, title: str, subtitle: str) -> CardFrame:
        card = CardFrame(muted=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title(title, subtitle))
        return card

    def _metric_card(self, title: str, value_widget: QLabel) -> CardFrame:
        card = CardFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_xs)
        title_label = QLabel(title)
        title_label.setObjectName("metricLabel")
        layout.addWidget(title_label)
        value_widget.setObjectName("metricValue")
        layout.addWidget(value_widget)
        return card

    def _create_plot(self, y_label: str, x_label: str) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        configure_plot_theme(plot, left_label=y_label, bottom_label=x_label)
        return plot

    def _double_spin(self, low: float, high: float, decimals: int, *, suffix: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSingleStep(10 ** (-decimals))
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

    def _table_item(self, text: str, *, centered: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if centered:
            item.setTextAlignment(Qt.AlignCenter)
        return item

    def _grade_tone(self, grade: str) -> str:
        return {"A": "success", "B": "warning", "C": "danger"}.get(grade, "accent")

    def _grade_brush(self, grade: str):
        mapping = {
            "A": pg.mkBrush(PLOT_SERIES_COLORS["secondary"]),
            "B": pg.mkBrush(PLOT_SERIES_COLORS["warning"]),
            "C": pg.mkBrush(PLOT_SERIES_COLORS["danger"]),
        }
        return mapping.get(grade, pg.mkBrush(PLOT_SERIES_COLORS["primary"]))

    def _set_chip(self, label: QLabel, text: str, tone: str) -> None:
        label.setText(text)
        label.setProperty("chipTone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
