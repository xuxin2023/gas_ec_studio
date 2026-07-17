from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import build_windows_rc, windows_signing


def test_certificate_usability_requires_private_key_and_future_expiry() -> None:
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    assert build_windows_rc._certificate_is_usable({"has_private_key": True, "not_after": future})
    assert not build_windows_rc._certificate_is_usable({"has_private_key": False, "not_after": future})
    assert not build_windows_rc._certificate_is_usable({"has_private_key": True, "not_after": past})


def test_normalize_thumbprint_accepts_spacing_and_rejects_invalid() -> None:
    source = "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88 99 AA BB CC DD"

    assert windows_signing.normalize_thumbprint(source) == source.replace(" ", "")
    with pytest.raises(windows_signing.SigningError, match="40-character"):
        windows_signing.normalize_thumbprint("not-a-thumbprint")


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
