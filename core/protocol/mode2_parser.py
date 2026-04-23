from __future__ import annotations

from typing import Any

from core.protocol.mode1_parser import _clean_token, _to_float
from models.hf_models import FrameQuality


MODE2_KEYS = [
    "co2_ppm",
    "h2o_mmol",
    "co2_density",
    "h2o_density",
    "co2_ratio_f",
    "co2_ratio_raw",
    "h2o_ratio_f",
    "h2o_ratio_raw",
    "ref_signal",
    "co2_signal",
    "h2o_signal",
    "chamber_temp_c",
    "case_temp_c",
    "pressure_kpa",
]
MODE2_STANDARD_FIELD_COUNT = 2 + len(MODE2_KEYS) + 1


def parse_mode2_frame(text: str) -> dict[str, Any] | None:
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
    quality = FrameQuality.FULL if len(parts) >= MODE2_STANDARD_FIELD_COUNT else FrameQuality.PARTIAL
    parsed: dict[str, Any] = {
        "mode": 2,
        "device_id": parts[1] if len(parts) > 1 else None,
        "frame_quality": quality,
        "status_text": parts[16] if len(parts) > 16 else None,
    }
    for key in MODE2_KEYS:
        parsed[key] = None
    for index, key in enumerate(MODE2_KEYS, start=2):
        if len(parts) > index:
            parsed[key] = _to_float(parts[index])
    for extra_index, token in enumerate(parts[17:], start=1):
        parsed[f"extra_{extra_index:02d}"] = token
    return parsed
