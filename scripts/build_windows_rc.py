from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.version import APP_VERSION  # noqa: E402


RC_RUNTIME_MODULES = (
    "PySide6",
    "pyqtgraph",
    "serial",
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "h5py",
    "rasterio",
    "pyproj",
    "morecantile",
    "rio_cogeo",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _safe_reset_dir(path: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(PROJECT_ROOT.resolve())
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _authenticode_status(path: Path) -> str:
    if os.name != "nt":
        return "not_checked"
    escaped = str(path).replace("'", "''")
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-AuthenticodeSignature -LiteralPath '{escaped}').Status.ToString()",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "not_checked"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify the Windows RC package.")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "artifacts" / "windows_rc")
    parser.add_argument("--work-root", type=Path, default=PROJECT_ROOT / ".build" / "windows_rc")
    parser.add_argument("--incremental", action="store_true", help="Reuse the existing PyInstaller analysis cache.")
    args = parser.parse_args()

    missing_modules = [module for module in RC_RUNTIME_MODULES if importlib.util.find_spec(module) is None]
    if missing_modules:
        raise RuntimeError(f"Missing RC build dependencies: {', '.join(missing_modules)}")

    display_version = APP_VERSION.replace("rc", "-rc")
    build_name = f"GasECStudio-{display_version}-win64"
    work_root = args.work_root.resolve() / APP_VERSION
    output_root = args.output_root.resolve() / display_version
    if args.incremental:
        work_root.mkdir(parents=True, exist_ok=True)
    else:
        _safe_reset_dir(work_root)
    _safe_reset_dir(output_root)
    dist_root = work_root / "dist"
    pyinstaller_work = work_root / "pyinstaller"

    env = os.environ.copy()
    env["GAS_EC_BUILD_NAME"] = build_name
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(pyinstaller_work),
        str(PROJECT_ROOT / "packaging" / "gas_ec_studio.spec"),
    ]
    if not args.incremental:
        command.insert(4, "--clean")
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)

    built_exe = dist_root / f"{build_name}.exe"
    if not built_exe.exists() or built_exe.stat().st_size < 10_000_000:
        raise RuntimeError(f"PyInstaller output is missing or unexpectedly small: {built_exe}")
    exe_path = output_root / built_exe.name
    shutil.copy2(built_exe, exe_path)

    readme_template = (PROJECT_ROOT / "packaging" / "RC_README.txt").read_text(encoding="utf-8")
    readme_path = output_root / "RC_README.txt"
    readme_path.write_text(readme_template.replace("{{VERSION}}", display_version), encoding="utf-8")

    smoke_report = output_root / "packaged-smoke-report.json"
    smoke_screenshot = output_root / "packaged-smoke-report-center.png"
    smoke_workspace = work_root / "smoke_workspace"
    smoke_env = os.environ.copy()
    smoke_env["QT_QPA_PLATFORM"] = "offscreen"
    smoke_env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    subprocess.run(
        [
            str(exe_path),
            "--workspace-root",
            str(smoke_workspace),
            "--smoke-report",
            str(smoke_report),
            "--smoke-screenshot",
            str(smoke_screenshot),
        ],
        cwd=output_root,
        env=smoke_env,
        timeout=240,
        check=True,
    )
    smoke_payload = json.loads(smoke_report.read_text(encoding="utf-8"))
    if smoke_payload.get("status") != "pass":
        raise RuntimeError(f"Packaged smoke test failed: {smoke_payload}")

    zip_path = output_root / f"{build_name}.zip"
    with ZipFile(zip_path, "w", compression=ZIP_STORED) as archive:
        archive.write(exe_path, f"{build_name}/{exe_path.name}")
        archive.write(readme_path, f"{build_name}/{readme_path.name}")

    files = [exe_path, zip_path, readme_path, smoke_report, smoke_screenshot]
    hashes = {path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)} for path in files}
    signing_status = _authenticode_status(exe_path)
    manifest = {
        "status": "pass",
        "product": "Gas EC Studio",
        "version": APP_VERSION,
        "display_version": display_version,
        "built_at": datetime.now().isoformat(),
        "python": sys.version,
        "pyinstaller": subprocess.check_output([sys.executable, "-m", "PyInstaller", "--version"], text=True).strip(),
        "git_commit": _git_commit(),
        "platform": sys.platform,
        "signing_status": signing_status,
        "smoke_status": smoke_payload.get("status"),
        "smoke_workspace": str(smoke_workspace),
        "files": hashes,
    }
    manifest_path = output_root / "build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sums_path = output_root / "SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f"{payload['sha256']}  {name}\n" for name, payload in hashes.items()),
        encoding="ascii",
    )
    print(json.dumps({"output_root": str(output_root), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
