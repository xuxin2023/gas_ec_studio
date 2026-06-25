from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.studio import StudioController
from app.theme import CardFrame, TOKENS, apply_app_theme, build_stylesheet, configure_plot_theme, preferred_ui_font_family


def test_stylesheet_contains_instrument_cockpit_contract() -> None:
    stylesheet = build_stylesheet()

    assert "QWidget#appShell" in stylesheet
    assert "qlineargradient" in stylesheet
    assert 'QFrame#card[cardRole="hero"]' in stylesheet
    assert 'QFrame#card[cardRole="hero"][shellHeroDock="true"]' in stylesheet
    assert 'QFrame#card[cardRole="hero"] QLabel#pageTitle' in stylesheet
    assert 'QFrame#card[cardRole="hero"] QLabel#subtitle[heroStatus="true"]' in stylesheet
    assert 'QFrame#card[cardRole="command"]' in stylesheet
    assert 'QFrame#card[cardRole="cockpit"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="console"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][commandTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][evidenceTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][routeAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"][navRailWorkbench="true"]' in stylesheet
    assert 'QWidget[navBrandBlock="true"]' in stylesheet
    assert 'QLabel[navRailNote="true"]' in stylesheet
    assert 'QLabel[navMissionChip="true"]' in stylesheet
    assert 'QLabel[navMissionChip="true"][navMissionPhase="compute"]' in stylesheet
    assert 'QWidget[shellRouteCockpit="true"]' in stylesheet
    assert 'QLabel[shellRouteProgress="true"]' in stylesheet
    assert 'QWidget[shellRouteStrip="true"]' in stylesheet
    assert 'QLabel[shellRouteStep="true"]' in stylesheet
    assert 'QLabel[shellRouteStep="true"][routeActive="true"]' in stylesheet
    assert 'QLabel[shellTile="true"]' in stylesheet
    assert 'QWidget[shellTelemetryStrip="true"]' in stylesheet
    assert 'QLabel[shellTile="true"][shellTelemetryTile="true"]' in stylesheet
    assert 'QWidget[shellClosureStrip="true"]' in stylesheet
    assert 'QWidget[shellClosureStrip="true"][shellClosureBus="true"]' in stylesheet
    assert 'QLabel[closureStage="true"]' in stylesheet
    assert 'QLabel[closureStage="true"][closureBusNode="true"]' in stylesheet
    assert 'QLabel[closureStage="true"][closureTone="accent"]' in stylesheet
    assert 'QPushButton[navButton="true"]' in stylesheet
    assert 'QPushButton[navButton="true"][navRouteTile="true"]' in stylesheet
    assert 'QPushButton[navButton="true"][navRouteTile="true"][navPhase="compute"]' in stylesheet
    assert 'QFrame[navPrincipleCard="true"][navPrincipleCompact="true"]' in stylesheet
    assert 'QToolButton[viewSwitch="true"]' in stylesheet
    assert 'QToolButton[shellModeToggle="true"]' in stylesheet
    assert 'QToolButton[shellModeToggle="true"]:checked' in stylesheet
    assert 'QToolButton[previewPaneSwitch="true"]' in stylesheet
    assert 'QToolButton[previewPaneSwitch="true"]:checked' in stylesheet
    assert 'QToolButton[methodShortcut="true"]' in stylesheet
    assert 'QToolButton[methodShortcut="true"]:checked' in stylesheet
    assert 'QToolButton[methodTaskSwitch="true"]' in stylesheet
    assert 'QToolButton[methodTaskSwitch="true"]:checked' in stylesheet
    assert 'QFrame#cardMuted[methodConsoleCompact="true"]' in stylesheet
    assert 'QWidget[methodStateMirror="true"]' in stylesheet
    assert 'QFrame#cardMuted[methodConsoleTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[methodConsoleTile="true"][methodTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[methodConsoleTile="true"][methodTone="warning"]' in stylesheet
    assert 'QFrame#cardMuted[methodConsoleTile="true"][methodTone="danger"]' in stylesheet
    assert 'QLabel[chipTone="accent"][spectralCommandChip="true"]' in stylesheet
    assert 'QWidget[spectralCommandDeck="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralStatusDock="true"][spectralHeaderStatus="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralFocusRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralFocusTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralFocusNextCard="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralFocusNextCard="true"][railTone="warning"]' in stylesheet
    assert 'QToolButton[spectralFocusAction="true"]' in stylesheet
    assert 'QToolButton[windowConsoleSwitch="true"]' in stylesheet
    assert 'QToolButton[windowConsoleSwitch="true"]:checked' in stylesheet
    assert 'QToolButton[closureModeSwitch="true"]' in stylesheet
    assert 'QToolButton[closureModeSwitch="true"]:checked' in stylesheet
    assert 'QComboBox[runRibbonField="true"]' in stylesheet
    assert 'QPushButton[runRibbonAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[closureCompactTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="rail"] QToolButton[viewSwitch="true"]:checked' in stylesheet
    assert 'QFrame#card[cardRole="command"] QToolButton[viewSwitch="true"]:checked' in stylesheet
    assert 'QLabel[methodFieldLabel="true"]' in stylesheet
    assert 'QLabel[methodGroupPill="true"]' in stylesheet
    assert 'QComboBox[methodFieldInput="true"]' in stylesheet
    assert 'QDoubleSpinBox[methodFieldInput="true"]' in stylesheet
    assert 'QWidget[methodFamilyControlStrip="true"]' in stylesheet
    assert 'QFrame#cardMuted[methodFamilyControlTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[methodFamilyControlTile="true"][summaryKey="recommended"]' in stylesheet
    assert 'QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="warning"]' in stylesheet
    assert 'QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="danger"]' in stylesheet
    assert 'QFrame#cardMuted[ecMethodShortcutDeck="true"]' in stylesheet
    assert 'QLabel[methodShortcutValue="true"]' in stylesheet
    assert 'QToolButton[methodShortcut="true"][methodTone="warning"]' in stylesheet
    assert 'QToolButton[methodShortcut="true"][activeMethodShortcut="true"]' in stylesheet
    assert 'QFrame#cardMuted[ecProcessRail="true"]' in stylesheet
    assert 'QWidget[stepPhaseMap="true"]' in stylesheet
    assert 'QToolButton[stepPhaseTile="true"]' in stylesheet
    assert 'QToolButton[stepPhaseTile="true"][phaseTone="success"]' in stylesheet
    assert 'QToolButton[stepPhaseTile="true"][phaseTone="warning"]' in stylesheet
    assert 'QToolButton[stepPhaseTile="true"][phaseTone="danger"]' in stylesheet
    assert 'QFrame#cardMuted[logPanelCompactDock="true"]' in stylesheet
    assert 'QLabel[logLatestLine="true"]' in stylesheet
    assert 'QToolButton[logPanelAction="true"]' in stylesheet
    assert 'QFrame#card[runCommandDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[runMissionStrip="true"]' in stylesheet
    assert 'QLabel[runMissionLabel="true"]' in stylesheet
    assert 'QLabel[runMissionValue="true"]' in stylesheet
    assert 'QLabel[runMissionText="true"]' in stylesheet
    assert 'QFrame#card[spectralRunCommandDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralSourceDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralActionDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralStatusDock="true"]' in stylesheet
    assert 'QWidget[spectralSummaryInline="true"]' in stylesheet
    assert 'QFrame#cardMuted[spectralSummaryMetric="true"]' in stylesheet
    assert 'QToolButton[railAction="true"]' in stylesheet
    assert 'QToolButton[railAction="true"][actionTone="danger"]' in stylesheet
    assert 'QToolButton[railMissionAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[railMissionTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[stepCommandDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[stepCommandTile="true"]' in stylesheet
    assert 'QToolButton[stepCommandAction="true"]' in stylesheet
    assert 'QFrame#card[reportPreviewHeaderDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewCommandDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewCommandTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryStatusRadar="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryStatusRadarCell="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryStatusRadarCell="true"] QLabel#metricValue[compactMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportCommandSummary="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportCommandSummary="true"][commandStatus="success"]' in stylesheet
    assert 'QLabel[reportCommandNextNote="true"]' in stylesheet
    assert 'QWidget[deliveryClosureStrip="true"]' in stylesheet
    assert 'QWidget[deliveryClosureStrip="true"][deliveryClosureMatrix="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryClosureTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryClosureTile="true"][commandGroup="artifact"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryClosureTile="true"][commandGroup="validation"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryClosureTile="true"][commandTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryClosureTile="true"] QLabel#metricValue[compactMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[cardRole="tile"][radarTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewWorkbench="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewAnalysisStrip="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="plot"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="table"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="insight"]' in stylesheet
    assert 'QLabel[reportPreviewAnalysisHint="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewWorkbenchBridge="true"]' in stylesheet
    assert 'QToolButton[previewWorkbenchSegment="true"]' in stylesheet
    assert 'QToolButton[previewWorkbenchSegment="true"][workbenchTone="success"]' in stylesheet
    assert 'QToolButton[previewWorkbenchSegment="true"][workbenchTone="accent"]' in stylesheet
    assert 'QToolButton[previewWorkbenchSegment="true"][workbenchTone="warning"]' in stylesheet
    assert 'QToolButton[previewWorkbenchSegment="true"][activeWorkbenchSegment="true"]' in stylesheet
    assert 'QWidget[reportPreviewMetricStrip="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportActionDrawer="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportActionDrawer="true"][actionTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[reportActionDrawer="true"][actionTone="accent"]' in stylesheet
    assert 'QFrame#cardMuted[reportActionDrawer="true"][actionTone="warning"]' in stylesheet
    assert 'QFrame#cardMuted[previewWorkflowRoute="true"]' in stylesheet
    assert 'QLabel[previewRouteTitle="true"]' in stylesheet
    assert 'QWidget[previewRouteButtonRow="true"]' in stylesheet
    assert 'QToolButton[previewWorkflowRouteButton="true"]' in stylesheet
    assert 'QToolButton[reportActionDrawerButton="true"]' in stylesheet
    assert 'QSplitter#reportPreviewSplitPane' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewPrimaryPane="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewContextPane="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportPreviewContextPane="true"][reportPreviewEvidenceRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewEvidenceSummary="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewEvidenceSummary="true"][evidenceTone="success"]' in stylesheet
    assert 'QLabel[previewEvidenceNote="true"]' in stylesheet
    assert 'QWidget[previewEvidenceStatusRow="true"]' in stylesheet
    assert 'QLabel[previewEvidenceStatusChip="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewContextTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewContextTile="true"][previewEvidenceTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewContextTile="true"][contextTone="success"]' in stylesheet
    assert 'QToolButton[previewContextAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[previewTrailStrip="true"]' in stylesheet
    assert 'QLabel[previewTrailLabel="true"]' in stylesheet
    assert 'QToolButton[previewCommandAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportNavRail="true"]' in stylesheet
    assert 'QTreeWidget#workflowTree[reportNavTree="true"]' in stylesheet
    assert 'QWidget[reportNavPhaseStrip="true"]' in stylesheet
    assert 'QToolButton[reportNavPhaseButton="true"]' in stylesheet
    assert 'QToolButton[reportNavPhaseButton="true"][activePhase="true"]' in stylesheet
    assert 'QLabel[reportNavStageNote="true"]' in stylesheet
    assert 'QFrame#cardMuted[reportNavTaskMap="true"]' in stylesheet
    assert 'QLabel[reportNavTaskValue="true"]' in stylesheet
    assert 'QLabel[reportNavTaskStep="true"][activeTaskStep="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryMissionRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryMissionRail="true"][desktopMissionRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailConsole="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailConsole="true"][railTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailConsole="true"][railTone="accent"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailConsole="true"][railTone="warning"]' in stylesheet
    assert 'QWidget[deliveryRailModeDock="true"]' in stylesheet
    assert 'QToolButton[deliveryRailModeSwitch="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryCockpitBridge="true"]' in stylesheet
    assert 'QToolButton[deliveryBridgeSegment="true"]' in stylesheet
    assert 'QToolButton[deliveryBridgeSegment="true"][bridgeTone="success"]' in stylesheet
    assert 'QToolButton[deliveryBridgeSegment="true"][bridgeTone="accent"]' in stylesheet
    assert 'QToolButton[deliveryBridgeSegment="true"][bridgeTone="warning"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailActionDock="true"][deliveryRailActionMatrix="true"]' in stylesheet
    assert 'QToolButton[deliveryRailAction="true"][actionTone="success"]' in stylesheet
    assert 'QToolButton[deliveryRailAction="true"][actionTone="accent"]' in stylesheet
    assert 'QToolButton[deliveryRailAction="true"][actionTone="warning"]' in stylesheet
    assert 'QToolButton[deliveryRailAction="true"][actionTone="danger"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryMissionMap="true"]' in stylesheet
    assert 'QToolButton[deliveryMissionNode="true"]' in stylesheet
    assert 'QToolButton[deliveryMissionNode="true"][missionTone="success"]' in stylesheet
    assert 'QToolButton[deliveryMissionNode="true"][missionTone="warning"]' in stylesheet
    assert 'QToolButton[deliveryMissionNode="true"]:checked' in stylesheet
    assert 'QFrame#card[deliveryMissionInspector="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryFocusShell="true"]' in stylesheet
    assert 'QFrame#card[deliveryGateCompact="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateHero="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateHero="true"][deliveryGateLayer="summary"]' in stylesheet
    assert 'QWidget[deliveryGateLayeredMatrix="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateLayerTile="true"][deliveryGateGroup="artifact"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateLayerTile="true"][deliveryGateGroup="validation"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="accent"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="warning"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateTile="true"] QLabel#chip' in stylesheet
    assert 'QFrame#cardMuted[deliveryGateTile="true"] QLabel#metricValue[compactMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryDetailShell="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryBatchPanel="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryInspectorSection="true"]' in stylesheet
    assert 'QFrame#cardMuted[batchMetricTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deliveryRailActionDock="true"]' in stylesheet
    assert 'QToolButton[deliveryRailAction="true"]' in stylesheet
    assert 'QFrame#card[projectSiteCommandDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[projectSiteMetric="true"]' in stylesheet
    assert 'QPushButton[projectSiteCommandButton="true"]' in stylesheet
    assert 'QFrame#cardMuted[projectSiteOpsRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[projectSiteActionDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[projectSiteOpsTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[projectSiteNextCard="true"]' in stylesheet
    assert 'QToolButton[projectSiteRailAction="true"]' in stylesheet
    assert 'QFrame#card[metadataEditorShell="true"]' in stylesheet
    assert 'QWidget[metadataPanelSwitch="true"]' in stylesheet
    assert 'QToolButton[metadataPanelSwitchButton="true"]' in stylesheet
    assert 'QStackedWidget[metadataEditorStack="true"]' in stylesheet
    assert 'QFrame#card[metadataCockpitDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[metadataSummaryTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[metadataEditorPanel="true"]' in stylesheet
    assert 'QFrame#card[metadataProfileDock="true"]' in stylesheet
    assert 'QPushButton[metadataActionButton="true"]' in stylesheet
    assert 'QFrame#card[realtimeCommandDock="true"]' in stylesheet
    assert 'QFrame#card[realtimeCommandDock="true"][realtimeCaptureConsole="true"]' in stylesheet
    assert 'QLabel[captureConsoleTitle="true"]' in stylesheet
    assert 'QLabel[captureConsoleSubtitle="true"]' in stylesheet
    assert 'QLabel#chip[captureConsoleChip="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeTargetDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeMetricDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeActionDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeStatusDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[captureConsoleCell="true"]' in stylesheet
    assert 'QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="target"]' in stylesheet
    assert 'QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="signal"]' in stylesheet
    assert 'QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="command"]' in stylesheet
    assert 'QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="link"]' in stylesheet
    assert 'QLabel[captureStageTag="true"]' in stylesheet
    assert 'QWidget[captureMetricStrip="true"]' in stylesheet
    assert 'QToolButton[realtimeMetricToggle="true"]' in stylesheet
    assert 'QToolButton[realtimeActionButton="true"]' in stylesheet
    assert 'QToolButton[realtimeActionButton="true"][capturePrimaryAction="true"]' in stylesheet
    assert 'QToolButton[realtimeActionButton="true"][captureDangerAction="true"]' in stylesheet
    assert 'QToolButton[realtimeActionButton="true"][captureSecondaryAction="true"]' in stylesheet
    assert 'QFrame#card[realtimeSummaryDock="true"]' in stylesheet
    assert 'QFrame#card[realtimeSummaryDock="true"][realtimeTelemetryRibbon="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeSessionTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeSummaryMetric="true"]' in stylesheet
    assert 'QFrame#card[realtimePlotPanel="true"]' in stylesheet
    assert 'QFrame#card[realtimePlotPanel="true"][realtimeSignalScope="true"]' in stylesheet
    assert 'QLabel[realtimeScopeReadout="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeEvidenceRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[realtimeEvidenceRail="true"][realtimeEvidenceConsole="true"]' in stylesheet
    assert 'QFrame#card[deviceDetailHeaderDock="true"]' in stylesheet
    assert 'QPushButton[deviceDetailHeaderButton="true"]' in stylesheet
    assert 'QToolButton[deviceDetailViewSwitch="true"]' in stylesheet
    assert 'QFrame#card[deviceDetailSummaryDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceDetailSummaryMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceOpsRail="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceOpsActionDock="true"]' in stylesheet
    assert 'QToolButton[deviceOpsRailAction="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceOpsTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceOpsNextCard="true"]' in stylesheet
    assert 'QFrame#card[deviceFleetStatusDock="true"]' in stylesheet
    assert 'QFrame#card[deviceFleetStatusDock="true"][deviceFleetTelemetryStrip="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceFleetMetric="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceFleetMetric="true"][deviceFleetMetricKey="recent_alarm"]' in stylesheet
    assert 'QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="danger"]' in stylesheet
    assert 'QLabel[fleetMetricLabel="true"]' in stylesheet
    assert 'QLabel[fleetMetricValue="true"]' in stylesheet
    assert 'QFrame#card[fieldReadinessDock="true"]' in stylesheet
    assert 'QFrame#cardMuted[fieldReadinessTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[fieldActionDock="true"]' in stylesheet
    assert 'QToolButton[fieldActionButton="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceOperationsCompactInspector="true"]' in stylesheet
    assert 'QToolButton[deviceInspectorModeSwitch="true"]' in stylesheet
    assert 'QToolButton[deviceInspectorModeSwitch="true"]:checked' in stylesheet
    assert 'QStackedWidget[deviceInspectorStack="true"]' in stylesheet
    assert 'QFrame[deviceInspectorSection="true"][deviceInspectorSectionRole="mission"]' in stylesheet
    assert 'QFrame[deviceInspectorSection="true"][deviceInspectorSectionRole="activity"]' in stylesheet
    assert 'QFrame#cardMuted[deviceMissionTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceMissionTile="true"][missionTone="success"]' in stylesheet
    assert 'QFrame#cardMuted[deviceMissionTile="true"][activeMissionStage="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceEvidenceTile="true"]' in stylesheet
    assert 'QFrame#cardMuted[deviceEvidenceTile="true"][evidenceTone="success"]' in stylesheet
    assert 'QLabel[deviceEvidenceLabel="true"]' in stylesheet
    assert 'QLabel[deviceEvidenceValue="true"]' in stylesheet
    assert 'QTableWidget[deviceInspectorActivityTable="true"]' in stylesheet
    assert 'QListWidget[deviceInspectorEventList="true"]' in stylesheet
    assert 'QPushButton[variant="danger"]' in stylesheet and "#fff1f1" in stylesheet
    assert "QTreeWidget#workflowTree" in stylesheet
    assert "QPlainTextEdit" in stylesheet
    assert "EddyPro" not in stylesheet
    assert "eddypro" not in stylesheet


def test_apply_app_theme_registers_desktop_font_family() -> None:
    app = QApplication.instance() or QApplication([])

    apply_app_theme(app)

    family = preferred_ui_font_family()
    assert family
    assert app.font().family() == family
    if QFontDatabase.families():
        assert family in QFontDatabase.families()


def test_card_frame_exposes_role_for_stylesheet() -> None:
    card = CardFrame(role="hero")

    assert card.objectName() == "card"
    assert card.property("cardRole") == "hero"
    assert card.graphicsEffect() is not None


def test_configure_plot_theme_applies_plot_contract() -> None:
    class FakeAxis:
        def __init__(self) -> None:
            self.text_pen = None
            self.pen = None
            self.style = {}

        def setTextPen(self, value: str) -> None:  # noqa: N802
            self.text_pen = value

        def setPen(self, value: str) -> None:  # noqa: N802
            self.pen = value

        def setStyle(self, **kwargs) -> None:  # noqa: N802
            self.style.update(kwargs)

    class FakeViewBox:
        def __init__(self) -> None:
            self.default_padding = None
            self.mouse_enabled = None

        def setDefaultPadding(self, value: float) -> None:  # noqa: N802
            self.default_padding = value

        def setMouseEnabled(self, *, x: bool, y: bool) -> None:  # noqa: N802
            self.mouse_enabled = (x, y)

    class FakePlot:
        def __init__(self) -> None:
            self.background = None
            self.grid = None
            self.labels = {}
            self.hidden_axes = []
            self.menu_enabled = None
            self.axes = {"left": FakeAxis(), "bottom": FakeAxis()}
            self.view_box = FakeViewBox()

        def setBackground(self, value: str) -> None:  # noqa: N802
            self.background = value

        def showGrid(self, *, x: bool, y: bool, alpha: float) -> None:  # noqa: N802
            self.grid = (x, y, alpha)

        def setLabel(self, axis: str, label: str) -> None:  # noqa: N802
            self.labels[axis] = label

        def hideAxis(self, axis: str) -> None:  # noqa: N802
            self.hidden_axes.append(axis)

        def getAxis(self, axis: str) -> FakeAxis:  # noqa: N802
            return self.axes[axis]

        def setMenuEnabled(self, enabled: bool) -> None:  # noqa: N802
            self.menu_enabled = enabled

        def getViewBox(self) -> FakeViewBox:  # noqa: N802
            return self.view_box

    plot = FakePlot()

    configure_plot_theme(plot, left_label="CO2", bottom_label="time", show_bottom=False)

    assert plot.background == "transparent"
    assert plot.grid == (True, True, 0.13)
    assert plot.labels["left"] == "CO2"
    assert "bottom" not in plot.labels
    assert plot.hidden_axes == ["bottom"]
    assert plot.axes["left"].text_pen == TOKENS.color_text_muted
    assert plot.axes["bottom"].pen == TOKENS.color_border
    assert plot.menu_enabled is False
    assert plot.view_box.default_padding == 0.04
    assert plot.view_box.mouse_enabled == (True, True)


def test_main_window_wires_theme_semantics() -> None:
    app = QApplication.instance() or QApplication([])
    apply_app_theme(app)
    controller = StudioController()
    window = StudioMainWindow(controller)

    assert window.centralWidget().objectName() == "appShell"
    assert window.header.property("cardRole") == "hero"
    assert window.header.property("shellHeroDock") is True
    assert window.header_status.property("heroStatus") is True
    assert window.route_cockpit.property("shellRouteCockpit") is True
    assert window.route_progress_label.property("shellRouteProgress") is True
    assert set(window.route_stage_tiles) == {"field", "site", "compute", "delivery"}
    assert all(tile.property("shellRouteStep") is True for tile in window.route_stage_tiles.values())
    assert window.route_stage_tiles["field"].property("routeActive") is True
    assert window.navigation.nav_mission_chip.property("navMissionPhase") == "field"
    assert window.navigation.property("cardRole") == "rail"
    assert window.navigation.property("navRailWorkbench") is True
    assert window.navigation.nav_mission_chip.property("navMissionChip") is True
    assert window.navigation.principle_footer.property("navPrincipleCard") is True
    assert window.navigation.principle_footer.property("navPrincipleCompact") is True
    assert window.navigation.principle_footer.maximumHeight() == 118
    assert window.inspector.property("cardRole") == "rail"
    assert window.log_panel.property("cardRole") == "console"
    assert window.log_panel.property("logPanelCompactDock") is True
    assert window.log_panel._expanded is False
    assert window.log_panel.editor.isHidden() is True
    assert window.log_panel.latest_line.isHidden() is False
    assert window.log_panel.latest_line.property("logLatestLine") is True
    assert window.log_panel.toggle_button.property("logPanelAction") is True
    assert window.log_panel.clear_button.property("logPanelAction") is True
    assert window.log_panel.maximumHeight() == 44
    assert window.log_panel.toggle_button.text() == "展开"
    assert window.log_panel.log_count_chip.text().endswith("条")
    window.log_panel.set_lines(["first", "second"])
    assert window.log_panel.log_count_chip.text() == "2 条"
    assert window.log_panel.latest_line.text() == "first"
    assert window.log_panel.latest_line.toolTip() == "first"
    window.log_panel.clear()
    assert window.log_panel.log_count_chip.text() == "0 条"
    assert window.log_panel.latest_line.text() == "暂无日志。"
    assert window.header_online_tile.property("shellTile") is True
    assert window.header_online_tile.property("shellTelemetryTile") is True
    assert window.header_telemetry_strip.property("shellTelemetryStrip") is True
    assert window.header_alarm_tile.property("shellTone") in {"success", "danger"}
    assert window.header_closure_strip.property("shellClosureStrip") is True
    assert window.header_closure_strip.property("shellClosureBus") is True
    assert set(window.header_closure_tiles) == {"device", "capture", "rp", "spectral", "delivery"}
    assert all(tile.property("closureStage") is True for tile in window.header_closure_tiles.values())
    assert all(tile.property("closureBusNode") is True for tile in window.header_closure_tiles.values())
    assert window.header_closure_tiles["rp"].text() == "RP\n待运行"
    assert window.header_closure_tiles["delivery"].text() == "交付\n待交付"
    assert window.operator_btn.property("viewSwitch") is True
    assert window.engineer_btn.property("viewSwitch") is True
    assert window.operator_btn.property("shellModeToggle") is True
    assert window.engineer_btn.property("shellModeToggle") is True
    assert all(button.property("navButton") is True for button in window.navigation._buttons.values())
    assert all(button.property("navRouteTile") is True for button in window.navigation._buttons.values())
    assert window.navigation._buttons["device_center"].property("navPhase") == "field"
    assert window.navigation._buttons["ec_processing"].property("navPhase") == "compute"
    assert window.navigation._buttons["report_center"].property("navPhase") == "delivery"

    window._set_page("ec_processing")
    assert window.route_stage_tiles["compute"].property("routeActive") is True
    assert window.navigation.nav_mission_chip.property("navMissionPhase") == "compute"
    assert window.route_progress_label.text() == "Compute / EC Processing"

    window._set_page("report_center")
    assert window.route_stage_tiles["delivery"].property("routeActive") is True
    assert window.navigation.nav_mission_chip.property("navMissionPhase") == "delivery"
    assert window.route_progress_label.text() == "Deliver / Report Center"

    controller.ec_processing_workspace["summary"]["status"] = "ok"
    controller.spectral_qc_workspace["run"]["last_result_status"] = "ok"
    controller.report_center_workspace["export_status"] = "exported"
    window._refresh_shell()
    assert window.header_closure_tiles["rp"].text() == "RP\n已闭合"
    assert window.header_closure_tiles["spectral"].text() == "谱修正\n已分析"
    assert window.header_closure_tiles["delivery"].text() == "交付\n已交付"

    window.log_panel.set_expanded(True)
    assert window.log_panel._expanded is True
    assert window.log_panel.editor.isHidden() is False
    assert window.log_panel.latest_line.isHidden() is True
    assert window.log_panel.maximumHeight() == 260

    window.close()
    controller.shutdown()
