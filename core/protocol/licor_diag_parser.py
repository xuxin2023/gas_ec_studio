from __future__ import annotations

import json
import re
from typing import Any

from models.hf_models import FrameQuality


LICOR_DIAGNOSTIC_BIT_LABELS = {
    0: "diagnostic_bit_0",
    1: "diagnostic_bit_1",
    2: "diagnostic_bit_2",
    3: "diagnostic_bit_3",
    4: "diagnostic_bit_4",
    5: "diagnostic_bit_5",
    6: "diagnostic_bit_6",
    7: "diagnostic_bit_7",
    8: "diagnostic_bit_8",
    9: "diagnostic_bit_9",
    10: "diagnostic_bit_10",
    11: "diagnostic_bit_11",
    12: "diagnostic_bit_12",
    13: "diagnostic_bit_13",
    14: "diagnostic_bit_14",
    15: "diagnostic_bit_15",
}


def parse_licor_diag_frame(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip().strip("<>")
    if not candidate:
        return None
    parsed = _parse_json_payload(candidate) or _parse_key_value_payload(candidate) or _parse_csv_payload(candidate)
    if not parsed:
        return None

    model = str(parsed.get("model") or parsed.get("instrument_model") or parsed.get("device_id") or "").strip()
    profile_id = _profile_id_for_model(model) or _profile_id_for_model(str(parsed.get("profile_id", "")))
    if profile_id == "":
        return None
    parsed["profile_id"] = profile_id
    parsed["instrument_family"] = "enclosed_path_irga" if profile_id == "licor_li7200_family" else "open_path_irga"
    parsed["device_id"] = str(parsed.get("device_id") or model or profile_id)
    parsed["mode"] = 1

    diagnostic_word = _coerce_int(parsed.get("diagnostic_word", parsed.get("status_word", 0)))
    if diagnostic_word is not None:
        parsed["diagnostic_word"] = diagnostic_word
    status_ok = _coerce_bool(parsed.get("status_ok"))
    if status_ok is None:
        status_ok = diagnostic_word in (None, 0)
    parsed["status_ok"] = status_ok
    active_faults = _diagnostic_word_faults(diagnostic_word)
    if not status_ok and not active_faults:
        active_faults = ["status_ok_false"]
    parsed["active_faults"] = active_faults
    parsed["status_text"] = "OK" if status_ok and not active_faults else "FAULT:" + "|".join(active_faults)

    quality = FrameQuality.FULL if parsed.get("co2_ppm") is not None and parsed.get("h2o_mmol") is not None else FrameQuality.PARTIAL
    parsed["frame_quality"] = quality
    parsed["normalized_payload"] = _normalized_payload(parsed)
    return parsed


def _parse_json_payload(candidate: str) -> dict[str, Any] | None:
    if not candidate.startswith("{"):
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    profile_hint = str(payload.get("profile_id") or payload.get("model") or payload.get("instrument_model") or "").lower()
    if "licor" not in profile_hint and "li7200" not in profile_hint and "li7500" not in profile_hint:
        return None
    return _normalize_alias_payload(payload)


def _parse_key_value_payload(candidate: str) -> dict[str, Any] | None:
    if "=" not in candidate:
        return None
    lower = candidate.lower()
    if not any(token in lower for token in ("licor", "li7200", "li-7200", "li7500", "li-7500")):
        return None
    payload: dict[str, Any] = {}
    for key, value in re.findall(r"([A-Za-z0-9_\-]+)\s*=\s*([^,\s;]+)", candidate):
        payload[_normalize_key(key)] = value.strip()
    if not payload:
        return None
    if "model" not in payload:
        first = re.split(r"[\s,;]+", candidate.strip(), maxsplit=1)[0]
        payload["model"] = first
    return _normalize_alias_payload(payload)


def _parse_csv_payload(candidate: str) -> dict[str, Any] | None:
    parts = [part.strip().strip('"') for part in candidate.split(",")]
    if len(parts) < 4:
        return None
    marker = parts[0].lower().replace("-", "")
    if marker not in {"licor", "li7200", "li7500", "li7200rs", "li7500a", "li7500ds"}:
        return None
    model = parts[1] if marker == "licor" and len(parts) > 1 else parts[0]
    offset = 2 if marker == "licor" else 1
    payload = {
        "model": model,
        "device_id": model,
        "co2_ppm": _coerce_float(_part(parts, offset)),
        "h2o_mmol": _coerce_float(_part(parts, offset + 1)),
        "co2_signal_strength_pct": _coerce_float(_part(parts, offset + 2)),
        "h2o_signal_strength_pct": _coerce_float(_part(parts, offset + 3)),
        "reference_signal_pct": _coerce_float(_part(parts, offset + 4)),
        "diagnostic_word": _coerce_int(_part(parts, offset + 5)),
        "cell_pressure_kpa": _coerce_float(_part(parts, offset + 6)),
        "cell_temperature_c": _coerce_float(_part(parts, offset + 7)),
    }
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def _normalize_alias_payload(payload: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "co2": "co2_ppm",
        "co2_ppm": "co2_ppm",
        "co2_molfrac": "co2_ppm",
        "h2o": "h2o_mmol",
        "h2o_mmol": "h2o_mmol",
        "h2o_mmol_mol": "h2o_mmol",
        "co2_signal": "co2_signal_strength_pct",
        "co2_signal_pct": "co2_signal_strength_pct",
        "co2_signal_strength": "co2_signal_strength_pct",
        "co2_signal_strength_pct": "co2_signal_strength_pct",
        "co2_agc": "co2_signal_strength_pct",
        "h2o_signal": "h2o_signal_strength_pct",
        "h2o_signal_pct": "h2o_signal_strength_pct",
        "h2o_signal_strength": "h2o_signal_strength_pct",
        "h2o_signal_strength_pct": "h2o_signal_strength_pct",
        "h2o_agc": "h2o_signal_strength_pct",
        "reference_signal": "reference_signal_pct",
        "reference_signal_pct": "reference_signal_pct",
        "ref_signal": "reference_signal_pct",
        "diag": "diagnostic_word",
        "diagnostic": "diagnostic_word",
        "diagnostic_word": "diagnostic_word",
        "diagnostic_value": "diagnostic_word",
        "status_word": "diagnostic_word",
        "cell_p": "cell_pressure_kpa",
        "cell_pressure": "cell_pressure_kpa",
        "cell_pressure_kpa": "cell_pressure_kpa",
        "cell_t": "cell_temperature_c",
        "cell_temp": "cell_temperature_c",
        "cell_temperature": "cell_temperature_c",
        "cell_temperature_c": "cell_temperature_c",
        "model": "model",
        "instrument_model": "model",
        "profile_id": "profile_id",
        "device_id": "device_id",
        "status_ok": "status_ok",
    }
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        target = aliases.get(_normalize_key(key))
        if not target:
            continue
        if target in {"co2_ppm", "h2o_mmol", "co2_signal_strength_pct", "h2o_signal_strength_pct", "reference_signal_pct", "cell_pressure_kpa", "cell_temperature_c"}:
            normalized[target] = _coerce_float(value)
        elif target == "diagnostic_word":
            normalized[target] = _coerce_int(value)
        else:
            normalized[target] = value
    return {key: value for key, value in normalized.items() if value is not None and value != ""}


def _normalized_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(parsed.get("profile_id", ""))
    import_key = "li7200_diagnostic_import" if profile_id == "licor_li7200_family" else "li7500_diagnostic_import"
    payload = {
        "licor_primary_analyzer_import": {
            "status": "decoded",
            "format": "licor_diagnostic_record",
            "parser": "parse_licor_diag_frame",
            "source_reference": {
                "eddypro_engine": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "eddypro_gui": "https://github.com/LI-COR-Environmental/eddypro-gui",
            },
            "limitations": [
                "Parser normalizes LI-COR diagnostic text/CSV/JSON records; it does not implement proprietary binary control protocol branches.",
                "Diagnostic-word bit labels are generic unless site-specific LI-COR status maps are configured downstream.",
            ],
        },
        import_key: {"status": "decoded"},
        "profile_id": profile_id,
        "instrument_family": parsed.get("instrument_family", ""),
        "co2_signal_strength_pct": parsed.get("co2_signal_strength_pct"),
        "h2o_signal_strength_pct": parsed.get("h2o_signal_strength_pct"),
        "reference_signal_pct": parsed.get("reference_signal_pct"),
        "diagnostic_word": parsed.get("diagnostic_word"),
        "status_ok": parsed.get("status_ok"),
        "active_faults": list(parsed.get("active_faults", []) or []),
    }
    for key in ("cell_pressure_kpa", "cell_temperature_c"):
        if parsed.get(key) is not None:
            payload[key] = parsed.get(key)
    return payload


def _profile_id_for_model(model: str) -> str:
    text = str(model or "").strip().lower().replace("-", "").replace("_", "")
    if "li7200" in text or text in {"7200", "7200rs"}:
        return "licor_li7200_family"
    if "li7500" in text or text in {"7500", "7500a", "7500ds"}:
        return "licor_li7500_family"
    return ""


def _diagnostic_word_faults(word: int | None) -> list[str]:
    if word in (None, 0):
        return []
    bits = [bit for bit in range(max(1, int(word).bit_length())) if int(word) & (1 << bit)]
    return [f"diagnostic_word:{word}:{LICOR_DIAGNOSTIC_BIT_LABELS.get(bit, f'bit_{bit}')}" for bit in bits]


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")


def _part(parts: list[str], index: int) -> str:
    return parts[index] if index < len(parts) else ""


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", str(value))
        return float(match.group(0)) if match else None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        number = _coerce_float(value)
        return int(number) if number is not None else None


def _coerce_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "ok", "pass", "normal"}:
        return True
    if text in {"0", "false", "no", "n", "fault", "fail", "bad", "error"}:
        return False
    return None
