from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from models.comparison_models import CompareAttributionResult, EddyProCompareResult, WindowAttributionResult


CAUSE_RECOMMENDATIONS = {
    "window_alignment": "优先核对窗口起止时间、时区、整窗规则和容差匹配设置。",
    "lag_method_or_lag_quality": "复核 lag 搜索窗口、峰值选择规则以及 lag 质量指标。",
    "rp_qc_or_stationarity": "检查 RP qc_matrix、stationarity 分段结果和异常窗口筛除规则。",
    "turbulence_or_ustar": "复核 u*、turbulence_score 以及低湍流窗口是否应剔除。",
    "density_or_mixing_ratio_path": "核对密度修正、混合比路径与通量口径是否一致。",
    "tube_attenuation": "复核 tube length/diameter/flow 等链路参数与 tube attenuation 模型。",
    "sensor_separation": "复核传感器间距、安装相对位置和 separation 分项设置。",
    "path_averaging": "复核路径长度、风速估计与 path averaging 分项设置。",
    "phase_or_lag_transfer": "复核 expected lag、phase term 与 transfer function 中的相位项。",
    "field_mapping_or_missing_metadata": "先核对字段映射、元数据完整性与回退项说明。",
    "unknown": "目前证据不足，建议先检查窗口对齐、字段映射和 provenance 明细。",
}


def classify_compare_result(
    compare_result: EddyProCompareResult,
    current_runs: dict[str, Any] | None = None,
    reference_meta: dict[str, Any] | None = None,
) -> CompareAttributionResult:
    created_at = datetime.now(UTC).replace(tzinfo=None)
    rp_lookup, spectral_lookup = _build_run_lookups(current_runs or {})
    reference_meta = dict(reference_meta or {})

    global_scores: dict[str, float] = defaultdict(float)
    global_evidence: dict[str, list[str]] = defaultdict(list)
    notes: list[str] = []

    summary = dict(compare_result.summary_metrics)
    unmatched_current = int(summary.get("unmatched_current_count", 0) or 0)
    unmatched_reference = int(summary.get("unmatched_reference_count", 0) or 0)
    matched_count = int(summary.get("matched_window_count", 0) or 0)
    total_windows = max(int(summary.get("current_window_count", 0) or 0), int(summary.get("reference_window_count", 0) or 0), 1)
    unmatched_ratio = (unmatched_current + unmatched_reference) / total_windows

    if unmatched_ratio >= 0.3:
        score = 0.95 if unmatched_ratio >= 0.5 else 0.72
        evidence = f"未匹配窗口偏多：current={unmatched_current}, reference={unmatched_reference}"
        _add_score(global_scores, global_evidence, "window_alignment", score, evidence)

    avg_lag_delta = _abs_float(summary.get("avg_lag_delta"))
    if avg_lag_delta >= 1.0:
        _add_score(global_scores, global_evidence, "lag_method_or_lag_quality", 0.9, f"平均 lag 偏差较大：{avg_lag_delta:.3f}s")
    elif avg_lag_delta >= 0.4:
        _add_score(global_scores, global_evidence, "lag_method_or_lag_quality", 0.6, f"平均 lag 偏差偏高：{avg_lag_delta:.3f}s")

    avg_cf_delta = _abs_float(summary.get("avg_correction_factor_delta"))
    if avg_cf_delta >= 0.08:
        component_cause, component_score, component_evidence = _classify_component_summary(spectral_lookup.values(), reference_meta)
        if component_cause is not None:
            _add_score(global_scores, global_evidence, component_cause, component_score, component_evidence)

    if _has_missing_metadata_signal(compare_result, spectral_lookup.values(), reference_meta):
        _add_score(
            global_scores,
            global_evidence,
            "field_mapping_or_missing_metadata",
            0.85,
            "provenance 或 compare notes 指向字段映射/元数据缺失",
        )

    window_attributions: list[WindowAttributionResult] = []
    for window in compare_result.window_results:
        rp_window = _match_window_context(window, rp_lookup)
        spectral_window = _match_window_context(window, spectral_lookup)
        attribution = _classify_window_result(window, rp_window=rp_window, spectral_window=spectral_window, reference_meta=reference_meta)
        window_attributions.append(attribution)
        _add_score(
            global_scores,
            global_evidence,
            attribution.dominant_cause,
            max(0.2, min(1.0, attribution.confidence)) * 0.6,
            f"{window.window_key}: {', '.join(attribution.evidence[:2]) or attribution.dominant_cause}",
        )
        for cause in attribution.secondary_causes:
            _add_score(global_scores, global_evidence, cause, 0.18, f"{window.window_key}: secondary cause")

    if not global_scores and matched_count == 0:
        _add_score(global_scores, global_evidence, "window_alignment", 0.7, "没有匹配窗口可用于稳定对标")
    if not global_scores:
        _add_score(global_scores, global_evidence, "unknown", 0.4, "当前证据不足，无法稳定定位单一主因")

    ranked = sorted(global_scores.items(), key=lambda item: item[1], reverse=True)
    dominant_causes = [cause for cause, _score in ranked[:3]]
    secondary_causes = [cause for cause, _score in ranked[3:6]]
    risk_level = _risk_level(compare_result=compare_result, ranked_scores=ranked)
    summary_text = _summary_text(dominant_causes, compare_result.summary_metrics, risk_level)

    if not current_runs:
        notes.append("current_runs 未提供，本次仅基于 compare_result 做基础归因。")
    elif not rp_lookup:
        notes.append("未找到可用 RP run，上层归因未使用 stationarity / turbulence / u* 证据。")
    elif not spectral_lookup:
        notes.append("未找到可用 Spectral run，上层归因未使用 correction factor provenance 证据。")

    if reference_meta:
        notes.append("reference_meta 已接入，用于补充元数据缺失/映射退化判断。")

    return CompareAttributionResult(
        attribution_id=f"attr_{created_at:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}",
        created_at=created_at,
        compare_id=compare_result.compare_id,
        dominant_causes=dominant_causes,
        secondary_causes=secondary_causes,
        risk_level=risk_level,
        summary_text=summary_text,
        notes=notes,
        window_attributions=window_attributions,
    )


def _classify_window_result(
    window: Any,
    *,
    rp_window: Any | None,
    spectral_window: Any | None,
    reference_meta: dict[str, Any],
) -> WindowAttributionResult:
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    notes: list[str] = []

    note_text = " ".join(str(item) for item in getattr(window, "notes", [])).lower()
    if "no matched" in note_text:
        _add_score(scores, evidence, "window_alignment", 0.96, "窗口未匹配或仅能弱匹配")

    lag_delta = _abs_float(getattr(window, "lag_delta", None))
    flux_delta = _abs_float(getattr(window, "flux_delta", None))
    cf_delta = _abs_float(getattr(window, "correction_factor_delta", None))

    if lag_delta >= 1.0:
        _add_score(scores, evidence, "lag_method_or_lag_quality", 0.92, f"lag 偏差较大：{lag_delta:.3f}s")
    elif lag_delta >= 0.4:
        _add_score(scores, evidence, "lag_method_or_lag_quality", 0.64, f"lag 偏差偏高：{lag_delta:.3f}s")

    rp_qc_score = _safe_number(getattr(rp_window, "qc_score", None))
    stationarity_score = _safe_number(getattr(rp_window, "stationarity_score", None))
    turbulence_score = _safe_number(getattr(rp_window, "turbulence_score", None))
    ustar = _safe_number(getattr(rp_window, "ustar", None))

    if flux_delta >= 0.1:
        if stationarity_score is not None and stationarity_score < 60.0:
            _add_score(scores, evidence, "rp_qc_or_stationarity", 0.86, f"stationarity_score 偏低：{stationarity_score:.1f}")
        elif rp_qc_score is not None and rp_qc_score < 60.0:
            _add_score(scores, evidence, "rp_qc_or_stationarity", 0.76, f"RP qc_score 偏低：{rp_qc_score:.1f}")

        if (turbulence_score is not None and turbulence_score < 60.0) or (ustar is not None and ustar < 0.15):
            detail = f"turbulence_score={turbulence_score:.1f}" if turbulence_score is not None else f"u*={ustar:.3f}"
            _add_score(scores, evidence, "turbulence_or_ustar", 0.82, f"湍流/ustar 证据偏弱：{detail}")

        if not scores and flux_delta >= 0.15:
            _add_score(scores, evidence, "density_or_mixing_ratio_path", 0.58, f"flux 偏差较大但 RP/FCC 证据不足：{flux_delta:.6f}")

    provenance_notes = [str(item) for item in getattr(spectral_window, "provenance_notes", [])] if spectral_window is not None else []
    if _notes_indicate_missing_metadata(provenance_notes) or _reference_meta_missing(reference_meta):
        _add_score(scores, evidence, "field_mapping_or_missing_metadata", 0.84, "provenance_notes 指向元数据缺失或回退项")

    if cf_delta >= 0.05 and spectral_window is not None:
        component_cause, component_score, component_evidence = _classify_component_window(spectral_window, cf_delta)
        if component_cause is not None:
            _add_score(scores, evidence, component_cause, component_score, component_evidence)

    if not scores:
        _add_score(scores, evidence, "unknown", 0.35, "当前窗口证据不足，无法稳定定位主因")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    dominant_cause = ranked[0][0]
    secondary_causes = [cause for cause, _score in ranked[1:3]]
    confidence = min(0.99, max(0.2, ranked[0][1]))
    window_evidence = evidence.get(dominant_cause, [])[:4]
    recommendation = CAUSE_RECOMMENDATIONS.get(dominant_cause, CAUSE_RECOMMENDATIONS["unknown"])

    if rp_window is None:
        notes.append("未匹配到 RP window 上下文。")
    if spectral_window is None:
        notes.append("未匹配到 Spectral window provenance 上下文。")

    return WindowAttributionResult(
        window_key=str(getattr(window, "window_key", "")),
        dominant_cause=dominant_cause,
        secondary_causes=secondary_causes,
        confidence=float(confidence),
        evidence=window_evidence,
        recommendation=recommendation,
        notes=notes,
    )


def _build_run_lookups(current_runs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rp_run = current_runs.get("rp_run") if isinstance(current_runs, dict) else None
    spectral_run = current_runs.get("spectral_run") if isinstance(current_runs, dict) else None
    return _window_lookup(rp_run), _window_lookup(spectral_run)


def _window_lookup(run_result: Any | None) -> dict[str, Any]:
    if run_result is None:
        return {}
    lookup: dict[str, Any] = {}
    for window in getattr(run_result, "windows", []) or []:
        window_id = str(getattr(window, "window_id", "")).strip()
        if window_id:
            lookup[window_id] = window
        start_time = getattr(window, "start_time", None)
        end_time = getattr(window, "end_time", None)
        if start_time is not None or end_time is not None:
            lookup[_time_key(start_time, end_time)] = window
    return lookup


def _match_window_context(window: Any, lookup: dict[str, Any]) -> Any | None:
    key = str(getattr(window, "window_key", "")).strip()
    if key and key in lookup:
        return lookup[key]
    return lookup.get(_time_key(getattr(window, "start_time", None), getattr(window, "end_time", None)))


def _time_key(start_time: Any, end_time: Any) -> str:
    start = start_time.isoformat() if start_time is not None else "none"
    end = end_time.isoformat() if end_time is not None else "none"
    return f"{start}__{end}"


def _classify_component_window(spectral_window: Any, cf_delta: float) -> tuple[str | None, float, str]:
    components = dict(getattr(spectral_window, "correction_factor_components", {}) or {})
    mapping = {
        "tube_component": "tube_attenuation",
        "separation_component": "sensor_separation",
        "path_component": "path_averaging",
        "phase_component": "phase_or_lag_transfer",
    }
    strongest_key: str | None = None
    strongest_value = 1.0
    for key in mapping:
        value = _safe_number(components.get(key))
        if value is not None and value > strongest_value:
            strongest_key = key
            strongest_value = value
    if strongest_key is None or cf_delta < 0.05:
        return None, 0.0, ""
    score = min(0.95, 0.55 + (strongest_value - 1.0) * 4.0 + min(cf_delta, 0.2))
    return mapping[strongest_key], score, f"{strongest_key} 偏高：{strongest_value:.3f}"


def _classify_component_summary(spectral_windows: Any, reference_meta: dict[str, Any]) -> tuple[str | None, float, str]:
    values_by_key: dict[str, list[float]] = defaultdict(list)
    for window in spectral_windows:
        components = dict(getattr(window, "correction_factor_components", {}) or {})
        for key in ("tube_component", "separation_component", "path_component", "phase_component"):
            value = _safe_number(components.get(key))
            if value is not None:
                values_by_key[key].append(value)
    mapping = {
        "tube_component": "tube_attenuation",
        "separation_component": "sensor_separation",
        "path_component": "path_averaging",
        "phase_component": "phase_or_lag_transfer",
    }
    best_key: str | None = None
    best_value = 1.0
    for key, values in values_by_key.items():
        if values:
            value = sum(values) / len(values)
            if value > best_value:
                best_key = key
                best_value = value
    if best_key is None:
        if _reference_meta_missing(reference_meta):
            return "field_mapping_or_missing_metadata", 0.75, "reference_meta 缺少元数据，无法稳定拆解 correction factor provenance"
        return None, 0.0, ""
    score = min(0.9, 0.48 + (best_value - 1.0) * 4.0)
    return mapping[best_key], score, f"平均 {best_key} 偏高：{best_value:.3f}"


def _has_missing_metadata_signal(compare_result: EddyProCompareResult, spectral_windows: Any, reference_meta: dict[str, Any]) -> bool:
    notes_text = " ".join(compare_result.notes).lower()
    if "missing" in notes_text or "field" in notes_text or "mapping" in notes_text:
        return True
    for window in spectral_windows:
        if _notes_indicate_missing_metadata(getattr(window, "provenance_notes", []) or []):
            return True
    return _reference_meta_missing(reference_meta)


def _notes_indicate_missing_metadata(notes: list[str]) -> bool:
    text = " ".join(str(item).lower() for item in notes)
    return any(token in text for token in ("fallback", "missing", "unavailable", "default", "metadata"))


def _reference_meta_missing(reference_meta: dict[str, Any]) -> bool:
    if not reference_meta:
        return False
    missing = reference_meta.get("missing_metadata") or reference_meta.get("mapping_incomplete") or reference_meta.get("field_mapping_issue")
    return bool(missing)


def _add_score(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    cause: str,
    score: float,
    evidence_text: str,
) -> None:
    if score <= 0.0:
        return
    scores[cause] += float(score)
    if evidence_text and evidence_text not in evidence[cause]:
        evidence[cause].append(evidence_text)


def _risk_level(compare_result: EddyProCompareResult, ranked_scores: list[tuple[str, float]]) -> str:
    summary = compare_result.summary_metrics
    top_score = ranked_scores[0][1] if ranked_scores else 0.0
    unmatched = int(summary.get("unmatched_current_count", 0) or 0) + int(summary.get("unmatched_reference_count", 0) or 0)
    avg_flux_delta = _abs_float(summary.get("avg_flux_delta"))
    avg_lag_delta = _abs_float(summary.get("avg_lag_delta"))
    if unmatched >= 3 or avg_flux_delta >= 0.2 or avg_lag_delta >= 1.2 or top_score >= 1.5:
        return "高"
    if unmatched >= 1 or avg_flux_delta >= 0.08 or avg_lag_delta >= 0.4 or top_score >= 0.8:
        return "中"
    return "低"


def _summary_text(dominant_causes: list[str], summary_metrics: dict[str, Any], risk_level: str) -> str:
    if not dominant_causes:
        return "当前归因证据不足，建议先检查窗口对齐与字段映射。"
    cause_text = "、".join(dominant_causes[:3])
    matched = int(summary_metrics.get("matched_window_count", 0) or 0)
    unmatched = int(summary_metrics.get("unmatched_current_count", 0) or 0) + int(summary_metrics.get("unmatched_reference_count", 0) or 0)
    return f"本次 EddyPro 对标差异的主要归因倾向为：{cause_text}。当前风险等级为{risk_level}，匹配窗口 {matched} 个，未匹配窗口 {unmatched} 个。"


def _abs_float(value: Any) -> float:
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def _safe_number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
