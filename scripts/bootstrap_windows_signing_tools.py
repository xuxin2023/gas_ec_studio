from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.windows_signing import (  # noqa: E402
    SigningError,
    WINDOWS_SDK_BUILD_TOOLS_ROOT,
    WINDOWS_SDK_BUILD_TOOLS_VERSION,
    WINDOWS_SDK_SIGNTOOL_SHA256,
    authenticode_info,
    bundled_signtool_path,
)


PACKAGE_ID = "microsoft.windows.sdk.buildtools"
PACKAGE_SHA256 = "D939FA052F9C80F878B2A28B7071A6F2C9A51029018BB87A835EBDA6E535A002"
PACKAGE_URL = (
    f"https://api.nuget.org/v3-flatcontainer/{PACKAGE_ID}/{WINDOWS_SDK_BUILD_TOOLS_VERSION}/"
    f"{PACKAGE_ID}.{WINDOWS_SDK_BUILD_TOOLS_VERSION}.nupkg"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _assert_hash(path: Path, expected: str, label: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise SigningError(f"{label} SHA-256 mismatch: expected {expected}, received {actual}")


def _download_package(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = Request(PACKAGE_URL, headers={"User-Agent": "GasECStudio-WindowsSigningBootstrap/1.0"})
    try:
        with urlopen(request, timeout=120) as response, partial.open("wb") as target:  # noqa: S310
            shutil.copyfileobj(response, target)
        _assert_hash(partial, PACKAGE_SHA256, "Windows SDK Build Tools package")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _extract_package(package_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with ZipFile(package_path) as archive:
        for member in archive.infolist():
            try:
                (destination / member.filename).resolve().relative_to(resolved_destination)
            except ValueError as exc:
                raise SigningError(f"Windows SDK package contains an unsafe path: {member.filename}") from exc
        archive.extractall(destination)


def bootstrap_signing_tools(*, force_download: bool = False) -> dict[str, object]:
    package_root = WINDOWS_SDK_BUILD_TOOLS_ROOT / WINDOWS_SDK_BUILD_TOOLS_VERSION
    package_path = package_root / f"{PACKAGE_ID}.{WINDOWS_SDK_BUILD_TOOLS_VERSION}.nupkg"
    extract_root = package_root / "package"
    tool_path = bundled_signtool_path()

    if force_download:
        package_path.unlink(missing_ok=True)
    if not package_path.is_file():
        _download_package(package_path)
    _assert_hash(package_path, PACKAGE_SHA256, "Windows SDK Build Tools package")

    if not tool_path.is_file():
        _extract_package(package_path, extract_root)
    if not tool_path.is_file():
        raise SigningError(f"The pinned package does not contain the expected x64 SignTool: {tool_path}")
    _assert_hash(tool_path, WINDOWS_SDK_SIGNTOOL_SHA256, "SignTool")

    signature = authenticode_info(tool_path)
    if signature.get("status") != "Valid":
        raise SigningError(f"The downloaded SignTool signature is not valid: {signature.get('status', 'unknown')}")
    probe = subprocess.run([str(tool_path), "/?"], text=True, capture_output=True, check=False)
    if probe.returncode != 0:
        raise SigningError(f"SignTool executable probe failed with exit code {probe.returncode}.")

    return {
        "status": "ready",
        "package": str(package_path),
        "package_version": WINDOWS_SDK_BUILD_TOOLS_VERSION,
        "package_sha256": PACKAGE_SHA256,
        "signtool": str(tool_path),
        "signtool_sha256": WINDOWS_SDK_SIGNTOOL_SHA256,
        "signtool_signature": signature,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the pinned Windows SDK SignTool into the project build cache.")
    parser.add_argument("--force-download", action="store_true", help="Redownload the pinned NuGet package.")
    args = parser.parse_args()
    print(json.dumps(bootstrap_signing_tools(force_download=args.force_download), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SigningError as exc:
        print(f"Signing tool bootstrap blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
