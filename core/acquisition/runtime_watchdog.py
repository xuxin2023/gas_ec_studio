from __future__ import annotations

from datetime import datetime
from typing import Any

from models.hf_models import NormalizedHFFrame


def extract_runtime_profile_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("runtime_profile", "watchdog", "smartflux_runtime"):
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    merged.setdefault("enabled", True)
    merged.setdefault("profile_id", "headless_watchdog_v1")
    merged.setdefault("deployment_mode", "headless_batch")
    merged.setdefault("restart_policy", "manual_review")
    merged.setdefault("watchdog_interval_s", 60.0)
    return merged


def build_runtime_watchdog_manifest(
    *,
    batch_id: str,
    config: dict[str, Any],
    rows: list[NormalizedHFFrame],
    rp_result: Any,
    spectral_result: Any,
    clock_sync_summary: dict[str, Any] | None,
    raw_import_summary: dict[str, Any] | None,
    network_validation: dict[str, Any] | None,
    run_started_at: datetime | None = None,
    run_completed_at: datetime | None = None,
    elapsed_ms: float | None = None,
) -> dict[str, Any]:
    profile = extract_runtime_profile_config(config)
    if not _truthy(profile.get("enabled", True)):
        return {
            "artifact_type": "runtime_watchdog",
            "status": "disabled",
            "profile_id": str(profile.get("profile_id", "headless_watchdog_v1")),
            "deployment_mode": str(profile.get("deployment_mode", "headless_batch")),
            "batch_id": batch_id,
            "checks": [],
            "recommended_actions": [],
            "provenance": "Runtime watchdog disabled by configuration.",
        }

    started_at = run_started_at or (rows[0].timestamp if rows else datetime(2000, 1, 1))
    completed_at = run_completed_at or started_at
    expected_sample_hz = _float_first(
        profile.get("expected_sample_hz"),
        config.get("sample_hz"),
        _nested(config, "steps", "window_sampling", "sample_hz"),
        default=0.0,
    )
    inferred = _infer_timing(rows)
    inferred_sample_hz = inferred["sample_hz"]
    if expected_sample_hz <= 0.0:
        expected_sample_hz = inferred_sample_hz
    max_gap_threshold = _float_first(
        profile.get("max_gap_seconds"),
        profile.get("max_allowed_gap_s"),
        default=max(1.0, 3.0 / max(expected_sample_hz or inferred_sample_hz or 1.0, 1e-9)),
    )
    sample_rate_tolerance = _float_first(profile.get("sample_rate_tolerance_fraction"), default=0.05)
    min_input_rows = int(_float_first(profile.get("min_input_rows"), default=1.0))
    min_window_count = int(_float_first(profile.get("min_window_count"), default=1.0))
    max_runtime_ms = _optional_float(profile.get("max_runtime_ms"))
    require_clock_sync = _truthy(profile.get("require_clock_sync", False))
    require_network_pass = _truthy(profile.get("require_network_pass", False))

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "input_rows",
            len(rows) >= min_input_rows,
            measured=len(rows),
            threshold=f">={min_input_rows}",
            severity="fail",
            message="High-frequency input row count is sufficient.",
            failure_message="High-frequency input row count is below runtime threshold.",
        )
    )
    monotonic = all(rows[index].timestamp <= rows[index + 1].timestamp for index in range(max(0, len(rows) - 1)))
    checks.append(
        _check(
            "timestamp_monotonic",
            monotonic,
            measured="monotonic" if monotonic else "out_of_order",
            threshold="nondecreasing acquisition timestamps",
            severity="fail",
            message="Input timestamps are monotonic after clock normalization.",
            failure_message="Input timestamps are not monotonic; sort or repair acquisition timestamps before daemonized processing.",
        )
    )
    if expected_sample_hz > 0.0 and inferred_sample_hz > 0.0:
        rel_error = abs(inferred_sample_hz - expected_sample_hz) / max(expected_sample_hz, 1e-9)
        sample_rate_ok = rel_error <= sample_rate_tolerance
    else:
        rel_error = None
        sample_rate_ok = False
    checks.append(
        _check(
            "sample_rate",
            sample_rate_ok,
            measured=round(inferred_sample_hz, 6) if inferred_sample_hz else None,
            threshold={"expected_hz": expected_sample_hz, "tolerance_fraction": sample_rate_tolerance},
            severity="warn",
            message="Inferred acquisition sample rate matches runtime profile.",
            failure_message="Inferred acquisition sample rate deviates from runtime profile.",
            detail={"relative_error": rel_error},
        )
    )
    checks.append(
        _check(
            "max_gap_seconds",
            inferred["max_gap_seconds"] <= max_gap_threshold if rows else False,
            measured=round(float(inferred["max_gap_seconds"]), 9),
            threshold=f"<={max_gap_threshold}",
            severity="fail",
            message="No timestamp gap exceeded watchdog threshold.",
            failure_message="A timestamp gap exceeded watchdog threshold.",
        )
    )
    clock_status = str((clock_sync_summary or {}).get("status", "disabled"))
    checks.append(
        _check(
            "clock_sync",
            (clock_status == "applied") if require_clock_sync else clock_status in {"applied", "disabled", "no_rows"},
            measured=clock_status,
            threshold="applied" if require_clock_sync else "tracked",
            severity="fail" if require_clock_sync else "warn",
            message="Clock synchronization status satisfies runtime policy.",
            failure_message="Runtime profile requires clock synchronization, but it was not applied.",
        )
    )
    rp_count = len(getattr(rp_result, "windows", []) or [])
    spectral_count = len(getattr(spectral_result, "windows", []) or [])
    checks.append(
        _check(
            "rp_window_generation",
            rp_count >= min_window_count,
            measured=rp_count,
            threshold=f">={min_window_count}",
            severity="fail",
            message="RP windows were generated.",
            failure_message="RP window generation did not meet watchdog threshold.",
        )
    )
    checks.append(
        _check(
            "spectral_window_generation",
            spectral_count >= min_window_count,
            measured=spectral_count,
            threshold=f">={min_window_count}",
            severity="fail",
            message="FCC/spectral windows were generated.",
            failure_message="FCC/spectral window generation did not meet watchdog threshold.",
        )
    )
    checks.append(
        _check(
            "window_count_alignment",
            rp_count == spectral_count,
            measured={"rp": rp_count, "spectral": spectral_count},
            threshold="rp_window_count == spectral_window_count",
            severity="warn",
            message="RP and FCC window counts are aligned.",
            failure_message="RP and FCC window counts differ.",
        )
    )
    network_status = str((network_validation or {}).get("validation_status", "not_requested"))
    network_ok = network_status in {"pass", "not_requested", ""}
    checks.append(
        _check(
            "network_validation",
            network_ok if require_network_pass else network_status not in {"artifact_missing"},
            measured=network_status,
            threshold="pass" if require_network_pass else "not artifact_missing",
            severity="fail" if require_network_pass else "warn",
            message="Network validation status satisfies runtime policy.",
            failure_message="Network validation status does not satisfy runtime policy.",
            detail={"missing_fields": list((network_validation or {}).get("missing_fields", []) or [])},
        )
    )
    if max_runtime_ms is not None:
        checks.append(
            _check(
                "runtime_elapsed_ms",
                float(elapsed_ms or 0.0) <= max_runtime_ms,
                measured=round(float(elapsed_ms or 0.0), 3),
                threshold=f"<={max_runtime_ms}",
                severity="warn",
                message="Batch runtime is within watchdog threshold.",
                failure_message="Batch runtime exceeded watchdog threshold.",
            )
        )
    checks.append(
        _check(
            "deterministic_run_ids",
            str(getattr(rp_result, "run_id", "")).startswith("rp_det_")
            and str(getattr(spectral_result, "run_id", "")).startswith("spectral_det_"),
            measured={"rp_run_id": getattr(rp_result, "run_id", ""), "spectral_run_id": getattr(spectral_result, "run_id", "")},
            threshold="rp_det_* and spectral_det_*",
            severity="warn",
            message="Headless run IDs are deterministic.",
            failure_message="Headless run IDs are not deterministic.",
        )
    )

    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    return {
        "artifact_type": "runtime_watchdog",
        "status": status,
        "profile_id": str(profile.get("profile_id", "headless_watchdog_v1")),
        "deployment_mode": str(profile.get("deployment_mode", "headless_batch")),
        "restart_policy": str(profile.get("restart_policy", "manual_review")),
        "watchdog_interval_s": _float_first(profile.get("watchdog_interval_s"), default=60.0),
        "batch_id": batch_id,
        "run_started_at": started_at.isoformat(),
        "run_completed_at": completed_at.isoformat(),
        "elapsed_ms": round(float(elapsed_ms or 0.0), 3),
        "check_count": len(checks),
        "fail_count": fail_count,
        "warn_count": warn_count,
        "checks": checks,
        "recommended_actions": _recommended_actions(checks),
        "input_summary": {
            "row_count": len(rows),
            "first_timestamp": rows[0].timestamp.isoformat() if rows else "",
            "last_timestamp": rows[-1].timestamp.isoformat() if rows else "",
            "inferred_sample_hz": inferred_sample_hz,
            "max_gap_seconds": inferred["max_gap_seconds"],
        },
        "raw_import_summary": dict(raw_import_summary or {}),
        "clock_sync_summary": dict(clock_sync_summary or {}),
        "network_validation_summary": dict(network_validation or {}),
        "provenance": (
            "Runtime watchdog v1 evaluates headless batch health after shared clock normalization "
            "and before delivery/export handoff."
        ),
        "limitations": [
            "This is a software watchdog manifest, not an embedded process supervisor.",
            "Hardware reboot and watchdog kick control remain future SmartFlux-hardening work; daemon_telemetry supplies optional PTP/GPS/watchdog log provenance.",
        ],
    }


def attach_runtime_watchdog(run_result: Any, watchdog: dict[str, Any]) -> None:
    if isinstance(getattr(run_result, "summary", None), dict):
        run_result.summary["runtime_watchdog_summary"] = dict(watchdog)
        run_result.summary["runtime_watchdog_status"] = watchdog.get("status", "")
    artifacts = getattr(run_result, "artifacts", None)
    if isinstance(artifacts, dict):
        artifacts["runtime_watchdog"] = dict(watchdog)
    for window in list(getattr(run_result, "windows", []) or []):
        diagnostics = getattr(window, "diagnostics", None)
        if not isinstance(diagnostics, dict):
            continue
        diagnostics["runtime_watchdog_status"] = watchdog.get("status", "")
        diagnostics["runtime_watchdog_profile"] = watchdog.get("profile_id", "")
        diagnostics["runtime_watchdog_fail_count"] = watchdog.get("fail_count", 0)
        diagnostics["runtime_watchdog_warn_count"] = watchdog.get("warn_count", 0)
        diagnostics["runtime_watchdog_detail"] = {
            "artifact_type": watchdog.get("artifact_type", "runtime_watchdog"),
            "status": watchdog.get("status", ""),
            "profile_id": watchdog.get("profile_id", ""),
            "deployment_mode": watchdog.get("deployment_mode", ""),
            "restart_policy": watchdog.get("restart_policy", ""),
            "check_count": watchdog.get("check_count", 0),
            "fail_count": watchdog.get("fail_count", 0),
            "warn_count": watchdog.get("warn_count", 0),
            "recommended_actions": list(watchdog.get("recommended_actions", []) or []),
            "provenance": watchdog.get("provenance", ""),
        }


def _infer_timing(rows: list[NormalizedHFFrame]) -> dict[str, float]:
    if len(rows) < 2:
        return {"sample_hz": 0.0, "median_dt_seconds": 0.0, "max_gap_seconds": 0.0}
    deltas = [
        (rows[index + 1].timestamp - rows[index].timestamp).total_seconds()
        for index in range(len(rows) - 1)
    ]
    positive = sorted(delta for delta in deltas if delta > 0.0)
    if not positive:
        return {"sample_hz": 0.0, "median_dt_seconds": 0.0, "max_gap_seconds": max(deltas) if deltas else 0.0}
    median_dt = positive[len(positive) // 2]
    return {
        "sample_hz": round(1.0 / median_dt, 9) if median_dt > 0.0 else 0.0,
        "median_dt_seconds": round(median_dt, 9),
        "max_gap_seconds": round(max(positive), 9),
    }


def _check(
    check_id: str,
    passed: bool,
    *,
    measured: Any,
    threshold: Any,
    severity: str,
    message: str,
    failure_message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = "pass" if passed else ("fail" if severity == "fail" else "warn")
    return {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "measured": measured,
        "threshold": threshold,
        "message": message if passed else failure_message,
        "detail": detail or {},
    }


def _recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id == "max_gap_seconds":
            actions.append("Inspect acquisition gaps, logger buffering, and upstream clock corrections.")
        elif check_id == "clock_sync":
            actions.append("Enable GPS/PTP clock_sync or relax require_clock_sync for non-SmartFlux replay batches.")
        elif check_id in {"rp_window_generation", "spectral_window_generation"}:
            actions.append("Verify sample_hz, block_minutes, and minimum input duration.")
        elif check_id == "network_validation":
            actions.append("Resolve network exporter missing fields or disable require_network_pass for draft runs.")
        elif check_id == "sample_rate":
            actions.append("Check runtime profile expected_sample_hz against inferred high-frequency timestamps.")
        else:
            actions.append(f"Review watchdog check {check_id}.")
    return list(dict.fromkeys(actions))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "enabled", "on"}


def _float_first(*values: Any, default: float) -> float:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return float(default)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
