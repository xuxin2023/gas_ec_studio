from __future__ import annotations

from typing import Any


GRADE_THRESHOLDS = [
    (85.0, "A"),
    (65.0, "B"),
    (0.0, "C"),
]


def classify_window_qc(
    *,
    issues: list[str],
    continuity_ratio: float,
    missing_ratio: float,
    lag_confidence: float,
    density_correction_factor: float,
    rotation_applied: bool,
    mean_rotated_w: float,
    stationarity_score: float | None,
    stationarity_detail: dict[str, Any],
    turbulence_score: float | None,
    turbulence_detail: dict[str, Any],
    ustar: float | None,
    advanced_tests: dict[str, dict[str, Any]] | None = None,
    eddypro_qc_method: str = "",
) -> dict[str, Any]:
    qc_matrix: dict[str, dict[str, Any]] = {}

    signal_issues = [issue for issue in issues if issue.endswith("_missing") or issue.endswith("_constant") or issue.endswith("_insufficient") or issue == "empty_window"]
    spike_issues = [issue for issue in issues if issue.endswith("_spike")]
    dropout_issues = [issue for issue in issues if issue.endswith("_dropout")]
    absolute_limit_issues = [issue for issue in issues if issue.endswith("_absolute_limit")]
    discontinuity_issues = [issue for issue in issues if issue.endswith("_discontinuity") or issue == "discontinuous_data"]
    skewness_issues = [issue for issue in issues if issue.endswith("_skewness")]
    kurtosis_issues = [issue for issue in issues if issue.endswith("_kurtosis")]

    qc_matrix["signal_validity"] = _issue_bucket(name="signal_validity", issues=signal_issues, fail_weight=22.0, attention_weight=10.0)
    qc_matrix["spike"] = _issue_bucket(name="spike", issues=spike_issues, fail_weight=8.0, attention_weight=4.0)
    qc_matrix["dropout"] = _issue_bucket(name="dropout", issues=dropout_issues, fail_weight=8.0, attention_weight=4.0)
    qc_matrix["absolute_limit"] = _issue_bucket(name="absolute_limit", issues=absolute_limit_issues, fail_weight=12.0, attention_weight=6.0)
    qc_matrix["discontinuity"] = _issue_bucket(name="discontinuity", issues=discontinuity_issues, fail_weight=10.0, attention_weight=5.0)
    qc_matrix["continuity"] = _ratio_check(
        value=continuity_ratio,
        pass_threshold=0.98,
        attention_threshold=0.90,
        key="continuity",
        better="high",
        weight=12.0,
        reason_templates=("continuity ratio is stable", "continuity ratio needs attention", "continuity ratio is poor"),
    )
    qc_matrix["missing_ratio"] = _ratio_check(
        value=missing_ratio,
        pass_threshold=0.03,
        attention_threshold=0.12,
        key="missing_ratio",
        better="low",
        weight=10.0,
        reason_templates=("missing ratio is low", "missing ratio is elevated", "missing ratio is high"),
    )
    qc_matrix["lag_confidence"] = _ratio_check(
        value=lag_confidence,
        pass_threshold=0.75,
        attention_threshold=0.55,
        key="lag_confidence",
        better="high",
        weight=10.0,
        reason_templates=("lag confidence is strong", "lag confidence is moderate", "lag confidence is low"),
    )
    qc_matrix["stationarity"] = _score_check(
        score=stationarity_score,
        detail=stationarity_detail,
        key="stationarity",
        weight=16.0,
        fallback_reason="stationarity check fell back because data were insufficient",
    )
    qc_matrix["turbulence"] = _score_check(
        score=turbulence_score,
        detail={**turbulence_detail, "ustar": ustar},
        key="turbulence",
        weight=16.0,
        fallback_reason="turbulence check fell back because wind components were insufficient",
    )
    qc_matrix["density_correction"] = _delta_check(
        value=abs(density_correction_factor - 1.0),
        attention_threshold=0.12,
        fail_threshold=0.30,
        key="density_correction",
        weight=6.0,
        description="density correction factor deviation",
    )
    qc_matrix["rotation"] = _rotation_check(rotation_applied=rotation_applied, mean_rotated_w=mean_rotated_w, weight=4.0)
    qc_matrix["skewness"] = _issue_bucket(name="skewness", issues=skewness_issues, fail_weight=6.0, attention_weight=3.0)
    qc_matrix["kurtosis"] = _issue_bucket(name="kurtosis", issues=kurtosis_issues, fail_weight=6.0, attention_weight=3.0)

    if advanced_tests:
        for test_key, test_result in advanced_tests.items():
            matrix_key = f"adv_{test_key}"
            qc_matrix[matrix_key] = _advanced_test_check(
                test_key=test_key, test_result=test_result, weight=1.0,
            )

    total_weight = sum(float(item["weight"]) for item in qc_matrix.values())
    weighted_score = sum(float(item["normalized_score"]) * float(item["weight"]) for item in qc_matrix.values())
    qc_score = float(weighted_score / max(total_weight, 1e-9))
    qc_grade = _grade_from_score(qc_score)

    qc_flags = [name for name, item in qc_matrix.items() if item["status"] in {"attention", "fail", "fallback"}]
    qc_reasons = []
    for name in qc_flags:
        reason = str(qc_matrix[name].get("reason", "")).strip()
        if reason:
            qc_reasons.append(reason)
    if not qc_reasons:
        qc_reasons.append("window passed unified RP QC matrix")

    failure_flags = [name for name in qc_flags if qc_matrix[name]["status"] == "fail"]
    attention_flags = [name for name in qc_flags if qc_matrix[name]["status"] == "attention"]
    if "signal_validity" in failure_flags:
        qc_grade = "C"
    eddypro_quality = _eddypro_quality_flag(
        method=eddypro_qc_method,
        stationarity_detail=stationarity_detail,
        turbulence_detail=turbulence_detail,
    )
    if eddypro_quality:
        qc_matrix["eddypro_quality_flag"] = eddypro_quality
        qc_grade = str(eddypro_quality["grade"])
        qc_score = min(qc_score, float(eddypro_quality["normalized_score"]))
        if eddypro_quality["status"] != "pass":
            qc_flags.append("eddypro_quality_flag")
            qc_reasons.append(str(eddypro_quality["reason"]))
    failure_flags = [name for name in qc_flags if qc_matrix[name]["status"] == "fail"]
    attention_flags = [name for name in qc_flags if qc_matrix[name]["status"] == "attention"]
    anomaly_type = failure_flags[0] if failure_flags else (attention_flags[0] if attention_flags else "none")
    signal_issues = qc_matrix.get("signal_validity", {}).get("issues", [])
    if any(str(issue).endswith("_constant") for issue in signal_issues):
        anomaly_type = "constant_signal"
    reason = "; ".join(qc_reasons)

    return {
        "qc_score": qc_score,
        "qc_grade": qc_grade,
        "anomaly_type": anomaly_type,
        "reason": reason,
        "qc_flags": qc_flags,
        "qc_reasons": qc_reasons,
        "qc_matrix": qc_matrix,
    }


def _eddypro_quality_flag(
    *,
    method: str,
    stationarity_detail: dict[str, Any],
    turbulence_detail: dict[str, Any],
) -> dict[str, Any] | None:
    normalized = str(method or "").strip().lower()
    if normalized not in {"mauder_foken_04", "mauder-foken-04", "mauder_foken", "eddypro_mauder_foken_04"}:
        return None
    stationarity_flag = _bounded_int(stationarity_detail.get("eddypro_partial_flag_lf"), default=9)
    turbulence_flag = _bounded_int(
        turbulence_detail.get("eddypro_partial_flag_lf", turbulence_detail.get("itc_partial_flag")),
        default=1,
    )
    if stationarity_flag <= 2 and turbulence_flag <= 2:
        flag = 0
    elif stationarity_flag <= 5 and turbulence_flag <= 5:
        flag = 1
    else:
        flag = 2
    grade = {0: "A", 1: "B", 2: "C"}[flag]
    status = "pass" if flag == 0 else ("attention" if flag == 1 else "fail")
    normalized_score = {0: 100.0, 1: 70.0, 2: 35.0}[flag]
    return _matrix_item(
        name="eddypro_quality_flag",
        status=status,
        normalized_score=normalized_score,
        weight=0.0,
        reason=(
            f"EddyPro Mauder-Foken 2004 QC flag={flag} "
            f"(stationarity_flag={stationarity_flag}, turbulence_flag={turbulence_flag})"
        ),
        value=flag,
        detail={
            "method": "mauder_foken_04",
            "flag": flag,
            "grade": grade,
            "stationarity_flag": stationarity_flag,
            "turbulence_flag": turbulence_flag,
            "provenance": "EddyPro QualityFlags/GTK2Flag mapping: 0=A, 1=B, 2=C.",
            "limitations": [
                "Turbulence partial flag falls back to the internal turbulence detail when exact EddyPro ITC metadata are unavailable.",
            ],
        },
    ) | {"grade": grade}


def _bounded_int(value: Any, *, default: int) -> int:
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(1, min(9, numeric))


def _issue_bucket(name: str, issues: list[str], fail_weight: float, attention_weight: float) -> dict[str, Any]:
    if not issues:
        return _matrix_item(name=name, status="pass", normalized_score=100.0, weight=fail_weight, reason="passed")
    status = "fail" if any(issue.endswith("_missing") or issue.endswith("_constant") or issue == "empty_window" for issue in issues) else "attention"
    weight = fail_weight if status == "fail" else attention_weight
    normalized_score = 10.0 if status == "fail" else 60.0
    reason = ", ".join(_describe_issue(issue) for issue in issues)
    return _matrix_item(name=name, status=status, normalized_score=normalized_score, weight=weight, reason=reason, issues=issues)


def _ratio_check(
    *,
    value: float,
    pass_threshold: float,
    attention_threshold: float,
    key: str,
    better: str,
    weight: float,
    reason_templates: tuple[str, str, str],
) -> dict[str, Any]:
    if better == "high":
        if value >= pass_threshold:
            status, normalized_score = "pass", 100.0
        elif value >= attention_threshold:
            status, normalized_score = "attention", 65.0
        else:
            status, normalized_score = "fail", 25.0
    else:
        if value <= pass_threshold:
            status, normalized_score = "pass", 100.0
        elif value <= attention_threshold:
            status, normalized_score = "attention", 65.0
        else:
            status, normalized_score = "fail", 25.0
    reason = reason_templates[0] if status == "pass" else (f"{reason_templates[1]} ({value:.3f})" if status == "attention" else f"{reason_templates[2]} ({value:.3f})")
    return _matrix_item(name=key, status=status, normalized_score=normalized_score, weight=weight, reason=reason, value=value)


def _score_check(
    *,
    score: float | None,
    detail: dict[str, Any],
    key: str,
    weight: float,
    fallback_reason: str,
) -> dict[str, Any]:
    status_hint = str(detail.get("status", "")).strip().lower()
    if score is None or status_hint in {"insufficient_data", "fallback"}:
        detail_reason = str(detail.get("reason") or "").strip()
        reason = detail_reason if detail_reason.startswith(key) else f"{key}: {detail_reason or fallback_reason}"
        return _matrix_item(name=key, status="fallback", normalized_score=35.0, weight=weight, reason=reason, detail=detail, value=score)
    if score >= 80.0:
        status = "pass"
    elif score >= 60.0:
        status = "attention"
    else:
        status = "fail"
    if status == "pass":
        reason = f"{key} passed ({score:.1f})"
    elif status == "attention":
        reason = f"{key} needs attention ({score:.1f})"
    else:
        reason = f"{key} failed ({score:.1f})"
    return _matrix_item(name=key, status=status, normalized_score=float(score), weight=weight, reason=reason, detail=detail, value=score)


def _delta_check(
    *,
    value: float,
    attention_threshold: float,
    fail_threshold: float,
    key: str,
    weight: float,
    description: str,
) -> dict[str, Any]:
    if value <= attention_threshold:
        status, normalized_score = "pass", 100.0
    elif value <= fail_threshold:
        status, normalized_score = "attention", 65.0
    else:
        status, normalized_score = "fail", 25.0
    if status == "pass":
        reason = f"{description} is acceptable"
    elif status == "attention":
        reason = f"{description} is noticeable ({value:.3f})"
    else:
        reason = f"{description} is large ({value:.3f})"
    return _matrix_item(name=key, status=status, normalized_score=normalized_score, weight=weight, reason=reason, value=value)


def _advanced_test_check(*, test_key: str, test_result: dict[str, Any], weight: float) -> dict[str, Any]:
    status_raw = str(test_result.get("status", ""))
    if status_raw == "pass":
        return _matrix_item(name=f"adv_{test_key}", status="pass", normalized_score=100.0, weight=weight, reason=f"advanced test {test_key} passed", detail=test_result.get("detail", {}), value=test_result.get("detail", {}).get("ratio") or test_result.get("detail", {}).get("cv") or test_result.get("detail", {}).get("confidence"))
    if status_raw in ("insufficient_data", "constant_signal", "calm"):
        return _matrix_item(name=f"adv_{test_key}", status="fallback", normalized_score=35.0, weight=weight, reason=f"advanced test {test_key} skipped ({status_raw})", detail=test_result.get("detail", {}))
    if status_raw == "fail":
        return _matrix_item(name=f"adv_{test_key}", status="fail", normalized_score=25.0, weight=weight, reason=f"advanced test {test_key} failed", detail=test_result.get("detail", {}), value=test_result.get("detail", {}).get("ratio") or test_result.get("detail", {}).get("cv") or test_result.get("detail", {}).get("exceed_fraction"))
    return _matrix_item(name=f"adv_{test_key}", status="fallback", normalized_score=35.0, weight=weight, reason=f"advanced test {test_key} unknown status ({status_raw})", detail=test_result.get("detail", {}))


def _rotation_check(*, rotation_applied: bool, mean_rotated_w: float, weight: float) -> dict[str, Any]:
    if not rotation_applied:
        return _matrix_item(name="rotation", status="attention", normalized_score=65.0, weight=weight, reason="rotation fallback was used", value=mean_rotated_w)
    if abs(mean_rotated_w) > 0.08:
        return _matrix_item(name="rotation", status="attention", normalized_score=60.0, weight=weight, reason=f"rotated mean w is not close to zero ({mean_rotated_w:.3f} m/s)", value=mean_rotated_w)
    return _matrix_item(name="rotation", status="pass", normalized_score=100.0, weight=weight, reason="rotation behaved as expected", value=mean_rotated_w)


def _matrix_item(
    *,
    name: str,
    status: str,
    normalized_score: float,
    weight: float,
    reason: str,
    value: Any | None = None,
    issues: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "normalized_score": float(normalized_score),
        "weight": float(weight),
        "reason": reason,
        "value": value,
        "issues": list(issues or []),
        "detail": dict(detail or {}),
    }


def _grade_from_score(score: float) -> str:
    for threshold, label in GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "C"


def _describe_issue(issue: str) -> str:
    mapping = {
        "empty_window": "window has no usable samples",
        "discontinuous_data": "timestamp continuity is poor",
        "co2_ppm_missing": "CO2 series is missing",
        "h2o_mmol_missing": "H2O series is missing",
        "pressure_kpa_missing": "pressure series is missing",
        "w_missing": "vertical wind is missing",
        "co2_ppm_constant": "CO2 series is constant",
        "h2o_mmol_constant": "H2O series is constant",
        "pressure_kpa_constant": "pressure series is constant",
        "temp_c_constant": "temperature series is constant",
        "w_constant": "vertical wind is constant",
        "co2_ppm_insufficient": "CO2 valid sample count is insufficient",
        "h2o_mmol_insufficient": "H2O valid sample count is insufficient",
        "pressure_kpa_insufficient": "pressure valid sample count is insufficient",
        "temp_c_insufficient": "temperature valid sample count is insufficient",
        "w_insufficient": "vertical wind valid sample count is insufficient",
        "co2_ppm_skewness": "CO2 distribution is highly skewed",
        "h2o_mmol_skewness": "H2O distribution is highly skewed",
        "w_skewness": "vertical wind distribution is highly skewed",
        "co2_ppm_kurtosis": "CO2 distribution has heavy tails",
        "h2o_mmol_kurtosis": "H2O distribution has heavy tails",
        "w_kurtosis": "vertical wind distribution has heavy tails",
    }
    if issue.endswith("_spike"):
        return f"{issue[:-6].replace('_', ' ')} contains spike values"
    if issue.endswith("_dropout"):
        return f"{issue[:-8].replace('_', ' ')} contains dropout/flat segments"
    if issue.endswith("_absolute_limit"):
        return f"{issue[:-15].replace('_', ' ')} exceeds absolute limits"
    if issue.endswith("_discontinuity"):
        return f"{issue[:-14].replace('_', ' ')} contains abrupt discontinuity"
    if issue.endswith("_skewness"):
        return f"{issue[:-9].replace('_', ' ')} distribution is highly skewed"
    if issue.endswith("_kurtosis"):
        return f"{issue[:-9].replace('_', ' ')} distribution has heavy tails"
    return mapping.get(issue, issue.replace("_", " "))
