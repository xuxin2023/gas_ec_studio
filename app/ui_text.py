from __future__ import annotations

from core.exports.public_text import PUBLIC_REFERENCE_REPLACEMENTS, public_safe_text

UI_REFERENCE_REPLACEMENTS = PUBLIC_REFERENCE_REPLACEMENTS


def ui_safe_text(value: object) -> str:
    return public_safe_text(value)
