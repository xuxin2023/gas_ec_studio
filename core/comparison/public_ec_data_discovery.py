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
DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH = Path("artifacts/public_ec_data/public_ec_data_discovery_probe.json")


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
    ready_to_register_count = sum(
        1
        for probe in probes
        if str(dict(probe.get("registration_readiness", {}) or {}).get("status", "")) == "ready_to_register"
    )
    raw_without_eddypro_pair_count = sum(
        1
        for probe in probes
        if bool(dict(probe.get("registration_readiness", {}) or {}).get("has_raw_input", False))
        and (
            "eddypro_project_or_settings"
            in list(dict(probe.get("registration_readiness", {}) or {}).get("missing_requirements", []) or [])
            or "official_eddypro_full_output"
            in list(dict(probe.get("registration_readiness", {}) or {}).get("missing_requirements", []) or [])
        )
    )
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
            "ready_to_register_candidate_count": ready_to_register_count,
            "raw_without_eddypro_pair_count": raw_without_eddypro_pair_count,
            "can_change_full_parity_gate": False,
            "next_action": _next_action(probes),
        },
        "sources": probes,
        "truthfulness_boundary": (
            "This artifact proves discovery/probe status only. It does not register a fixture, does not run EddyPro, "
            "and cannot change can_release_full_eddypro_parity until a candidate completes raw-to-final registration and acceptance."
        ),
    }


def build_public_raw_importer_smoke_plan(
    *,
    discovery_probe_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    max_sample_bytes: int = 65536,
) -> dict[str, Any]:
    """Build a safe importer-smoke plan for real public raw candidates.

    The plan is intentionally evidence-oriented: it identifies real raw sources
    that are useful for importer work while preserving the missing EddyPro
    settings/output requirements that keep full parity blocked.
    """

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    probe_path = _resolve(root, discovery_probe_path or DEFAULT_PUBLIC_EC_DISCOVERY_PROBE_PATH)
    probe = _read_json(probe_path) if probe_path.exists() else {}
    if not probe.get("sources"):
        probe = build_public_ec_data_discovery_probe(
            manifest_path=manifest_path,
            workspace_root=root,
            run_network=False,
        )
    sources = [dict(item or {}) for item in list(probe.get("sources", []) or [])]
    candidates = [_raw_importer_candidate_plan(item, max_sample_bytes=max_sample_bytes) for item in sources]
    real_candidates = [item for item in candidates if item.get("has_real_raw_potential")]
    direct_sample_count = sum(1 for item in real_candidates if item.get("sample_mode") == "byte_range")
    operator_subset_count = sum(1 for item in real_candidates if item.get("sample_mode") == "operator_subset")
    ready_to_register_count = sum(
        1 for item in real_candidates if str(item.get("registration_readiness_status", "")) == "ready_to_register"
    )
    return {
        "artifact_type": "public_raw_importer_smoke_plan_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "ready_for_importer_smoke" if real_candidates else "no_real_raw_candidates",
        "discovery_probe_path": str(probe_path) if probe_path.exists() else "",
        "source_count": len(sources),
        "real_raw_candidate_count": len(real_candidates),
        "direct_byte_sample_candidate_count": direct_sample_count,
        "operator_subset_required_count": operator_subset_count,
        "ready_to_register_candidate_count": ready_to_register_count,
        "max_sample_bytes": int(max_sample_bytes),
        "can_change_full_parity_gate": False,
        "candidate_plans": real_candidates,
        "next_actions": _smoke_plan_next_actions(real_candidates),
        "truthfulness_boundary": (
            "This plan moves real public data into importer smoke testing only. It does not register a parity fixture "
            "and cannot change full EddyPro parity until EddyPro project/settings, official Full_Output, normalized "
            "reference, provenance, and acceptance evidence are present."
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
        "parity_value": str(source.get("parity_value", "")),
        "status": "not_probed",
        "real_data_candidate": str(source.get("parity_value", "")).startswith("real_"),
        "download_url_status": "",
        "network_errors": [],
        "truthfulness_boundary": source.get("truthfulness_boundary", ""),
    }
    if not run_network:
        payload["status"] = "skipped_network"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
        payload["registration_readiness"] = _registration_readiness(source, payload)
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
    elif source.get("landing_probe_keywords") or source.get("candidate_files"):
        payload.update(_probe_generic_landing_source(source, timeout_s=timeout_s))
    else:
        payload["status"] = "static_ledger_only"
        payload["candidate_files"] = list(source.get("candidate_files", []) or [])
    payload["registration_readiness"] = _registration_readiness(source, payload)
    return payload


def _raw_importer_candidate_plan(source_probe: dict[str, Any], *, max_sample_bytes: int) -> dict[str, Any]:
    readiness = dict(source_probe.get("registration_readiness", {}) or {})
    candidate_files = [dict(item or {}) for item in list(source_probe.get("candidate_files", []) or [])]
    downloadable = [
        item
        for item in candidate_files
        if str(item.get("download_url_status", "")) == "verified"
        or int(dict(item.get("head", {}) or {}).get("status_code", 0) or 0) == 200
        or str(item.get("url", "") or item.get("download_url", "")).startswith(("http://", "https://"))
    ]
    has_raw = bool(readiness.get("has_raw_input", False))
    parity_value = str(source_probe.get("parity_value", "")).lower()
    already_accepted = str(readiness.get("status", "")) == "registered_and_accepted"
    real_candidate = (
        has_raw
        or parity_value.startswith(("real_ec", "real_raw", "real_high_frequency_raw", "real_large_high_frequency_raw"))
    ) and not already_accepted
    sample_mode = "not_applicable"
    if downloadable:
        sample_mode = "byte_range"
    elif real_candidate:
        sample_mode = "operator_subset"
    missing = list(readiness.get("missing_requirements", []) or [])
    return {
        "source_id": str(source_probe.get("source_id", "")),
        "provider": str(source_probe.get("provider", "")),
        "source_url": str(source_probe.get("source_url", "")),
        "status": str(source_probe.get("status", "")),
        "has_real_raw_potential": bool(real_candidate),
        "sample_mode": sample_mode,
        "sample_byte_budget": int(max_sample_bytes) if sample_mode == "byte_range" else 0,
        "candidate_file_count": len(candidate_files),
        "downloadable_file_count": len(downloadable),
        "candidate_files": [
            {
                "name": str(item.get("name", "")),
                "url": str(item.get("url", "") or item.get("download_url", "")),
                "size_bytes": int(item.get("size_bytes", item.get("size", 0)) or 0),
                "download_url_status": str(item.get("download_url_status", "")),
            }
            for item in downloadable[:5]
        ],
        "registration_readiness_status": str(readiness.get("status", "")),
        "missing_for_eddypro_parity": missing,
        "can_register_as_eddypro_parity_fixture": not missing and bool(readiness),
        "recommended_smoke": _recommended_smoke(source_probe, sample_mode=sample_mode),
        "truthfulness_boundary": (
            "Importer smoke can validate parser and metadata handling. It is not an EddyPro raw-to-final parity fixture "
            "unless the missing registration evidence list is empty and acceptance passes."
        ),
    }


def _recommended_smoke(source_probe: dict[str, Any], *, sample_mode: str) -> dict[str, Any]:
    source_id = str(source_probe.get("source_id", "")).lower()
    provider = str(source_probe.get("provider", "")).lower()
    if "neon" in source_id or "neon" in provider:
        return {
            "smoke_type": "neon_hdf5_metadata_row_rp",
            "command_family": [
                "--download-neon-hdf5-candidate",
                "--build-neon-hdf5-metadata-smoke",
                "--build-neon-hdf5-row-smoke",
                "--run-neon-hdf5-rp-smoke",
            ],
            "claim_scope": "engineering_validation_only",
        }
    if "crocus" in source_id or "osti" in provider:
        return {
            "smoke_type": "generic_high_frequency_raw_sample",
            "command_family": ["--build-public-ec-data-discovery", "operator_supplied_sample_then_raw_importer_probe"],
            "claim_scope": "importer_validation_only",
        }
    if "bas" in source_id or "antarctic" in provider:
        return {
            "smoke_type": "large_raw_subset_stress_sample",
            "command_family": ["operator_supplied_subset_then_raw_importer_probe"],
            "claim_scope": "importer_stress_validation_only",
        }
    if "icos" in source_id or "icos" in provider:
        return {
            "smoke_type": "authenticated_raw_ascii_subset",
            "command_family": ["authenticated_download_or_operator_subset_then_raw_importer_probe"],
            "claim_scope": "importer_validation_only",
        }
    return {
        "smoke_type": "manual_public_raw_subset" if sample_mode == "operator_subset" else "byte_range_sample",
        "command_family": ["operator_supplied_sample_then_raw_importer_probe"],
        "claim_scope": "engineering_validation_only",
    }


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


def _probe_generic_landing_source(source: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "landing_not_verified",
        "download_url_status": "not_verified",
        "source_page_status": "",
        "registration_outcome": str(source.get("registration_outcome", "not_registered")),
        "candidate_files": [],
    }
    errors: list[str] = []
    try:
        source_text = _read_url_text(str(source.get("source_url", "")), timeout_s=timeout_s)
        result["source_page_status"] = "pass"
        result["landing_keyword_hits"] = _keyword_hits(
            source_text,
            [str(item) for item in list(source.get("landing_probe_keywords", []) or []) if str(item).strip()],
        )
    except Exception as exc:  # pragma: no cover - network/environment dependent
        errors.append(f"source_page_failed: {exc}")

    candidate_payloads: list[dict[str, Any]] = []
    for item in list(source.get("candidate_files", []) or []):
        candidate = dict(item or {})
        url = str(candidate.get("url", "") or candidate.get("download_url", "")).strip()
        if url:
            head = _head_url(url, timeout_s=timeout_s)
            candidate["head"] = head
            if head.get("status_code") == 200:
                candidate["download_url_status"] = "verified"
        candidate_payloads.append(candidate)
    result["candidate_files"] = candidate_payloads
    verified_count = sum(1 for item in candidate_payloads if str(item.get("download_url_status", "")) == "verified")
    if verified_count:
        result["download_url_status"] = "verified"
    elif result.get("source_page_status") == "pass":
        result["download_url_status"] = str(source.get("download_url_status", "landing_only") or "landing_only")
    result["network_errors"] = errors
    result["status"] = "landing_verified" if result.get("source_page_status") == "pass" else "network_error"
    return result


def _registration_readiness(source: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    declared = dict(source.get("registration_evidence", {}) or {})
    parity_value = str(source.get("parity_value", "")).lower()
    if parity_value.startswith(("real_raw", "real_high_frequency_raw", "real_large_high_frequency_raw")):
        declared.setdefault("raw_input", True)
    if str(source.get("registration_outcome", "")) in {"registered", "registered_and_accepted"}:
        declared.setdefault("raw_input", True)
        declared.setdefault("eddypro_project_or_settings", True)
        declared.setdefault("official_eddypro_full_output", True)
        declared.setdefault("normalized_reference", True)
        declared.setdefault("normalization_provenance", True)
        declared.setdefault("acceptance_evidence", True)
    required = {
        "raw_input": bool(declared.get("raw_input", False)),
        "eddypro_project_or_settings": bool(declared.get("eddypro_project_or_settings", False)),
        "official_eddypro_full_output": bool(declared.get("official_eddypro_full_output", False)),
        "normalized_reference": bool(declared.get("normalized_reference", False)),
        "normalization_provenance": bool(declared.get("normalization_provenance", False)),
        "acceptance_evidence": bool(declared.get("acceptance_evidence", False)),
    }
    missing = [key for key, present in required.items() if not present]
    status = "ready_to_register" if not missing else "blocked_missing_registration_evidence"
    if str(source.get("registration_outcome", "")) == "registered_and_accepted":
        status = "registered_and_accepted"
    return {
        "artifact_type": "public_ec_candidate_registration_readiness_v1",
        "status": status,
        "has_raw_input": required["raw_input"],
        "has_eddypro_project_or_settings": required["eddypro_project_or_settings"],
        "has_official_eddypro_full_output": required["official_eddypro_full_output"],
        "has_normalized_reference": required["normalized_reference"],
        "has_normalization_provenance": required["normalization_provenance"],
        "has_acceptance_evidence": required["acceptance_evidence"],
        "missing_requirements": missing,
        "can_change_full_parity_gate": False,
        "probe_status": str(probe.get("status", "")),
        "truthfulness_boundary": (
            "A public EC candidate is promotion-ready only when raw input, EddyPro project/settings, "
            "official EddyPro Full_Output, normalized reference, provenance, and acceptance evidence are all present."
        ),
    }


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


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    folded = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in folded]


def _next_action(probes: list[dict[str, Any]]) -> str:
    if any(str(dict(item.get("registration_readiness", {}) or {}).get("status", "")) == "ready_to_register" for item in probes):
        return "Promote the ready public candidate through official raw bundle registration and acceptance."
    if any(str(item.get("status", "")) == "candidate_verified" for item in probes):
        return "Build a small importer smoke test for the verified NEON HDF5 candidate before downloading full files."
    if any(bool(dict(item.get("registration_readiness", {}) or {}).get("has_raw_input", False)) for item in probes):
        return "Use real raw public candidates for importer smoke tests while keeping full EddyPro parity blocked until an EddyPro output pair exists."
    if any(str(item.get("status", "")) == "licence_flow_verified" for item in probes):
        return "Add an authenticated ICOS download path or use an operator-provided accepted file."
    return "Continue source-derived parity closure and rerun public discovery later."


def _smoke_plan_next_actions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    byte_range_ids = [str(item.get("source_id", "")) for item in candidates if item.get("sample_mode") == "byte_range"]
    operator_ids = [str(item.get("source_id", "")) for item in candidates if item.get("sample_mode") == "operator_subset"]
    if byte_range_ids:
        actions.append(
            {
                "priority": "P0",
                "action": "Run bounded byte-range or metadata smoke on direct-download public candidates.",
                "source_ids": byte_range_ids,
            }
        )
    if operator_ids:
        actions.append(
            {
                "priority": "P1",
                "action": "Use operator-provided subsets for landing-page-only or very large raw datasets.",
                "source_ids": operator_ids,
            }
        )
    actions.append(
        {
            "priority": "P0",
            "action": "Keep full EddyPro parity blocked until each promoted source has settings, Full_Output, provenance, and acceptance evidence.",
            "source_ids": [str(item.get("source_id", "")) for item in candidates],
        }
    )
    return actions


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
