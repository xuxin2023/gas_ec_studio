from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shlex
from typing import Any


INSTALL_CONFIG_KEYS = ("runtime_install", "installable_runtime", "runtime_install_profile")


def has_runtime_install_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in INSTALL_CONFIG_KEYS):
        return True
    smartflux = config.get("smartflux_runtime", {})
    return isinstance(smartflux, dict) and any(
        isinstance(smartflux.get(key), dict) and smartflux.get(key) for key in INSTALL_CONFIG_KEYS
    )


def extract_runtime_install_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    runtime_service = config.get("runtime_service", {})
    smartflux = config.get("smartflux_runtime", {})
    for key in INSTALL_CONFIG_KEYS:
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    if isinstance(smartflux, dict):
        for key in INSTALL_CONFIG_KEYS:
            payload = smartflux.get(key, {})
            if isinstance(payload, dict):
                merged.update(payload)
    service_payloads = []
    if isinstance(runtime_service, dict):
        service_payloads.append(runtime_service)
    if isinstance(smartflux, dict):
        service_payloads.append(smartflux)
    for service_config in service_payloads:
        for source_key, target_key in (
            ("service_name", "service_name"),
            ("display_name", "display_name"),
            ("description", "description"),
            ("restart_policy", "restart_policy"),
            ("service_user", "user"),
            ("user", "user"),
            ("entrypoint", "command"),
            ("command", "command"),
        ):
            value = service_config.get(source_key)
            if value not in (None, "", []):
                merged.setdefault(target_key, value)
    service_id = ""
    if isinstance(runtime_service, dict):
        service_id = str(runtime_service.get("service_id", ""))
    if not service_id and isinstance(smartflux, dict):
        service_id = str(smartflux.get("service_id", ""))
    merged.setdefault("enabled", True)
    merged.setdefault("profile_id", "installable_runtime_profile_v1")
    merged.setdefault("service_name", service_id or "gas-ec-runtime")
    merged.setdefault("display_name", "Gas EC Studio Runtime")
    merged.setdefault("description", "Gas EC Studio unattended headless eddy-covariance processing runtime.")
    merged.setdefault("os_targets", ["systemd", "windows_service"])
    merged.setdefault("restart_policy", "on-failure")
    merged.setdefault("restart_sec", 10)
    merged.setdefault("dry_run", True)
    merged.setdefault("require_explicit_command", True)
    return merged


def build_installable_runtime_profile(
    *,
    config: dict[str, Any],
    runtime_root: Path | str | None = None,
) -> dict[str, Any]:
    install_config = extract_runtime_install_config(config)
    if not _truthy(install_config.get("enabled", True)):
        return {
            "artifact_type": "installable_runtime_profile",
            "status": "disabled",
            "profile_id": str(install_config.get("profile_id", "installable_runtime_profile_v1")),
            "checks": [],
            "provenance": "Installable runtime profile disabled by configuration.",
        }

    root = Path(runtime_root or install_config.get("runtime_root") or Path.cwd())
    working_directory = _resolve_working_directory(install_config, runtime_root=root)
    command_explicit = install_config.get("command") not in (None, "", [])
    command_value = (
        install_config.get("command")
        if command_explicit
        else ["python", "-m", "core.headless_batch_runner", "--help"]
    )
    command = _command_text(command_value)
    windows_command = _windows_command_text(command_value)
    targets = _normalize_targets(install_config.get("os_targets") or install_config.get("targets"))
    service_name = _service_name(str(install_config.get("service_name", "gas-ec-runtime")))
    display_name = str(install_config.get("display_name", "Gas EC Studio Runtime"))
    description = str(install_config.get("description", "Gas EC Studio unattended runtime."))
    environment = _normalize_environment(install_config.get("environment", {}))
    restart_policy = str(install_config.get("restart_policy", "on-failure")).strip() or "on-failure"
    restart_sec = int(_float_first(install_config.get("restart_sec"), default=10.0))
    user = str(install_config.get("user", "") or "")
    dry_run = _truthy(install_config.get("dry_run", True))
    require_explicit_command = _truthy(install_config.get("require_explicit_command", True))

    systemd = (
        _systemd_plan(
            service_name=service_name,
            display_name=display_name,
            description=description,
            working_directory=working_directory,
            command=command,
            restart_policy=restart_policy,
            restart_sec=restart_sec,
            user=user,
            environment=environment,
        )
        if "systemd" in targets
        else {}
    )
    windows = (
        _windows_service_plan(
            service_name=service_name,
            display_name=display_name,
            description=description,
            working_directory=working_directory,
            command=windows_command,
            restart_sec=restart_sec,
            environment=environment,
        )
        if "windows_service" in targets
        else {}
    )
    checks = _preflight_checks(
        service_name=service_name,
        targets=targets,
        working_directory=working_directory,
        command_explicit=command_explicit,
        require_explicit_command=require_explicit_command,
        dry_run=dry_run,
        systemd=systemd,
        windows=windows,
    )
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    return {
        "artifact_type": "installable_runtime_profile",
        "status": status,
        "profile_id": str(install_config.get("profile_id", "installable_runtime_profile_v1")),
        "generated_at": datetime.now().isoformat(),
        "runtime_root": str(root),
        "working_directory": str(working_directory),
        "service_name": service_name,
        "display_name": display_name,
        "description": description,
        "command": command,
        "windows_command": windows_command,
        "command_explicit": command_explicit,
        "os_targets": targets,
        "dry_run": dry_run,
        "execution_mode": "plan_only_no_install_performed",
        "restart_policy": restart_policy,
        "restart_sec": restart_sec,
        "user": user,
        "environment": environment,
        "systemd_unit": systemd,
        "windows_service": windows,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _recommended_actions(checks),
        "provenance": (
            "Installable runtime profile v1 renders auditable systemd and Windows Service deployment plans, "
            "preflight checks, and dry-run commands without installing, enabling, starting, or rebooting a host."
        ),
        "limitations": [
            "This artifact is a deployment plan only; a privileged deployment operator or CI job must perform the install.",
            "Windows Service command execution semantics depend on the host service wrapper when the command is not a direct executable.",
            "Hardware watchdog and reboot controls remain delegated to supervisor_integration providers.",
        ],
    }


def _systemd_plan(
    *,
    service_name: str,
    display_name: str,
    description: str,
    working_directory: Path,
    command: str,
    restart_policy: str,
    restart_sec: int,
    user: str,
    environment: dict[str, str],
) -> dict[str, Any]:
    unit_name = f"{service_name}.service"
    lines = [
        "[Unit]",
        f"Description={description or display_name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={working_directory}",
        f"ExecStart={command}",
        f"Restart={restart_policy}",
        f"RestartSec={restart_sec}",
    ]
    if user:
        lines.append(f"User={user}")
    for key, value in environment.items():
        lines.append(f"Environment={_systemd_environment(key, value)}")
    lines.extend(["", "[Install]", "WantedBy=multi-user.target", ""])
    install_path = f"/etc/systemd/system/{unit_name}"
    return {
        "artifact_type": "systemd_unit_plan",
        "unit_name": unit_name,
        "install_path": install_path,
        "content": "\n".join(lines),
        "dry_run_commands": [
            f"sudo install -m 0644 {unit_name} {install_path}",
            "sudo systemctl daemon-reload",
            f"sudo systemctl enable --now {unit_name}",
            f"systemctl status {unit_name}",
        ],
        "rollback_commands": [
            f"sudo systemctl disable --now {unit_name}",
            f"sudo rm -f {install_path}",
            "sudo systemctl daemon-reload",
        ],
    }


def _windows_service_plan(
    *,
    service_name: str,
    display_name: str,
    description: str,
    working_directory: Path,
    command: str,
    restart_sec: int,
    environment: dict[str, str],
) -> dict[str, Any]:
    binary_path = f'cmd.exe /C "cd /D {_cmd_quote(str(working_directory))} && {command}"'
    ps_env = "; ".join(f'$env:{key}={_ps_quote(value)}' for key, value in environment.items())
    prefix = f"{ps_env}; " if ps_env else ""
    new_service = (
        f"New-Service -Name {_ps_quote(service_name)} -DisplayName {_ps_quote(display_name)} "
        f"-Description {_ps_quote(description)} -BinaryPathName {_ps_quote(binary_path)} -StartupType Automatic"
    )
    return {
        "artifact_type": "windows_service_plan",
        "service_name": service_name,
        "display_name": display_name,
        "binary_path": binary_path,
        "dry_run_commands": [
            prefix + new_service,
            f"sc.exe failure {service_name} reset= 86400 actions= restart/{max(1000, restart_sec * 1000)}",
            f"Start-Service -Name {_ps_quote(service_name)}",
            f"Get-Service -Name {_ps_quote(service_name)}",
        ],
        "rollback_commands": [
            f"Stop-Service -Name {_ps_quote(service_name)} -ErrorAction SilentlyContinue",
            f"sc.exe delete {service_name}",
        ],
    }


def _preflight_checks(
    *,
    service_name: str,
    targets: list[str],
    working_directory: Path,
    command_explicit: bool,
    require_explicit_command: bool,
    dry_run: bool,
    systemd: dict[str, Any],
    windows: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _check(
            "service_name",
            bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", service_name)),
            measured=service_name,
            threshold="3-64 characters: letters, digits, underscore, dot, dash",
            severity="fail",
            failure_message="Service name is not valid for a cross-platform install plan.",
        ),
        _check(
            "os_target_coverage",
            bool(targets) and any(target in {"systemd", "windows_service"} for target in targets),
            measured=",".join(targets),
            threshold="systemd and/or windows_service",
            severity="fail",
            failure_message="No supported OS service target was selected.",
        ),
        _check(
            "working_directory_exists",
            working_directory.exists() and working_directory.is_dir(),
            measured=str(working_directory),
            threshold="existing directory",
            severity="warn",
            failure_message="Working directory does not exist on this host.",
        ),
        _check(
            "runtime_command_explicit",
            command_explicit or not require_explicit_command,
            measured="explicit" if command_explicit else "default_help_command",
            threshold="explicit runtime command",
            severity="warn",
            failure_message="Runtime command was not explicitly configured; generated plan uses a safe help command.",
        ),
        _check(
            "plan_only_execution",
            dry_run,
            measured="dry_run" if dry_run else "apply_requested_but_not_executed",
            threshold="dry_run plan",
            severity="warn",
            failure_message="Configuration requested non-dry-run install, but artifact generation never mutates host services.",
        ),
        _check(
            "systemd_plan_rendered",
            "systemd" not in targets or bool(systemd.get("content")),
            measured="rendered" if systemd.get("content") else "not_rendered",
            threshold="rendered when target includes systemd",
            severity="fail",
            failure_message="Systemd target was selected but no unit content was rendered.",
        ),
        _check(
            "windows_service_plan_rendered",
            "windows_service" not in targets or bool(windows.get("binary_path")),
            measured="rendered" if windows.get("binary_path") else "not_rendered",
            threshold="rendered when target includes windows_service",
            severity="fail",
            failure_message="Windows Service target was selected but no service command was rendered.",
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
        "message": "Installable runtime preflight check passed." if passed else failure_message,
    }


def _recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id == "runtime_command_explicit":
            actions.append("Set runtime_install.command to the production headless runner command before deployment.")
        elif check_id == "working_directory_exists":
            actions.append("Create the runtime working directory or point runtime_install.working_directory at the deployment path.")
        elif check_id == "plan_only_execution":
            actions.append("Keep dry_run=true for artifact generation; execute install commands only in a controlled deployment step.")
        elif check_id == "service_name":
            actions.append("Choose a short service name using only letters, digits, underscore, dot, or dash.")
        else:
            actions.append(f"Review installable runtime preflight check {check_id}.")
    return list(dict.fromkeys(actions))


def _resolve_working_directory(config: dict[str, Any], *, runtime_root: Path) -> Path:
    value = config.get("working_directory") or config.get("workdir") or runtime_root
    path = Path(str(value))
    if not path.is_absolute():
        path = runtime_root / path
    return path


def _normalize_targets(value: Any) -> list[str]:
    raw: list[Any]
    if isinstance(value, str):
        raw = re.split(r"[,| ]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = ["systemd", "windows_service"]
    targets: list[str] = []
    for item in raw:
        target = str(item).strip().lower().replace("-", "_")
        if target in {"windows", "win_service", "windowsservice", "sc"}:
            target = "windows_service"
        if target:
            targets.append(target)
    return list(dict.fromkeys(targets))


def _normalize_environment(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    env: dict[str, str] = {}
    for key, payload in value.items():
        name = str(key).strip()
        if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        env[name] = str(payload)
    return env


def _service_name(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _command_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(shlex.quote(str(item)) for item in value)
    return str(value).strip()


def _windows_command_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_cmd_arg(str(item)) for item in value)
    return str(value).strip()


def _systemd_environment(key: str, value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'{key}="{escaped}"'


def _cmd_arg(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=+@%-]+", value):
        return value
    return _cmd_quote(value)


def _cmd_quote(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


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
