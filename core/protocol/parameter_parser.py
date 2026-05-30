from __future__ import annotations

from typing import Any

from core.protocol.mode1_parser import _clean_token


def parse_parameter_response(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip().strip("<>")
    if not candidate:
        return None
    parts = [_clean_token(part) for part in candidate.split(",")]
    if len(parts) < 2:
        return None
    if parts[0].upper() != "YGAS":
        return None
    if not _is_device_id(parts[1]):
        return None
    if len(parts) == 2:
        values = []
    elif len(parts) == 3 and _is_parameter_value(parts[2]):
        values = parts[2:]
    elif (
        len(parts) == 6
        and _is_float(parts[2])
        and str(parts[3]).isdigit()
        and str(parts[4]).upper() in {"N", "E", "O"}
        and str(parts[5]).isdigit()
    ):
        values = parts[2:]
    else:
        return None
    return {
        "response_type": "parameter",
        "device_id": parts[1],
        "values": values,
        "value_count": len(values),
        "raw": candidate,
    }


def _is_device_id(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return text == "FFF" or (len(text) == 3 and all(ch in "0123456789ABCDEF" for ch in text))


def _is_parameter_value(value: Any) -> bool:
    text = str(value or "").strip()
    if _is_float(text):
        return True
    return bool(text) and text.upper() in {"N", "E", "O", "TRUE", "FALSE"}


def _is_float(value: Any) -> bool:
    try:
        float(str(value))
        return True
    except ValueError:
        return False
