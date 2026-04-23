from __future__ import annotations

import re
from typing import Any

from models.hf_models import FrameQuality


def _clean_token(token: Any) -> str:
    text = str(token or "").strip()
    text = text.lstrip("<>[](){} \t\r\n")
    for marker in (">", "]", ")", "}", "\r", "\n"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip().strip("<>[](){} \t\r\n")


def _to_float(value: str) -> float | None:
    text = str(value or "").strip()
    try:
        return float(text)
    except Exception:
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text)
        if not match:
            return None
        return float(match.group(0))


def parse_mode1_frame(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip().strip("<>")
    if "YGAS" not in candidate.upper():
        return None
    parts = [_clean_token(part) for part in candidate.split(",")]
    if len(parts) < 4:
        return None
    head = parts[0].upper()
    if "YGAS" not in head:
        return None
    co2 = _to_float(parts[2]) if len(parts) > 2 else None
    h2o = _to_float(parts[3]) if len(parts) > 3 else None
    if co2 is None or h2o is None:
        return None
    quality = FrameQuality.FULL if len(parts) >= 9 else FrameQuality.PARTIAL
    return {
        "mode": 1,
        "device_id": parts[1] if len(parts) > 1 else None,
        "co2_ppm": co2,
        "h2o_mmol": h2o,
        "co2_signal": _to_float(parts[4]) if len(parts) > 4 else None,
        "h2o_signal": _to_float(parts[5]) if len(parts) > 5 else None,
        "chamber_temp_c": _to_float(parts[6]) if len(parts) > 6 else None,
        "pressure_kpa": _to_float(parts[7]) if len(parts) > 7 else None,
        "status_text": parts[8] if len(parts) > 8 else None,
        "frame_quality": quality,
    }
