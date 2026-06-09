from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.pages.device_center_page import DeviceCenterPage
from app.pages.device_detail_page import DeviceDetailPage
from app.pages.ec_processing_page import ECProcessingPage
from app.pages.project_site_page import ProjectSitePage
from app.pages.realtime_page import RealtimePage
from app.pages.report_center_page import ReportCenterPage
from app.pages.spectral_qc_page import SpectralQCPage
from app.studio import StudioController
from app.theme import CardFrame, TOKENS
from app.widgets.context_inspector import ContextInspector
from app.widgets.log_panel import LogPanel
from app.widgets.navigation import NavigationRail


class StudioMainWindow(QMainWindow):
    def __init__(self, controller: StudioController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Gas EC Studio")
        self.resize(1760, 1020)

        central = QWidget()
        central.setObjectName("appShell")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        root.setSpacing(TOKENS.spacing_md)

        self.header = self._build_header()
        root.addWidget(self.header)

        vertical = QSplitter(Qt.Vertical)
        vertical.setObjectName("shellVerticalSplitter")
        root.addWidget(vertical, 1)

        top_widget = QWidget()
        top_widget.setObjectName("mainDeck")
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(TOKENS.spacing_md)
        vertical.addWidget(top_widget)

        self.navigation = NavigationRail()
        self.navigation.page_changed.connect(self._set_page)
        top_layout.addWidget(self.navigation)

        inner_splitter = QSplitter(Qt.Horizontal)
        inner_splitter.setObjectName("shellInnerSplitter")
        top_layout.addWidget(inner_splitter, 1)

        self.stack = QStackedWidget()
        self.stack.setObjectName("workspaceStack")
        self.device_center_page = DeviceCenterPage(controller)
        self.device_detail_page = DeviceDetailPage(controller)
        self.realtime_page = RealtimePage(controller)
        self.project_site_page = ProjectSitePage(controller)
        self.ec_processing_page = ECProcessingPage(controller)
        self.spectral_qc_page = SpectralQCPage(controller)
        self.report_center_page = ReportCenterPage(controller)
        self.pages = {
            "device_center": self.device_center_page,
            "device_detail": self.device_detail_page,
            "realtime": self.realtime_page,
            "project_site": self.project_site_page,
            "ec_processing": self.ec_processing_page,
            "spectral_qc": self.spectral_qc_page,
            "report_center": self.report_center_page,
        }
        for key in ("device_center", "device_detail", "realtime", "project_site", "ec_processing", "spectral_qc", "report_center"):
            self.stack.addWidget(self.pages[key])
        inner_splitter.addWidget(self.stack)

        self.inspector = ContextInspector()
        inner_splitter.addWidget(self.inspector)
        inner_splitter.setSizes([1080, 360])

        self.log_panel = LogPanel()
        vertical.addWidget(self.log_panel)
        vertical.setSizes([820, 220])

        self.device_center_page.open_detail_requested.connect(self._open_device_detail)
        self.device_center_page.open_realtime_requested.connect(lambda: self._set_page("realtime"))
        self.device_detail_page.back_requested.connect(lambda: self._set_page("device_center"))
        self.device_detail_page.open_realtime_requested.connect(lambda: self._set_page("realtime"))

        self.controller.devices_changed.connect(self._refresh_shell)
        self.controller.selection_changed.connect(self._refresh_shell)
        self.controller.logs_changed.connect(self._refresh_shell)
        self.controller.events_changed.connect(self._refresh_shell)
        self.controller.view_mode_changed.connect(self._refresh_shell)
        self.controller.project_changed.connect(self._refresh_shell)
        self.controller.processing_changed.connect(self._refresh_shell)
        self.controller.spectral_qc_changed.connect(self._refresh_shell)
        self.controller.report_changed.connect(self._refresh_shell)
        self._set_page("device_center")
        self._refresh_shell()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.controller.shutdown()
        super().closeEvent(event)

    def _build_header(self) -> CardFrame:
        card = CardFrame(role="hero")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_lg, TOKENS.spacing_md, TOKENS.spacing_lg, TOKENS.spacing_md)
        layout.setSpacing(TOKENS.spacing_md)

        title_box = QVBoxLayout()
        title = QLabel("Gas EC Studio")
        title.setObjectName("pageTitle")
        subtitle = QLabel("独立的气体分析仪高端工程工作台，兼顾现场操作、协议诊断和高频采集。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.header_status = QLabel()
        self.header_status.setObjectName("subtitle")
        self.header_status.setProperty("heroStatus", True)
        self.header_status.setWordWrap(True)
        layout.addWidget(self.header_status)

        telemetry = QHBoxLayout()
        telemetry.setSpacing(TOKENS.spacing_sm)
        self.header_online_tile = self._header_tile("在线", "--")
        self.header_sampling_tile = self._header_tile("采集", "--")
        self.header_alarm_tile = self._header_tile("异常", "--")
        self.header_view_tile = self._header_tile("视图", "--")
        for tile in (
            self.header_online_tile,
            self.header_sampling_tile,
            self.header_alarm_tile,
            self.header_view_tile,
        ):
            telemetry.addWidget(tile)
        layout.addLayout(telemetry)

        group = QButtonGroup(card)
        self.operator_btn = QToolButton()
        self.operator_btn.setText("操作员视图")
        self.operator_btn.setProperty("viewSwitch", True)
        self.operator_btn.setCheckable(True)
        self.operator_btn.setChecked(True)
        self.operator_btn.clicked.connect(lambda: self.controller.set_view_mode("operator"))
        self.engineer_btn = QToolButton()
        self.engineer_btn.setText("工程师视图")
        self.engineer_btn.setProperty("viewSwitch", True)
        self.engineer_btn.setCheckable(True)
        self.engineer_btn.clicked.connect(lambda: self.controller.set_view_mode("engineer"))
        group.addButton(self.operator_btn)
        group.addButton(self.engineer_btn)
        layout.addWidget(self.operator_btn)
        layout.addWidget(self.engineer_btn)
        return card

    def _header_tile(self, label: str, value: str) -> QLabel:
        tile = QLabel(f"{label}\n{value}")
        tile.setProperty("shellTile", True)
        tile.setAlignment(Qt.AlignCenter)
        tile.setMinimumWidth(78)
        return tile

    def _set_header_tile(self, tile: QLabel, label: str, value: str, tone: str = "neutral") -> None:
        tile.setText(f"{label}\n{value}")
        tile.setProperty("shellTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def _set_page(self, page_key: str) -> None:
        mapping = {
            "device_center": 0,
            "device_detail": 1,
            "realtime": 2,
            "project_site": 3,
            "ec_processing": 4,
            "spectral_qc": 5,
            "report_center": 6,
        }
        self.stack.setCurrentIndex(mapping[page_key])
        if page_key == "device_detail":
            self.navigation.select("device_center")
        else:
            self.navigation.select(page_key)
        self.controller.set_selected_page(page_key)
        self._refresh_shell()

    def _open_device_detail(self, device_uid: str) -> None:
        self.controller.select_device(device_uid)
        self._set_page("device_detail")

    def _refresh_shell(self) -> None:
        summary = self.controller.status_summary()
        view_label = "操作员" if self.controller.view_mode == "operator" else "工程师"
        self.header_status.setText(
            f"在线 {summary['online_devices']} / {summary['total_devices']} 台 · "
            f"异常 {summary['abnormal_devices']} 台 · "
            f"采集中 {summary['sampling_devices']} 台 · "
            f"最近告警：{summary['recent_alarm']}"
        )
        alarm_tone = "success" if summary["abnormal_devices"] == 0 else "danger"
        sampling_tone = "success" if summary["sampling_devices"] > 0 else "warning"
        self._set_header_tile(self.header_online_tile, "在线", f"{summary['online_devices']}/{summary['total_devices']}", "success")
        self._set_header_tile(self.header_sampling_tile, "采集", str(summary["sampling_devices"]), sampling_tone)
        self._set_header_tile(self.header_alarm_tile, "异常", str(summary["abnormal_devices"]), alarm_tone)
        self._set_header_tile(self.header_view_tile, "视图", view_label, "accent")
        self.operator_btn.setChecked(self.controller.view_mode == "operator")
        self.engineer_btn.setChecked(self.controller.view_mode == "engineer")
        self.inspector.refresh(self.controller.context_snapshot())
        self.log_panel.set_lines(self.controller.log_lines())
