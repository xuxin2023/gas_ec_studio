from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from app.theme import CardFrame, TOKENS, section_title


class NavigationRail(CardFrame):
    page_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(muted=True, role="rail", parent=parent)
        self.setProperty("navRailWorkbench", True)
        self.setMinimumWidth(188)
        self.setMaximumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)

        brand = section_title("Gas EC Studio", "高端科学仪器工作台")
        brand.setProperty("navBrandBlock", True)
        layout.addWidget(brand)

        note = QLabel("以设备接入、现场诊断和高频采集为核心，协议细节只在需要时出现。")
        note.setObjectName("subtitle")
        note.setProperty("navRailNote", True)
        note.setWordWrap(True)
        note.setMaximumHeight(52)
        layout.addWidget(note)

        self.nav_mission_chip = QLabel("FIELD -> FLUX -> DELIVERY")
        self.nav_mission_chip.setProperty("navMissionChip", True)
        layout.addWidget(self.nav_mission_chip)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        pages = [
            ("device_center", "设备中心", "接入与配置"),
            ("realtime", "实时采集", "曲线与缓存"),
            ("project_site", "项目与站点", "归档与上下文"),
            ("ec_processing", "EC 处理", "流程与中间结果"),
            ("spectral_qc", "谱修正与 QC", "频谱与质量控制"),
            ("report_center", "报告中心", "结果与出口"),
        ]
        nav_phases = [
            ("01", "field"),
            ("02", "field"),
            ("03", "site"),
            ("04", "compute"),
            ("05", "compute"),
            ("06", "delivery"),
        ]
        for index, (key, title, subtitle) in enumerate(pages):
            number, phase = nav_phases[index]
            button = QPushButton(f"{number}  {title}\n{subtitle}")
            button.setProperty("navButton", True)
            button.setProperty("navRouteTile", True)
            button.setProperty("navPhase", phase)
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.setMaximumHeight(54)
            button.setToolTip(f"{title} | {subtitle}")
            button.clicked.connect(lambda checked, page_key=key: self._emit_page(page_key, checked))
            self._group.addButton(button, index)
            self._buttons[key] = button
            layout.addWidget(button)

        self.principle_footer = QFrame()
        self.principle_footer.setProperty("navPrincipleCard", True)
        self.principle_footer.setProperty("navPrincipleCompact", True)
        self.principle_footer.setMaximumHeight(118)
        footer_layout = QVBoxLayout(self.principle_footer)
        footer_layout.setContentsMargins(TOKENS.spacing_sm, TOKENS.spacing_xs, TOKENS.spacing_sm, TOKENS.spacing_xs)
        footer_layout.setSpacing(4)
        title = QLabel("视图原则")
        title.setObjectName("metricLabel")
        footer_layout.addWidget(title)
        for text in (
            "操作员先看状态，工程师再看细节",
            "方法、风险和中间结果同屏出现",
            "危险操作必须二次确认",
        ):
            item = QLabel(f"· {text}")
            item.setObjectName("subtitle")
            item.setWordWrap(True)
            item.setMaximumHeight(26)
            footer_layout.addWidget(item)
        layout.addWidget(self.principle_footer)
        layout.addStretch(1)

        self.select("device_center")

    def select(self, page_key: str) -> None:
        button = self._buttons.get(page_key)
        if button:
            button.setChecked(True)

    def _emit_page(self, page_key: str, checked: bool) -> None:
        if checked:
            self.page_changed.emit(page_key)
