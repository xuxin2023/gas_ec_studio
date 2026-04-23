from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget


@dataclass(frozen=True, slots=True)
class DesignTokens:
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
    color_bg: str = "#f4f7fb"
    color_surface: str = "#ffffff"
    color_surface_soft: str = "#f8fbff"
    color_border: str = "#d9e2ee"
    color_text: str = "#162234"
    color_text_muted: str = "#607086"
    color_accent: str = "#2b6cbf"
    color_accent_soft: str = "#e8f1fc"
    color_success: str = "#2f855a"
    color_warning: str = "#b7791f"
    color_error: str = "#c53030"
    color_chip_neutral: str = "#e9eff6"
    color_chip_text: str = "#334155"


TOKENS = DesignTokens()


def build_stylesheet() -> str:
    return f"""
    * {{
        font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
        color: {TOKENS.color_text};
        font-size: {TOKENS.font_sm}px;
    }}
    QWidget {{
        background: {TOKENS.color_bg};
    }}
    QMainWindow {{
        background: {TOKENS.color_bg};
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
    QLabel#pageTitle {{
        font-size: {TOKENS.font_xl}px;
        font-weight: 700;
        color: {TOKENS.color_text};
    }}
    QLabel#sectionTitle {{
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
        font-weight: 700;
        color: {TOKENS.color_text};
    }}
    QLabel#metricLabel {{
        color: {TOKENS.color_text_muted};
        font-size: {TOKENS.font_xs}px;
        letter-spacing: 0.5px;
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
        border-color: #b7c8dc;
        background: #fcfdff;
    }}
    QPushButton[variant="primary"] {{
        background: {TOKENS.color_accent};
        color: white;
        border: 1px solid {TOKENS.color_accent};
    }}
    QPushButton[variant="danger"] {{
        background: #fff5f5;
        color: {TOKENS.color_error};
        border: 1px solid #f3c6c6;
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        min-height: 38px;
        border-radius: {TOKENS.radius_sm}px;
        border: 1px solid {TOKENS.color_border};
        background: white;
        padding: 6px 10px;
        selection-background-color: {TOKENS.color_accent};
    }}
    QTextEdit, QPlainTextEdit {{
        min-height: 100px;
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
        border-color: #bfd3f0;
    }}
    QListWidget, QTableWidget, QTreeWidget {{
        background: white;
        border: 1px solid {TOKENS.color_border};
        border-radius: {TOKENS.radius_md}px;
        gridline-color: {TOKENS.color_border};
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
        background: #f7fafe;
        border: none;
        border-bottom: 1px solid {TOKENS.color_border};
        padding: 8px;
        font-weight: 700;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
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


class CardFrame(QFrame):
    def __init__(self, *, muted: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cardMuted" if muted else "card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(17, 34, 68, 20))
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
