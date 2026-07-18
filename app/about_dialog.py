from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.resources import application_icon, release_notes_text, user_guide_text
from app.version import DISPLAY_VERSION


ABOUT_TEXT = """
## Gas EC Studio

面向气体分析、现场采集、通量处理、质量复核和成果交付的独立桌面工作台。

**当前版本：** {version}

**主要工作区**

- 设备中心与实时采集
- 项目、站点和元数据管理
- EC 处理、谱修正与质量控制
- 报告、证据包和交付文件导出

用户数据默认保存在 `%LOCALAPPDATA%\\GasECStudio\\runtime_data`。发布包离线运行，不会自动上传项目数据。
"""


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setProperty("aboutDialog", True)
        self.setWindowTitle("关于 Gas EC Studio")
        self.setWindowIcon(application_icon())
        self.resize(720, 560)
        self.setMinimumSize(600, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        header = QWidget()
        header.setProperty("aboutHeader", True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)

        icon_label = QLabel()
        icon_label.setProperty("aboutIcon", True)
        icon_label.setFixedSize(58, 58)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(application_icon().pixmap(QSize(52, 52)))
        header_layout.addWidget(icon_label)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(3)
        title = QLabel("Gas EC Studio")
        title.setProperty("aboutTitle", True)
        subtitle = QLabel("气体分析与通量工程工作台")
        subtitle.setProperty("aboutSubtitle", True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)

        version = QLabel(DISPLAY_VERSION)
        version.setProperty("aboutVersionBadge", True)
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(version)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.about_browser = self._browser(ABOUT_TEXT.format(version=DISPLAY_VERSION))
        self.guide_browser = self._browser(user_guide_text())
        self.release_notes_browser = self._browser(release_notes_text())
        self.tabs.addTab(self.about_browser, "关于")
        self.tabs.addTab(self.guide_browser, "使用说明")
        self.tabs.addTab(self.release_notes_browser, "更新日志")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _browser(markdown: str) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setProperty("aboutText", True)
        browser.setOpenExternalLinks(False)
        browser.setMarkdown(markdown.strip())
        return browser
