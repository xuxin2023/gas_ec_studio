from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import threading
import time
from typing import Any


def has_daemon_telemetry_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in ("daemon_telemetry", "hardware_telemetry")):
        return True
    smartflux = config.get("smartflux_runtime", {})
    return isinstance(smartflux, dict) and isinstance(smartflux.get("daemon_telemetry"), dict) and bool(smartflux.get("daemon_telemetry"))


def extract_daemon_telemetry_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("daemon_telemetry", "hardware_telemetry"):
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    smartflux = config.get("smartflux_runtime", {})
    if isinstance(smartflux, dict):
        telemetry = smartflux.get("daemon_telemetry", {})
        if isinstance(telemetry, dict):
            merged.update(telemetry)
    merged.setdefault("enabled", True)
    merged.setdefault("profile_id", "daemon_telemetry_v1")
    merged.setdefault("max_ptp_offset_ns", 1_000_000.0)
    merged.setdefault("max_gps_jitter_ns", 1_000_000.0)
    merged.setdefault("max_supervisor_restarts", 3)
    merged.setdefault("require_supervisor_running", False)
    merged.setdefault("require_ptp_lock", False)
    merged.setdefault("require_gps_lock", False)
    merged.setdefault("require_hardware_watchdog", False)
    return merged


def build_daemon_telemetry_artifact(
    *,
    config: dict[str, Any],
    runtime_root: Path | str | None = None,
    service_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    telemetry_config = extract_daemon_telemetry_config(config)
    if not _truthy(telemetry_config.get("enabled", True)):
        return {
            "artifact_type": "daemon_telemetry",
            "status": "disabled",
            "profile_id": str(telemetry_config.get("profile_id", "daemon_telemetry_v1")),
            "checks": [],
            "provenance": "Daemon telemetry disabled by configuration.",
        }

    root = Path(runtime_root or Path.cwd())
    process_telemetry = _process_telemetry(runtime_root=root)
    supervisor = _supervisor_status(telemetry_config)
    ptp_servo = parse_ptp_servo_log(_optional_path(telemetry_config.get("ptp_servo_log") or telemetry_config.get("ptp_log")))
    gps_pps = parse_gps_pps_log(_optional_path(telemetry_config.get("gps_pps_log") or telemetry_config.get("gps_log")))
    hardware_watchdog = parse_hardware_watchdog_log(
        _optional_path(telemetry_config.get("hardware_watchdog_log") or telemetry_config.get("watchdog_log"))
    )
    checks = _build_checks(
        telemetry_config=telemetry_config,
        supervisor=supervisor,
        ptp_servo=ptp_servo,
        gps_pps=gps_pps,
        hardware_watchdog=hardware_watchdog,
    )
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    return {
        "artifact_type": "daemon_telemetry",
        "status": status,
        "profile_id": str(telemetry_config.get("profile_id", "daemon_telemetry_v1")),
        "collected_at": datetime.now().isoformat(),
        "runtime_root": str(root),
        "service_id": str((service_config or {}).get("service_id", "")),
        "process_telemetry": process_telemetry,
        "supervisor": supervisor,
        "ptp_servo": ptp_servo,
        "gps_pps": gps_pps,
        "hardware_watchdog": hardware_watchdog,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _recommended_actions(checks),
        "provenance": (
            "Daemon telemetry v1 parses configured supervisor, PTP servo, GPS PPS, and hardware watchdog logs "
            "and samples process-level telemetry for SmartFlux-style runtime audit."
        ),
        "limitations": [
            "The artifact parses text/JSON telemetry supplied by the runtime host; it does not install or control an OS daemon.",
            "Hardware watchdog kicking and system reboot control still require platform-specific supervisor integration.",
        ],
    }


def parse_ptp_servo_log(path: Path | None) -> dict[str, Any]:
    lines = _read_lines(path)
    offsets: list[float] = []
    states: list[str] = []
    for line in lines:
        offsets.extend(_extract_metric_values(line, names=("master offset", "offset"), default_unit="ns"))
        state = _extract_state(line)
        if state:
            states.append(state)
    latest_state = states[-1] if states else "not_reported"
    latest_offset = offsets[-1] if offsets else None
    locked = latest_state.lower() in {"s2", "locked", "lock", "synced", "synchronized"}
    return {
        "artifact_type": "ptp_servo_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("locked" if locked else "unlocked")),
        "line_count": len(lines),
        "sample_count": len(offsets),
        "latest_state": latest_state,
        "locked": locked,
        "latest_offset_ns": latest_offset,
        "max_abs_offset_ns": max((abs(value) for value in offsets), default=None),
        "provenance": "Parsed PTP servo text log for offset and lock-state evidence.",
    }


def parse_gps_pps_log(path: Path | None) -> dict[str, Any]:
    lines = _read_lines(path)
    offsets: list[float] = []
    jitters: list[float] = []
    lock_states: list[bool] = []
    for line in lines:
        offsets.extend(_extract_metric_values(line, names=("offset", "offset_ns", "pps offset"), default_unit="ns"))
        jitters.extend(_extract_metric_values(line, names=("jitter", "jitter_ns"), default_unit="ns"))
        lock = _extract_lock_bool(line)
        if lock is not None:
            lock_states.append(lock)
    latest_lock = lock_states[-1] if lock_states else False
    return {
        "artifact_type": "gps_pps_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("locked" if latest_lock else "unlocked")),
        "line_count": len(lines),
        "sample_count": max(len(offsets), len(jitters), len(lock_states)),
        "locked": latest_lock,
        "latest_offset_ns": offsets[-1] if offsets else None,
        "latest_jitter_ns": jitters[-1] if jitters else None,
        "max_abs_offset_ns": max((abs(value) for value in offsets), default=None),
        "max_jitter_ns": max(jitters, default=None),
        "provenance": "Parsed GPS PPS text log for lock, offset, and jitter evidence.",
    }


def parse_hardware_watchdog_log(path: Path | None) -> dict[str, Any]:
    lines = _read_lines(path)
    kick_count = 0
    timeout_count = 0
    reboot_count = 0
    armed_count = 0
    disarmed_count = 0
    latest_event = ""
    for line in lines:
        lowered = line.lower()
        if "kick" in lowered or "keepalive" in lowered:
            kick_count += 1
            latest_event = "kick"
        if "timeout" in lowered or "expired" in lowered:
            timeout_count += 1
            latest_event = "timeout"
        if "reboot" in lowered or "reset" in lowered:
            reboot_count += 1
            latest_event = "reboot"
        if "disarmed" in lowered or "disabled" in lowered:
            disarmed_count += 1
            latest_event = "disarmed"
        elif "armed" in lowered or "enabled" in lowered:
            armed_count += 1
            latest_event = "armed"
    active = bool(kick_count or armed_count) and timeout_count == 0
    return {
        "artifact_type": "hardware_watchdog_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("active" if active else "fault")),
        "line_count": len(lines),
        "kick_count": kick_count,
        "timeout_count": timeout_count,
        "reboot_count": reboot_count,
        "armed_count": armed_count,
        "disarmed_count": disarmed_count,
        "latest_event": latest_event or "not_reported",
        "provenance": "Parsed hardware watchdog text log for kick, timeout, reboot, and armed-state events.",
    }


def _build_checks(
    *,
    telemetry_config: dict[str, Any],
    supervisor: dict[str, Any],
    ptp_servo: dict[str, Any],
    gps_pps: dict[str, Any],
    hardware_watchdog: dict[str, Any],
) -> list[dict[str, Any]]:
    max_ptp_offset = _float_first(telemetry_config.get("max_ptp_offset_ns"), default=1_000_000.0)
    max_gps_jitter = _float_first(telemetry_config.get("max_gps_jitter_ns"), default=1_000_000.0)
    max_restarts = int(_float_first(telemetry_config.get("max_supervisor_restarts"), default=3.0))
    require_supervisor = _truthy(telemetry_config.get("require_supervisor_running", False))
    require_ptp = _truthy(telemetry_config.get("require_ptp_lock", False))
    require_gps = _truthy(telemetry_config.get("require_gps_lock", False))
    require_watchdog = _truthy(telemetry_config.get("require_hardware_watchdog", False))
    checks = [
        _check(
            "supervisor_state",
            supervisor.get("state") in {"running", "active", "ok"} if require_supervisor else supervisor.get("state") not in {"failed", "crashed"},
            measured=supervisor.get("state", ""),
            threshold="running/active" if require_supervisor else "not failed",
            severity="fail" if require_supervisor else "warn",
            failure_message="Runtime supervisor is not in an acceptable state.",
        ),
        _check(
            "supervisor_restarts",
            int(supervisor.get("restart_count", 0) or 0) <= max_restarts,
            measured=supervisor.get("restart_count", 0),
            threshold=f"<={max_restarts}",
            severity="warn",
            failure_message="Supervisor restart count exceeds telemetry policy.",
        ),
        _check(
            "ptp_lock",
            bool(ptp_servo.get("locked")) if require_ptp else ptp_servo.get("status") not in {"unlocked"},
            measured=ptp_servo.get("status", ""),
            threshold="locked" if require_ptp else "not explicitly unlocked",
            severity="fail" if require_ptp else "warn",
            failure_message="PTP servo is not locked.",
        ),
        _check(
            "ptp_offset",
            _within_abs_threshold(ptp_servo.get("max_abs_offset_ns"), max_ptp_offset, missing_ok=not require_ptp),
            measured=ptp_servo.get("max_abs_offset_ns"),
            threshold=f"<={max_ptp_offset} ns",
            severity="fail" if require_ptp else "warn",
            failure_message="PTP servo offset exceeds telemetry threshold.",
        ),
        _check(
            "gps_pps_lock",
            bool(gps_pps.get("locked")) if require_gps else gps_pps.get("status") not in {"unlocked"},
            measured=gps_pps.get("status", ""),
            threshold="locked" if require_gps else "not explicitly unlocked",
            severity="fail" if require_gps else "warn",
            failure_message="GPS PPS is not locked.",
        ),
        _check(
            "gps_pps_jitter",
            _within_abs_threshold(gps_pps.get("max_jitter_ns"), max_gps_jitter, missing_ok=not require_gps),
            measured=gps_pps.get("max_jitter_ns"),
            threshold=f"<={max_gps_jitter} ns",
            severity="fail" if require_gps else "warn",
            failure_message="GPS PPS jitter exceeds telemetry threshold.",
        ),
        _check(
            "hardware_watchdog",
            hardware_watchdog.get("status") == "active" if require_watchdog else hardware_watchdog.get("status") not in {"fault"},
            measured=hardware_watchdog.get("status", ""),
            threshold="active" if require_watchdog else "not fault",
            severity="fail" if require_watchdog else "warn",
            failure_message="Hardware watchdog is not active or reported a timeout/reboot fault.",
        ),
    ]
    return checks


def _supervisor_status(config: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    path = _optional_path(config.get("supervisor_status_file") or config.get("supervisor_file"))
    if path and path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {"state": "parse_error", "source_file": str(path)}
    inline = config.get("supervisor_status", {})
    if isinstance(inline, dict):
        payload.update(inline)
    state = str(payload.get("state") or payload.get("status") or ("not_configured" if not payload else "unknown")).strip().lower()
    restart_count = _int_first(payload.get("restart_count"), payload.get("restarts"), default=0)
    return {
        "artifact_type": "supervisor_status",
        "source_file": str(path or payload.get("source_file", "")),
        "service_name": str(payload.get("service_name", payload.get("name", ""))),
        "state": state,
        "restart_count": restart_count,
        "last_exit_code": payload.get("last_exit_code", payload.get("exit_code", "")),
        "provenance": "Supervisor status loaded from configured JSON/status payload.",
    }


def _process_telemetry(*, runtime_root: Path) -> dict[str, Any]:
    rss_mb = _process_rss_mb()
    disk_free_mb = None
    try:
        usage = shutil.disk_usage(runtime_root)
        disk_free_mb = round(float(usage.free) / (1024.0 * 1024.0), 3)
    except OSError:
        pass
    return {
        "artifact_type": "process_telemetry",
        "pid": os.getpid(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "process_cpu_seconds": round(time.process_time(), 6),
        "process_memory_rss_mb": rss_mb,
        "thread_count": threading.active_count(),
        "runtime_root": str(runtime_root),
        "disk_free_mb": disk_free_mb,
    }


def _process_rss_mb() -> float | None:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return round(float(counters.WorkingSetSize) / (1024.0 * 1024.0), 3)
        except Exception:
            return None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_kb = float(usage.ru_maxrss)
        if rss_kb > 1024.0 * 1024.0:
            rss_kb = rss_kb / 1024.0
        return round(rss_kb / 1024.0, 3)
    except Exception:
        return None


def _read_lines(path: Path | None) -> list[str]:
    if path is None or not path.exists() or not path.is_file():
        return []
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def _extract_metric_values(line: str, *, names: tuple[str, ...], default_unit: str) -> list[float]:
    values: list[float] = []
    escaped = "|".join(re.escape(name) for name in names)
    pattern = re.compile(rf"(?:{escaped})\s*[=:]?\s*([-+]?\d+(?:\.\d+)?)(?:\s*(ns|us|µs|ms|s)\b)?", re.IGNORECASE)
    for match in pattern.finditer(line):
        unit = (match.group(2) or default_unit).lower()
        value = float(match.group(1))
        values.append(_to_ns(value, unit))
    return values


def _extract_state(line: str) -> str:
    match = re.search(r"\b(?:state|servo_state)\s*[=:]?\s*([A-Za-z0-9_+-]+)", line, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    lowered = line.lower()
    if " s2 " in f" {lowered} " or "locked" in lowered or "synchronized" in lowered:
        return "locked"
    if "unlocked" in lowered or "fault" in lowered:
        return "unlocked"
    return ""


def _extract_lock_bool(line: str) -> bool | None:
    match = re.search(r"\b(?:lock|locked|pps_lock)\s*[=:]?\s*(true|false|yes|no|1|0|locked|unlocked)", line, flags=re.IGNORECASE)
    if not match:
        lowered = line.lower()
        if "locked" in lowered and "unlocked" not in lowered:
            return True
        if "unlocked" in lowered or "lost lock" in lowered:
            return False
        return None
    value = match.group(1).strip().lower()
    return value in {"true", "yes", "1", "locked"}


def _to_ns(value: float, unit: str) -> float:
    if unit in {"s", "sec", "second", "seconds"}:
        return value * 1_000_000_000.0
    if unit == "ms":
        return value * 1_000_000.0
    if unit in {"us", "µs"}:
        return value * 1_000.0
    return value


def _optional_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _within_abs_threshold(value: Any, threshold: float, *, missing_ok: bool) -> bool:
    parsed = _optional_float(value)
    if parsed is None:
        return missing_ok
    return abs(parsed) <= threshold


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
        "message": "Daemon telemetry check passed." if passed else failure_message,
    }


def _recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id.startswith("ptp"):
            actions.append("Inspect PTP servo lock state, grandmaster selection, and network timing path.")
        elif check_id.startswith("gps"):
            actions.append("Inspect GPS PPS lock, antenna signal, and PPS jitter source.")
        elif check_id == "hardware_watchdog":
            actions.append("Review hardware watchdog keepalive, timeout, and reboot logs before unattended delivery.")
        elif check_id.startswith("supervisor"):
            actions.append("Inspect OS supervisor state and restart history.")
        else:
            actions.append(f"Review daemon telemetry check {check_id}.")
    return list(dict.fromkeys(actions))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "enabled", "on", "locked", "active"}


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


def _int_first(*values: Any, default: int) -> int:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return int(parsed)
    return int(default)
