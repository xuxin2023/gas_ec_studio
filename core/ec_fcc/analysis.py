from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
from typing import Any, Iterable

import numpy as np
try:
    from scipy import signal  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    signal = None

from models.hf_models import NormalizedHFFrame
from models.spectral_models import SpectralRunResult, WindowSpectralResult


SPECTRAL_LIBRARY_SERIES = [
    ("power_measured", "power_freq", "power_measured"),
    ("power_reference", "power_freq", "power_ref"),
    ("cospectrum", "cross_freq", "cross_value"),
    ("ogive", "ogive_freq", "ogive_value"),
    ("transfer_observed", "transfer_freq", "transfer_value"),
    ("total_transfer_model", "total_transfer_function_freq", "total_transfer_function_value"),
]


@dataclass(slots=True)
class LagAnalysisResult:
    lag_seconds: float
    confidence: float
    lag_curve_x: list[float]
    lag_curve_y: list[float]
    co2_lag_seconds: float
    h2o_lag_seconds: float


@dataclass(slots=True)
class TransferFunctionProvenance:
    transfer_function_components: dict[str, Any] = field(default_factory=dict)
    correction_factor_components: dict[str, float] = field(default_factory=dict)
    total_transfer_function_freq: list[float] = field(default_factory=list)
    total_transfer_function_value: list[float] = field(default_factory=list)
    effective_cutoff_info: dict[str, Any] = field(default_factory=dict)
    correction_factor_detail: dict[str, Any] = field(default_factory=dict)
    provenance_notes: list[str] = field(default_factory=list)
    model_version: str = "fcc_transfer_components_v1"


def build_spectral_assessment_library(
    spectral_runs: Iterable[SpectralRunResult],
    *,
    dataset_id: str = "",
    target_bins: int = 24,
    group_by: Iterable[str] | None = None,
    min_windows_per_group: int = 1,
) -> dict[str, Any]:
    """Build a reusable long-period spectra/cospectra assessment library.

    This is an EddyPro-style spectral assessment library artifact, not an
    official EddyPro numerical parity claim. Original per-window spectral arrays
    remain in the run results; this artifact provides stratified ensembles.
    """

    runs = list(spectral_runs or [])
    grouping = [str(item) for item in (group_by or ("month", "qc_grade", "high_freq_loss_risk")) if str(item)]
    min_windows = max(1, int(min_windows_per_group))
    records = [
        record
        for run in runs
        for window in list(run.windows or [])
        for record in [_spectral_library_window_record(run, window)]
        if record["has_spectral_values"]
    ]
    all_freqs = [
        freq
        for record in records
        for pairs in dict(record.get("series", {}) or {}).values()
        for freq, _value in list(pairs or [])
        if freq > 0.0
    ]
    edges = _spectral_library_log_edges(all_freqs, target_bins=max(1, int(target_bins)))
    group_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        group_members["all"].append(record)
        for group_id, _label in _spectral_library_group_keys(record, grouping):
            group_members[group_id].append(record)

    groups = [
        _spectral_library_group_payload(
            group_id=group_id,
            records=members,
            edges=edges,
            min_windows=min_windows,
        )
        for group_id, members in sorted(group_members.items(), key=lambda item: item[0])
    ]
    status = "ok" if records and any(group.get("status") == "ok" for group in groups) else ("empty" if not records else "needs_more_windows")
    period_starts = [record["start_time"] for record in records]
    period_ends = [record["end_time"] for record in records]
    model_versions = sorted({str(record.get("model_version", "")) for record in records if str(record.get("model_version", ""))})
    run_ids = sorted({str(record.get("run_id", "")) for record in records if str(record.get("run_id", ""))})
    return {
        "artifact_type": "spectral_assessment_library_v1",
        "library_id": dataset_id or _spectral_library_id(run_ids, period_starts, period_ends),
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "run_count": len(run_ids),
        "source_run_ids": run_ids,
        "window_count": len(records),
        "group_count": len(groups),
        "group_by": grouping,
        "target_bin_count": max(1, int(target_bins)),
        "actual_bin_count": len(edges),
        "min_windows_per_group": min_windows,
        "period": {
            "start": min(period_starts).isoformat() if period_starts else "",
            "end": max(period_ends).isoformat() if period_ends else "",
        },
        "value_families": [item[0] for item in SPECTRAL_LIBRARY_SERIES],
        "summary": {
            "qc_grade_counts": dict(sorted(Counter(str(record.get("qc_grade", "")) for record in records).items())),
            "risk_counts": dict(sorted(Counter(str(record.get("high_freq_loss_risk", "")) for record in records).items())),
            "mean_correction_factor": _spectral_mean_or_zero([float(record.get("correction_factor", 0.0)) for record in records]),
            "mean_lag_seconds": _spectral_mean_or_zero([float(record.get("lag_seconds", 0.0)) for record in records]),
            "model_versions": model_versions,
        },
        "groups": groups,
        "provenance": {
            "source": "SpectralRunResult WindowSpectralResult spectral arrays",
            "ensemble_method": "log-frequency interpolation followed by arithmetic mean and sample standard deviation",
            "stratification": grouping,
            "model_versions": model_versions,
        },
        "known_limitations": [
            "This library is generated from available gas_ec_studio FCC run results and does not replace official EddyPro spectral golden-output validation.",
            "Groups with fewer than min_windows_per_group windows are retained but marked needs_more_windows.",
            "Frequency bins are log-spaced and interpolated for ensemble comparability; original per-window arrays remain the source of truth.",
        ],
    }


def _spectral_library_window_record(run: SpectralRunResult, window: WindowSpectralResult) -> dict[str, Any]:
    series: dict[str, list[tuple[float, float]]] = {}
    for series_name, freq_attr, value_attr in SPECTRAL_LIBRARY_SERIES:
        series[series_name] = _spectral_pairs(getattr(window, freq_attr, []), getattr(window, value_attr, []))
    return {
        "run_id": run.run_id,
        "data_source": run.data_source,
        "time_range": run.time_range,
        "window_id": window.window_id,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "month": window.start_time.strftime("%Y-%m"),
        "qc_grade": str(window.qc_grade),
        "high_freq_loss_risk": str(window.high_freq_loss_risk),
        "model_version": str(window.model_version),
        "correction_factor": float(window.correction_factor),
        "lag_seconds": float(window.lag_seconds),
        "lag_confidence": float(window.lag_confidence),
        "flux_sign": "positive" if float(window.corrected_flux_after) >= 0.0 else "negative",
        "series": series,
        "has_spectral_values": any(bool(pairs) for pairs in series.values()),
    }


def _spectral_library_group_keys(record: dict[str, Any], group_by: list[str]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for field_name in group_by:
        raw_value = record.get(field_name, "")
        value = str(raw_value).strip() or "unknown"
        safe_value = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
        keys.append((f"{field_name}:{safe_value}", f"{field_name}={value}"))
    return keys


def _spectral_library_group_payload(
    *,
    group_id: str,
    records: list[dict[str, Any]],
    edges: list[tuple[float, float, float]],
    min_windows: int,
) -> dict[str, Any]:
    rows = _spectral_library_binned_rows(records, edges)
    run_ids = sorted({str(record.get("run_id", "")) for record in records if str(record.get("run_id", ""))})
    window_ids = [str(record.get("window_id", "")) for record in records if str(record.get("window_id", ""))]
    period_starts = [record["start_time"] for record in records]
    period_ends = [record["end_time"] for record in records]
    status = "ok" if len(records) >= min_windows and rows else "needs_more_windows"
    if not records or not rows:
        status = "empty"
    return {
        "group_id": group_id,
        "group_label": "all_windows" if group_id == "all" else group_id,
        "status": status,
        "run_count": len(run_ids),
        "window_count": len(records),
        "source_run_ids": run_ids,
        "source_window_ids": window_ids,
        "period_start": min(period_starts).isoformat() if period_starts else "",
        "period_end": max(period_ends).isoformat() if period_ends else "",
        "qc_grade_counts": dict(sorted(Counter(str(record.get("qc_grade", "")) for record in records).items())),
        "risk_counts": dict(sorted(Counter(str(record.get("high_freq_loss_risk", "")) for record in records).items())),
        "mean_correction_factor": _spectral_mean_or_zero([float(record.get("correction_factor", 0.0)) for record in records]),
        "mean_lag_seconds": _spectral_mean_or_zero([float(record.get("lag_seconds", 0.0)) for record in records]),
        "binned_ensemble": {
            "binning": "log_frequency",
            "bin_count": len(rows),
            "rows": rows,
        },
    }


def _spectral_library_binned_rows(
    records: list[dict[str, Any]],
    edges: list[tuple[float, float, float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (freq_min, freq_max, center) in enumerate(edges, start=1):
        row: dict[str, Any] = {
            "bin_index": index,
            "freq_min_hz": float(freq_min),
            "freq_max_hz": float(freq_max),
            "freq_center_hz": float(center),
        }
        for series_name, _freq_attr, _value_attr in SPECTRAL_LIBRARY_SERIES:
            values: list[float] = []
            for record in records:
                pairs = list(dict(record.get("series", {}) or {}).get(series_name, []) or [])
                interpolated = _spectral_interpolate(pairs, center)
                if interpolated is not None:
                    values.append(interpolated)
            row[f"{series_name}_mean"] = _spectral_mean_or_blank(values)
            row[f"{series_name}_std"] = _spectral_std_or_blank(values)
            row[f"{series_name}_window_count"] = len(values)
        rows.append(row)
    return rows


def _spectral_pairs(freqs: Any, values: Any) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for raw_freq, raw_value in zip(list(freqs or []), list(values or []), strict=False):
        try:
            freq = float(raw_freq)
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(freq) and math.isfinite(value):
            pairs.append((freq, value))
    pairs.sort(key=lambda item: item[0])
    return pairs


def _spectral_library_log_edges(freqs: list[float], *, target_bins: int) -> list[tuple[float, float, float]]:
    positive = [float(freq) for freq in freqs if freq > 0.0 and math.isfinite(float(freq))]
    if not positive:
        return []
    low = max(min(positive), 1e-9)
    high = max(max(positive), low * 1.001)
    bin_count = max(1, min(int(target_bins), len(set(round(freq, 12) for freq in positive))))
    log_low = math.log10(low)
    log_high = math.log10(high)
    raw_edges = [10.0 ** (log_low + (log_high - log_low) * index / bin_count) for index in range(bin_count + 1)]
    return [
        (
            float(raw_edges[index]),
            float(raw_edges[index + 1]),
            float(math.sqrt(max(raw_edges[index], 1e-12) * max(raw_edges[index + 1], 1e-12))),
        )
        for index in range(bin_count)
    ]


def _spectral_interpolate(pairs: list[tuple[float, float]], x_value: float) -> float | None:
    if not pairs or x_value < pairs[0][0] or x_value > pairs[-1][0]:
        return None
    if len(pairs) == 1:
        return float(pairs[0][1]) if abs(float(pairs[0][0]) - x_value) <= 1e-12 else None
    for (x0, y0), (x1, y1) in zip(pairs[:-1], pairs[1:], strict=False):
        if x0 == x1:
            continue
        if x0 <= x_value <= x1:
            weight = (x_value - x0) / (x1 - x0)
            return float(y0 + (y1 - y0) * weight)
    return None


def _spectral_mean_or_blank(values: list[float]) -> float | str:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return float(sum(clean) / len(clean)) if clean else ""


def _spectral_std_or_blank(values: list[float]) -> float | str:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 2:
        return ""
    mean = sum(clean) / len(clean)
    return float(math.sqrt(sum((value - mean) ** 2 for value in clean) / (len(clean) - 1)))


def _spectral_mean_or_zero(values: list[float]) -> float:
    mean = _spectral_mean_or_blank(values)
    return float(mean) if mean != "" else 0.0


def _spectral_library_id(run_ids: list[str], starts: list[datetime], ends: list[datetime]) -> str:
    if not run_ids:
        return "spectral_library_empty"
    start = min(starts).strftime("%Y%m%d%H%M%S") if starts else "unknown"
    end = max(ends).strftime("%Y%m%d%H%M%S") if ends else "unknown"
    return f"spectral_library_{start}_{end}_{len(run_ids)}runs"


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
    if total_samples < target_samples * 2 and total_samples >= min_samples * 3:
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


def series_from_rows(rows: list[NormalizedHFFrame]) -> dict[str, Any]:
    def _extract(name: str) -> np.ndarray:
        values = [getattr(row, name) for row in rows]
        data = np.array([np.nan if value is None else float(value) for value in values], dtype=float)
        return _fill_missing(data)

    vertical_velocity, has_vertical_velocity = _extract_vertical_velocity(rows)
    horizontal = _extract_horizontal_wind(rows)
    return {
        "co2": _extract("co2_ppm"),
        "h2o": _extract("h2o_mmol"),
        "pressure": _extract("pressure_kpa"),
        "chamber_temp": _extract("chamber_temp_c"),
        "case_temp": _extract("case_temp_c"),
        "vertical_velocity": vertical_velocity,
        "has_vertical_velocity": has_vertical_velocity,
        "u": horizontal["u"],
        "v": horizontal["v"],
        "horizontal_speed": horizontal["horizontal_speed"],
        "horizontal_speed_valid": bool(horizontal["horizontal_speed_valid"]),
    }


def build_velocity_proxy(series: dict[str, Any], expected_lag_samples: int) -> np.ndarray:
    if bool(series.get("has_vertical_velocity")):
        observed = _standardize(_detrend(np.asarray(series["vertical_velocity"], dtype=float)))
        if float(np.std(observed)) > 1e-6:
            return observed

    pressure = _standardize(np.gradient(_detrend(np.asarray(series["pressure"], dtype=float))))
    thermal = _standardize(
        np.gradient(
            _detrend(np.asarray(series["chamber_temp"], dtype=float) - np.asarray(series["case_temp"], dtype=float))
        )
    )
    humidity = _standardize(np.gradient(_detrend(np.asarray(series["h2o"], dtype=float))))
    lag_samples = max(1, int(expected_lag_samples))
    proxy = 0.50 * pressure + 0.30 * thermal + 0.20 * _shift_right(humidity, max(1, lag_samples // 3))
    if float(np.std(proxy)) <= 1e-6:
        proxy = np.gradient(_detrend(np.asarray(series["co2"], dtype=float)))
    return _standardize(proxy)


def analyze_lag(
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
        lag_seconds=lag_seconds,
        confidence=confidence,
        lag_curve_x=[float(lag / sample_rate_hz) for lag in lags],
        lag_curve_y=[float(value) for value in blend_curve],
        co2_lag_seconds=float(lags[co2_peak] / sample_rate_hz),
        h2o_lag_seconds=float(lags[h2o_peak] / sample_rate_hz),
    )


def power_spectrum(series: np.ndarray, sample_rate_hz: float) -> tuple[list[float], list[float], list[float]]:
    nperseg = min(len(series), 256)
    if nperseg < 16:
        return [], [], []
    freq, measured = _welch_density(_detrend(series), fs=sample_rate_hz, nperseg=nperseg)
    if freq.size <= 1:
        return [], [], []
    anchor = max(float(measured[1]), 1e-6)
    reference = anchor / np.power(1.0 + (freq / max(freq[1], 0.1)), 5.0 / 3.0)
    return freq.tolist(), reference.tolist(), measured.tolist()


def cross_spectrum(vertical_velocity: np.ndarray, scalar_series: np.ndarray, sample_rate_hz: float) -> tuple[list[float], list[float]]:
    nperseg = min(len(vertical_velocity), 256)
    if nperseg < 16:
        return [], []
    freq, values = _csd_density(
        _detrend(vertical_velocity),
        _detrend(scalar_series),
        fs=sample_rate_hz,
        nperseg=nperseg,
    )
    return freq.tolist(), np.real(values).tolist()


def ogive_curve(cross_freq: list[float], cross_value: list[float]) -> tuple[list[float], list[float]]:
    if len(cross_freq) < 2:
        return [], []
    freq = np.array(cross_freq, dtype=float)
    values = np.array(cross_value, dtype=float)
    spacing = np.gradient(freq)
    ogive = np.cumsum(values * spacing)
    scale = max(np.max(np.abs(ogive)), 1e-6)
    return freq.tolist(), (ogive / scale).tolist()


def transfer_function(power_freq: list[float], power_ref: list[float], power_measured: list[float]) -> tuple[list[float], list[float]]:
    if not power_freq:
        return [], []
    ref = np.array(power_ref, dtype=float)
    measured = np.array(power_measured, dtype=float)
    ratio = np.clip(measured / np.maximum(ref, 1e-9), 0.0, 1.0)
    return list(power_freq), ratio.tolist()


def correction_factor(power_freq: list[float], power_ref: list[float], power_measured: list[float]) -> tuple[float, float]:
    if len(power_freq) < 4:
        return 1.0, 0.0
    freq = np.array(power_freq, dtype=float)
    ref = np.array(power_ref, dtype=float)
    measured = np.array(power_measured, dtype=float)
    high_mask = freq >= np.quantile(freq, 0.65)
    if not np.any(high_mask):
        high_mask = freq >= np.median(freq)
    loss = np.clip((ref[high_mask] - measured[high_mask]) / np.maximum(ref[high_mask], 1e-9), 0.0, 1.0)
    loss_ratio = float(loss.mean()) if loss.size else 0.0
    return 1.0 + loss_ratio * 0.45, loss_ratio


def transfer_function_provenance(
    *,
    power_freq: list[float],
    power_ref: list[float],
    power_measured: list[float],
    sample_rate_hz: float,
    config: dict[str, Any],
    series: dict[str, Any],
    lag_seconds: float,
    lag_confidence: float,
    base_factor: float,
    factor_cap: float,
) -> TransferFunctionProvenance:
    transfer_model = str(_config_value(config, "transfer_function.transfer_model", "transfer_function.model") or "component_product")
    correction_mode = str(_config_value(config, "correction_factor.correction_mode", "correction_factor.mode") or "provenance_weighted")
    if not power_freq:
        return TransferFunctionProvenance(
            provenance_notes=[
                "transfer function provenance fell back because spectral frequency bins are unavailable",
                f"transfer_model={transfer_model}",
                f"correction_mode={correction_mode}",
            ],
            correction_factor_components={
                "base_factor": float(min(base_factor, factor_cap)),
                "tube_component": 1.0,
                "separation_component": 1.0,
                "path_component": 1.0,
                "phase_component": 1.0,
                "total_factor": float(min(base_factor, factor_cap)),
            },
            correction_factor_detail={
                "factor_cap": float(factor_cap),
                "factor_before_cap": float(base_factor),
                "factor_cap_applied": bool(base_factor > factor_cap),
                "transfer_model": transfer_model,
                "correction_mode": correction_mode,
            },
            model_version=f"fcc_transfer_components_v1:{transfer_model}:{correction_mode}",
        )

    freq = np.array(power_freq, dtype=float)
    observed_transfer = np.clip(
        np.array(power_measured, dtype=float) / np.maximum(np.array(power_ref, dtype=float), 1e-9),
        0.05,
        1.0,
    )
    notes: list[str] = []
    notes.extend([f"transfer_model={transfer_model}", f"correction_mode={correction_mode}"])

    metadata = _resolve_transfer_metadata(config=config, series=series, lag_seconds=lag_seconds, lag_confidence=lag_confidence)
    notes.extend(metadata["notes"])

    tube_curve, tube_cutoff = _tube_attenuation(freq, metadata)
    separation_curve, separation_cutoff = _sensor_separation(freq, metadata)
    path_curve, path_cutoff = _path_averaging(freq, metadata)
    phase_curve, phase_cutoff = _phase_attenuation(freq, metadata)
    low_pass_total = np.clip(tube_curve * separation_curve * path_curve * phase_curve, 0.05, 1.0)

    capped_factor = float(min(base_factor, factor_cap))
    correction_components, factor_detail = _correction_factor_components(
        freq=freq,
        observed_transfer=observed_transfer,
        component_curves={
            "tube_component": tube_curve,
            "separation_component": separation_curve,
            "path_component": path_curve,
            "phase_component": phase_curve,
        },
        base_factor=capped_factor,
        factor_before_cap=float(base_factor),
        factor_cap=float(factor_cap),
    )
    factor_detail["transfer_model"] = transfer_model
    factor_detail["correction_mode"] = correction_mode

    transfer_components = {
        "tube_attenuation": _component_payload(freq, tube_curve, tube_cutoff, tube_cutoff is not None, metadata["tube_source"]),
        "sensor_separation": _component_payload(
            freq,
            separation_curve,
            separation_cutoff,
            separation_cutoff is not None,
            metadata["separation_source"],
        ),
        "path_averaging": _component_payload(freq, path_curve, path_cutoff, path_cutoff is not None, metadata["path_source"]),
        "phase_term": _component_payload(freq, phase_curve, phase_cutoff, True, metadata["phase_source"]),
        "low_pass_total": _component_payload(freq, low_pass_total, _effective_cutoff(freq, low_pass_total), True, "product of enabled component terms"),
    }

    return TransferFunctionProvenance(
        transfer_function_components=transfer_components,
        correction_factor_components=correction_components,
        total_transfer_function_freq=freq.tolist(),
        total_transfer_function_value=low_pass_total.tolist(),
        effective_cutoff_info={
            "tube_cutoff_hz": tube_cutoff,
            "separation_cutoff_hz": separation_cutoff,
            "path_cutoff_hz": path_cutoff,
            "phase_cutoff_hz": phase_cutoff,
            "effective_total_cutoff_hz": _effective_cutoff(freq, low_pass_total),
        },
        correction_factor_detail=factor_detail,
        provenance_notes=notes,
        model_version=f"fcc_transfer_components_v1:{transfer_model}:{correction_mode}",
    )


def flux_estimate(vertical_velocity: np.ndarray, scalar_series: np.ndarray) -> float:
    if len(vertical_velocity) == 0 or len(scalar_series) == 0:
        return 0.0
    return float(np.mean(_detrend(vertical_velocity) * _detrend(scalar_series)))


def _extract_horizontal_wind(rows: list[NormalizedHFFrame]) -> dict[str, Any]:
    u_values: list[float] = []
    v_values: list[float] = []
    for row in rows:
        payload = _load_payload(row.raw_text) or _load_payload(row.status_text or "")
        u_values.append(_payload_value(payload, ("u", "u_ms", "u_mps", "wind_u")))
        v_values.append(_payload_value(payload, ("v", "v_ms", "v_mps", "wind_v")))
    u_array = _fill_missing(np.array(u_values, dtype=float))
    v_array = _fill_missing(np.array(v_values, dtype=float))
    valid = ~np.isnan(np.array(u_values, dtype=float)) & ~np.isnan(np.array(v_values, dtype=float))
    horizontal_speed = np.sqrt(np.square(u_array) + np.square(v_array))
    return {
        "u": u_array,
        "v": v_array,
        "horizontal_speed": horizontal_speed,
        "horizontal_speed_valid": bool(np.any(valid)),
    }


def _extract_vertical_velocity(rows: list[NormalizedHFFrame]) -> tuple[np.ndarray, bool]:
    values: list[float] = []
    found = False
    for row in rows:
        value = _value_from_payload(row.raw_text)
        if value is None:
            value = _value_from_payload(row.status_text or "")
        if value is None:
            values.append(np.nan)
            continue
        values.append(float(value))
        found = True
    return _fill_missing(np.array(values, dtype=float)), found


def _value_from_payload(payload: str) -> float | None:
    parsed = _load_payload(payload)
    if parsed is None:
        return None
    value = _payload_value(parsed, ("w", "w_ms", "w_mps", "vertical_velocity", "vertical_wind"))
    return None if np.isnan(value) else float(value)


def _load_payload(payload: str) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _payload_value(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> float:
    if not payload:
        return np.nan
    for key in keys:
        if payload.get(key) is not None:
            return float(payload[key])
    return np.nan


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


def _detrend(values: np.ndarray) -> np.ndarray:
    if values.size < 3:
        return values.astype(float, copy=True)
    if signal is not None:
        return signal.detrend(values, type="linear")
    x_axis = np.arange(values.size, dtype=float)
    slope, intercept = np.polyfit(x_axis, values, deg=1)
    return values - (slope * x_axis + intercept)


def _standardize(values: np.ndarray) -> np.ndarray:
    scale = float(np.std(values))
    if scale <= 1e-9:
        return values - float(np.mean(values))
    return (values - float(np.mean(values))) / scale


def _shift_right(values: np.ndarray, count: int) -> np.ndarray:
    if count <= 0:
        return values
    shifted = np.empty_like(values)
    shifted[:count] = values[0]
    shifted[count:] = values[:-count]
    return shifted


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


def _resolve_transfer_metadata(*, config: dict[str, Any], series: dict[str, Any], lag_seconds: float, lag_confidence: float) -> dict[str, Any]:
    notes: list[str] = []
    tube_length = _config_value(config, "transfer_function.tube_length_m", "sampling_chain.tube_length_m", "tube_length_m")
    diameter_mm = _config_value(config, "transfer_function.tube_diameter_mm", "sampling_chain.tube_diameter_mm", "tube_diameter_mm")
    flow_lpm = _config_value(config, "transfer_function.flow_lpm", "sampling_chain.flow_lpm", "flow_lpm")
    separation_m = _config_value(
        config,
        "transfer_function.sensor_separation_m",
        "instrument_layout.height_delta_m",
        "sensor_separation_m",
    )
    path_length_m = _config_value(config, "transfer_function.path_length_m", "path_length_m")
    expected_lag_s = _config_value(config, "lag_phase.expected_lag_s", "expected_lag_s")

    tube_source = "config transfer/sampling chain"
    if tube_length is None or flow_lpm is None or diameter_mm is None:
        tube_source = "fallback: tube metadata unavailable"
        notes.append("tube attenuation fell back to neutral because tube length/diameter/flow metadata are incomplete")
    separation_source = "config instrument layout"
    if separation_m is None:
        separation_source = "fallback: sensor separation metadata unavailable"
        notes.append("sensor separation fell back to neutral because separation metadata are unavailable")
    path_source = "config transfer function"
    if path_length_m is None:
        path_length_m = 0.12
        path_source = "fallback: default optical path length 0.12 m"
        notes.append("path averaging used default path length 0.12 m because path metadata are unavailable")

    horizontal_speed = np.asarray(series.get("horizontal_speed", []), dtype=float)
    if bool(series.get("horizontal_speed_valid")) and horizontal_speed.size:
        adv_speed = float(np.mean(horizontal_speed))
        wind_source = "horizontal wind from payload"
    else:
        adv_speed = 2.0 + float(np.std(np.asarray(series.get("vertical_velocity", []), dtype=float)))
        wind_source = "fallback proxy from vertical velocity variance"
        notes.append("advection speed used fallback proxy because horizontal wind payload is unavailable")

    phase_sigma = max(
        abs(float(lag_seconds) - float(expected_lag_s if expected_lag_s is not None else lag_seconds)),
        (1.0 - float(lag_confidence)) / max(1.0, float(_config_value(config, "sample_hz", "timing.sample_hz") or 10.0)),
    )
    phase_source = (
        "lag uncertainty relative to expected lag"
        if expected_lag_s is not None
        else "fallback from lag confidence because expected lag metadata are unavailable"
    )
    if expected_lag_s is None:
        notes.append("phase attenuation used lag confidence fallback because expected lag metadata are unavailable")

    return {
        "tube_length_m": float(tube_length) if tube_length is not None else None,
        "tube_diameter_mm": float(diameter_mm) if diameter_mm is not None else None,
        "flow_lpm": float(flow_lpm) if flow_lpm is not None else None,
        "sensor_separation_m": float(separation_m) if separation_m is not None else None,
        "path_length_m": float(path_length_m),
        "adv_speed_mps": max(adv_speed, 0.3),
        "phase_sigma_s": max(phase_sigma, 0.005),
        "tube_source": tube_source,
        "separation_source": separation_source,
        "path_source": f"{path_source}; advection={wind_source}",
        "phase_source": phase_source,
        "notes": notes,
    }


def _tube_attenuation(freq: np.ndarray, metadata: dict[str, Any]) -> tuple[np.ndarray, float | None]:
    length = metadata.get("tube_length_m")
    diameter_mm = metadata.get("tube_diameter_mm")
    flow_lpm = metadata.get("flow_lpm")
    if length is None or diameter_mm is None or flow_lpm is None or length <= 0.0 or diameter_mm <= 0.0 or flow_lpm <= 0.0:
        return np.ones_like(freq, dtype=float), None
    radius_m = max(float(diameter_mm) / 1000.0 / 2.0, 1e-4)
    flow_m3_s = float(flow_lpm) / 60000.0
    velocity = max(flow_m3_s / (np.pi * radius_m * radius_m), 0.05)
    residence_time = max(float(length) / velocity, 1e-4)
    cutoff_hz = 1.0 / (2.0 * np.pi * residence_time)
    curve = np.clip(1.0 / np.sqrt(1.0 + np.square(freq / max(cutoff_hz, 1e-4))), 0.05, 1.0)
    return curve, float(cutoff_hz)


def _sensor_separation(freq: np.ndarray, metadata: dict[str, Any]) -> tuple[np.ndarray, float | None]:
    separation = metadata.get("sensor_separation_m")
    if separation is None or separation <= 0.0:
        return np.ones_like(freq, dtype=float), None
    adv_speed = max(float(metadata["adv_speed_mps"]), 0.3)
    cutoff_hz = adv_speed / (2.0 * np.pi * max(float(separation), 1e-4))
    curve = np.clip(1.0 / np.sqrt(1.0 + np.square(freq / max(cutoff_hz, 1e-4))), 0.05, 1.0)
    return curve, float(cutoff_hz)


def _path_averaging(freq: np.ndarray, metadata: dict[str, Any]) -> tuple[np.ndarray, float | None]:
    path_length = max(float(metadata["path_length_m"]), 1e-4)
    adv_speed = max(float(metadata["adv_speed_mps"]), 0.3)
    cutoff_hz = adv_speed / (np.pi * path_length)
    scaled = freq / max(cutoff_hz, 1e-4)
    curve = np.clip(np.abs(np.sinc(scaled / 2.0)), 0.05, 1.0)
    return curve, float(cutoff_hz)


def _phase_attenuation(freq: np.ndarray, metadata: dict[str, Any]) -> tuple[np.ndarray, float]:
    sigma_s = max(float(metadata["phase_sigma_s"]), 1e-4)
    curve = np.clip(np.exp(-0.5 * np.square(2.0 * np.pi * freq * sigma_s)), 0.05, 1.0)
    cutoff_hz = 1.0 / (2.0 * np.pi * sigma_s)
    return curve, float(cutoff_hz)


def _correction_factor_components(
    *,
    freq: np.ndarray,
    observed_transfer: np.ndarray,
    component_curves: dict[str, np.ndarray],
    base_factor: float,
    factor_before_cap: float,
    factor_cap: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    if freq.size < 4:
        return (
            {
                "base_factor": float(base_factor),
                "tube_component": 1.0,
                "separation_component": 1.0,
                "path_component": 1.0,
                "phase_component": 1.0,
                "total_factor": float(base_factor),
            },
            {
                "factor_before_cap": float(factor_before_cap),
                "factor_cap": float(factor_cap),
                "factor_cap_applied": bool(factor_before_cap > factor_cap),
                "weighted_component_loss": {},
                "observed_transfer_mean": float(np.mean(observed_transfer)),
            },
        )

    high_mask = freq >= np.quantile(freq, 0.65)
    if not np.any(high_mask):
        high_mask = freq >= np.median(freq)
    weights = observed_transfer[high_mask]
    weights = weights / max(float(np.sum(weights)), 1e-9)
    losses = {}
    for key, curve in component_curves.items():
        component_loss = np.clip(1.0 - np.asarray(curve, dtype=float)[high_mask], 0.0, 1.0)
        losses[key] = float(np.sum(component_loss * weights))
    total_loss = sum(losses.values())
    if total_loss <= 1e-9 and base_factor > 1.0:
        losses = {key: 1.0 for key in component_curves}
        total_loss = float(len(component_curves))

    component_factors: dict[str, float] = {}
    for key in ("tube_component", "separation_component", "path_component", "phase_component"):
        share = (losses.get(key, 0.0) / total_loss) if total_loss > 0.0 else 0.0
        component_factors[key] = float(base_factor ** share) if share > 0.0 else 1.0
    total_factor = float(np.prod(list(component_factors.values()))) if component_factors else float(base_factor)
    component_payload = {"base_factor": float(base_factor), **component_factors, "total_factor": total_factor}
    detail = {
        "factor_before_cap": float(factor_before_cap),
        "factor_cap": float(factor_cap),
        "factor_cap_applied": bool(factor_before_cap > factor_cap),
        "weighted_component_loss": losses,
        "observed_transfer_mean": float(np.mean(observed_transfer[high_mask])),
        "high_frequency_bins": int(np.count_nonzero(high_mask)),
    }
    return component_payload, detail


def _component_payload(
    freq: np.ndarray,
    curve: np.ndarray,
    cutoff_hz: float | None,
    enabled: bool,
    source: str,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "freq": [float(item) for item in freq],
        "value": [float(item) for item in curve],
        "cutoff_hz": cutoff_hz,
        "source": source,
    }


def _effective_cutoff(freq: np.ndarray, curve: np.ndarray) -> float | None:
    if freq.size == 0 or curve.size == 0:
        return None
    indices = np.where(curve <= 1.0 / np.sqrt(2.0))[0]
    if indices.size == 0:
        return None
    return float(freq[int(indices[0])])


def _config_value(config: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = config
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current
    return None


def _welch_density(values: np.ndarray, fs: float, nperseg: int) -> tuple[np.ndarray, np.ndarray]:
    if signal is not None:
        return signal.welch(values, fs=fs, nperseg=nperseg, scaling="density")

    step = max(1, nperseg // 2)
    window = np.hanning(nperseg)
    scale = fs * np.sum(window * window)
    spectra: list[np.ndarray] = []
    for start in range(0, max(1, values.size - nperseg + 1), step):
        segment = values[start : start + nperseg]
        if segment.size < nperseg:
            break
        spectrum = np.fft.rfft(segment * window)
        density = (np.abs(spectrum) ** 2) / max(scale, 1e-12)
        spectra.append(density)
    if not spectra:
        return np.array([], dtype=float), np.array([], dtype=float)
    averaged = np.mean(np.stack(spectra, axis=0), axis=0)
    freq = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return freq, averaged


def _csd_density(x_values: np.ndarray, y_values: np.ndarray, fs: float, nperseg: int) -> tuple[np.ndarray, np.ndarray]:
    if signal is not None:
        return signal.csd(x_values, y_values, fs=fs, nperseg=nperseg, scaling="density")

    step = max(1, nperseg // 2)
    window = np.hanning(nperseg)
    scale = fs * np.sum(window * window)
    spectra: list[np.ndarray] = []
    for start in range(0, max(1, min(x_values.size, y_values.size) - nperseg + 1), step):
        left = x_values[start : start + nperseg]
        right = y_values[start : start + nperseg]
        if left.size < nperseg or right.size < nperseg:
            break
        x_fft = np.fft.rfft(left * window)
        y_fft = np.fft.rfft(right * window)
        spectra.append((x_fft * np.conjugate(y_fft)) / max(scale, 1e-12))
    if not spectra:
        return np.array([], dtype=float), np.array([], dtype=complex)
    averaged = np.mean(np.stack(spectra, axis=0), axis=0)
    freq = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return freq, averaged
