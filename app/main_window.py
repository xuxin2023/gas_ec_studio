from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.about_dialog import AboutDialog
from app.pages.device_center_page import DeviceCenterPage
from app.pages.device_detail_page import DeviceDetailPage
from app.pages.ec_processing_page import ECProcessingPage
from app.pages.project_site_page import ProjectSitePage
from app.pages.realtime_page import RealtimePage
from app.pages.report_center_page import ReportCenterPage
from app.pages.spectral_qc_page import SpectralQCPage
from app.resources import application_icon
from app.studio import StudioController
from app.theme import CardFrame, TOKENS
from app.widgets.context_inspector import ContextInspector
from app.widgets.log_panel import LogPanel
from app.widgets.navigation import NavigationRail


class AdaptiveStackedWidget(QStackedWidget):
    """Keep the shell responsive while pages manage their own dense content."""

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(940, 620)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(620, 420)


class StudioMainWindow(QMainWindow):
    def __init__(self, controller: StudioController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Gas EC Studio")
        self.setWindowIcon(application_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)
        self._compact_shell: bool | None = None
        self._inspector_visible: bool | None = None
        self._active_page_key = "device_center"
        self.about_dialog: AboutDialog | None = None
        self._embedded_inspector_pages = {"device_detail", "project_site", "ec_processing", "report_center"}
        self._route_context = {
            "device_center": ("field", "Field", "Device Center", "Connect instruments and verify live status"),
            "device_detail": ("field", "Field", "Device Detail", "Inspect one analyzer without leaving the field deck"),
            "realtime": ("field", "Field", "Realtime Capture", "Watch high-frequency acquisition and buffer health"),
            "project_site": ("site", "Site", "Project Metadata", "Lock station context before flux processing"),
            "ec_processing": ("compute", "Compute", "EC Processing", "Run flux, footprint, uncertainty and correction methods"),
            "spectral_qc": ("compute", "Compute", "Spectral QC", "Review cospectra, repair evidence and QC closure"),
            "report_center": ("delivery", "Deliver", "Report Center", "Package exports, manifests and audit evidence"),
        }

        central = QWidget()
        central.setObjectName("appShell")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md, TOKENS.spacing_md)
        root.setSpacing(TOKENS.spacing_md)

        self.header = self._build_header()
        root.addWidget(self.header)

        self.vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter.setObjectName("shellVerticalSplitter")
        self.vertical_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.vertical_splitter, 1)

        top_widget = QWidget()
        top_widget.setObjectName("mainDeck")
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(TOKENS.spacing_md)
        self.vertical_splitter.addWidget(top_widget)

        self.navigation = NavigationRail()
        self.navigation.page_changed.connect(self._set_page)
        top_layout.addWidget(self.navigation)

        self.inner_splitter = QSplitter(Qt.Horizontal)
        self.inner_splitter.setObjectName("shellInnerSplitter")
        self.inner_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        top_layout.addWidget(self.inner_splitter, 1)

        self.stack = AdaptiveStackedWidget()
        self.stack.setObjectName("workspaceStack")
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self.inner_splitter.addWidget(self.stack)

        self.inspector = ContextInspector()
        self.inner_splitter.addWidget(self.inspector)
        self.inner_splitter.setSizes([1000, 300])

        self.log_panel = LogPanel()
        self.vertical_splitter.addWidget(self.log_panel)
        self.vertical_splitter.setSizes([800, 44])

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
        self._apply_responsive_shell(force=True)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.controller.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_responsive_shell()

    def _build_header(self) -> CardFrame:
        card = CardFrame(role="hero")
        card.setProperty("shellHeroDock", True)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(TOKENS.spacing_md, TOKENS.spacing_sm, TOKENS.spacing_md, TOKENS.spacing_sm)
        layout.setSpacing(TOKENS.spacing_sm)

        title_holder = QWidget()
        title_holder.setProperty("shellBrandBlock", True)
        title_holder.setMaximumWidth(300)
        title_holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        brand_layout = QGridLayout(title_holder)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setHorizontalSpacing(TOKENS.spacing_sm)
        brand_layout.setVerticalSpacing(TOKENS.spacing_xs)
        self.brand_icon = QLabel()
        self.brand_icon.setProperty("shellBrandIcon", True)
        self.brand_icon.setFixedSize(30, 30)
        self.brand_icon.setAlignment(Qt.AlignCenter)
        self.brand_icon.setPixmap(self.windowIcon().pixmap(QSize(28, 28)))
        brand_layout.addWidget(self.brand_icon, 0, 0)
        title = QLabel("Gas EC Studio")
        title.setObjectName("pageTitle")
        subtitle = QLabel("独立的气体分析仪高端工程工作台，兼顾现场操作、协议诊断和高频采集。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        brand_layout.addWidget(title, 0, 1)
        brand_layout.addWidget(subtitle, 1, 0, 1, 2)
        brand_layout.setColumnStretch(1, 1)
        layout.addWidget(title_holder)

        self.route_cockpit = self._build_route_cockpit()
        layout.addWidget(self.route_cockpit)
        layout.addStretch(1)

        self.header_status = QLabel()
        self.header_status.setObjectName("subtitle")
        self.header_status.setProperty("heroStatus", True)
        self.header_status.setWordWrap(True)
        self.header_status.setMinimumWidth(0)
        self.header_status.setMaximumWidth(220)
        self.header_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.header_status)

        self.header_closure_strip = QWidget()
        self.header_closure_strip.setProperty("shellClosureStrip", True)
        self.header_closure_strip.setProperty("shellClosureBus", True)
        self.header_closure_strip.setMaximumWidth(304)
        closure_layout = QHBoxLayout(self.header_closure_strip)
        closure_layout.setContentsMargins(0, 0, 0, 0)
        closure_layout.setSpacing(4)
        self.header_closure_tiles = {
            "device": self._closure_stage("设备", "--"),
            "capture": self._closure_stage("采集", "--"),
            "rp": self._closure_stage("RP", "--"),
            "spectral": self._closure_stage("谱修正", "--"),
            "delivery": self._closure_stage("交付", "--"),
        }
        for tile in self.header_closure_tiles.values():
            closure_layout.addWidget(tile)
        layout.addWidget(self.header_closure_strip)

        self.header_telemetry_strip = QWidget()
        self.header_telemetry_strip.setProperty("shellTelemetryStrip", True)
        self.header_telemetry_strip.setMaximumWidth(246)
        telemetry = QHBoxLayout(self.header_telemetry_strip)
        telemetry.setContentsMargins(0, 0, 0, 0)
        telemetry.setSpacing(TOKENS.spacing_xs)
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
        layout.addWidget(self.header_telemetry_strip)

        group = QButtonGroup(card)
        self.operator_btn = QToolButton()
        self.operator_btn.setText("操作员视图")
        self.operator_btn.setProperty("viewSwitch", True)
        self.operator_btn.setProperty("shellModeToggle", True)
        self.operator_btn.setText("OP")
        self.operator_btn.setToolTip("Operator view")
        self.operator_btn.setCheckable(True)
        self.operator_btn.setChecked(True)
        self.operator_btn.clicked.connect(lambda: self.controller.set_view_mode("operator"))
        self.engineer_btn = QToolButton()
        self.engineer_btn.setText("工程师视图")
        self.engineer_btn.setProperty("viewSwitch", True)
        self.engineer_btn.setProperty("shellModeToggle", True)
        self.engineer_btn.setText("ENG")
        self.engineer_btn.setToolTip("Engineer view")
        self.engineer_btn.setCheckable(True)
        self.engineer_btn.clicked.connect(lambda: self.controller.set_view_mode("engineer"))
        for button in (self.operator_btn, self.engineer_btn):
            button.setMinimumWidth(0)
            button.setMaximumWidth(54)
            button.setMaximumHeight(54)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        group.addButton(self.operator_btn)
        group.addButton(self.engineer_btn)
        layout.addWidget(self.operator_btn)
        layout.addWidget(self.engineer_btn)

        self.about_btn = QToolButton()
        self.about_btn.setObjectName("aboutButton")
        self.about_btn.setProperty("shellAboutButton", True)
        self.about_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        self.about_btn.setIconSize(QSize(20, 20))
        self.about_btn.setToolTip("关于、使用说明与更新日志")
        self.about_btn.setAccessibleName("关于、使用说明与更新日志")
        self.about_btn.setFixedWidth(44)
        self.about_btn.setMaximumHeight(54)
        self.about_btn.clicked.connect(self._show_about_dialog)
        layout.addWidget(self.about_btn)
        return card

    def _show_about_dialog(self) -> None:
        if self.about_dialog is None:
            self.about_dialog = AboutDialog(self)
        self.about_dialog.show()
        self.about_dialog.raise_()
        self.about_dialog.activateWindow()

    def _build_route_cockpit(self) -> QWidget:
        cockpit = QWidget()
        cockpit.setProperty("shellRouteCockpit", True)
        cockpit.setMinimumWidth(280)
        cockpit.setMaximumWidth(330)
        cockpit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(cockpit)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        self.route_progress_label = QLabel("Field / Device Center")
        self.route_progress_label.setProperty("shellRouteProgress", True)
        self.route_progress_label.setMinimumWidth(0)
        self.route_progress_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.route_progress_label)

        strip = QWidget()
        strip.setProperty("shellRouteStrip", True)
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(4)
        self.route_stage_tiles: dict[str, QLabel] = {}
        for key, label in (("field", "FIELD"), ("site", "SITE"), ("compute", "COMPUTE"), ("delivery", "DELIVER")):
            tile = QLabel(label)
            tile.setAlignment(Qt.AlignCenter)
            tile.setProperty("shellRouteStep", True)
            tile.setProperty("routeTone", key)
            tile.setMinimumWidth(0)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            self.route_stage_tiles[key] = tile
            strip_layout.addWidget(tile)
        layout.addWidget(strip)
        return cockpit

    def _header_tile(self, label: str, value: str) -> QLabel:
        tile = QLabel(f"{label}\n{value}")
        tile.setProperty("shellTile", True)
        tile.setProperty("shellTelemetryTile", True)
        tile.setAlignment(Qt.AlignCenter)
        tile.setMinimumWidth(0)
        tile.setMaximumWidth(56)
        tile.setMaximumHeight(54)
        tile.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        return tile

    def _closure_stage(self, label: str, value: str) -> QLabel:
        tile = QLabel(f"{label}\n{value}")
        tile.setProperty("closureStage", True)
        tile.setProperty("closureBusNode", True)
        tile.setAlignment(Qt.AlignCenter)
        tile.setMinimumWidth(0)
        tile.setMaximumWidth(52)
        tile.setMaximumHeight(54)
        tile.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        return tile

    def _set_header_tile(self, tile: QLabel, label: str, value: str, tone: str = "neutral") -> None:
        tile.setText(f"{label}\n{value}")
        tile.setProperty("shellTone", tone)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def _set_closure_stage(self, key: str, label: str, value: str, tone: str = "neutral") -> None:
        tile = self.header_closure_tiles[key]
        tile.setText(f"{label}\n{value}")
        tile.setProperty("closureTone", tone)
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
        self._active_page_key = page_key
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
        self._refresh_closure_strip(summary)
        self.operator_btn.setChecked(self.controller.view_mode == "operator")
        self.engineer_btn.setChecked(self.controller.view_mode == "engineer")
        self.inspector.refresh(self.controller.context_snapshot())
        self.log_panel.set_lines(self.controller.log_lines())
        self._refresh_route_cockpit()
        self._apply_responsive_shell()

    def _apply_responsive_shell(self, force: bool = False) -> None:
        compact = self.width() < 1500
        inspector_visible = (not compact) and self._active_page_key not in self._embedded_inspector_pages
        if not force and compact == self._compact_shell and inspector_visible == self._inspector_visible:
            return
        self._compact_shell = compact
        self._inspector_visible = inspector_visible
        self.header_status.setVisible(not compact)
        self.navigation.principle_footer.setVisible(not compact)
        self.inspector.setVisible(inspector_visible)
        if not inspector_visible:
            self.inner_splitter.setSizes([1, 0])
            self.vertical_splitter.setSizes([650, 54])
        else:
            self.inner_splitter.setSizes([980, 300])
            self.vertical_splitter.setSizes([800, 54])

    def _refresh_route_cockpit(self) -> None:
        phase, phase_label, page_label, detail = self._route_context.get(
            self._active_page_key,
            self._route_context["device_center"],
        )
        self.route_progress_label.setText(f"{phase_label} / {page_label}")
        self.route_progress_label.setToolTip(detail)
        for key, tile in self.route_stage_tiles.items():
            tile.setProperty("routeActive", key == phase)
            tile.setProperty("routeTone", key)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        self.navigation.set_route_context(phase, page_label)

    def _refresh_closure_strip(self, summary: dict) -> None:
        if summary["online_devices"] <= 0:
            device_value, device_tone = "待接入", "warning"
        elif summary["abnormal_devices"] > 0:
            device_value, device_tone = "需处理", "danger"
        else:
            device_value, device_tone = "就绪", "success"

        capture_value = "采集中" if summary["sampling_devices"] > 0 else "待启动"
        capture_tone = "success" if summary["sampling_devices"] > 0 else "warning"

        rp_summary = self.controller.ec_processing_workspace.get("summary", {})
        rp_status = str(rp_summary.get("status", "")).lower()
        if rp_status in {"ok", "ready", "complete", "completed", "success"}:
            rp_value, rp_tone = "已闭合", "success"
        elif rp_status in {"empty", "", "not_run", "pending"}:
            rp_value, rp_tone = "待运行", "warning"
        else:
            rp_value, rp_tone = "需复核", "danger"

        spectral_run = self.controller.spectral_qc_workspace.get("run", {})
        spectral_summary = self.controller.spectral_qc_workspace.get("summary", {})
        spectral_status = str(spectral_run.get("last_result_status", "")).lower()
        spectral_windows = int(spectral_summary.get("qc_good_windows", 0) or 0) + int(
            spectral_summary.get("attention_windows", 0) or 0
        )
        if spectral_status in {"ok", "ready", "complete", "completed", "success"} or spectral_windows > 0:
            spectral_value, spectral_tone = "已分析", "success"
        elif spectral_status in {"error", "failed", "blocked"}:
            spectral_value, spectral_tone = "需复核", "danger"
        else:
            spectral_value, spectral_tone = "待分析", "warning"

        report_workspace = self.controller.report_center_workspace
        export_status = str(report_workspace.get("export_status", ""))
        export_status_key = export_status.lower()
        if export_status_key in {"exported", "ready", "delivered"} or any(marker in export_status for marker in ("已导出", "已交付")):
            delivery_value, delivery_tone = "已交付", "success"
        elif export_status_key in {"failed", "error", "blocked"}:
            delivery_value, delivery_tone = "需复核", "danger"
        else:
            delivery_value, delivery_tone = "待交付", "warning"

        self._set_closure_stage("device", "设备", device_value, device_tone)
        self._set_closure_stage("capture", "采集", capture_value, capture_tone)
        self._set_closure_stage("rp", "RP", rp_value, rp_tone)
        self._set_closure_stage("spectral", "谱修正", spectral_value, spectral_tone)
        self._set_closure_stage("delivery", "交付", delivery_value, delivery_tone)
