from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


CODE_SIGNING_EKU = "1.3.6.1.5.5.7.3.3"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SDK_BUILD_TOOLS_VERSION = "10.0.28000.2270"
WINDOWS_SDK_BIN_VERSION = "10.0.28000.0"
WINDOWS_SDK_BUILD_TOOLS_ROOT = PROJECT_ROOT / ".build" / "tools" / "windows-sdk"
WINDOWS_SDK_SIGNTOOL_SHA256 = "EB2C41BFA718DF21AB773FE0AAE119C79B6E8BA8A9CD475512B7DD42306FE7B7"


def bundled_signtool_path() -> Path:
    return (
        WINDOWS_SDK_BUILD_TOOLS_ROOT
        / WINDOWS_SDK_BUILD_TOOLS_VERSION
        / "package"
        / "bin"
        / WINDOWS_SDK_BIN_VERSION
        / "x64"
        / "signtool.exe"
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


class SigningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SigningRequest:
    signtool: Path
    timestamp_url: str
    certificate_thumbprint: str = ""
    certificate_store: str = "CurrentUser"
    pfx_path: Path | None = None
    pfx_password: str = ""

    @property
    def identity_mode(self) -> str:
        return "pfx" if self.pfx_path is not None else "certificate_store"


def _powershell_json(command: str, *, env: dict[str, str] | None = None) -> object:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit={result.returncode}"
        raise SigningError(f"PowerShell signing query failed: {detail}")
    output = result.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SigningError(f"PowerShell signing query returned invalid JSON: {output[:240]}") from exc


def normalize_thumbprint(value: str) -> str:
    normalized = "".join(character for character in str(value or "") if character.isalnum()).upper()
    if normalized and (len(normalized) != 40 or any(character not in "0123456789ABCDEF" for character in normalized)):
        raise SigningError("Certificate thumbprint must be a 40-character SHA-1 hexadecimal value.")
    return normalized


def find_signtool(explicit: Path | str | None = None) -> Path | None:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise SigningError(f"SignTool was not found at the configured path: {candidate}")
        return candidate

    bundled = bundled_signtool_path()
    if bundled.is_file():
        actual_hash = _file_sha256(bundled)
        if actual_hash != WINDOWS_SDK_SIGNTOOL_SHA256:
            raise SigningError(
                "Bundled SignTool SHA-256 mismatch: "
                f"expected {WINDOWS_SDK_SIGNTOOL_SHA256}, received {actual_hash}"
            )
        return bundled.resolve()

    discovered = shutil.which("signtool.exe") or shutil.which("signtool")
    if discovered:
        return Path(discovered).resolve()

    roots = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Windows Kits" / "10" / "bin",
        Path(os.environ.get("ProgramFiles", "")) / "Windows Kits" / "10" / "bin",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("*/x64/signtool.exe"))
            candidates.extend(root.glob("x64/signtool.exe"))
    return sorted((candidate.resolve() for candidate in candidates), reverse=True)[0] if candidates else None


def list_code_signing_certificates() -> list[dict[str, object]]:
    command = r"""
$rows = @()
foreach ($store in @('Cert:\CurrentUser\My', 'Cert:\LocalMachine\My')) {
    $scope = if ($store -like '*LocalMachine*') { 'LocalMachine' } else { 'CurrentUser' }
    foreach ($cert in @(Get-ChildItem -Path $store -CodeSigningCert -ErrorAction SilentlyContinue)) {
        $rows += [pscustomobject]@{
            store = $scope
            subject = $cert.Subject
            issuer = $cert.Issuer
            thumbprint = $cert.Thumbprint
            has_private_key = [bool]$cert.HasPrivateKey
            not_before = $cert.NotBefore.ToString('o')
            not_after = $cert.NotAfter.ToString('o')
        }
    }
}
@($rows) | ConvertTo-Json -Compress
"""
    payload = _powershell_json(command)
    if payload is None:
        return []
    return list(payload) if isinstance(payload, list) else [dict(payload)]


def certificate_store_info(thumbprint: str, store: str) -> dict[str, object]:
    normalized = normalize_thumbprint(thumbprint)
    if store not in {"CurrentUser", "LocalMachine"}:
        raise SigningError(f"Unsupported certificate store: {store}")
    command = rf"""
$thumb = '{normalized}'
$cert = Get-ChildItem -Path 'Cert:\{store}\My' -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Thumbprint -eq $thumb }} | Select-Object -First 1
if ($null -eq $cert) {{ throw 'Code-signing certificate not found in {store}\My.' }}
if (-not $cert.HasPrivateKey) {{ throw 'Code-signing certificate has no private key.' }}
if ($cert.NotAfter -le (Get-Date)) {{ throw 'Code-signing certificate is expired.' }}
[pscustomobject]@{{
    store = '{store}'
    subject = $cert.Subject
    issuer = $cert.Issuer
    thumbprint = $cert.Thumbprint
    has_private_key = [bool]$cert.HasPrivateKey
    not_before = $cert.NotBefore.ToString('o')
    not_after = $cert.NotAfter.ToString('o')
}} | ConvertTo-Json -Compress
"""
    payload = _powershell_json(command)
    if not isinstance(payload, dict):
        raise SigningError("Certificate store query did not return a certificate.")
    return payload


def pfx_certificate_info(path: Path, password_env: str, *, env: dict[str, str] | None = None) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SigningError(f"PFX file does not exist: {resolved}")
    process_env = dict(os.environ if env is None else env)
    password = str(process_env.get(password_env, ""))
    if not password:
        raise SigningError(f"PFX password environment variable is missing or empty: {password_env}")
    escaped_path = str(resolved).replace("'", "''")
    escaped_env_name = password_env.replace("'", "''")
    command = rf"""
$secure = ConvertTo-SecureString -String $env:{escaped_env_name} -AsPlainText -Force
$data = Get-PfxData -FilePath '{escaped_path}' -Password $secure
$cert = $data.EndEntityCertificates | Select-Object -First 1
if ($null -eq $cert) {{ throw 'PFX does not contain an end-entity certificate.' }}
$eku = @($cert.EnhancedKeyUsageList | ForEach-Object {{ $_.ObjectId.Value }})
if ('{CODE_SIGNING_EKU}' -notin $eku) {{ throw 'PFX certificate is not valid for code signing.' }}
if ($cert.NotAfter -le (Get-Date)) {{ throw 'PFX code-signing certificate is expired.' }}
[pscustomobject]@{{
    store = 'PFX'
    subject = $cert.Subject
    issuer = $cert.Issuer
    thumbprint = $cert.Thumbprint
    has_private_key = $true
    not_before = $cert.NotBefore.ToString('o')
    not_after = $cert.NotAfter.ToString('o')
}} | ConvertTo-Json -Compress
"""
    payload = _powershell_json(command, env=process_env)
    if not isinstance(payload, dict):
        raise SigningError("PFX query did not return a certificate.")
    return payload


def prepare_signing_request(
    *,
    signtool: Path | str | None,
    timestamp_url: str,
    certificate_thumbprint: str,
    certificate_store: str,
    pfx_path: Path | None,
    pfx_password_env: str,
    require_signature: bool,
    env: dict[str, str] | None = None,
) -> tuple[SigningRequest | None, dict[str, object]]:
    normalized_thumbprint = normalize_thumbprint(certificate_thumbprint)
    if normalized_thumbprint and pfx_path is not None:
        raise SigningError("Choose either a certificate thumbprint or a PFX file, not both.")
    identity_requested = bool(normalized_thumbprint or pfx_path is not None)
    if not identity_requested:
        if require_signature:
            raise SigningError("A trusted code-signing certificate is required; provide --certificate-thumbprint or --pfx.")
        return None, {}

    tool = find_signtool(signtool)
    if tool is None:
        raise SigningError("SignTool was not found. Install Windows SDK Signing Tools or pass --signtool.")
    timestamp = str(timestamp_url or "").strip()
    if not timestamp.startswith(("https://", "http://")):
        raise SigningError("A valid RFC 3161 timestamp URL is required via --timestamp-url.")

    process_env = dict(os.environ if env is None else env)
    if pfx_path is not None:
        certificate = pfx_certificate_info(pfx_path, pfx_password_env, env=process_env)
        password = str(process_env.get(pfx_password_env, ""))
        request = SigningRequest(
            signtool=tool,
            timestamp_url=timestamp,
            pfx_path=pfx_path.expanduser().resolve(),
            pfx_password=password,
        )
    else:
        certificate = certificate_store_info(normalized_thumbprint, certificate_store)
        request = SigningRequest(
            signtool=tool,
            timestamp_url=timestamp,
            certificate_thumbprint=normalized_thumbprint,
            certificate_store=certificate_store,
        )
    return request, certificate


def authenticode_info(path: Path) -> dict[str, object]:
    escaped = str(path.resolve()).replace("'", "''")
    command = rf"""
$signature = Get-AuthenticodeSignature -LiteralPath '{escaped}'
[pscustomobject]@{{
    status = $signature.Status.ToString()
    status_message = $signature.StatusMessage
    signer_subject = if ($signature.SignerCertificate) {{ $signature.SignerCertificate.Subject }} else {{ '' }}
    signer_issuer = if ($signature.SignerCertificate) {{ $signature.SignerCertificate.Issuer }} else {{ '' }}
    signer_thumbprint = if ($signature.SignerCertificate) {{ $signature.SignerCertificate.Thumbprint }} else {{ '' }}
    certificate_not_after = if ($signature.SignerCertificate) {{ $signature.SignerCertificate.NotAfter.ToString('o') }} else {{ '' }}
    timestamp_subject = if ($signature.TimeStamperCertificate) {{ $signature.TimeStamperCertificate.Subject }} else {{ '' }}
    timestamp_thumbprint = if ($signature.TimeStamperCertificate) {{ $signature.TimeStamperCertificate.Thumbprint }} else {{ '' }}
}} | ConvertTo-Json -Compress
"""
    payload = _powershell_json(command)
    if not isinstance(payload, dict):
        raise SigningError("Authenticode verification did not return signature details.")
    return payload


def sign_and_verify(path: Path, request: SigningRequest) -> dict[str, object]:
    command = [
        str(request.signtool),
        "sign",
        "/fd",
        "SHA256",
        "/tr",
        request.timestamp_url,
        "/td",
        "SHA256",
    ]
    if request.pfx_path is not None:
        command.extend(["/f", str(request.pfx_path), "/p", request.pfx_password])
    else:
        if request.certificate_store == "LocalMachine":
            command.append("/sm")
        command.extend(["/sha1", request.certificate_thumbprint])
    command.append(str(path.resolve()))
    signed = subprocess.run(command, text=True, capture_output=True, check=False)
    if signed.returncode != 0:
        detail = signed.stderr.strip() or signed.stdout.strip() or f"exit={signed.returncode}"
        raise SigningError(f"SignTool signing failed: {detail}")

    verified = subprocess.run(
        [str(request.signtool), "verify", "/pa", "/all", "/v", str(path.resolve())],
        text=True,
        capture_output=True,
        check=False,
    )
    if verified.returncode != 0:
        detail = verified.stderr.strip() or verified.stdout.strip() or f"exit={verified.returncode}"
        raise SigningError(f"SignTool verification failed: {detail}")

    info = authenticode_info(path)
    if info.get("status") != "Valid":
        raise SigningError(f"Authenticode verification is not valid: {info.get('status', 'unknown')}")
    if not str(info.get("timestamp_subject", "")).strip():
        raise SigningError("The signed executable has no trusted timestamp certificate.")
    expected_thumbprint = str(request.certificate_thumbprint or "").upper()
    actual_thumbprint = str(info.get("signer_thumbprint", "") or "").upper()
    if expected_thumbprint and actual_thumbprint != expected_thumbprint:
        raise SigningError("The signed executable does not use the requested certificate thumbprint.")
    return {
        **info,
        "identity_mode": request.identity_mode,
        "timestamp_url": request.timestamp_url,
        "verification": "signtool_and_authenticode",
    }
