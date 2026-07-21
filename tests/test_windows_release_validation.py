from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from scripts.build_windows_rc import _windows_version_tuple, _write_windows_version_info
from scripts import validate_windows_release


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _build_release_fixture(
    root: Path,
    *,
    version: str = "0.1.0rc1",
    signed: bool = True,
    include_unsigned_warning: bool = True,
) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    display_version = version.replace("rc", "-rc")
    executable = root / f"GasECStudio-{display_version}-win64.exe"
    readme = root / "RC_README.txt"
    archive_path = root / f"GasECStudio-{display_version}-win64.zip"
    executable.write_bytes(b"signed-executable")
    readme_text = f"Gas EC Studio {display_version}\nValidated release package.\n"
    if not signed and include_unsigned_warning:
        readme_text += "当前候选版本未签名，Windows 可能显示未知发布者提示。\n"
    readme.write_text(readme_text, encoding="utf-8")
    with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
        archive.write(
            executable, f"GasECStudio-{display_version}-win64/{executable.name}"
        )
        archive.write(readme, f"GasECStudio-{display_version}-win64/{readme.name}")

    commit = "A" * 40
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in (executable, archive_path, readme)
    }
    signing = (
        {
            "status": "Valid",
            "verification": "signtool_and_authenticode",
            "identity_mode": "pfx",
            "signer_thumbprint": "B" * 40,
            "timestamp_subject": "CN=Timestamp",
        }
        if signed
        else {
            "status": "NotSigned",
            "verification": "authenticode_only",
            "identity_mode": "none",
            "signer_thumbprint": "",
            "timestamp_subject": "",
        }
    )
    manifest = {
        "status": "pass",
        "version": version,
        "release_channel": "rc" if "rc" in version else "final",
        "git_commit": commit,
        "signing_status": "Valid" if signed else "NotSigned",
        "signing": signing,
        "smoke_status": "pass",
        "files": files,
    }
    (root / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{metadata['sha256']}  {name}\n" for name, metadata in files.items()),
        encoding="ascii",
    )
    return executable, commit


def _valid_authenticode(_path: Path) -> dict[str, object]:
    return {
        "status": "Valid",
        "signer_thumbprint": "B" * 40,
        "timestamp_subject": "CN=Timestamp",
    }


def test_windows_version_info_is_generated_from_application_version(
    tmp_path: Path,
) -> None:
    version_info = tmp_path / "version_info.txt"

    _write_windows_version_info(
        version_info,
        app_version="0.1.0rc6",
        display_version="0.1.0 RC6",
    )

    content = version_info.read_text(encoding="utf-8")
    assert _windows_version_tuple("0.1.0rc6") == (0, 1, 0, 6)
    assert _windows_version_tuple("1.2.3") == (1, 2, 3, 0)
    assert "filevers=(0, 1, 0, 6)" in content
    assert "prodvers=(0, 1, 0, 6)" in content
    assert "StringStruct(u'FileVersion', u'0.1.0 RC6')" in content
    assert "StringStruct(u'ProductVersion', u'0.1.0 RC6')" in content


def test_signed_rc_release_validation_passes(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path, expected_commit=commit
    )

    assert report["status"] == "pass"
    assert report["blockers"] == []


def test_unsigned_rc_release_validation_requires_explicit_policy(
    tmp_path: Path,
) -> None:
    _executable, commit = _build_release_fixture(tmp_path, signed=False)

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        verify_authenticode=False,
    )

    assert report["status"] == "blocked"
    assert "signature_status_not_valid" in report["blockers"]


def test_unsigned_rc_release_validation_passes_with_disclosed_policy(
    tmp_path: Path,
) -> None:
    _executable, commit = _build_release_fixture(tmp_path, signed=False)

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        allow_unsigned_prerelease=True,
        verify_authenticode=False,
    )

    assert report["status"] == "pass"
    assert report["release_policy"] == "unsigned_prerelease"
    assert report["blockers"] == []


def test_unsigned_rc_release_validation_requires_readme_warning(tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(
        tmp_path,
        signed=False,
        include_unsigned_warning=False,
    )

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        allow_unsigned_prerelease=True,
        verify_authenticode=False,
    )

    assert report["status"] == "blocked"
    assert "unsigned_prerelease_warning_missing" in report["blockers"]


def test_unsigned_final_release_cannot_use_prerelease_policy(tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(
        tmp_path, version="0.1.0", signed=False
    )

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        require_final=True,
        allow_unsigned_prerelease=True,
        verify_authenticode=False,
    )

    assert report["status"] == "blocked"
    assert "unsigned_prerelease_policy_requires_rc" in report["blockers"]
    assert "signature_status_not_valid" in report["blockers"]


def test_final_validation_rejects_rc_version(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path, expected_commit=commit, require_final=True
    )

    assert report["status"] == "blocked"
    assert "final_version_required" in report["blockers"]


def test_signed_final_release_validation_passes(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path, version="0.1.0")
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        expected_version="0.1.0",
        require_final=True,
    )

    assert report["status"] == "pass"
    assert report["release_channel"] == "final"


def test_release_validation_rejects_version_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        expected_version="0.1.0",
    )

    assert report["status"] == "blocked"
    assert "version_mismatch" in report["blockers"]


def test_release_validation_detects_hash_tampering(monkeypatch, tmp_path: Path) -> None:
    executable, commit = _build_release_fixture(tmp_path)
    executable.write_bytes(b"tampered")
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path, expected_commit=commit
    )

    assert report["status"] == "blocked"
    assert f"manifest_file_hash_mismatch:{executable.name}" in report["blockers"]


def test_release_validation_detects_zip_readme_tampering(
    monkeypatch, tmp_path: Path
) -> None:
    executable, commit = _build_release_fixture(tmp_path)
    archive_path = next(tmp_path.glob("*.zip"))
    with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
        archive.write(executable, f"release/{executable.name}")
        archive.writestr("release/RC_README.txt", "different internal release note")
    manifest_path = tmp_path / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][archive_path.name] = {
        "bytes": archive_path.stat().st_size,
        "sha256": _sha256(archive_path),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "SHA256SUMS.txt").write_text(
        "".join(
            f"{metadata['sha256']}  {name}\n"
            for name, metadata in manifest["files"].items()
        ),
        encoding="ascii",
    )
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path, expected_commit=commit
    )

    assert report["status"] == "blocked"
    assert "release_zip_readme_hash_mismatch" in report["blockers"]


def test_release_validation_rejects_forbidden_release_text(
    monkeypatch, tmp_path: Path
) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    (tmp_path / "RC_README.txt").write_text(
        "EddyPro compatibility package", encoding="utf-8"
    )
    monkeypatch.setattr(
        validate_windows_release, "authenticode_info", _valid_authenticode
    )

    report = validate_windows_release.build_release_validation(
        tmp_path, expected_commit=commit
    )

    assert report["status"] == "blocked"
    assert "forbidden_release_term:eddypro" in report["blockers"]
