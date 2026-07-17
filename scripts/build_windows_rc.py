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
from scripts.windows_signing import (  # noqa: E402
    SigningError,
    authenticode_info,
    find_signtool,
    list_code_signing_certificates,
    prepare_signing_request,
    sign_and_verify,
)


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


def _certificate_is_usable(certificate: dict[str, object]) -> bool:
    if not bool(certificate.get("has_private_key")):
        return False
    try:
        expires_at = datetime.fromisoformat(str(certificate["not_after"]))
    except (KeyError, TypeError, ValueError):
        return False
    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
    return expires_at > now


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify the Windows RC package.")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "artifacts" / "windows_rc")
    parser.add_argument("--work-root", type=Path, default=PROJECT_ROOT / ".build" / "windows_rc")
    parser.add_argument("--incremental", action="store_true", help="Reuse the existing PyInstaller analysis cache.")
    parser.add_argument("--require-signature", action="store_true", help="Fail unless the output is validly signed and timestamped.")
    parser.add_argument("--certificate-thumbprint", default="", help="SHA-1 thumbprint in the Windows certificate store.")
    parser.add_argument("--certificate-store", choices=("CurrentUser", "LocalMachine"), default="CurrentUser")
    parser.add_argument("--pfx", type=Path, help="PFX code-signing certificate path.")
    parser.add_argument("--pfx-password-env", default="GAS_EC_SIGN_PFX_PASSWORD")
    parser.add_argument("--timestamp-url", default=os.environ.get("GAS_EC_TIMESTAMP_URL", ""))
    parser.add_argument("--signtool", type=Path, help="Explicit signtool.exe path.")
    parser.add_argument("--signing-preflight-only", action="store_true", help="Validate signing inputs without building.")
    parser.add_argument("--signing-audit", action="store_true", help="List local signing tools and certificates without building.")
    args = parser.parse_args()

    if args.signing_audit:
        tool = find_signtool(args.signtool)
        certificates = list_code_signing_certificates()
        usable_certificates = [certificate for certificate in certificates if _certificate_is_usable(certificate)]
        timestamp_url = str(args.timestamp_url or "").strip()
        timestamp_ready = timestamp_url.startswith(("https://", "http://"))
        blockers = [
            *([] if tool else ["signtool_not_found"]),
            *([] if usable_certificates else ["usable_code_signing_certificate_not_found"]),
            *([] if timestamp_ready else ["timestamp_url_not_configured"]),
        ]
        payload = {
            "status": "ready" if not blockers else "blocked",
            "signtool": str(tool or ""),
            "timestamp_url": timestamp_url,
            "certificates": certificates,
            "usable_certificate_count": len(usable_certificates),
            "blockers": blockers,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "ready" else 2

    signing_request, signing_certificate = prepare_signing_request(
        signtool=args.signtool,
        timestamp_url=args.timestamp_url,
        certificate_thumbprint=args.certificate_thumbprint,
        certificate_store=args.certificate_store,
        pfx_path=args.pfx,
        pfx_password_env=args.pfx_password_env,
        require_signature=args.require_signature or args.signing_preflight_only,
    )
    if args.signing_preflight_only:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "signtool": str(signing_request.signtool if signing_request else ""),
                    "certificate": signing_certificate,
                    "timestamp_url": signing_request.timestamp_url if signing_request else "",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

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

    if signing_request is not None:
        signing = sign_and_verify(exe_path, signing_request)
    else:
        signing = authenticode_info(exe_path)
        signing["identity_mode"] = "none"
        signing["verification"] = "authenticode_only"
    signing_status = str(signing.get("status", "not_checked"))
    if args.require_signature and signing_status != "Valid":
        raise SigningError(f"A valid signature is required, received: {signing_status}")

    readme_template = (PROJECT_ROOT / "packaging" / "RC_README.txt").read_text(encoding="utf-8")
    readme_path = output_root / "RC_README.txt"
    signing_note = (
        f"本可执行文件已完成代码签名与时间戳验证，签名者：{signing.get('signer_subject', '--')}。"
        if signing_status == "Valid"
        else "当前可执行文件未进行商业代码签名，Windows 可能显示未知发布者提示。"
    )
    readme_path.write_text(
        readme_template.replace("{{VERSION}}", display_version).replace("{{SIGNING_NOTE}}", signing_note),
        encoding="utf-8",
    )

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
        "signing": signing,
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
    try:
        raise SystemExit(main())
    except SigningError as exc:
        print(f"Signing gate blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
