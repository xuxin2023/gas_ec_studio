from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QSizePolicy, QVBoxLayout, QWidget


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
    color_bg: str = "#eaf2f6"
    color_bg_deep: str = "#cddfe8"
    color_surface: str = "#ffffff"
    color_surface_soft: str = "#f5f9fc"
    color_surface_warm: str = "#fffdf8"
    color_border: str = "#bfd1dc"
    color_border_strong: str = "#819aad"
    color_text: str = "#0c2230"
    color_text_muted: str = "#506b7d"
    color_accent: str = "#0b6f7f"
    color_accent_hover: str = "#075a69"
    color_accent_soft: str = "#d8f3f4"
    color_success: str = "#19784c"
    color_warning: str = "#a86612"
    color_error: str = "#ba2f2b"
    color_copper: str = "#b66b1d"
    color_chip_neutral: str = "#e4edf3"
    color_chip_text: str = "#25384a"
    color_hero_ink: str = "#081f2d"
    color_hero_teal: str = "#0b6678"
    color_hero_mint: str = "#d8f1e8"
    shadow_soft: str = "rgba(15, 35, 52, 0.11)"


TOKENS = DesignTokens()
_FONT_REGISTRATION_DONE = False
_REGISTERED_FONT_FAMILIES: tuple[str, ...] = ()


def _register_desktop_fonts() -> tuple[str, ...]:
    global _FONT_REGISTRATION_DONE, _REGISTERED_FONT_FAMILIES
    if _FONT_REGISTRATION_DONE:
        return _REGISTERED_FONT_FAMILIES

    font_paths = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\bahnschrift.ttf"),
        Path(r"C:\Windows\Fonts\consola.ttf"),
    )
    families: list[str] = []
    for path in font_paths:
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))
    _FONT_REGISTRATION_DONE = True
    _REGISTERED_FONT_FAMILIES = tuple(dict.fromkeys(families))
    return _REGISTERED_FONT_FAMILIES


def preferred_ui_font_family() -> str:
    families = set(_register_desktop_fonts()) | set(QFontDatabase.families())
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun", "Segoe UI"):
        if family in families:
            return family
    return "Segoe UI"

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
    QWidget[pageSurface="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fbfdfe,
            stop: 0.34 #edf7f8,
            stop: 0.72 {TOKENS.color_bg},
            stop: 1 {TOKENS.color_bg_deep}
        );
    }}
    QMainWindow {{
        background: {TOKENS.color_bg};
    }}
    QWidget#appShell {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fbfdfe,
            stop: 0.28 #edf7f8,
            stop: 0.66 {TOKENS.color_bg},
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
            stop: 0 {TOKENS.color_hero_ink},
            stop: 0.48 {TOKENS.color_hero_teal},
            stop: 0.78 #bfe8df,
            stop: 1 {TOKENS.color_hero_mint}
        );
        border: 1px solid #7eb3bd;
    }}
    QFrame#card[cardRole="hero"] QLabel#pageTitle {{
        color: #f7fcfd;
        letter-spacing: 0.4px;
    }}
    QFrame#card[cardRole="hero"] QLabel#subtitle {{
        color: #d6edf2;
    }}
    QFrame#card[cardRole="hero"] QLabel[heroStatus="true"] {{
        color: #214254;
    }}
    QFrame#card[cardRole="hero"] QLabel#subtitle[heroStatus="true"] {{
        color: #214254;
    }}
    QFrame#card[cardRole="panel"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fffefb,
            stop: 0.7 #ffffff,
            stop: 1 #f4faf8
        );
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
            stop: 0 #fffcf2,
            stop: 0.55 #ffffff,
            stop: 1 #e9f7f1
        );
        border: 1px solid #c7dccf;
    }}
    QFrame#cardMuted[cardRole="tile"] {{
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid #d3e1e8;
        border-radius: {TOKENS.radius_md}px;
    }}
    QFrame#cardMuted[cardRole="tile"][expertTone="success"],
    QFrame#cardMuted[cardRole="tile"][gateTone="success"],
    QFrame#cardMuted[cardRole="tile"][commandTone="success"],
    QFrame#cardMuted[cardRole="tile"][evidenceTone="success"] {{
        background: #f1fbf5;
        border-color: #b7dcc9;
    }}
    QFrame#cardMuted[cardRole="tile"][expertTone="accent"],
    QFrame#cardMuted[cardRole="tile"][gateTone="accent"],
    QFrame#cardMuted[cardRole="tile"][commandTone="accent"],
    QFrame#cardMuted[cardRole="tile"][evidenceTone="accent"] {{
        background: #eef9fb;
        border-color: #a7ccd5;
    }}
    QFrame#cardMuted[cardRole="tile"][expertTone="warning"],
    QFrame#cardMuted[cardRole="tile"][gateTone="warning"],
    QFrame#cardMuted[cardRole="tile"][commandTone="warning"],
    QFrame#cardMuted[cardRole="tile"][evidenceTone="warning"] {{
        background: #fff8e8;
        border-color: #ead1a5;
    }}
    QFrame#cardMuted[cardRole="tile"][evidenceTone="danger"] {{
        background: #fdeaea;
        border-color: #efc1c1;
    }}
    QFrame#cardMuted[cardRole="tile"][routeAction="true"] {{
        background: rgba(255, 255, 255, 0.92);
        border-color: #c8dce5;
        border-radius: {TOKENS.radius_md}px;
    }}
    QFrame#cardMuted[cardRole="rail"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 rgba(255, 255, 255, 0.76),
            stop: 0.58 rgba(248, 252, 255, 0.64),
            stop: 1 rgba(232, 243, 247, 0.58)
        );
        border: 1px solid #d7e5ec;
        border-radius: {TOKENS.radius_lg}px;
    }}
    QFrame#cardMuted[cardRole="console"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #f8fbfd,
            stop: 0.55 #eef6f9,
            stop: 1 #e8f1f4
        );
        border: 1px solid #c6d9e4;
        border-radius: {TOKENS.radius_lg}px;
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
    QLabel#metricValue[compactMetric="true"] {{
        font-size: 14px;
        font-weight: 700;
        padding: 1px 0;
    }}
    QLabel#metricLabel {{
        color: {TOKENS.color_text_muted};
        font-size: {TOKENS.font_xs}px;
        letter-spacing: 0.5px;
        font-weight: 700;
    }}
    QLabel[methodFieldLabel="true"] {{
        font-family: {TOKENS.font_family_mono};
        color: #31586c;
        background: rgba(255, 255, 255, 0.58);
        border: 1px solid rgba(180, 205, 218, 0.64);
        border-radius: 7px;
        padding: 1px 6px;
    }}
    QLabel[methodGroupPill="true"] {{
        color: #0f6675;
        background: rgba(220, 245, 244, 0.68);
        border: 1px solid #add7da;
        border-radius: 10px;
        padding: 3px 9px;
        font-size: {TOKENS.font_xs}px;
        font-weight: 700;
    }}
    QLabel[heroStatus="true"] {{
        min-width: 160px;
        padding: 7px 10px;
        border-radius: {TOKENS.radius_md}px;
        background: rgba(255, 255, 255, 0.86);
        border: 1px solid rgba(255, 255, 255, 0.72);
        color: #214254;
    }}
    QLabel[shellTile="true"] {{
        min-width: 40px;
        padding: 6px 7px;
        border-radius: {TOKENS.radius_md}px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid rgba(255, 255, 255, 0.68);
        color: {TOKENS.color_text};
        font-weight: 800;
        line-height: 1.25;
    }}
    QLabel[shellTile="true"][shellTone="accent"] {{
        background: {TOKENS.color_accent_soft};
        border-color: #a7ccd5;
        color: {TOKENS.color_accent};
    }}
    QLabel[shellTile="true"][shellTone="success"] {{
        background: #e8f7ee;
        border-color: #b7dcc9;
        color: {TOKENS.color_success};
    }}
    QLabel[shellTile="true"][shellTone="warning"] {{
        background: #fff5df;
        border-color: #ead1a5;
        color: {TOKENS.color_warning};
    }}
    QLabel[shellTile="true"][shellTone="danger"] {{
        background: #fdeaea;
        border-color: #efc1c1;
        color: {TOKENS.color_error};
    }}
    QWidget[shellClosureStrip="true"] {{
        padding: 2px;
        border-radius: {TOKENS.radius_md}px;
        background: rgba(33, 66, 84, 0.08);
        border: 1px solid rgba(33, 66, 84, 0.10);
    }}
    QLabel[closureStage="true"] {{
        min-width: 40px;
        padding: 5px 6px;
        border-radius: {TOKENS.radius_sm}px;
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(255, 255, 255, 0.62);
        color: {TOKENS.color_text_muted};
        font-size: {TOKENS.font_xs}px;
        font-weight: 800;
        line-height: 1.18;
    }}
    QLabel[closureStage="true"][closureTone="success"] {{
        background: #e8f7ee;
        border-color: #b7dcc9;
        color: {TOKENS.color_success};
    }}
    QLabel[closureStage="true"][closureTone="accent"] {{
        background: #e5f6f8;
        border-color: #b7dbe2;
        color: {TOKENS.color_accent};
    }}
    QLabel[closureStage="true"][closureTone="warning"] {{
        background: #fff5df;
        border-color: #ead1a5;
        color: {TOKENS.color_warning};
    }}
    QLabel[closureStage="true"][closureTone="danger"] {{
        background: #fdeaea;
        border-color: #efc1c1;
        color: {TOKENS.color_error};
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
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff1f1,
            stop: 1 #fff8f8
        );
        color: {TOKENS.color_error};
        border: 1px solid #f3c6c6;
    }}
    QPushButton[variant="ghost"] {{
        background: transparent;
    }}
    QPushButton[navButton="true"] {{
        min-height: 52px;
        padding: 7px 10px;
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
            stop: 0 #bfecef,
            stop: 0.12 {TOKENS.color_accent_soft},
            stop: 1 rgba(255, 255, 255, 0.92)
        );
        border: 1px solid #a7ccd5;
        color: {TOKENS.color_accent};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        min-height: 38px;
        border-radius: {TOKENS.radius_sm}px;
        border: 1px solid #c5d7e2;
        background: #fbfdfe;
        padding: 6px 10px;
        selection-background-color: {TOKENS.color_accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {TOKENS.color_accent};
        background: #ffffff;
        color: {TOKENS.color_text};
    }}
    QComboBox[methodFieldInput="true"],
    QSpinBox[methodFieldInput="true"],
    QDoubleSpinBox[methodFieldInput="true"] {{
        min-height: 28px;
        border-radius: 8px;
        padding: 3px 8px;
        background: #ffffff;
        border-color: #bdd2dd;
    }}
    QTextEdit, QPlainTextEdit {{
        min-height: 100px;
    }}
    QPlainTextEdit {{
        font-family: {TOKENS.font_family_mono};
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #102535,
            stop: 0.72 #0e1d2a,
            stop: 1 #132b35
        );
        color: #d9f7ee;
        border-color: #2d4d60;
        border-radius: {TOKENS.radius_md}px;
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
    QToolButton:hover {{
        border-color: {TOKENS.color_border_strong};
        background: #fbfdfe;
    }}
    QToolButton:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #c5eef1,
            stop: 1 #f7fdfd
        );
        color: {TOKENS.color_accent};
        border-color: #a7ccd5;
    }}
    QToolButton[railAction="true"] {{
        min-height: 28px;
        border-radius: {TOKENS.radius_sm}px;
        padding: 0 8px;
        color: #0e5f6e;
        background: rgba(255, 255, 255, 0.9);
        border-color: #b8d4de;
    }}
    QToolButton[railAction="true"][actionTone="danger"] {{
        color: {TOKENS.color_error};
        background: #fff1f1;
        border-color: #efc1c1;
    }}
    QToolButton[viewSwitch="true"] {{
        min-width: 42px;
        border-radius: 17px;
    }}
    QFrame#card[cardRole="command"] QToolButton[viewSwitch="true"],
    QFrame#cardMuted[cardRole="rail"] QToolButton[viewSwitch="true"],
    QFrame#cardMuted[cardRole="panel"] QToolButton[viewSwitch="true"] {{
        min-height: 32px;
        padding: 0 10px;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #c8dde6;
        color: {TOKENS.color_text_muted};
    }}
    QFrame#card[cardRole="command"] QToolButton[viewSwitch="true"]:hover,
    QFrame#cardMuted[cardRole="rail"] QToolButton[viewSwitch="true"]:hover,
    QFrame#cardMuted[cardRole="panel"] QToolButton[viewSwitch="true"]:hover {{
        background: rgba(255, 255, 255, 0.92);
        border-color: #95bdc8;
        color: {TOKENS.color_text};
    }}
    QFrame#card[cardRole="command"] QToolButton[viewSwitch="true"]:checked,
    QFrame#cardMuted[cardRole="rail"] QToolButton[viewSwitch="true"]:checked,
    QFrame#cardMuted[cardRole="panel"] QToolButton[viewSwitch="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #b8e9ed,
            stop: 0.62 #dff8f6,
            stop: 1 #f9fffc
        );
        border: 1px solid #8dbfc9;
        color: {TOKENS.color_accent};
        font-weight: 800;
    }}
    QToolButton[previewPaneSwitch="true"] {{
        min-height: 28px;
        min-width: 58px;
        border-radius: 14px;
        padding: 0 12px;
        background: rgba(255, 255, 255, 0.84);
        border: 1px solid #b9d3dc;
        color: #31586a;
    }}
    QToolButton[previewPaneSwitch="true"]:hover {{
        background: #f8fcfd;
        border-color: #7eb3bd;
        color: {TOKENS.color_text};
    }}
    QToolButton[previewPaneSwitch="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 {TOKENS.color_accent},
            stop: 1 #0f8990
        );
        border: 1px solid {TOKENS.color_accent_hover};
        color: #ffffff;
        font-weight: 800;
    }}
    QToolButton[methodShortcut="true"] {{
        min-height: 28px;
        min-width: 66px;
        border-radius: 14px;
        padding: 0 8px;
        background: #f7fbfd;
        border: 1px solid #bed6df;
        color: #31586a;
    }}
    QToolButton[methodShortcut="true"]:hover {{
        background: #ffffff;
        border-color: #7eb3bd;
        color: {TOKENS.color_text};
    }}
    QToolButton[methodShortcut="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #0c6d78,
            stop: 1 #33a0a0
        );
        border: 1px solid #075a69;
        color: #ffffff;
        font-weight: 800;
    }}
    QToolButton[methodTaskSwitch="true"] {{
        min-height: 28px;
        min-width: 76px;
        border-radius: 14px;
        padding: 0 10px;
        background: rgba(247, 251, 253, 0.88);
        border: 1px solid #b8d4dd;
        color: #31586a;
    }}
    QToolButton[methodTaskSwitch="true"]:hover {{
        background: #ffffff;
        border-color: #7eb3bd;
        color: {TOKENS.color_text};
    }}
    QToolButton[methodTaskSwitch="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #083f50,
            stop: 1 #0f8990
        );
        border: 1px solid #063847;
        color: #ffffff;
        font-weight: 800;
    }}
    QToolButton[windowConsoleSwitch="true"] {{
        min-height: 26px;
        min-width: 48px;
        border-radius: 13px;
        padding: 0 8px;
        background: rgba(255, 255, 255, 0.74);
        border: 1px solid #c4dce4;
        color: #31586a;
    }}
    QToolButton[windowConsoleSwitch="true"]:hover {{
        background: #ffffff;
        border-color: #86b7c0;
        color: {TOKENS.color_text};
    }}
    QToolButton[windowConsoleSwitch="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #0b6f7f,
            stop: 1 #53aca3
        );
        border: 1px solid #075a69;
        color: #ffffff;
        font-weight: 800;
    }}
    QListWidget, QTableWidget, QTreeWidget {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #ffffff,
            stop: 1 #f7fbfd
        );
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
            stop: 0 #bce8ef,
            stop: 0.16 {TOKENS.color_accent_soft},
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
    font_family = preferred_ui_font_family()
    app.setStyleSheet(build_stylesheet())
    font = QFont(font_family, TOKENS.font_sm)
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
    wrapper.setMinimumWidth(0)
    wrapper.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    title_label.setMinimumWidth(0)
    title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("subtitle")
        subtitle_label.setMinimumWidth(0)
        subtitle_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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
