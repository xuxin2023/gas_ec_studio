from __future__ import annotations

import hashlib
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import bootstrap_windows_signing_tools, build_windows_rc, windows_signing


def test_certificate_usability_requires_private_key_and_future_expiry() -> None:
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    assert build_windows_rc._certificate_is_usable({"has_private_key": True, "not_after": future})
    assert not build_windows_rc._certificate_is_usable({"has_private_key": False, "not_after": future})
    assert not build_windows_rc._certificate_is_usable({"has_private_key": True, "not_after": past})


def test_release_channel_detection_distinguishes_prerelease_versions() -> None:
    assert build_windows_rc._release_channel_for_version("0.1.0rc1") == "rc"
    assert build_windows_rc._release_channel_for_version("0.1.0.dev2") == "rc"
    assert build_windows_rc._release_channel_for_version("0.1.0") == "final"


def test_packaged_smoke_waits_for_success(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class FakeProcess:
        pid = 123

        def wait(self, *, timeout: int) -> int:
            observed["timeout"] = timeout
            return 0

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(build_windows_rc.subprocess, "Popen", fake_popen)

    build_windows_rc._run_packaged_smoke(
        ["app.exe", "--smoke-report", "report.json"],
        cwd=tmp_path,
        env={"QT_QPA_PLATFORM": "offscreen"},
    )

    assert observed["timeout"] == build_windows_rc.PACKAGED_SMOKE_TIMEOUT_SECONDS
    assert observed["command"] == ["app.exe", "--smoke-report", "report.json"]


def test_packaged_smoke_terminates_process_tree_on_timeout(monkeypatch, tmp_path: Path) -> None:
    terminated: list[object] = []

    class FakeProcess:
        pid = 456

        def wait(self, *, timeout: int) -> int:
            raise subprocess.TimeoutExpired(["app.exe"], timeout)

    process = FakeProcess()
    monkeypatch.setattr(build_windows_rc.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(build_windows_rc, "_terminate_process_tree", terminated.append)

    with pytest.raises(subprocess.TimeoutExpired):
        build_windows_rc._run_packaged_smoke(["app.exe"], cwd=tmp_path, env={})

    assert terminated == [process]


def test_normalize_thumbprint_accepts_spacing_and_rejects_invalid() -> None:
    source = "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88 99 AA BB CC DD"

    assert windows_signing.normalize_thumbprint(source) == source.replace(" ", "")
    with pytest.raises(windows_signing.SigningError, match="40-character"):
        windows_signing.normalize_thumbprint("not-a-thumbprint")


def test_powershell_signing_query_uses_clean_windows_module_path(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(windows_signing.subprocess, "run", fake_run)
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")

    assert windows_signing._powershell_json("'ok' | ConvertTo-Json") == {}
    assert observed["command"][0] == "powershell.exe"
    assert "PSModulePath" not in observed["env"]


def test_find_signtool_uses_pinned_build_cache(monkeypatch, tmp_path: Path) -> None:
    cache_root = tmp_path / "windows-sdk"
    monkeypatch.setattr(windows_signing, "WINDOWS_SDK_BUILD_TOOLS_ROOT", cache_root)
    monkeypatch.setattr(windows_signing.shutil, "which", lambda _name: None)
    tool = windows_signing.bundled_signtool_path()
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"tool")
    monkeypatch.setattr(windows_signing, "WINDOWS_SDK_SIGNTOOL_SHA256", hashlib.sha256(b"tool").hexdigest().upper())

    assert windows_signing.find_signtool() == tool.resolve()


def test_find_signtool_rejects_tampered_build_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(windows_signing, "WINDOWS_SDK_BUILD_TOOLS_ROOT", tmp_path / "windows-sdk")
    tool = windows_signing.bundled_signtool_path()
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"tampered")

    with pytest.raises(windows_signing.SigningError, match="Bundled SignTool SHA-256 mismatch"):
        windows_signing.find_signtool()


def test_signing_tool_hash_validation_fails_closed(tmp_path: Path) -> None:
    payload = tmp_path / "package.nupkg"
    payload.write_bytes(b"unexpected")

    with pytest.raises(windows_signing.SigningError, match="SHA-256 mismatch"):
        bootstrap_windows_signing_tools._assert_hash(payload, "0" * 64, "test package")


def test_signing_tool_extraction_rejects_parent_traversal(tmp_path: Path) -> None:
    package = tmp_path / "unsafe.nupkg"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with pytest.raises(windows_signing.SigningError, match="unsafe path"):
        bootstrap_windows_signing_tools._extract_package(package, tmp_path / "extract")
    assert not (tmp_path / "outside.txt").exists()


def test_prepare_signing_request_fails_closed_without_identity() -> None:
    with pytest.raises(windows_signing.SigningError, match="trusted code-signing certificate"):
        windows_signing.prepare_signing_request(
            signtool=None,
            timestamp_url="https://timestamp.example.test",
            certificate_thumbprint="",
            certificate_store="CurrentUser",
            pfx_path=None,
            pfx_password_env="GAS_EC_SIGN_PFX_PASSWORD",
            require_signature=True,
        )


def test_prepare_store_request_validates_tool_certificate_and_timestamp(monkeypatch, tmp_path: Path) -> None:
    tool = tmp_path / "signtool.exe"
    tool.write_bytes(b"tool")
    thumbprint = "A" * 40
    monkeypatch.setattr(windows_signing, "find_signtool", lambda _configured=None: tool)
    monkeypatch.setattr(
        windows_signing,
        "certificate_store_info",
        lambda requested, store: {"thumbprint": requested, "store": store, "subject": "CN=Release"},
    )

    request, certificate = windows_signing.prepare_signing_request(
        signtool=tool,
        timestamp_url="https://timestamp.example.test",
        certificate_thumbprint=thumbprint,
        certificate_store="LocalMachine",
        pfx_path=None,
        pfx_password_env="GAS_EC_SIGN_PFX_PASSWORD",
        require_signature=True,
    )

    assert request is not None
    assert request.certificate_thumbprint == thumbprint
    assert request.certificate_store == "LocalMachine"
    assert request.timestamp_url == "https://timestamp.example.test"
    assert certificate["subject"] == "CN=Release"


def test_sign_and_verify_requires_valid_timestamped_requested_certificate(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"binary")
    tool = tmp_path / "signtool.exe"
    tool.write_bytes(b"tool")
    thumbprint = "B" * 40
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(windows_signing.subprocess, "run", fake_run)
    monkeypatch.setattr(
        windows_signing,
        "authenticode_info",
        lambda _path: {
            "status": "Valid",
            "signer_subject": "CN=Release",
            "signer_thumbprint": thumbprint,
            "timestamp_subject": "CN=Timestamp",
        },
    )
    request = windows_signing.SigningRequest(
        signtool=tool,
        timestamp_url="https://timestamp.example.test",
        certificate_thumbprint=thumbprint,
        certificate_store="LocalMachine",
    )

    result = windows_signing.sign_and_verify(executable, request)

    assert result["status"] == "Valid"
    assert result["verification"] == "signtool_and_authenticode"
    assert commands[0][1:8] == ["sign", "/fd", "SHA256", "/tr", "https://timestamp.example.test", "/td", "SHA256"]
    assert "/sm" in commands[0]
    assert commands[1][1:5] == ["verify", "/pa", "/all", "/v"]


def test_sign_and_verify_rejects_missing_timestamp(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"binary")
    tool = tmp_path / "signtool.exe"
    tool.write_bytes(b"tool")
    monkeypatch.setattr(
        windows_signing.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr(
        windows_signing,
        "authenticode_info",
        lambda _path: {"status": "Valid", "signer_thumbprint": "C" * 40, "timestamp_subject": ""},
    )
    request = windows_signing.SigningRequest(
        signtool=tool,
        timestamp_url="https://timestamp.example.test",
        certificate_thumbprint="C" * 40,
    )

    with pytest.raises(windows_signing.SigningError, match="no trusted timestamp"):
        windows_signing.sign_and_verify(executable, request)
