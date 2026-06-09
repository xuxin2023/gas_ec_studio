from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

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


PROJECT_SECTION_LABELS = {
    "overview": "项目概览",
    "site_info": "站点基础信息",
    "instrument_layout": "仪器布设",
    "sampling_chain": "采样链路",
    "timing": "时间与采样",
    "output_template": "输出模板",
    "runtime_template": "运行模板",
}

EC_STEP_LABELS = {
    "window_sampling": "窗口与采样",
    "data_cleaning": "数据清洗",
    "lag": "lag",
    "rotation": "坐标旋转",
    "detrend": "去趋势",
    "covariance": "协方差",
    "density_correction": "密度/混合比修正",
    "steadiness": "稳态检验",
    "turbulence": "湍流检验",
    "uncertainty": "不确定度",
    "output": "输出",
}

SPECTRAL_SECTION_LABELS = {
    "overview": "总览",
    "lag_phase": "时滞与相位",
    "power_spectrum": "功率谱",
    "cross_spectrum": "互谱/协谱",
    "ogive": "Ogive",
    "transfer_function": "传递函数",
    "correction_factor": "修正因子",
    "qc_overview": "QC 总览",
    "window_detail": "窗口明细",
}


class ContextInspector(CardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(muted=True, parent=parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)
        layout.addWidget(section_title("上下文检查器", "根据当前页面展示摘要、风险和建议，不把工程细节铺满主界面。"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(TOKENS.spacing_md)
        self.scroll.setWidget(self.content)

    def refresh(self, context: dict) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if context.get("project_inspector") is not None:
            self._render_project_inspector(context)
        elif context.get("ec_inspector") is not None:
            self._render_ec_inspector(context)
        elif context.get("spectral_qc_inspector") is not None:
            self._render_spectral_qc_inspector(context)
        elif context.get("eddypro_attribution_inspector") is not None:
            self._render_eddypro_attribution_inspector(context)
        elif context.get("eddypro_compare_inspector") is not None:
            self._render_eddypro_compare_inspector(context)
        elif context.get("report_inspector") is not None:
            self._render_report_inspector(context)
        else:
            self._render_device_inspector(context)

        self._sanitize_visible_labels()
        self.content_layout.addStretch(1)

    def _render_project_inspector(self, context: dict) -> None:
        data = context["project_inspector"]
        section_name = PROJECT_SECTION_LABELS.get(data.get("section"), "当前目录")
        score_card = self._card("完整性评分", "用一眼能懂的方式提示当前项目配置成熟度。")
        score_layout = score_card.layout()
        score_label = QLabel(f"{data.get('score', 0)} 分")
        score_label.setObjectName("metricValue")
        score_layout.addWidget(score_label)
        score_layout.addWidget(chip(f"当前目录：{section_name}", "accent"))
        self.content_layout.addWidget(score_card)

        missing_card = self._card("缺失项", "优先补齐这些项，完整性评分会明显提升。")
        missing_layout = missing_card.layout()
        missing_items = data.get("missing_items") or []
        if missing_items:
            for item in missing_items[:6]:
                row = QLabel(f"• {item}")
                row.setObjectName("subtitle")
                row.setWordWrap(True)
                missing_layout.addWidget(row)
        else:
            row = QLabel("当前没有明显缺失项，可以进入处理流程或现场预检查。")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            missing_layout.addWidget(row)
        self.content_layout.addWidget(missing_card)

        note_card = self._card("参数说明", "帮助用户理解当前目录为什么重要。")
        note_layout = note_card.layout()
        note = QLabel(data.get("parameter_note", ""))
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        note_layout.addWidget(note)
        self.content_layout.addWidget(note_card)

        risk_card = self._card("风险提示", "把需要优先关注的现场风险翻译成人类可理解的说明。")
        risk_layout = risk_card.layout()
        for text in data.get("risks", [])[:4]:
            row = QLabel(f"• {text}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            risk_layout.addWidget(row)
        self.content_layout.addWidget(risk_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_ec_inspector(self, context: dict) -> None:
        data = context["ec_inspector"]
        step_name = EC_STEP_LABELS.get(data.get("step"), "当前步骤")
        method_card = self._card("当前方法", "始终告诉用户当前步骤采用了什么方法。")
        method_layout = method_card.layout()
        method_layout.addWidget(chip(step_name, "accent"))
        method_label = QLabel(data.get("current_method", ""))
        method_label.setObjectName("metricValue")
        method_label.setWordWrap(True)
        method_layout.addWidget(method_label)
        score = QLabel(f"推荐成熟度 {data.get('score', 0)} 分")
        score.setObjectName("subtitle")
        score.setWordWrap(True)
        method_layout.addWidget(score)
        self.content_layout.addWidget(method_card)

        applicable_card = self._card("适用条件", "避免把处理流程当成无条件通用模板。")
        applicable_layout = applicable_card.layout()
        applicable = QLabel(data.get("applicable", ""))
        applicable.setObjectName("subtitle")
        applicable.setWordWrap(True)
        applicable_layout.addWidget(applicable)
        self.content_layout.addWidget(applicable_card)

        recommended_card = self._card("推荐设置", "先给出稳妥建议，再让工程师向深处调整。")
        recommended_layout = recommended_card.layout()
        recommended = QLabel(data.get("recommended", ""))
        recommended.setObjectName("subtitle")
        recommended.setWordWrap(True)
        recommended_layout.addWidget(recommended)
        self.content_layout.addWidget(recommended_card)

        risk_card = self._card("风险提示", "把当前步骤的主要风险说明白，降低黑箱感。")
        risk_layout = risk_card.layout()
        for text in data.get("risks", [])[:4]:
            row = QLabel(f"• {text}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            risk_layout.addWidget(row)
        self.content_layout.addWidget(risk_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_spectral_qc_inspector(self, context: dict) -> None:
        data = context["spectral_qc_inspector"]
        section_name = SPECTRAL_SECTION_LABELS.get(data.get("section"), "当前目录")

        focus_card = self._card("当前聚焦", "把当前目录、窗口与等级固定展示，减少来回跳转。")
        focus_layout = focus_card.layout()
        focus_layout.addWidget(chip(section_name, "accent"))
        focus_layout.addWidget(chip(f"窗口：{data.get('current_window', '未选择')}", "success"))
        focus_layout.addWidget(chip(f"QC：{data.get('current_grade', '--')}", "warning"))
        note = QLabel(data.get("section_note", ""))
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        focus_layout.addWidget(note)
        self.content_layout.addWidget(focus_card)

        score_card = self._card("质量判断", "先给出结论，再让工程师继续追溯原因。")
        score_layout = score_card.layout()
        for text in (
            f"lag 可信度：{data.get('lag_confidence', '--')}",
            f"高频损失风险：{data.get('high_freq_loss_risk', '--')}",
            f"优良窗口数：{data.get('good_windows', 0)}",
            f"需关注窗口数：{data.get('attention_windows', 0)}",
            f"当前修正因子：{data.get('correction_factor', '--')}",
        ):
            row = QLabel(text)
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            score_layout.addWidget(row)
        self.content_layout.addWidget(score_card)

        risk_card = self._card("异常原因", "把用户最关心的“为什么不好”直接写出来。")
        risk_layout = risk_card.layout()
        reason = QLabel(data.get("recent_reason", "暂无异常"))
        reason.setObjectName("subtitle")
        reason.setWordWrap(True)
        risk_layout.addWidget(reason)
        for text in data.get("risks", [])[:4]:
            row = QLabel(f"• {text}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            risk_layout.addWidget(row)
        self.content_layout.addWidget(risk_card)

        action_card = self._card("建议动作", "优先给出下一步，不让用户停在诊断信息里。")
        action_layout = action_card.layout()
        for text in data.get("actions", [])[:4]:
            row = QLabel(f"• {text}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            action_layout.addWidget(row)
        self.content_layout.addWidget(action_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_report_inspector(self, context: dict) -> None:
        data = context["report_inspector"]

        title_card = self._card("当前报告", "让用户在右侧随时确认当前预览的报告对象。")
        title_layout = title_card.layout()
        title_layout.addWidget(chip(data.get("view_mode", "工程诊断"), "accent"))
        title = QLabel(data.get("title", "报告"))
        title.setObjectName("metricValue")
        title.setWordWrap(True)
        title_layout.addWidget(title)
        source = QLabel(f"{data.get('source', '')}\n更新时间：{data.get('updated_at', '--')}")
        source.setObjectName("subtitle")
        source.setWordWrap(True)
        title_layout.addWidget(source)
        title_layout.addWidget(chip(data.get("export_status", "尚未导出"), "success"))
        self.content_layout.addWidget(title_card)

        export_card = self._card("导出与来源", "把导出选项、版本和文件信息收在同一侧栏。")
        export_layout = export_card.layout()
        if data.get("export_options"):
            row = QLabel("导出选项")
            row.setObjectName("metricLabel")
            export_layout.addWidget(row)
            for item in data.get("export_options", [])[:4]:
                text = QLabel(f"• {item}")
                text.setObjectName("subtitle")
                text.setWordWrap(True)
                export_layout.addWidget(text)
        file_info = data.get("file_info", {})
        if file_info:
            row = QLabel("文件信息")
            row.setObjectName("metricLabel")
            export_layout.addWidget(row)
            for key, value in list(file_info.items())[:4]:
                text = QLabel(f"{key}：{value}")
                text.setObjectName("subtitle")
                text.setWordWrap(True)
                export_layout.addWidget(text)
        if data.get("versions"):
            row = QLabel("版本与来源")
            row.setObjectName("metricLabel")
            export_layout.addWidget(row)
            for item in data.get("versions", [])[:4]:
                text = QLabel(f"• {item}")
                text.setObjectName("subtitle")
                text.setWordWrap(True)
                export_layout.addWidget(text)
        self.content_layout.addWidget(export_card)

        usage_card = self._card("使用建议", "操作员、工程师和管理汇报都能在这里找到下一步。")
        usage_layout = usage_card.layout()
        for item in data.get("usage", [])[:4]:
            text = QLabel(f"• {item}")
            text.setObjectName("subtitle")
            text.setWordWrap(True)
            usage_layout.addWidget(text)
        for item in data.get("conclusions", [])[:2]:
            text = QLabel(item)
            text.setObjectName("subtitle")
            text.setWordWrap(True)
            usage_layout.addWidget(text)
        compare = data.get("batch_compare", {})
        if compare:
            compare_text = QLabel(
                f"当前批次：{compare.get('current_batch', '--')}\n对比批次：{compare.get('compare_batch', '--')}"
            )
            compare_text.setObjectName("subtitle")
            compare_text.setWordWrap(True)
            usage_layout.addWidget(compare_text)
        self.content_layout.addWidget(usage_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_eddypro_compare_inspector(self, context: dict) -> None:
        data = context["eddypro_compare_inspector"]

        title_card = self._card("行业参考对标", "在右侧快速确认本次对标对象、匹配情况和主要风险。")
        title_layout = title_card.layout()
        title_layout.addWidget(chip(data.get("status", "空状态"), "accent"))
        title = QLabel(data.get("compare_id", "当前还没有行业参考对标结果"))
        title.setObjectName("metricValue")
        title.setWordWrap(True)
        title_layout.addWidget(title)
        source = QLabel(f"当前来源：{data.get('current_source', '--')}\n参考来源：{data.get('reference_source', '--')}")
        source.setObjectName("subtitle")
        source.setWordWrap(True)
        title_layout.addWidget(source)
        self.content_layout.addWidget(title_card)

        summary_card = self._card("摘要指标", "优先看匹配窗口数、平均偏差和 QC 一致率。")
        summary_layout = summary_card.layout()
        for text in (
            f"匹配窗口数：{data.get('matched_window_count', 0)}",
            f"平均 lag 偏差：{data.get('avg_lag_delta', '--')}",
            f"平均 flux 偏差：{data.get('avg_flux_delta', '--')}",
            f"QC 一致率：{data.get('qc_match_ratio', '--')}",
        ):
            row = QLabel(text)
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            summary_layout.addWidget(row)
        self.content_layout.addWidget(summary_card)

        risk_card = self._card("风险提示", "把需要优先复核的差异直接列出来。")
        risk_layout = risk_card.layout()
        for item in (data.get("risk_summary", []) or ["当前未发现显著行业参考对标风险。"])[:4]:
            row = QLabel(f"• {item}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            risk_layout.addWidget(row)
        self.content_layout.addWidget(risk_card)

        action_card = self._card("建议动作", "先看前 10 个差异窗口，再定位明显偏差。")
        action_layout = action_card.layout()
        for item in data.get("actions", [])[:4]:
            row = QLabel(f"• {item}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            action_layout.addWidget(row)
        self.content_layout.addWidget(action_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_eddypro_attribution_inspector(self, context: dict) -> None:
        data = context["eddypro_attribution_inspector"]

        title_card = self._card("行业参考归因解释", "把对标差异的主要解释和下一步复核动作收在同一侧栏。")
        title_layout = title_card.layout()
        title_layout.addWidget(chip(data.get("status", "空状态"), "accent"))
        title = QLabel(" / ".join(data.get("dominant_causes", [])[:3]) or "当前还没有对标归因结果")
        title.setObjectName("metricValue")
        title.setWordWrap(True)
        title_layout.addWidget(title)
        summary = QLabel(data.get("summary_text", "请先运行行业参考对标比较"))
        summary.setObjectName("subtitle")
        summary.setWordWrap(True)
        title_layout.addWidget(summary)
        title_layout.addWidget(chip(f"风险等级：{data.get('risk_level', '未知')}", "warning"))
        self.content_layout.addWidget(title_card)

        coverage_card = self._card("覆盖情况", "先确认归因覆盖了多少窗口，再决定是否继续下钻。")
        coverage_layout = coverage_card.layout()
        for text in (
            f"归因数量：{data.get('attribution_count', 0)}",
            f"窗口覆盖：{data.get('window_coverage_count', 0)}",
        ):
            row = QLabel(text)
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            coverage_layout.addWidget(row)
        self.content_layout.addWidget(coverage_card)

        recommendation_card = self._card("关键建议", "优先处理最可能改变对标结论的复核动作。")
        recommendation_layout = recommendation_card.layout()
        recommendations = data.get("recommendations", []) or ["当前还没有对标归因结果", "请先运行行业参考对标比较"]
        for item in recommendations[:4]:
            row = QLabel(f"- {item}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            recommendation_layout.addWidget(row)
        self.content_layout.addWidget(recommendation_card)

        action_card = self._card("建议动作", "把归因摘要转成可执行的排查顺序。")
        action_layout = action_card.layout()
        for item in data.get("actions", [])[:4]:
            row = QLabel(f"- {item}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            action_layout.addWidget(row)
        self.content_layout.addWidget(action_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _render_device_inspector(self, context: dict) -> None:
        device = context.get("device")
        if device is not None:
            status_card = self._card("当前设备摘要", f"{device.config.label} · {device.config.port}")
            status_layout = status_card.layout()
            status_layout.addWidget(
                chip(
                    "在线" if device.runtime.connected else "离线",
                    "success" if device.runtime.connected else "warning",
                )
            )
            for text in (
                f"设备 ID：{device.config.device_id}",
                f"当前模式：MODE{device.runtime.mode}",
                f"输出方式：{'主动发送' if device.runtime.active_send else '按需读取'}",
                f"最近有效帧：{device.runtime.last_frame_time.strftime('%H:%M:%S') if device.runtime.last_frame_time else '暂无'}",
                f"当前说明：{device.runtime.last_message}",
            ):
                row = QLabel(text)
                row.setObjectName("subtitle")
                row.setWordWrap(True)
                status_layout.addWidget(row)
            self.content_layout.addWidget(status_card)

        tx_rows = context.get("recent_transactions", [])
        tx_card = self._card("最近事务", "最近执行过的关键动作。")
        tx_layout = tx_card.layout()
        if tx_rows:
            for record in tx_rows[:4]:
                line = QLabel(f"[{record.created_at:%H:%M:%S}] {record.label} · {record.response_summary or record.status.value}")
                line.setObjectName("subtitle")
                line.setWordWrap(True)
                tx_layout.addWidget(line)
        else:
            empty = QLabel("还没有事务记录。")
            empty.setObjectName("subtitle")
            tx_layout.addWidget(empty)
        self.content_layout.addWidget(tx_card)

        suggestion_card = self._card("建议操作", "根据当前状态给出下一步建议。")
        suggestion_layout = suggestion_card.layout()
        for text in context.get("suggestions", [])[:4]:
            row = QLabel(f"• {text}")
            row.setObjectName("subtitle")
            row.setWordWrap(True)
            suggestion_layout.addWidget(row)
        self.content_layout.addWidget(suggestion_card)

        event_card = self._card("最近告警", "只保留需要关注的提示。")
        event_layout = event_card.layout()
        events = context.get("recent_events", [])
        if events:
            for event in events[:4]:
                tone = "danger" if event.severity == "error" else ("warning" if event.severity == "warning" else "accent")
                event_layout.addWidget(chip(event.title, tone))
                detail = QLabel(event.message)
                detail.setObjectName("subtitle")
                detail.setWordWrap(True)
                event_layout.addWidget(detail)
        else:
            detail = QLabel("当前没有需要处理的异常事件。")
            detail.setObjectName("subtitle")
            event_layout.addWidget(detail)
        self.content_layout.addWidget(event_card)

        self.content_layout.addWidget(self._logs_card(context))

    def _logs_card(self, context: dict) -> CardFrame:
        log_card = self._card("最近提示", "保留最近几条中文提示，方便快速回看。")
        log_layout = log_card.layout()
        rows = context.get("logs", [])
        if not rows:
            empty = QLabel("暂无日志提示。")
            empty.setObjectName("subtitle")
            log_layout.addWidget(empty)
            return log_card
        for row in rows[:6]:
            text = QLabel(f"[{row['time']}] {row['message']}")
            text.setObjectName("subtitle")
            text.setWordWrap(True)
            log_layout.addWidget(text)
        return log_card

    def _card(self, title: str, subtitle: str) -> CardFrame:
        card = CardFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_sm)
        layout.addWidget(section_title(_ui_safe_text(title), _ui_safe_text(subtitle)))
        return card

    def _sanitize_visible_labels(self) -> None:
        for label in self.content.findChildren(QLabel):
            safe = _ui_safe_text(label.text())
            if safe != label.text():
                label.setText(safe)
