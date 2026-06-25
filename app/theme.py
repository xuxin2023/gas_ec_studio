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
    QFrame#card[cardRole="hero"][shellHeroDock="true"] {{
        border-radius: 20px;
        border: 1px solid #7cb8c1;
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
    QFrame#cardMuted[cardRole="tile"][evidenceTone="success"],
    QFrame#cardMuted[cardRole="tile"][radarTone="success"] {{
        background: #f1fbf5;
        border-color: #b7dcc9;
    }}
    QFrame#cardMuted[cardRole="tile"][expertTone="accent"],
    QFrame#cardMuted[cardRole="tile"][gateTone="accent"],
    QFrame#cardMuted[cardRole="tile"][commandTone="accent"],
    QFrame#cardMuted[cardRole="tile"][evidenceTone="accent"],
    QFrame#cardMuted[cardRole="tile"][radarTone="accent"] {{
        background: #eef9fb;
        border-color: #a7ccd5;
    }}
    QFrame#cardMuted[cardRole="tile"][expertTone="warning"],
    QFrame#cardMuted[cardRole="tile"][gateTone="warning"],
    QFrame#cardMuted[cardRole="tile"][commandTone="warning"],
    QFrame#cardMuted[cardRole="tile"][evidenceTone="warning"],
    QFrame#cardMuted[cardRole="tile"][radarTone="warning"] {{
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
    QFrame#cardMuted[cardRole="rail"][navRailWorkbench="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fbfefe,
            stop: 0.54 #edf8fa,
            stop: 1 #e7f2f6
        );
        border-color: #c9dce5;
    }}
    QFrame#cardMuted[ecProcessRail="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fbfefe,
            stop: 0.58 #eef8fa,
            stop: 1 #e9f4f0
        );
        border-color: #c4dce4;
    }}
    QWidget[stepPhaseMap="true"] {{
        max-height: 78px;
    }}
    QToolButton[stepPhaseTile="true"] {{
        min-height: 30px;
        border-radius: 11px;
        padding: 2px 8px;
        background: rgba(255, 255, 255, 0.78);
        border: 1px solid #c8dce5;
        color: #31586a;
        font-size: 10px;
        font-weight: 800;
    }}
    QToolButton[stepPhaseTile="true"]:checked {{
        background: #e8f8f8;
        border-color: #70b7c1;
        color: #063847;
    }}
    QToolButton[stepPhaseTile="true"][phaseTone="success"] {{
        background: #f0fbf5;
        border-color: #9fd2bb;
    }}
    QToolButton[stepPhaseTile="true"][phaseTone="warning"] {{
        background: #fff8e8;
        border-color: #e6c98e;
    }}
    QToolButton[stepPhaseTile="true"][phaseTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
    }}
    QWidget[navBrandBlock="true"] {{
        padding: 4px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.48);
    }}
    QLabel[navRailNote="true"] {{
        color: #486476;
        font-size: 12px;
    }}
    QLabel[navMissionChip="true"] {{
        border-radius: 11px;
        padding: 3px 8px;
        background: rgba(7, 47, 59, 0.10);
        border: 1px solid rgba(104, 153, 169, 0.24);
        color: #0e5f6e;
        font-size: 10px;
        font-weight: 900;
        letter-spacing: 0.5px;
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
    QFrame#cardMuted[logPanelCompactDock="true"] {{
        border-radius: 15px;
        background: rgba(244, 251, 252, 0.92);
        border-color: #bcd6df;
    }}
    QLabel[logLatestLine="true"] {{
        color: #31586a;
        font-size: 11px;
    }}
    QToolButton[logPanelAction="true"],
    QPushButton[logPanelAction="true"] {{
        min-height: 22px;
        border-radius: 11px;
        padding: 0 10px;
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
    QWidget[shellTelemetryStrip="true"] {{
        padding: 2px;
        border-radius: 16px;
        background: rgba(246, 252, 253, 0.34);
        border: 1px solid rgba(255, 255, 255, 0.28);
    }}
    QLabel[shellTile="true"][shellTelemetryTile="true"] {{
        min-width: 36px;
        padding: 4px 6px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.76);
        font-size: 11px;
        line-height: 1.12;
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
    QWidget[shellClosureStrip="true"][shellClosureBus="true"] {{
        padding: 3px;
        border-radius: 17px;
        background: rgba(7, 47, 59, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.20);
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
    QLabel[closureStage="true"][closureBusNode="true"] {{
        min-width: 42px;
        padding: 4px 5px;
        border-radius: 14px;
        font-size: 11px;
        line-height: 1.08;
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
    QPushButton[navButton="true"][navRouteTile="true"] {{
        min-height: 46px;
        padding: 5px 9px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.42);
        border: 1px solid rgba(191, 216, 223, 0.58);
        color: #38576a;
        line-height: 1.12;
    }}
    QPushButton[navButton="true"][navRouteTile="true"][navPhase="field"] {{
        border-left: 3px solid #8ecfd4;
    }}
    QPushButton[navButton="true"][navRouteTile="true"][navPhase="site"] {{
        border-left: 3px solid #a6d5b8;
    }}
    QPushButton[navButton="true"][navRouteTile="true"][navPhase="compute"] {{
        border-left: 3px solid #e3c27a;
    }}
    QPushButton[navButton="true"][navRouteTile="true"][navPhase="delivery"] {{
        border-left: 3px solid #7eb3bd;
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
    QFrame[navPrincipleCard="true"][navPrincipleCompact="true"] {{
        border-radius: 14px;
        border: 1px solid rgba(191, 216, 223, 0.70);
        background: rgba(255, 255, 255, 0.58);
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
    QToolButton[railMissionAction="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 7px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid #b9d3dc;
    }}
    QFrame#cardMuted[railMissionTile="true"] {{
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.66);
        border: 1px solid #d1e1e8;
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
    QToolButton[shellModeToggle="true"] {{
        min-height: 52px;
        min-width: 48px;
        border-radius: 16px;
        padding: 0 8px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid rgba(255, 255, 255, 0.48);
        color: #16495a;
        font-weight: 800;
    }}
    QToolButton[shellModeToggle="true"]:checked {{
        background: #ffffff;
        border: 1px solid #9bc9d2;
        color: #073746;
    }}
    QFrame#cardMuted[ecMethodShortcutDeck="true"] {{
        border-radius: 16px;
        border: 1px solid #c8dfe6;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f8fcfd,
            stop: 0.56 #eef8f9,
            stop: 1 #f8fbef
        );
    }}
    QLabel[methodShortcutValue="true"] {{
        color: #123c4c;
        font-size: 13px;
        font-weight: 900;
    }}
    QLabel[methodShortcutNote="true"] {{
        color: #587282;
        font-size: 9px;
        font-weight: 700;
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
    QToolButton[methodShortcut="true"][methodTone="success"] {{
        border-color: #9fd2bb;
        background: #f1fbf5;
    }}
    QToolButton[methodShortcut="true"][methodTone="warning"] {{
        border-color: #e6c98e;
        background: #fff7e4;
    }}
    QToolButton[methodShortcut="true"][methodTone="danger"] {{
        border-color: #e8b3ad;
        background: #fff0ef;
        color: {TOKENS.color_error};
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
    QToolButton[methodShortcut="true"][activeMethodShortcut="true"] {{
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
    QFrame#cardMuted[methodConsoleCompact="true"] {{
        border-radius: 16px;
        border: 1px solid #bfd8df;
        background: rgba(247, 252, 253, 0.82);
    }}
    QWidget[methodStateMirror="true"] {{
        max-height: 46px;
    }}
    QFrame#cardMuted[methodConsoleTile="true"] {{
        border-radius: 13px;
        border: 1px solid #c8dde4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 rgba(255, 255, 255, 0.94),
            stop: 1 rgba(239, 248, 249, 0.84)
        );
    }}
    QFrame#cardMuted[methodConsoleTile="true"][methodTone="success"] {{
        background: #f1fbf5;
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[methodConsoleTile="true"][methodTone="accent"] {{
        background: #eef9fb;
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[methodConsoleTile="true"][methodTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
    }}
    QFrame#cardMuted[methodConsoleTile="true"][methodTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
    }}
    QFrame#cardMuted[methodConsoleTile="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 13px;
        font-weight: 800;
    }}
    QWidget[methodFamilyControlStrip="true"] {{
        max-height: 52px;
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"] {{
        border-radius: 12px;
        border: 1px solid #c9dfe6;
        background: rgba(255, 255, 255, 0.84);
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"][summaryKey="recommended"] {{
        background: #f3fbfb;
        border-color: #afd2da;
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="success"] {{
        background: #f2fbf5;
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"][methodTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
    }}
    QFrame#cardMuted[methodFamilyControlTile="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 12px;
        font-weight: 800;
        padding: 0;
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
    QToolButton[closureModeSwitch="true"] {{
        min-height: 24px;
        min-width: 48px;
        border-radius: 12px;
        padding: 0 8px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #c4dce4;
        color: #31586a;
    }}
    QToolButton[closureModeSwitch="true"]:checked {{
        background: #0b6f7f;
        border: 1px solid #075a69;
        color: #ffffff;
        font-weight: 800;
    }}
    QComboBox[runRibbonField="true"] {{
        min-height: 28px;
        border-radius: 13px;
        padding-left: 10px;
        background: rgba(255, 255, 255, 0.86);
        border: 1px solid #b8d4dd;
    }}
    QFrame#card[runCommandDock="true"] {{
        border-radius: 18px;
        border: 1px solid #a8cbd4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #edf9fa,
            stop: 0.45 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[runMissionStrip="true"] {{
        border-radius: 13px;
        border: 1px solid #c3dce3;
        background: rgba(255, 255, 255, 0.72);
    }}
    QLabel[runMissionLabel="true"] {{
        color: #5c7480;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }}
    QLabel[runMissionValue="true"] {{
        color: #0f2a3a;
        font-size: 11px;
        font-weight: 800;
    }}
    QLabel[runMissionText="true"] {{
        color: #31586a;
        font-size: 11px;
    }}
    QPushButton[runRibbonAction="true"] {{
        min-height: 28px;
        border-radius: 14px;
        padding: 0 12px;
    }}
    QFrame#card[spectralRunCommandDock="true"] {{
        border-radius: 18px;
        border: 1px solid #a8cbd4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #edf9fa,
            stop: 0.50 #ffffff,
            stop: 1 #e8f6ef
        );
    }}
    QFrame#cardMuted[spectralSourceDock="true"],
    QFrame#cardMuted[spectralActionDock="true"],
    QFrame#cardMuted[spectralStatusDock="true"] {{
        border-radius: 14px;
        border: 1px solid #c3dce3;
        background: rgba(255, 255, 255, 0.74);
    }}
    QWidget[spectralSummaryInline="true"] {{
        max-height: 72px;
    }}
    QFrame#cardMuted[spectralSummaryMetric="true"] {{
        border-radius: 13px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[stepCommandDock="true"] {{
        border-radius: 15px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.86);
    }}
    QFrame#cardMuted[stepCommandTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.70);
    }}
    QToolButton[stepCommandAction="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 8px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QFrame#card[reportPreviewHeaderDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.46 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[previewCommandDock="true"] {{
        border-radius: 15px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.88);
    }}
    QFrame#cardMuted[previewCommandTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.72);
    }}
    QFrame#cardMuted[deliveryStatusRadar="true"] {{
        border-radius: 14px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.64);
    }}
    QFrame#cardMuted[deliveryStatusRadarCell="true"] {{
        border-radius: 10px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.72);
    }}
    QFrame#cardMuted[deliveryStatusRadarCell="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 11px;
        font-weight: 800;
        padding: 0;
    }}
    QFrame#cardMuted[reportCommandSummary="true"] {{
        border-radius: 15px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f8fcfd,
            stop: 0.56 #ffffff,
            stop: 1 #eef8f2
        );
    }}
    QFrame#cardMuted[reportCommandSummary="true"][commandStatus="success"] {{
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[reportCommandSummary="true"][commandStatus="accent"] {{
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[reportCommandSummary="true"][commandStatus="warning"] {{
        border-color: #e6c98e;
    }}
    QLabel[reportCommandNextNote="true"] {{
        color: #527081;
        font-size: 10px;
        font-weight: 700;
    }}
    QWidget[deliveryClosureStrip="true"] {{
        max-height: 104px;
    }}
    QWidget[deliveryClosureStrip="true"][deliveryClosureMatrix="true"] {{
        background: transparent;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d1e2e8;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 rgba(255, 255, 255, 0.94),
            stop: 1 rgba(239, 248, 249, 0.84)
        );
    }}
    QFrame#cardMuted[deliveryClosureTile="true"][commandGroup="artifact"] {{
        border-left: 3px solid #8bbfca;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"][commandGroup="validation"] {{
        border-left: 3px solid #d7ad70;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"][commandTone="success"] {{
        background: #f1fbf5;
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"][commandTone="accent"] {{
        background: #eef9fb;
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"][commandTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
    }}
    QFrame#cardMuted[deliveryClosureTile="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 11px;
        font-weight: 800;
    }}
    QFrame#cardMuted[reportPreviewWorkbench="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(247, 252, 253, 0.84);
    }}
    QFrame#cardMuted[reportPreviewAnalysisStrip="true"] {{
        border-radius: 14px;
        border: 1px solid #c3dce3;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #f7fcfd,
            stop: 0.58 #ffffff,
            stop: 1 #eef8f1
        );
    }}
    QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="plot"] {{
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="table"] {{
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[reportPreviewAnalysisStrip="true"][analysisMode="insight"] {{
        border-color: #e6c98e;
    }}
    QLabel[reportPreviewAnalysisHint="true"] {{
        color: #527081;
        font-size: 10px;
        font-weight: 700;
    }}
    QWidget[reportPreviewMetricStrip="true"] {{
        max-height: 62px;
    }}
    QFrame#cardMuted[reportPreviewMetric="true"] {{
        border-radius: 13px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[reportActionDrawer="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #f8fcfd,
            stop: 0.58 #ffffff,
            stop: 1 #eef8f2
        );
    }}
    QFrame#cardMuted[reportActionDrawer="true"][actionTone="success"] {{
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[reportActionDrawer="true"][actionTone="accent"] {{
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[reportActionDrawer="true"][actionTone="warning"] {{
        border-color: #e6c98e;
    }}
    QFrame#cardMuted[previewWorkflowRoute="true"] {{
        border-radius: 14px;
        border: 1px solid #c3dce4;
        background: rgba(248, 252, 253, 0.88);
    }}
    QLabel[previewRouteTitle="true"] {{
        color: #456879;
        font-size: 10px;
        font-weight: 800;
    }}
    QWidget[previewRouteButtonRow="true"] {{
        background: transparent;
    }}
    QToolButton[previewWorkflowRouteButton="true"] {{
        min-height: 22px;
        border-radius: 11px;
        padding: 0 8px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
        font-size: 10px;
        font-weight: 800;
    }}
    QToolButton[previewWorkflowRouteButton="true"]:checked {{
        background: #dff5f7;
        border-color: #7fbec8;
    }}
    QToolButton[reportActionDrawerButton="true"] {{
        min-height: 22px;
        border-radius: 11px;
        padding: 0 8px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
        font-size: 11px;
        font-weight: 800;
    }}
    QSplitter#reportPreviewSplitPane {{
        background: transparent;
    }}
    QFrame#cardMuted[reportPreviewPrimaryPane="true"] {{
        border-radius: 15px;
        border: 1px solid #c9dfe6;
        background: rgba(255, 255, 255, 0.80);
    }}
    QFrame#cardMuted[reportPreviewContextPane="true"] {{
        border-radius: 15px;
        border: 1px solid #c8dce4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f8fcfd,
            stop: 1 #eef8f2
        );
    }}
    QFrame#cardMuted[reportPreviewContextPane="true"][reportPreviewEvidenceRail="true"] {{
        border-color: #b8d6df;
    }}
    QFrame#cardMuted[previewEvidenceSummary="true"] {{
        border-radius: 13px;
        border: 1px solid #bed8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f8fcfd,
            stop: 0.56 #ffffff,
            stop: 1 #eff8ef
        );
    }}
    QFrame#cardMuted[previewEvidenceSummary="true"][evidenceTone="success"] {{
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[previewEvidenceSummary="true"][evidenceTone="accent"] {{
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[previewEvidenceSummary="true"][evidenceTone="warning"] {{
        border-color: #e6c98e;
    }}
    QLabel[previewEvidenceNote="true"] {{
        color: #527081;
        font-size: 10px;
        font-weight: 700;
    }}
    QWidget[previewEvidenceStatusRow="true"] {{
        background: transparent;
    }}
    QLabel[previewEvidenceStatusChip="true"] {{
        min-width: 42px;
        font-size: 9px;
        font-weight: 800;
    }}
    QFrame#cardMuted[previewContextTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d1e2e8;
        background: rgba(255, 255, 255, 0.78);
    }}
    QFrame#cardMuted[previewContextTile="true"][previewEvidenceTile="true"] {{
        border-radius: 11px;
    }}
    QFrame#cardMuted[previewContextTile="true"][contextTone="success"] {{
        background: #f0fbf5;
        border-color: #9fd2bb;
    }}
    QFrame#cardMuted[previewContextTile="true"][contextTone="accent"] {{
        background: #eef9fb;
        border-color: #94c9d3;
    }}
    QFrame#cardMuted[previewContextTile="true"][contextTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
    }}
    QFrame#cardMuted[previewContextTile="true"][contextTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
    }}
    QFrame#cardMuted[previewContextTile="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 12px;
        font-weight: 800;
    }}
    QToolButton[previewContextAction="true"] {{
        min-height: 18px;
        border-radius: 9px;
        padding: 0 6px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #bfd8df;
        color: #0e5f6e;
        font-size: 10px;
        font-weight: 800;
    }}
    QFrame#cardMuted[previewTrailStrip="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #f7fcfd,
            stop: 1 #eef8f2
        );
    }}
    QLabel[previewTrailLabel="true"] {{
        color: #31586a;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }}
    QToolButton[previewCommandAction="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 8px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QFrame#cardMuted[reportNavRail="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(247, 252, 253, 0.82);
    }}
    QTreeWidget#workflowTree[reportNavTree="true"] {{
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid #d2e3e9;
        padding: 4px;
    }}
    QWidget[reportNavPhaseStrip="true"] {{
        background: transparent;
    }}
    QToolButton[reportNavPhaseButton="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 1px 6px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #c8dce4;
        color: #31586a;
        font-size: 9px;
        font-weight: 800;
    }}
    QToolButton[reportNavPhaseButton="true"][activePhase="true"],
    QToolButton[reportNavPhaseButton="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #e5f8fb,
            stop: 1 #f8fff5
        );
        border-color: #7fbec8;
        color: #0d6472;
    }}
    QLabel[reportNavStageNote="true"] {{
        color: #527081;
        font-size: 10px;
        font-weight: 700;
    }}
    QFrame#cardMuted[reportNavTaskMap="true"] {{
        border-radius: 16px;
        border: 1px solid #cfe3e8;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f9fdfc,
            stop: 0.58 #eff9f8,
            stop: 1 #f6fbef
        );
    }}
    QLabel[reportNavTaskValue="true"] {{
        color: #153847;
        font-size: 15px;
        font-weight: 900;
    }}
    QLabel[reportNavTaskNote="true"] {{
        color: #5a7280;
        font-size: 9px;
        font-weight: 700;
    }}
    QLabel[reportNavTaskStep="true"] {{
        padding: 2px 4px;
        border-radius: 9px;
        border: 1px solid #d7e7eb;
        background: rgba(255, 255, 255, 0.72);
        color: #5b7480;
        font-size: 8px;
        font-weight: 800;
    }}
    QLabel[reportNavTaskStep="true"][activeTaskStep="true"] {{
        border-color: #7fbec8;
        background: #e7f8fa;
        color: #0d6472;
    }}
    QFrame#cardMuted[deliveryMissionRail="true"] {{
        border-radius: 18px;
        border: 1px solid #c4dce4;
        background: rgba(247, 252, 253, 0.86);
    }}
    QFrame#cardMuted[deliveryMissionRail="true"][desktopMissionRail="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f9fdfc,
            stop: 0.54 #edf8f9,
            stop: 1 #e6f3f6
        );
    }}
    QFrame#cardMuted[deliveryRailConsole="true"] {{
        border-radius: 16px;
        border: 1px solid #bad6de;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f7fcfd,
            stop: 0.58 #ffffff,
            stop: 1 #edf8f1
        );
    }}
    QFrame#cardMuted[deliveryRailConsole="true"][railTone="success"] {{
        border-color: #9fcfba;
    }}
    QFrame#cardMuted[deliveryRailConsole="true"][railTone="accent"] {{
        border-color: #8fc5d0;
    }}
    QFrame#cardMuted[deliveryRailConsole="true"][railTone="warning"] {{
        border-color: #e2c17e;
    }}
    QWidget[deliveryRailModeDock="true"] {{
        background: transparent;
    }}
    QToolButton[deliveryRailModeSwitch="true"] {{
        min-height: 22px;
        border-radius: 11px;
        padding: 0 8px;
        font-size: 10px;
        font-weight: 800;
    }}
    QFrame#cardMuted[deliveryMissionMap="true"] {{
        border-radius: 14px;
        border: 1px solid #c6dce3;
        background: rgba(248, 252, 253, 0.80);
    }}
    QToolButton[deliveryMissionNode="true"] {{
        min-height: 22px;
        border-radius: 10px;
        padding: 0 5px;
        background: rgba(255, 255, 255, 0.74);
        border: 1px solid #ccdde4;
        color: #31586a;
        font-size: 9px;
        font-weight: 800;
    }}
    QToolButton[deliveryMissionNode="true"][missionTone="success"] {{
        background: #f0fbf5;
        border-color: #9fd2bb;
    }}
    QToolButton[deliveryMissionNode="true"][missionTone="accent"] {{
        background: #eef9fb;
        border-color: #94c9d3;
    }}
    QToolButton[deliveryMissionNode="true"][missionTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
    }}
    QToolButton[deliveryMissionNode="true"][missionTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
    }}
    QToolButton[deliveryMissionNode="true"]:checked {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #0c6d78,
            stop: 1 #2f9ca0
        );
        border-color: #075a69;
        color: #ffffff;
    }}
    QFrame#card[deliveryMissionInspector="true"] {{
        border-radius: 16px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.78);
    }}
    QFrame#cardMuted[deliveryFocusShell="true"] {{
        border-radius: 15px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.70);
    }}
    QFrame#card[deliveryGateCompact="true"] {{
        border-radius: 15px;
        border: 1px solid #c4d8dc;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #fffaf0,
            stop: 0.62 #ffffff,
            stop: 1 #edf8f2
        );
    }}
    QFrame#cardMuted[deliveryGateHero="true"] {{
        border-radius: 12px;
        border: 1px solid #bdd6dc;
        background: rgba(248, 252, 253, 0.90);
    }}
    QFrame#cardMuted[deliveryGateHero="true"][deliveryGateLayer="summary"] {{
        border: 1px solid #b6d6dd;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #f6fbfc,
            stop: 0.52 #ffffff,
            stop: 1 #eef7f0
        );
    }}
    QWidget[deliveryGateLayeredMatrix="true"] {{
        background: transparent;
    }}
    QFrame#cardMuted[deliveryGateTile="true"] {{
        border-radius: 10px;
        border: 1px solid #d0e1e7;
        background: rgba(255, 255, 255, 0.78);
    }}
    QFrame#cardMuted[deliveryGateLayerTile="true"][deliveryGateGroup="artifact"] {{
        border-left: 3px solid #8bbfca;
        background: rgba(250, 253, 253, 0.90);
    }}
    QFrame#cardMuted[deliveryGateLayerTile="true"][deliveryGateGroup="validation"] {{
        border-left: 3px solid #e1ad6c;
        background: rgba(255, 251, 244, 0.88);
    }}
    QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="success"] {{
        border-color: #9cccb4;
    }}
    QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="accent"] {{
        border-color: #b9d7df;
    }}
    QFrame#cardMuted[deliveryGateLayerTile="true"][gateTone="warning"] {{
        border-color: #e4c488;
    }}
    QFrame#cardMuted[deliveryGateTile="true"] QLabel#chip {{
        font-size: 9px;
        padding: 0 2px;
    }}
    QFrame#cardMuted[deliveryGateTile="true"] QLabel#metricValue[compactMetric="true"] {{
        font-size: 11px;
        font-weight: 800;
        padding: 0;
    }}
    QFrame#cardMuted[deliveryDetailShell="true"],
    QFrame#cardMuted[deliveryBatchPanel="true"],
    QFrame#cardMuted[deliveryInspectorSection="true"] {{
        border-radius: 14px;
        border: 1px solid #d0e1e7;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[batchMetricTile="true"] {{
        border-radius: 11px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.78);
    }}
    QFrame#cardMuted[deliveryRailActionDock="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.88);
    }}
    QFrame#cardMuted[deliveryRailActionDock="true"][deliveryRailActionMatrix="true"] {{
        border-color: #aecfd8;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f8fdfd,
            stop: 0.54 #ffffff,
            stop: 1 #eff8ef
        );
    }}
    QToolButton[deliveryRailAction="true"] {{
        min-height: 28px;
        border-radius: 12px;
        padding: 0 7px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
        font-weight: 800;
    }}
    QToolButton[deliveryRailAction="true"][actionTone="success"] {{
        background: #f0fbf5;
        border-color: #9fd2bb;
        color: #0f6946;
    }}
    QToolButton[deliveryRailAction="true"][actionTone="accent"] {{
        background: #edf9fb;
        border-color: #8fc5d0;
        color: #0b6475;
    }}
    QToolButton[deliveryRailAction="true"][actionTone="warning"] {{
        background: #fff7e4;
        border-color: #e6c98e;
        color: #8a5d0e;
    }}
    QToolButton[deliveryRailAction="true"][actionTone="danger"] {{
        background: #fff0ef;
        border-color: #e8b3ad;
        color: #a5382d;
    }}
    QFrame#card[projectSiteCommandDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.48 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[projectSiteMetric="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QPushButton[projectSiteCommandButton="true"] {{
        min-height: 26px;
        border-radius: 13px;
        padding: 0 10px;
    }}
    QFrame#cardMuted[projectSiteOpsRail="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(247, 252, 253, 0.86);
    }}
    QFrame#cardMuted[projectSiteActionDock="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.90);
    }}
    QFrame#cardMuted[projectSiteOpsTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.70);
    }}
    QFrame#cardMuted[projectSiteNextCard="true"] {{
        border-radius: 14px;
        border: 1px solid #c8dce4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 1 #edf9fa
        );
    }}
    QToolButton[projectSiteRailAction="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 7px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QFrame#card[metadataEditorShell="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.88);
    }}
    QFrame#card[metadataCockpitDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.50 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[metadataSummaryTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[metadataEditorPanel="true"] {{
        border-radius: 14px;
        border: 1px solid #d2e3e9;
        background: rgba(247, 252, 253, 0.74);
    }}
    QFrame#card[metadataProfileDock="true"] {{
        border-radius: 16px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 1 #edf9fa
        );
    }}
    QPushButton[metadataActionButton="true"] {{
        min-height: 26px;
        border-radius: 13px;
        padding: 0 10px;
        border: 1px solid #b8d4dd;
        background: #f7fcfd;
        color: #0e5f6e;
    }}
    QFrame#card[realtimeCommandDock="true"] {{
        border-radius: 18px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #edf9fa,
            stop: 0.52 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#card[realtimeCommandDock="true"][realtimeCaptureConsole="true"] {{
        border-color: #9fcbd4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #edf9fa,
            stop: 0.42 #ffffff,
            stop: 0.72 #f7fbf3,
            stop: 1 #e5f4ef
        );
    }}
    QLabel[captureConsoleTitle="true"] {{
        color: #073f49;
        letter-spacing: 0.4px;
    }}
    QLabel[captureConsoleSubtitle="true"] {{
        color: #4f6f76;
    }}
    QLabel#chip[captureConsoleChip="true"] {{
        border: 1px solid #8dc7d0;
        background: #d6f2f5;
        color: #073f49;
    }}
    QFrame#cardMuted[realtimeTargetDock="true"],
    QFrame#cardMuted[realtimeMetricDock="true"],
    QFrame#cardMuted[realtimeActionDock="true"],
    QFrame#cardMuted[realtimeStatusDock="true"] {{
        border-radius: 14px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.74);
    }}
    QFrame#cardMuted[captureConsoleCell="true"] {{
        border-radius: 16px;
        border: 1px solid #b8d4dd;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #ffffff,
            stop: 1 #f4fbfc
        );
    }}
    QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="target"] {{
        border-left: 4px solid #2f8ea1;
    }}
    QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="signal"] {{
        border-left: 4px solid #7dbb91;
    }}
    QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="command"] {{
        border-left: 4px solid #d5a642;
    }}
    QFrame#cardMuted[captureConsoleCell="true"][captureCellRole="link"] {{
        border-left: 4px solid #5f9daa;
    }}
    QLabel[captureStageTag="true"] {{
        padding: 1px 8px;
        border-radius: 8px;
        background: rgba(232, 248, 250, 0.92);
        color: #0e5f6e;
        font-weight: 700;
    }}
    QWidget[captureMetricStrip="true"] {{
        background: transparent;
    }}
    QFrame#cardMuted[realtimeStatusDock="true"][evidenceTone="success"] {{
        border-color: #8ecfba;
        background: rgba(231, 250, 241, 0.88);
    }}
    QFrame#cardMuted[realtimeStatusDock="true"][evidenceTone="warning"] {{
        border-color: #efc980;
        background: rgba(255, 249, 235, 0.90);
    }}
    QFrame#cardMuted[realtimeStatusDock="true"][evidenceTone="danger"] {{
        border-color: #e99d9a;
        background: rgba(255, 240, 240, 0.90);
    }}
    QToolButton[realtimeMetricToggle="true"] {{
        min-height: 26px;
        border-radius: 13px;
        padding: 0 10px;
        background: #e8f8fa;
        border: 1px solid #8dc7d0;
        color: #0e5f6e;
    }}
    QToolButton[realtimeMetricToggle="true"]:checked {{
        background: #d6f2f5;
        border-color: #56aeb9;
        color: #073f49;
    }}
    QToolButton[realtimeActionButton="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 7px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QToolButton[realtimeActionButton="true"][capturePrimaryAction="true"] {{
        background: #0e5f6e;
        border-color: #0a4b56;
        color: #ffffff;
        font-weight: 700;
    }}
    QToolButton[realtimeActionButton="true"][captureDangerAction="true"] {{
        background: #fff1f1;
        border-color: #e09a96;
        color: #8a2e28;
        font-weight: 700;
    }}
    QToolButton[realtimeActionButton="true"][captureSecondaryAction="true"] {{
        background: #ffffff;
        border-color: #c8dce4;
        color: #315f68;
    }}
    QFrame#card[realtimeSummaryDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.50 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#card[realtimeSummaryDock="true"][realtimeTelemetryRibbon="true"] {{
        border-color: #bed5c5;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff8e8,
            stop: 0.45 #ffffff,
            stop: 1 #edf8ef
        );
    }}
    QFrame#cardMuted[realtimeSessionTile="true"],
    QFrame#cardMuted[realtimeSummaryMetric="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#card[realtimePlotPanel="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.88);
    }}
    QFrame#card[realtimePlotPanel="true"][realtimeSignalScope="true"] {{
        border-color: #b9d6de;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #ffffff,
            stop: 1 #f3fafb
        );
    }}
    QLabel[realtimeScopeReadout="true"] {{
        padding: 4px 10px;
        border-radius: 10px;
        background: rgba(232, 248, 250, 0.76);
        color: #315f68;
    }}
    QFrame#cardMuted[realtimeEvidenceRail="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(247, 252, 253, 0.86);
    }}
    QFrame#cardMuted[realtimeEvidenceRail="true"][realtimeEvidenceConsole="true"] {{
        border-color: #bcd5dd;
        background: rgba(244, 251, 252, 0.92);
    }}
    QFrame#card[deviceDetailHeaderDock="true"] {{
        border-radius: 18px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 0.48 #f7fcfd,
            stop: 1 #e7f5f1
        );
    }}
    QPushButton[deviceDetailHeaderButton="true"],
    QToolButton[deviceDetailViewSwitch="true"] {{
        min-height: 30px;
        border-radius: 14px;
        padding: 0 12px;
        border: 1px solid #b8d4dd;
        background: #f7fcfd;
        color: #0e3344;
    }}
    QToolButton[deviceDetailViewSwitch="true"]:checked {{
        background: #d6f2f5;
        border-color: #56aeb9;
        color: #073f49;
    }}
    QFrame#card[deviceDetailSummaryDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.50 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[deviceDetailSummaryMetric="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[deviceOpsRail="true"] {{
        border-radius: 18px;
        border: 1px solid #c8dce4;
        background: rgba(247, 252, 253, 0.86);
    }}
    QFrame#cardMuted[deviceOpsActionDock="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.90);
    }}
    QToolButton[deviceOpsRailAction="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 8px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QFrame#cardMuted[deviceOpsTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.70);
    }}
    QFrame#cardMuted[deviceOpsNextCard="true"] {{
        border-radius: 14px;
        border: 1px solid #c8dce4;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #ffffff,
            stop: 1 #edf9fa
        );
    }}
    QFrame#card[deviceFleetStatusDock="true"] {{
        border-radius: 18px;
        border: 1px solid #c8d9ca;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff9e9,
            stop: 0.46 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#card[deviceFleetStatusDock="true"][deviceFleetTelemetryStrip="true"] {{
        border-color: #bed5c5;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #fff8e8,
            stop: 0.36 #ffffff,
            stop: 0.72 #f7fbf3,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[deviceFleetMetric="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[deviceFleetMetric="true"][deviceFleetMetricKey="recent_alarm"] {{
        border-radius: 14px;
    }}
    QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="success"] {{
        border-color: #8ecfba;
        background: rgba(231, 250, 241, 0.86);
    }}
    QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="accent"] {{
        border-color: #8dc7d0;
        background: rgba(232, 248, 250, 0.88);
    }}
    QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="warning"] {{
        border-color: #efc980;
        background: rgba(255, 249, 235, 0.88);
    }}
    QFrame#cardMuted[deviceFleetMetric="true"][fleetMetricTone="danger"] {{
        border-color: #e09a96;
        background: rgba(255, 241, 241, 0.90);
    }}
    QLabel[fleetMetricLabel="true"] {{
        color: #315f68;
        font-weight: 700;
    }}
    QLabel[fleetMetricValue="true"] {{
        color: #09293a;
        font-weight: 800;
    }}
    QFrame#card[fieldReadinessDock="true"] {{
        border-radius: 18px;
        border: 1px solid #bfd8df;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 #edf9fa,
            stop: 0.52 #ffffff,
            stop: 1 #e7f5f1
        );
    }}
    QFrame#cardMuted[fieldReadinessTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.72);
    }}
    QFrame#cardMuted[fieldActionDock="true"] {{
        border-radius: 14px;
        border: 1px solid #bfd8df;
        background: rgba(244, 251, 252, 0.88);
    }}
    QToolButton[fieldActionButton="true"] {{
        min-height: 24px;
        border-radius: 12px;
        padding: 0 7px;
        background: #f7fcfd;
        border: 1px solid #b8d4dd;
        color: #0e5f6e;
    }}
    QFrame#cardMuted[deviceOperationsCompactInspector="true"] {{
        border-radius: 18px;
        border: 1px solid #bcd5dd;
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #f4fbfc,
            stop: 0.50 #ffffff,
            stop: 1 #eef8f5
        );
    }}
    QWidget[deviceInspectorTitle="true"] {{
        background: transparent;
    }}
    QToolButton[deviceInspectorModeSwitch="true"] {{
        min-height: 28px;
        border-radius: 14px;
        padding: 0 14px;
        border: 1px solid #b8d4dd;
        background: #ffffff;
        color: #315f68;
        font-weight: 700;
    }}
    QToolButton[deviceInspectorModeSwitch="true"]:checked {{
        background: #d6f2f5;
        border-color: #56aeb9;
        color: #073f49;
    }}
    QStackedWidget[deviceInspectorStack="true"] {{
        background: transparent;
    }}
    QFrame[deviceInspectorSection="true"] {{
        border-radius: 14px;
    }}
    QFrame[deviceInspectorSection="true"][deviceInspectorSectionRole="mission"] {{
        border-color: #bed5c5;
        background: rgba(255, 249, 235, 0.74);
    }}
    QFrame[deviceInspectorSection="true"][deviceInspectorSectionRole="evidence"] {{
        border-color: #b9d6de;
        background: rgba(244, 251, 252, 0.82);
    }}
    QFrame[deviceInspectorSection="true"][deviceInspectorSectionRole="activity"] {{
        border-color: #c8dce4;
        background: rgba(247, 252, 253, 0.86);
    }}
    QFrame#cardMuted[deviceEvidenceTile="true"] {{
        border-radius: 12px;
        border: 1px solid #d2e3e9;
        background: rgba(255, 255, 255, 0.76);
    }}
    QFrame#cardMuted[deviceEvidenceTile="true"][evidenceTone="success"] {{
        border-color: #8ecfba;
        background: rgba(231, 250, 241, 0.86);
    }}
    QFrame#cardMuted[deviceEvidenceTile="true"][evidenceTone="accent"] {{
        border-color: #8dc7d0;
        background: rgba(232, 248, 250, 0.88);
    }}
    QFrame#cardMuted[deviceEvidenceTile="true"][evidenceTone="warning"] {{
        border-color: #efc980;
        background: rgba(255, 249, 235, 0.88);
    }}
    QLabel[deviceEvidenceLabel="true"] {{
        color: #315f68;
        font-weight: 700;
    }}
    QLabel[deviceEvidenceValue="true"] {{
        color: #09293a;
        font-weight: 800;
    }}
    QTableWidget[deviceInspectorActivityTable="true"],
    QListWidget[deviceInspectorEventList="true"] {{
        border-radius: 12px;
        border: 1px solid #c8dce4;
        background: rgba(255, 255, 255, 0.78);
    }}
    QTableWidget[deviceInspectorActivityTable="true"]::item {{
        padding: 2px 6px;
    }}
    QListWidget[deviceInspectorEventList="true"]::item {{
        padding: 3px 7px;
        margin: 1px 3px;
        border-radius: 8px;
    }}
    QFrame#cardMuted[closureCompactTile="true"] {{
        border-radius: 14px;
        border: 1px solid #c4dce4;
        background: rgba(255, 255, 255, 0.62);
    }}
    QFrame#cardMuted[closureCompactTile="true"][evidenceTone="success"] {{
        border-color: #8ecfba;
        background: rgba(231, 250, 241, 0.86);
    }}
    QFrame#cardMuted[closureCompactTile="true"][evidenceTone="accent"] {{
        border-color: #8dc7d0;
        background: rgba(232, 248, 250, 0.88);
    }}
    QFrame#cardMuted[closureCompactTile="true"][evidenceTone="warning"] {{
        border-color: #efc980;
        background: rgba(255, 249, 235, 0.90);
    }}
    QFrame#cardMuted[closureCompactTile="true"][evidenceTone="danger"] {{
        border-color: #e99d9a;
        background: rgba(255, 240, 240, 0.90);
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
