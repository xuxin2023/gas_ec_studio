from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_NEON_HDF5_OUTPUT_ROOT = Path("artifacts/public_ec_data/neon")
REQUIRED_RAW_TO_FINAL_FIELDS = ["time", "u", "v", "w", "sonic_temperature", "co2", "h2o"]


def download_neon_hdf5_candidate(
    discovery_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    output_root: str | Path | None = None,
    source_id: str = "",
    candidate_name: str = "",
    overwrite: bool = False,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Download one verified NEON HDF5 candidate without registering it as parity evidence."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    source_path = _resolve(root, discovery_path)
    output_dir = _resolve(root, output_root or DEFAULT_NEON_HDF5_OUTPUT_ROOT)
    payload = _read_json(source_path)
    source, candidate = _select_neon_candidate(payload, source_id=source_id, candidate_name=candidate_name)
    result: dict[str, Any] = {
        "artifact_type": "neon_hdf5_candidate_download_v1",
        "generated_at": datetime.now().isoformat(),
        "source_discovery_artifact": str(source_path),
        "source_id": str(source.get("source_id", "")),
        "candidate_name": str(candidate.get("name", "")),
        "candidate_url": str(candidate.get("url", "")),
        "expected_size_bytes": int(candidate.get("size_bytes", candidate.get("head_content_length", 0)) or 0),
        "expected_md5": str(candidate.get("md5", "")),
        "status": "blocked",
        "action": "",
        "local_path": "",
        "can_change_full_parity_gate": False,
        "truthfulness_boundary": (
            "Downloading a public NEON HDF5 file is acquisition evidence only. It is not an EddyPro "
            "raw-to-final parity fixture until metadata mapping, importer validation, official output, "
            "normalization provenance, and acceptance all pass."
        ),
    }
    if not source:
        result["status"] = "source_not_found"
        result["errors"] = ["No NEON source matched the requested source id."]
        return result
    if not candidate:
        result["status"] = "candidate_not_found"
        result["errors"] = ["No HDF5 candidate with a download URL matched the requested candidate name."]
        return result
    url = str(candidate.get("url", "")).strip()
    if not url:
        result["status"] = "missing_url"
        result["errors"] = ["Selected candidate has no URL."]
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / _safe_filename(str(candidate.get("name", "neon_candidate.h5")))
    result["local_path"] = str(target_path)
    if target_path.exists() and not overwrite:
        existing = _file_hashes(target_path)
        result.update(existing)
        result["action"] = "skipped_existing"
        result["status"] = _download_validation_status(
            size_bytes=int(existing.get("size_bytes", 0) or 0),
            expected_size=int(result.get("expected_size_bytes", 0) or 0),
            md5=str(existing.get("md5", "")),
            expected_md5=str(result.get("expected_md5", "")),
        )
        return result

    tmp_path = target_path.with_suffix(target_path.suffix + ".part")
    if tmp_path.exists():
        tmp_path.unlink()
    md5_digest = hashlib.md5()  # noqa: S324 - used for provider checksum comparison, not security.
    sha256_digest = hashlib.sha256()
    written = 0
    request = Request(url, headers={"User-Agent": "gas_ec_studio_neon_hdf5_importer/1.0"})
    try:
        with urlopen(request, timeout=float(timeout_s)) as response, tmp_path.open("wb") as output:
            result["http_status"] = int(getattr(response, "status", 0) or 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                md5_digest.update(chunk)
                sha256_digest.update(chunk)
                written += len(chunk)
    except Exception as exc:  # pragma: no cover - network/environment dependent
        if tmp_path.exists():
            tmp_path.unlink()
        result["status"] = "download_failed"
        result["errors"] = [str(exc)]
        return result

    shutil.move(str(tmp_path), str(target_path))
    result.update(
        {
            "action": "downloaded",
            "size_bytes": written,
            "md5": md5_digest.hexdigest(),
            "sha256": sha256_digest.hexdigest().upper(),
        }
    )
    result["status"] = _download_validation_status(
        size_bytes=written,
        expected_size=int(result.get("expected_size_bytes", 0) or 0),
        md5=str(result.get("md5", "")),
        expected_md5=str(result.get("expected_md5", "")),
    )
    return result


def build_neon_hdf5_metadata_smoke(
    hdf5_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    source_id: str = "",
    source_discovery_artifact: str | Path | None = None,
    max_datasets: int = 250,
    max_attrs: int = 24,
) -> dict[str, Any]:
    """Inspect a NEON HDF5 file and infer EC field candidates without processing fluxes."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    path = _resolve(root, hdf5_path)
    dependency = _load_h5py()
    base = {
        "artifact_type": "neon_hdf5_metadata_smoke_v1",
        "generated_at": datetime.now().isoformat(),
        "source_id": source_id,
        "source_file": str(path),
        "source_discovery_artifact": str(_resolve(root, source_discovery_artifact)) if source_discovery_artifact else "",
        "hdf5_dependency": dependency["summary"],
        "status": "blocked",
        "can_change_full_parity_gate": False,
        "truthfulness_boundary": (
            "This artifact proves HDF5 structure readability and candidate EC field mapping only. It does not "
            "run EddyPro, does not normalize official output, and cannot change can_release_full_eddypro_parity."
        ),
    }
    if not dependency["available"]:
        return {
            **base,
            "status": "missing_hdf5_dependency",
            "errors": ["Install h5py to inspect NEON HDF5 metadata."],
        }
    if not path.exists() or not path.is_file():
        return {**base, "status": "file_missing", "errors": [f"HDF5 file missing: {path}"]}

    h5py = dependency["module"]
    try:
        file_hashes = _file_hashes(path)
        with h5py.File(path, "r") as hdf:
            inspection = _inspect_hdf5_tree(hdf, max_datasets=max_datasets, max_attrs=max_attrs)
    except Exception as exc:
        return {
            **base,
            "status": "invalid_hdf5",
            "errors": [str(exc)],
            "file": _basic_file_payload(path),
        }

    field_candidates = _infer_field_candidates(inspection["field_scan_datasets"])
    field_mappings = _select_field_mappings(field_candidates)
    coverage = _field_coverage(field_mappings)
    status = _metadata_status(inspection, coverage)
    return {
        **base,
        "status": status,
        "file": file_hashes,
        "hdf5_summary": {
            "root_attrs": inspection["root_attrs"],
            "group_count": inspection["group_count"],
            "dataset_count": inspection["dataset_count"],
            "dataset_preview_count": len(inspection["datasets"]),
            "field_scan_dataset_count": len(inspection["field_scan_datasets"]),
            "dataset_truncated": inspection["dataset_truncated"],
            "estimated_dataset_bytes": inspection["estimated_dataset_bytes"],
        },
        "datasets": inspection["datasets"],
        "field_candidates": field_candidates,
        "field_mappings": field_mappings,
        "canonical_field_coverage": coverage,
        "importer_smoke": {
            "can_open_hdf5": True,
            "can_infer_time": "time" in field_mappings,
            "can_infer_wind_components": all(item in field_mappings for item in ("u", "v", "w")),
            "can_infer_trace_gases": any(item in field_mappings for item in ("co2", "h2o", "ch4")),
            "ready_for_raw_to_final_registration": False,
            "can_change_full_parity_gate": False,
        },
        "known_limitations": [
            "NEON HDF5 layout is not an EddyPro .ghg/TOB1/SLT project bundle.",
            "This smoke artifact does not decode NEON site-specific scale factors, time alignment, or quality masks.",
            "Official EddyPro output/settings are still required before numeric raw-to-final parity can be claimed.",
        ],
        "next_action": _next_action(status, coverage),
    }


def _inspect_hdf5_tree(hdf: Any, *, max_datasets: int, max_attrs: int) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    group_count = 1
    dataset_count = 0
    estimated_bytes = 0
    root_attrs = _attrs_payload(hdf.attrs, limit=max_attrs)
    field_scan_datasets: list[dict[str, Any]] = []

    def visit(name: str, obj: Any) -> None:
        nonlocal group_count, dataset_count, estimated_bytes
        module_name = getattr(type(obj), "__module__", "")
        class_name = getattr(type(obj), "__name__", "")
        if class_name == "Group" and module_name.startswith("h5py"):
            group_count += 1
            return
        if class_name != "Dataset" or not module_name.startswith("h5py"):
            return
        dataset_count += 1
        estimated_bytes += _dataset_nbytes(obj)
        payload = _dataset_payload(name, obj, max_attrs=max_attrs)
        field_scan_datasets.append(payload)
        if len(datasets) >= max(0, int(max_datasets)):
            return
        datasets.append(payload)

    hdf.visititems(visit)
    return {
        "root_attrs": root_attrs,
        "group_count": group_count,
        "dataset_count": dataset_count,
        "datasets": datasets,
        "field_scan_datasets": field_scan_datasets,
        "dataset_truncated": dataset_count > len(datasets),
        "estimated_dataset_bytes": estimated_bytes,
    }


def _dataset_payload(name: str, dataset: Any, *, max_attrs: int) -> dict[str, Any]:
    shape = list(dataset.shape or [])
    attrs = _attrs_payload(dataset.attrs, limit=max_attrs)
    return {
        "path": "/" + str(name).strip("/"),
        "name": str(name).split("/")[-1],
        "shape": shape,
        "ndim": len(shape),
        "dtype": str(dataset.dtype),
        "dtype_fields": [str(key) for key in (dataset.dtype.fields or {}).keys()],
        "size": int(getattr(dataset, "size", 0) or 0),
        "estimated_bytes": _dataset_nbytes(dataset),
        "chunks": list(dataset.chunks or []),
        "compression": str(dataset.compression or ""),
        "attrs": attrs,
        "units": _first_attr(attrs, ("units", "unit", "Unit", "UNITS")),
        "long_name": _first_attr(attrs, ("long_name", "LongName", "description", "Description", "standard_name")),
    }


def _infer_field_candidates(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for dataset in datasets:
        candidates.extend(_dataset_field_candidates(dataset))
    return sorted(candidates, key=lambda item: (-float(item["confidence"]), str(item["canonical_field"]), str(item["path"])))


def _dataset_field_candidates(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    path = str(dataset.get("path", ""))
    attrs = dict(dataset.get("attrs", {}) or {})
    units = str(dataset.get("units", ""))
    long_name = str(dataset.get("long_name", ""))
    text = " ".join([path, str(dataset.get("name", "")), units, long_name, " ".join(str(value) for value in attrs.values())])
    normalized = _normalize_text(text)
    compact = normalized.replace(" ", "").replace("_", "").replace("-", "")
    segments = [_normalize_text(segment) for segment in path.strip("/").replace("-", "_").split("/")]
    last_segment = segments[-1] if segments else ""
    last_compact = last_segment.replace(" ", "")
    dtype_fields = [_normalize_text(str(field)) for field in list(dataset.get("dtype_fields", []) or [])]
    dtype_compact = {field.replace(" ", "") for field in dtype_fields}
    candidates: list[dict[str, Any]] = []

    def add(field: str, confidence: float, reason: str) -> None:
        candidates.append(
            {
                "canonical_field": field,
                "path": path,
                "confidence": round(float(confidence), 3),
                "reason": reason,
                "dtype": dataset.get("dtype", ""),
                "shape": dataset.get("shape", []),
                "units": units,
                "long_name": long_name,
            }
        )

    if _has_segment(segments, {"time", "timestamp", "datetime", "time_bgn", "time_end"}):
        add("time", 0.95, "dataset path contains a time/timestamp segment")
    elif {"timebgn", "timeend"}.intersection(dtype_compact):
        if last_compact == "veloxaxserth":
            confidence = 0.93
        elif last_compact in {"veloyaxserth", "velozaxserth", "tempsoni"}:
            confidence = 0.92
        else:
            confidence = 0.9 if "/data/soni/" in path.lower().replace("\\", "/") else 0.88
        add("time", confidence, "compound dataset dtype contains timeBgn/timeEnd fields")
    elif "timestamp" in compact or "datetime" in compact:
        add("time", 0.82, "dataset metadata mentions timestamp/datetime")

    if last_compact == "veloxaxserth":
        add("u", 0.98, "NEON sonic dataset veloXaxsErth maps to the earth-frame u component")
    elif _has_segment(segments, {"u", "u_wind", "uwind", "wind_u", "u_component"}):
        add("u", 0.96, "dataset path identifies the u wind component")
    elif "uwind" in compact or "ucomponent" in compact or "eastwardwind" in compact:
        add("u", 0.82, "dataset metadata suggests u/eastward wind")

    if last_compact == "veloyaxserth":
        add("v", 0.98, "NEON sonic dataset veloYaxsErth maps to the earth-frame v component")
    elif _has_segment(segments, {"v", "v_wind", "vwind", "wind_v", "v_component"}):
        add("v", 0.96, "dataset path identifies the v wind component")
    elif "vwind" in compact or "vcomponent" in compact or "northwardwind" in compact:
        add("v", 0.82, "dataset metadata suggests v/northward wind")

    if last_compact == "velozaxserth":
        add("w", 0.98, "NEON sonic dataset veloZaxsErth maps to the earth-frame w component")
    elif _has_segment(segments, {"w", "w_wind", "wwind", "wind_w", "w_component", "vertical_wind"}):
        add("w", 0.96, "dataset path identifies the w wind component")
    elif "verticalwind" in compact or "wcomponent" in compact:
        add("w", 0.84, "dataset metadata suggests vertical wind")

    if "co2" in last_compact or "carbondioxide" in _normalize_text(long_name).replace(" ", ""):
        add("co2", 0.94, "dataset metadata indicates CO2")
    elif "co2" in compact:
        add("co2", 0.7, "dataset parent path mentions CO2")
    if "h2o" in last_compact or "watervapor" in _normalize_text(long_name).replace(" ", "") or "water vap" in normalized:
        add("h2o", 0.94, "dataset metadata indicates H2O/water vapor")
    elif "h2o" in compact:
        add("h2o", 0.7, "dataset parent path mentions H2O")
    if "ch4" in last_compact or "methane" in _normalize_text(long_name).replace(" ", ""):
        add("ch4", 0.9, "dataset metadata indicates CH4/methane")
    elif "ch4" in compact:
        add("ch4", 0.68, "dataset parent path mentions CH4")

    if last_compact == "tempsoni":
        add("sonic_temperature", 0.94, "NEON sonic dataset tempSoni maps to sonic temperature")
    elif ("sonic" in normalized and ("temp" in normalized or "temperature" in normalized)) or _has_segment(
        segments, {"ts", "sonic_temperature", "sonictemp"}
    ):
        add("sonic_temperature", 0.9, "dataset metadata indicates sonic temperature")
    elif _has_segment(segments, {"t_sonic"}):
        add("sonic_temperature", 0.86, "dataset path indicates sonic temperature")

    if last_compact == "tempair":
        add("air_temperature", 0.86, "NEON sonic dataset tempAir maps to air temperature")
    elif ("air" in normalized and ("temp" in normalized or "temperature" in normalized)) or _has_segment(
        segments, {"air_temperature", "tair", "ta"}
    ):
        add("air_temperature", 0.82, "dataset metadata indicates air temperature")
    if last_compact in {"pres", "presatm", "pressum"} or "pressure" in normalized or "barometric" in normalized or _has_segment(
        segments, {"pressure", "press", "pa"}
    ):
        add("pressure", 0.78, "dataset metadata indicates pressure")
    if _has_segment(segments, {"qc", "quality", "flag", "flags"}) or "qualityflag" in compact:
        add("qc_flag", 0.74, "dataset metadata indicates quality/flag information")
    return candidates


def _select_field_mappings(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        field = str(candidate.get("canonical_field", ""))
        if field and field not in selected:
            selected[field] = deepcopy(candidate)
    return selected


def _field_coverage(field_mappings: dict[str, Any]) -> dict[str, Any]:
    found = [field for field in REQUIRED_RAW_TO_FINAL_FIELDS if field in field_mappings]
    missing = [field for field in REQUIRED_RAW_TO_FINAL_FIELDS if field not in field_mappings]
    optional_found = [field for field in ("air_temperature", "pressure", "ch4", "qc_flag") if field in field_mappings]
    return {
        "required_fields": REQUIRED_RAW_TO_FINAL_FIELDS,
        "found_required_fields": found,
        "missing_required_fields": missing,
        "optional_found_fields": optional_found,
        "coverage_ratio": round(len(found) / len(REQUIRED_RAW_TO_FINAL_FIELDS), 3),
    }


def _metadata_status(inspection: dict[str, Any], coverage: dict[str, Any]) -> str:
    if int(inspection.get("dataset_count", 0) or 0) <= 0:
        return "hdf5_opened_no_datasets"
    missing = set(coverage.get("missing_required_fields", []) or [])
    if not missing:
        return "mapping_ready_for_importer_smoke"
    found = set(coverage.get("found_required_fields", []) or [])
    if {"time", "u", "v", "w"}.issubset(found) and bool(found.intersection({"co2", "h2o"})):
        return "partial_mapping_ready"
    return "hdf5_opened_mapping_incomplete"


def _next_action(status: str, coverage: dict[str, Any]) -> str:
    if status == "mapping_ready_for_importer_smoke":
        return "Build a NEON HDF5 row extractor and map QC/units before raw-to-final registration."
    if status == "partial_mapping_ready":
        missing = ", ".join(coverage.get("missing_required_fields", []) or [])
        return f"Resolve missing canonical fields before row extraction: {missing}."
    return "Download or provide a complete NEON HDF5 file and refine field-name aliases from the inspected structure."


def _select_neon_candidate(
    payload: dict[str, Any],
    *,
    source_id: str,
    candidate_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sources = [dict(item or {}) for item in list(payload.get("sources", []) or [])]
    selected_source: dict[str, Any] = {}
    for source in sources:
        source_key = str(source.get("source_id", ""))
        provider = str(source.get("provider", ""))
        if source_id and source_key != source_id:
            continue
        if source_id or "neon" in source_key.lower() or "neon" in provider.lower():
            selected_source = source
            break
    if not selected_source:
        return {}, {}
    for candidate in list(selected_source.get("candidate_files", []) or []):
        item = dict(candidate or {})
        name = str(item.get("name", ""))
        if candidate_name and name != candidate_name:
            continue
        if name.lower().endswith((".h5", ".hdf5")) and str(item.get("url", "")):
            return selected_source, item
    return selected_source, {}


def _load_h5py() -> dict[str, Any]:
    try:
        import h5py  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on runtime package set
        return {"available": False, "module": None, "summary": {"available": False, "error": str(exc)}}
    return {"available": True, "module": h5py, "summary": {"available": True, "version": str(h5py.__version__)}}


def _attrs_payload(attrs: Any, *, limit: int) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for index, key in enumerate(list(attrs.keys())):
        if index >= max(0, int(limit)):
            break
        payload[str(key)] = _json_value(attrs[key])
    return payload


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in list(value)[:12]]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in list(value.items())[:12]}
    return str(value)


def _first_attr(attrs: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in attrs:
            return str(attrs.get(key, ""))
    lowered = {str(key).lower(): value for key, value in attrs.items()}
    for key in keys:
        if key.lower() in lowered:
            return str(lowered[key.lower()])
    return ""


def _dataset_nbytes(dataset: Any) -> int:
    try:
        return int(getattr(dataset, "size", 0) or 0) * int(getattr(dataset.dtype, "itemsize", 0) or 0)
    except Exception:
        return 0


def _file_hashes(path: Path) -> dict[str, Any]:
    md5_digest = hashlib.md5()  # noqa: S324 - used for provider checksum comparison, not security.
    sha256_digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            md5_digest.update(chunk)
            sha256_digest.update(chunk)
    return {
        "path": str(path),
        "size_bytes": size,
        "md5": md5_digest.hexdigest(),
        "sha256": sha256_digest.hexdigest().upper(),
    }


def _basic_file_payload(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0}


def _download_validation_status(*, size_bytes: int, expected_size: int, md5: str, expected_md5: str) -> str:
    if expected_size > 0 and size_bytes != expected_size:
        return "validation_failed"
    if expected_md5 and md5.lower() != expected_md5.lower():
        return "validation_failed"
    return "pass"


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"sources": [], "errors": [f"manifest missing: {path}"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"sources": [], "errors": [f"manifest invalid: {exc}"]}
    return deepcopy(payload) if isinstance(payload, dict) else {"sources": []}


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in value.strip())
    return safe or "neon_candidate.h5"


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("/", " ").replace("-", " ").replace("_", " ").lower().split())


def _has_segment(segments: list[str], expected: set[str]) -> bool:
    normalized_expected = {_normalize_text(item) for item in expected}
    return any(segment in normalized_expected for segment in segments)
