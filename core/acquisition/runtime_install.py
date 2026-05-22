from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import re
import shlex
from typing import Any


INSTALL_CONFIG_KEYS = ("runtime_install", "installable_runtime", "runtime_install_profile")
FEEDBACK_CONFIG_KEYS = ("runtime_deployment_feedback", "post_install_feedback", "deployment_feedback")


def has_runtime_install_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in INSTALL_CONFIG_KEYS):
        return True
    smartflux = config.get("smartflux_runtime", {})
    return isinstance(smartflux, dict) and any(
        isinstance(smartflux.get(key), dict) and smartflux.get(key) for key in INSTALL_CONFIG_KEYS
    )


def has_runtime_deployment_feedback_config(config: dict[str, Any]) -> bool:
    if any(isinstance(config.get(key), dict) and config.get(key) for key in FEEDBACK_CONFIG_KEYS):
        return True
    runtime_install = config.get("runtime_install", {})
    if isinstance(runtime_install, dict) and isinstance(runtime_install.get("feedback"), dict) and runtime_install.get("feedback"):
        return True
    smartflux = config.get("smartflux_runtime", {})
    return isinstance(smartflux, dict) and any(
        isinstance(smartflux.get(key), dict) and smartflux.get(key) for key in FEEDBACK_CONFIG_KEYS
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


def extract_runtime_deployment_feedback_config(config: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in FEEDBACK_CONFIG_KEYS:
        payload = config.get(key, {})
        if isinstance(payload, dict):
            merged.update(payload)
    runtime_install = config.get("runtime_install", {})
    if isinstance(runtime_install, dict) and isinstance(runtime_install.get("feedback"), dict):
        merged.update(runtime_install["feedback"])
    smartflux = config.get("smartflux_runtime", {})
    if isinstance(smartflux, dict):
        for key in FEEDBACK_CONFIG_KEYS:
            payload = smartflux.get(key, {})
            if isinstance(payload, dict):
                merged.update(payload)
    merged.setdefault("enabled", True)
    merged.setdefault("require_install_record", True)
    merged.setdefault("require_running", True)
    merged.setdefault("require_rollback_success", False)
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
    deployment_plan = _deployment_plan_summary(profile_status=status, systemd=systemd, windows=windows, targets=targets)
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
        "deployment_plan": deployment_plan,
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


def build_runtime_deployment_feedback_artifact(
    *,
    config: dict[str, Any],
    runtime_root: Path | str | None = None,
    installable_runtime_profile: dict[str, Any] | None = None,
    runtime_deployment: dict[str, Any] | None = None,
    service_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    feedback_config = extract_runtime_deployment_feedback_config(config)
    if not has_runtime_deployment_feedback_config(config):
        return {}
    profile = dict(installable_runtime_profile or {})
    deployment = dict(runtime_deployment or profile.get("deployment_plan", {}) or {})
    if not _truthy(feedback_config.get("enabled", True)):
        return {
            "artifact_type": "runtime_deployment_feedback",
            "status": "disabled",
            "profile_id": str(profile.get("profile_id", "")),
            "checks": [],
            "provenance": "Runtime deployment feedback disabled by configuration.",
        }
    root = Path(runtime_root or profile.get("runtime_root") or Path.cwd())
    expected_service = str(feedback_config.get("service_name") or profile.get("service_name") or "")
    observed_status = _deployment_service_status(
        config=feedback_config,
        runtime_root=root,
        fallback_status=dict(service_status or {}),
    )
    install_log = _deployment_log_summary(_feedback_path(feedback_config.get("install_log_file") or feedback_config.get("install_record_file"), runtime_root=root))
    rollback_log = _deployment_log_summary(_feedback_path(feedback_config.get("rollback_log_file") or feedback_config.get("rollback_record_file"), runtime_root=root))
    checks = _feedback_checks(
        feedback_config=feedback_config,
        expected_service=expected_service,
        service_status=observed_status,
        install_log=install_log,
        rollback_log=rollback_log,
    )
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count else "pass")
    target_apply_observed = bool(install_log.get("applied_count", 0) or observed_status.get("state") in {"running", "active", "ok"})
    return {
        "artifact_type": "runtime_deployment_feedback",
        "status": status,
        "profile_id": str(profile.get("profile_id", "")),
        "service_name": expected_service,
        "collected_at": datetime.now().isoformat(),
        "runtime_root": str(root),
        "execution_mode": str(deployment.get("execution_mode", "operator_gated_external_executor")),
        "builder_host_mutation_performed": False,
        "target_apply_observed": target_apply_observed,
        "service_status": observed_status,
        "install_log": install_log,
        "rollback_log": rollback_log,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _feedback_recommended_actions(checks),
        "provenance": (
            "Runtime deployment feedback v1 normalizes post-install service status, install logs, and rollback "
            "logs supplied by the target host. It does not execute installation, rollback, restart, or reboot commands."
        ),
        "limitations": [
            "Feedback depends on target-host snapshots supplied after operator-gated deployment.",
            "Service status parsing covers systemd show/status, Windows sc.exe output, and JSON/manual payloads.",
            "A running service snapshot is operational evidence, not proof that every OS-level install command succeeded.",
        ],
    }


def build_runtime_deployment_artifact(
    *,
    installable_runtime_profile: dict[str, Any],
) -> dict[str, Any]:
    if not installable_runtime_profile:
        return {}
    profile_status = str(installable_runtime_profile.get("status", "not_configured"))
    scripts = _deployment_scripts(installable_runtime_profile)
    checks = _deployment_checks(profile_status=profile_status, scripts=scripts)
    fail_count = sum(1 for item in checks if item["status"] == "fail")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    status = "fail" if fail_count else ("warning" if warn_count or profile_status == "warning" else "pass")
    return {
        "artifact_type": "runtime_deployment",
        "status": status,
        "profile_id": str(installable_runtime_profile.get("profile_id", "")),
        "service_name": str(installable_runtime_profile.get("service_name", "")),
        "generated_at": datetime.now().isoformat(),
        "execution_mode": "operator_gated_external_executor",
        "host_mutation_performed": False,
        "apply_gate": "GAS_EC_APPLY=1 for shell scripts or -Apply for PowerShell scripts",
        "installable_runtime_status": profile_status,
        "os_targets": list(installable_runtime_profile.get("os_targets", []) or []),
        "script_count": len(scripts),
        "scripts": scripts,
        "checks": checks,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "recommended_actions": _deployment_recommended_actions(checks),
        "provenance": (
            "Runtime deployment v1 packages install, status, and rollback scripts from the installable runtime "
            "profile. The generated scripts are guarded and perform no host mutation unless the operator "
            "explicitly enables the apply gate after review."
        ),
        "limitations": [
            "Scripts are generated from the exported plan and must be reviewed on the target host before application.",
            "The artifact builder does not execute privileged service installation, service start, rollback, or reboot commands.",
            "Post-install status evidence should be fed back through supervisor_integration status snapshots.",
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


def _deployment_plan_summary(
    *,
    profile_status: str,
    systemd: dict[str, Any],
    windows: dict[str, Any],
    targets: list[str],
) -> dict[str, Any]:
    script_names: list[str] = []
    if systemd:
        script_names.extend(["install_systemd.sh", "rollback_systemd.sh"])
    if windows:
        script_names.extend(["install_windows_service.ps1", "rollback_windows_service.ps1"])
    return {
        "artifact_type": "runtime_deployment_plan",
        "status": profile_status,
        "execution_mode": "operator_gated_external_executor",
        "host_mutation_performed": False,
        "os_targets": list(targets),
        "script_names": script_names,
        "apply_gate": "GAS_EC_APPLY=1 or PowerShell -Apply",
        "provenance": "Deployment plan summary generated from installable runtime profile.",
    }


def _deployment_scripts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    scripts: list[dict[str, Any]] = []
    systemd = dict(profile.get("systemd_unit", {}) or {})
    windows = dict(profile.get("windows_service", {}) or {})
    if systemd:
        scripts.append(
            {
                "filename": "install_systemd.sh",
                "target": "systemd",
                "kind": "install",
                "content": _systemd_install_script(systemd),
            }
        )
        scripts.append(
            {
                "filename": "rollback_systemd.sh",
                "target": "systemd",
                "kind": "rollback",
                "content": _systemd_rollback_script(systemd),
            }
        )
    if windows:
        scripts.append(
            {
                "filename": "install_windows_service.ps1",
                "target": "windows_service",
                "kind": "install",
                "content": _windows_install_script(windows),
            }
        )
        scripts.append(
            {
                "filename": "rollback_windows_service.ps1",
                "target": "windows_service",
                "kind": "rollback",
                "content": _windows_rollback_script(windows),
            }
        )
    return scripts


def _systemd_install_script(systemd: dict[str, Any]) -> str:
    unit_name = str(systemd.get("unit_name", "gas-ec-runtime.service"))
    install_path = str(systemd.get("install_path", f"/etc/systemd/system/{unit_name}"))
    content = str(systemd.get("content", ""))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'if [[ "${GAS_EC_APPLY:-}" != "1" ]]; then',
            '  echo "Dry-run only. Review this script, then set GAS_EC_APPLY=1 to apply on the target host."',
            "  exit 0",
            "fi",
            'if [[ "$(id -u)" -ne 0 ]]; then',
            '  echo "Run as root or via sudo on the target host." >&2',
            "  exit 1",
            "fi",
            f"cat > {shlex.quote(install_path)} <<'GAS_EC_SYSTEMD_UNIT'",
            content,
            "GAS_EC_SYSTEMD_UNIT",
            "systemctl daemon-reload",
            f"systemctl enable --now {shlex.quote(unit_name)}",
            f"systemctl status {shlex.quote(unit_name)} --no-pager",
            "",
        ]
    )


def _systemd_rollback_script(systemd: dict[str, Any]) -> str:
    unit_name = str(systemd.get("unit_name", "gas-ec-runtime.service"))
    install_path = str(systemd.get("install_path", f"/etc/systemd/system/{unit_name}"))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            'if [[ "${GAS_EC_APPLY:-}" != "1" ]]; then',
            '  echo "Dry-run only. Review this script, then set GAS_EC_APPLY=1 to rollback on the target host."',
            "  exit 0",
            "fi",
            'if [[ "$(id -u)" -ne 0 ]]; then',
            '  echo "Run as root or via sudo on the target host." >&2',
            "  exit 1",
            "fi",
            f"systemctl disable --now {shlex.quote(unit_name)} || true",
            f"rm -f {shlex.quote(install_path)}",
            "systemctl daemon-reload",
            f"systemctl status {shlex.quote(unit_name)} --no-pager || true",
            "",
        ]
    )


def _windows_install_script(windows: dict[str, Any]) -> str:
    service_name = str(windows.get("service_name", "gas-ec-runtime"))
    commands = [str(item) for item in list(windows.get("dry_run_commands", []) or []) if item]
    return "\n".join(
        [
            "param([switch]$Apply)",
            "Set-StrictMode -Version Latest",
            "$ErrorActionPreference = 'Stop'",
            "if (-not $Apply -and $env:GAS_EC_APPLY -ne '1') {",
            "  Write-Host 'Dry-run only. Review this script, then pass -Apply or set GAS_EC_APPLY=1 on the target host.'",
            "  exit 0",
            "}",
            "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())",
            "if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {",
            "  throw 'Run this script from an elevated PowerShell session on the target host.'",
            "}",
            f"if (Get-Service -Name {_ps_quote(service_name)} -ErrorAction SilentlyContinue) {{",
            f"  throw 'Service already exists: {service_name}. Run rollback or choose another service name.'",
            "}",
            *commands,
            "",
        ]
    )


def _windows_rollback_script(windows: dict[str, Any]) -> str:
    commands = [str(item) for item in list(windows.get("rollback_commands", []) or []) if item]
    return "\n".join(
        [
            "param([switch]$Apply)",
            "Set-StrictMode -Version Latest",
            "$ErrorActionPreference = 'Stop'",
            "if (-not $Apply -and $env:GAS_EC_APPLY -ne '1') {",
            "  Write-Host 'Dry-run only. Review this script, then pass -Apply or set GAS_EC_APPLY=1 on the target host.'",
            "  exit 0",
            "}",
            "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())",
            "if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {",
            "  throw 'Run this script from an elevated PowerShell session on the target host.'",
            "}",
            *commands,
            "",
        ]
    )


def _deployment_checks(
    *,
    profile_status: str,
    scripts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contents = [str(script.get("content", "")) for script in scripts]
    has_apply_gate = bool(contents) and all("GAS_EC_APPLY" in content or "[switch]$Apply" in content for content in contents)
    return [
        _check(
            "installable_runtime_profile_status",
            profile_status not in {"fail", "disabled", "not_configured"},
            measured=profile_status,
            threshold="pass or warning",
            severity="fail",
            failure_message="Installable runtime profile is not deployable.",
        ),
        _check(
            "deployment_script_count",
            len(scripts) >= 2,
            measured=len(scripts),
            threshold="at least install and rollback scripts for one target",
            severity="fail",
            failure_message="Deployment package did not render install/rollback scripts.",
        ),
        _check(
            "deployment_apply_gate",
            has_apply_gate,
            measured="present" if has_apply_gate else "missing",
            threshold="explicit apply gate in every script",
            severity="fail",
            failure_message="Deployment scripts must be protected by an explicit apply gate.",
        ),
        _check(
            "host_mutation_performed",
            True,
            measured=False,
            threshold="false during artifact generation",
            severity="fail",
            failure_message="Artifact generation must not mutate host services.",
        ),
    ]


def _deployment_recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id == "installable_runtime_profile_status":
            actions.append("Resolve installable runtime preflight failures before using deployment scripts.")
        elif check_id == "deployment_apply_gate":
            actions.append("Regenerate deployment scripts and verify every script requires GAS_EC_APPLY=1 or -Apply.")
        else:
            actions.append(f"Review runtime deployment check {check_id}.")
    return list(dict.fromkeys(actions))


def _deployment_service_status(
    *,
    config: dict[str, Any],
    runtime_root: Path,
    fallback_status: dict[str, Any],
) -> dict[str, Any]:
    inline = config.get("service_status", {})
    if isinstance(inline, dict) and inline:
        return _normalize_feedback_service_status(inline, source="inline")
    status_file = _feedback_path(
        config.get("status_file")
        or config.get("service_status_file")
        or config.get("supervisor_status_file"),
        runtime_root=runtime_root,
    )
    if status_file is not None and status_file.exists():
        text = _read_text(status_file)
        parsed = _parse_feedback_service_status(text=text, source_file=status_file)
        if parsed:
            return parsed
    if fallback_status:
        payload = dict(fallback_status)
        payload.setdefault("source", "supervisor_integration")
        return _normalize_feedback_service_status(payload, source=str(payload.get("source", "supervisor_integration")))
    return {
        "artifact_type": "runtime_deployment_service_status",
        "status": "not_configured",
        "state": "not_configured",
        "source_file": str(status_file or ""),
        "service_name": "",
        "provenance": "No post-install service status snapshot was supplied.",
    }


def _parse_feedback_service_status(*, text: str, source_file: Path) -> dict[str, Any]:
    if not text.strip():
        return _normalize_feedback_service_status({"state": "missing", "source_file": str(source_file)}, source="empty_file")
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload.setdefault("source_file", str(source_file))
            return _normalize_feedback_service_status(payload, source="json")
    except json.JSONDecodeError:
        pass
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    if fields:
        active_state = fields.get("ActiveState", "")
        sub_state = fields.get("SubState", "")
        state = "running" if active_state == "active" and sub_state in {"running", "exited", ""} else (active_state or "unknown")
        return _normalize_feedback_service_status(
            {
                "adapter": "systemd",
                "source_file": str(source_file),
                "service_name": fields.get("Id", fields.get("Names", "")),
                "state": state,
                "active_state": active_state,
                "sub_state": sub_state,
                "restart_count": _int_first(fields.get("NRestarts"), default=0),
                "last_exit_code": fields.get("ExecMainStatus", ""),
                "result": fields.get("Result", ""),
            },
            source="systemd",
        )
    service_name = ""
    payload: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SERVICE_NAME"):
            service_name = stripped.split(":", 1)[-1].strip()
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            payload[key.strip().upper().replace(" ", "_")] = value.strip()
    if payload:
        state_text = payload.get("STATE", "")
        match = re.search(r"\b(RUNNING|STOPPED|PAUSED|START_PENDING|STOP_PENDING)\b", state_text, flags=re.IGNORECASE)
        state = "unknown"
        if match:
            normalized = match.group(1).lower()
            state = "running" if normalized == "running" else normalized
        return _normalize_feedback_service_status(
            {
                "adapter": "windows_service",
                "source_file": str(source_file),
                "service_name": service_name or payload.get("SERVICE_NAME", ""),
                "state": state,
                "raw_state": state_text,
                "last_exit_code": payload.get("WIN32_EXIT_CODE", ""),
                "result": payload.get("SERVICE_EXIT_CODE", ""),
            },
            source="windows_service",
        )
    return _normalize_feedback_service_status(
        {
            "adapter": "manual",
            "source_file": str(source_file),
            "state": "unknown",
            "raw_excerpt": text[:200],
        },
        source="text",
    )


def _normalize_feedback_service_status(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    state = str(payload.get("state") or payload.get("status") or "unknown").strip().lower()
    return {
        "artifact_type": "runtime_deployment_service_status",
        "status": "running" if state in {"running", "active", "ok"} else state,
        "state": state,
        "source": source,
        "adapter": str(payload.get("adapter", "")),
        "source_file": str(payload.get("source_file", "")),
        "service_name": str(payload.get("service_name", payload.get("name", ""))),
        "restart_count": _int_first(payload.get("restart_count"), payload.get("restarts"), default=0),
        "last_exit_code": payload.get("last_exit_code", payload.get("exit_code", "")),
        "result": payload.get("result", ""),
        "raw_state": payload.get("raw_state", ""),
        "raw_excerpt": payload.get("raw_excerpt", ""),
        "provenance": "Normalized post-install service status feedback.",
    }


def _deployment_log_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "artifact_type": "runtime_deployment_log",
            "status": "not_configured",
            "source_file": "",
            "record_count": 0,
            "applied_count": 0,
            "dry_run_count": 0,
            "error_count": 0,
            "latest_action": "",
            "provenance": "No deployment log file configured.",
        }
    text = _read_text(path)
    if not text:
        return {
            "artifact_type": "runtime_deployment_log",
            "status": "missing",
            "source_file": str(path),
            "record_count": 0,
            "applied_count": 0,
            "dry_run_count": 0,
            "error_count": 0,
            "latest_action": "",
            "provenance": "Deployment log file was missing or empty.",
        }
    records = _parse_deployment_log_records(text)
    error_count = sum(1 for item in records if str(item.get("status", "")).lower() in {"fail", "failed", "error"} or int(item.get("exit_code", 0) or 0) != 0)
    applied_count = sum(1 for item in records if _truthy(item.get("applied", item.get("apply", False))))
    dry_run_count = sum(1 for item in records if _truthy(item.get("dry_run", False)))
    latest_action = str(records[-1].get("action", records[-1].get("kind", ""))) if records else ""
    return {
        "artifact_type": "runtime_deployment_log",
        "status": "fail" if error_count else ("applied" if applied_count else "dry_run" if dry_run_count else "recorded"),
        "source_file": str(path),
        "record_count": len(records),
        "applied_count": applied_count,
        "dry_run_count": dry_run_count,
        "error_count": error_count,
        "latest_action": latest_action,
        "records": records[:20],
        "provenance": "Parsed target-host deployment feedback log.",
    }


def _parse_deployment_log_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                records.append(payload)
                continue
        except json.JSONDecodeError:
            pass
        lowered = stripped.lower()
        records.append(
            {
                "action": "rollback" if "rollback" in lowered else "install" if "install" in lowered else "status",
                "status": "failed" if any(token in lowered for token in ("error", "failed", "exception")) else "success",
                "applied": "apply" in lowered or "enabled" in lowered or "started" in lowered,
                "dry_run": "dry-run" in lowered or "dry run" in lowered,
                "raw": stripped[:300],
            }
        )
    return records


def _feedback_checks(
    *,
    feedback_config: dict[str, Any],
    expected_service: str,
    service_status: dict[str, Any],
    install_log: dict[str, Any],
    rollback_log: dict[str, Any],
) -> list[dict[str, Any]]:
    require_install = _truthy(feedback_config.get("require_install_record", True))
    require_running = _truthy(feedback_config.get("require_running", True))
    require_rollback = _truthy(feedback_config.get("require_rollback_success", False))
    service_name = str(service_status.get("service_name", ""))
    return [
        _check(
            "post_install_service_state",
            service_status.get("state") in {"running", "active", "ok"} if require_running else service_status.get("state") not in {"failed", "missing"},
            measured=service_status.get("state", ""),
            threshold="running/active" if require_running else "not failed/missing",
            severity="fail" if require_running else "warn",
            failure_message="Post-install service status is not acceptable.",
        ),
        _check(
            "install_record",
            install_log.get("record_count", 0) > 0 and install_log.get("error_count", 0) == 0 if require_install else install_log.get("status") != "fail",
            measured=install_log.get("status", ""),
            threshold="recorded without errors" if require_install else "not fail",
            severity="fail" if require_install else "warn",
            failure_message="Install feedback record is missing or reports errors.",
        ),
        _check(
            "rollback_record",
            rollback_log.get("record_count", 0) > 0 and rollback_log.get("error_count", 0) == 0 if require_rollback else rollback_log.get("status") != "fail",
            measured=rollback_log.get("status", ""),
            threshold="rollback recorded without errors" if require_rollback else "not fail",
            severity="fail" if require_rollback else "warn",
            failure_message="Rollback feedback record is missing or reports errors.",
        ),
        _check(
            "service_name_match",
            not expected_service or not service_name or expected_service in service_name,
            measured=service_name,
            threshold=expected_service or "not constrained",
            severity="warn",
            failure_message="Post-install service status does not match the planned service name.",
        ),
    ]


def _feedback_recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        if item.get("status") == "pass":
            continue
        check_id = str(item.get("check_id", ""))
        if check_id == "post_install_service_state":
            actions.append("Collect fresh systemd/Windows Service status after deployment and verify the runtime service is running.")
        elif check_id == "install_record":
            actions.append("Attach the target-host install log or rerun the guarded install script with deployment logging enabled.")
        elif check_id == "rollback_record":
            actions.append("Attach rollback verification if rollback was required for this delivery.")
        elif check_id == "service_name_match":
            actions.append("Verify the installed service name matches the generated installable runtime profile.")
        else:
            actions.append(f"Review runtime deployment feedback check {check_id}.")
    return list(dict.fromkeys(actions))


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


def _feedback_path(value: Any, *, runtime_root: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = runtime_root / path
    return path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


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


def _int_first(*values: Any, default: int) -> int:
    return int(_float_first(*values, default=float(default)))
