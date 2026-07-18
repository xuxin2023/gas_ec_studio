from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def resource_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str | Path) -> Path:
    return resource_root() / Path(relative_path)


def application_icon() -> QIcon:
    return QIcon(str(resource_path("app/assets/gas_ec_studio_icon.png")))


def release_notes_text() -> str:
    changelog_path = resource_path("CHANGELOG.md")
    try:
        return changelog_path.read_text(encoding="utf-8")
    except OSError:
        return "# 更新日志\n\n当前发布包未包含更新日志。"


def user_guide_text() -> str:
    guide_path = resource_path("docs/user_guide.md")
    try:
        return guide_path.read_text(encoding="utf-8")
    except OSError:
        return "# 使用说明\n\n当前发布包未包含使用说明。"
