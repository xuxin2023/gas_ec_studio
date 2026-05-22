from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
from typing import Any

from core.acquisition.daemon_telemetry import build_daemon_telemetry_artifact, has_daemon_telemetry_config
from models.hf_models import NormalizedHFFrame


def extract_runtime_service_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("runtime_service", "embedded_runtime", "smartflux_runtime"):
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    merged.setdefault("enabled", True)
    merged.setdefault("service_id", "embedded_runtime_service_v1")
    merged.setdefault("deployment_mode", "supervised_headless")
    merged.setdefault("restart_policy", "retry_failed_batch_once")
    merged.setdefault("heartbeat_interval_s", 60.0)
    merged.setdefault("max_consecutive_failures", 3)
    merged.setdefault("quarantine_failed_watchdog", True)
    merged.setdefault("disk_warning_free_mb", 512.0)
    merged.setdefault("max_queue_depth", 24)
    return merged


def build_host_telemetry(
    *,
    runtime_root: Path | str | None,
    queue_depth: int,
    service_config: dict[str, Any],
) -> dict[str, Any]:
    root = Path(runtime_root or Path.cwd())
    try:
        usage = shutil.disk_usage(root)
        free_mb = round(float(usage.free) / (1024.0 * 1024.0), 3)
        total_mb = round(float(usage.total) / (1024.0 * 1024.0), 3)
    except OSError:
        free_mb = None
        total_mb = None
    disk_threshold = _float_first(service_config.get("disk_warning_free_mb"), default=512.0)
    max_queue_depth = int(_float_first(service_config.get("max_queue_depth"), default=24.0))
    disk_status = "unknown" if free_mb is None else ("warn" if free_mb < disk_threshold else "ok")
    queue_status = "warn" if queue_depth > max_queue_depth else "ok"
    return {
        "artifact_type": "runtime_host_telemetry",
        "sampled_at": datetime.now().isoformat(),
        "runtime_root": str(root),
        "disk_free_mb": free_mb,
        "disk_total_mb": total_mb,
        "disk_warning_free_mb": disk_threshold,
        "disk_status": disk_status,
        "queue_depth": queue_depth,
        "max_queue_depth": max_queue_depth,
        "queue_status": queue_status,
        "provenance": "Host telemetry collected with Python standard-library disk usage and service queue counters.",
        "limitations": [
            "Detailed CPU load, hardware watchdog control, and OS supervisor state require daemon_telemetry or platform-specific integration.",
        ],
    }


def run_runtime_service_batches(
    *,
    config: dict[str, Any],
    metadata: Any,
    batches: list[Any],
    runtime_root: Path | str | None = None,
    data_source_prefix: str = "runtime_service",
) -> dict[str, Any]:
    from core.headless_batch_runner import run_headless_batch

    service_config = extract_runtime_service_config(config)
    service_started_at = datetime.now()
    service_id = str(service_config.get("service_id", "embedded_runtime_service_v1"))
    service_run_id = _service_run_id(service_id=service_id, started_at=service_started_at, batch_count=len(batches))
    if not _truthy(service_config.get("enabled", True)):
        return {
            "artifact_type": "runtime_service",
            "status": "disabled",
            "service_id": service_id,
            "service_run_id": service_run_id,
            "started_at": service_started_at.isoformat(),
            "completed_at": service_started_at.isoformat(),
            "batch_count": len(batches),
            "heartbeats": [],
            "batch_records": [],
            "quarantine_records": [],
            "restart_records": [],
            "provenance": "Runtime service disabled by configuration.",
        }

    restart_policy = str(service_config.get("restart_policy", "retry_failed_batch_once")).strip().lower()
    max_attempts = 2 if restart_policy in {"retry_failed_batch_once", "retry_once", "restart_batch_once"} else 1
    max_consecutive_failures = int(_float_first(service_config.get("max_consecutive_failures"), default=3.0))
    quarantine_failed_watchdog = _truthy(service_config.get("quarantine_failed_watchdog", True))
    batch_records: list[dict[str, Any]] = []
    heartbeats: list[dict[str, Any]] = []
    quarantine_records: list[dict[str, Any]] = []
    restart_records: list[dict[str, Any]] = []
    successful_results: list[dict[str, Any]] = []
    consecutive_failures = 0
    max_observed_consecutive_failures = 0

    for index, batch_input in enumerate(batches):
        sequence = index + 1
        input_id = _input_id(batch_input=batch_input, sequence=sequence)
        time_range = _input_time_range(batch_input=batch_input)
        telemetry_before = build_host_telemetry(
            runtime_root=runtime_root,
            queue_depth=max(0, len(batches) - index - 1),
            service_config=service_config,
        )
        record: dict[str, Any] = {
            "sequence": sequence,
            "input_id": input_id,
            "time_range": time_range,
            "attempt_count": 0,
            "status": "pending",
            "batch_id": "",
            "watchdog_status": "",
            "quarantined": False,
            "started_at": datetime.now().isoformat(),
            "completed_at": "",
            "error": "",
            "telemetry_before": telemetry_before,
        }

        result: dict[str, Any] | None = None
        final_error = ""
        for attempt in range(1, max_attempts + 1):
            record["attempt_count"] = attempt
            try:
                rows = _coerce_rows(batch_input)
                result = run_headless_batch(
                    config=deepcopy(config),
                    metadata=metadata,
                    rows=rows,
                    data_source=f"{data_source_prefix}:{input_id}",
                    time_range=time_range,
                )
                watchdog = dict(result.get("runtime_watchdog_summary", {}) or {})
                watchdog_status = str(watchdog.get("status", "not_run"))
                record["batch_id"] = str(result.get("batch_id", ""))
                record["watchdog_status"] = watchdog_status
                if watchdog_status == "fail" and quarantine_failed_watchdog:
                    record["status"] = "watchdog_fail"
                    record["quarantined"] = True
                    quarantine_records.append(
                        _quarantine_record(
                            sequence=sequence,
                            input_id=input_id,
                            reason="runtime_watchdog_fail",
                            detail={"watchdog_status": watchdog_status, "batch_id": record["batch_id"]},
                        )
                    )
                    consecutive_failures += 1
                elif watchdog_status == "warning":
                    record["status"] = "warning"
                    consecutive_failures = 0
                else:
                    record["status"] = "ok"
                    consecutive_failures = 0
                successful_results.append(result)
                break
            except Exception as exc:  # noqa: BLE001 - service manifest must isolate failed batches.
                final_error = f"{type(exc).__name__}: {exc}"
                if attempt < max_attempts:
                    restart_records.append(
                        {
                            "sequence": sequence,
                            "input_id": input_id,
                            "failed_attempt": attempt,
                            "next_attempt": attempt + 1,
                            "policy": restart_policy,
                            "reason": final_error,
                            "recorded_at": datetime.now().isoformat(),
                        }
                    )
                    continue
                record["status"] = "failed"
                record["quarantined"] = True
                record["error"] = final_error
                quarantine_records.append(
                    _quarantine_record(
                        sequence=sequence,
                        input_id=input_id,
                        reason="batch_exception",
                        detail={"error": final_error, "attempts": attempt},
                    )
                )
                consecutive_failures += 1
        max_observed_consecutive_failures = max(max_observed_consecutive_failures, consecutive_failures)
        record["completed_at"] = datetime.now().isoformat()
        record["telemetry_after"] = build_host_telemetry(
            runtime_root=runtime_root,
            queue_depth=max(0, len(batches) - sequence),
            service_config=service_config,
        )
        batch_records.append(record)
        heartbeats.append(
            {
                "artifact_type": "runtime_service_heartbeat",
                "service_id": service_id,
                "service_run_id": service_run_id,
                "sequence": sequence,
                "recorded_at": record["completed_at"],
                "input_id": input_id,
                "batch_id": record["batch_id"],
                "batch_status": record["status"],
                "watchdog_status": record["watchdog_status"],
                "queue_depth": max(0, len(batches) - sequence),
                "telemetry": record["telemetry_after"],
            }
        )

    completed_at = datetime.now()
    failure_count = sum(1 for item in batch_records if item["status"] == "failed")
    watchdog_failure_count = sum(1 for item in batch_records if item["status"] == "watchdog_fail")
    warning_count = sum(1 for item in batch_records if item["status"] == "warning")
    daemon_telemetry = (
        build_daemon_telemetry_artifact(config=config, runtime_root=runtime_root, service_config=service_config)
        if has_daemon_telemetry_config(config)
        else {}
    )
    status = _service_status(
        failure_count=failure_count,
        watchdog_failure_count=watchdog_failure_count,
        warning_count=warning_count,
        max_observed_consecutive_failures=max_observed_consecutive_failures,
        max_consecutive_failures=max_consecutive_failures,
        daemon_telemetry_status=str(daemon_telemetry.get("status", "")),
    )
    manifest = {
        "artifact_type": "runtime_service",
        "status": status,
        "delivery_state": _delivery_state(status),
        "service_id": service_id,
        "service_run_id": service_run_id,
        "deployment_mode": str(service_config.get("deployment_mode", "supervised_headless")),
        "restart_policy": restart_policy,
        "heartbeat_interval_s": _float_first(service_config.get("heartbeat_interval_s"), default=60.0),
        "started_at": service_started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "elapsed_ms": round((completed_at - service_started_at).total_seconds() * 1000.0, 3),
        "batch_count": len(batches),
        "successful_batch_count": sum(1 for item in batch_records if item["status"] in {"ok", "warning", "watchdog_fail"}),
        "failure_count": failure_count,
        "watchdog_failure_count": watchdog_failure_count,
        "warning_count": warning_count,
        "max_consecutive_failures": max_consecutive_failures,
        "max_observed_consecutive_failures": max_observed_consecutive_failures,
        "latest_batch_id": next((item["batch_id"] for item in reversed(batch_records) if item.get("batch_id")), ""),
        "heartbeats": heartbeats,
        "batch_records": batch_records,
        "restart_records": restart_records,
        "quarantine_records": quarantine_records,
        "host_telemetry": heartbeats[-1]["telemetry"] if heartbeats else build_host_telemetry(runtime_root=runtime_root, queue_depth=0, service_config=service_config),
        "daemon_telemetry": daemon_telemetry,
        "daemon_telemetry_status": daemon_telemetry.get("status", ""),
        "checks": _service_checks(
            status=status,
            batch_records=batch_records,
            host_telemetry=heartbeats[-1]["telemetry"] if heartbeats else {},
            service_config=service_config,
            max_observed_consecutive_failures=max_observed_consecutive_failures,
            daemon_telemetry=daemon_telemetry,
        ),
        "provenance": (
        "Runtime service v1 executes queued headless batches, records heartbeats, isolates failed inputs, "
            "and attaches service-level health and daemon telemetry provenance to successful RP/FCC results."
        ),
        "limitations": [
            "This service wrapper is process-level Python orchestration, not an installed OS daemon.",
            "Hardware watchdog control and automatic system reboot still require platform-specific supervisor integration.",
        ],
    }
    for result in successful_results:
        attach_runtime_service_manifest(result.get("rp_result"), manifest)
        attach_runtime_service_manifest(result.get("spectral_result"), manifest)
    return {
        "service_manifest": manifest,
        "batch_results": successful_results,
        "latest_batch": successful_results[-1] if successful_results else None,
    }


def attach_runtime_service_manifest(run_result: Any, service_manifest: dict[str, Any]) -> None:
    if run_result is None:
        return
    compact = _compact_service_manifest(service_manifest)
    if isinstance(getattr(run_result, "summary", None), dict):
        run_result.summary["runtime_service_summary"] = dict(service_manifest)
        run_result.summary["runtime_service_status"] = compact["status"]
        run_result.summary["runtime_service_delivery_state"] = compact["delivery_state"]
    artifacts = getattr(run_result, "artifacts", None)
    if isinstance(artifacts, dict):
        artifacts["runtime_service"] = dict(service_manifest)
        if isinstance(service_manifest.get("daemon_telemetry"), dict) and service_manifest["daemon_telemetry"]:
            artifacts["daemon_telemetry"] = dict(service_manifest["daemon_telemetry"])
            supervisor_integration = dict(service_manifest["daemon_telemetry"].get("supervisor_integration", {}) or {})
            if isinstance(supervisor_integration.get("installable_runtime_profile"), dict) and supervisor_integration["installable_runtime_profile"]:
                artifacts["installable_runtime_profile"] = dict(supervisor_integration["installable_runtime_profile"])
    for window in list(getattr(run_result, "windows", []) or []):
        diagnostics = getattr(window, "diagnostics", None)
        if not isinstance(diagnostics, dict):
            continue
        diagnostics["runtime_service_status"] = compact["status"]
        diagnostics["runtime_service_id"] = compact["service_id"]
        diagnostics["runtime_service_run_id"] = compact["service_run_id"]
        diagnostics["runtime_service_delivery_state"] = compact["delivery_state"]
        diagnostics["runtime_service_quarantine_count"] = compact["quarantine_count"]
        diagnostics["runtime_service_restart_count"] = compact["restart_count"]
        diagnostics["runtime_service_detail"] = dict(compact)
        daemon = dict(service_manifest.get("daemon_telemetry", {}) or {})
        diagnostics["daemon_telemetry_status"] = daemon.get("status", "")
        diagnostics["supervisor_state"] = dict(daemon.get("supervisor", {}) or {}).get("state", "")
        diagnostics["ptp_lock_status"] = dict(daemon.get("ptp_servo", {}) or {}).get("status", "")
        diagnostics["gps_pps_lock_status"] = dict(daemon.get("gps_pps", {}) or {}).get("status", "")
        diagnostics["hardware_watchdog_status"] = dict(daemon.get("hardware_watchdog", {}) or {}).get("status", "")
        supervisor_integration = dict(daemon.get("supervisor_integration", {}) or {})
        install_profile = dict(supervisor_integration.get("installable_runtime_profile", {}) or {})
        diagnostics["os_supervisor_status"] = supervisor_integration.get("status", "")
        diagnostics["os_supervisor_state"] = dict(supervisor_integration.get("service_status", {}) or {}).get("state", "")
        diagnostics["watchdog_provider_status"] = dict(supervisor_integration.get("hardware_watchdog_provider", {}) or {}).get("status", "")
        diagnostics["installable_runtime_status"] = install_profile.get("status", "")
        diagnostics["installable_runtime_profile_id"] = install_profile.get("profile_id", "")
        diagnostics["installable_runtime_targets"] = list(install_profile.get("os_targets", []) or [])
        diagnostics["installable_runtime_detail"] = install_profile
        diagnostics["supervisor_integration_detail"] = supervisor_integration
        diagnostics["daemon_telemetry_detail"] = _compact_daemon_telemetry(daemon)


def _compact_service_manifest(service_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": "runtime_service",
        "status": service_manifest.get("status", ""),
        "delivery_state": service_manifest.get("delivery_state", ""),
        "service_id": service_manifest.get("service_id", ""),
        "service_run_id": service_manifest.get("service_run_id", ""),
        "deployment_mode": service_manifest.get("deployment_mode", ""),
        "restart_policy": service_manifest.get("restart_policy", ""),
        "batch_count": service_manifest.get("batch_count", 0),
        "failure_count": service_manifest.get("failure_count", 0),
        "watchdog_failure_count": service_manifest.get("watchdog_failure_count", 0),
        "warning_count": service_manifest.get("warning_count", 0),
        "quarantine_count": len(service_manifest.get("quarantine_records", []) or []),
        "restart_count": len(service_manifest.get("restart_records", []) or []),
        "latest_batch_id": service_manifest.get("latest_batch_id", ""),
        "host_telemetry": dict(service_manifest.get("host_telemetry", {}) or {}),
        "daemon_telemetry_status": dict(service_manifest.get("daemon_telemetry", {}) or {}).get("status", ""),
        "provenance": service_manifest.get("provenance", ""),
        "limitations": list(service_manifest.get("limitations", []) or []),
    }


def _compact_daemon_telemetry(daemon_telemetry: dict[str, Any]) -> dict[str, Any]:
    if not daemon_telemetry:
        return {}
    return {
        "artifact_type": "daemon_telemetry",
        "status": daemon_telemetry.get("status", ""),
        "profile_id": daemon_telemetry.get("profile_id", ""),
        "supervisor": dict(daemon_telemetry.get("supervisor", {}) or {}),
        "ptp_servo": dict(daemon_telemetry.get("ptp_servo", {}) or {}),
        "gps_pps": dict(daemon_telemetry.get("gps_pps", {}) or {}),
        "hardware_watchdog": dict(daemon_telemetry.get("hardware_watchdog", {}) or {}),
        "supervisor_integration": dict(daemon_telemetry.get("supervisor_integration", {}) or {}),
        "fail_count": daemon_telemetry.get("fail_count", 0),
        "warn_count": daemon_telemetry.get("warn_count", 0),
        "recommended_actions": list(daemon_telemetry.get("recommended_actions", []) or []),
    }


def _service_checks(
    *,
    status: str,
    batch_records: list[dict[str, Any]],
    host_telemetry: dict[str, Any],
    service_config: dict[str, Any],
    max_observed_consecutive_failures: int,
    daemon_telemetry: dict[str, Any],
) -> list[dict[str, Any]]:
    max_consecutive = int(_float_first(service_config.get("max_consecutive_failures"), default=3.0))
    return [
        _check(
            "service_status",
            status in {"pass", "warning"},
            measured=status,
            threshold="pass or warning",
            severity="fail",
            failure_message="Runtime service requires operator review before unattended delivery.",
        ),
        _check(
            "heartbeat_count",
            len(batch_records) == sum(1 for _ in batch_records),
            measured=len(batch_records),
            threshold="one heartbeat per input batch",
            severity="warn",
            failure_message="Runtime service heartbeat accounting is incomplete.",
        ),
        _check(
            "consecutive_failures",
            max_observed_consecutive_failures < max_consecutive,
            measured=max_observed_consecutive_failures,
            threshold=f"<{max_consecutive}",
            severity="fail",
            failure_message="Consecutive runtime failures exceeded service policy.",
        ),
        _check(
            "disk_free_mb",
            str(host_telemetry.get("disk_status", "unknown")) != "warn",
            measured=host_telemetry.get("disk_free_mb"),
            threshold=f">={_float_first(service_config.get('disk_warning_free_mb'), default=512.0)}",
            severity="warn",
            failure_message="Runtime root disk free space is below warning threshold.",
        ),
        _check(
            "queue_depth",
            str(host_telemetry.get("queue_status", "unknown")) != "warn",
            measured=host_telemetry.get("queue_depth"),
            threshold=f"<={int(_float_first(service_config.get('max_queue_depth'), default=24.0))}",
            severity="warn",
            failure_message="Runtime input queue depth is above warning threshold.",
        ),
        _check(
            "daemon_telemetry",
            str(daemon_telemetry.get("status", "not_configured")) not in {"fail"},
            measured=daemon_telemetry.get("status", "not_configured"),
            threshold="not fail",
            severity="fail",
            failure_message="Daemon telemetry reports a blocking supervisor/clock/watchdog fault.",
        ),
    ]


def _check(
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
        "message": "Service check passed." if passed else failure_message,
    }


def _service_status(
    *,
    failure_count: int,
    watchdog_failure_count: int,
    warning_count: int,
    max_observed_consecutive_failures: int,
    max_consecutive_failures: int,
    daemon_telemetry_status: str = "",
) -> str:
    if daemon_telemetry_status == "fail" or max_observed_consecutive_failures >= max_consecutive_failures:
        return "fail"
    if failure_count or watchdog_failure_count:
        return "degraded"
    if daemon_telemetry_status == "warning" or warning_count:
        return "warning"
    return "pass"


def _delivery_state(status: str) -> str:
    if status == "pass":
        return "ready"
    if status == "warning":
        return "ready_with_warnings"
    if status == "degraded":
        return "degraded_review_required"
    return "blocked"


def _service_run_id(*, service_id: str, started_at: datetime, batch_count: int) -> str:
    digest = hashlib.sha1(f"{service_id}|{started_at.isoformat()}|{batch_count}".encode("utf-8")).hexdigest()[:12]
    return f"runtime_service_{digest}"


def _input_id(*, batch_input: Any, sequence: int) -> str:
    if isinstance(batch_input, dict) and batch_input.get("input_id"):
        return str(batch_input["input_id"])
    return f"batch-{sequence:04d}"


def _input_time_range(*, batch_input: Any) -> str:
    if isinstance(batch_input, dict) and batch_input.get("time_range"):
        return str(batch_input["time_range"])
    return ""


def _coerce_rows(batch_input: Any) -> list[NormalizedHFFrame]:
    rows = batch_input.get("rows") if isinstance(batch_input, dict) else batch_input
    if not isinstance(rows, list) or not all(isinstance(row, NormalizedHFFrame) for row in rows):
        raise ValueError("runtime service batch rows must be a list[NormalizedHFFrame]")
    if not rows:
        raise ValueError("runtime service batch rows are empty")
    return rows


def _quarantine_record(*, sequence: int, input_id: str, reason: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "input_id": input_id,
        "reason": reason,
        "detail": detail,
        "recorded_at": datetime.now().isoformat(),
        "operator_action": "review_input_before_requeue",
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "enabled", "on"}


def _float_first(*values: Any, default: float) -> float:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)
