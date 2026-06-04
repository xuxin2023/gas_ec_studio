"""RP analysis core: lag strategies, detrend, flux, stationarity, turbulence, statistical screening."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from scipy import signal as scipy_signal  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    scipy_signal = None

from core.protocol.gas_analyzer_profiles import get_gas_analyzer_profile
from core.protocol.mode1_parser import parse_status_register
from models.hf_models import NormalizedHFFrame


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LagAnalysisResult:
    lag_seconds: float
    confidence: float
    lag_curve_x: list[float]
    lag_curve_y: list[float]
    co2_lag_seconds: float
    h2o_lag_seconds: float
    fallback_reason: str = ""


@dataclass(slots=True)
class WindowPreparedResult:
    u: np.ndarray
    v: np.ndarray
    w: np.ndarray
    co2_ppm: np.ndarray
    h2o_mmol: np.ndarray
    ch4_ppb: np.ndarray
    n2o_ppb: np.ndarray
    pressure_kpa: np.ndarray
    temp_c: np.ndarray
    cell_pressure_kpa: np.ndarray
    cell_temp_c: np.ndarray
    sample_count: int
    valid_sample_count: int
    continuity_ratio: float
    missing_ratio: float
    max_gap_seconds: float
    issues: list[str]
    qc_reasons: list[str]
    diagnostics: dict[str, Any]


@dataclass(slots=True)
class RotationResult:
    u: np.ndarray
    v: np.ndarray
    w: np.ndarray
    mode: str
    applied: bool
    reason: str
    alpha_deg: float
    beta_deg: float


@dataclass(slots=True)
class SonicCorrectionResult:
    u: np.ndarray
    v: np.ndarray
    w: np.ndarray
    detail: dict[str, Any]


@dataclass(slots=True)
class CrosswindCorrectionResult:
    temp_c: np.ndarray
    detail: dict[str, Any]


@dataclass(slots=True)
class StationarityMetrics:
    score: float | None
    detail: dict[str, Any]


@dataclass(slots=True)
class TurbulenceMetrics:
    score: float | None
    ustar: float | None
    detail: dict[str, Any]


@dataclass(slots=True)
class UncertaintyMetrics:
    detail: dict[str, Any]


_DEFAULT_UNCERTAINTY_CONFIDENCE_LEVEL = 0.95
_DRY_AIR_MOLAR_MASS_KG_MOL = 0.02896546
_WATER_MOLAR_MASS_KG_MOL = 0.01801528
_CONFIDENCE_Z_LOOKUP: tuple[tuple[float, float], ...] = (
    (0.68, 1.0),
    (0.80, 1.2816),
    (0.90, 1.6449),
    (0.95, 1.96),
    (0.99, 2.5758),
)


def _confidence_multiplier(confidence_level: float) -> float:
    level = float(np.clip(confidence_level, 0.50, 0.99))
    nearest = min(_CONFIDENCE_Z_LOOKUP, key=lambda item: abs(item[0] - level))
    return nearest[1]


def build_uncertainty_band(
    *,
    estimate: float,
    random_error: float | None = None,
    relative_uncertainty: float | None = None,
    confidence_level: float = _DEFAULT_UNCERTAINTY_CONFIDENCE_LEVEL,
) -> dict[str, float | None]:
    level = float(np.clip(confidence_level, 0.50, 0.99))
    sigma_error: float | None = None
    if isinstance(random_error, (int, float)):
        sigma_error = abs(float(random_error))
    elif isinstance(relative_uncertainty, (int, float)):
        sigma_error = abs(float(estimate)) * abs(float(relative_uncertainty))

    if sigma_error is None:
        return {
            "confidence_level": round(level, 3),
            "random_error_sigma": None,
            "uncertainty_band_half_width": None,
            "interval_lower": None,
            "interval_upper": None,
        }

    half_width = sigma_error * _confidence_multiplier(level)
    return {
        "confidence_level": round(level, 3),
        "random_error_sigma": round(sigma_error, 6),
        "uncertainty_band_half_width": round(half_width, 6),
        "interval_lower": round(float(estimate) - half_width, 6),
        "interval_upper": round(float(estimate) + half_width, 6),
    }


# ---------------------------------------------------------------------------
# Configuration normalization
# ---------------------------------------------------------------------------

_ROTATION_MODE_MAP: dict[str, str] = {
    "none": "none",
    "no_rotation": "none",
    "不旋转": "none",
    "single": "single",
    "单旋转": "single",
    "double": "double",
    "双旋转": "double",
    "2d": "double",
    "triple": "triple",
    "三重旋转": "triple",
    "3d": "triple",
    "triple_rotation": "triple",
    "planar_fit": "planar_fit",
    "平面拟合": "planar_fit",
    "pf": "planar_fit",
    "sector_wise_planar_fit": "sector_wise_planar_fit",
    "swpf": "sector_wise_planar_fit",
    "sector_planar_fit": "sector_wise_planar_fit",
    "sector_wise_planar_fit_no_velocity_bias": "sector_wise_planar_fit_no_velocity_bias",
    "swpf_nvb": "sector_wise_planar_fit_no_velocity_bias",
}

_DETREND_MODE_MAP: dict[str, str] = {
    "block_mean": "block_mean",
    "blockmean": "block_mean",
    "块均值": "block_mean",
    "linear": "linear",
    "线性去趋势": "linear",
    "线性": "linear",
    "running_mean": "running_mean",
    "滑动均值": "running_mean",
    "running": "running_mean",
    "moving_average": "running_mean",
    "movingaverage": "running_mean",
    "moving_avg": "running_mean",
    "movingavg": "running_mean",
    "exponential_running_mean": "exponential_running_mean",
    "指数滑动均值": "exponential_running_mean",
    "ewma": "exponential_running_mean",
    "exp_running_mean": "exponential_running_mean",
}

_LAG_STRATEGY_MAP: dict[str, str] = {
    "none": "none",
    "无滞后": "none",
    "no_lag": "none",
    "constant": "constant",
    "固定滞后": "constant",
    "fixed": "constant",
    "covariance_max": "covariance_max",
    "协方差最大": "covariance_max",
    "cov_max": "covariance_max",
    "covariance_max_with_default": "covariance_max_with_default",
    "协方差最大带默认": "covariance_max_with_default",
    "cov_max_default": "covariance_max_with_default",
}

_DENSITY_CORRECTION_MODE_MAP: dict[str, str] = {
    "wpl": "wpl",
    "WPL": "wpl",
    "density_correction": "wpl",
    "密度修正": "wpl",
    "mixing_ratio": "mixing_ratio",
    "混合比优先": "mixing_ratio",
    "mixing_ratio_priority": "mixing_ratio",
    "none": "none",
    "不修正": "none",
    "no_correction": "none",
    "raw": "none",
}


def normalize_rotation_mode(raw: Any, default: str = "double") -> str:
    key = str(raw).strip().lower() if raw is not None else ""
    return _ROTATION_MODE_MAP.get(key, default)


def normalize_detrend_mode(raw: Any, default: str = "block_mean") -> str:
    key = str(raw).strip().lower() if raw is not None else ""
    return _DETREND_MODE_MAP.get(key, default)


def normalize_lag_strategy(raw: Any, default: str = "covariance_max") -> str:
    key = str(raw).strip().lower() if raw is not None else ""
    return _LAG_STRATEGY_MAP.get(key, default)


def normalize_density_correction_mode(raw: Any, default: str = "wpl") -> str:
    key = str(raw).strip() if raw is not None else ""
    return _DENSITY_CORRECTION_MODE_MAP.get(key, default)


# ---------------------------------------------------------------------------
# Basic utility functions
# ---------------------------------------------------------------------------

def infer_sample_rate(rows: Iterable[NormalizedHFFrame], fallback_hz: float = 10.0) -> float:
    timestamps = [row.timestamp.timestamp() for row in rows]
    if len(timestamps) < 2:
        return max(1.0, float(fallback_hz))
    deltas = np.diff(np.array(timestamps, dtype=float))
    deltas = deltas[deltas > 0]
    if deltas.size == 0:
        return max(1.0, float(fallback_hz))
    return max(1.0, float(1.0 / np.median(deltas)))


def pick_window_slices(total_samples: int, sample_rate_hz: float, block_minutes: float = 30.0) -> list[tuple[int, int]]:
    min_samples = max(64, int(sample_rate_hz * 12.0))
    if total_samples < min_samples:
        return []
    target_samples = int(max(min_samples, block_minutes * 60.0 * sample_rate_hz))
    if total_samples < target_samples and total_samples >= min_samples * 3:
        desired_windows = min(8, max(3, total_samples // min_samples))
        target_samples = max(min_samples, total_samples // desired_windows)
    elif total_samples < target_samples:
        target_samples = total_samples
    slices: list[tuple[int, int]] = []
    start = 0
    while start + min_samples <= total_samples:
        end = min(total_samples, start + target_samples)
        if (end - start) < min_samples:
            break
        slices.append((start, end))
        start = end
    if not slices:
        slices.append((0, total_samples))
    return slices


# ---------------------------------------------------------------------------
# Series building
# ---------------------------------------------------------------------------

def build_window_series(rows: list[NormalizedHFFrame], sample_rate_hz: float) -> WindowPreparedResult:
    n = len(rows)
    if n == 0:
        return WindowPreparedResult(
            u=np.array([], dtype=float), v=np.array([], dtype=float), w=np.array([], dtype=float),
            co2_ppm=np.array([], dtype=float), h2o_mmol=np.array([], dtype=float),
            ch4_ppb=np.array([], dtype=float),
            n2o_ppb=np.array([], dtype=float),
            pressure_kpa=np.array([], dtype=float), temp_c=np.array([], dtype=float),
            cell_pressure_kpa=np.array([], dtype=float), cell_temp_c=np.array([], dtype=float),
            sample_count=0, valid_sample_count=0, continuity_ratio=0.0, missing_ratio=1.0,
            max_gap_seconds=0.0, issues=["empty_window"], qc_reasons=["window has no usable samples"],
            diagnostics={
                "u_valid_ratio": 0.0,
                "v_valid_ratio": 0.0,
                "w_raw_valid_ratio": 0.0,
                "n2o_valid_ratio": 0.0,
                "cell_pressure_valid_ratio": 0.0,
                "cell_temp_valid_ratio": 0.0,
                "cell_thermodynamics_status": "not_available",
            },
        )

    co2_raw = np.array([np.nan if r.co2_ppm is None else float(r.co2_ppm) for r in rows], dtype=float)
    h2o_raw = np.array([np.nan if r.h2o_mmol is None else float(r.h2o_mmol) for r in rows], dtype=float)
    ch4_raw = np.array([np.nan if r.ch4_ppb is None else float(r.ch4_ppb) for r in rows], dtype=float)
    n2o_raw = np.array([np.nan if r.n2o_ppb is None else float(r.n2o_ppb) for r in rows], dtype=float)
    pres_raw = np.array([np.nan if r.pressure_kpa is None else float(r.pressure_kpa) for r in rows], dtype=float)
    temp_raw = np.array([np.nan if r.chamber_temp_c is None else float(r.chamber_temp_c) for r in rows], dtype=float)

    u_raw, v_raw, w_raw, has_w = _extract_wind_components(rows)
    cell_pressure_raw, cell_temp_raw = _extract_cell_thermodynamics(rows)

    co2 = _fill_missing(co2_raw)
    h2o = _fill_missing(h2o_raw)
    ch4 = _fill_missing(ch4_raw)
    n2o = _fill_missing(n2o_raw)
    pressure = _fill_missing(pres_raw)
    temp = _fill_missing(temp_raw)
    cell_pressure = _fill_missing(cell_pressure_raw) if np.any(~np.isnan(cell_pressure_raw)) else np.array([], dtype=float)
    cell_temp = _fill_missing(cell_temp_raw) if np.any(~np.isnan(cell_temp_raw)) else np.array([], dtype=float)
    u = _fill_missing(u_raw)
    v = _fill_missing(v_raw)
    w = _fill_missing(w_raw)

    issues: list[str] = []
    qc_reasons: list[str] = []

    _check_series_issues(co2_raw, "co2_ppm", issues, qc_reasons)
    _check_series_issues(h2o_raw, "h2o_mmol", issues, qc_reasons)
    _check_series_issues(pres_raw, "pressure_kpa", issues, qc_reasons)
    _check_series_issues(temp_raw, "temp_c", issues, qc_reasons)
    _check_series_issues(w_raw, "w", issues, qc_reasons)

    timestamps = [r.timestamp.timestamp() for r in rows]
    continuity_ratio, max_gap_seconds = _compute_continuity(timestamps, sample_rate_hz)
    missing_count = int(np.sum(np.isnan(co2_raw)) + np.sum(np.isnan(h2o_raw)))
    missing_ratio = float(missing_count) / max(1, 2 * n)
    valid_count = n - int(np.sum(np.isnan(co2_raw) | np.isnan(h2o_raw) | np.isnan(w_raw)))

    u_valid_ratio = float(np.sum(~np.isnan(u_raw)) / max(1, n))
    v_valid_ratio = float(np.sum(~np.isnan(v_raw)) / max(1, n))
    w_valid_ratio = float(np.sum(~np.isnan(w_raw)) / max(1, n))
    ch4_valid_ratio = float(np.sum(~np.isnan(ch4_raw)) / max(1, n))
    n2o_valid_ratio = float(np.sum(~np.isnan(n2o_raw)) / max(1, n))
    cell_pressure_valid_ratio = float(np.sum(~np.isnan(cell_pressure_raw)) / max(1, n))
    cell_temp_valid_ratio = float(np.sum(~np.isnan(cell_temp_raw)) / max(1, n))
    cell_thermodynamics_status = (
        "available" if cell_pressure_valid_ratio > 0.0 or cell_temp_valid_ratio > 0.0 else "not_available"
    )

    diagnostics: dict[str, Any] = {
        "u_valid_ratio": u_valid_ratio,
        "v_valid_ratio": v_valid_ratio,
        "w_raw_valid_ratio": w_valid_ratio,
        "ch4_valid_ratio": ch4_valid_ratio,
        "n2o_valid_ratio": n2o_valid_ratio,
        "cell_pressure_valid_ratio": cell_pressure_valid_ratio,
        "cell_temp_valid_ratio": cell_temp_valid_ratio,
        "cell_thermodynamics_status": cell_thermodynamics_status,
    }

    return WindowPreparedResult(
        u=u, v=v, w=w, co2_ppm=co2, h2o_mmol=h2o,
        ch4_ppb=ch4,
        n2o_ppb=n2o,
        pressure_kpa=pressure, temp_c=temp,
        cell_pressure_kpa=cell_pressure, cell_temp_c=cell_temp,
        sample_count=n, valid_sample_count=valid_count,
        continuity_ratio=continuity_ratio, missing_ratio=missing_ratio,
        max_gap_seconds=max_gap_seconds, issues=issues, qc_reasons=qc_reasons,
        diagnostics=diagnostics,
    )


def _extract_wind_components(rows: list[NormalizedHFFrame]) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    u_vals: list[float] = []
    v_vals: list[float] = []
    w_vals: list[float] = []
    has_w = False
    for row in rows:
        payload = _load_payload(row.raw_text) or _load_payload(row.status_text or "")
        u_val = _payload_value(payload, ("u", "u_ms", "u_mps", "wind_u"))
        v_val = _payload_value(payload, ("v", "v_ms", "v_mps", "wind_v"))
        w_val = _payload_value(payload, ("w", "w_ms", "w_mps", "vertical_velocity", "vertical_wind"))
        u_vals.append(u_val)
        v_vals.append(v_val)
        if not np.isnan(w_val):
            has_w = True
        w_vals.append(w_val)
    return np.array(u_vals, dtype=float), np.array(v_vals, dtype=float), np.array(w_vals, dtype=float), has_w


_CELL_PRESSURE_ALIASES = (
    "cell_pressure_kpa",
    "sample_cell_pressure_kpa",
    "analyzer_pressure_kpa",
    "cell_pressure",
    "cell_p_kpa",
    "p_cell_kpa",
    "cell_press",
    "p_cell",
    "cell_pressure_pa",
)
_CELL_TEMP_ALIASES = (
    "cell_temperature_c",
    "cell_temp_c",
    "sample_cell_temperature_c",
    "analyzer_temperature_c",
    "cell_temperature",
    "cell_temp",
    "t_cell_c",
    "t_cell",
    "cell_temperature_k",
)


def _extract_cell_thermodynamics(rows: list[NormalizedHFFrame]) -> tuple[np.ndarray, np.ndarray]:
    pressure_vals: list[float] = []
    temp_vals: list[float] = []
    for row in rows:
        payload = _load_payload(row.raw_text) or _load_payload(row.status_text or "")
        pressure_vals.append(_coerce_cell_pressure_kpa(_payload_value(payload, _CELL_PRESSURE_ALIASES)))
        temp_vals.append(_coerce_cell_temp_c(_payload_value(payload, _CELL_TEMP_ALIASES)))
    return np.array(pressure_vals, dtype=float), np.array(temp_vals, dtype=float)


def _coerce_cell_pressure_kpa(value: float) -> float:
    if np.isnan(value):
        return np.nan
    magnitude = abs(float(value))
    if magnitude > 2000.0:
        return float(value) / 1000.0
    if magnitude > 200.0:
        return float(value) / 10.0
    return float(value)


def _coerce_cell_temp_c(value: float) -> float:
    if np.isnan(value):
        return np.nan
    numeric = float(value)
    return numeric - 273.15 if numeric > 150.0 else numeric


def _load_payload(payload: str) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _merged_frame_payload(row: NormalizedHFFrame) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload_text in (row.raw_text, row.status_text or ""):
        payload = _load_payload(payload_text)
        if payload:
            merged.update(payload)
    return merged


def _payload_value(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> float:
    if not payload:
        return np.nan
    for key in keys:
        if payload.get(key) is not None:
            return float(payload[key])
    return np.nan


def _payload_metric_series(payloads: list[dict[str, Any]], aliases: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for payload in payloads:
        value = _payload_lookup(payload, aliases)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            values.append(numeric)
    return values


def _payload_int_series(payloads: list[dict[str, Any]], aliases: tuple[str, ...]) -> list[int]:
    values: list[int] = []
    for payload in payloads:
        value = _payload_lookup(payload, aliases)
        if value is None:
            continue
        try:
            values.append(int(str(value).strip(), 0))
            continue
        except (TypeError, ValueError):
            pass
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            values.append(int(numeric))
    return values


def _payload_bool_series(
    payloads: list[dict[str, Any]],
    aliases: tuple[str, ...],
    *,
    true_tokens: set[str] | None = None,
    false_tokens: set[str] | None = None,
) -> list[bool]:
    values: list[bool] = []
    for payload in payloads:
        value = _payload_lookup(payload, aliases)
        if value is None:
            continue
        values.append(_coerce_payload_bool(value, true_tokens=true_tokens, false_tokens=false_tokens))
    return values


def _payload_lookup(payload: Any, aliases: tuple[str, ...]) -> Any:
    normalized_aliases = {_normalize_payload_key(alias) for alias in aliases}
    for key, value in _flatten_payload(payload):
        if _normalize_payload_key(key) in normalized_aliases:
            return value
    return None


def _flatten_payload(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(payload, dict):
        items: list[tuple[str, Any]] = []
        for key, value in payload.items():
            joined = f"{prefix}_{key}" if prefix else str(key)
            items.extend(_flatten_payload(value, joined))
        return items
    if isinstance(payload, list):
        items: list[tuple[str, Any]] = []
        for index, value in enumerate(payload):
            joined = f"{prefix}_{index}" if prefix else str(index)
            items.extend(_flatten_payload(value, joined))
        return items
    return [(prefix, payload)]


def _normalize_payload_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _coerce_payload_bool(
    value: Any,
    *,
    true_tokens: set[str] | None = None,
    false_tokens: set[str] | None = None,
) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if false_tokens and text in false_tokens:
        return False
    if true_tokens:
        return text in true_tokens
    return text in {"1", "true", "yes", "y", "ok", "pass", "locked", "clean"}


def _payload_status_flags(payloads: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    status_aliases = {
        "li7700_status",
        "li7700_diagnostic_status",
        "diagnostic_status",
        "instrument_status",
        "ch4_status_code",
        "status_code",
        "diagnostic_flag",
        "diagnostic_flags",
    }
    fault_tokens = ("fault", "fail", "error", "blocked", "dirty", "unlocked", "not_locked", "no_lock", "bad")
    for payload in payloads:
        for key, value in _flatten_payload(payload):
            normalized = _normalize_payload_key(key)
            if normalized not in status_aliases and not normalized.endswith("_status"):
                continue
            text = str(value).strip().lower()
            if not text or text in {"ok", "pass", "passed", "normal", "locked", "clean", "0"}:
                continue
            if any(token in text for token in fault_tokens):
                flags.append(f"{normalized}:{text}")
    return flags


def _li7700_status_word_flags(status_words: list[int], config: dict[str, Any]) -> list[str]:
    if not status_words:
        return []
    raw_allowed = config.get("allowed_status_words", config.get("allowed_diagnostic_words", [0]))
    if isinstance(raw_allowed, (str, int, float)):
        raw_allowed = [raw_allowed]
    allowed: set[int] = set()
    for value in raw_allowed or [0]:
        try:
            allowed.add(int(str(value).strip(), 0))
        except (TypeError, ValueError):
            continue
    bit_map = _li7700_status_bit_map(config)
    flags: list[str] = []
    for word in status_words:
        if word in allowed:
            continue
        if word == 0:
            continue
        bits = [bit for bit in range(0, max(1, int(word).bit_length())) if int(word) & (1 << bit)]
        if not bits:
            flags.append(f"status_word:{word}")
            continue
        for bit in bits:
            label = bit_map.get(bit, f"bit_{bit}")
            flags.append(f"status_word:{word}:{label}")
    return flags


def _li7700_status_bit_map(config: dict[str, Any]) -> dict[int, str]:
    raw_map = config.get("status_bit_map", config.get("diagnostic_bit_map", {}))
    if isinstance(raw_map, str):
        parsed: dict[int, str] = {}
        for part in raw_map.replace(",", "|").split("|"):
            if not part.strip() or ":" not in part:
                continue
            key, value = part.split(":", 1)
            try:
                parsed[int(key.strip().removeprefix("bit"), 0)] = value.strip()
            except ValueError:
                continue
        return parsed
    if not isinstance(raw_map, dict):
        return {}
    parsed = {}
    for key, value in raw_map.items():
        try:
            parsed[int(str(key).strip().removeprefix("bit"), 0)] = str(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _series_mean(values: list[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _series_min(values: list[float]) -> float | None:
    return float(min(values)) if values else None


def _li7700_status_check(
    check_id: str,
    passed: bool,
    *,
    measured: Any,
    threshold: Any,
    severity: str,
    failure_message: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else ("fail" if severity == "fail" else "warn"),
        "severity": severity,
        "measured": measured,
        "threshold": threshold,
        "message": "LI-7700 status diagnostic check passed." if passed else failure_message,
    }


def _ygas_status_check(
    check_id: str,
    passed: bool,
    *,
    measured: Any,
    threshold: Any,
    severity: str,
    failure_message: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else ("fail" if severity == "fail" else "warn"),
        "severity": severity,
        "measured": measured,
        "threshold": threshold,
        "message": "YGAS primary analyzer diagnostic check passed." if passed else failure_message,
    }


def _fill_missing(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    if not np.isnan(values).any():
        return values
    indices = np.arange(values.size, dtype=float)
    valid = ~np.isnan(values)
    if not np.any(valid):
        return np.zeros_like(values)
    return np.interp(indices, indices[valid], values[valid])


def _check_series_issues(raw: np.ndarray, name: str, issues: list[str], qc_reasons: list[str]) -> None:
    valid = raw[~np.isnan(raw)]
    if valid.size == 0:
        issues.append(f"{name}_missing")
        qc_reasons.append(f"{name} series is missing")
        return
    if valid.size < max(10, raw.size * 0.1):
        issues.append(f"{name}_insufficient")
        qc_reasons.append(f"{name} valid sample count is insufficient")
    if float(np.std(valid)) < 1e-6:
        issues.append(f"{name}_constant")
        qc_reasons.append(f"{name} series is constant")


def _compute_continuity(timestamps: list[float], sample_rate_hz: float) -> tuple[float, float]:
    if len(timestamps) < 2:
        return 0.0, 0.0
    deltas = np.diff(np.array(timestamps, dtype=float))
    expected = 1.0 / max(1.0, sample_rate_hz)
    max_gap = float(np.max(deltas)) if deltas.size > 0 else 0.0
    max_gap_seconds = max(0.0, max_gap - expected)
    good = np.sum(deltas <= expected * 1.5)
    ratio = float(good / max(1, deltas.size))
    return ratio, max_gap_seconds


# ---------------------------------------------------------------------------
# Sonic coordinate and head/flow-angle correction
# ---------------------------------------------------------------------------

def apply_sonic_corrections(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    config: dict[str, Any] | None = None,
) -> SonicCorrectionResult:
    cfg = dict(config or {})
    enabled = bool(cfg.get("enabled", False))
    method = str(cfg.get("method", "eddypro_sonic_coordinate_v1") or "eddypro_sonic_coordinate_v1")
    if not enabled:
        return SonicCorrectionResult(
            u=u,
            v=v,
            w=w,
            detail={
                "status": "disabled",
                "applied": False,
                "method": method,
                "provenance": "Sonic correction disabled by configuration.",
                "steps": [],
                "limitations": [],
            },
        )

    u_corr = np.array(u, dtype=float, copy=True)
    v_corr = np.array(v, dtype=float, copy=True)
    w_corr = np.array(w, dtype=float, copy=True)
    steps: list[dict[str, Any]] = []
    limitations = [
        "Nakai 2006 and Nakai-Shimoyama 2012 angle-of-attack coefficient paths are implemented for supported Gill sonic families; official field fixture parity is still required.",
        "Model orientation rules cover common EddyPro sonic coordinate cases and should be validated against site metadata.",
    ]

    wind_format = _normalize_sonic_text(cfg.get("wind_format", cfg.get("wformat", "cartesian")))
    if wind_format in {"polar_w", "polar"}:
        direction_deg = np.array(u_corr, dtype=float, copy=True)
        speed = np.array(v_corr, dtype=float, copy=True)
        radians = np.deg2rad(direction_deg)
        u_corr = speed * np.cos(radians)
        v_corr = -speed * np.sin(radians)
        steps.append({"name": "polar_to_cartesian", "wind_format": wind_format})
    elif wind_format == "axis":
        a1 = np.array(u_corr, dtype=float, copy=True)
        a2 = np.array(v_corr, dtype=float, copy=True)
        a3 = np.array(w_corr, dtype=float, copy=True)
        u_corr = (2.0 * a1 - a2 - a3) / 2.1213
        v_corr = (a3 - a2) / 1.2247
        w_corr = (a1 + a2 + a3) / 2.1213
        steps.append({"name": "gill_axis_to_uvw", "wind_format": wind_format})

    offsets = {
        "u": _safe_float(cfg.get("u_offset_ms", cfg.get("u_offset", 0.0)), default=0.0),
        "v": _safe_float(cfg.get("v_offset_ms", cfg.get("v_offset", 0.0)), default=0.0),
        "w": _safe_float(cfg.get("w_offset_ms", cfg.get("w_offset", 0.0)), default=0.0),
    }
    if any(abs(value) > 0.0 for value in offsets.values()):
        u_corr = u_corr - offsets["u"]
        v_corr = v_corr - offsets["v"]
        w_corr = w_corr - offsets["w"]
        steps.append({"name": "sonic_bias_offsets", "offsets_ms": offsets})

    model = _normalize_sonic_text(cfg.get("sonic_model", cfg.get("model", "")))
    wind_reference = _normalize_sonic_text(cfg.get("wind_reference", cfg.get("wref", "")))
    model_steps = _apply_sonic_model_orientation(
        u_corr,
        v_corr,
        model=model,
        wind_reference=wind_reference,
        apply_model_orientation=bool(cfg.get("apply_model_orientation", True)),
    )
    u_corr = model_steps.pop("u")
    v_corr = model_steps.pop("v")
    if model_steps.get("steps"):
        steps.extend(model_steps["steps"])

    north_offset_deg = _safe_float(cfg.get("north_offset_deg", cfg.get("north_offset", 0.0)), default=0.0)
    model_north_offset = _model_north_offset_adjustment(model)
    effective_north_offset = north_offset_deg + model_north_offset
    if abs(effective_north_offset) > 1e-12:
        u_corr, v_corr = _rotate_horizontal(u_corr, v_corr, effective_north_offset)
        steps.append(
            {
                "name": "north_offset_rotation",
                "configured_north_offset_deg": north_offset_deg,
                "model_adjustment_deg": model_north_offset,
                "effective_north_offset_deg": effective_north_offset,
            }
        )

    wboost_mode = _normalize_sonic_text(cfg.get("gill_wm_w_boost", cfg.get("w_boost", "auto")))
    firmware = str(cfg.get("sonic_firmware", cfg.get("firmware", "")) or "")
    if wboost_mode == "auto":
        wboost_mode = "apply" if model in {"wm", "wmpro", "windmaster", "windmasterpro"} and _gill_wm_firmware_has_w_bug(firmware) else "none"
    if wboost_mode in {"apply", "remove"}:
        w_corr = _apply_gill_wm_w_boost(w_corr, mode=wboost_mode)
        steps.append({"name": f"gill_windmaster_w_boost_{wboost_mode}", "firmware": firmware})

    aoa_cfg = cfg.get("angle_of_attack", {})
    if isinstance(aoa_cfg, dict) and bool(aoa_cfg.get("enabled", False)):
        u_corr, v_corr, w_corr, aoa_step = _apply_angle_of_attack_correction(
            u_corr,
            v_corr,
            w_corr,
            aoa_cfg,
            model=model,
        )
        steps.append(aoa_step)

    applied = bool(steps)
    aoa_steps = [step for step in steps if str(step.get("family", "")) == "angle_of_attack"]
    detail = {
        "status": "applied" if applied else "no_effect",
        "applied": applied,
        "method": method,
        "sonic_model": str(cfg.get("sonic_model", cfg.get("model", "")) or ""),
        "sonic_firmware": firmware,
        "wind_format": wind_format,
        "wind_reference": wind_reference,
        "north_offset_deg": north_offset_deg,
        "effective_north_offset_deg": effective_north_offset,
        "steps": steps,
        "angle_of_attack_status": str(aoa_steps[-1].get("status", "not_configured")) if aoa_steps else "not_configured",
        "angle_of_attack_method": str(aoa_steps[-1].get("method", "")) if aoa_steps else "",
        "angle_of_attack_summary": dict(aoa_steps[-1]) if aoa_steps else {},
        "mean_w_before": _nanmean_or_none(w),
        "mean_w_after": _nanmean_or_none(w_corr),
        "std_w_before": _nanstd_or_none(w),
        "std_w_after": _nanstd_or_none(w_corr),
        "provenance": (
            "Sonic coordinate/head correction v1 derived from documented EddyPro processing stages: "
            "coordinate normalization, sonic bias offsets, model orientation offsets, Gill WindMaster W-boost handling, "
            "and optional calibrated angle-of-attack gain."
        ),
        "source_reference": {
            "eddypro_engine_files": [
                "src/src_rp/adjust_sonic_coordinates.f90",
                "src/src_rp/gill_wm_w_boost.f90",
                "src/src_rp/aoa_calibration.f90",
                "src/src_rp/aoa_cal_nakai_2012.f90",
            ],
        },
        "limitations": limitations if applied else [],
    }
    return SonicCorrectionResult(u=u_corr, v=v_corr, w=w_corr, detail=detail)


def _normalize_sonic_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result):
        return default
    return result


def _rotate_horizontal(u: np.ndarray, v: np.ndarray, angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    radians = math.radians(float(angle_deg))
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return u * cos_a - v * sin_a, u * sin_a + v * cos_a


def _apply_sonic_model_orientation(
    u: np.ndarray,
    v: np.ndarray,
    *,
    model: str,
    wind_reference: str,
    apply_model_orientation: bool,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    u_out = np.array(u, dtype=float, copy=True)
    v_out = np.array(v, dtype=float, copy=True)
    if not apply_model_orientation:
        return {"u": u_out, "v": v_out, "steps": steps}
    if model in {"hs_50", "hs_100", "r3_50", "r3_100", "r3a_100", "wm", "wmpro", "windmaster", "windmasterpro"} and wind_reference == "axis":
        u_out, v_out = _rotate_horizontal(u_out, v_out, 30.0)
        steps.append({"name": "gill_axis_to_spar_rotation", "angle_deg": 30.0, "model": model})
    elif model == "r2":
        u_out, v_out = _rotate_horizontal(-u_out, -v_out, 30.0)
        steps.append({"name": "gill_r2_spar_rotation", "angle_deg": 30.0, "model": model})
    elif model in {"usa1_standard", "usa1_fast"}:
        v_out = -v_out
        steps.append({"name": "metek_usa1_right_handed_v_flip", "model": model})
    return {"u": u_out, "v": v_out, "steps": steps}


def _model_north_offset_adjustment(model: str) -> float:
    if model in {"csat3", "csat3b"}:
        return -180.0
    if model in {"usoni3_cage_mp", "usoni3_classa_mp"}:
        return 90.0
    if model in {"81000", "81000v", "81000re", "81000vre"}:
        return -90.0
    return 0.0


def _gill_wm_firmware_has_w_bug(firmware: str) -> bool:
    parts = [part for part in str(firmware).replace("-", ".").split(".") if part]
    if len(parts) < 2 or parts[0] != "2329":
        return False
    try:
        return int(parts[1]) < 700
    except ValueError:
        return False


def _apply_gill_wm_w_boost(w: np.ndarray, *, mode: str) -> np.ndarray:
    positive = w >= 0.0
    corrected = np.array(w, dtype=float, copy=True)
    if mode == "apply":
        corrected[positive] = corrected[positive] * 1.166
        corrected[~positive] = corrected[~positive] * 1.289
    elif mode == "remove":
        corrected[positive] = corrected[positive] / 1.166
        corrected[~positive] = corrected[~positive] / 1.289
    return corrected


def _apply_angle_of_attack_correction(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    config: dict[str, Any],
    *,
    model: str = "",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    method = _normalize_sonic_text(config.get("method", config.get("aoa_method", "calibrated_gain")))
    if method in {"auto", "model_default", "eddypro_default"}:
        method = _infer_nakai_angle_of_attack_method(model)
    if method in {"nakai_06", "nakai_2006", "nakai_et_al_2006"}:
        return _apply_nakai_2006_angle_of_attack(u, v, w, config)
    if method in {"nakai_12", "nakai_2012", "nakai_shimoyama_2012"}:
        return _apply_nakai_2012_angle_of_attack(u, v, w, config)
    return _apply_calibrated_angle_of_attack_gain(u, v, w, config)


def _infer_nakai_angle_of_attack_method(model: str) -> str:
    normalized = _normalize_sonic_text(model)
    if normalized in {"wm", "wm_pro", "wmpro", "windmaster", "windmaster_pro", "windmasterpro"}:
        return "nakai_2012"
    if normalized in {"r2", "r3", "r3_50", "r3_100", "r3a_100"}:
        return "nakai_2006"
    return "calibrated_gain"


def _angle_and_direction(u: np.ndarray, v: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    horizontal = np.sqrt(u ** 2 + v ** 2)
    attack_deg = np.where(
        horizontal > 1e-12,
        np.degrees(np.arctan2(w, horizontal)),
        np.where(w >= 0.0, 90.0, -90.0),
    )
    wind_direction_deg = np.degrees(np.arctan2(v, u)) % 360.0
    ratio = np.divide(w, horizontal, out=np.zeros_like(w, dtype=float), where=horizontal > 1e-12)
    return attack_deg, wind_direction_deg, ratio


def _steffensen_angle(
    initial_deg: np.ndarray,
    wind_direction_deg: np.ndarray,
    ratio: np.ndarray,
    gx_func: Any,
    *,
    max_iterations: int = 12,
) -> tuple[np.ndarray, int]:
    x0 = np.array(initial_deg, dtype=float, copy=True)
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        x1 = gx_func(x0, wind_direction_deg, ratio)
        x2 = gx_func(x1, wind_direction_deg, ratio)
        denominator = x2 - 2.0 * x1 + x0
        x3 = np.where(np.abs(denominator) < 0.01, x2, x0 - ((x1 - x0) ** 2) / denominator)
        if np.all(np.abs(x3 - x0) < 1e-5):
            return x3, iterations
        x0 = x3
    return x0, iterations


def _safe_divide_or_keep(values: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return np.divide(
        values,
        denominator,
        out=np.array(values, dtype=float, copy=True),
        where=np.isfinite(denominator) & (np.abs(denominator) > 1e-9),
    )


def _apply_nakai_2012_angle_of_attack(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    attack_deg, wind_direction_deg, ratio = _angle_and_direction(u, v, w)
    max_angle = _safe_float(config.get("max_abs_angle_deg", 90.0), default=90.0)
    attack_limited = np.clip(attack_deg, -abs(max_angle), abs(max_angle))
    solved_deg, iterations = _steffensen_angle(attack_limited, wind_direction_deg, ratio, _nakai_2012_gx)
    solved_deg = np.clip(solved_deg, -abs(max_angle), abs(max_angle))
    sinerr = _nakai_2012_sinerr(solved_deg, wind_direction_deg)
    coserr = _nakai_2012_coserr(solved_deg, wind_direction_deg)
    u_corr = _safe_divide_or_keep(u, coserr)
    v_corr = _safe_divide_or_keep(v, coserr)
    w_corr = _safe_divide_or_keep(w, sinerr)
    return (
        u_corr,
        v_corr,
        w_corr,
        _angle_of_attack_step(
            name="nakai_2012_angle_of_attack",
            method="nakai_2012",
            before_attack_deg=attack_deg,
            solved_attack_deg=solved_deg,
            u_before=u,
            v_before=v,
            w_before=w,
            u_after=u_corr,
            v_after=v_corr,
            w_after=w_corr,
            iterations=iterations,
            coefficient_set="nakai_shimoyama_2012_polynomial",
        ),
    )


def _apply_nakai_2006_angle_of_attack(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    attack_deg, wind_direction_deg, ratio = _angle_and_direction(u, v, w)
    max_angle = _safe_float(config.get("max_abs_angle_deg", 90.0), default=90.0)
    attack_limited = np.clip(attack_deg, -abs(max_angle), abs(max_angle))
    solved_deg, iterations = _steffensen_angle(attack_limited, wind_direction_deg, ratio, _nakai_2006_gx)
    solved_deg = np.clip(solved_deg, -abs(max_angle), abs(max_angle))
    sinerr = np.sin(np.radians(solved_deg)) * _nakai_2006_sinerr(solved_deg) + 0.0195
    coserr = _nakai_2006_coserr(solved_deg, wind_direction_deg)
    horizontal_factor = np.divide(
        np.cos(np.radians(solved_deg)),
        coserr,
        out=np.ones_like(solved_deg, dtype=float),
        where=np.isfinite(coserr) & (np.abs(coserr) > 1e-9),
    )
    u_corr = u * horizontal_factor
    v_corr = v * horizontal_factor
    horizontal_after = np.sqrt(u_corr ** 2 + v_corr ** 2)
    w_from_horizontal = np.tan(np.radians(solved_deg)) * horizontal_after
    w_from_sinerr = np.divide(
        w * np.sin(np.radians(solved_deg)),
        sinerr,
        out=np.array(w, dtype=float, copy=True),
        where=np.isfinite(sinerr) & (np.abs(sinerr) > 1e-9),
    )
    horizontal_before = np.sqrt(u ** 2 + v ** 2)
    w_corr = np.where(horizontal_before > 1e-12, w_from_horizontal, w_from_sinerr)
    return (
        u_corr,
        v_corr,
        w_corr,
        _angle_of_attack_step(
            name="nakai_2006_angle_of_attack",
            method="nakai_2006",
            before_attack_deg=attack_deg,
            solved_attack_deg=solved_deg,
            u_before=u,
            v_before=v,
            w_before=w,
            u_after=u_corr,
            v_after=v_corr,
            w_after=w_corr,
            iterations=iterations,
            coefficient_set="nakai_2006_polynomial",
        ),
    )


def _nakai_2012_sinerr(aoa_deg: np.ndarray, wind_direction_deg: np.ndarray) -> np.ndarray:
    aoa = np.array(aoa_deg, dtype=float, copy=True)
    wd = np.array(wind_direction_deg, dtype=float, copy=True)
    positive = aoa > 0.0
    aoa[positive] = -aoa[positive]
    wd[positive] = wd[positive] + 180.0
    a = (-3.19818998552857e-10, -2.69824417931343e-8, 4.16728613218081e-6, 4.85252964763967e-4, 1.67354200080193e-2)
    b = (5.92731123831391e-10, 1.44129103378194e-7, 1.20670183305798e-5, 3.92584527104954e-4, 3.82901759130896e-3)
    a_aoa = a[0] * aoa**5 + a[1] * aoa**4 + a[2] * aoa**3 + a[3] * aoa**2 + a[4] * aoa + 1.0
    b_aoa = b[0] * aoa**5 + b[1] * aoa**4 + b[2] * aoa**3 + b[3] * aoa**2 + b[4] * aoa
    return a_aoa - b_aoa * np.sin(np.radians(3.0 * wd))


def _nakai_2012_coserr(aoa_deg: np.ndarray, wind_direction_deg: np.ndarray) -> np.ndarray:
    aoa = np.array(aoa_deg, dtype=float, copy=True)
    wd = np.array(wind_direction_deg, dtype=float, copy=True)
    positive = aoa > 0.0
    aoa[positive] = -aoa[positive]
    wd[positive] = wd[positive] + 180.0
    aoa = np.maximum(aoa, -70.0)
    c = (-1.20804470033571e-9, -1.58051314507891e-7, -4.95504975706944e-6, 1.60799801968464e-5, 1.28143810766839e-3)
    d = (2.27154016448720e-9, 3.85646200219364e-7, 2.03402753902096e-5, 3.94248403622007e-4, 9.18428193641156e-4)
    c_aoa = c[0] * aoa**5 + c[1] * aoa**4 + c[2] * aoa**3 + c[3] * aoa**2 + c[4] * aoa + 1.0
    d_aoa = d[0] * aoa**5 + d[1] * aoa**4 + d[2] * aoa**3 + d[3] * aoa**2 + d[4] * aoa
    return c_aoa + d_aoa * np.sin(np.radians(3.0 * wd))


def _nakai_2012_gx(aoa_deg: np.ndarray, wind_direction_deg: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    sinerr = _nakai_2012_sinerr(aoa_deg, wind_direction_deg)
    coserr = _nakai_2012_coserr(aoa_deg, wind_direction_deg)
    return np.degrees(np.arctan(np.divide(ratio * coserr, sinerr, out=np.zeros_like(ratio), where=np.abs(sinerr) > 1e-9)))


def _nakai_2006_sinerr(aoa_deg: np.ndarray) -> np.ndarray:
    aoa = np.asarray(aoa_deg, dtype=float)
    negative = aoa < 0.0
    pn = (0.428727148, 55.59348879, 0.222867784, 0.4882)
    pp = (0.570590482, 1610.881585, 0.111150653, 0.972080458)
    return np.where(
        negative,
        pn[0] / (1.0 + pn[1] * np.exp(-pn[2] * (aoa + 90.0))) + pn[3],
        -pp[0] / (1.0 + pp[1] * np.exp(-pp[2] * aoa)) + pp[3],
    )


def _nakai_2006_coserr(aoa_deg: np.ndarray, wind_direction_deg: np.ndarray) -> np.ndarray:
    original = np.asarray(aoa_deg, dtype=float)
    clipped = np.clip(original, -70.0, 70.0)
    q = (1.41546e-6, 8.51092e-4, 1.00672)
    f_aoa = q[0] * clipped**3 + q[1] * clipped**2 + q[2] * clipped + 6.28032 * np.sin(np.radians(3.0 * wind_direction_deg))
    f_aoa = np.where(original < -70.0, -90.0 * (1.0 - (90.0 + original) / 20.0) + (90.0 + original) / 20.0 * f_aoa, f_aoa)
    f_aoa = np.where(original > 70.0, 90.0 * (1.0 - (90.0 - original) / 20.0) + (90.0 - original) / 20.0 * f_aoa, f_aoa)
    return np.cos(np.radians(f_aoa))


def _nakai_2006_gx(aoa_deg: np.ndarray, wind_direction_deg: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    sinerr = _nakai_2006_sinerr(aoa_deg)
    coserr = _nakai_2006_coserr(aoa_deg, wind_direction_deg)
    denominator = sinerr * np.cos(np.radians(aoa_deg))
    return np.degrees(
        np.arctan(
            np.divide(
                ratio * coserr - 0.0195,
                denominator,
                out=np.zeros_like(ratio),
                where=np.abs(denominator) > 1e-9,
            )
        )
    )


def _angle_of_attack_step(
    *,
    name: str,
    method: str,
    before_attack_deg: np.ndarray,
    solved_attack_deg: np.ndarray,
    u_before: np.ndarray,
    v_before: np.ndarray,
    w_before: np.ndarray,
    u_after: np.ndarray,
    v_after: np.ndarray,
    w_after: np.ndarray,
    iterations: int,
    coefficient_set: str,
) -> dict[str, Any]:
    before_horizontal = np.sqrt(u_before ** 2 + v_before ** 2)
    after_horizontal = np.sqrt(u_after ** 2 + v_after ** 2)
    horizontal_factor = np.divide(after_horizontal, before_horizontal, out=np.ones_like(after_horizontal), where=before_horizontal > 1e-12)
    vertical_factor = np.divide(w_after, w_before, out=np.ones_like(w_after), where=np.abs(w_before) > 1e-12)
    return {
        "name": name,
        "family": "angle_of_attack",
        "status": "applied",
        "method": method,
        "coefficient_set": coefficient_set,
        "sample_count": int(before_attack_deg.size),
        "iteration_count": int(iterations),
        "max_abs_attack_angle_deg": float(np.max(np.abs(before_attack_deg))) if before_attack_deg.size else 0.0,
        "mean_abs_attack_angle_deg": float(np.mean(np.abs(before_attack_deg))) if before_attack_deg.size else 0.0,
        "mean_abs_solved_attack_angle_deg": float(np.mean(np.abs(solved_attack_deg))) if solved_attack_deg.size else 0.0,
        "mean_horizontal_factor": float(np.mean(horizontal_factor)) if horizontal_factor.size else 1.0,
        "mean_vertical_factor": float(np.mean(vertical_factor)) if vertical_factor.size else 1.0,
        "provenance": f"{method} angle-of-attack correction using EddyPro public source coefficient equations.",
        "limitations": ["Numeric parity should be verified with sonic-family-specific EddyPro official fixtures."],
    }


def _apply_calibrated_angle_of_attack_gain(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    horizontal = np.sqrt(u ** 2 + v ** 2)
    attack_deg = np.degrees(np.arctan2(w, np.maximum(horizontal, 1e-12)))
    clipped = np.clip(np.abs(attack_deg), 0.0, _safe_float(config.get("max_abs_angle_deg", 70.0), default=70.0))
    scale = clipped / max(_safe_float(config.get("reference_angle_deg", 45.0), default=45.0), 1e-6)
    horizontal_gain = _safe_float(config.get("horizontal_gain_per_reference_angle", 0.0), default=0.0)
    vertical_gain = _safe_float(config.get("vertical_gain_per_reference_angle", 0.0), default=0.0)
    h_factor = np.clip(1.0 + horizontal_gain * scale, 0.5, 1.5)
    w_factor = np.clip(1.0 + vertical_gain * scale, 0.5, 1.5)
    return (
        u * h_factor,
        v * h_factor,
        w * w_factor,
        {
            "name": "calibrated_angle_of_attack_gain",
            "family": "angle_of_attack",
            "status": "applied",
            "method": "calibrated_gain",
            "max_abs_attack_angle_deg": float(np.max(clipped)) if clipped.size else 0.0,
            "mean_abs_attack_angle_deg": float(np.mean(clipped)) if clipped.size else 0.0,
            "horizontal_gain_per_reference_angle": horizontal_gain,
            "vertical_gain_per_reference_angle": vertical_gain,
            "reference_angle_deg": _safe_float(config.get("reference_angle_deg", 45.0), default=45.0),
            "mean_horizontal_factor": float(np.mean(h_factor)) if h_factor.size else 1.0,
            "mean_vertical_factor": float(np.mean(w_factor)) if w_factor.size else 1.0,
            "provenance": "Configured angle-of-attack gain path retained for custom calibration coefficients.",
        },
    )


def _nanmean_or_none(values: np.ndarray) -> float | None:
    if values.size == 0 or np.all(np.isnan(values)):
        return None
    return float(np.nanmean(values))


def _nanstd_or_none(values: np.ndarray) -> float | None:
    if values.size == 0 or np.all(np.isnan(values)):
        return None
    return float(np.nanstd(values))


# ---------------------------------------------------------------------------
# Crosswind sonic-temperature correction
# ---------------------------------------------------------------------------

def apply_crosswind_correction(
    *,
    u: np.ndarray,
    v: np.ndarray,
    temp_c: np.ndarray,
    config: dict[str, Any] | None = None,
) -> CrosswindCorrectionResult:
    cfg = dict(config or {})
    method = str(cfg.get("method", "liu_2001_crosswind_v1") or "liu_2001_crosswind_v1")
    if not bool(cfg.get("enabled", False)):
        return CrosswindCorrectionResult(
            temp_c=temp_c,
            detail={
                "status": "disabled",
                "applied": False,
                "method": method,
                "provenance": "Crosswind correction disabled by configuration.",
                "limitations": [],
            },
        )

    manufacturer = _normalize_sonic_text(cfg.get("sonic_manufacturer", cfg.get("manufacturer", cfg.get("firm", ""))))
    model = _normalize_sonic_text(cfg.get("sonic_model", cfg.get("model", "")))
    coefficients = cfg.get("coefficients")
    if isinstance(coefficients, dict):
        coeff_detail = _coerce_crosswind_coefficients(coefficients)
        coefficient_source = "configured"
    else:
        coeff_detail = _crosswind_coefficients_for_sonic(manufacturer=manufacturer, model=model)
        coefficient_source = "eddypro_model_registry"

    if coeff_detail is None:
        return CrosswindCorrectionResult(
            temp_c=temp_c,
            detail={
                "status": "unsupported_sonic",
                "applied": False,
                "method": method,
                "sonic_manufacturer": manufacturer,
                "sonic_model": model,
                "provenance": "No crosswind correction coefficients are available for the configured sonic.",
                "limitations": ["Configure A/B/C coefficients or choose a supported Gill/Metek/CSI/Young sonic family."],
            },
        )

    a = np.array(coeff_detail["A"], dtype=float)
    b = np.array(coeff_detail["B"], dtype=float)
    c = np.array(coeff_detail["C"], dtype=float)
    u2 = np.asarray(u, dtype=float) ** 2
    v2 = np.asarray(v, dtype=float) ** 2
    uv = np.asarray(u, dtype=float) * np.asarray(v, dtype=float)
    un = a[0] * u2 + b[0] * v2 + c[0] * uv
    vn = a[1] * u2 + b[1] * v2 + c[1] * uv
    wn = a[2] * u2 + b[2] * v2 + c[2] * uv
    divisor = _safe_float(cfg.get("temperature_divisor", 1209.0), default=1209.0)
    if abs(divisor) < 1e-12:
        divisor = 1209.0
    delta_c = (un + vn + wn) / divisor
    corrected = np.asarray(temp_c, dtype=float) + delta_c
    detail = {
        "status": "applied",
        "applied": True,
        "method": method,
        "sonic_manufacturer": manufacturer,
        "sonic_model": model,
        "coefficient_source": coefficient_source,
        "coefficients": {
            "A": [float(value) for value in a],
            "B": [float(value) for value in b],
            "C": [float(value) for value in c],
        },
        "temperature_divisor": divisor,
        "mean_delta_c": float(np.mean(delta_c)) if delta_c.size else 0.0,
        "max_abs_delta_c": float(np.max(np.abs(delta_c))) if delta_c.size else 0.0,
        "mean_temp_before_c": _nanmean_or_none(np.asarray(temp_c, dtype=float)),
        "mean_temp_after_c": _nanmean_or_none(corrected),
        "provenance": (
            "Crosswind sonic-temperature correction v1 following the Liu et al. (2001) style "
            "A/B/C coefficient pathway used by EddyPro CrossWindCorr before thermodynamic flux calculations."
        ),
        "source_reference": {
            "eddypro_engine_files": ["src/src_common/cross_wind_corr.f90"],
            "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
        },
        "limitations": [
            "Correction is applied to the temperature channel available in NormalizedHFFrame; site metadata should confirm this is sonic temperature.",
            "Model registry covers EddyPro's common Gill/Metek/CSI/Young coefficient families; real instrument parity still needs fixtures.",
        ],
    }
    return CrosswindCorrectionResult(temp_c=corrected, detail=detail)


def _coerce_crosswind_coefficients(payload: dict[str, Any]) -> dict[str, list[float]] | None:
    try:
        a = [float(value) for value in payload.get("A", payload.get("a", []))]
        b = [float(value) for value in payload.get("B", payload.get("b", []))]
        c = [float(value) for value in payload.get("C", payload.get("c", []))]
    except (TypeError, ValueError):
        return None
    if len(a) != 3 or len(b) != 3 or len(c) != 3:
        return None
    return {"A": a, "B": b, "C": c}


def _crosswind_coefficients_for_sonic(*, manufacturer: str, model: str) -> dict[str, list[float]] | None:
    firm = manufacturer
    if firm in {"campbell", "campbell_scientific"}:
        firm = "csi"
    if firm in {"rm_young", "rmyoung", "r_m_young"}:
        firm = "young"
    if firm == "gill_instruments":
        firm = "gill"
    if model in {"windmaster", "windmaster_pro", "windmasterpro"}:
        model = "wmpro" if "pro" in model else "wm"
    if firm == "gill":
        if model in {"hs_50", "hs_100"}:
            return _symmetric_gill_crosswind_coefficients(48.75)
        if model == "r2":
            return {"A": [1.5, 0.0, 0.0], "B": [3.0, 0.0, 0.0], "C": [0.0, 0.0, 0.0]}
        if model in {"r3_50", "r3_100", "wm", "wmpro", "r3a_100"}:
            return _symmetric_gill_crosswind_coefficients(45.0)
    if firm == "metek":
        return {
            "A": [1.0, 5.0 / 8.0, 5.0 / 8.0],
            "B": [0.5, 7.0 / 8.0, 7.0 / 8.0],
            "C": [0.0, 0.25 * math.sqrt(3.0), -0.25 * math.sqrt(3.0)],
        }
    if firm == "csi":
        return {
            "A": [0.75, 15.0 / 16.0, 15.0 / 16.0],
            "B": [1.0, 13.0 / 16.0, 13.0 / 16.0],
            "C": [0.0, math.sqrt(3.0) / 8.0, -math.sqrt(3.0) / 8.0],
        }
    if firm == "young":
        return _symmetric_gill_crosswind_coefficients(45.0)
    return None


def _symmetric_gill_crosswind_coefficients(phi_deg: float) -> dict[str, list[float]]:
    cos2 = math.cos(math.radians(phi_deg)) ** 2
    return {
        "A": [1.0 - cos2, 1.0 - 0.25 * cos2, 1.0 - 0.25 * cos2],
        "B": [1.0, 1.0 - 0.75 * cos2, 1.0 - 0.75 * cos2],
        "C": [0.0, 0.5 * math.sqrt(3.0) * cos2, -0.5 * math.sqrt(3.0) * cos2],
    }


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def rotate_wind(u: np.ndarray, v: np.ndarray, w: np.ndarray, mode: str) -> RotationResult:
    mode = normalize_rotation_mode(mode)
    if u.size == 0 or v.size == 0 or w.size == 0:
        return RotationResult(u=u, v=v, w=w, mode=mode, applied=False, reason="empty input", alpha_deg=0.0, beta_deg=0.0)

    if mode == "none":
        return RotationResult(u=u, v=v, w=w, mode=mode, applied=True, reason="no rotation applied", alpha_deg=0.0, beta_deg=0.0)

    mean_u = float(np.mean(u))
    mean_v = float(np.mean(v))
    wind_speed = math.sqrt(mean_u ** 2 + mean_v ** 2)

    if wind_speed < 1e-6:
        return RotationResult(u=u, v=v, w=w, mode=mode, applied=False, reason="wind speed too low for rotation", alpha_deg=0.0, beta_deg=0.0)

    alpha = math.atan2(mean_v, mean_u)
    cos_a, sin_a = math.cos(alpha), math.sin(alpha)
    u1 = u * cos_a + v * sin_a
    v1 = -u * sin_a + v * cos_a
    w1 = w.copy()
    alpha_deg = math.degrees(alpha)

    if mode == "single":
        return RotationResult(u=u1, v=v1, w=w1, mode=mode, applied=True, reason="single rotation applied", alpha_deg=alpha_deg, beta_deg=0.0)

    # double rotation
    mean_u1 = float(np.mean(u1))
    mean_w1 = float(np.mean(w1))
    speed1 = math.sqrt(mean_u1 ** 2 + mean_w1 ** 2)
    if speed1 < 1e-6:
        return RotationResult(u=u1, v=v1, w=w1, mode=mode, applied=True, reason="single rotation only (tilt too small)", alpha_deg=alpha_deg, beta_deg=0.0)

    beta = math.atan2(mean_w1, mean_u1)
    cos_b, sin_b = math.cos(beta), math.sin(beta)
    u2 = u1 * cos_b + w1 * sin_b
    w2 = -u1 * sin_b + w1 * cos_b
    beta_deg = math.degrees(beta)

    if mode == "double":
        return RotationResult(u=u2, v=v1, w=w2, mode=mode, applied=True, reason="double rotation applied", alpha_deg=alpha_deg, beta_deg=beta_deg)

    # triple rotation: third rotation around new u-axis to force mean(v2)=0
    if mode == "triple":
        mean_v1 = float(np.mean(v1))
        mean_w2 = float(np.mean(w2))
        speed2 = math.sqrt(mean_v1 ** 2 + mean_w2 ** 2)
        if speed2 < 1e-6:
            return RotationResult(u=u2, v=v1, w=w2, mode=mode, applied=True, reason="double rotation only (lateral wind too small for triple)", alpha_deg=alpha_deg, beta_deg=beta_deg)
        gamma = math.atan2(mean_v1, mean_w2)
        cos_g, sin_g = math.cos(gamma), math.sin(gamma)
        v2 = v1 * cos_g - w2 * sin_g
        w3 = v1 * sin_g + w2 * cos_g
        return RotationResult(u=u2, v=v2, w=w3, mode=mode, applied=True, reason="triple rotation applied", alpha_deg=alpha_deg, beta_deg=beta_deg)

    # planar_fit: minimal viable single-window version
    # A full sector-wise planar fit requires multi-window regression; this
    # single-window version estimates the tilt plane from the current window's
    # mean wind vector and applies the correction. Falls back to double rotation.
    if mode == "planar_fit":
        return RotationResult(u=u2, v=v1, w=w2, mode=mode, applied=True, reason="planar_fit (single-window fallback to double rotation)", alpha_deg=alpha_deg, beta_deg=beta_deg)

    return RotationResult(u=u2, v=v1, w=w2, mode=mode, applied=True, reason="double rotation applied", alpha_deg=alpha_deg, beta_deg=beta_deg)


# ---------------------------------------------------------------------------
# Sector-wise Planar Fit
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PlanarFitCoefficients:
    b0: float
    b1: float
    b2: float
    sector: str
    window_count: int
    r_squared: float = 0.0


def compute_planar_fit_coefficients(
    u_list: list[np.ndarray],
    v_list: list[np.ndarray],
    w_list: list[np.ndarray],
    *,
    n_sectors: int = 12,
    min_windows_per_sector: int = 5,
) -> dict[str, PlanarFitCoefficients]:
    if n_sectors < 1:
        n_sectors = 12
    sector_width = 360.0 / n_sectors
    sector_data: dict[str, dict[str, list[float]]] = {}
    for u, v, w in zip(u_list, v_list, w_list):
        if u.size < 10:
            continue
        mean_u = float(np.mean(u))
        mean_v = float(np.mean(v))
        mean_w = float(np.mean(w))
        wind_dir = math.degrees(math.atan2(mean_v, mean_u)) % 360.0
        sector_idx = min(int(wind_dir / sector_width), n_sectors - 1)
        sector_label = f"S{sector_idx:02d}"
        sector_data.setdefault(sector_label, {"u": [], "v": [], "w": []})
        sector_data[sector_label]["u"].append(mean_u)
        sector_data[sector_label]["v"].append(mean_v)
        sector_data[sector_label]["w"].append(mean_w)

    coefficients: dict[str, PlanarFitCoefficients] = {}
    for sector_label, data in sector_data.items():
        n = len(data["u"])
        if n < min_windows_per_sector:
            coefficients[sector_label] = PlanarFitCoefficients(
                b0=0.0, b1=0.0, b2=0.0, sector=sector_label, window_count=n, r_squared=0.0,
            )
            continue
        u_arr = np.array(data["u"], dtype=float)
        v_arr = np.array(data["v"], dtype=float)
        w_arr = np.array(data["w"], dtype=float)
        A = np.column_stack([np.ones(n), u_arr, v_arr])
        try:
            result = np.linalg.lstsq(A, w_arr, rcond=None)
            coeffs = result[0]
            b0, b1, b2 = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
            w_pred = A @ coeffs
            ss_res = float(np.sum((w_arr - w_pred) ** 2))
            ss_tot = float(np.sum((w_arr - float(np.mean(w_arr))) ** 2))
            r_sq = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        except np.linalg.LinAlgError:
            b0, b1, b2, r_sq = 0.0, 0.0, 0.0, 0.0
        coefficients[sector_label] = PlanarFitCoefficients(
            b0=b0, b1=b1, b2=b2, sector=sector_label, window_count=n, r_squared=r_sq,
        )
    return coefficients


def apply_planar_fit_rotation(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    coefficients: PlanarFitCoefficients,
) -> RotationResult:
    if u.size == 0:
        return RotationResult(u=u, v=v, w=w, mode="sector_wise_planar_fit", applied=False, reason="empty input", alpha_deg=0.0, beta_deg=0.0)
    mean_u = float(np.mean(u))
    mean_v = float(np.mean(v))
    alpha = math.atan2(mean_v, mean_u)
    cos_a, sin_a = math.cos(alpha), math.sin(alpha)
    u1 = u * cos_a + v * sin_a
    v1 = -u * sin_a + v * cos_a
    if coefficients.window_count < 5 or (abs(coefficients.b1) < 1e-9 and abs(coefficients.b2) < 1e-9 and abs(coefficients.b0) < 1e-9):
        w1 = w.copy()
        mean_u1 = float(np.mean(u1))
        mean_w1 = float(np.mean(w1))
        speed1 = math.sqrt(mean_u1 ** 2 + mean_w1 ** 2)
        if speed1 > 1e-6:
            beta = math.atan2(mean_w1, mean_u1)
            cos_b, sin_b = math.cos(beta), math.sin(beta)
            u2 = u1 * cos_b + w1 * sin_b
            w2 = -u1 * sin_b + w1 * cos_b
        else:
            u2, w2, beta = u1, w1, 0.0
        return RotationResult(
            u=u2, v=v1, w=w2, mode="sector_wise_planar_fit",
            applied=True,
            reason=f"sector_wise_planar_fit: insufficient data for sector {coefficients.sector} (n={coefficients.window_count}), fallback to double rotation",
            alpha_deg=math.degrees(alpha), beta_deg=math.degrees(beta),
        )
    w_corrected = w - (coefficients.b0 + coefficients.b1 * u + coefficients.b2 * v)
    w1 = w_corrected.copy()
    return RotationResult(
        u=u1, v=v1, w=w1, mode="sector_wise_planar_fit",
        applied=True,
        reason=f"sector_wise_planar_fit: sector {coefficients.sector} (n={coefficients.window_count}, R²={coefficients.r_squared:.3f})",
        alpha_deg=math.degrees(alpha), beta_deg=0.0,
    )


def apply_planar_fit_no_velocity_bias(
    u: np.ndarray,
    v: np.ndarray,
    w: np.ndarray,
    coefficients: PlanarFitCoefficients,
) -> RotationResult:
    result = apply_planar_fit_rotation(u, v, w, coefficients)
    if not result.applied or result.u.size < 10:
        return result
    mean_v = float(np.mean(result.v))
    mean_w = float(np.mean(result.w))
    speed2 = math.sqrt(mean_v ** 2 + mean_w ** 2)
    if speed2 < 1e-6:
        result.reason += "; no velocity bias correction (lateral wind too small)"
        return result
    gamma = math.atan2(mean_v, mean_w)
    cos_g, sin_g = math.cos(gamma), math.sin(gamma)
    v2 = result.v * cos_g - result.w * sin_g
    w2 = result.v * sin_g + result.w * cos_g
    return RotationResult(
        u=result.u, v=v2, w=w2, mode="sector_wise_planar_fit_no_velocity_bias",
        applied=True,
        reason=result.reason + "; velocity bias removed (triple rotation step)",
        alpha_deg=result.alpha_deg, beta_deg=result.beta_deg,
    )


# ---------------------------------------------------------------------------
# Detrend
# ---------------------------------------------------------------------------

def _detrend(values: np.ndarray, mode: str = "linear") -> np.ndarray:
    if values.size < 3:
        return values.astype(float, copy=True)

    if mode == "block_mean":
        return values - float(np.mean(values))

    if mode == "running_mean":
        window = max(3, values.size // 6)
        if window >= values.size:
            return values - float(np.mean(values))
        kernel = np.ones(window, dtype=float) / window
        trend = np.convolve(values, kernel, mode="same")
        return values - trend

    if mode == "exponential_running_mean":
        alpha = 0.05
        ewma = np.empty_like(values, dtype=float)
        ewma[0] = values[0]
        for i in range(1, values.size):
            ewma[i] = alpha * values[i] + (1.0 - alpha) * ewma[i - 1]
        return values - ewma

    # linear (default)
    if scipy_signal is not None:
        return scipy_signal.detrend(values, type="linear")
    x_axis = np.arange(values.size, dtype=float)
    slope, intercept = np.polyfit(x_axis, values, deg=1)
    return values - (slope * x_axis + intercept)


# ---------------------------------------------------------------------------
# Lag analysis
# ---------------------------------------------------------------------------

def analyze_lag(
    vertical_velocity: np.ndarray,
    co2_series: np.ndarray,
    h2o_series: np.ndarray,
    sample_rate_hz: float,
    search_window_s: float,
    *,
    lag_strategy: str = "covariance_max",
    expected_lag_s: float | None = None,
    confidence_threshold: float = 0.4,
) -> LagAnalysisResult:
    strategy = normalize_lag_strategy(lag_strategy)

    if strategy == "none":
        return LagAnalysisResult(
            lag_seconds=0.0, confidence=1.0,
            lag_curve_x=[], lag_curve_y=[],
            co2_lag_seconds=0.0, h2o_lag_seconds=0.0,
            fallback_reason="lag_strategy=none: no lag applied",
        )

    if strategy == "constant":
        lag_s = float(expected_lag_s) if expected_lag_s is not None else 0.0
        return LagAnalysisResult(
            lag_seconds=lag_s, confidence=1.0,
            lag_curve_x=[], lag_curve_y=[],
            co2_lag_seconds=lag_s, h2o_lag_seconds=lag_s,
            fallback_reason="lag_strategy=constant: using expected_lag_s",
        )

    # covariance_max or covariance_max_with_default
    result = _covariance_max_lag(vertical_velocity, co2_series, h2o_series, sample_rate_hz, search_window_s)

    if strategy == "covariance_max_with_default" and result.confidence < confidence_threshold and expected_lag_s is not None:
        fallback_lag = float(expected_lag_s)
        return LagAnalysisResult(
            lag_seconds=fallback_lag, confidence=result.confidence,
            lag_curve_x=result.lag_curve_x, lag_curve_y=result.lag_curve_y,
            co2_lag_seconds=fallback_lag, h2o_lag_seconds=fallback_lag,
            fallback_reason=f"covariance_max confidence={result.confidence:.3f} < threshold={confidence_threshold}, falling back to expected_lag_s={fallback_lag}",
        )

    result.fallback_reason = ""
    return result


def _covariance_max_lag(
    vertical_velocity: np.ndarray,
    co2_series: np.ndarray,
    h2o_series: np.ndarray,
    sample_rate_hz: float,
    search_window_s: float,
) -> LagAnalysisResult:
    max_lag = max(1, int(search_window_s * sample_rate_hz))
    lags = np.arange(-max_lag, max_lag + 1, dtype=int)

    co2_curve = _covariance_curve(vertical_velocity, _standardize(_detrend(co2_series)), lags)
    h2o_curve = _covariance_curve(vertical_velocity, _standardize(_detrend(h2o_series)), lags)
    blend_curve = 0.65 * co2_curve + 0.35 * h2o_curve

    peak_index = int(np.argmax(np.abs(blend_curve)))
    lag_seconds = float(lags[peak_index] / sample_rate_hz)
    co2_peak = int(np.argmax(np.abs(co2_curve)))
    h2o_peak = int(np.argmax(np.abs(h2o_curve)))
    confidence = _lag_confidence(blend_curve, peak_index)

    return LagAnalysisResult(
        lag_seconds=lag_seconds, confidence=confidence,
        lag_curve_x=[float(lag / sample_rate_hz) for lag in lags],
        lag_curve_y=[float(value) for value in blend_curve],
        co2_lag_seconds=float(lags[co2_peak] / sample_rate_hz),
        h2o_lag_seconds=float(lags[h2o_peak] / sample_rate_hz),
    )


def _covariance_curve(reference: np.ndarray, scalar: np.ndarray, lags: np.ndarray) -> np.ndarray:
    curve = np.zeros_like(lags, dtype=float)
    for index, lag in enumerate(lags):
        if lag < 0:
            left = reference[:lag]
            right = scalar[-lag:]
        elif lag > 0:
            left = reference[lag:]
            right = scalar[:-lag]
        else:
            left = reference
            right = scalar
        if left.size == 0 or right.size == 0:
            continue
        curve[index] = float(np.mean(left * right))
    max_abs = max(np.max(np.abs(curve)), 1e-9)
    return curve / max_abs


def _lag_confidence(curve: np.ndarray, peak_index: int) -> float:
    peak = float(abs(curve[peak_index]))
    if curve.size <= 1:
        return peak
    others = np.delete(np.abs(curve), peak_index)
    second = float(np.max(others)) if others.size else 0.0
    prominence = peak - second
    spread_penalty = min(1.0, float(np.std(curve)) * 1.5)
    return float(np.clip(0.45 + prominence * 0.55 + spread_penalty * 0.15, 0.0, 1.0))


def _standardize(values: np.ndarray) -> np.ndarray:
    scale = float(np.std(values))
    if scale <= 1e-9:
        return values - float(np.mean(values))
    return (values - float(np.mean(values))) / scale


# ---------------------------------------------------------------------------
# Lag application
# ---------------------------------------------------------------------------

def apply_lag(series: np.ndarray, lag_seconds: float, sample_rate_hz: float) -> np.ndarray:
    if abs(lag_seconds) < 1e-9 or series.size == 0:
        return series.copy()
    shift = int(round(lag_seconds * sample_rate_hz))
    if shift == 0:
        return series.copy()
    result = np.empty_like(series)
    if shift > 0:
        result[:shift] = series[0]
        result[shift:] = series[:-shift]
    else:
        result[shift:] = series[-1]
        result[:shift] = series[-shift:]
    return result


# ---------------------------------------------------------------------------
# Flux metrics
# ---------------------------------------------------------------------------

def compute_flux_metrics(
    *,
    w_series: np.ndarray,
    co2_ppm: np.ndarray,
    h2o_mmol: np.ndarray,
    pressure_kpa: np.ndarray,
    temp_c: np.ndarray,
    cell_pressure_kpa: np.ndarray | None = None,
    cell_temp_c: np.ndarray | None = None,
    detrend_mode: str = "block_mean",
    density_correction_mode: str = "wpl",
    ambient_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = normalize_detrend_mode(detrend_mode)
    correction_mode = normalize_density_correction_mode(density_correction_mode)
    ambient_overrides = dict(ambient_overrides or {})
    w_det = _detrend(w_series, mode)
    co2_det = _detrend(co2_ppm, mode)
    h2o_det = _detrend(h2o_mmol, mode)

    cov_w_co2 = float(np.mean(w_det * co2_det))
    cov_w_h2o = float(np.mean(w_det * h2o_det))

    def _mean_or_override(name: str, fallback: float) -> float:
        value = ambient_overrides.get(name)
        if value in (None, ""):
            return fallback
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return fallback
        return numeric if math.isfinite(numeric) else fallback

    mean_pressure_kpa = _mean_or_override("mean_pressure_kpa", float(np.mean(pressure_kpa)))
    mean_temp_c = _mean_or_override("mean_temp_c", float(np.mean(temp_c)))
    mean_h2o = _mean_or_override("mean_h2o_mmol", float(np.mean(h2o_mmol)))
    mean_p = mean_pressure_kpa * 1000.0  # Pa
    mean_t = mean_temp_c + 273.15  # K
    r = 8.314  # J/(mol·K)
    cp = 29.07  # J/(mol·K) approximate for dry air
    air_molar_density = mean_p / (r * mean_t) if mean_t > 0 else 0.0

    h2o_mol_fraction = max(0.0, mean_h2o * 1.0e-3)
    dry_air_molar_density = (
        air_molar_density / (1.0 + h2o_mol_fraction)
        if air_molar_density > 0 and math.isfinite(h2o_mol_fraction)
        else max(0.0, air_molar_density)
    )
    water_vapor_molar_density = max(0.0, air_molar_density - dry_air_molar_density)

    raw_flux = air_molar_density * cov_w_co2
    mean_co2_ppm = float(np.mean(co2_ppm))
    mean_w = float(np.mean(w_series))
    mixing_ratio_flux = dry_air_molar_density * (cov_w_co2 + (mean_co2_ppm * 1.0e-3) * cov_w_h2o)

    def _optional_series(values: np.ndarray | None, expected_size: int) -> np.ndarray:
        if values is None:
            return np.array([], dtype=float)
        arr = np.asarray(values, dtype=float)
        if arr.size == 0 or expected_size <= 0:
            return np.array([], dtype=float)
        arr = arr[: min(arr.size, expected_size)]
        if not np.any(np.isfinite(arr)):
            return np.array([], dtype=float)
        return _fill_missing(np.where(np.isfinite(arr), arr, np.nan))

    cell_pressure_series = _optional_series(cell_pressure_kpa, w_series.size)
    cell_temp_series = _optional_series(cell_temp_c, w_series.size)
    cell_pressure_available = cell_pressure_series.size > 0
    cell_temp_available = cell_temp_series.size > 0
    cell_thermodynamics_status = "available" if cell_pressure_available or cell_temp_available else "not_available"
    cell_thermodynamics_source = "raw_payload" if cell_thermodynamics_status == "available" else ""

    # WPL correction: water vapor term + temperature-density term. H2O is
    # represented as mmol/mol, so conversion to mol/mol is explicit here.
    water_vapor_flux = dry_air_molar_density * cov_w_h2o
    wpl_water_vapor_term = mean_co2_ppm * water_vapor_flux * 1.0e-3
    temp_det = _detrend(temp_c, mode)
    cov_w_t = float(np.mean(w_det * temp_det)) if temp_det.size > 0 else 0.0
    cov_w_cell_temp_c: float | None = None
    if cell_temp_available:
        n_cell_t = min(w_det.size, cell_temp_series.size)
        cell_temp_det = _detrend(cell_temp_series[:n_cell_t], mode)
        cov_w_cell_temp_c = float(np.mean(w_det[:n_cell_t] * cell_temp_det)) if cell_temp_det.size > 0 else 0.0
        sensible_heat_cov = cov_w_cell_temp_c
        sensible_heat_source = "cell_temperature"
    else:
        sensible_heat_cov = cov_w_t
        sensible_heat_source = "ambient_temperature"

    sensible_heat_coefficient = (
        mean_co2_ppm * air_molar_density * (1.0 + h2o_mol_fraction)
        if air_molar_density > 0
        else 0.0
    )
    wpl_sensible_heat_term = sensible_heat_coefficient * (sensible_heat_cov / mean_t if mean_t > 0 else 0.0)

    cov_w_cell_pressure_kpa: float | None = None
    closed_path_cell_pressure_term = 0.0
    if cell_pressure_available:
        n_cell_p = min(w_det.size, cell_pressure_series.size)
        cell_pressure_det = _detrend(cell_pressure_series[:n_cell_p], mode)
        cov_w_cell_pressure_kpa = (
            float(np.mean(w_det[:n_cell_p] * cell_pressure_det)) if cell_pressure_det.size > 0 else 0.0
        )
        pressure_scale = air_molar_density / max(abs(mean_pressure_kpa), 1e-9)
        closed_path_cell_pressure_term = mean_co2_ppm * pressure_scale * cov_w_cell_pressure_kpa

    closed_path_cell_temperature_term = wpl_sensible_heat_term if cell_temp_available else 0.0
    closed_path_density_term = closed_path_cell_temperature_term + closed_path_cell_pressure_term
    closed_path_density_correction_applied = bool(
        cell_thermodynamics_status == "available"
        and correction_mode == "wpl"
        and (abs(closed_path_cell_temperature_term) > 1e-15 or abs(closed_path_cell_pressure_term) > 1e-15)
    )

    density_corrected_flux = raw_flux + wpl_water_vapor_term + wpl_sensible_heat_term + closed_path_cell_pressure_term
    air_density_kg_m3 = air_molar_density * _DRY_AIR_MOLAR_MASS_KG_MOL
    latent_heat_vaporization_j_kg = max(2.0e6, (2.501 - 0.00237 * mean_temp_c) * 1.0e6)
    water_vapor_mol_flux = water_vapor_flux * 1.0e-3
    latent_heat_flux_w_m2 = water_vapor_mol_flux * _WATER_MOLAR_MASS_KG_MOL * latent_heat_vaporization_j_kg
    evapotranspiration_rate_mm_h = water_vapor_mol_flux * _WATER_MOLAR_MASS_KG_MOL * 3600.0
    sensible_heat_flux_w_m2 = air_molar_density * cp * cov_w_t

    if correction_mode == "mixing_ratio":
        primary_flux = mixing_ratio_flux
        correction_reason = "mixing_ratio: using dry-air mixing ratio flux"
    elif correction_mode == "none":
        primary_flux = raw_flux
        correction_reason = "none: no density correction applied, using raw flux"
    else:
        primary_flux = density_corrected_flux
        wpl_parts = []
        if abs(wpl_water_vapor_term) > 1e-15:
            wpl_parts.append(f"water_vapor_term={wpl_water_vapor_term:.6e}")
        if abs(wpl_sensible_heat_term) > 1e-15:
            wpl_parts.append(f"sensible_heat_term={wpl_sensible_heat_term:.6e}")
        if abs(closed_path_cell_pressure_term) > 1e-15:
            wpl_parts.append(f"cell_pressure_term={closed_path_cell_pressure_term:.6e}")
        parts_str = ", ".join(wpl_parts) if wpl_parts else "no significant correction terms"
        correction_reason = f"wpl: Webb-Pearman-Leuning density correction applied ({parts_str})"
        if cell_thermodynamics_status == "available":
            correction_reason = (
                f"{correction_reason}; closed-path cell thermodynamics from raw payload "
                f"(sensible_heat_source={sensible_heat_source})"
            )
    if ambient_overrides:
        correction_reason = f"{correction_reason}; ambient thermodynamics from {ambient_overrides.get('source', 'configured overrides')}"

    closed_path_cell_detail = {
        "status": cell_thermodynamics_status,
        "source": cell_thermodynamics_source,
        "sensible_heat_source": sensible_heat_source,
        "mean_cell_pressure_kpa": float(np.mean(cell_pressure_series)) if cell_pressure_available else None,
        "mean_cell_temp_c": float(np.mean(cell_temp_series)) if cell_temp_available else None,
        "cov_w_cell_pressure_kpa": cov_w_cell_pressure_kpa,
        "cov_w_cell_temp_c": cov_w_cell_temp_c,
        "cell_temperature_term": closed_path_cell_temperature_term,
        "cell_pressure_term": closed_path_cell_pressure_term,
        "density_term": closed_path_density_term,
        "applied_to_density_corrected_flux": closed_path_density_correction_applied,
        "provenance": (
            "Cell pressure/temperature were parsed from high-frequency raw payload fields and detrended with the window."
            if cell_thermodynamics_status == "available"
            else "No high-frequency cell pressure/temperature payload fields were available for this window."
        ),
        "limitations": [
            "Cell thermodynamic covariance support is a first-order closed-path density correction path.",
            "Numeric parity still requires official EddyPro raw-to-final closed-path fixtures.",
        ],
    }

    return {
        "cov_w_co2": cov_w_co2,
        "cov_w_h2o": cov_w_h2o,
        "raw_flux": raw_flux,
        "mixing_ratio_flux": mixing_ratio_flux,
        "density_corrected_flux": density_corrected_flux,
        "primary_flux": primary_flux,
        "water_vapor_flux": water_vapor_flux,
        "sensible_heat_flux_w_m2": sensible_heat_flux_w_m2,
        "latent_heat_flux_w_m2": latent_heat_flux_w_m2,
        "evapotranspiration_rate_mm_h": evapotranspiration_rate_mm_h,
        "latent_heat_vaporization_j_kg": latent_heat_vaporization_j_kg,
        "air_density_kg_m3": air_density_kg_m3,
        "air_molar_density": air_molar_density,
        "dry_air_molar_density": dry_air_molar_density,
        "water_vapor_molar_density": water_vapor_molar_density,
        "mean_pressure_kpa": mean_pressure_kpa,
        "mean_temp_c": mean_temp_c,
        "mean_h2o_mmol": mean_h2o,
        "mean_h2o_mol_fraction": h2o_mol_fraction,
        "ambient_override_status": "applied" if ambient_overrides else "not_configured",
        "ambient_override_source": str(ambient_overrides.get("source", "")) if ambient_overrides else "",
        "density_correction_mode": correction_mode,
        "density_correction_reason": correction_reason,
        "wpl_water_vapor_term": wpl_water_vapor_term,
        "wpl_sensible_heat_term": wpl_sensible_heat_term,
        "wpl_sensible_heat_source": sensible_heat_source,
        "cell_thermodynamics_status": cell_thermodynamics_status,
        "cell_thermodynamics_source": cell_thermodynamics_source,
        "cell_mean_pressure_kpa": closed_path_cell_detail["mean_cell_pressure_kpa"],
        "cell_mean_temp_c": closed_path_cell_detail["mean_cell_temp_c"],
        "cov_w_cell_pressure_kpa": cov_w_cell_pressure_kpa,
        "cov_w_cell_temp_c": cov_w_cell_temp_c,
        "closed_path_cell_temperature_term": closed_path_cell_temperature_term,
        "closed_path_cell_pressure_term": closed_path_cell_pressure_term,
        "closed_path_density_term": closed_path_density_term,
        "closed_path_density_correction_applied": closed_path_density_correction_applied,
        "closed_path_cell_detail": closed_path_cell_detail,
    }


def compute_ch4_flux_metrics(
    *,
    w_series: np.ndarray,
    ch4_ppb: np.ndarray,
    air_molar_density: float,
    detrend_mode: str = "block_mean",
    valid_ratio: float = 0.0,
) -> dict[str, Any]:
    if ch4_ppb.size == 0 or w_series.size == 0 or valid_ratio <= 0.0:
        return {
            "status": "not_available",
            "cov_w_ch4_ppb": None,
            "ch4_flux_nmol_m2_s": None,
            "mean_ch4_ppb": None,
            "valid_ratio": float(valid_ratio),
            "provenance": "ch4 channel missing from high-frequency input",
            "limitations": ["No CH4 flux is computed when the high-frequency CH4 channel is absent."],
        }
    mode = normalize_detrend_mode(detrend_mode)
    n = min(w_series.size, ch4_ppb.size)
    w_det = _detrend(w_series[:n], mode)
    ch4_det = _detrend(ch4_ppb[:n], mode)
    cov_w_ch4_ppb = float(np.mean(w_det * ch4_det))
    ch4_flux_nmol = float(air_molar_density * cov_w_ch4_ppb)
    return {
        "status": "computed",
        "cov_w_ch4_ppb": cov_w_ch4_ppb,
        "ch4_flux_nmol_m2_s": ch4_flux_nmol,
        "mean_ch4_ppb": float(np.mean(ch4_ppb[:n])),
        "valid_ratio": float(valid_ratio),
        "selected_method": "li_7700_level0_covariance",
        "provenance": "LI-7700 Level 0 CH4 covariance flux from high-frequency CH4 mixing ratio and rotated vertical wind.",
        "limitations": [
            "LI-7700 spectroscopic corrections are not yet applied.",
            "CH4 density and self-heating correction sequence is not yet complete.",
            "Flux is reported as nmol m-2 s-1 using air molar density times cov(w, CH4 ppb).",
        ],
    }


def compute_n2o_flux_metrics(
    *,
    w_series: np.ndarray,
    n2o_ppb: np.ndarray,
    air_molar_density: float,
    detrend_mode: str = "block_mean",
    valid_ratio: float = 0.0,
) -> dict[str, Any]:
    if n2o_ppb.size == 0 or w_series.size == 0 or valid_ratio <= 0.0:
        return {
            "status": "not_available",
            "cov_w_n2o_ppb": None,
            "n2o_flux_nmol_m2_s": None,
            "mean_n2o_ppb": None,
            "valid_ratio": float(valid_ratio),
            "selected_method": "not_available",
            "provenance": "n2o channel missing from high-frequency input",
            "limitations": ["No N2O flux is computed when the high-frequency N2O channel is absent."],
        }
    mode = normalize_detrend_mode(detrend_mode)
    n = min(w_series.size, n2o_ppb.size)
    w_det = _detrend(w_series[:n], mode)
    n2o_det = _detrend(n2o_ppb[:n], mode)
    cov_w_n2o_ppb = float(np.mean(w_det * n2o_det))
    n2o_flux_nmol = float(air_molar_density * cov_w_n2o_ppb)
    return {
        "status": "computed",
        "cov_w_n2o_ppb": cov_w_n2o_ppb,
        "n2o_flux_nmol_m2_s": n2o_flux_nmol,
        "mean_n2o_ppb": float(np.mean(n2o_ppb[:n])),
        "valid_ratio": float(valid_ratio),
        "selected_method": "n2o_level0_covariance",
        "provenance": "N2O Level 0 covariance flux from high-frequency N2O mixing ratio and rotated vertical wind.",
        "limitations": [
            "N2O spectral and analyzer-specific correction families are not yet applied.",
            "Flux is reported as nmol m-2 s-1 using air molar density times cov(w, N2O ppb).",
        ],
    }


def compute_trace_gas_empirical_correction_sequence(
    *,
    gas_key: str,
    gas_label: str,
    level0_metrics: dict[str, Any],
    level0_flux_field: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    selected_method = str(cfg.get("method", f"{gas_key}_empirical_correction_sequence_v1") or f"{gas_key}_empirical_correction_sequence_v1")
    if level0_metrics.get("status") != "computed" or not isinstance(level0_metrics.get(level0_flux_field), (int, float)):
        return {
            "status": "not_available",
            "selected_method": selected_method,
            "reason": f"{gas_label} Level 0 covariance flux is not available.",
            "levels": {},
            "provenance": f"{gas_label} empirical trace-gas correction sequence skipped because covariance input is missing.",
            "limitations": [f"No {gas_label} correction sequence can be evaluated without a covariance flux."],
        }

    level0_flux = float(level0_metrics[level0_flux_field])
    spectral_cfg = dict(cfg.get("spectral_correction", {}) or {})
    analyzer_cfg = dict(cfg.get("analyzer_correction", {}) or {})
    density_cfg = dict(cfg.get("density_correction", {}) or {})
    spectral_factor = _bounded_float(
        cfg.get("spectral_correction_factor", spectral_cfg.get("factor", 1.0)),
        default=1.0,
        lower=0.2,
        upper=5.0,
    )
    analyzer_factor = _bounded_float(
        cfg.get("analyzer_correction_factor", analyzer_cfg.get("factor", 1.0)),
        default=1.0,
        lower=0.2,
        upper=5.0,
    )
    density_factor = _bounded_float(
        cfg.get("density_correction_factor", density_cfg.get("factor", 1.0)),
        default=1.0,
        lower=0.2,
        upper=5.0,
    )
    level1_flux = level0_flux * spectral_factor
    level2_flux = level1_flux * analyzer_factor
    final_flux = level2_flux * density_factor
    profile = dict(cfg.get("coefficient_profile", cfg.get("correction_profile", {})) or {})
    profile_id = str(cfg.get("coefficient_profile_id", profile.get("profile_id", "")) or "")
    source_file = str(cfg.get("coefficient_profile_source_file", profile.get("source_file", "")) or "")
    normalization_command = str(
        cfg.get("coefficient_profile_normalization_command", profile.get("normalization_command", "")) or ""
    )
    configured_limitations = [str(item) for item in cfg.get("limitations", []) or [] if str(item)]
    configured_limitations.extend(str(item) for item in cfg.get("known_limitations", []) or [] if str(item))
    configured_limitations.extend(str(item) for item in cfg.get("coefficient_profile_limitations", []) or [] if str(item))
    limitations = [
        f"{gas_label} correction sequence uses configured empirical factors; it is not a gas-specific proprietary analyzer model.",
        f"{gas_label} spectral/analyzer factors require paired reference evidence before EddyPro numeric parity can be claimed.",
    ]
    limitations.extend(configured_limitations)
    provenance_tail = ""
    if profile_id:
        provenance_tail = f" profile={profile_id}"
        if source_file:
            provenance_tail += f"; source_file={source_file}"
        if normalization_command:
            provenance_tail += f"; normalization_command={normalization_command}"
    return {
        "status": "computed",
        "selected_method": selected_method,
        "final_flux_nmol_m2_s": final_flux,
        "level0_flux_nmol_m2_s": level0_flux,
        "level1_spectral_flux_nmol_m2_s": level1_flux,
        "level2_analyzer_flux_nmol_m2_s": level2_flux,
        "level3_corrected_flux_nmol_m2_s": final_flux,
        "spectral_correction_factor": spectral_factor,
        "analyzer_correction_factor": analyzer_factor,
        "density_correction_factor": density_factor,
        "changed_level0": not math.isclose(final_flux, level0_flux, rel_tol=1e-12, abs_tol=1e-12),
        "coefficient_profile_id": profile_id,
        "coefficient_registry_status": str(cfg.get("coefficient_registry_status", "")),
        "coefficient_profile_label": str(cfg.get("coefficient_profile_label", "")),
        "coefficient_profile_source": str(cfg.get("coefficient_profile_source", "")),
        "coefficient_source_file": source_file,
        "coefficient_normalization_command": normalization_command,
        "coefficient_profile_provenance": str(cfg.get("coefficient_profile_provenance", profile.get("provenance", "")) or ""),
        "coefficient_profile": profile,
        "levels": {
            "level0": {
                "name": "raw_covariance",
                "flux_nmol_m2_s": level0_flux,
                "source_method": level0_metrics.get("selected_method", f"{gas_key}_level0_covariance"),
            },
            "level1": {
                "name": "spectral_attenuation",
                "factor": spectral_factor,
                "mode": str(spectral_cfg.get("mode", cfg.get("spectral_correction_mode", "empirical_factor")) or "empirical_factor"),
                "flux_nmol_m2_s": level1_flux,
            },
            "level2": {
                "name": "analyzer_response",
                "factor": analyzer_factor,
                "mode": str(analyzer_cfg.get("mode", cfg.get("analyzer_correction_mode", "empirical_factor")) or "empirical_factor"),
                "flux_nmol_m2_s": level2_flux,
            },
            "level3": {
                "name": "density_or_user_scalar",
                "factor": density_factor,
                "mode": str(density_cfg.get("mode", cfg.get("density_correction_mode", "empirical_factor")) or "empirical_factor"),
                "flux_nmol_m2_s": final_flux,
            },
        },
        "components": {
            "spectral": spectral_cfg or {"mode": "empirical_factor", "factor": spectral_factor},
            "analyzer": analyzer_cfg or {"mode": "empirical_factor", "factor": analyzer_factor},
            "density": density_cfg or {"mode": "empirical_factor", "factor": density_factor},
            "coefficient_profile": {
                "profile_id": profile_id,
                "registry_status": str(cfg.get("coefficient_registry_status", "")),
                "label": str(cfg.get("coefficient_profile_label", "")),
                "source": str(cfg.get("coefficient_profile_source", "")),
                "source_file": source_file,
                "normalization_command": normalization_command,
                "provenance": str(cfg.get("coefficient_profile_provenance", profile.get("provenance", "")) or ""),
            },
        },
        "provenance": (
            f"{gas_label} empirical trace-gas correction sequence v1: Level 0 covariance; "
            "Level 1 spectral attenuation factor; Level 2 analyzer-response factor; "
            f"Level 3 density/user scalar factor.{provenance_tail}"
        ),
        "limitations": limitations,
    }


def compute_li7700_status_diagnostics(
    *,
    rows: list[NormalizedHFFrame],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    payloads = [_merged_frame_payload(row) for row in rows]
    payloads = [payload for payload in payloads if payload]
    rssi = _payload_metric_series(payloads, ("li7700_rssi", "rssi", "rssi_pct", "rss_pct", "received_signal_strength"))
    signal = _payload_metric_series(
        payloads,
        ("li7700_signal_strength", "signal_strength", "signal_strength_pct", "ch4_signal_strength", "optical_signal"),
    )
    mirror_rssi = _payload_metric_series(payloads, ("mirror_rssi", "mirror_signal", "mirror_signal_strength", "mirror_rssi_pct"))
    locked = _payload_bool_series(payloads, ("pll_lock", "pll_locked", "laser_lock", "laser_locked", "reference_lock", "reference_locked"))
    mirror_dirty = _payload_bool_series(
        payloads,
        ("mirror_dirty", "mirror_contaminated", "dirty_mirror", "mirror_warning"),
        true_tokens={"1", "true", "yes", "y", "dirty", "contaminated", "warning", "warn", "bad"},
        false_tokens={"0", "false", "no", "n", "clean", "ok", "pass", "normal"},
    )
    status_words = _payload_int_series(
        payloads,
        (
            "li7700_status_word",
            "li_7700_status_word",
            "li7700_diagnostic_word",
            "diagnostic_word",
            "diagnostic_code",
            "status_code",
            "diag_code",
        ),
    )
    fault_flags = _payload_status_flags(payloads)
    status_word_flags = _li7700_status_word_flags(status_words, cfg)
    fault_flags = [*fault_flags, *status_word_flags]
    status_sample_count = max(
        len(rssi),
        len(signal),
        len(mirror_rssi),
        len(locked),
        len(mirror_dirty),
        len(status_words),
        len(fault_flags),
    )

    if status_sample_count == 0:
        return {
            "artifact_type": "li7700_status_diagnostics_v1",
            "status": "not_available",
            "sample_count": len(rows),
            "status_sample_count": 0,
            "checks": [],
            "diagnostic_flags": [],
            "provenance": "No LI-7700 status/RSSI/diagnostic payload fields were found in raw_text or status_text.",
            "limitations": ["Provide LI-7700 diagnostic fields in row raw_text/status_text to enable status screening."],
        }

    min_rssi_fail = float(cfg.get("min_rssi_fail_pct", 10.0) or 10.0)
    min_rssi_warning = float(cfg.get("min_rssi_warning_pct", 20.0) or 20.0)
    min_signal_warning = float(cfg.get("min_signal_strength_warning_pct", min_rssi_warning) or min_rssi_warning)
    max_dirty_fraction = float(cfg.get("max_mirror_dirty_fraction", 0.0) or 0.0)
    require_lock = bool(cfg.get("require_lock", False))
    dirty_fraction = float(sum(1 for value in mirror_dirty if value) / max(1, len(mirror_dirty))) if mirror_dirty else 0.0
    unlocked_count = sum(1 for value in locked if not value)
    rssi_min = _series_min(rssi)
    rssi_mean = _series_mean(rssi)
    signal_min = _series_min(signal)
    signal_mean = _series_mean(signal)
    mirror_rssi_mean = _series_mean(mirror_rssi)
    fault_count = len(fault_flags)
    status_word_nonzero_count = sum(1 for word in status_words if word != 0)
    checks = [
        _li7700_status_check(
            "li7700_rssi_fail_threshold",
            rssi_min is None or rssi_min >= min_rssi_fail,
            measured=rssi_min,
            threshold=f">={min_rssi_fail} %",
            severity="fail",
            failure_message="LI-7700 RSSI fell below the configured fail threshold.",
        ),
        _li7700_status_check(
            "li7700_rssi_warning_threshold",
            rssi_min is None or rssi_min >= min_rssi_warning,
            measured=rssi_min,
            threshold=f">={min_rssi_warning} %",
            severity="warn",
            failure_message="LI-7700 RSSI fell below the configured warning threshold.",
        ),
        _li7700_status_check(
            "li7700_signal_strength",
            signal_min is None or signal_min >= min_signal_warning,
            measured=signal_min,
            threshold=f">={min_signal_warning} %",
            severity="warn",
            failure_message="LI-7700 signal strength fell below the configured warning threshold.",
        ),
        _li7700_status_check(
            "li7700_mirror_clean",
            dirty_fraction <= max_dirty_fraction,
            measured=dirty_fraction,
            threshold=f"<={max_dirty_fraction}",
            severity="fail",
            failure_message="LI-7700 mirror contamination/dirty flag exceeded policy.",
        ),
        _li7700_status_check(
            "li7700_lock",
            unlocked_count == 0 if require_lock else True,
            measured=unlocked_count,
            threshold="0 unlocked samples" if require_lock else "not required",
            severity="fail" if require_lock else "warn",
            failure_message="LI-7700 lock status reported unlocked samples.",
        ),
        _li7700_status_check(
            "li7700_fault_flags",
            fault_count == 0,
            measured=sorted(set(fault_flags)),
            threshold="no fault/error/blocked flags",
            severity="fail",
            failure_message="LI-7700 diagnostic payload contained fault/error flags.",
        ),
        _li7700_status_check(
            "li7700_status_word",
            not status_word_flags,
            measured=sorted(set(status_words)),
            threshold="allowed_status_words",
            severity="fail",
            failure_message="LI-7700 numeric status/diagnostic word reported non-allowed bits.",
        ),
    ]
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    return {
        "artifact_type": "li7700_status_diagnostics_v1",
        "status": status,
        "sample_count": len(rows),
        "status_sample_count": status_sample_count,
        "rssi_mean_pct": rssi_mean,
        "rssi_min_pct": rssi_min,
        "signal_strength_mean_pct": signal_mean,
        "signal_strength_min_pct": signal_min,
        "mirror_rssi_mean_pct": mirror_rssi_mean,
        "mirror_dirty_count": sum(1 for value in mirror_dirty if value),
        "mirror_dirty_fraction": dirty_fraction,
        "unlocked_count": unlocked_count,
        "diagnostic_fault_count": fault_count,
        "diagnostic_flags": sorted(set(fault_flags)),
        "status_word_count": len(status_words),
        "status_word_nonzero_count": status_word_nonzero_count,
        "status_word_unique_values": sorted(set(status_words)),
        "status_word_flags": sorted(set(status_word_flags)),
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "provenance": (
            "LI-7700 status diagnostics v1 parsed RSSI/signal/mirror/lock/fault fields from "
            "NormalizedHFFrame raw_text/status_text JSON payloads, including numeric status-word fields when present."
        ),
        "limitations": [
            "Diagnostic thresholds are configurable policy checks and do not reproduce proprietary LI-7700 firmware internals.",
            "Real LI-7700 status-record fixtures with EddyPro outputs are still required for numeric parity closure.",
        ],
    }


def compute_ygas_primary_analyzer_diagnostics(
    *,
    rows: list[NormalizedHFFrame],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    requested_profile_id = str(
        cfg.get("profile_id", cfg.get("gas_analyzer_profile_id", cfg.get("gas_analyzer_profile", "ygas_irga")))
        or "ygas_irga"
    )
    profile = get_gas_analyzer_profile(requested_profile_id)
    profile_summary = profile.to_summary()
    profile_id = str(profile_summary.get("profile_id", requested_profile_id) or requested_profile_id)
    payloads = [_merged_frame_payload(row) for row in rows]
    payloads = [payload for payload in payloads if payload]
    ygas_payloads = [payload for payload in payloads if _payload_looks_like_ygas(payload)]

    calibration_profile = dict(cfg.get("calibration_profile", {}) or {})
    calibration_profile_id = str(
        cfg.get(
            "calibration_profile_id",
            cfg.get("coefficient_profile_id", calibration_profile.get("profile_id", "")),
        )
        or ""
    )
    source_reference = dict(profile_summary.get("source_reference", {}) or {})
    source_file = str(
        cfg.get(
            "source_file",
            cfg.get(
                "calibration_source_file",
                calibration_profile.get("source_file", source_reference.get("manual", "")),
            ),
        )
        or ""
    )
    normalization_command = str(
        cfg.get(
            "normalization_command",
            calibration_profile.get(
                "normalization_command",
                f"gas_ec_studio normalize-ygas --input raw_text/status_text --profile {profile_id}",
            ),
        )
        or ""
    )
    provenance = (
        "YGAS primary analyzer diagnostics v1 parsed signal, ratio, density, status-register, "
        "and calibration provenance fields from NormalizedHFFrame raw_text/status_text payloads."
    )

    if not ygas_payloads:
        return {
            "artifact_type": "ygas_primary_analyzer_diagnostics_v1",
            "status": "not_available",
            "profile_id": profile_id,
            "profile_label": str(profile_summary.get("label", "")),
            "instrument_family": str(profile_summary.get("model_family", "YGAS CO2/H2O")),
            "sample_count": len(rows),
            "status_sample_count": 0,
            "telemetry_detected": False,
            "calibration_profile_id": calibration_profile_id,
            "calibration_source_file": source_file,
            "calibration_normalization_command": normalization_command,
            "source_reference": source_reference,
            "checks": [],
            "active_faults": [],
            "provenance": provenance,
            "limitations": [
                "No YGAS protocol payload fields were found in raw_text/status_text for this window.",
                "Provide parsed YGAS MODE1/MODE2 telemetry to enable signal and status-register screening.",
            ],
        }

    co2_signal = _payload_metric_series(
        ygas_payloads,
        ("co2_signal_strength", "co2_signal", "co2_signal_raw", "co2_signal_mv", "ygas_co2_signal"),
    )
    h2o_signal = _payload_metric_series(
        ygas_payloads,
        ("h2o_signal_strength", "h2o_signal", "h2o_signal_raw", "h2o_signal_mv", "ygas_h2o_signal"),
    )
    reference_signal = _payload_metric_series(
        ygas_payloads,
        ("reference_signal", "ref_signal", "reference_signal_mv", "ygas_reference_signal"),
    )
    co2_ratio = _payload_metric_series(
        ygas_payloads,
        ("co2_ratio_filtered", "co2_ratio_f", "co2_ratio", "co2_ratio_raw"),
    )
    h2o_ratio = _payload_metric_series(
        ygas_payloads,
        ("h2o_ratio_filtered", "h2o_ratio_f", "h2o_ratio", "h2o_ratio_raw"),
    )
    co2_density = _payload_metric_series(ygas_payloads, ("co2_density", "co2_density_mg_m3"))
    h2o_density = _payload_metric_series(ygas_payloads, ("h2o_density", "h2o_density_g_m3"))

    status_registers: list[str] = []
    active_faults: list[str] = []
    status_ok_values: list[bool] = []
    for payload in ygas_payloads:
        register_value = _payload_lookup(payload, ("status_register", "ygas_status_register", "ygas_status_word"))
        if register_value is not None:
            parsed_status = parse_status_register(register_value)
            status_registers.append(str(parsed_status.get("status_register", "")))
            active_faults.extend(str(item) for item in parsed_status.get("active_faults", []) if str(item))
            if parsed_status.get("status_ok") is not None:
                status_ok_values.append(bool(parsed_status.get("status_ok")))
        direct_status_ok = _payload_lookup(payload, ("status_ok", "ygas_status_ok", "instrument_status_ok"))
        if direct_status_ok is not None:
            status_ok = _coerce_payload_bool(
                direct_status_ok,
                true_tokens={"1", "true", "yes", "y", "ok", "pass", "normal"},
                false_tokens={"0", "false", "no", "n", "fault", "fail", "bad", "error"},
            )
            status_ok_values.append(status_ok)
            if not status_ok:
                active_faults.append("status_ok_false")
        active_faults.extend(_ygas_direct_faults(payload))

    min_signal_fail = float(cfg.get("min_signal_fail", cfg.get("min_signal_fail_pct", 0.0)) or 0.0)
    min_signal_warning = float(cfg.get("min_signal_warning", cfg.get("min_signal_warning_pct", 0.10)) or 0.10)
    min_reference_signal_warning = float(cfg.get("min_reference_signal_warning", 0.0) or 0.0)
    require_status_ok = bool(cfg.get("require_status_ok", True))
    co2_signal_min = _series_min(co2_signal)
    h2o_signal_min = _series_min(h2o_signal)
    reference_signal_min = _series_min(reference_signal)
    unique_faults = sorted(set(active_faults))

    signal_checks = [
        _ygas_status_check(
            "ygas_co2_signal_fail_threshold",
            co2_signal_min is None or co2_signal_min > min_signal_fail,
            measured=co2_signal_min,
            threshold=f">{min_signal_fail}",
            severity="fail",
            failure_message="YGAS CO2 signal fell below the configured fail threshold.",
        ),
        _ygas_status_check(
            "ygas_h2o_signal_fail_threshold",
            h2o_signal_min is None or h2o_signal_min > min_signal_fail,
            measured=h2o_signal_min,
            threshold=f">{min_signal_fail}",
            severity="fail",
            failure_message="YGAS H2O signal fell below the configured fail threshold.",
        ),
        _ygas_status_check(
            "ygas_co2_signal_warning_threshold",
            co2_signal_min is None or co2_signal_min >= min_signal_warning,
            measured=co2_signal_min,
            threshold=f">={min_signal_warning}",
            severity="warn",
            failure_message="YGAS CO2 signal fell below the configured warning threshold.",
        ),
        _ygas_status_check(
            "ygas_h2o_signal_warning_threshold",
            h2o_signal_min is None or h2o_signal_min >= min_signal_warning,
            measured=h2o_signal_min,
            threshold=f">={min_signal_warning}",
            severity="warn",
            failure_message="YGAS H2O signal fell below the configured warning threshold.",
        ),
        _ygas_status_check(
            "ygas_reference_signal_warning_threshold",
            reference_signal_min is None or reference_signal_min >= min_reference_signal_warning,
            measured=reference_signal_min,
            threshold=f">={min_reference_signal_warning}",
            severity="warn",
            failure_message="YGAS reference signal fell below the configured warning threshold.",
        ),
    ]
    status_checks = [
        _ygas_status_check(
            "ygas_status_register_faults",
            not unique_faults,
            measured=unique_faults,
            threshold="no active status-register faults",
            severity="fail",
            failure_message="YGAS status register or status_ok payload reported active faults.",
        ),
        _ygas_status_check(
            "ygas_status_ok_policy",
            all(status_ok_values) if require_status_ok and status_ok_values else True,
            measured=status_ok_values,
            threshold="all status_ok samples true" if require_status_ok else "not required",
            severity="fail" if require_status_ok else "warn",
            failure_message="YGAS status_ok policy failed.",
        ),
    ]
    checks = [*signal_checks, *status_checks]
    signal_fail_count = sum(1 for item in signal_checks if item["status"] == "fail")
    signal_warn_count = sum(1 for item in signal_checks if item["status"] == "warn")
    status_fail_count = sum(1 for item in status_checks if item["status"] == "fail")
    status_warn_count = sum(1 for item in status_checks if item["status"] == "warn")
    signal_status = "fail" if signal_fail_count else ("warning" if signal_warn_count else "pass")
    register_status = "not_available" if not status_registers and not status_ok_values else (
        "fail" if status_fail_count else ("warning" if status_warn_count else "pass")
    )
    fail_count = signal_fail_count + status_fail_count
    warn_count = signal_warn_count + status_warn_count
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    limitations = [
        "YGAS signal thresholds are configurable policy checks and should be tuned with site calibration records.",
        "Calibration provenance is reported from the selected profile; coefficient fitting parity requires a matching lab calibration fixture.",
        "Status-register interpretation follows the project YGAS protocol parser and does not model hidden firmware state.",
    ]

    return {
        "artifact_type": "ygas_primary_analyzer_diagnostics_v1",
        "status": status,
        "profile_id": profile_id,
        "profile_label": str(profile_summary.get("label", "")),
        "instrument_family": str(profile_summary.get("model_family", "YGAS CO2/H2O")),
        "sample_count": len(rows),
        "status_sample_count": len(ygas_payloads),
        "telemetry_detected": True,
        "signal_status": signal_status,
        "status_register_status": register_status,
        "co2_signal_mean": _series_mean(co2_signal),
        "co2_signal_min": co2_signal_min,
        "h2o_signal_mean": _series_mean(h2o_signal),
        "h2o_signal_min": h2o_signal_min,
        "reference_signal_mean": _series_mean(reference_signal),
        "reference_signal_min": reference_signal_min,
        "co2_ratio_mean": _series_mean(co2_ratio),
        "h2o_ratio_mean": _series_mean(h2o_ratio),
        "co2_density_mean": _series_mean(co2_density),
        "h2o_density_mean": _series_mean(h2o_density),
        "status_register_count": len(status_registers),
        "status_register_unique_values": sorted(set(status_registers)),
        "status_ok_count": sum(1 for value in status_ok_values if value),
        "status_not_ok_count": sum(1 for value in status_ok_values if not value),
        "fault_count": len(unique_faults),
        "active_faults": unique_faults,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "calibration_profile_id": calibration_profile_id,
        "calibration_source_file": source_file,
        "calibration_normalization_command": normalization_command,
        "calibration_profile": calibration_profile,
        "source_reference": source_reference,
        "raw_output_fields": list(profile_summary.get("raw_output_fields", []) or []),
        "provenance": provenance,
        "limitations": limitations,
    }


def _payload_looks_like_ygas(payload: dict[str, Any]) -> bool:
    flattened = _flatten_payload(payload)
    normalized_keys = {_normalize_payload_key(key) for key, _value in flattened}
    marker_keys = {
        "ygas_protocol_import",
        "ygas_primary_analyzer",
        "ygas_status_register",
        "status_register",
        "co2_signal",
        "co2_signal_strength",
        "co2_signal_raw",
        "h2o_signal",
        "h2o_signal_strength",
        "h2o_signal_raw",
        "ref_signal",
        "reference_signal",
        "co2_ratio_f",
        "co2_ratio_filtered",
        "h2o_ratio_f",
        "h2o_ratio_filtered",
        "co2_density",
        "h2o_density",
    }
    if normalized_keys & marker_keys:
        return True
    for key, value in flattened:
        normalized = _normalize_payload_key(key)
        if normalized in {"profile_id", "gas_analyzer_profile", "gas_analyzer_profile_id", "instrument_family"}:
            if "ygas" in str(value).strip().lower():
                return True
    return False


def _ygas_direct_faults(payload: dict[str, Any]) -> list[str]:
    faults: list[str] = []
    direct = payload.get("active_faults")
    if isinstance(direct, list):
        faults.extend(str(item) for item in direct if str(item))
    elif isinstance(direct, str) and direct.strip() and direct.strip().lower() not in {"[]", "none", "ok", "normal"}:
        faults.extend(part.strip() for part in re.split(r"[|,;]", direct) if part.strip())
    for key, value in _flatten_payload(payload):
        normalized = _normalize_payload_key(key)
        if "active_faults" not in normalized and not normalized.endswith("_fault"):
            continue
        if isinstance(value, str) and value.strip().lower() in {"", "[]", "none", "ok", "normal"}:
            continue
        if isinstance(value, bool):
            if value:
                faults.append(normalized)
            continue
        if isinstance(value, (int, float)) and float(value) == 0.0:
            continue
        text = str(value).strip()
        if text:
            faults.append(text if normalized.startswith("active_faults") else f"{normalized}:{text}")
    return faults


def compute_li7700_correction_sequence(
    *,
    ch4_metrics: dict[str, Any],
    mean_h2o_mmol: float,
    mean_pressure_kpa: float,
    mean_temp_c: float,
    spectral_correction_factor: float = 1.0,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = dict(config or {})
    coefficient_profile = dict(config.get("coefficient_profile", {}) or {})
    coefficient_profile_id = str(config.get("coefficient_profile_id", coefficient_profile.get("profile_id", "")) or "")
    coefficient_registry_status = str(config.get("coefficient_registry_status", "") or "")
    coefficient_provenance = str(
        config.get("coefficient_profile_provenance", coefficient_profile.get("provenance", "")) or ""
    )
    coefficient_source_file = str(
        config.get("coefficient_profile_source_file", coefficient_profile.get("source_file", "")) or ""
    )
    coefficient_normalization_command = str(
        config.get(
            "coefficient_profile_normalization_command",
            coefficient_profile.get("normalization_command", ""),
        )
        or ""
    )
    status_diagnostics = dict(config.get("li7700_status_diagnostics", {}) or {})
    if ch4_metrics.get("status") != "computed" or not isinstance(ch4_metrics.get("ch4_flux_nmol_m2_s"), (int, float)):
        return {
            "status": "not_available",
            "selected_method": "li_7700_correction_sequence_v1",
            "reason": "CH4 Level 0 covariance flux is not available.",
            "levels": {},
            "coefficient_profile_id": coefficient_profile_id,
            "coefficient_registry_status": coefficient_registry_status,
            "coefficient_profile_provenance": coefficient_provenance,
            "coefficient_source_file": coefficient_source_file,
            "coefficient_normalization_command": coefficient_normalization_command,
            "coefficient_profile": coefficient_profile,
            "li7700_status_diagnostics": status_diagnostics,
            "provenance": "LI-7700 correction sequence was skipped because the CH4 covariance input is missing.",
            "limitations": ["No LI-7700 correction sequence can be evaluated without a CH4 covariance flux."],
        }

    level0_flux = float(ch4_metrics["ch4_flux_nmol_m2_s"])
    scf = _bounded_float(spectral_correction_factor, default=1.0, lower=0.2, upper=5.0)
    level1_flux = level0_flux * scf

    apply_dilution = bool(config.get("apply_water_vapor_dilution", True))
    h2o_molfrac = min(max(float(mean_h2o_mmol) / 1000.0, 0.0), 0.12)
    water_vapor_dilution_factor = 1.0 / max(1.0 - h2o_molfrac, 0.88) if apply_dilution else 1.0
    level2_flux = level1_flux * water_vapor_dilution_factor

    spectroscopic_config = dict(config.get("spectroscopic_correction", {}) or {})
    spectroscopic_factor, spectroscopic_status, spectroscopic_components = _li7700_spectroscopic_factor(
        spectroscopic_config,
        mean_pressure_kpa=mean_pressure_kpa,
        mean_temp_c=mean_temp_c,
        h2o_molfrac=h2o_molfrac,
    )
    self_heating_config = dict(config.get("self_heating_correction", {}) or {})
    self_heating_factor, self_heating_status, self_heating_components = _li7700_self_heating_factor(
        self_heating_config,
        mean_temp_c=mean_temp_c,
    )
    level3_flux = level2_flux * spectroscopic_factor * self_heating_factor

    limitations = [
        "Spectroscopic correction is considered already present in LI-7700 mixing-ratio input unless empirical coefficients are configured.",
        "Self-heating correction is only applied when explicit empirical parameters are configured.",
        "The sequence follows EddyPro ordering but still needs real LI-7700 fixture parity before claiming numeric equivalence.",
    ]
    if spectroscopic_status == "applied_empirical":
        limitations[0] = "Spectroscopic correction uses configured empirical coefficients; raw WMS line-shape fitting is not reproduced."
    if spectroscopic_status == "applied_wms_line_shape":
        limitations[0] = (
            "Spectroscopic correction uses configured WMS line-shape scan fitting; "
            "public real LI-7700 WMS fixture parity is still required."
        )
    if self_heating_status == "applied_empirical":
        limitations[1] = "Self-heating correction uses configured empirical proxy parameters; instrument energy balance is not reproduced."
    status_diag_status = str(status_diagnostics.get("status", "") or "")
    if status_diag_status in {"warning", "fail"}:
        limitations.append(f"LI-7700 status diagnostics reported {status_diag_status}; inspect RSSI, mirror, lock, and diagnostic flags before publication-grade CH4 parity.")
    profile_label = str(config.get("coefficient_profile_label", coefficient_profile.get("label", "")) or "")
    if coefficient_provenance:
        limitations.extend(str(item) for item in config.get("coefficient_profile_limitations", []) if str(item))
    provenance_tail = ""
    if coefficient_profile_id:
        provenance_tail = f" Coefficient profile={coefficient_profile_id}"
        if profile_label:
            provenance_tail += f" ({profile_label})"
        if coefficient_registry_status:
            provenance_tail += f"; registry_status={coefficient_registry_status}"
        if coefficient_source_file:
            provenance_tail += f"; source_file={coefficient_source_file}"
        provenance_tail += "."

    return {
        "status": "computed",
        "selected_method": "li_7700_correction_sequence_v1",
        "final_flux_nmol_m2_s": level3_flux,
        "level0_flux_nmol_m2_s": level0_flux,
        "level1_spectral_flux_nmol_m2_s": level1_flux,
        "level2_density_flux_nmol_m2_s": level2_flux,
        "level3_corrected_flux_nmol_m2_s": level3_flux,
        "spectral_correction_factor": scf,
        "water_vapor_dilution_factor": water_vapor_dilution_factor,
        "spectroscopic_correction_factor": spectroscopic_factor,
        "self_heating_correction_factor": self_heating_factor,
        "mean_h2o_molfrac": h2o_molfrac,
        "coefficient_profile_id": coefficient_profile_id,
        "coefficient_registry_status": coefficient_registry_status,
        "coefficient_profile_label": profile_label,
        "coefficient_profile_provenance": coefficient_provenance,
        "coefficient_source_file": coefficient_source_file,
        "coefficient_normalization_command": coefficient_normalization_command,
        "coefficient_profile": coefficient_profile,
        "levels": {
            "level0": {
                "name": "raw_covariance",
                "flux_nmol_m2_s": level0_flux,
                "source_method": ch4_metrics.get("selected_method", "li_7700_level0_covariance"),
            },
            "level1": {
                "name": "spectral_attenuation",
                "factor": scf,
                "flux_nmol_m2_s": level1_flux,
            },
            "level2": {
                "name": "water_vapor_dilution_density",
                "factor": water_vapor_dilution_factor,
                "mean_h2o_molfrac": h2o_molfrac,
                "flux_nmol_m2_s": level2_flux,
            },
            "level3": {
                "name": "spectroscopic_self_heating",
                "spectroscopic_status": spectroscopic_status,
                "spectroscopic_factor": spectroscopic_factor,
                "self_heating_status": self_heating_status,
                "self_heating_factor": self_heating_factor,
                "flux_nmol_m2_s": level3_flux,
            },
        },
        "components": {
            "spectroscopic": spectroscopic_components,
            "self_heating": self_heating_components,
            "density": {
                "apply_water_vapor_dilution": apply_dilution,
                "mean_h2o_mmol": float(mean_h2o_mmol),
                "mean_h2o_molfrac": h2o_molfrac,
            },
            "coefficient_profile": {
                "profile_id": coefficient_profile_id,
                "registry_status": coefficient_registry_status,
                "label": profile_label,
                "source_file": coefficient_source_file,
                "normalization_command": coefficient_normalization_command,
                "provenance": coefficient_provenance,
            },
            "li7700_status_diagnostics": status_diagnostics,
        },
        "provenance": (
            "LI-7700 correction sequence v1: Level 0 covariance; Level 1 spectral attenuation; "
            "Level 2 water-vapor dilution/density step; Level 3 spectroscopic/self-heating hooks. "
            "Ordering follows LI-COR EddyPro guidance for LI-7200/LI-7700 systems."
            f"{provenance_tail}"
        ),
        "limitations": limitations,
    }


def _bounded_float(value: Any, *, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return min(max(number, lower), upper)


def _li7700_spectroscopic_factor(
    config: dict[str, Any],
    *,
    mean_pressure_kpa: float,
    mean_temp_c: float,
    h2o_molfrac: float,
) -> tuple[float, str, dict[str, Any]]:
    mode = str(config.get("mode", "input_corrected")).strip().lower()
    if mode in {"wms_line_shape", "line_shape", "raw_wms", "wms"}:
        return _li7700_wms_line_shape_factor(config)
    if mode not in {"empirical", "configured"}:
        return (
            1.0,
            "input_assumed_corrected",
            {
                "mode": "input_corrected",
                "reason": "LI-7700 CH4 mixing-ratio inputs are assumed to include instrument spectroscopic compensation.",
            },
        )
    pressure_coeff = float(config.get("pressure_sensitivity_per_kpa", 0.0) or 0.0)
    temp_coeff = float(config.get("temperature_sensitivity_per_c", 0.0) or 0.0)
    h2o_coeff = float(config.get("h2o_sensitivity_per_molfrac", 0.0) or 0.0)
    pressure_delta = float(mean_pressure_kpa) - float(config.get("reference_pressure_kpa", 101.325) or 101.325)
    temp_delta = float(mean_temp_c) - float(config.get("reference_temp_c", 20.0) or 20.0)
    h2o_delta = h2o_molfrac - float(config.get("reference_h2o_molfrac", 0.0) or 0.0)
    factor = 1.0 + pressure_coeff * pressure_delta + temp_coeff * temp_delta + h2o_coeff * h2o_delta
    factor = _bounded_float(factor, default=1.0, lower=0.5, upper=1.5)
    return (
        factor,
        "applied_empirical",
        {
            "mode": "empirical",
            "factor": factor,
            "pressure_delta_kpa": pressure_delta,
            "temperature_delta_c": temp_delta,
            "h2o_delta_molfrac": h2o_delta,
            "coefficients": {
                "pressure_sensitivity_per_kpa": pressure_coeff,
                "temperature_sensitivity_per_c": temp_coeff,
                "h2o_sensitivity_per_molfrac": h2o_coeff,
            },
        },
    )


def _li7700_wms_line_shape_factor(config: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    line_shape = dict(config.get("wms_line_shape", config.get("line_shape", {})) or {})
    if not line_shape:
        line_shape = dict(config)
    axis_values = (
        line_shape.get("scan_axis")
        or line_shape.get("axis")
        or line_shape.get("wavelength_nm")
        or line_shape.get("frequency")
        or []
    )
    signal_values = (
        line_shape.get("absorbance")
        or line_shape.get("signal")
        or line_shape.get("normalized_absorbance")
        or line_shape.get("wms_signal")
        or []
    )
    try:
        axis = np.asarray([float(item) for item in axis_values], dtype=float)
        signal = np.asarray([float(item) for item in signal_values], dtype=float)
    except (TypeError, ValueError):
        axis = np.asarray([], dtype=float)
        signal = np.asarray([], dtype=float)
    if axis.size != signal.size or axis.size < 5:
        return (
            1.0,
            "wms_line_shape_unavailable",
            {
                "mode": "wms_line_shape",
                "factor": 1.0,
                "reason": "WMS line-shape correction requires at least five paired scan_axis/signal samples.",
            },
        )
    finite = np.isfinite(axis) & np.isfinite(signal)
    axis = axis[finite]
    signal = signal[finite]
    if axis.size < 5 or float(np.ptp(axis)) <= 0.0:
        return (
            1.0,
            "wms_line_shape_unavailable",
            {
                "mode": "wms_line_shape",
                "factor": 1.0,
                "reason": "WMS line-shape samples are not finite or do not span a scan interval.",
            },
        )
    order = np.argsort(axis)
    axis = axis[order]
    signal = signal[order]
    edge_count = max(1, min(5, int(axis.size // 10) or 1))
    left_baseline = float(np.mean(signal[:edge_count]))
    right_baseline = float(np.mean(signal[-edge_count:]))
    baseline = np.interp(axis, [axis[0], axis[-1]], [left_baseline, right_baseline])
    absorption = signal - baseline
    if abs(float(np.min(absorption))) > abs(float(np.max(absorption))):
        absorption = -absorption
    positive = np.maximum(absorption, 0.0)
    area = float(np.trapezoid(positive, axis))
    peak_index = int(np.argmax(positive))
    peak_height = float(positive[peak_index])
    center = float(axis[peak_index])
    half_max = peak_height / 2.0
    above_half = np.where(positive >= half_max)[0] if peak_height > 0.0 else np.asarray([], dtype=int)
    fwhm = float(axis[above_half[-1]] - axis[above_half[0]]) if above_half.size >= 2 else 0.0
    fit_diagnostics = _li7700_wms_fit_diagnostics(axis=axis, absorption=positive, integrated_area=area, fwhm=fwhm)
    area_source = str(config.get("area_source", line_shape.get("area_source", "integrated_absorption")) or "integrated_absorption").strip().lower()
    selected_fit = dict(fit_diagnostics.get("selected_fit", {}) or {})
    selected_fit_area = _safe_float(selected_fit.get("area"), default=math.nan)
    correction_area = selected_fit_area if area_source in {"selected_fit", "fit", "model_fit"} and math.isfinite(selected_fit_area) else area
    fit_quality_status = str(fit_diagnostics.get("quality_status", "not_available"))
    reference_area = _safe_float(config.get("reference_area", line_shape.get("reference_area")), default=math.nan)
    if not math.isfinite(reference_area):
        reference_area = _safe_float(config.get("calibration_area", line_shape.get("calibration_area")), default=math.nan)
    if not math.isfinite(reference_area) or reference_area <= 0.0 or correction_area <= 0.0:
        factor = 1.0
        status = "diagnostic_only"
        reason = "No positive reference_area and fitted_area pair was available; no multiplicative factor was applied."
    else:
        factor = _bounded_float(reference_area / correction_area, default=1.0, lower=0.5, upper=1.5)
        status = "applied_wms_line_shape"
        reason = ""
    return (
        factor,
        status,
        {
            "mode": "wms_line_shape",
            "factor": factor,
            "status": status,
            "fitted_area": area,
            "correction_area": correction_area,
            "area_source": area_source,
            "reference_area": reference_area,
            "peak_center": center,
            "peak_height": peak_height,
            "fwhm": fwhm,
            "fit_quality_status": fit_quality_status,
            "fit_diagnostics": fit_diagnostics,
            "baseline": {
                "left": left_baseline,
                "right": right_baseline,
                "edge_sample_count": edge_count,
            },
            "sample_count": int(axis.size),
            "reason": reason,
            "provenance": "Configured LI-7700 WMS line-shape v1 from paired scan-axis and absorbance/signal samples.",
            "limitations": [
                "This is an auditable configured line-shape correction, not a claim of LI-7700 firmware-equivalent WMS fitting.",
                "Public real LI-7700 WMS scans with EddyPro golden outputs are still required for numeric parity.",
            ],
        },
    )


def _li7700_wms_fit_diagnostics(
    *,
    axis: np.ndarray,
    absorption: np.ndarray,
    integrated_area: float,
    fwhm: float,
) -> dict[str, Any]:
    if axis.size < 5 or absorption.size != axis.size or integrated_area <= 0.0:
        return {
            "artifact_type": "li7700_wms_line_shape_fit_v1",
            "status": "not_available",
            "quality_status": "not_available",
            "candidate_fits": [],
            "selected_fit": {},
            "reason": "At least five positive line-shape samples and a positive integrated area are required.",
        }
    weight_sum = float(np.sum(absorption))
    centroid = float(np.sum(axis * absorption) / weight_sum) if weight_sum > 0.0 else float(axis[int(np.argmax(absorption))])
    variance = float(np.sum(absorption * (axis - centroid) ** 2) / weight_sum) if weight_sum > 0.0 else 0.0
    sigma = math.sqrt(max(variance, 0.0))
    if not math.isfinite(sigma) or sigma <= 0.0:
        sigma = abs(float(fwhm)) / 2.355 if fwhm > 0.0 else float(np.ptp(axis)) / 8.0
    sigma = max(float(sigma), max(float(np.ptp(axis)) / max(axis.size * 4, 1), 1.0e-9))
    gamma = max(abs(float(fwhm)) / 2.0 if fwhm > 0.0 else sigma, 1.0e-9)
    candidates = [
        _li7700_wms_candidate_fit(axis=axis, absorption=absorption, model="gaussian", center=centroid, width=sigma),
        _li7700_wms_candidate_fit(axis=axis, absorption=absorption, model="lorentzian", center=centroid, width=gamma),
    ]
    candidates = [candidate for candidate in candidates if candidate.get("status") == "fit"]
    if not candidates:
        return {
            "artifact_type": "li7700_wms_line_shape_fit_v1",
            "status": "not_available",
            "quality_status": "not_available",
            "candidate_fits": [],
            "selected_fit": {},
            "reason": "No finite Gaussian/Lorentzian candidate fit could be evaluated.",
        }
    selected = min(candidates, key=lambda item: float(item.get("rmse", math.inf)))
    normalized_rmse = float(selected.get("normalized_rmse", math.inf))
    area_ratio = float(selected.get("area", 0.0) / integrated_area) if integrated_area > 0.0 else math.inf
    quality_status = "pass" if normalized_rmse <= 0.15 and 0.65 <= area_ratio <= 1.35 else ("warning" if normalized_rmse <= 0.35 else "fail")
    asymmetry = _li7700_wms_asymmetry(axis=axis, absorption=absorption, center=centroid)
    return {
        "artifact_type": "li7700_wms_line_shape_fit_v1",
        "status": "fit",
        "quality_status": quality_status,
        "selected_model": selected.get("model", ""),
        "selected_fit": selected,
        "candidate_fits": candidates,
        "integrated_area": integrated_area,
        "selected_to_integrated_area_ratio": area_ratio,
        "centroid": centroid,
        "moment_sigma": sigma,
        "asymmetry": asymmetry,
        "provenance": "LI-7700 WMS line-shape fit v1 evaluates Gaussian and Lorentzian candidates using deterministic least-squares amplitude estimates.",
        "limitations": [
            "This fit is an auditable open implementation and does not claim proprietary LI-7700 firmware equivalence.",
            "Real LI-7700 WMS scan fixtures with EddyPro golden outputs are required to tune acceptance thresholds.",
        ],
    }


def _li7700_wms_candidate_fit(
    *,
    axis: np.ndarray,
    absorption: np.ndarray,
    model: str,
    center: float,
    width: float,
) -> dict[str, Any]:
    if width <= 0.0 or not math.isfinite(width):
        return {"model": model, "status": "invalid_width"}
    if model == "gaussian":
        shape = np.exp(-0.5 * ((axis - center) / width) ** 2)
    elif model == "lorentzian":
        shape = 1.0 / (1.0 + ((axis - center) / width) ** 2)
    else:
        return {"model": model, "status": "unknown_model"}
    denom = float(np.dot(shape, shape))
    if denom <= 0.0 or not math.isfinite(denom):
        return {"model": model, "status": "singular"}
    amplitude = max(float(np.dot(absorption, shape) / denom), 0.0)
    fitted = amplitude * shape
    residual = absorption - fitted
    rmse = float(math.sqrt(float(np.mean(residual ** 2))))
    peak = max(float(np.max(absorption)), 1.0e-12)
    return {
        "model": model,
        "status": "fit",
        "center": center,
        "width": width,
        "amplitude": amplitude,
        "area": float(np.trapezoid(fitted, axis)),
        "rmse": rmse,
        "normalized_rmse": rmse / peak,
        "max_abs_residual": float(np.max(np.abs(residual))),
    }


def _li7700_wms_asymmetry(*, axis: np.ndarray, absorption: np.ndarray, center: float) -> float:
    left = absorption[axis < center]
    right = absorption[axis > center]
    left_area = float(np.trapezoid(left, axis[axis < center])) if left.size >= 2 else 0.0
    right_area = float(np.trapezoid(right, axis[axis > center])) if right.size >= 2 else 0.0
    denom = max(abs(left_area) + abs(right_area), 1.0e-12)
    return float((right_area - left_area) / denom)


def _li7700_self_heating_factor(
    config: dict[str, Any],
    *,
    mean_temp_c: float,
) -> tuple[float, str, dict[str, Any]]:
    mode = str(config.get("mode", "not_configured")).strip().lower()
    if mode not in {"empirical", "configured", "proxy"}:
        return (
            1.0,
            "not_configured",
            {
                "mode": "not_configured",
                "reason": "No LI-7700 self-heating empirical parameters were configured.",
            },
        )
    temp_excess = config.get("temperature_excess_c")
    if temp_excess is None and config.get("sensor_body_temp_c") is not None:
        temp_excess = float(config.get("sensor_body_temp_c")) - float(mean_temp_c)
    temp_excess = float(temp_excess or 0.0)
    coefficient = float(config.get("flux_sensitivity_per_c", 0.0) or 0.0)
    factor = _bounded_float(1.0 + coefficient * temp_excess, default=1.0, lower=0.7, upper=1.3)
    return (
        factor,
        "applied_empirical",
        {
            "mode": "empirical",
            "factor": factor,
            "temperature_excess_c": temp_excess,
            "flux_sensitivity_per_c": coefficient,
        },
    )


# ---------------------------------------------------------------------------
# Stationarity metrics
# ---------------------------------------------------------------------------

def _eddypro_partial_flag_lf(value: float | int | None) -> int:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return 9
    if not math.isfinite(val):
        return 9
    if 0 <= val <= 15:
        return 1
    if val <= 30:
        return 2
    if val <= 50:
        return 3
    if val <= 75:
        return 4
    if val <= 100:
        return 5
    if val <= 250:
        return 6
    if val <= 500:
        return 7
    if val <= 1000:
        return 8
    return 9


def compute_stationarity_metrics(
    *,
    w_series: np.ndarray,
    scalar_series: np.ndarray,
    detrend_mode: str = "block_mean",
) -> StationarityMetrics:
    n = min(w_series.size, scalar_series.size)
    if n < 120:
        return StationarityMetrics(
            score=None,
            detail={"status": "insufficient_data", "reason": "not enough samples for stationarity test", "sample_count": n},
        )

    w = np.asarray(w_series[:n], dtype=float)
    s = np.asarray(scalar_series[:n], dtype=float)

    n_sub = 6
    sub_len = n // n_sub
    if sub_len < 6:
        return StationarityMetrics(
            score=None,
            detail={"status": "insufficient_data", "reason": "sub-window too short", "sample_count": n, "sub_windows": n_sub},
        )

    full_cov = float(np.mean((w - float(np.mean(w))) * (s - float(np.mean(s)))))
    sub_covs: list[float] = []
    for i in range(n_sub):
        start = i * sub_len
        end = start + sub_len
        sub_w = w[start:end]
        sub_s = s[start:end]
        sub_covs.append(float(np.mean((sub_w - float(np.mean(sub_w))) * (sub_s - float(np.mean(sub_s))))))

    sub_mean = float(np.mean(sub_covs))
    sub_std = float(np.std(sub_covs))
    if abs(full_cov) < 1e-12 and sub_std < 1e-12:
        score = 100.0
    elif abs(full_cov) < 1e-12:
        score = 0.0
    else:
        ratio = abs(sub_mean - full_cov) / max(abs(full_cov), 1e-9)
        score = float(np.clip(100.0 * (1.0 - min(ratio, 1.0)), 0.0, 100.0))
    percent_difference = abs(sub_mean - full_cov) * 100.0 / max(abs(full_cov), 1e-9)

    return StationarityMetrics(
        score=score,
        detail={
            "status": "ok",
            "full_covariance": full_cov,
            "sub_window_mean": sub_mean,
            "sub_window_std": sub_std,
            "n_sub_windows": n_sub,
            "sub_window_length": sub_len,
            "percent_difference": percent_difference,
            "eddypro_partial_flag_lf": _eddypro_partial_flag_lf(percent_difference),
            "provenance": "EddyPro-style stationarity test: full-window covariance compared with the mean of six sub-window covariances.",
        },
    )


# ---------------------------------------------------------------------------
# Turbulence metrics
# ---------------------------------------------------------------------------

def compute_turbulence_metrics(
    *,
    u_series: np.ndarray,
    v_series: np.ndarray,
    w_series: np.ndarray,
    detrend_mode: str = "block_mean",
    u_valid_ratio: float = 0.0,
    v_valid_ratio: float = 0.0,
    w_valid_ratio: float = 0.0,
) -> TurbulenceMetrics:
    mode = normalize_detrend_mode(detrend_mode)
    n = min(u_series.size, v_series.size, w_series.size)
    if n < 60 or u_valid_ratio < 0.3 or v_valid_ratio < 0.3 or w_valid_ratio < 0.3:
        return TurbulenceMetrics(
            score=None, ustar=None,
            detail={"status": "insufficient_data", "reason": "not enough valid wind samples for turbulence assessment", "sample_count": n},
        )

    u = _detrend(u_series[:n], mode)
    v = _detrend(v_series[:n], mode)
    w = _detrend(w_series[:n], mode)

    ustar = (abs(float(np.mean(u * w))) + abs(float(np.mean(v * w)))) ** 0.25

    sigma_u = float(np.std(u))
    sigma_v = float(np.std(v))
    sigma_w = float(np.std(w))
    mean_u = float(np.mean(u_series[:n]))

    if ustar < 0.1 or mean_u < 0.5:
        score = float(np.clip(100.0 * ustar / 0.1, 0.0, 100.0))
    else:
        itc = sigma_w / max(mean_u, 1e-6)
        score = float(np.clip(100.0 * (1.0 - min(itc / 1.0, 1.0)), 0.0, 100.0))

    return TurbulenceMetrics(
        score=score, ustar=ustar,
        detail={
            "status": "ok",
            "ustar": ustar,
            "sigma_u": sigma_u,
            "sigma_v": sigma_v,
            "sigma_w": sigma_w,
            "mean_u": mean_u,
        },
    )


# ---------------------------------------------------------------------------
# Uncertainty metrics
# ---------------------------------------------------------------------------

def compute_uncertainty_metrics(
    *,
    flux_metrics: dict[str, float],
    lag_confidence: float,
    stationarity: StationarityMetrics,
    turbulence: TurbulenceMetrics,
    continuity_ratio: float,
    missing_ratio: float,
) -> UncertaintyMetrics:
    raw_flux = abs(flux_metrics.get("raw_flux", 0.0))
    primary_flux = float(flux_metrics.get("primary_flux", flux_metrics.get("density_corrected_flux", 0.0)) or 0.0)
    density_corrected_flux = abs(flux_metrics.get("density_corrected_flux", 0.0))
    density_delta_ratio = abs(density_corrected_flux - raw_flux) / max(raw_flux, 1e-12)
    random_component = max(0.0, 1.0 - float(lag_confidence))
    stationarity_component = max(0.0, 1.0 - float((stationarity.score if stationarity.score is not None else 50.0) / 100.0))
    turbulence_component = max(0.0, 1.0 - float((turbulence.score if turbulence.score is not None else 50.0) / 100.0))
    continuity_component = max(0.0, 1.0 - float(continuity_ratio))
    density_component = min(1.0, float(density_delta_ratio))
    components = {
        "random_component": round(random_component, 4),
        "stationarity_component": round(stationarity_component, 4),
        "turbulence_component": round(turbulence_component, 4),
        "continuity_component": round(continuity_component, 4),
        "density_component": round(density_component, 4),
    }
    relative_uncertainty = float(np.mean(list(components.values()))) if components else 0.0
    band = build_uncertainty_band(
        estimate=primary_flux,
        relative_uncertainty=relative_uncertainty,
        confidence_level=_DEFAULT_UNCERTAINTY_CONFIDENCE_LEVEL,
    )
    if raw_flux < 1e-12:
        return UncertaintyMetrics(
            detail={
                "status": "negligible_flux",
                "reason": "flux magnitude is negligible",
                "selected_method": "composite_empirical",
                "relative_uncertainty": 0.0,
                "overall_confidence": 1.0,
                "components": components,
                "random_component": components["random_component"],
                "stationarity_component": components["stationarity_component"],
                "turbulence_component": components["turbulence_component"],
                "continuity_component": components["continuity_component"],
                "density_component": components["density_component"],
                "confidence_level": band["confidence_level"],
                "random_error_sigma": band["random_error_sigma"],
                "uncertainty_band_half_width": band["uncertainty_band_half_width"],
                "interval_lower": band["interval_lower"],
                "interval_upper": band["interval_upper"],
                "limitations": [
                    "Empirical fallback is designed for quick RP screening, not formal interval estimation",
                    "Systematic bias and representativeness errors are not included",
                ],
                "provenance": "Composite empirical RP uncertainty rollup",
            }
        )

    return UncertaintyMetrics(
        detail={
            "status": "ok",
            "selected_method": "composite_empirical",
            "relative_uncertainty": round(relative_uncertainty, 4),
            "overall_confidence": round(max(0.0, 1.0 - relative_uncertainty), 4),
            "components": components,
            "random_component": components["random_component"],
            "stationarity_component": components["stationarity_component"],
            "turbulence_component": components["turbulence_component"],
            "continuity_component": components["continuity_component"],
            "density_component": components["density_component"],
            "confidence_level": band["confidence_level"],
            "random_error_sigma": band["random_error_sigma"],
            "uncertainty_band_half_width": band["uncertainty_band_half_width"],
            "interval_lower": band["interval_lower"],
            "interval_upper": band["interval_upper"],
            "limitations": [
                "Empirical fallback is designed for quick RP screening, not formal interval estimation",
                "Systematic bias and representativeness errors are not included",
                f"Missing ratio {missing_ratio:.3f} is only represented indirectly via continuity and density terms",
            ],
            "provenance": "Composite empirical RP uncertainty rollup",
        }
    )


# ---------------------------------------------------------------------------
# Statistical screening
# ---------------------------------------------------------------------------

_DEFAULT_ABSOLUTE_LIMITS: dict[str, tuple[float, float]] = {
    "co2_ppm": (0.0, 1500.0),
    "h2o_mmol": (0.0, 50.0),
    "pressure_kpa": (50.0, 120.0),
    "w": (-30.0, 30.0),
    "u": (-30.0, 30.0),
    "v": (-30.0, 30.0),
}


# ---------------------------------------------------------------------------
# Advanced statistical tests
# ---------------------------------------------------------------------------

def check_amplitude_resolution(
    series: np.ndarray,
    *,
    resolution: float | None = None,
    ratio_threshold: float = 10.0,
) -> dict[str, Any]:
    valid = series[~np.isnan(series)]
    if valid.size < 10:
        return {"test": "amplitude_resolution", "status": "insufficient_data", "detail": {"sample_count": valid.size}}
    if resolution is None:
        diffs = np.diff(np.sort(np.unique(valid)))
        if diffs.size == 0:
            return {"test": "amplitude_resolution", "status": "constant_signal", "detail": {"resolution": 0.0, "signal_std": float(np.std(valid))}}
        resolution = float(np.min(diffs))
    signal_std = float(np.std(valid))
    if signal_std < 1e-12:
        return {"test": "amplitude_resolution", "status": "constant_signal", "detail": {"resolution": resolution, "signal_std": 0.0}}
    ratio = signal_std / resolution
    passed = ratio >= ratio_threshold
    return {
        "test": "amplitude_resolution",
        "status": "pass" if passed else "fail",
        "detail": {"resolution": resolution, "signal_std": signal_std, "ratio": ratio, "threshold": ratio_threshold},
    }


def check_time_lag(
    w_series: np.ndarray,
    scalar_series: np.ndarray,
    sample_rate_hz: float,
    *,
    max_lag_s: float = 5.0,
    confidence_threshold: float = 0.4,
) -> dict[str, Any]:
    n = min(w_series.size, scalar_series.size)
    if n < 20:
        return {"test": "time_lag_test", "status": "insufficient_data", "detail": {"sample_count": n}}
    w = _detrend(w_series[:n], "linear")
    s = _detrend(scalar_series[:n], "linear")
    max_lag = max(1, int(max_lag_s * sample_rate_hz))
    lags = np.arange(-max_lag, max_lag + 1, dtype=int)
    curve = np.zeros_like(lags, dtype=float)
    for idx, lag in enumerate(lags):
        if lag < 0:
            left, right = w[:lag], s[-lag:]
        elif lag > 0:
            left, right = w[lag:], s[:-lag]
        else:
            left, right = w, s
        if left.size > 0 and right.size > 0:
            curve[idx] = float(np.mean(left * right))
    max_abs = max(np.max(np.abs(curve)), 1e-9)
    curve = curve / max_abs
    peak_idx = int(np.argmax(np.abs(curve)))
    peak_lag_s = float(lags[peak_idx] / sample_rate_hz)
    peak_value = float(curve[peak_idx])
    others = np.delete(np.abs(curve), peak_idx)
    second_peak = float(np.max(others)) if others.size > 0 else 0.0
    prominence = abs(peak_value) - second_peak
    confidence = float(np.clip(0.45 + prominence * 0.55, 0.0, 1.0))
    passed = confidence >= confidence_threshold
    return {
        "test": "time_lag_test",
        "status": "pass" if passed else "fail",
        "detail": {
            "peak_lag_s": peak_lag_s,
            "confidence": confidence,
            "confidence_threshold": confidence_threshold,
            "peak_value": peak_value,
        },
    }


def check_angle_of_attack(
    u: np.ndarray,
    w: np.ndarray,
    *,
    max_angle_deg: float = 40.0,
) -> dict[str, Any]:
    n = min(u.size, w.size)
    if n < 10:
        return {"test": "angle_of_attack", "status": "insufficient_data", "detail": {"sample_count": n}}
    speed = np.sqrt(u[:n] ** 2 + w[:n] ** 2)
    valid_mask = speed > 0.1
    if not np.any(valid_mask):
        return {"test": "angle_of_attack", "status": "insufficient_data", "detail": {"valid_count": 0}}
    angles = np.degrees(np.arctan2(w[:n][valid_mask], u[:n][valid_mask]))
    exceed_count = int(np.sum(np.abs(angles) > max_angle_deg))
    exceed_fraction = exceed_count / int(np.sum(valid_mask))
    passed = exceed_fraction < 0.05
    return {
        "test": "angle_of_attack",
        "status": "pass" if passed else "fail",
        "detail": {
            "mean_angle_deg": float(np.mean(angles)),
            "max_angle_deg": float(np.max(np.abs(angles))),
            "exceed_fraction": exceed_fraction,
            "exceed_count": exceed_count,
            "threshold_deg": max_angle_deg,
            "max_exceed_fraction": 0.05,
        },
    }


def check_steadiness_of_horizontal_wind(
    u: np.ndarray,
    v: np.ndarray,
    *,
    cv_threshold: float = 0.50,
) -> dict[str, Any]:
    n = min(u.size, v.size)
    if n < 10:
        return {"test": "steadiness_of_horizontal_wind", "status": "insufficient_data", "detail": {"sample_count": n}}
    speed = np.sqrt(u[:n] ** 2 + v[:n] ** 2)
    mean_speed = float(np.mean(speed))
    if mean_speed < 1e-6:
        return {"test": "steadiness_of_horizontal_wind", "status": "calm", "detail": {"mean_speed": mean_speed}}
    cv = float(np.std(speed)) / mean_speed
    passed = cv < cv_threshold
    return {
        "test": "steadiness_of_horizontal_wind",
        "status": "pass" if passed else "fail",
        "detail": {
            "mean_speed": mean_speed,
            "speed_std": float(np.std(speed)),
            "cv": cv,
            "threshold": cv_threshold,
        },
    }


def optimize_lag(
    w_series: np.ndarray,
    co2_series: np.ndarray,
    h2o_series: np.ndarray,
    sample_rate_hz: float,
    *,
    search_window_s: float = 4.0,
    expected_lag_s: float | None = None,
) -> dict[str, Any]:
    max_lag = max(1, int(search_window_s * sample_rate_hz))
    lags = np.arange(-max_lag, max_lag + 1, dtype=int)
    co2_det = _detrend(co2_series, "linear")
    h2o_det = _detrend(h2o_series, "linear")
    w_det = _detrend(w_series, "linear")
    co2_curve = np.zeros_like(lags, dtype=float)
    h2o_curve = np.zeros_like(lags, dtype=float)
    for idx, lag in enumerate(lags):
        if lag < 0:
            wl, cl, hl = w_det[:lag], co2_det[-lag:], h2o_det[-lag:]
        elif lag > 0:
            wl, cl, hl = w_det[lag:], co2_det[:-lag], h2o_det[:-lag]
        else:
            wl, cl, hl = w_det, co2_det, h2o_det
        if wl.size > 0:
            co2_curve[idx] = float(np.mean(wl * cl)) if cl.size == wl.size else 0.0
            h2o_curve[idx] = float(np.mean(wl * hl)) if hl.size == wl.size else 0.0
    co2_peak = int(np.argmax(np.abs(co2_curve)))
    h2o_peak = int(np.argmax(np.abs(h2o_curve)))
    co2_lag_s = float(lags[co2_peak] / sample_rate_hz)
    h2o_lag_s = float(lags[h2o_peak] / sample_rate_hz)
    return {
        "co2_lag_s": co2_lag_s,
        "h2o_lag_s": h2o_lag_s,
        "co2_curve": [float(v) for v in co2_curve],
        "h2o_curve": [float(v) for v in h2o_curve],
        "lag_curve_x": [float(lag / sample_rate_hz) for lag in lags],
    }


def optimize_h2o_lag_rh(
    w_series: np.ndarray,
    h2o_series: np.ndarray,
    temp_c: np.ndarray,
    pressure_kpa: np.ndarray,
    sample_rate_hz: float,
    *,
    search_window_s: float = 4.0,
) -> dict[str, Any]:
    n = min(w_series.size, h2o_series.size, temp_c.size, pressure_kpa.size)
    if n < 20:
        return {"h2o_lag_s": 0.0, "rh_adjusted": False, "detail": {"reason": "insufficient_data"}}
    mean_t = float(np.mean(temp_c[:n])) + 273.15
    mean_p = float(np.mean(pressure_kpa[:n])) * 1000.0
    es = 611.2 * math.exp(17.67 * (mean_t - 273.15) / (mean_t - 29.65)) if mean_t > 273.15 else 611.2
    mean_h2o = float(np.mean(h2o_series[:n]))
    rh_approx = min(1.0, max(0.0, (mean_h2o * mean_t * 8.314) / (es * 1000.0))) if es > 0 else 0.5
    base_result = optimize_lag(w_series[:n], h2o_series[:n], h2o_series[:n], sample_rate_hz, search_window_s=search_window_s)
    h2o_lag_s = base_result["h2o_lag_s"]
    if rh_approx > 0.85:
        h2o_lag_s *= 0.9
        rh_note = "high RH (>85%): H2O lag reduced by 10% (v1 approximation)"
    elif rh_approx < 0.30:
        h2o_lag_s *= 1.1
        rh_note = "low RH (<30%): H2O lag increased by 10% (v1 approximation)"
    else:
        rh_note = "moderate RH: no RH-dependent adjustment"
    return {
        "h2o_lag_s": h2o_lag_s,
        "rh_approx": rh_approx,
        "rh_adjusted": rh_approx > 0.85 or rh_approx < 0.30,
        "detail": {"rh_note": rh_note, "base_h2o_lag_s": base_result["h2o_lag_s"]},
    }


def run_statistical_screening(
    series_dict: dict[str, np.ndarray],
    *,
    constant_threshold: float = 1e-6,
    skewness_threshold: float = 2.0,
    kurtosis_threshold: float = 7.0,
    dropout_min_run: int = 10,
    spike_sigma: float = 5.0,
    discontinuity_sigma: float = 8.0,
    absolute_limits: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    limits = {**_DEFAULT_ABSOLUTE_LIMITS, **(absolute_limits or {})}
    all_issues: list[str] = []
    all_qc_reasons: list[str] = []
    detail: dict[str, Any] = {}

    for name, raw_series in series_dict.items():
        series = np.asarray(raw_series, dtype=float)
        valid = series[~np.isnan(series)]
        var_detail: dict[str, Any] = {}

        if valid.size == 0:
            all_issues.append(f"{name}_missing")
            all_qc_reasons.append(f"{name} series is missing")
            detail[name] = {"status": "missing", "valid_count": 0}
            continue

        # constant signal
        std_val = float(np.std(valid))
        if std_val < constant_threshold:
            all_issues.append(f"{name}_constant")
            all_qc_reasons.append(f"{name} signal is constant (std={std_val:.2e})")
            var_detail["constant"] = {"std": std_val, "threshold": constant_threshold}

        # skewness
        if valid.size >= 3 and std_val > constant_threshold:
            mean_val = float(np.mean(valid))
            skew_val = float(np.mean(((valid - mean_val) / std_val) ** 3))
            if abs(skew_val) > skewness_threshold:
                all_issues.append(f"{name}_skewness")
                all_qc_reasons.append(f"{name} skewness is high ({skew_val:.2f})")
            var_detail["skewness"] = {"value": skew_val, "threshold": skewness_threshold}

        # kurtosis (excess)
        if valid.size >= 4 and std_val > constant_threshold:
            mean_val = float(np.mean(valid))
            kurt_val = float(np.mean(((valid - mean_val) / std_val) ** 4)) - 3.0
            if kurt_val > kurtosis_threshold:
                all_issues.append(f"{name}_kurtosis")
                all_qc_reasons.append(f"{name} kurtosis is high ({kurt_val:.2f})")
            var_detail["kurtosis"] = {"value": kurt_val, "threshold": kurtosis_threshold}

        # dropout (flat runs)
        if valid.size >= dropout_min_run:
            max_run = 1
            current_run = 1
            for i in range(1, valid.size):
                if abs(valid[i] - valid[i - 1]) < 1e-9:
                    current_run += 1
                    max_run = max(max_run, current_run)
                else:
                    current_run = 1
            if max_run >= dropout_min_run:
                all_issues.append(f"{name}_dropout")
                all_qc_reasons.append(f"{name} contains dropout/flat segments (run={max_run})")
            var_detail["dropout"] = {"max_run": max_run, "threshold": dropout_min_run}

        # spike
        if valid.size >= 10 and std_val > constant_threshold:
            mean_val = float(np.mean(valid))
            spike_count = int(np.sum(np.abs(valid - mean_val) > spike_sigma * std_val))
            if spike_count > 0:
                all_issues.append(f"{name}_spike")
                all_qc_reasons.append(f"{name} contains spike values ({spike_count} points)")
            var_detail["spike"] = {"count": spike_count, "sigma_threshold": spike_sigma}

        # absolute limit
        if name in limits:
            lo, hi = limits[name]
            over_count = int(np.sum((valid < lo) | (valid > hi)))
            if over_count > 0:
                all_issues.append(f"{name}_absolute_limit")
                all_qc_reasons.append(f"{name} exceeds absolute limits ({over_count} points)")
            var_detail["absolute_limit"] = {"count": over_count, "range": [lo, hi]}

        # discontinuity
        if valid.size >= 10:
            diffs = np.abs(np.diff(valid))
            if diffs.size > 0:
                rolling_std = float(np.std(diffs))
                if rolling_std > 1e-9:
                    disc_count = int(np.sum(diffs > discontinuity_sigma * rolling_std))
                    if disc_count > 0:
                        all_issues.append(f"{name}_discontinuity")
                        all_qc_reasons.append(f"{name} contains abrupt discontinuity ({disc_count} points)")
                    var_detail["discontinuity"] = {"count": disc_count, "sigma_threshold": discontinuity_sigma}

        var_detail["valid_count"] = int(valid.size)
        detail[name] = var_detail

    return {
        "issues": all_issues,
        "qc_reasons": all_qc_reasons,
        "detail": detail,
    }


def compare_window_to_reference(
    window: object,
    reference: object,
    *,
    flux_rel_threshold: float = 0.10,
    lag_abs_threshold_s: float = 0.5,
    wpl_rel_threshold: float = 0.20,
    qc_grade_must_match: bool = False,
) -> dict[str, Any]:
    from models.rp_models import BenchmarkFieldComparison, BenchmarkWindowResult, EddyProReferenceWindow, WindowRPResult
    if not isinstance(window, WindowRPResult) or not isinstance(reference, EddyProReferenceWindow):
        return {"error": "window must be WindowRPResult, reference must be EddyProReferenceWindow"}
    comparisons: list[BenchmarkFieldComparison] = []
    notes: list[str] = []
    diag = window.diagnostics if window.diagnostics else {}

    def _compare_numeric(
        field_name: str,
        ref_val: float | None,
        act_val: float | None,
        threshold: float,
        mode: str = "relative",
    ) -> BenchmarkFieldComparison:
        if ref_val is None or act_val is None:
            return BenchmarkFieldComparison(
                field_name=field_name, reference_value=ref_val, actual_value=act_val,
                absolute_error=None, relative_error=None, threshold=threshold,
                passed=True, note="skipped: missing value",
            )
        abs_err = abs(act_val - ref_val)
        rel_err = abs_err / abs(ref_val) if abs(ref_val) > 1e-15 else None
        if mode == "relative":
            passed = (rel_err if rel_err is not None else abs_err) <= threshold
        else:
            passed = abs_err <= threshold
        note = ""
        if not passed:
            note = f"{field_name}: actual={act_val:.6g}, ref={ref_val:.6g}, rel_err={rel_err:.4f}" if rel_err is not None else f"{field_name}: actual={act_val:.6g}, ref={ref_val:.6g}, abs_err={abs_err:.6g}"
        return BenchmarkFieldComparison(
            field_name=field_name, reference_value=ref_val, actual_value=act_val,
            absolute_error=abs_err, relative_error=rel_err, threshold=threshold,
            passed=passed, note=note,
        )

    comparisons.append(_compare_numeric("primary_flux", reference.primary_flux, window.primary_flux, flux_rel_threshold, "relative"))
    comparisons.append(_compare_numeric("lag_seconds", reference.lag_seconds, window.lag_seconds, lag_abs_threshold_s, "absolute"))
    comparisons.append(_compare_numeric("wpl_water_vapor_term", reference.wpl_water_vapor_term, diag.get("wpl_water_vapor_term"), wpl_rel_threshold, "relative"))
    comparisons.append(_compare_numeric("wpl_sensible_heat_term", reference.wpl_sensible_heat_term, diag.get("wpl_sensible_heat_term"), wpl_rel_threshold, "relative"))
    total_dc_ref = reference.total_density_correction
    total_dc_act = None
    wpl_wv = diag.get("wpl_water_vapor_term", 0.0)
    wpl_sh = diag.get("wpl_sensible_heat_term", 0.0)
    if isinstance(wpl_wv, (int, float)) and isinstance(wpl_sh, (int, float)):
        total_dc_act = wpl_wv + wpl_sh
    comparisons.append(_compare_numeric("total_density_correction", total_dc_ref, total_dc_act, wpl_rel_threshold, "relative"))

    if reference.primary_flux_source and window.primary_flux_source:
        src_match = reference.primary_flux_source == window.primary_flux_source
        comparisons.append(BenchmarkFieldComparison(
            field_name="primary_flux_source", reference_value=None, actual_value=None,
            absolute_error=None, relative_error=None, threshold=0.0,
            passed=src_match, note="" if src_match else f"source mismatch: ref={reference.primary_flux_source}, actual={window.primary_flux_source}",
        ))

    if reference.rotation_mode and window.rotation_mode:
        rot_match = reference.rotation_mode == window.rotation_mode or reference.rotation_mode == diag.get("applied_rotation_impl", "")
        comparisons.append(BenchmarkFieldComparison(
            field_name="rotation_mode", reference_value=None, actual_value=None,
            absolute_error=None, relative_error=None, threshold=0.0,
            passed=rot_match, note="" if rot_match else f"rotation mismatch: ref={reference.rotation_mode}, actual={window.rotation_mode}",
        ))

    if reference.lag_strategy and diag.get("lag_strategy"):
        ls_match = reference.lag_strategy == diag["lag_strategy"]
        comparisons.append(BenchmarkFieldComparison(
            field_name="lag_strategy", reference_value=None, actual_value=None,
            absolute_error=None, relative_error=None, threshold=0.0,
            passed=ls_match, note="" if ls_match else f"lag strategy mismatch: ref={reference.lag_strategy}, actual={diag['lag_strategy']}",
        ))

    if qc_grade_must_match and reference.qc_grade and window.qc_grade:
        grade_match = reference.qc_grade == window.qc_grade
        comparisons.append(BenchmarkFieldComparison(
            field_name="qc_grade", reference_value=None, actual_value=None,
            absolute_error=None, relative_error=None, threshold=0.0,
            passed=grade_match, note="" if grade_match else f"grade mismatch: ref={reference.qc_grade}, actual={window.qc_grade}",
        ))
    elif reference.qc_grade and window.qc_grade:
        ref_rank = {"A": 3, "B": 2, "C": 1}.get(reference.qc_grade, 0)
        act_rank = {"A": 3, "B": 2, "C": 1}.get(window.qc_grade, 0)
        within_one = abs(ref_rank - act_rank) <= 1
        comparisons.append(BenchmarkFieldComparison(
            field_name="qc_grade", reference_value=None, actual_value=None,
            absolute_error=None, relative_error=None, threshold=0.0,
            passed=within_one, note="" if within_one else f"grade differs by >1: ref={reference.qc_grade}, actual={window.qc_grade}",
        ))

    overall_pass = all(c.passed for c in comparisons)
    result = BenchmarkWindowResult(
        window_id=window.window_id,
        comparisons=comparisons,
        overall_pass=overall_pass,
        notes=notes,
    )
    return result.to_dict()


def load_eddypro_reference_json(path: str | object) -> list[dict[str, Any]]:
    from models.rp_models import EddyProReferenceWindow
    p = Path(path) if not isinstance(path, Path) else path
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "windows" in payload:
        payload = payload["windows"]
    if isinstance(payload, dict):
        payload = [payload]
    windows: list[dict[str, Any]] = []
    for item in payload:
        ref = EddyProReferenceWindow.from_dict(item)
        windows.append({
            "window_id": ref.window_id,
            "start_time": ref.start_time,
            "end_time": ref.end_time,
            "primary_flux": ref.primary_flux,
            "primary_flux_source": ref.primary_flux_source,
            "lag_seconds": ref.lag_seconds,
            "lag_strategy": ref.lag_strategy,
            "rotation_mode": ref.rotation_mode,
            "applied_rotation_impl": ref.applied_rotation_impl,
            "wpl_water_vapor_term": ref.wpl_water_vapor_term,
            "wpl_sensible_heat_term": ref.wpl_sensible_heat_term,
            "total_density_correction": ref.total_density_correction,
            "qc_grade": ref.qc_grade,
            "qc_score": ref.qc_score,
            "notes": ref.notes,
        })
    return windows


def load_eddypro_reference_csv(path: str | object, *, field_mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
    import csv as _csv
    from models.rp_models import EddyProReferenceWindow
    p = Path(path) if not isinstance(path, Path) else path
    default_mapping: dict[str, str] = {
        "window_id": "Filename",
        "start_time": "start_time",
        "end_time": "end_time",
        "primary_flux": "Fc",
        "primary_flux_source": "primary_flux_source",
        "lag_seconds": "lag_seconds",
        "lag_strategy": "lag_strategy",
        "rotation_mode": "rotation_mode",
        "applied_rotation_impl": "applied_rotation_impl",
        "wpl_water_vapor_term": "wpl_water_vapor_term",
        "wpl_sensible_heat_term": "wpl_sensible_heat_term",
        "total_density_correction": "total_density_correction",
        "qc_grade": "qc_grade",
        "qc_score": "qc_score",
    }
    if field_mapping:
        default_mapping.update(field_mapping)
    mapping = default_mapping
    windows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            mapped: dict[str, Any] = {}
            for target_key, source_col in mapping.items():
                val = row.get(source_col, "")
                if val == "" or val == "-9999" or val == "NaN":
                    mapped[target_key] = None
                else:
                    mapped[target_key] = val
            if not mapped.get("window_id"):
                mapped["window_id"] = f"ep_row_{len(windows)}"
            if not mapped.get("start_time"):
                mapped["start_time"] = ""
            if not mapped.get("end_time"):
                mapped["end_time"] = ""
            ref = EddyProReferenceWindow.from_dict(mapped)
            windows.append({
                "window_id": ref.window_id,
                "start_time": ref.start_time,
                "end_time": ref.end_time,
                "primary_flux": ref.primary_flux,
                "primary_flux_source": ref.primary_flux_source,
                "lag_seconds": ref.lag_seconds,
                "lag_strategy": ref.lag_strategy,
                "rotation_mode": ref.rotation_mode,
                "applied_rotation_impl": ref.applied_rotation_impl,
                "wpl_water_vapor_term": ref.wpl_water_vapor_term,
                "wpl_sensible_heat_term": ref.wpl_sensible_heat_term,
                "total_density_correction": ref.total_density_correction,
                "qc_grade": ref.qc_grade,
                "qc_score": ref.qc_score,
                "notes": ref.notes,
            })
    return windows


def run_benchmark_comparison(
    rp_result: object,
    reference_windows: list[dict[str, Any]],
    *,
    flux_rel_threshold: float = 0.10,
    lag_abs_threshold_s: float = 0.5,
    wpl_rel_threshold: float = 0.20,
    qc_grade_must_match: bool = False,
    time_match_tolerance_s: float = 60.0,
) -> list[dict[str, Any]]:
    from models.rp_models import EddyProReferenceWindow, RPRunResult
    if not isinstance(rp_result, RPRunResult):
        return []
    ref_by_id: dict[str, EddyProReferenceWindow] = {}
    ref_by_start: dict[str, EddyProReferenceWindow] = {}
    for rw in reference_windows:
        ref = EddyProReferenceWindow.from_dict(rw)
        ref_by_id[ref.window_id] = ref
        if ref.start_time:
            ref_by_start[ref.start_time] = ref
    results: list[dict[str, Any]] = []
    for window in rp_result.windows:
        ref = ref_by_id.get(window.window_id)
        match_strategy = "window_id_exact"
        matched_ref_id = window.window_id
        if ref is None:
            start_iso = window.start_time.isoformat() if hasattr(window.start_time, "isoformat") else str(window.start_time)
            ref = ref_by_start.get(start_iso)
            match_strategy = "start_time_exact"
            matched_ref_id = start_iso
        if ref is None and hasattr(window, "start_time"):
            from datetime import timedelta
            for ref_st, ref_obj in ref_by_start.items():
                try:
                    ref_dt = datetime.fromisoformat(ref_st)
                    delta = abs((window.start_time - ref_dt).total_seconds())
                    if delta <= time_match_tolerance_s:
                        ref = ref_obj
                        match_strategy = f"start_time_fuzzy({delta:.0f}s)"
                        matched_ref_id = ref_obj.window_id
                        break
                except (ValueError, TypeError):
                    continue
        if ref is None:
            results.append({
                "window_id": window.window_id,
                "comparisons": [],
                "overall_pass": True,
                "notes": ["no matching reference window"],
                "match_strategy": "none",
                "matched_reference_window_id": "",
            })
            continue
        bench = compare_window_to_reference(
            window, ref,
            flux_rel_threshold=flux_rel_threshold,
            lag_abs_threshold_s=lag_abs_threshold_s,
            wpl_rel_threshold=wpl_rel_threshold,
            qc_grade_must_match=qc_grade_must_match,
        )
        bench["match_strategy"] = match_strategy
        bench["matched_reference_window_id"] = matched_ref_id
        results.append(bench)
    return results


EDDYPRO_QC_TO_GRADE = {
    "0": "A",
    "1": "B",
    "2": "C",
    0: "A",
    1: "B",
    2: "C",
}


def eddypro_qc_flag_to_grade(flag: int | str | None) -> str:
    if flag is None:
        return ""
    return EDDYPRO_QC_TO_GRADE.get(flag, "")


def load_eddypro_reference_with_qc_mapping(path: str | object, *, qc_column: str = "qc_grade") -> list[dict[str, Any]]:
    p = Path(path) if not isinstance(path, Path) else path
    if p.suffix.lower() == ".json":
        windows = load_eddypro_reference_json(p)
    else:
        windows = load_eddypro_reference_csv(p)
    for w in windows:
        qc_val = w.get("qc_grade")
        if qc_val is not None and str(qc_val) in ("0", "1", "2"):
            w["qc_grade"] = eddypro_qc_flag_to_grade(qc_val)
    return windows


def list_available_references(references_root: str | Path | None = None) -> list[dict[str, Any]]:
    if references_root is None:
        references_root = Path(__file__).resolve().parent.parent.parent / "references" / "eddypro"
    root = Path(references_root)
    results: list[dict[str, Any]] = []
    for json_path in sorted(root.rglob("*.json")):
        if json_path.name.endswith("_provenance.json"):
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ref_id = payload.get("reference_id", json_path.stem)
        csv_path = json_path.with_suffix(".csv")
        provenance_path = json_path.parent / f"{json_path.stem}_provenance.json"
        results.append({
            "reference_id": ref_id,
            "json_path": str(json_path),
            "csv_path": str(csv_path) if csv_path.exists() else "",
            "provenance_path": str(provenance_path) if provenance_path.exists() else "",
            "source": payload.get("source", ""),
            "description": payload.get("description", ""),
            "site_info": payload.get("site_info", {}),
            "processing_settings": payload.get("processing_settings", {}),
            "method_metadata": payload.get("method_metadata", {}),
            "method_metadata_coverage": payload.get("method_metadata_coverage", {}),
            "window_count": len(payload.get("windows", [])),
        })
    return results


def generate_reference_provenance(path: str | Path) -> dict[str, Any]:
    p = Path(path) if not isinstance(path, Path) else path
    payload = json.loads(p.read_text(encoding="utf-8"))
    csv_path = p.with_suffix(".csv")
    provenance_path = p.parent / f"{p.stem}_provenance.json"
    existing_provenance: dict[str, Any] = {}
    if provenance_path.exists():
        try:
            existing_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    provenance = {
        "reference_id": payload.get("reference_id", p.stem),
        "original_file": str(csv_path) if csv_path.exists() else "",
        "original_file_name": csv_path.name if csv_path.exists() else "",
        "json_source": str(p),
        "normalization_time": payload.get("normalization_time", payload.get("created_at", "")),
        "normalization_script": "references/eddypro/normalize_reference.py",
        "field_mapping": payload.get("field_mapping", {}),
        "raw_columns": payload.get("raw_columns", []),
        "unmapped_columns": payload.get("unmapped_columns", []),
        "metadata_source_files": payload.get("metadata_source_files", []),
        "processing_settings": payload.get("processing_settings", {}),
        "method_metadata": payload.get("method_metadata", {}),
        "method_metadata_coverage": payload.get("method_metadata_coverage", {}),
        "qc_mapping_strategy": payload.get("qc_mapping_strategy", "EddyPro 0/1/2 -> gas_ec_studio A/B/C"),
        "known_limitations": payload.get("known_limitations", []),
        "window_count": len(payload.get("windows", [])),
        "required_fields_present": all(
            any(w.get(f) is not None for w in payload.get("windows", []))
            for f in ("window_id", "start_time", "end_time", "primary_flux")
        ),
    }
    if existing_provenance:
        for key in ("original_file", "original_file_name", "raw_columns"):
            if key in existing_provenance and key not in provenance:
                provenance[key] = existing_provenance[key]
    return provenance


# ---------------------------------------------------------------------------
# Footprint models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FootprintResult:
    method: str
    peak_distance_m: float
    offset_distance_m: float
    contribution_distances: dict[str, float]
    detail: dict[str, Any]


@dataclass(slots=True)
class Footprint2DGrid:
    method: str
    x_coords_m: list[float]
    y_coords_m: list[float]
    contribution_grid: list[list[float]]
    peak_downwind_m: float
    peak_crosswind_m: float
    half_width_m: float
    contribution_contours_m: dict[str, float]
    detail: dict[str, Any]


@dataclass(slots=True)
class MethodCompareResult:
    method_family: str
    selected_method: str
    methods_run: list[str]
    primary_metric: str
    primary_outputs: dict[str, float]
    consensus_value: float | None
    deviations: dict[str, float]
    recommendation: str
    recommendation_reason: str
    status: str
    detail: dict[str, Any]


def compute_footprint_kljun(
    *,
    ustar: float,
    mean_wind_speed: float,
    sigma_v: float,
    z_m: float,
    h: float,
    z0: float | None = None,
    ol: float | None = None,
) -> FootprintResult:
    if ustar < 1e-6 or mean_wind_speed < 1e-6 or z_m <= 0:
        return FootprintResult(
            method="kljun",
            peak_distance_m=0.0,
            offset_distance_m=0.0,
            contribution_distances={},
            detail={"status": "insufficient_data", "reason": "ustar or wind speed too low"},
        )
    z_eff = z_m - 0.67 * h if h > 0 else z_m
    if z_eff <= 0:
        z_eff = z_m * 0.1
    if ol is None:
        ol = -z_eff * (ustar ** 3) / (0.4 * 9.81 * max(abs(sigma_v), 1e-6) * ustar + 1e-12)
        if ol > 0:
            ol = -ol
    if z0 is None:
        z0 = max(0.1 * z_eff * math.exp(-0.4 * mean_wind_speed / max(ustar, 1e-6)), 1e-6)
    zeta = z_eff / ol if abs(ol) > 1e-6 else 0.0
    if zeta >= 0:
        xm = z_eff * (0.56 + 0.28 * abs(zeta) ** 0.6)
    else:
        xm = z_eff * 0.56 / (1.0 + 0.28 * abs(zeta) ** 0.6)
    peak_distance = max(xm, 0.1)
    offset_distance = peak_distance * 0.15
    contribution_distances = {}
    for pct in (10, 30, 50, 70, 90):
        scale = 0.3 + 0.7 * (pct / 100.0) ** 0.5
        contribution_distances[f"x{pct}"] = round(peak_distance * scale, 2)
    return FootprintResult(
        method="kljun",
        peak_distance_m=round(peak_distance, 2),
        offset_distance_m=round(offset_distance, 2),
        contribution_distances=contribution_distances,
        detail={
            "status": "ok",
            "reference": "Kljun et al. 2015",
            "inputs": {
                "ustar": round(ustar, 4),
                "mean_wind_speed": round(mean_wind_speed, 4),
                "sigma_v": round(sigma_v, 4),
                "z_m": round(z_m, 4),
                "canopy_height_m": round(h, 4),
            },
            "z_eff_m": round(z_eff, 2),
            "ol_m": round(ol, 2),
            "zeta": round(zeta, 4),
            "z0_m": round(z0, 4),
            "peak_distance_m": round(peak_distance, 2),
            "offset_distance_m": round(offset_distance, 2),
            "contribution_distances_m": dict(contribution_distances),
            "provenance": "Kljun et al. 2015, simplified parametric form",
            "limitations": [
                "Simplified parametric approximation, not full 2D model",
                "Assumes flat terrain and homogeneous surface",
                "Unstable conditions use empirical parameterization",
            ],
        },
    )


def compute_footprint_kormann_meixner(
    *,
    ustar: float,
    mean_wind_speed: float,
    sigma_v: float,
    z_m: float,
    h: float,
) -> FootprintResult:
    if ustar < 1e-6 or mean_wind_speed < 1e-6 or z_m <= 0:
        return FootprintResult(
            method="kormann_meixner",
            peak_distance_m=0.0,
            offset_distance_m=0.0,
            contribution_distances={},
            detail={"status": "insufficient_data", "reason": "ustar or wind speed too low"},
        )
    z_eff = z_m - 0.67 * h if h > 0 else z_m
    if z_eff <= 0:
        z_eff = z_m * 0.1
    u_star_ratio = ustar / max(mean_wind_speed, 1e-6)
    r = max(0.5, min(2.0, 1.0 + 0.5 * u_star_ratio))
    xm = z_eff / r
    peak_distance = max(xm, 0.1)
    offset_distance = peak_distance * 0.12
    contribution_distances = {}
    for pct in (10, 30, 50, 70, 90):
        scale = 0.25 + 0.75 * (pct / 100.0) ** 0.45
        contribution_distances[f"x{pct}"] = round(peak_distance * scale, 2)
    return FootprintResult(
        method="kormann_meixner",
        peak_distance_m=round(peak_distance, 2),
        offset_distance_m=round(offset_distance, 2),
        contribution_distances=contribution_distances,
        detail={
            "status": "ok",
            "reference": "Kormann & Meixner 2001",
            "inputs": {
                "ustar": round(ustar, 4),
                "mean_wind_speed": round(mean_wind_speed, 4),
                "sigma_v": round(sigma_v, 4),
                "z_m": round(z_m, 4),
                "canopy_height_m": round(h, 4),
            },
            "z_eff_m": round(z_eff, 2),
            "r_param": round(r, 3),
            "peak_distance_m": round(peak_distance, 2),
            "offset_distance_m": round(offset_distance, 2),
            "contribution_distances_m": dict(contribution_distances),
            "provenance": "Kormann & Meixner 2001, parametric power-law approximation",
            "limitations": [
                "Power-law wind profile approximation",
                "Assumes stationary conditions",
                "No crosswind dispersion in this simplified form",
            ],
        },
    )


def compute_footprint_hsieh(
    *,
    ustar: float,
    mean_wind_speed: float,
    z_m: float,
    h: float,
    ol: float | None = None,
) -> FootprintResult:
    if ustar < 1e-6 or mean_wind_speed < 1e-6 or z_m <= 0:
        return FootprintResult(
            method="hsieh",
            peak_distance_m=0.0,
            offset_distance_m=0.0,
            contribution_distances={},
            detail={"status": "insufficient_data", "reason": "ustar or wind speed too low"},
        )
    z_eff = z_m - 0.67 * h if h > 0 else z_m
    if z_eff <= 0:
        z_eff = z_m * 0.1
    if ol is None:
        ol = -100.0
    zeta = z_eff / ol if abs(ol) > 1e-6 else 0.0
    if zeta < -0.1:
        D = 0.28 * (z_eff ** 0.82) * (abs(ol) ** 0.18)
    elif zeta > 0.1:
        D = 2.44 * (z_eff ** 0.90) * (abs(ol) ** 0.10)
    else:
        D = 0.97 * z_eff ** 0.86
    peak_distance = max(D, 0.1)
    offset_distance = peak_distance * 0.10
    contribution_distances = {}
    for pct in (10, 30, 50, 70, 90):
        scale = 0.2 + 0.8 * (pct / 100.0) ** 0.5
        contribution_distances[f"x{pct}"] = round(peak_distance * scale, 2)
    return FootprintResult(
        method="hsieh",
        peak_distance_m=round(peak_distance, 2),
        offset_distance_m=round(offset_distance, 2),
        contribution_distances=contribution_distances,
        detail={
            "status": "ok",
            "reference": "Hsieh et al. 2000",
            "inputs": {
                "ustar": round(ustar, 4),
                "mean_wind_speed": round(mean_wind_speed, 4),
                "z_m": round(z_m, 4),
                "canopy_height_m": round(h, 4),
            },
            "z_eff_m": round(z_eff, 2),
            "ol_m": round(ol, 2),
            "zeta": round(zeta, 4),
            "D_param": round(D, 2),
            "peak_distance_m": round(peak_distance, 2),
            "offset_distance_m": round(offset_distance, 2),
            "contribution_distances_m": dict(contribution_distances),
            "provenance": "Hsieh et al. 2000, analytical approximation",
            "limitations": [
                "Analytical approximation for neutral/unstable/stable regimes",
                "Single-point source assumption",
                "No crosswind integration in this simplified form",
            ],
        },
    )


def compute_footprint(
    *,
    method: str = "kljun",
    ustar: float,
    mean_wind_speed: float,
    sigma_v: float = 0.0,
    z_m: float,
    h: float = 0.0,
    z0: float | None = None,
    ol: float | None = None,
) -> FootprintResult:
    if method == "kormann_meixner":
        return compute_footprint_kormann_meixner(
            ustar=ustar, mean_wind_speed=mean_wind_speed,
            sigma_v=sigma_v, z_m=z_m, h=h,
        )
    if method == "hsieh":
        return compute_footprint_hsieh(
            ustar=ustar, mean_wind_speed=mean_wind_speed,
            z_m=z_m, h=h, ol=ol,
        )
    return compute_footprint_kljun(
        ustar=ustar, mean_wind_speed=mean_wind_speed,
        sigma_v=sigma_v, z_m=z_m, h=h, z0=z0, ol=ol,
    )


def compute_footprint_2d_grid(
    *,
    footprint: FootprintResult | None = None,
    method: str = "kljun",
    ustar: float,
    mean_wind_speed: float,
    sigma_v: float = 0.0,
    z_m: float,
    h: float = 0.0,
    z0: float | None = None,
    ol: float | None = None,
    x_bins: int = 32,
    y_bins: int = 25,
    max_downwind_m: float | None = None,
    max_crosswind_m: float | None = None,
) -> Footprint2DGrid | None:
    """Build a compact 2D source-area grid from the selected footprint family.

    The grid is a window-level diagnostic artifact: the downwind distribution is
    anchored to the selected footprint method and the crosswind spread is a
    Gaussian dispersion envelope driven by sigma_v / wind speed.
    """
    if footprint is None:
        footprint = compute_footprint(
            method=method,
            ustar=ustar,
            mean_wind_speed=mean_wind_speed,
            sigma_v=sigma_v,
            z_m=z_m,
            h=h,
            z0=z0,
            ol=ol,
        )
    if footprint.peak_distance_m <= 0.0 or mean_wind_speed < 1e-6 or z_m <= 0.0:
        return None

    x_bins = max(8, min(int(x_bins or 32), 96))
    y_bins = max(7, min(int(y_bins or 25), 81))
    if y_bins % 2 == 0:
        y_bins += 1

    peak_x = max(float(footprint.peak_distance_m), 0.1)
    x90 = float(footprint.contribution_distances.get("x90", peak_x * 4.0) or peak_x * 4.0)
    x_max = max(float(max_downwind_m or 0.0), x90 * 1.25, peak_x * 5.0, z_m * 10.0, 1.0)
    dispersion_ratio = abs(float(sigma_v or 0.0)) / max(abs(float(mean_wind_speed or 0.0)), 0.1)
    y_extent = max(float(max_crosswind_m or 0.0), x90 * (0.12 + 0.35 * dispersion_ratio), z_m * 2.5, 1.0)

    x_coords = np.linspace(x_max / x_bins, x_max, x_bins)
    y_coords = np.linspace(-y_extent, y_extent, y_bins)

    shape_by_method = {
        "kljun": 0.70,
        "kormann_meixner": 0.82,
        "hsieh": 0.76,
    }
    log_sigma = shape_by_method.get(str(footprint.method), 0.74)
    safe_x = np.maximum(x_coords, 1e-6)
    downwind = np.exp(-0.5 * (np.log(safe_x / peak_x) / log_sigma) ** 2) / safe_x
    downwind = np.where(np.isfinite(downwind), downwind, 0.0)
    if float(np.sum(downwind)) <= 1e-15:
        return None

    grid = np.zeros((y_bins, x_bins), dtype=float)
    for idx, x_value in enumerate(x_coords):
        sigma_y = max(0.35, z_m * 0.20 + x_value * (0.07 + 0.22 * dispersion_ratio))
        crosswind = np.exp(-0.5 * (y_coords / sigma_y) ** 2)
        crosswind_sum = float(np.sum(crosswind))
        if crosswind_sum > 1e-15:
            grid[:, idx] = downwind[idx] * crosswind / crosswind_sum

    total = float(np.sum(grid))
    if total <= 1e-15:
        return None
    grid = grid / total

    peak_idx = np.unravel_index(int(np.argmax(grid)), grid.shape)
    peak_downwind_m = float(x_coords[peak_idx[1]])
    peak_crosswind_m = float(y_coords[peak_idx[0]])
    peak_column = grid[:, peak_idx[1]]
    half_mask = peak_column >= (float(np.max(peak_column)) * 0.5)
    half_width = float(np.max(np.abs(y_coords[half_mask]))) if np.any(half_mask) else 0.0

    downwind_cumulative = np.cumsum(np.sum(grid, axis=0))
    contribution_contours: dict[str, float] = {}
    for pct in (10, 30, 50, 70, 90):
        target = pct / 100.0
        contour_idx = int(np.searchsorted(downwind_cumulative, target, side="left"))
        contour_idx = min(max(contour_idx, 0), len(x_coords) - 1)
        contribution_contours[f"x{pct}"] = round(float(x_coords[contour_idx]), 2)

    return Footprint2DGrid(
        method=str(footprint.method),
        x_coords_m=[round(float(value), 3) for value in x_coords],
        y_coords_m=[round(float(value), 3) for value in y_coords],
        contribution_grid=[
            [round(float(value), 8) for value in row]
            for row in grid.tolist()
        ],
        peak_downwind_m=round(peak_downwind_m, 2),
        peak_crosswind_m=round(peak_crosswind_m, 2),
        half_width_m=round(half_width, 2),
        contribution_contours_m=contribution_contours,
        detail={
            "status": "ok",
            "grid_shape": [int(y_bins), int(x_bins)],
            "grid_sum": round(float(np.sum(grid)), 6),
            "downwind_extent_m": round(float(x_max), 2),
            "crosswind_extent_m": round(float(y_extent), 2),
            "dispersion_ratio": round(float(dispersion_ratio), 4),
            "source_peak_distance_m": round(float(footprint.peak_distance_m), 2),
            "source_contribution_distances_m": dict(footprint.contribution_distances),
            "provenance": (
                "2D footprint grid derived from selected 1D footprint family and "
                "sigma_v wind-direction dispersion envelope"
            ),
            "method_provenance": footprint.detail.get("provenance", ""),
            "limitations": [
                "Diagnostic 2D source-area grid, not a full analytical footprint solver",
                "Assumes flat homogeneous terrain and symmetric crosswind dispersion",
                "Crosswind width uses sigma_v / mean wind speed as an empirical envelope",
            ],
        },
    )


# ---------------------------------------------------------------------------
# Random uncertainty family
# ---------------------------------------------------------------------------

def compute_uncertainty_mann_lenschow(
    *,
    cov_w_scalar: float,
    var_w: float,
    var_scalar: float,
    n_samples: int,
    averaging_period_s: float,
    integral_timescale_s: float | None = None,
) -> dict[str, Any]:
    if n_samples < 100 or abs(cov_w_scalar) < 1e-15:
        band = build_uncertainty_band(estimate=cov_w_scalar, random_error=None)
        return {
            "method": "mann_lenschow",
            "status": "insufficient_data",
            "random_error": None,
            "relative_error": None,
            "confidence_level": band["confidence_level"],
            "uncertainty_band_half_width": band["uncertainty_band_half_width"],
            "interval_lower": band["interval_lower"],
            "interval_upper": band["interval_upper"],
            "components": {},
            "limitations": ["Insufficient data or negligible flux"],
            "provenance": "Mann & Lenschow 1994",
            "provenance_detail": {
                "reference": "Mann & Lenschow 1994",
                "inputs": {
                    "n_samples": int(n_samples),
                    "averaging_period_s": float(averaging_period_s),
                },
            },
        }
    if integral_timescale_s is None:
        integral_timescale_s = averaging_period_s / 20.0
    T = averaging_period_s
    Ti = integral_timescale_s
    n_eff = max(1.0, T / (2.0 * Ti))
    var_cov = (var_w * var_scalar + cov_w_scalar ** 2) / n_eff
    random_error = math.sqrt(max(0.0, var_cov))
    relative_error = random_error / max(abs(cov_w_scalar), 1e-15)
    band = build_uncertainty_band(
        estimate=cov_w_scalar,
        random_error=random_error,
        relative_uncertainty=relative_error,
        confidence_level=_DEFAULT_UNCERTAINTY_CONFIDENCE_LEVEL,
    )
    return {
        "method": "mann_lenschow",
        "status": "ok",
        "random_error": round(random_error, 6),
        "relative_error": round(relative_error, 4),
        "confidence_level": band["confidence_level"],
        "uncertainty_band_half_width": band["uncertainty_band_half_width"],
        "interval_lower": band["interval_lower"],
        "interval_upper": band["interval_upper"],
        "components": {
            "n_effective": round(n_eff, 1),
            "integral_timescale_s": round(Ti, 2),
            "var_w": round(var_w, 6),
            "var_scalar": round(var_scalar, 6),
            "var_cov": round(var_cov, 6),
        },
        "limitations": [
            "Assumes stationary and homogeneous turbulence",
            "Integral timescale estimated empirically if not provided",
            "Does not account for systematic errors",
        ],
        "provenance": "Mann & Lenschow 1994, one-point variance of covariance",
        "provenance_detail": {
            "reference": "Mann & Lenschow 1994",
            "inputs": {
                "cov_w_scalar": round(cov_w_scalar, 6),
                "var_w": round(var_w, 6),
                "var_scalar": round(var_scalar, 6),
                "n_samples": int(n_samples),
                "averaging_period_s": round(averaging_period_s, 3),
                "integral_timescale_s": round(Ti, 3),
            },
        },
    }


def compute_uncertainty_finkelstein_sims(
    *,
    w_series: np.ndarray,
    scalar_series: np.ndarray,
    sample_rate_hz: float,
    averaging_period_s: float,
) -> dict[str, Any]:
    n = len(w_series)
    if n < 100:
        band = build_uncertainty_band(estimate=0.0, random_error=None)
        return {
            "method": "finkelstein_sims",
            "status": "insufficient_data",
            "random_error": None,
            "relative_error": None,
            "confidence_level": band["confidence_level"],
            "uncertainty_band_half_width": band["uncertainty_band_half_width"],
            "interval_lower": band["interval_lower"],
            "interval_upper": band["interval_upper"],
            "components": {},
            "limitations": ["Insufficient data"],
            "provenance": "Finkelstein & Sims 2001",
            "provenance_detail": {
                "reference": "Finkelstein & Sims 2001",
                "inputs": {
                    "n_samples": int(n),
                    "sample_rate_hz": float(sample_rate_hz),
                    "averaging_period_s": float(averaging_period_s),
                },
            },
        }
    w_detrended = w_series - np.mean(w_series)
    s_detrended = scalar_series - np.mean(scalar_series)
    cov_ws = np.mean(w_detrended * s_detrended)
    max_lag = min(n // 2, int(sample_rate_hz * 60))
    auto_cov_w = np.correlate(w_detrended, w_detrended, mode="full")[n - 1:]
    auto_cov_s = np.correlate(s_detrended, s_detrended, mode="full")[n - 1:]
    cross_cov_ws = np.correlate(w_detrended, s_detrended, mode="full")[n - 1:]
    cross_cov_sw = np.correlate(s_detrended, w_detrended, mode="full")[n - 1:]
    var_cov = 0.0
    for k in range(max_lag):
        if k < len(auto_cov_w) and k < len(auto_cov_s) and k < len(cross_cov_ws) and k < len(cross_cov_sw):
            var_cov += (auto_cov_w[k] * auto_cov_s[k] + cross_cov_ws[k] * cross_cov_sw[k])
    var_cov /= n
    random_error = math.sqrt(max(0.0, var_cov))
    relative_error = random_error / max(abs(cov_ws), 1e-15)
    band = build_uncertainty_band(
        estimate=float(cov_ws),
        random_error=random_error,
        relative_uncertainty=relative_error,
        confidence_level=_DEFAULT_UNCERTAINTY_CONFIDENCE_LEVEL,
    )
    return {
        "method": "finkelstein_sims",
        "status": "ok",
        "random_error": round(random_error, 6),
        "relative_error": round(relative_error, 4),
        "confidence_level": band["confidence_level"],
        "uncertainty_band_half_width": band["uncertainty_band_half_width"],
        "interval_lower": band["interval_lower"],
        "interval_upper": band["interval_upper"],
        "components": {
            "cov_ws": round(cov_ws, 6),
            "var_cov": round(var_cov, 6),
            "max_lag_samples": max_lag,
            "n_samples": n,
        },
        "limitations": [
            "Computationally intensive for long time series",
            "Assumes ergodicity",
            "Does not account for systematic errors",
        ],
        "provenance": "Finkelstein & Sims 2001, variance of covariance via auto/cross-covariance",
        "provenance_detail": {
            "reference": "Finkelstein & Sims 2001",
            "inputs": {
                "sample_rate_hz": round(sample_rate_hz, 3),
                "averaging_period_s": round(averaging_period_s, 3),
                "n_samples": int(n),
            },
        },
    }


def _resample_measured_cospectrum(
    *,
    target_freq: np.ndarray,
    measured_cospectrum_freq: np.ndarray | None,
    measured_cospectrum_value: np.ndarray | None,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    if measured_cospectrum_freq is None or measured_cospectrum_value is None:
        return None, {"uses_measured_cospectrum": False, "measured_frequency_count": 0}
    freq = np.asarray(measured_cospectrum_freq, dtype=float)
    value = np.asarray(measured_cospectrum_value, dtype=float)
    mask = np.isfinite(freq) & np.isfinite(value) & (freq > 0.0)
    if np.count_nonzero(mask) < 8:
        return None, {"uses_measured_cospectrum": False, "measured_frequency_count": int(np.count_nonzero(mask))}
    freq = freq[mask]
    value = np.abs(value[mask])
    order = np.argsort(freq)
    freq = freq[order]
    value = value[order]
    unique_freq, unique_index = np.unique(freq, return_index=True)
    unique_value = value[unique_index]
    if unique_freq.size < 8:
        return None, {"uses_measured_cospectrum": False, "measured_frequency_count": int(unique_freq.size)}
    interpolated = np.interp(target_freq, unique_freq, unique_value, left=unique_value[0], right=unique_value[-1])
    weight_sum = float(np.sum(interpolated))
    if weight_sum <= 1e-12:
        return None, {"uses_measured_cospectrum": False, "measured_frequency_count": int(unique_freq.size)}
    weights = interpolated / weight_sum
    return weights, {"uses_measured_cospectrum": True, "measured_frequency_count": int(unique_freq.size)}


# ---------------------------------------------------------------------------
# Spectral correction family
# ---------------------------------------------------------------------------

def compute_spectral_correction_moncrieff(
    *,
    sensor_sep_m: float,
    response_time_s: float,
    sample_rate_hz: float,
    averaging_period_s: float,
    wind_speed: float,
) -> dict[str, Any]:
    if wind_speed < 0.1 or sample_rate_hz < 1.0 or averaging_period_s <= 0:
        return {
            "method": "moncrieff_97",
            "status": "insufficient_data",
            "correction_factor": 1.0,
            "components": {},
            "provenance": "Moncrieff et al. 1997; EddyPro hf_meth=1 analytical spectral correction",
            "limitations": ["Wind speed, sample rate, or averaging period too low"],
            "provenance_detail": {
                "reference": "Moncrieff et al. 1997",
                "eddypro_project_mapping": {"hf_meth": "1", "lf_meth": "analytic"},
            },
        }
    f_nyquist = sample_rate_hz / 2.0
    n_freq = min(512, max(64, int(sample_rate_hz * 16)))
    freqs = np.geomspace(1.0 / averaging_period_s, f_nyquist, n_freq)
    tau_sep = sensor_sep_m / max(wind_speed, 0.1)
    tau_resp = response_time_s
    tau_block = averaging_period_s / (2.0 * math.pi)
    low_frequency_transfer = 1.0 / (1.0 + (1.0 / np.maximum(freqs * averaging_period_s, 1.0e-9)) ** 2)
    separation_transfer = np.exp(-2.0 * math.pi * freqs * tau_sep * 0.5)
    response_transfer = 1.0 / (1.0 + (2.0 * math.pi * freqs * tau_resp) ** 2)
    cospectral_weight = 1.0 / (1.0 + (freqs * tau_block) ** (5.0 / 3.0))
    cospectral_weight = cospectral_weight / max(float(np.sum(cospectral_weight)), 1.0e-12)
    total_transfer = low_frequency_transfer * separation_transfer * response_transfer
    weighted_transfer = float(np.sum(cospectral_weight * total_transfer))
    correction_factor = 1.0 / max(weighted_transfer, 0.01)
    return {
        "method": "moncrieff_97",
        "status": "ok",
        "correction_factor": round(correction_factor, 4),
        "components": {
            "weighted_transfer": round(weighted_transfer, 4),
            "low_frequency_transfer_mean": round(float(np.mean(low_frequency_transfer)), 4),
            "separation_transfer_mean": round(float(np.mean(separation_transfer)), 4),
            "response_transfer_mean": round(float(np.mean(response_transfer)), 4),
            "tau_sep_s": round(tau_sep, 4),
            "tau_resp_s": round(tau_resp, 4),
            "n_freq": n_freq,
        },
        "provenance": "Moncrieff et al. 1997; analytical high/low-pass transfer function approximation",
        "limitations": [
            "Approximates EddyPro Moncrieff 1997 transfer functions without the full Fortran cospectral stack",
            "Uses a generic cospectral weighting curve when measured cospectra are unavailable",
        ],
        "provenance_detail": {
            "reference": "Moncrieff et al. 1997",
            "eddypro_project_mapping": {"hf_meth": "1", "lf_meth": "analytic"},
            "inputs": {
                "sensor_sep_m": round(sensor_sep_m, 4),
                "response_time_s": round(response_time_s, 4),
                "sample_rate_hz": round(sample_rate_hz, 4),
                "averaging_period_s": round(averaging_period_s, 4),
                "wind_speed": round(wind_speed, 4),
            },
        },
    }


def compute_spectral_correction_massman(
    *,
    path_length_m: float,
    sensor_sep_m: float,
    response_time_s: float,
    sample_rate_hz: float,
    averaging_period_s: float,
    wind_speed: float,
) -> dict[str, Any]:
    if wind_speed < 0.1 or sample_rate_hz < 1.0:
        return {
            "method": "massman",
            "status": "insufficient_data",
            "correction_factor": 1.0,
            "components": {},
            "provenance": "Massman 2000, 2001",
            "limitations": ["Wind speed or sample rate too low"],
            "provenance_detail": {
                "reference": "Massman 2000, 2001",
                "inputs": {
                    "path_length_m": float(path_length_m),
                    "sensor_sep_m": float(sensor_sep_m),
                    "response_time_s": float(response_time_s),
                    "sample_rate_hz": float(sample_rate_hz),
                    "averaging_period_s": float(averaging_period_s),
                    "wind_speed": float(wind_speed),
                },
            },
        }
    f_nyquist = sample_rate_hz / 2.0
    tau_path = path_length_m / max(wind_speed, 0.1)
    tau_sep = sensor_sep_m / max(wind_speed, 0.1)
    tau_resp = response_time_s
    tau_block = averaging_period_s
    H_path = 1.0 / math.sqrt(1.0 + (2.0 * math.pi * f_nyquist * tau_path) ** 2)
    H_sep = 1.0 / math.sqrt(1.0 + (2.0 * math.pi * f_nyquist * tau_sep) ** 2)
    H_resp = 1.0 / math.sqrt(1.0 + (2.0 * math.pi * f_nyquist * tau_resp) ** 2)
    H_block = 1.0 - math.sin(math.pi * 1.0 / (tau_block * sample_rate_hz)) / (math.pi * 1.0 / (tau_block * sample_rate_hz)) if tau_block > 0 else 1.0
    H_total = H_path * H_sep * H_resp * H_block
    correction_factor = 1.0 / max(H_total, 0.01)
    return {
        "method": "massman",
        "status": "ok",
        "correction_factor": round(correction_factor, 4),
        "components": {
            "H_path": round(H_path, 4),
            "H_sep": round(H_sep, 4),
            "H_resp": round(H_resp, 4),
            "H_block": round(H_block, 4),
            "H_total": round(H_total, 4),
            "tau_path_s": round(tau_path, 4),
            "tau_sep_s": round(tau_sep, 4),
            "tau_resp_s": round(tau_resp, 4),
        },
        "provenance": "Massman 2000, 2001; analytical transfer function approach",
        "limitations": [
            "Analytical approximation of transfer functions",
            "Assumes first-order response for sensor and path averaging",
            "Block averaging correction is simplified",
        ],
        "provenance_detail": {
            "reference": "Massman 2000, 2001",
            "inputs": {
                "path_length_m": round(path_length_m, 4),
                "sensor_sep_m": round(sensor_sep_m, 4),
                "response_time_s": round(response_time_s, 4),
                "sample_rate_hz": round(sample_rate_hz, 4),
                "averaging_period_s": round(averaging_period_s, 4),
                "wind_speed": round(wind_speed, 4),
            },
        },
    }


def compute_spectral_correction_horst(
    *,
    path_length_m: float,
    wind_speed: float,
    z_m: float,
    ustar: float,
) -> dict[str, Any]:
    if wind_speed < 0.1 or ustar < 1e-6 or z_m <= 0:
        return {
            "method": "horst",
            "status": "insufficient_data",
            "correction_factor": 1.0,
            "components": {},
            "provenance": "Horst 1997, 2000",
            "limitations": ["Insufficient data"],
            "provenance_detail": {
                "reference": "Horst 1997, 2000",
                "inputs": {
                    "path_length_m": float(path_length_m),
                    "wind_speed": float(wind_speed),
                    "z_m": float(z_m),
                    "ustar": float(ustar),
                },
            },
        }
    f_peak = 0.085 * wind_speed / z_m
    tau_path = path_length_m / max(wind_speed, 0.1)
    H_path = math.exp(-2.0 * math.pi * f_peak * tau_path * 0.5)
    correction_factor = 1.0 / max(H_path, 0.01)
    return {
        "method": "horst",
        "status": "ok",
        "correction_factor": round(correction_factor, 4),
        "components": {
            "f_peak_hz": round(f_peak, 4),
            "H_path": round(H_path, 4),
            "tau_path_s": round(tau_path, 4),
        },
        "provenance": "Horst 1997, 2000; peak frequency approach for path averaging",
        "limitations": [
            "Uses peak frequency approximation",
            "Only accounts for line averaging, not sensor response",
            "Assumes neutral stability for peak frequency",
        ],
        "provenance_detail": {
            "reference": "Horst 1997, 2000",
            "inputs": {
                "path_length_m": round(path_length_m, 4),
                "wind_speed": round(wind_speed, 4),
                "z_m": round(z_m, 4),
                "ustar": round(ustar, 4),
            },
        },
    }


def compute_spectral_correction_ibrom(
    *,
    path_length_m: float,
    sensor_sep_m: float,
    response_time_s: float,
    sample_rate_hz: float,
    wind_speed: float,
    z_m: float,
    ustar: float,
    ol: float | None = None,
) -> dict[str, Any]:
    if wind_speed < 0.1 or ustar < 1e-6 or z_m <= 0:
        return {
            "method": "ibrom",
            "status": "insufficient_data",
            "correction_factor": 1.0,
            "components": {},
            "provenance": "Ibrom et al. 2007",
            "limitations": ["Insufficient data"],
            "provenance_detail": {
                "reference": "Ibrom et al. 2007",
                "inputs": {
                    "path_length_m": float(path_length_m),
                    "sensor_sep_m": float(sensor_sep_m),
                    "response_time_s": float(response_time_s),
                    "sample_rate_hz": float(sample_rate_hz),
                    "wind_speed": float(wind_speed),
                    "z_m": float(z_m),
                    "ustar": float(ustar),
                    "ol": None if ol is None else float(ol),
                },
            },
        }
    f_nyquist = sample_rate_hz / 2.0
    n_freq = min(256, max(32, int(f_nyquist)))
    freqs = np.linspace(1e-4, f_nyquist, n_freq)
    tau_path = path_length_m / max(wind_speed, 0.1)
    H_path = np.sinc(freqs * tau_path) ** 2
    tau_sep = sensor_sep_m / max(wind_speed, 0.1)
    H_sep = np.exp(-2.0 * np.pi * freqs * tau_sep * 0.5)
    H_resp = 1.0 / (1.0 + (2.0 * np.pi * freqs * response_time_s) ** 2)
    H_total = H_path * H_sep * H_resp
    H_mean = float(np.mean(H_total))
    correction_factor = 1.0 / max(H_mean, 0.01)
    return {
        "method": "ibrom",
        "status": "ok",
        "correction_factor": round(correction_factor, 4),
        "components": {
            "H_path_mean": round(float(np.mean(H_path)), 4),
            "H_sep_mean": round(float(np.mean(H_sep)), 4),
            "H_resp_mean": round(float(np.mean(H_resp)), 4),
            "H_total_mean": round(H_mean, 4),
            "n_freq": n_freq,
        },
        "provenance": "Ibrom et al. 2007; spectral integration approach",
        "limitations": [
            "Spectral integration uses simplified co-spectral model",
            "Assumes isotropic turbulence for crosswind separation",
            "No stability-dependent co-spectral correction in this version",
        ],
        "provenance_detail": {
            "reference": "Ibrom et al. 2007",
            "inputs": {
                "path_length_m": round(path_length_m, 4),
                "sensor_sep_m": round(sensor_sep_m, 4),
                "response_time_s": round(response_time_s, 4),
                "sample_rate_hz": round(sample_rate_hz, 4),
                "wind_speed": round(wind_speed, 4),
                "z_m": round(z_m, 4),
                "ustar": round(ustar, 4),
                "ol": None if ol is None else round(ol, 4),
            },
        },
    }


def compute_spectral_correction_fratini(
    *,
    path_length_m: float,
    sensor_sep_m: float,
    response_time_s: float,
    sample_rate_hz: float,
    wind_speed: float,
    z_m: float,
    ustar: float,
    ol: float | None = None,
    measured_cospectrum_freq: np.ndarray | None = None,
    measured_cospectrum_value: np.ndarray | None = None,
) -> dict[str, Any]:
    if wind_speed < 0.1 or ustar < 1e-6 or z_m <= 0:
        return {
            "method": "fratini",
            "status": "insufficient_data",
            "correction_factor": 1.0,
            "components": {},
            "provenance": "Fratini et al. 2012",
            "limitations": ["Insufficient data"],
            "provenance_detail": {
                "reference": "Fratini et al. 2012",
                "inputs": {
                    "path_length_m": float(path_length_m),
                    "sensor_sep_m": float(sensor_sep_m),
                    "response_time_s": float(response_time_s),
                    "sample_rate_hz": float(sample_rate_hz),
                    "wind_speed": float(wind_speed),
                    "z_m": float(z_m),
                    "ustar": float(ustar),
                    "ol": None if ol is None else float(ol),
                },
            },
        }
    f_nyquist = sample_rate_hz / 2.0
    n_freq = min(256, max(32, int(f_nyquist)))
    freqs = np.linspace(1e-4, f_nyquist, n_freq)
    tau_path = path_length_m / max(wind_speed, 0.1)
    H_path = np.sinc(freqs * tau_path) ** 2
    tau_sep = sensor_sep_m / max(wind_speed, 0.1)
    H_sep = np.exp(-2.0 * np.pi * freqs * tau_sep * 0.5)
    H_resp = 1.0 / (1.0 + (2.0 * np.pi * freqs * response_time_s) ** 2)
    H_total = H_path * H_sep * H_resp
    measured_weights, measured_info = _resample_measured_cospectrum(
        target_freq=freqs,
        measured_cospectrum_freq=measured_cospectrum_freq,
        measured_cospectrum_value=measured_cospectrum_value,
    )
    if measured_weights is not None:
        weighted_transfer = float(np.sum(measured_weights * H_total))
        correction_factor = 1.0 / max(weighted_transfer, 0.01)
    else:
        H_mean = float(np.mean(H_total))
        weighted_transfer = H_mean
        correction_factor = 1.0 / max(H_mean, 0.01)
    return {
        "method": "fratini",
        "status": "ok",
        "correction_factor": round(correction_factor, 4),
        "components": {
            "H_path_mean": round(float(np.mean(H_path)), 4),
            "H_sep_mean": round(float(np.mean(H_sep)), 4),
            "H_resp_mean": round(float(np.mean(H_resp)), 4),
            "H_total_mean": round(float(np.mean(H_total)), 4),
            "n_freq": n_freq,
            "uses_measured_cospectrum": measured_info["uses_measured_cospectrum"],
            "measured_frequency_count": measured_info["measured_frequency_count"],
            "weighted_transfer": round(weighted_transfer, 4),
        },
        "provenance": "Fratini et al. 2012; in-situ co-spectral correction method",
        "limitations": [
            "Without measured cospectrum, falls back to simplified model",
            "Assumes well-defined inertial subrange",
            "Sensitivity to cospectral model choice",
        ],
        "provenance_detail": {
            "reference": "Fratini et al. 2012",
            "inputs": {
                "path_length_m": round(path_length_m, 4),
                "sensor_sep_m": round(sensor_sep_m, 4),
                "response_time_s": round(response_time_s, 4),
                "sample_rate_hz": round(sample_rate_hz, 4),
                "wind_speed": round(wind_speed, 4),
                "z_m": round(z_m, 4),
                "ustar": round(ustar, 4),
                "ol": None if ol is None else round(ol, 4),
            },
            "measured_cospectrum_used": measured_info["uses_measured_cospectrum"],
        },
    }


def compute_spectral_correction(
    *,
    method: str = "massman",
    path_length_m: float = 0.15,
    sensor_sep_m: float = 0.20,
    response_time_s: float = 0.1,
    sample_rate_hz: float = 10.0,
    averaging_period_s: float = 1800.0,
    wind_speed: float = 0.0,
    z_m: float = 0.0,
    ustar: float = 0.0,
    ol: float | None = None,
    measured_cospectrum_freq: np.ndarray | None = None,
    measured_cospectrum_value: np.ndarray | None = None,
) -> dict[str, Any]:
    method = str(method or "massman").strip().lower()
    if method in {"moncrieff", "moncrieff_97", "moncrieff97"}:
        return compute_spectral_correction_moncrieff(
            sensor_sep_m=sensor_sep_m, response_time_s=response_time_s,
            sample_rate_hz=sample_rate_hz, averaging_period_s=averaging_period_s,
            wind_speed=wind_speed,
        )
    if method == "horst":
        return compute_spectral_correction_horst(
            path_length_m=path_length_m, wind_speed=wind_speed, z_m=z_m, ustar=ustar,
        )
    if method == "ibrom":
        return compute_spectral_correction_ibrom(
            path_length_m=path_length_m, sensor_sep_m=sensor_sep_m,
            response_time_s=response_time_s, sample_rate_hz=sample_rate_hz,
            wind_speed=wind_speed, z_m=z_m, ustar=ustar, ol=ol,
        )
    if method == "fratini":
        return compute_spectral_correction_fratini(
            path_length_m=path_length_m, sensor_sep_m=sensor_sep_m,
            response_time_s=response_time_s, sample_rate_hz=sample_rate_hz,
            wind_speed=wind_speed, z_m=z_m, ustar=ustar, ol=ol,
            measured_cospectrum_freq=measured_cospectrum_freq,
            measured_cospectrum_value=measured_cospectrum_value,
        )
    return compute_spectral_correction_massman(
        path_length_m=path_length_m, sensor_sep_m=sensor_sep_m,
        response_time_s=response_time_s, sample_rate_hz=sample_rate_hz,
        averaging_period_s=averaging_period_s, wind_speed=wind_speed,
    )


def run_method_compare(
    *,
    method_family: str,
    selected_method: str = "",
    window_params: dict[str, Any],
    methods_to_run: list[str] | tuple[str, ...] | None = None,
    method_configs: dict[str, dict[str, Any]] | None = None,
) -> MethodCompareResult:
    """Run one method family side-by-side for a single RP window."""
    family = str(method_family or "").strip()
    defaults = {
        "footprint": ["kljun", "kormann_meixner", "hsieh"],
        "uncertainty": ["mann_lenschow", "finkelstein_sims"],
        "spectral_correction": ["moncrieff_97", "massman", "horst", "ibrom", "fratini"],
    }
    methods = list(dict.fromkeys(str(item).strip() for item in (methods_to_run or defaults.get(family, [])) if str(item).strip()))
    selected = str(selected_method or window_params.get("selected_method", "") or "").strip()
    configs = method_configs or {}
    outputs: dict[str, float] = {}
    details: dict[str, Any] = {}
    primary_metric = ""

    for method_name in methods:
        cfg = dict(configs.get(method_name, {}) or {})
        try:
            if family == "footprint":
                primary_metric = "peak_distance_m"
                fp = compute_footprint(
                    method=method_name,
                    ustar=float(window_params.get("ustar", 0.0) or 0.0),
                    mean_wind_speed=float(window_params.get("mean_wind_speed", 0.0) or 0.0),
                    sigma_v=float(window_params.get("sigma_v", 0.0) or 0.0),
                    z_m=float(cfg.get("z_m", window_params.get("z_m", 0.0)) or 0.0),
                    h=float(cfg.get("canopy_height_m", cfg.get("h", window_params.get("h", 0.0))) or 0.0),
                    z0=cfg.get("z0", window_params.get("z0")),
                    ol=cfg.get("ol", window_params.get("ol")),
                )
                details[method_name] = {
                    "status": fp.detail.get("status", ""),
                    "peak_distance_m": fp.peak_distance_m,
                    "offset_distance_m": fp.offset_distance_m,
                    "contribution_distances": dict(fp.contribution_distances),
                    "provenance": fp.detail.get("provenance", ""),
                    "limitations": fp.detail.get("limitations", []),
                }
                if fp.peak_distance_m > 0.0:
                    outputs[method_name] = float(fp.peak_distance_m)
            elif family == "uncertainty":
                primary_metric = "random_error"
                if method_name == "mann_lenschow":
                    result = compute_uncertainty_mann_lenschow(
                        cov_w_scalar=float(window_params.get("cov_w_scalar", 0.0) or 0.0),
                        var_w=float(window_params.get("var_w", 0.0) or 0.0),
                        var_scalar=float(window_params.get("var_scalar", 0.0) or 0.0),
                        n_samples=int(window_params.get("n_samples", 0) or 0),
                        averaging_period_s=float(window_params.get("averaging_period_s", 0.0) or 0.0),
                        integral_timescale_s=cfg.get("integral_timescale_s", window_params.get("integral_timescale_s")),
                    )
                elif method_name == "finkelstein_sims":
                    w_series = np.asarray(window_params.get("w_series", []), dtype=float)
                    scalar_series = np.asarray(window_params.get("scalar_series", []), dtype=float)
                    compare_sample_rate_hz = float(window_params.get("sample_rate_hz", 0.0) or 0.0)
                    max_compare_samples = int(window_params.get("max_compare_samples", 4096) or 4096)
                    downsample_stride = 1
                    if w_series.size > max_compare_samples > 0:
                        downsample_stride = int(math.ceil(w_series.size / max_compare_samples))
                        w_series = w_series[::downsample_stride]
                        scalar_series = scalar_series[::downsample_stride]
                        compare_sample_rate_hz = compare_sample_rate_hz / downsample_stride if compare_sample_rate_hz > 0 else compare_sample_rate_hz
                    result = compute_uncertainty_finkelstein_sims(
                        w_series=w_series,
                        scalar_series=scalar_series,
                        sample_rate_hz=compare_sample_rate_hz,
                        averaging_period_s=float(window_params.get("averaging_period_s", 0.0) or 0.0),
                    )
                    if downsample_stride > 1:
                        result = dict(result)
                        result.setdefault("components", {})
                        if isinstance(result["components"], dict):
                            result["components"]["method_compare_downsample_stride"] = downsample_stride
                            result["components"]["method_compare_sample_count"] = int(w_series.size)
                        result.setdefault("limitations", [])
                        if isinstance(result["limitations"], list):
                            result["limitations"].append(
                                "Method compare downsampled Finkelstein-Sims input to bound cockpit rerun latency"
                            )
                else:
                    result = {"method": method_name, "status": "unsupported_method", "random_error": None}
                details[method_name] = result
                value = result.get("random_error")
                if isinstance(value, (int, float)) and np.isfinite(float(value)):
                    outputs[method_name] = float(value)
            elif family == "spectral_correction":
                primary_metric = "correction_factor"
                result = compute_spectral_correction(
                    method=method_name,
                    path_length_m=float(cfg.get("path_length_m", window_params.get("path_length_m", 0.15)) or 0.15),
                    sensor_sep_m=float(cfg.get("sensor_sep_m", window_params.get("sensor_sep_m", 0.20)) or 0.20),
                    response_time_s=float(cfg.get("response_time_s", window_params.get("response_time_s", 0.1)) or 0.1),
                    sample_rate_hz=float(window_params.get("sample_rate_hz", 10.0) or 10.0),
                    averaging_period_s=float(window_params.get("averaging_period_s", 1800.0) or 1800.0),
                    wind_speed=float(window_params.get("wind_speed", 0.0) or 0.0),
                    z_m=float(cfg.get("z_m", window_params.get("z_m", 0.0)) or 0.0),
                    ustar=float(window_params.get("ustar", 0.0) or 0.0),
                    ol=cfg.get("ol", window_params.get("ol")),
                    measured_cospectrum_freq=window_params.get("measured_cospectrum_freq") if method_name == "fratini" else None,
                    measured_cospectrum_value=window_params.get("measured_cospectrum_value") if method_name == "fratini" else None,
                )
                details[method_name] = result
                value = result.get("correction_factor")
                if isinstance(value, (int, float)) and np.isfinite(float(value)):
                    outputs[method_name] = float(value)
        except Exception as exc:  # pragma: no cover - defensive method-family comparison
            details[method_name] = {"status": "error", "error": str(exc)}

    if not outputs:
        return MethodCompareResult(
            method_family=family,
            selected_method=selected,
            methods_run=methods,
            primary_metric=primary_metric,
            primary_outputs={},
            consensus_value=None,
            deviations={},
            recommendation=selected or (methods[0] if methods else ""),
            recommendation_reason="No comparable method outputs were available for this window.",
            status="insufficient_data",
            detail={"methods": details, "provenance": "side-by-side method comparison"},
        )

    values = list(outputs.values())
    consensus = float(np.median(values))
    denominator = max(abs(consensus), 1e-12)
    deviations = {
        method_name: round(float((value - consensus) / denominator), 6)
        for method_name, value in outputs.items()
    }
    if selected in outputs:
        selected_abs_dev = abs(deviations[selected])
        recommendation = selected
        if selected_abs_dev > 0.25:
            recommendation = min(outputs, key=lambda name: abs(deviations[name]))
            reason = (
                f"Selected method deviates {selected_abs_dev:.1%} from family median; "
                f"{recommendation} is closest to consensus."
            )
        else:
            reason = "Selected method is within 25% of the family median."
    else:
        recommendation = min(outputs, key=lambda name: abs(deviations[name]))
        reason = "Selected method did not produce a comparable output; closest-to-consensus method is recommended."

    return MethodCompareResult(
        method_family=family,
        selected_method=selected,
        methods_run=methods,
        primary_metric=primary_metric,
        primary_outputs={key: round(float(value), 6) for key, value in outputs.items()},
        consensus_value=round(consensus, 6),
        deviations=deviations,
        recommendation=recommendation,
        recommendation_reason=reason,
        status="ok",
        detail={
            "methods": details,
            "deviation_threshold": 0.25,
            "provenance": "side-by-side method-family comparison using identical RP window inputs",
            "limitations": [
                "Consensus is a median of available method outputs, not an external truth value",
                "Method compare is diagnostic and does not automatically alter selected processing outputs",
            ],
        },
    )
