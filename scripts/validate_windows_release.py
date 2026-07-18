from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.windows_signing import SigningError, authenticode_info  # noqa: E402


FORBIDDEN_RELEASE_TERMS = ("eddypro", "eddy pro")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _stream_sha256(handle) -> str:  # noqa: ANN001
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest().upper()


def _is_prerelease(version: str) -> bool:
    return bool(re.search(r"(?:a|b|rc|dev)\d*", version, flags=re.IGNORECASE))


def _load_manifest(root: Path, blockers: list[str]) -> dict[str, object]:
    path = root / "build-manifest.json"
    if not path.is_file():
        blockers.append("build_manifest_missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blockers.append("build_manifest_invalid")
        return {}
    if not isinstance(payload, dict):
        blockers.append("build_manifest_invalid")
        return {}
    return payload


def _validate_manifest_files(root: Path, manifest: dict[str, object], blockers: list[str]) -> dict[str, str]:
    files = manifest.get("files", {})
    if not isinstance(files, dict) or not files:
        blockers.append("manifest_files_missing")
        return {}
    verified: dict[str, str] = {}
    for raw_name, raw_metadata in files.items():
        name = str(raw_name)
        if Path(name).name != name or not isinstance(raw_metadata, dict):
            blockers.append(f"manifest_file_entry_invalid:{name}")
            continue
        path = root / name
        if not path.is_file():
            blockers.append(f"manifest_file_missing:{name}")
            continue
        try:
            expected_size = int(raw_metadata.get("bytes", -1))
        except (TypeError, ValueError):
            blockers.append(f"manifest_file_size_invalid:{name}")
            expected_size = -1
        expected_hash = str(raw_metadata.get("sha256", "")).upper()
        actual_hash = _sha256(path)
        if path.stat().st_size != expected_size:
            blockers.append(f"manifest_file_size_mismatch:{name}")
        if actual_hash != expected_hash:
            blockers.append(f"manifest_file_hash_mismatch:{name}")
        verified[name] = actual_hash
    return verified


def _validate_sums(root: Path, verified: dict[str, str], blockers: list[str]) -> None:
    sums_path = root / "SHA256SUMS.txt"
    if not sums_path.is_file():
        blockers.append("sha256sums_missing")
        return
    try:
        lines = sums_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        blockers.append("sha256sums_invalid")
        return
    declared: dict[str, str] = {}
    for line in lines:
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            declared[parts[1].strip()] = parts[0].upper()
    for name, actual_hash in verified.items():
        if declared.get(name) != actual_hash:
            blockers.append(f"sha256sums_mismatch:{name}")


def _validate_zip(root: Path, verified: dict[str, str], blockers: list[str]) -> dict[str, object]:
    archives = [root / name for name in verified if name.lower().endswith(".zip")]
    executables = [name for name in verified if name.lower().endswith(".exe")]
    if len(archives) != 1:
        blockers.append("release_zip_count_invalid")
        return {}
    if len(executables) != 1:
        blockers.append("release_executable_count_invalid")
        return {}
    archive_path = archives[0]
    executable_name = executables[0]
    try:
        with ZipFile(archive_path) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            executable_members = [name for name in members if Path(name).name == executable_name]
            readme_members = [name for name in members if Path(name).name == "RC_README.txt"]
            if len(executable_members) != 1:
                blockers.append("release_zip_executable_missing")
            else:
                with archive.open(executable_members[0]) as handle:
                    if _stream_sha256(handle) != verified[executable_name]:
                        blockers.append("release_zip_executable_hash_mismatch")
            if len(readme_members) != 1:
                blockers.append("release_zip_readme_missing")
            elif "RC_README.txt" not in verified:
                blockers.append("release_readme_not_manifested")
            else:
                with archive.open(readme_members[0]) as handle:
                    if _stream_sha256(handle) != verified["RC_README.txt"]:
                        blockers.append("release_zip_readme_hash_mismatch")
            expected_member_names = {executable_name, "RC_README.txt"}
            unexpected_members = [name for name in members if Path(name).name not in expected_member_names]
            if unexpected_members:
                blockers.append("release_zip_unexpected_members")
            for member in members:
                normalized_member = member.casefold()
                if any(term in normalized_member for term in FORBIDDEN_RELEASE_TERMS):
                    blockers.append("forbidden_release_zip_member")
                    break
            return {"path": str(archive_path), "members": members}
    except (BadZipFile, OSError, ValueError):
        blockers.append("release_zip_invalid")
        return {}


def _scan_release_text(root: Path, blockers: list[str]) -> None:
    readme = root / "RC_README.txt"
    if not readme.is_file():
        blockers.append("release_readme_missing")
        return
    try:
        text = readme.read_text(encoding="utf-8").casefold()
    except (OSError, UnicodeError):
        blockers.append("release_readme_invalid")
        return
    for term in FORBIDDEN_RELEASE_TERMS:
        if term in text:
            blockers.append(f"forbidden_release_term:{term.replace(' ', '_')}")


def build_release_validation(
    artifact_root: Path,
    *,
    expected_commit: str = "",
    expected_version: str = "",
    require_final: bool = False,
    verify_authenticode: bool = True,
) -> dict[str, object]:
    root = artifact_root.resolve()
    blockers: list[str] = []
    manifest = _load_manifest(root, blockers)
    version = str(manifest.get("version", ""))
    release_channel = str(manifest.get("release_channel", "") or ("rc" if _is_prerelease(version) else "final"))

    if manifest.get("status") != "pass":
        blockers.append("build_status_not_passed")
    if manifest.get("smoke_status") != "pass":
        blockers.append("smoke_status_not_passed")
    actual_commit = str(manifest.get("git_commit", ""))
    if expected_commit and actual_commit.casefold() != expected_commit.casefold():
        blockers.append("git_commit_mismatch")
    if expected_version and version != expected_version:
        blockers.append("version_mismatch")
    if require_final and (_is_prerelease(version) or release_channel != "final"):
        blockers.append("final_version_required")

    signing = manifest.get("signing", {})
    signing = signing if isinstance(signing, dict) else {}
    if manifest.get("signing_status") != "Valid" or signing.get("status") != "Valid":
        blockers.append("signature_status_not_valid")
    if signing.get("verification") != "signtool_and_authenticode":
        blockers.append("signature_verification_incomplete")
    if not str(signing.get("signer_thumbprint", "")).strip():
        blockers.append("signer_thumbprint_missing")
    if not str(signing.get("timestamp_subject", "")).strip():
        blockers.append("trusted_timestamp_missing")

    verified = _validate_manifest_files(root, manifest, blockers)
    _validate_sums(root, verified, blockers)
    zip_summary = _validate_zip(root, verified, blockers)
    _scan_release_text(root, blockers)

    executable_names = [name for name in verified if name.lower().endswith(".exe")]
    authenticode: dict[str, object] = {}
    if verify_authenticode and len(executable_names) == 1:
        if os.name != "nt":
            blockers.append("authenticode_verification_requires_windows")
        else:
            try:
                authenticode = authenticode_info(root / executable_names[0])
            except SigningError:
                blockers.append("authenticode_verification_failed")
            else:
                if authenticode.get("status") != "Valid":
                    blockers.append("authenticode_status_not_valid")
                if not str(authenticode.get("timestamp_subject", "")).strip():
                    blockers.append("authenticode_timestamp_missing")
                if str(authenticode.get("signer_thumbprint", "")).casefold() != str(
                    signing.get("signer_thumbprint", "")
                ).casefold():
                    blockers.append("authenticode_signer_mismatch")

    return {
        "artifact_type": "windows_release_validation_v1",
        "status": "pass" if not blockers else "blocked",
        "artifact_root": str(root),
        "version": version,
        "release_channel": release_channel,
        "git_commit": actual_commit,
        "expected_commit": expected_commit,
        "expected_version": expected_version,
        "require_final": require_final,
        "signing": signing,
        "authenticode": authenticode,
        "verified_files": verified,
        "zip": zip_summary,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a signed Windows release package before promotion.")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--skip-authenticode", action="store_true", help="Only for non-Windows unit or metadata checks.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_release_validation(
        args.artifact_root,
        expected_commit=args.expected_commit,
        expected_version=args.expected_version,
        require_final=args.require_final,
        verify_authenticode=not args.skip_authenticode,
    )
    output = args.output or args.artifact_root / "release-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
