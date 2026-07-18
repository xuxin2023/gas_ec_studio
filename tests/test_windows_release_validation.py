from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from scripts import validate_windows_release


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _build_release_fixture(root: Path, *, version: str = "0.1.0rc1") -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    display_version = version.replace("rc", "-rc")
    executable = root / f"GasECStudio-{display_version}-win64.exe"
    readme = root / "RC_README.txt"
    archive_path = root / f"GasECStudio-{display_version}-win64.zip"
    executable.write_bytes(b"signed-executable")
    readme.write_text(f"Gas EC Studio {display_version}\nValidated release package.\n", encoding="utf-8")
    with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
        archive.write(executable, f"GasECStudio-{display_version}-win64/{executable.name}")
        archive.write(readme, f"GasECStudio-{display_version}-win64/{readme.name}")

    commit = "A" * 40
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in (executable, archive_path, readme)
    }
    signing = {
        "status": "Valid",
        "verification": "signtool_and_authenticode",
        "identity_mode": "pfx",
        "signer_thumbprint": "B" * 40,
        "timestamp_subject": "CN=Timestamp",
    }
    manifest = {
        "status": "pass",
        "version": version,
        "release_channel": "rc" if "rc" in version else "final",
        "git_commit": commit,
        "signing_status": "Valid",
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


def test_signed_rc_release_validation_passes(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(tmp_path, expected_commit=commit)

    assert report["status"] == "pass"
    assert report["blockers"] == []


def test_final_validation_rejects_rc_version(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(tmp_path, expected_commit=commit, require_final=True)

    assert report["status"] == "blocked"
    assert "final_version_required" in report["blockers"]


def test_signed_final_release_validation_passes(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path, version="0.1.0")
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(
        tmp_path,
        expected_commit=commit,
        expected_version="0.1.0",
        require_final=True,
    )

    assert report["status"] == "pass"
    assert report["release_channel"] == "final"


def test_release_validation_rejects_version_mismatch(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

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
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(tmp_path, expected_commit=commit)

    assert report["status"] == "blocked"
    assert f"manifest_file_hash_mismatch:{executable.name}" in report["blockers"]


def test_release_validation_detects_zip_readme_tampering(monkeypatch, tmp_path: Path) -> None:
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
        "".join(f"{metadata['sha256']}  {name}\n" for name, metadata in manifest["files"].items()),
        encoding="ascii",
    )
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(tmp_path, expected_commit=commit)

    assert report["status"] == "blocked"
    assert "release_zip_readme_hash_mismatch" in report["blockers"]


def test_release_validation_rejects_forbidden_release_text(monkeypatch, tmp_path: Path) -> None:
    _executable, commit = _build_release_fixture(tmp_path)
    (tmp_path / "RC_README.txt").write_text("EddyPro compatibility package", encoding="utf-8")
    monkeypatch.setattr(validate_windows_release, "authenticode_info", _valid_authenticode)

    report = validate_windows_release.build_release_validation(tmp_path, expected_commit=commit)

    assert report["status"] == "blocked"
    assert "forbidden_release_term:eddypro" in report["blockers"]
