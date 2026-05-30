from __future__ import annotations

import re
from typing import Any

from models.hf_models import FrameQuality

STATUS_BIT_DESCRIPTIONS = {
    0: "system_running",
    1: "data_abnormal",
    2: "motor_speed_abnormal",
    3: "temperature_abnormal",
    4: "lamp_power_high",
    5: "lamp_power_low",
    6: "photocurrent_abnormal",
    7: "pulse_not_synchronized",
    8: "co2_signal_over_range",
    9: "h2o_signal_over_range",
    10: "co2_delta_over_range",
    11: "h2o_delta_over_range",
    12: "co2_signal_low",
    13: "h2o_signal_low",
}


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


def parse_status_register(value: Any) -> dict[str, Any]:
    text = str(value or "").strip().upper()
    if not text:
        return {
            "status_register": "",
            "status_bits": {},
            "active_faults": [],
            "status_ok": None,
        }
    try:
        register = int(text, 16)
    except ValueError:
        return {
            "status_register": text,
            "status_bits": {},
            "active_faults": [] if text in {"OK", "NORMAL"} else ["unparsed_status_text"],
            "status_ok": text in {"OK", "NORMAL"},
        }
    status_bits = {
        name: bool(register & (1 << bit))
        for bit, name in STATUS_BIT_DESCRIPTIONS.items()
    }
    active_faults = [
        name
        for bit, name in STATUS_BIT_DESCRIPTIONS.items()
        if bit != 0 and bool(register & (1 << bit))
    ]
    return {
        "status_register": text.zfill(4),
        "status_bits": status_bits,
        "active_faults": active_faults,
        "status_ok": bool(status_bits.get("system_running", False)) and not active_faults,
    }


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
    if len(parts) > 4 and _to_float(parts[4]) is None:
        return None
    if len(parts) > 5 and _to_float(parts[5]) is None:
        return None
    quality = FrameQuality.FULL if len(parts) >= 9 else FrameQuality.PARTIAL
    status = parse_status_register(parts[8] if len(parts) > 8 else None)
    status_text = parts[8] if len(parts) > 8 else None
    if status["status_ok"] is True:
        status_text = "OK"
    elif status["active_faults"]:
        status_text = "FAULT:" + "|".join(status["active_faults"])
    return {
        "mode": 1,
        "device_id": parts[1] if len(parts) > 1 else None,
        "co2_ppm": co2,
        "h2o_mmol": h2o,
        "co2_signal": _to_float(parts[4]) if len(parts) > 4 else None,
        "h2o_signal": _to_float(parts[5]) if len(parts) > 5 else None,
        "chamber_temp_c": _to_float(parts[6]) if len(parts) > 6 else None,
        "pressure_kpa": _to_float(parts[7]) if len(parts) > 7 else None,
        "status_text": status_text,
        "status_register": status["status_register"],
        "status_bits": status["status_bits"],
        "active_faults": status["active_faults"],
        "status_ok": status["status_ok"],
        "checksum": parts[9] if len(parts) > 9 else None,
        "frame_quality": quality,
    }
