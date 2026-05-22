from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from core.acquisition.runtime_install import (
    build_installable_runtime_profile,
    build_runtime_deployment_feedback_artifact,
    has_runtime_deployment_feedback_config,
    has_runtime_install_config,
)


def has_supervisor_integration_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in ("supervisor_integration", "os_supervisor", "hardware_watchdog_provider")):
        return True
    if has_runtime_install_config(config):
        return True
    if has_runtime_deployment_feedback_config(config):
        return True
    smartflux = config.get("smartflux_runtime", {})
    return isinstance(smartflux, dict) and any(
        isinstance(smartflux.get(key), dict) and smartflux.get(key)
        for key in ("supervisor_integration", "os_supervisor", "hardware_watchdog_provider")
    )


def extract_supervisor_integration_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("supervisor_integration", "os_supervisor"):
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    smartflux = config.get("smartflux_runtime", {})
    if isinstance(smartflux, dict):
        for key in ("supervisor_integration", "os_supervisor"):
            payload = smartflux.get(key, {})
            if isinstance(payload, dict):
                merged.update(payload)
    provider = config.get("hardware_watchdog_provider", {})
    if isinstance(provider, dict):
        merged.setdefault("hardware_watchdog_provider", {}).update(provider)
    if isinstance(smartflux, dict) and isinstance(smartflux.get("hardware_watchdog_provider"), dict):
        merged.setdefault("hardware_watchdog_provider", {}).update(smartflux["hardware_watchdog_provider"])
    merged.setdefault("enabled", True)
    merged.setdefault("profile_id", "os_supervisor_integration_v1")
    merged.setdefault("adapter", "auto")
    merged.setdefault("require_running", False)
    merged.setdefault("max_restart_count", 3)
    merged.setdefault("allow_reboot_request", False)
    return merged


def build_supervisor_integration_artifact(
    *,
    config: dict[str, Any],
    runtime_root: Path | str | None = None,
) -> dict[str, Any]:
    integration_config = extract_supervisor_integration_config(config)
    if not _truthy(integration_config.get("enabled", True)):
        return {
            "artifact_type": "supervisor_integration",
            "status": "disabled",
            "profile_id": str(integration_config.get("profile_id", "os_supervisor_integration_v1")),
            "checks": [],
            "provenance": "OS supervisor integration disabled by configuration.",
        }
    root = Path(runtime_root or Path.cwd())
    adapter = str(integration_config.get("adapter", "auto")).strip().lower()
    service_status = load_service_status(integration_config=integration_config, adapter=adapter)
    watchdog_provider = run_hardware_watchdog_provider(
        provider_config=dict(integration_config.get("hardware_watchdog_provider", {}) or {}),
        runtime_root=root,
        allow_reboot_request=_truthy(integration_config.get("allow_reboot_request", False)),
    )
    installable_runtime_profile = (
        build_installable_runtime_profile(config=config, runtime_root=root)
        if has_runtime_install_config(config)
        else {}
    )
    runtime_deployment_feedback = (
        build_runtime_deployment_feedback_artifact(
            config=config,
            runtime_root=root,
            installable_runtime_profile=installable_runtime_profile,
            service_status=service_status,
        )
        if has_runtime_deployment_feedback_config(config)
        else {}
    )
    checks = _checks(
        integration_config=integration_config,
        service_status=service_status,
        watchdog_provider=watchdog_provider,
        installable_runtime_profile=installable_runtime_profile,
        runtime_deployment_feedback=runtime_deployment_feedback,
    )
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    return {
        "artifact_type": "supervisor_integration",
        "status": status,
        "profile_id": str(integration_config.get("profile_id", "os_supervisor_integration_v1")),
        "adapter": adapter,
        "collected_at": datetime.now().isoformat(),
        "runtime_root": str(root),
        "service_status": service_status,
        "hardware_watchdog_provider": watchdog_provider,
        "installable_runtime_profile": installable_runtime_profile,
        "runtime_deployment_feedback": runtime_deployment_feedback,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _recommended_actions(checks),
        "provenance": (
            "Supervisor integration v1 normalizes configured systemd/Windows/manual service status and records "
            "hardware watchdog kick/reboot provider attempts, plus optional installable runtime deployment plans, "
            "post-install feedback, without installing or mutating an OS service."
        ),
        "limitations": [
            "This artifact reads configured status snapshots and uses file/manual watchdog providers; direct systemd/Windows Service control is intentionally not invoked here.",
            "Installable runtime profiles are rendered as dry-run deployment plans and must be applied by a privileged deployment step.",
            "Post-install feedback must be supplied by the target host after operator-gated deployment.",
            "Real hardware watchdog kick and reboot control require a platform-specific provider supplied by the deployment host.",
        ],
    }


def load_service_status(*, integration_config: dict[str, Any], adapter: str) -> dict[str, Any]:
    inline = integration_config.get("service_status", {})
    if isinstance(inline, dict) and inline:
        return _normalize_manual_status(inline)
    status_file = _optional_path(
        integration_config.get("status_file")
        or integration_config.get("supervisor_status_file")
        or integration_config.get("service_status_file")
    )
    if status_file is None:
        return _normalize_manual_status({"state": "not_configured", "adapter": adapter})
    text = _read_text(status_file)
    if text == "":
        return _normalize_manual_status({"state": "missing", "adapter": adapter, "source_file": str(status_file)})
    if adapter == "systemd" or (adapter == "auto" and ("ActiveState=" in text or "SubState=" in text or "Loaded:" in text)):
        return parse_systemd_status(text, source_file=status_file)
    if adapter in {"windows", "windows_service", "sc"} or (adapter == "auto" and ("SERVICE_NAME" in text or "STATE" in text)):
        return parse_windows_service_status(text, source_file=status_file)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload.setdefault("source_file", str(status_file))
            return _normalize_manual_status(payload)
    except json.JSONDecodeError:
        pass
    return _normalize_manual_status({"state": "unknown", "adapter": adapter, "source_file": str(status_file), "raw_excerpt": text[:200]})


def parse_systemd_status(text: str, *, source_file: Path | None = None) -> dict[str, Any]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    active_state = fields.get("ActiveState", "")
    sub_state = fields.get("SubState", "")
    result = fields.get("Result", "")
    restart_count = _int_first(fields.get("NRestarts"), fields.get("RestartUSec"), default=0)
    if not active_state:
        active_match = re.search(r"Active:\s+(\w+)(?:\s+\(([^)]+)\))?", text, flags=re.IGNORECASE)
        if active_match:
            active_state = active_match.group(1).strip().lower()
            sub_state = (active_match.group(2) or sub_state).strip().lower()
    state = "running" if active_state == "active" and sub_state in {"running", "exited", ""} else (active_state or "unknown")
    if active_state in {"failed", "inactive"}:
        state = active_state
    return {
        "artifact_type": "os_supervisor_status",
        "adapter": "systemd",
        "source_file": str(source_file or ""),
        "service_name": fields.get("Id", fields.get("Names", "")),
        "state": state,
        "active_state": active_state,
        "sub_state": sub_state,
        "restart_count": restart_count,
        "last_exit_code": fields.get("ExecMainStatus", ""),
        "result": result,
        "provenance": "Parsed systemd status/show snapshot.",
    }


def parse_windows_service_status(text: str, *, source_file: Path | None = None) -> dict[str, Any]:
    payload: dict[str, str] = {}
    service_name = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("SERVICE_NAME"):
            service_name = stripped.split(":", 1)[-1].strip()
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            payload[key.strip().upper().replace(" ", "_")] = value.strip()
    state_text = payload.get("STATE", "")
    state = "unknown"
    state_match = re.search(r"\b(RUNNING|STOPPED|PAUSED|START_PENDING|STOP_PENDING)\b", state_text, flags=re.IGNORECASE)
    if state_match:
        normalized = state_match.group(1).lower()
        state = "running" if normalized == "running" else normalized
    return {
        "artifact_type": "os_supervisor_status",
        "adapter": "windows_service",
        "source_file": str(source_file or ""),
        "service_name": service_name or payload.get("SERVICE_NAME", ""),
        "state": state,
        "raw_state": state_text,
        "restart_count": _int_first(payload.get("RESTART_COUNT"), default=0),
        "last_exit_code": payload.get("WIN32_EXIT_CODE", ""),
        "result": payload.get("SERVICE_EXIT_CODE", ""),
        "provenance": "Parsed Windows Service/sc.exe status snapshot.",
    }


def run_hardware_watchdog_provider(
    *,
    provider_config: dict[str, Any],
    runtime_root: Path,
    allow_reboot_request: bool,
) -> dict[str, Any]:
    if not provider_config:
        return {
            "artifact_type": "hardware_watchdog_provider",
            "status": "not_configured",
            "provider": "",
            "kick_attempted": False,
            "reboot_requested": False,
            "provenance": "No hardware watchdog provider configured.",
        }
    provider = str(provider_config.get("provider", provider_config.get("mode", "file"))).strip().lower()
    enabled = _truthy(provider_config.get("enabled", True))
    if not enabled:
        return {
            "artifact_type": "hardware_watchdog_provider",
            "status": "disabled",
            "provider": provider,
            "kick_attempted": False,
            "reboot_requested": False,
            "provenance": "Hardware watchdog provider disabled by configuration.",
        }
    if provider not in {"file", "audit_file", "manual"}:
        return {
            "artifact_type": "hardware_watchdog_provider",
            "status": "unsupported_provider",
            "provider": provider,
            "kick_attempted": False,
            "reboot_requested": False,
            "provenance": "Unsupported provider; no system call or hardware mutation was attempted.",
        }
    if provider == "manual":
        return {
            "artifact_type": "hardware_watchdog_provider",
            "status": "manual_review",
            "provider": provider,
            "kick_attempted": False,
            "reboot_requested": False,
            "provenance": "Manual provider records that watchdog kick/reboot is handled outside gas_ec_studio.",
        }
    kick_file = _provider_path(provider_config.get("kick_file") or provider_config.get("audit_file"), runtime_root=runtime_root)
    reboot_file = _provider_path(provider_config.get("reboot_request_file"), runtime_root=runtime_root)
    dry_run = _truthy(provider_config.get("dry_run", True))
    kick_payload = {
        "artifact_type": "hardware_watchdog_kick",
        "provider": provider,
        "recorded_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "service_name": str(provider_config.get("service_name", "")),
        "provenance": "File provider records a watchdog kick attempt for deployment-side forwarding.",
    }
    kick_written = _append_json_line(kick_file, kick_payload)
    reboot_requested = _truthy(provider_config.get("request_reboot", False))
    reboot_written = False
    if reboot_requested and allow_reboot_request:
        reboot_payload = {
            "artifact_type": "hardware_watchdog_reboot_request",
            "provider": provider,
            "recorded_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "service_name": str(provider_config.get("service_name", "")),
            "reason": str(provider_config.get("reboot_reason", "runtime_service_requested")),
            "provenance": "File provider records a reboot request for external supervisor review.",
        }
        reboot_written = _append_json_line(reboot_file, reboot_payload)
    status = "kick_recorded" if kick_written else "kick_failed"
    if reboot_requested and not allow_reboot_request:
        status = "reboot_blocked_by_policy"
    elif reboot_requested and allow_reboot_request and reboot_written:
        status = "kick_and_reboot_recorded"
    return {
        "artifact_type": "hardware_watchdog_provider",
        "status": status,
        "provider": provider,
        "kick_attempted": True,
        "kick_recorded": kick_written,
        "kick_file": str(kick_file),
        "dry_run": dry_run,
        "reboot_requested": reboot_requested,
        "reboot_allowed": allow_reboot_request,
        "reboot_recorded": reboot_written,
        "reboot_request_file": str(reboot_file) if reboot_file else "",
        "provenance": "Hardware watchdog file provider attempted an auditable kick/reboot handoff.",
        "limitations": ["File provider does not directly kick a hardware watchdog; deployment supervisor must consume the audit file."],
    }


def _checks(
    *,
    integration_config: dict[str, Any],
    service_status: dict[str, Any],
    watchdog_provider: dict[str, Any],
    installable_runtime_profile: dict[str, Any],
    runtime_deployment_feedback: dict[str, Any],
) -> list[dict[str, Any]]:
    require_running = _truthy(integration_config.get("require_running", False))
    max_restart_count = int(_float_first(integration_config.get("max_restart_count"), default=3.0))
    require_kick = _truthy(integration_config.get("require_watchdog_kick", False))
    checks = [
        _check(
            "os_supervisor_state",
            service_status.get("state") in {"running", "active", "ok"} if require_running else service_status.get("state") not in {"failed", "crashed"},
            measured=service_status.get("state", ""),
            threshold="running/active" if require_running else "not failed",
            severity="fail" if require_running else "warn",
            failure_message="Configured OS supervisor status is not acceptable.",
        ),
        _check(
            "os_supervisor_restart_count",
            int(service_status.get("restart_count", 0) or 0) <= max_restart_count,
            measured=service_status.get("restart_count", 0),
            threshold=f"<={max_restart_count}",
            severity="warn",
            failure_message="OS supervisor restart count exceeds policy.",
        ),
        _check(
            "hardware_watchdog_kick_provider",
            bool(watchdog_provider.get("kick_recorded")) if require_kick else watchdog_provider.get("status") not in {"unsupported_provider", "kick_failed"},
            measured=watchdog_provider.get("status", ""),
            threshold="kick recorded" if require_kick else "provider supported or not configured",
            severity="fail" if require_kick else "warn",
            failure_message="Hardware watchdog kick provider did not record a kick.",
        ),
        _check(
            "reboot_policy",
            watchdog_provider.get("status") != "reboot_blocked_by_policy",
            measured=watchdog_provider.get("status", ""),
            threshold="no blocked reboot request",
            severity="warn",
            failure_message="A reboot request was present but blocked by integration policy.",
        ),
    ]
    if installable_runtime_profile:
        install_status = str(installable_runtime_profile.get("status", "not_configured"))
        checks.append(
            _check(
                "installable_runtime_profile",
                install_status != "fail",
                measured=install_status,
                threshold="not fail",
                severity="fail",
                failure_message="Installable runtime profile preflight has blocking failures.",
            )
        )
        checks.append(
            _check(
                "installable_runtime_preflight_warnings",
                install_status not in {"warning"},
                measured=install_status,
                threshold="no warning preflight checks",
                severity="warn",
                failure_message="Installable runtime profile has deployment preflight warnings.",
            )
        )
    if runtime_deployment_feedback:
        feedback_status = str(runtime_deployment_feedback.get("status", "not_configured"))
        checks.append(
            _check(
                "runtime_deployment_feedback",
                feedback_status != "fail",
                measured=feedback_status,
                threshold="not fail",
                severity="fail",
                failure_message="Runtime deployment feedback reports a blocking post-install issue.",
            )
        )
        checks.append(
            _check(
                "runtime_deployment_feedback_warnings",
                feedback_status not in {"warning"},
                measured=feedback_status,
                threshold="no warning feedback checks",
                severity="warn",
                failure_message="Runtime deployment feedback has post-install warnings.",
            )
        )
    return checks


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
        "message": "Supervisor integration check passed." if passed else failure_message,
    }


def _recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id.startswith("os_supervisor"):
            actions.append("Inspect systemd/Windows Service state and restart history before unattended runtime delivery.")
        elif check_id == "hardware_watchdog_kick_provider":
            actions.append("Configure a supported hardware watchdog provider or verify the deployment-side file handoff.")
        elif check_id == "reboot_policy":
            actions.append("Review reboot policy; enable allow_reboot_request only for supervised deployments.")
        elif check_id.startswith("installable_runtime"):
            actions.append("Review installable runtime profile preflight checks before applying OS service deployment commands.")
        elif check_id.startswith("runtime_deployment_feedback"):
            actions.append("Review target-host install/status/rollback feedback before unattended deployment delivery.")
        else:
            actions.append(f"Review supervisor integration check {check_id}.")
    return list(dict.fromkeys(actions))


def _normalize_manual_status(payload: dict[str, Any]) -> dict[str, Any]:
    state = str(payload.get("state") or payload.get("status") or "unknown").strip().lower()
    return {
        "artifact_type": "os_supervisor_status",
        "adapter": str(payload.get("adapter", "manual")),
        "source_file": str(payload.get("source_file", "")),
        "service_name": str(payload.get("service_name", payload.get("name", ""))),
        "state": state,
        "restart_count": _int_first(payload.get("restart_count"), payload.get("restarts"), default=0),
        "last_exit_code": payload.get("last_exit_code", payload.get("exit_code", "")),
        "result": payload.get("result", ""),
        "provenance": "Supervisor status normalized from manual/configured payload.",
    }


def _provider_path(value: Any, *, runtime_root: Path) -> Path:
    if value in (None, ""):
        return runtime_root / "hardware_watchdog_provider.jsonl"
    path = Path(str(value))
    if not path.is_absolute():
        path = runtime_root / path
    return path


def _append_json_line(path: Path | None, payload: dict[str, Any]) -> bool:
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _optional_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "enabled", "on", "running", "active"}


def _float_first(*values: Any, default: float) -> float:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)


def _int_first(*values: Any, default: int) -> int:
    return int(_float_first(*values, default=float(default)))
