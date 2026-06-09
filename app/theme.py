from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget


@dataclass(frozen=True, slots=True)
class DesignTokens:
    font_family_ui: str = "'Microsoft YaHei UI', 'Aptos', 'Segoe UI', sans-serif"
    font_family_display: str = "'Microsoft YaHei UI', 'Aptos Display', 'Bahnschrift', sans-serif"
    font_family_mono: str = "'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace"
    spacing_xs: int = 6
    spacing_sm: int = 10
    spacing_md: int = 16
    spacing_lg: int = 24
    spacing_xl: int = 32
    radius_sm: int = 10
    radius_md: int = 16
    radius_lg: int = 22
    font_xs: int = 11
    font_sm: int = 12
    font_md: int = 14
    font_lg: int = 18
    font_xl: int = 26
    color_bg: str = "#eef4f8"
    color_bg_deep: str = "#dbe8ef"
    color_surface: str = "#ffffff"
    color_surface_soft: str = "#f8fbff"
    color_surface_warm: str = "#fffdf8"
    color_border: str = "#ccdae6"
    color_border_strong: str = "#9bb2c5"
    color_text: str = "#102232"
    color_text_muted: str = "#587083"
    color_accent: str = "#0f6c81"
    color_accent_hover: str = "#0b5c6f"
    color_accent_soft: str = "#dff3f7"
    color_success: str = "#19784c"
    color_warning: str = "#a86612"
    color_error: str = "#ba2f2b"
    color_copper: str = "#b66b1d"
    color_chip_neutral: str = "#e4edf3"
    color_chip_text: str = "#25384a"
    shadow_soft: str = "rgba(15, 35, 52, 0.11)"


TOKENS = DesignTokens()

PLOT_SERIES_COLORS = {
    "primary": TOKENS.color_accent,
    "secondary": "#3c8f6f",
    "muted": "#8fa2b2",
    "warning": TOKENS.color_copper,
    "danger": TOKENS.color_error,
    "violet": "#6b5aa8",
    "slate": "#475569",
}


def build_stylesheet() -> str:
    return f"""
    * {{
        font-family: {TOKENS.font_family_ui};
        color: {TOKENS.color_text};
        font-size: {TOKENS.font_sm}px;
    }}
    QWidget {{
        background: transparent;
    }}
    QMainWindow {{
        background: {TOKENS.color_bg};
    }}
    QWidget#appShell {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f7fbfd,
            stop: 0.42 {TOKENS.color_bg},
            stop: 1 {TOKENS.color_bg_deep}
        );
    }}
    QFrame#card {{
        background: {TOKENS.color_surface};
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
    }}
    QFrame#cardMuted {{
        background: {TOKENS.color_surface_soft};
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
    }}
    QFrame#card[cardRole="hero"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 0.54 #f5fbfd,
            stop: 1 #edf8f4
        );
        border: 1px solid #bfd8df;
    }}
    QFrame#card[cardRole="panel"] {{
        background: {TOKENS.color_surface_warm};
    }}
    QFrame#card[cardRole="command"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 0.62 #f7fbfd,
            stop: 1 #e7f5f2
        );
        border: 1px solid #bfd8df;
    }}
    QFrame#card[cardRole="cockpit"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fffdf8,
            stop: 0.55 #ffffff,
            stop: 1 #eff8f4
        );
        border: 1px solid #d4e2d8;
    }}
    QFrame#cardMuted[cardRole="tile"] {{
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid #d7e4eb;
        border-radius: {TOKENS.radius_md}px;
    }}
    QLabel#pageTitle {{
        font-family: {TOKENS.font_family_display};
        font-size: {TOKENS.font_xl}px;
        font-weight: 800;
        color: {TOKENS.color_text};
    }}
    QLabel#sectionTitle {{
        font-family: {TOKENS.font_family_display};
        font-size: {TOKENS.font_lg}px;
        font-weight: 700;
        color: {TOKENS.color_text};
    }}
    QLabel#subtitle {{
        color: {TOKENS.color_text_muted};
        font-size: {TOKENS.font_sm}px;
    }}
    QLabel#metricValue {{
        font-size: 22px;
        font-weight: 800;
        color: {TOKENS.color_text};
    }}
    QLabel#metricLabel {{
        color: {TOKENS.color_text_muted};
        font-size: {TOKENS.font_xs}px;
        letter-spacing: 0.5px;
        font-weight: 700;
    }}
    QLabel[heroStatus="true"] {{
        min-width: 340px;
        padding: 10px 14px;
        border-radius: {TOKENS.radius_md}px;
        background: rgba(255, 255, 255, 0.68);
        border: 1px solid #d2e4eb;
        color: {TOKENS.color_text_muted};
    }}
    QLabel#chip {{
        border-radius: {TOKENS.radius_sm}px;
        padding: 4px 10px;
        background: {TOKENS.color_chip_neutral};
        color: {TOKENS.color_chip_text};
        font-size: {TOKENS.font_xs}px;
        font-weight: 600;
    }}
    QLabel[chipTone="accent"] {{
        background: {TOKENS.color_accent_soft};
        color: {TOKENS.color_accent};
    }}
    QLabel[chipTone="success"] {{
        background: #e7f7ee;
        color: {TOKENS.color_success};
    }}
    QLabel[chipTone="warning"] {{
        background: #fff4df;
        color: {TOKENS.color_warning};
    }}
    QLabel[chipTone="danger"] {{
        background: #fde8e8;
        color: {TOKENS.color_error};
    }}
    QPushButton {{
        min-height: 36px;
        padding: 0 14px;
        border-radius: {TOKENS.radius_sm}px;
        border: 1px solid {TOKENS.color_border};
        background: {TOKENS.color_surface};
        color: {TOKENS.color_text};
        font-weight: 600;
    }}
    QPushButton:hover {{
        border-color: {TOKENS.color_border_strong};
        background: #fcfdff;
    }}
    QPushButton:pressed {{
        background: #eef5f8;
    }}
    QPushButton:disabled {{
        color: #98a8b6;
        background: #eef3f6;
        border-color: #dde7ee;
    }}
    QPushButton[variant="primary"] {{
        background: {TOKENS.color_accent};
        color: white;
        border: 1px solid {TOKENS.color_accent};
    }}
    QPushButton[variant="primary"]:hover {{
        background: {TOKENS.color_accent_hover};
        border-color: {TOKENS.color_accent_hover};
    }}
    QPushButton[variant="danger"] {{
        background: #fff5f5;
        color: {TOKENS.color_error};
        border: 1px solid #f3c6c6;
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
    }}
    QPushButton[navButton="true"] {{
        min-height: 58px;
        padding: 8px 12px;
        text-align: left;
        border-radius: {TOKENS.radius_md}px;
        background: transparent;
        border: 1px solid transparent;
        color: {TOKENS.color_text_muted};
        font-weight: 700;
    }}
    QPushButton[navButton="true"]:hover {{
        background: rgba(255, 255, 255, 0.72);
        border-color: #d2e3ea;
        color: {TOKENS.color_text};
    }}
    QPushButton[navButton="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 {TOKENS.color_accent_soft},
            stop: 1 #ffffff
        );
        border: 1px solid #a7ccd5;
        color: {TOKENS.color_accent};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        min-height: 38px;
        border-radius: {TOKENS.radius_sm}px;
        border: 1px solid {TOKENS.color_border};
        background: white;
        padding: 6px 10px;
        selection-background-color: {TOKENS.color_accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {TOKENS.color_accent};
        background: #ffffff;
    }}
    QTextEdit, QPlainTextEdit {{
        min-height: 100px;
    }}
    QPlainTextEdit {{
        font-family: {TOKENS.font_family_mono};
        background: #0f2232;
        color: #d9f7ee;
        border-color: #294458;
    }}
    QComboBox::drop-down {{
        width: 28px;
        border: none;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 24px;
        border-left: 1px solid {TOKENS.color_border};
        border-bottom: 1px solid {TOKENS.color_border};
        border-top-right-radius: {TOKENS.radius_sm}px;
        background: #f4f9fb;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 24px;
        border-left: 1px solid {TOKENS.color_border};
        border-bottom-right-radius: {TOKENS.radius_sm}px;
        background: #f4f9fb;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {TOKENS.color_accent_soft};
    }}
    QToolButton {{
        min-height: 34px;
        border-radius: {TOKENS.radius_sm}px;
        border: 1px solid {TOKENS.color_border};
        background: white;
        padding: 0 12px;
        font-weight: 600;
    }}
    QToolButton:checked {{
        background: {TOKENS.color_accent_soft};
        color: {TOKENS.color_accent};
        border-color: #a7ccd5;
    }}
    QToolButton[viewSwitch="true"] {{
        min-width: 88px;
        border-radius: 17px;
    }}
    QListWidget, QTableWidget, QTreeWidget {{
        background: white;
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
        gridline-color: {TOKENS.color_border};
    }}
    QTableWidget::item {{
        padding: 7px 8px;
    }}
    QTableWidget::item:selected {{
        background: {TOKENS.color_accent_soft};
        color: {TOKENS.color_text};
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 8px 10px;
        border-radius: {TOKENS.radius_sm}px;
        margin: 2px 4px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {TOKENS.color_accent_soft};
        color: {TOKENS.color_text};
    }}
    QTreeWidget#workflowTree {{
        background: rgba(255, 255, 255, 0.62);
        border: 1px solid #d9e6ee;
        border-radius: {TOKENS.radius_md}px;
        padding: 6px;
    }}
    QTreeWidget#workflowTree::item {{
        min-height: 30px;
        margin: 2px 0;
        padding: 7px 10px;
        border-radius: {TOKENS.radius_sm}px;
    }}
    QTreeWidget#workflowTree::item:selected {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 {TOKENS.color_accent_soft},
            stop: 1 #ffffff
        );
        color: {TOKENS.color_accent};
        font-weight: 800;
    }}
    QTabWidget::pane {{
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
        background: white;
        top: -1px;
    }}
    QTabBar::tab {{
        min-height: 34px;
        padding: 0 14px;
        margin-right: 6px;
        background: #edf2f8;
        border: 1px solid #dbe5f0;
        border-top-left-radius: {TOKENS.radius_sm}px;
        border-top-right-radius: {TOKENS.radius_sm}px;
        color: {TOKENS.color_text_muted};
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: white;
        color: {TOKENS.color_text};
        border-color: {TOKENS.color_border};
    }}
    QSplitter::handle {{
        background: transparent;
    }}
    QHeaderView::section {{
        background: #f3f8fb;
        border: none;
        border-bottom: 1px solid {TOKENS.color_border};
        padding: 8px;
        font-weight: 700;
    }}
    QGroupBox {{
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
        margin-top: 14px;
        padding: 16px 12px 12px 12px;
        background: rgba(255, 255, 255, 0.58);
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {TOKENS.color_text_muted};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 10px;
        background: transparent;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #b5c8d7;
        border-radius: 5px;
        min-height: 36px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #8faabd;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        width: 0;
    }}
    QScrollBar:horizontal {{
        height: 10px;
        background: transparent;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: #b5c8d7;
        border-radius: 5px;
        min-width: 36px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        height: 0;
        width: 0;
    }}
    """


def apply_app_theme(app: QWidget) -> None:
    app.setStyleSheet(build_stylesheet())
    font = QFont("Microsoft YaHei UI", TOKENS.font_sm)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(TOKENS.color_bg))
    palette.setColor(QPalette.Base, QColor(TOKENS.color_surface))
    palette.setColor(QPalette.Text, QColor(TOKENS.color_text))
    palette.setColor(QPalette.ButtonText, QColor(TOKENS.color_text))
    app.setPalette(palette)


def configure_plot_theme(
    plot: Any,
    *,
    left_label: str = "",
    bottom_label: str = "",
    show_bottom: bool = True,
    grid_alpha: float = 0.13,
) -> None:
    """Apply the desktop cockpit plot language to pyqtgraph plot widgets/items."""
    if hasattr(plot, "setBackground"):
        plot.setBackground("transparent")
    if hasattr(plot, "showGrid"):
        plot.showGrid(x=True, y=True, alpha=grid_alpha)
    if left_label and hasattr(plot, "setLabel"):
        plot.setLabel("left", left_label)
    if show_bottom and bottom_label and hasattr(plot, "setLabel"):
        plot.setLabel("bottom", bottom_label)
    elif not show_bottom and hasattr(plot, "hideAxis"):
        plot.hideAxis("bottom")

    for axis_name in ("left", "bottom"):
        if not hasattr(plot, "getAxis"):
            continue
        axis = plot.getAxis(axis_name)
        axis.setTextPen(TOKENS.color_text_muted)
        axis.setPen(TOKENS.color_border)
        axis.setStyle(tickTextOffset=8, autoExpandTextSpace=True)

    if hasattr(plot, "setMenuEnabled"):
        plot.setMenuEnabled(False)
    if hasattr(plot, "getViewBox"):
        view_box = plot.getViewBox()
        view_box.setDefaultPadding(0.04)
        view_box.setMouseEnabled(x=True, y=True)


class CardFrame(QFrame):
    def __init__(self, *, muted: bool = False, role: str = "default", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cardMuted" if muted else "card")
        self.setProperty("cardRole", role)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34 if role == "hero" else 26)
        shadow.setOffset(0, 12 if role == "hero" else 8)
        shadow.setColor(QColor(15, 35, 52, 32 if role == "hero" else 20))
        self.setGraphicsEffect(shadow)


def section_title(title: str, subtitle: str = "") -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("subtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return wrapper


def chip(text: str, tone: str = "neutral") -> QLabel:
    label = QLabel(text)
    label.setObjectName("chip")
    if tone != "neutral":
        label.setProperty("chipTone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
    return label
