from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH = Path("references/eddypro/public_raw_search/ec_public_data_sources.json")
DEFAULT_PUBLIC_EC_SAMPLE_ROOT = Path("artifacts/public_ec_data")


def build_public_ec_data_discovery_probe(
    *,
    manifest_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    sample_output_root: str | Path | None = None,
    sample_bytes: int = 0,
    timeout_s: float = 60.0,
    run_network: bool = True,
) -> dict[str, Any]:
    """Probe public real EC candidates without promoting them to EddyPro parity fixtures."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, manifest_path or DEFAULT_PUBLIC_EC_DATA_SOURCES_PATH)
    manifest = _read_json(source_path)
    sources = [dict(item or {}) for item in list(manifest.get("sources", []) or [])]
    sample_root = _resolve(root, sample_output_root or DEFAULT_PUBLIC_EC_SAMPLE_ROOT)
    probes = [
        _probe_source(
            item,
            sample_root=sample_root,
            sample_bytes=sample_bytes,
            timeout_s=timeout_s,
            run_network=run_network,
        )
        for item in sources
    ]
    status_counts: dict[str, int] = {}
    for probe in probes:
        status = str(probe.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    registered_count = sum(
        1
        for probe in probes
        if str(probe.get("registration_outcome", "")) in {"registered", "registered_and_accepted"}
    )
    real_candidate_count = sum(1 for probe in probes if bool(probe.get("real_data_candidate", False)))
    downloadable_count = sum(1 for probe in probes if str(probe.get("download_url_status", "")) == "verified")
    return {
        "artifact_type": "public_ec_data_discovery_probe_v1",
        "generated_at": datetime.now().isoformat(),
        "manifest_path": str(source_path),
        "manifest_id": str(manifest.get("manifest_id", "")),
        "run_network": bool(run_network),
        "sample_bytes_requested": int(sample_bytes or 0),
        "sample_output_root": str(sample_root),
        "status": "ok" if probes else "no_sources",
        "summary": {
            "source_count": len(probes),
            "status_counts": status_counts,
            "registered_count": registered_count,
            "real_data_candidate_count": real_candidate_count,
            "downloadable_candidate_count": downloadable_count,
            "can_change_full_parity_gate": False,
            "next_action": _next_action(probes),
        },
        "sources": probes,
        "truthfulness_boundary": (
            "This artifact proves discovery/probe status only. It does not register a fixture, does not run EddyPro, "
            "and cannot change can_release_full_eddypro_parity until a candidate completes raw-to-final registration and acceptance."
        ),
    }


def _probe_source(
    source: dict[str, Any],
    *,
    sample_root: Path,
    sample_bytes: int,
    timeout_s: float,
    run_network: bool,
) -> dict[str, Any]:
    source_id = str(source.get("source_id", "unknown_source") or "unknown_source")
    provider = str(source.get("provider", ""))
    payload: dict[str, Any] = {
        "source_id": source_id,
        "provider": provider,
        "source_url": str(source.get("source_url", "")),
        "registration_outcome": str(source.get("registration_outcome", "")),
        "declared_access_status": str(source.get("access_status", "")),
        "status": "not_probed",
        "real_data_candidate": str(source.get("parity_value", "")).startswith("real_"),
        "download_url_status": "",
        "network_errors": [],
        "truthfulness_boundary": source.get("truthfulness_boundary", ""),
    }
    if not run_network:
        payload["status"] = "skipped_network"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
        return payload

    if source.get("api_query_url"):
        payload.update(
            _probe_neon_api_source(
                source,
                sample_root=sample_root,
                sample_bytes=sample_bytes,
                timeout_s=timeout_s,
            )
        )
    elif "icos" in provider.lower() or "icos" in source_id.lower():
        payload.update(_probe_icos_landing_source(source, timeout_s=timeout_s))
    else:
        payload["status"] = "static_ledger_only"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
    return payload


def _probe_neon_api_source(
    source: dict[str, Any],
    *,
    sample_root: Path,
    sample_bytes: int,
    timeout_s: float,
) -> dict[str, Any]:
    api_url = str(source.get("api_query_url", "")).strip()
    result: dict[str, Any] = {
        "status": "blocked",
        "api_query_url": api_url,
        "api_status": "",
        "candidate_files": [],
        "download_url_status": "not_verified",
    }
    try:
        api_payload = _read_url_json(api_url, timeout_s=timeout_s)
    except Exception as exc:  # pragma: no cover - network/environment dependent
        result["status"] = "network_error"
        result["network_errors"] = [f"api_query_failed: {exc}"]
        return result

    result["api_status"] = "pass"
    candidates = _neon_candidate_files(api_payload)
    candidate_payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_payload = dict(candidate)
        head = _head_url(str(candidate.get("url", "")), timeout_s=timeout_s)
        candidate_payload["head"] = head
        if head.get("status_code") == 200:
            candidate_payload["download_url_status"] = "verified"
        if sample_bytes > 0 and head.get("status_code") == 200:
            sample = _download_byte_sample(
                source_url=str(candidate.get("url", "")),
                target_path=sample_root / "neon" / _safe_filename(str(candidate.get("name", "neon_candidate.h5.sample"))),
                sample_bytes=int(sample_bytes),
                timeout_s=timeout_s,
            )
            candidate_payload["byte_sample"] = sample
        candidate_payloads.append(candidate_payload)

    verified_count = sum(1 for item in candidate_payloads if str(item.get("download_url_status", "")) == "verified")
    result["candidate_files"] = candidate_payloads
    result["download_url_status"] = "verified" if verified_count else "not_verified"
    result["status"] = "candidate_verified" if verified_count else "api_only"
    result["registration_outcome"] = str(source.get("registration_outcome", "not_registered"))
    return result


def _probe_icos_landing_source(source: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "landing_not_verified",
        "download_url_status": "licence_required",
        "source_page_status": "",
        "licence_page_status": "",
        "registration_outcome": str(source.get("registration_outcome", "not_programmatically_registered")),
    }
    errors: list[str] = []
    try:
        source_text = _read_url_text(str(source.get("source_url", "")), timeout_s=timeout_s)
        result["source_page_status"] = "pass"
        result["mentions_raw_ascii"] = "Raw ASCII" in source_text
    except Exception as exc:  # pragma: no cover - network/environment dependent
        errors.append(f"source_page_failed: {exc}")
    if source.get("licence_url"):
        try:
            licence_text = _read_url_text(str(source.get("licence_url", "")), timeout_s=timeout_s)
            result["licence_page_status"] = "pass"
            result["licence_acceptance_required"] = "I hereby confirm" in licence_text or "licence_accept" in licence_text
        except Exception as exc:  # pragma: no cover - network/environment dependent
            errors.append(f"licence_page_failed: {exc}")
    result["network_errors"] = errors
    result["status"] = "licence_flow_verified" if result.get("source_page_status") == "pass" else "network_error"
    return result


def _neon_candidate_files(api_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for release in list(dict(api_payload.get("data", {}) or {}).get("releases", []) or []):
        for package in list(dict(release or {}).get("packages", []) or []):
            for file_payload in list(dict(package or {}).get("files", []) or []):
                file_item = dict(file_payload or {})
                name = str(file_item.get("name", ""))
                if not name.lower().endswith((".h5", ".hdf5")):
                    continue
                candidates.append(
                    {
                        "name": name,
                        "size_bytes": int(file_item.get("size", 0) or 0),
                        "md5": str(file_item.get("md5", "")),
                        "url": str(file_item.get("url", "")),
                        "release": str(dict(release or {}).get("release", "")),
                        "site_code": str(dict(package or {}).get("siteCode", "")),
                        "month": str(dict(package or {}).get("month", "")),
                        "package_type": str(dict(package or {}).get("packageType", "")),
                    }
                )
    return candidates


def _download_byte_sample(*, source_url: str, target_path: Path, sample_bytes: int, timeout_s: float) -> dict[str, Any]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path = target_path.with_suffix(target_path.suffix + ".sample")
    end = max(0, int(sample_bytes) - 1)
    request = Request(
        source_url,
        headers={
            "User-Agent": "gas_ec_studio_public_ec_discovery/1.0",
            "Range": f"bytes=0-{end}",
        },
    )
    written = 0
    digest = hashlib.sha256()
    with urlopen(request, timeout=float(timeout_s)) as response, sample_path.open("wb") as output:
        while written < sample_bytes:
            chunk = response.read(min(65536, sample_bytes - written))
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            written += len(chunk)
    return {
        "status": "sampled" if written > 0 else "empty",
        "path": str(sample_path),
        "size_bytes": written,
        "sha256": digest.hexdigest().upper() if written > 0 else "",
        "requested_bytes": int(sample_bytes),
    }


def _head_url(url: str, *, timeout_s: float) -> dict[str, Any]:
    if not url:
        return {"status": "missing_url", "status_code": 0}
    request = Request(url, method="HEAD", headers={"User-Agent": "gas_ec_studio_public_ec_discovery/1.0"})
    try:
        with urlopen(request, timeout=float(timeout_s)) as response:
            return {
                "status": "pass",
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_length": _int_header(response.headers.get("Content-Length")),
                "content_type": str(response.headers.get("Content-Type", "")),
                "accept_ranges": str(response.headers.get("Accept-Ranges", "")),
                "etag": str(response.headers.get("ETag", "")),
                "x_goog_hash": str(response.headers.get("x-goog-hash", "")),
            }
    except Exception as exc:  # pragma: no cover - network/environment dependent
        return {"status": "fail", "status_code": 0, "error": str(exc)}


def _read_url_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    text = _read_url_text(url, timeout_s=timeout_s)
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _read_url_text(url: str, *, timeout_s: float) -> str:
    request = Request(url, headers={"User-Agent": "gas_ec_studio_public_ec_discovery/1.0"})
    with urlopen(request, timeout=float(timeout_s)) as response:
        return response.read().decode("utf-8", "replace")


def _next_action(probes: list[dict[str, Any]]) -> str:
    if any(str(item.get("status", "")) == "candidate_verified" for item in probes):
        return "Build a small importer smoke test for the verified NEON HDF5 candidate before downloading full files."
    if any(str(item.get("status", "")) == "licence_flow_verified" for item in probes):
        return "Add an authenticated ICOS download path or use an operator-provided accepted file."
    return "Continue source-derived parity closure and rerun public discovery later."


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"sources": [], "manifest_id": "", "errors": [f"manifest missing: {path}"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"sources": [], "manifest_id": "", "errors": [f"manifest invalid: {exc}"]}
    return deepcopy(payload) if isinstance(payload, dict) else {"sources": [], "manifest_id": ""}


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in value.strip())
    return safe or "public_ec_candidate"


def _int_header(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
