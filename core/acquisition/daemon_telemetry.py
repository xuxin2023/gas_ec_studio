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

from core.acquisition.supervisor_integration import build_supervisor_integration_artifact, has_supervisor_integration_config


def has_daemon_telemetry_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in ("daemon_telemetry", "hardware_telemetry")):
        return True
    if has_supervisor_integration_config(config):
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
    supervisor_integration = (
        build_supervisor_integration_artifact(config=config, runtime_root=root)
        if has_supervisor_integration_config(config)
        else {}
    )
    checks = _build_checks(
        telemetry_config=telemetry_config,
        supervisor=supervisor,
        ptp_servo=ptp_servo,
        gps_pps=gps_pps,
        hardware_watchdog=hardware_watchdog,
        supervisor_integration=supervisor_integration,
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
        "supervisor_integration": supervisor_integration,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _recommended_actions(checks),
        "provenance": (
            "Daemon telemetry v1 parses configured supervisor, PTP servo, GPS PPS, and hardware watchdog logs, "
            "samples process-level telemetry, and incorporates OS supervisor integration provider evidence."
        ),
        "limitations": [
            "The artifact parses text/JSON telemetry supplied by the runtime host; it does not install or control an OS daemon.",
            "Hardware watchdog kicking and reboot control use configured providers; direct platform service mutation is not invoked by telemetry collection.",
        ],
    }


def parse_ptp_servo_log(path: Path | None) -> dict[str, Any]:
    lines = _read_lines(path)
    offsets: list[float] = []
    states: list[str] = []
    dialects: set[str] = set()
    for line in lines:
        dialects.update(_detect_daemon_dialects(line))
        for payload in _json_payloads(line):
            dialects.add("json")
            offsets.extend(
                _json_metric_values(
                    payload,
                    keys=("master_offset", "master_offset_ns", "offset", "offset_ns", "offset_seconds", "last_offset", "system_time"),
                    default_unit="ns",
                )
            )
            state = _state_from_json(payload)
            if state:
                states.append(state)
        offsets.extend(_extract_metric_values(line, names=("master offset", "offset"), default_unit="ns"))
        offsets.extend(_extract_chrony_time_offsets(line))
        state = _extract_state(line)
        if state:
            states.append(state)
        if _chrony_line_indicates_lock(line):
            states.append("locked")
    latest_state = states[-1] if states else "not_reported"
    latest_offset = offsets[-1] if offsets else None
    locked = latest_state.lower() in {"s2", "locked", "lock", "synced", "synchronized", "synchronised", "normal"}
    return {
        "artifact_type": "ptp_servo_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("locked" if locked else "unlocked")),
        "dialect": _primary_dialect(dialects),
        "dialects": sorted(dialects),
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
    dialects: set[str] = set()
    for line in lines:
        dialects.update(_detect_daemon_dialects(line))
        for payload in _json_payloads(line):
            dialects.add("json")
            offsets.extend(
                _json_metric_values(
                    payload,
                    keys=("offset", "offset_ns", "pps_offset", "pps_offset_ns", "ept", "tdop"),
                    default_unit="ns",
                )
            )
            jitters.extend(
                _json_metric_values(
                    payload,
                    keys=("jitter", "jitter_ns", "precision", "epx", "epy"),
                    default_unit="ns",
                )
            )
            lock = _lock_from_json(payload)
            if lock is not None:
                lock_states.append(lock)
        offsets.extend(_extract_metric_values(line, names=("offset", "offset_ns", "pps offset"), default_unit="ns"))
        jitters.extend(_extract_metric_values(line, names=("jitter", "jitter_ns"), default_unit="ns"))
        jitters.extend(_extract_metric_values(line, names=("+/-", "precision"), default_unit="ns"))
        lock = _extract_gps_lock_bool(line)
        if lock is not None:
            lock_states.append(lock)
    latest_lock = lock_states[-1] if lock_states else False
    return {
        "artifact_type": "gps_pps_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("locked" if latest_lock else "unlocked")),
        "dialect": _primary_dialect(dialects),
        "dialects": sorted(dialects),
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
    provider_record_count = 0
    dialects: set[str] = set()
    latest_event = ""
    for line in lines:
        lowered = line.lower()
        dialects.update(_detect_daemon_dialects(line))
        for payload in _json_payloads(line):
            provider_record_count += 1
            dialects.add("json")
            event = str(payload.get("artifact_type") or payload.get("event") or payload.get("action") or "").lower()
            if "kick" in event or _truthy(payload.get("kick_delivered", payload.get("kick_recorded", False))):
                kick_count += 1
                latest_event = "kick"
            if "reboot" in event or _truthy(payload.get("reboot_recorded", False)):
                reboot_count += 1
                latest_event = "reboot"
            if str(payload.get("status", "")).lower() in {"timeout", "fault", "expired"}:
                timeout_count += 1
                latest_event = "timeout"
        if "watchdog=1" in lowered or "kick" in lowered or "keepalive" in lowered or "keep alive" in lowered:
            kick_count += 1
            latest_event = "kick"
        if "timeout" in lowered or "timed out" in lowered or "expired" in lowered or "watchdog failure" in lowered:
            timeout_count += 1
            latest_event = "timeout"
        if "reboot" in lowered or "reset" in lowered:
            reboot_count += 1
            latest_event = "reboot"
        if "disarmed" in lowered or "disabled" in lowered or "closed /dev/watchdog" in lowered:
            disarmed_count += 1
            latest_event = "disarmed"
        elif "armed" in lowered or "enabled" in lowered or "opened /dev/watchdog" in lowered or "watchdog device" in lowered:
            armed_count += 1
            latest_event = "armed"
    active = bool(kick_count or armed_count) and timeout_count == 0
    return {
        "artifact_type": "hardware_watchdog_log",
        "source_file": str(path or ""),
        "status": "not_configured" if path is None else ("missing" if not lines else ("active" if active else "fault")),
        "dialect": _primary_dialect(dialects),
        "dialects": sorted(dialects),
        "line_count": len(lines),
        "kick_count": kick_count,
        "timeout_count": timeout_count,
        "reboot_count": reboot_count,
        "armed_count": armed_count,
        "disarmed_count": disarmed_count,
        "provider_record_count": provider_record_count,
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
    supervisor_integration: dict[str, Any],
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
        _check(
            "supervisor_integration",
            supervisor_integration.get("status", "not_configured") not in {"fail"},
            measured=supervisor_integration.get("status", "not_configured"),
            threshold="not fail",
            severity="fail",
            failure_message="OS supervisor integration reported a blocking service/watchdog provider fault.",
        ),
    ]
    return checks


def _supervisor_status(config: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    path = _optional_path(config.get("supervisor_status_file") or config.get("supervisor_file"))
    raw_text = ""
    if path and path.exists():
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            payload = _parse_supervisor_text_status(raw_text, source_file=path)
        except OSError:
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
        "dialect": str(payload.get("dialect", "")),
        "event_count": int(payload.get("event_count", 0) or 0),
        "provenance": "Supervisor status loaded from configured JSON/status payload.",
    }


def _parse_supervisor_text_status(text: str, *, source_file: Path | None = None) -> dict[str, Any]:
    state = "unknown"
    service_name = ""
    restart_count = 0
    last_exit_code = ""
    event_count = 0
    dialects: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        event_count += 1
        lowered = stripped.lower()
        dialects.update(_detect_daemon_dialects(stripped))
        if "service_name" in lowered and ":" in stripped:
            service_name = stripped.split(":", 1)[-1].strip()
        service_match = re.search(r"\b([\w.-]+\.service)\b", stripped)
        if service_match and not service_name:
            service_name = service_match.group(1)
        if "entered the running state" in lowered or "started" in lowered or "active (running)" in lowered:
            state = "running"
        elif "entered the stopped state" in lowered or "stopped" in lowered or "inactive" in lowered:
            state = "stopped"
        elif "failed" in lowered or "crashed" in lowered or "service failed" in lowered:
            state = "failed"
        restart_match = re.search(r"(?:restart(?:_count| counter)?|nrestarts|restarts?)\D+(\d+)", stripped, flags=re.IGNORECASE)
        if restart_match:
            restart_count = max(restart_count, int(restart_match.group(1)))
        exit_match = re.search(r"(?:exit(?:_code)?|status|result)\D+(-?\d+)", stripped, flags=re.IGNORECASE)
        if exit_match:
            last_exit_code = exit_match.group(1)
    return {
        "source_file": str(source_file or ""),
        "service_name": service_name,
        "state": state,
        "restart_count": restart_count,
        "last_exit_code": last_exit_code,
        "dialect": _primary_dialect(dialects),
        "event_count": event_count,
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


def _json_payloads(line: str) -> list[dict[str, Any]]:
    stripped = line.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return []
    return [payload] if isinstance(payload, dict) else []


def _detect_daemon_dialects(line: str) -> set[str]:
    lowered = line.lower()
    dialects: set[str] = set()
    if "ptp4l" in lowered:
        dialects.add("ptp4l")
    if "phc2sys" in lowered:
        dialects.add("phc2sys")
    if "chronyd" in lowered or "chronyc" in lowered or "leap status" in lowered or "system time" in lowered:
        dialects.add("chrony")
    if "gpsd" in lowered or ('"class"' in lowered and any(token in lowered for token in ('"tpv"', '"pps"', '"sky"'))):
        dialects.add("gpsd")
    if "pps" in lowered:
        dialects.add("pps")
    if "systemd" in lowered or ".service" in lowered or "watchdog=1" in lowered:
        dialects.add("systemd_journal")
    if "service control manager" in lowered or "event id" in lowered or "entered the running state" in lowered:
        dialects.add("windows_event")
    if "watchdogd" in lowered:
        dialects.add("watchdogd")
    if "/dev/watchdog" in lowered or "softdog" in lowered:
        dialects.add("linux_watchdog")
    if stripped_starts_json(line):
        dialects.add("json")
    return dialects


def stripped_starts_json(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("{") and stripped.endswith("}")


def _primary_dialect(dialects: set[str]) -> str:
    priority = (
        "ptp4l",
        "phc2sys",
        "chrony",
        "gpsd",
        "pps",
        "systemd_journal",
        "windows_event",
        "watchdogd",
        "linux_watchdog",
        "json",
    )
    for dialect in priority:
        if dialect in dialects:
            return dialect
    return ""


def _json_metric_values(payload: dict[str, Any], *, keys: tuple[str, ...], default_unit: str) -> list[float]:
    values: list[float] = []
    wanted = {_normalize_key(key) for key in keys}
    for key, value in _flatten_json_items(payload):
        normalized = _normalize_key(key)
        if normalized not in wanted:
            continue
        parsed = _optional_float(value)
        if parsed is None:
            continue
        values.append(_to_ns(parsed, _unit_from_key(normalized, default_unit=default_unit)))
    return values


def _flatten_json_items(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(payload, dict):
        items: list[tuple[str, Any]] = []
        for key, value in payload.items():
            joined = f"{prefix}_{key}" if prefix else str(key)
            items.extend(_flatten_json_items(value, joined))
        return items
    if isinstance(payload, list):
        items = []
        for index, value in enumerate(payload):
            joined = f"{prefix}_{index}" if prefix else str(index)
            items.extend(_flatten_json_items(value, joined))
        return items
    return [(prefix, payload)]


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _unit_from_key(key: str, *, default_unit: str) -> str:
    if key in {"ept", "offset_seconds", "system_time_seconds"} or key.endswith("_seconds") or key.endswith("_s"):
        return "s"
    if key.endswith("_ms"):
        return "ms"
    if key.endswith("_us"):
        return "us"
    if key.endswith("_ns"):
        return "ns"
    return default_unit


def _state_from_json(payload: dict[str, Any]) -> str:
    for key, value in _flatten_json_items(payload):
        normalized = _normalize_key(key)
        if normalized in {"state", "servo_state", "clock_state", "leap_status", "status", "sync_state"}:
            text = str(value).strip().lower()
            if text in {"s2", "locked", "lock", "synced", "synchronized", "synchronised", "normal"}:
                return "locked"
            if text in {"unlocked", "fault", "failed", "nosync", "not_synchronised", "not_synchronized"}:
                return "unlocked"
    return ""


def _lock_from_json(payload: dict[str, Any]) -> bool | None:
    for key, value in _flatten_json_items(payload):
        normalized = _normalize_key(key)
        if normalized in {"lock", "locked", "pps_lock", "fix", "gps_fix", "synchronized", "synchronised"}:
            return _truthy(value)
        if normalized in {"mode", "fix_mode"}:
            parsed = _optional_float(value)
            if parsed is not None:
                return parsed >= 2
        if normalized == "class" and str(value).strip().upper() == "PPS":
            return True
        if normalized == "status" and str(value).strip().lower() in {"locked", "fix", "3d", "dgps"}:
            return True
    return None


def _extract_chrony_time_offsets(line: str) -> list[float]:
    values: list[float] = []
    pattern = re.compile(
        r"(?:system time|last offset|rms offset|root dispersion)\s*:\s*([-+]?\d+(?:\.\d+)?)\s*(nanoseconds?|ns|microseconds?|us|milliseconds?|ms|seconds?|s)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(line):
        values.append(_to_ns(float(match.group(1)), match.group(2).lower()))
    return values


def _chrony_line_indicates_lock(line: str) -> bool:
    lowered = line.lower()
    return (
        ("leap status" in lowered and "normal" in lowered)
        or "selected source" in lowered
        or "system clock synchronized" in lowered
        or "system clock synchronised" in lowered
        or "tracking is synchronized" in lowered
        or "tracking is synchronised" in lowered
    )


def _extract_metric_values(line: str, *, names: tuple[str, ...], default_unit: str) -> list[float]:
    values: list[float] = []
    escaped = "|".join(re.escape(name) for name in names)
    pattern = re.compile(
        rf"(?:{escaped})\s*[=:]?\s*([-+]?\d+(?:\.\d+)?)(?:\s*(nanoseconds?|ns|microseconds?|us|µs|milliseconds?|ms|seconds?|s)\b)?",
        re.IGNORECASE,
    )
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
    if " s2 " in f" {lowered} " or "locked" in lowered or "synchronized" in lowered or "synchronised" in lowered:
        return "locked"
    if "unlocked" in lowered or "fault" in lowered:
        return "unlocked"
    return ""


def _extract_gps_lock_bool(line: str) -> bool | None:
    lock = _extract_lock_bool(line)
    if lock is not None:
        return lock
    stripped = line.strip()
    lowered = stripped.lower()
    if re.search(r"^[\^\=\#\?][\*o+]?\s*(pps|gps|gnss|nmea)", lowered):
        return "*" in stripped[:3] or "+" in stripped[:3]
    if stripped.startswith("$") and ("GGA" in stripped or "GNS" in stripped):
        parts = stripped.split(",")
        if len(parts) > 6:
            quality = _optional_float(parts[6])
            return quality is not None and quality > 0
    if "gps fix" in lowered or "3d fix" in lowered or "pps locked" in lowered:
        return True
    if "no fix" in lowered or "lost pps" in lowered:
        return False
    return None


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
    if unit in {"ms", "millisecond", "milliseconds"}:
        return value * 1_000_000.0
    if unit in {"us", "µs", "microsecond", "microseconds"}:
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
