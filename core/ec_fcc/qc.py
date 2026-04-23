from __future__ import annotations

from typing import Any


def classify_window_qc(
    *,
    lag_confidence: float,
    correction_factor: float,
    loss_ratio: float,
    ogive_final: float,
    lag_disagreement_s: float,
) -> dict[str, Any]:
    issues: list[str] = []
    score = 0

    if lag_confidence < 0.58:
        issues.append("lag 不稳")
        score += 2
    elif lag_confidence < 0.76:
        issues.append("相位偏移")
        score += 1

    if correction_factor > 1.22 or loss_ratio > 0.24:
        issues.append("高频损失")
        score += 2
    elif correction_factor > 1.12 or loss_ratio > 0.12:
        issues.append("高频损失")
        score += 1

    if abs(ogive_final - 1.0) > 0.24:
        issues.append("非平稳")
        score += 2
    elif abs(ogive_final - 1.0) > 0.12:
        issues.append("非平稳")
        score += 1

    if lag_disagreement_s > 0.7 and "相位偏移" not in issues:
        issues.append("相位偏移")
        score += 1

    if score <= 1:
        qc_grade = "A"
    elif score <= 3:
        qc_grade = "B"
    else:
        qc_grade = "C"

    if loss_ratio > 0.26:
        risk = "高"
    elif loss_ratio > 0.13:
        risk = "中"
    else:
        risk = "低"

    anomaly_type = issues[0] if issues else "无异常"
    if not issues:
        reason = "lag 主峰清晰，互谱主能量带稳定，ogive 已收敛到平台。"
    else:
        reason_parts: list[str] = []
        if "lag 不稳" in issues:
            reason_parts.append("lag 曲线主峰不够突出或存在竞争峰值")
        if "相位偏移" in issues:
            reason_parts.append("co2 与 h2o 的 lag 判断存在偏移")
        if "高频损失" in issues:
            reason_parts.append("高频端谱能量衰减偏快，修正因子被抬高")
        if "非平稳" in issues:
            reason_parts.append("ogive 平台尚未稳定，窗口内部可能存在状态变化")
        reason = "；".join(reason_parts) + "。"

    return {
        "qc_grade": qc_grade,
        "anomaly_type": anomaly_type,
        "high_freq_loss_risk": risk,
        "reason": reason,
        "qc_band_value": {"A": 3.0, "B": 2.0, "C": 1.0}[qc_grade],
    }
