from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any
from urllib.request import Request, urlopen

from models.hf_models import FrameQuality, NormalizedHFFrame


DEFAULT_NEON_HDF5_OUTPUT_ROOT = Path("artifacts/public_ec_data/neon")
REQUIRED_RAW_TO_FINAL_FIELDS = ["time", "u", "v", "w", "sonic_temperature", "co2", "h2o"]
ROW_EXTRACTION_REQUIRED_FIELDS = ["u", "v", "w", "co2", "h2o", "sonic_temperature"]


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


def build_neon_hdf5_row_extraction_smoke(
    hdf5_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    metadata_smoke_path: str | Path | None = None,
    source_id: str = "",
    rows_output_path: str | Path | None = None,
    max_rows: int = 128,
    start_index: int = 0,
    max_time_gap_s: float = 900.0,
    include_row_records: bool = False,
) -> dict[str, Any]:
    """Extract a small NEON HDF5 row window into the project's normalized row contract."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    path = _resolve(root, hdf5_path)
    metadata_path = _resolve(root, metadata_smoke_path) if metadata_smoke_path else None
    dependency = _load_h5py()
    metadata_smoke = _read_json(metadata_path) if metadata_path else build_neon_hdf5_metadata_smoke(
        path,
        workspace_root=root,
        source_id=source_id,
    )
    base = {
        "artifact_type": "neon_hdf5_row_extraction_smoke_v1",
        "generated_at": datetime.now().isoformat(),
        "source_id": source_id or str(metadata_smoke.get("source_id", "")),
        "source_file": str(path),
        "metadata_smoke_artifact": str(metadata_path) if metadata_path else "",
        "metadata_smoke_status": str(metadata_smoke.get("status", "")),
        "hdf5_dependency": dependency["summary"],
        "status": "blocked",
        "can_change_full_parity_gate": False,
        "ready_for_raw_to_final_registration": False,
        "truthfulness_boundary": (
            "This artifact converts a small NEON HDF5 aggregated-data window into normalized rows for importer "
            "smoke testing only. NEON DP4 HDF5 is not an EddyPro raw bundle and this does not provide official "
            "EddyPro output parity."
        ),
    }
    if not dependency["available"]:
        return {**base, "status": "missing_hdf5_dependency", "errors": ["Install h5py to extract NEON HDF5 rows."]}
    if not path.exists() or not path.is_file():
        return {**base, "status": "file_missing", "errors": [f"HDF5 file missing: {path}"]}
    field_mappings = dict(metadata_smoke.get("field_mappings", {}) or {})
    missing_mapping = [field for field in ROW_EXTRACTION_REQUIRED_FIELDS if field not in field_mappings]
    if missing_mapping:
        return {
            **base,
            "status": "mapping_incomplete",
            "missing_required_mappings": missing_mapping,
            "field_mappings": field_mappings,
        }

    h5py = dependency["module"]
    try:
        with h5py.File(path, "r") as hdf:
            extraction = _extract_neon_rows_from_hdf(
                hdf,
                field_mappings=field_mappings,
                source_file=path,
                source_id=str(base["source_id"] or "neon_hdf5"),
                max_rows=max_rows,
                start_index=start_index,
                max_time_gap_s=max_time_gap_s,
            )
    except Exception as exc:
        return {**base, "status": "row_extraction_failed", "errors": [str(exc)]}

    rows = list(extraction.pop("rows"))
    rows_output = _write_row_records(root, rows_output_path, rows) if rows_output_path else {}
    row_count = len(rows)
    status = "pass" if row_count >= min(64, max(1, int(max_rows))) else ("partial" if row_count else "no_complete_rows")
    payload: dict[str, Any] = {
        **base,
        "status": status,
        "row_count": row_count,
        "row_preview": rows[:5],
        "rows_output": rows_output,
        "field_mappings": field_mappings,
        "field_units": extraction["field_units"],
        "qc_mapping": extraction["qc_mapping"],
        "alignment_summary": extraction["alignment_summary"],
        "estimated_sample_rate_hz": extraction["estimated_sample_rate_hz"],
        "time_range": extraction["time_range"],
        "rp_smoke_ready": row_count >= 64,
        "known_limitations": [
            "Rows are extracted from NEON aggregated HDF5 products, not high-frequency EddyPro raw samples.",
            "Different NEON variables may have different averaging intervals and instrument heights.",
            "QC flags are carried as NEON qfFinl values when matching qfqm datasets exist; EddyPro flag parity is not claimed.",
        ],
        "next_action": (
            "Run the NEON HDF5 RP smoke and then implement a declared NEON-specific validation target."
            if row_count >= 64
            else "Increase max_rows or adjust start_index after the first complete CO2/H2O/sonic overlap."
        ),
    }
    if include_row_records:
        payload["row_records"] = rows
    return payload


def row_records_to_normalized_frames(records: list[dict[str, Any]]) -> list[NormalizedHFFrame]:
    frames: list[NormalizedHFFrame] = []
    for record in records:
        frames.append(
            NormalizedHFFrame(
                timestamp=_parse_datetime(str(record["timestamp"])),
                device_uid=str(record.get("device_uid", "neon_hdf5")),
                device_id=str(record.get("device_id", "NEON")),
                mode=int(record.get("mode", 2)),
                frame_quality=FrameQuality(str(record.get("frame_quality", FrameQuality.FULL.value))),
                co2_ppm=_optional_number(record.get("co2_ppm")),
                h2o_mmol=_optional_number(record.get("h2o_mmol")),
                pressure_kpa=_optional_number(record.get("pressure_kpa")),
                chamber_temp_c=_optional_number(record.get("chamber_temp_c")),
                case_temp_c=_optional_number(record.get("case_temp_c")),
                ch4_ppb=_optional_number(record.get("ch4_ppb")),
                status_text=str(record.get("status_text", "")) or None,
                raw_text=str(record.get("raw_text", "")),
            )
        )
    return frames


def _extract_neon_rows_from_hdf(
    hdf: Any,
    *,
    field_mappings: dict[str, Any],
    source_file: Path,
    source_id: str,
    max_rows: int,
    start_index: int,
    max_time_gap_s: float,
) -> dict[str, Any]:
    series_by_field: dict[str, list[dict[str, Any]]] = {}
    field_units: dict[str, str] = {}
    qc_mapping: dict[str, Any] = {}
    fields = [
        "time",
        "u",
        "v",
        "w",
        "co2",
        "h2o",
        "sonic_temperature",
        "air_temperature",
        "pressure",
        "ch4",
    ]
    for field in fields:
        mapping = dict(field_mappings.get(field, {}) or {})
        dataset_path = str(mapping.get("path", ""))
        if not dataset_path or dataset_path.strip("/") not in hdf:
            continue
        dataset = hdf[dataset_path]
        unit = _mean_unit(dataset.attrs)
        field_units[field] = unit
        series_by_field[field] = _read_neon_dataset_series(dataset, field=field, unit=unit)
        qc_mapping[field] = _read_neon_qc_mapping(hdf, dataset_path)

    base_field = "time" if series_by_field.get("time") else "u"
    base_series = series_by_field.get(base_field, [])
    indexed = {field: _index_series(series) for field, series in series_by_field.items()}
    resolved_start = _first_complete_base_index(
        base_series,
        indexed=indexed,
        requested_start=max(0, int(start_index)),
        max_time_gap_s=max_time_gap_s,
    )
    rows: list[dict[str, Any]] = []
    if resolved_start >= 0:
        for base_item in base_series[resolved_start:]:
            if len(rows) >= max(0, int(max_rows)):
                break
            timestamp = base_item["center"]
            matched = {
                field: _series_item_at_time(indexed.get(field, {}), timestamp, max_time_gap_s=max_time_gap_s)
                for field in series_by_field
                if field != "time"
            }
            required_missing = [field for field in ROW_EXTRACTION_REQUIRED_FIELDS if matched.get(field) is None]
            if required_missing:
                continue
            rows.append(
                _build_neon_row_record(
                    timestamp=timestamp,
                    matched=matched,
                    field_units=field_units,
                    qc_mapping=qc_mapping,
                    source_file=source_file,
                    source_id=source_id,
                )
            )

    estimated_sample_rate_hz = _estimate_sample_rate_from_records(rows)
    return {
        "rows": rows,
        "field_units": field_units,
        "qc_mapping": qc_mapping,
        "estimated_sample_rate_hz": estimated_sample_rate_hz,
        "time_range": _row_time_range(rows),
        "alignment_summary": {
            "base_field": base_field,
            "base_path": str(dict(field_mappings.get(base_field, {}) or {}).get("path", "")),
            "base_series_count": len(base_series),
            "resolved_start_index": resolved_start,
            "requested_start_index": int(start_index),
            "max_time_gap_s": float(max_time_gap_s),
            "series_counts": {field: len(series) for field, series in series_by_field.items()},
            "required_fields": ROW_EXTRACTION_REQUIRED_FIELDS,
        },
    }


def _read_neon_dataset_series(dataset: Any, *, field: str, unit: str) -> list[dict[str, Any]]:
    data = dataset[:]
    dtype_fields = list((dataset.dtype.fields or {}).keys())
    if dtype_fields:
        names = {str(name).lower(): str(name) for name in dtype_fields}
        value_name = names.get("mean") or _first_numeric_compound_field(data, dtype_fields)
        start_name = names.get("timebgn") or names.get("time_bgn")
        end_name = names.get("timeend") or names.get("time_end")
        if not value_name:
            return []
        series: list[dict[str, Any]] = []
        for index, record in enumerate(data):
            value = _optional_number(record[value_name])
            start = _parse_datetime(_decode_scalar(record[start_name])) if start_name else None
            end = _parse_datetime(_decode_scalar(record[end_name])) if end_name else start
            if value is None or start is None:
                continue
            end = end or start
            series.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "center": _midpoint_datetime(start, end),
                    "value": _convert_neon_value(field, value, unit),
                    "raw_value": value,
                    "unit": unit,
                    "num_samp": _optional_number(record[names["numsamp"]]) if "numsamp" in names else None,
                }
            )
        return series

    return []


def _first_numeric_compound_field(data: Any, fields: list[str]) -> str:
    for field in fields:
        try:
            value = data[field][0] if len(data) else None
        except Exception:
            continue
        if _optional_number(value) is not None:
            return str(field)
    return ""


def _read_neon_qc_mapping(hdf: Any, dataset_path: str) -> dict[str, Any]:
    normalized = "/" + dataset_path.strip("/")
    qc_path = normalized.replace("/data/", "/qfqm/", 1)
    if qc_path.strip("/") not in hdf:
        return {"status": "not_found", "path": qc_path, "flag_field": ""}
    dataset = hdf[qc_path]
    fields = list((dataset.dtype.fields or {}).keys())
    lowered = {str(field).lower(): str(field) for field in fields}
    flag_field = lowered.get("qffinl") or lowered.get("qf") or lowered.get("flag") or ""
    return {
        "status": "mapped" if flag_field else "dataset_found_no_flag_field",
        "path": qc_path,
        "flag_field": flag_field,
        "dtype": str(dataset.dtype),
        "shape": list(dataset.shape or []),
    }


def _index_series(series: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "series": series,
        "starts": [item["start"] for item in series],
        "centers": [item["center"] for item in series],
    }


def _first_complete_base_index(
    base_series: list[dict[str, Any]],
    *,
    indexed: dict[str, dict[str, Any]],
    requested_start: int,
    max_time_gap_s: float,
) -> int:
    for index in range(max(0, requested_start), len(base_series)):
        timestamp = base_series[index]["center"]
        if all(_series_item_at_time(indexed.get(field, {}), timestamp, max_time_gap_s=max_time_gap_s) for field in ROW_EXTRACTION_REQUIRED_FIELDS):
            return index
    return -1


def _series_item_at_time(indexed: dict[str, Any], timestamp: datetime, *, max_time_gap_s: float) -> dict[str, Any] | None:
    series = list(indexed.get("series", []) or [])
    starts = list(indexed.get("starts", []) or [])
    if not series:
        return None
    index = bisect_right(starts, timestamp) - 1
    candidates = [idx for idx in (index, index + 1) if 0 <= idx < len(series)]
    best: dict[str, Any] | None = None
    best_gap = math.inf
    for candidate_index in candidates:
        item = series[candidate_index]
        if item["start"] <= timestamp <= item["end"]:
            return item
        gap = abs((item["center"] - timestamp).total_seconds())
        if gap < best_gap:
            best = item
            best_gap = gap
    return best if best is not None and best_gap <= float(max_time_gap_s) else None


def _build_neon_row_record(
    *,
    timestamp: datetime,
    matched: dict[str, dict[str, Any] | None],
    field_units: dict[str, str],
    qc_mapping: dict[str, Any],
    source_file: Path,
    source_id: str,
) -> dict[str, Any]:
    raw_payload: dict[str, Any] = {
        "raw_source": str(source_file),
        "source_id": source_id,
        "source_format": "NEON_HDF5_DP4",
        "u": _item_value(matched.get("u")),
        "v": _item_value(matched.get("v")),
        "w": _item_value(matched.get("w")),
        "neon_units": field_units,
        "neon_num_samp": {
            field: _item_num_samp(item)
            for field, item in matched.items()
            if item is not None and _item_num_samp(item) is not None
        },
        "neon_interval": {
            field: {
                "start": item["start"].isoformat(),
                "end": item["end"].isoformat(),
            }
            for field, item in matched.items()
            if item is not None
        },
        "neon_qc_mapping": qc_mapping,
    }
    ch4_ppb = _item_value(matched.get("ch4"))
    if ch4_ppb is not None:
        raw_payload["ch4_ppb"] = ch4_ppb
    return NormalizedHFFrame(
        timestamp=timestamp,
        device_uid="neon_hdf5",
        device_id=source_id or "NEON",
        mode=2,
        frame_quality=FrameQuality.FULL,
        co2_ppm=_item_value(matched.get("co2")),
        h2o_mmol=_item_value(matched.get("h2o")),
        pressure_kpa=_item_value(matched.get("pressure")),
        chamber_temp_c=_item_value(matched.get("sonic_temperature")),
        case_temp_c=_item_value(matched.get("air_temperature")),
        ch4_ppb=ch4_ppb,
        status_text="neon_hdf5_row_smoke",
        raw_text=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
    ).to_record()


def _write_row_records(root: Path, rows_output_path: str | Path | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows_output_path:
        return {}
    path = _resolve(root, rows_output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "row_count": len(rows)}


def _row_time_range(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {"start": "", "end": ""}
    return {"start": str(rows[0].get("timestamp", "")), "end": str(rows[-1].get("timestamp", ""))}


def _estimate_sample_rate_from_records(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2:
        return 1.0
    timestamps = [_parse_datetime(str(row["timestamp"])) for row in rows[: min(len(rows), 16)]]
    deltas = [
        (right - left).total_seconds()
        for left, right in zip(timestamps[:-1], timestamps[1:])
        if (right - left).total_seconds() > 0
    ]
    if not deltas:
        return 1.0
    deltas_sorted = sorted(deltas)
    median = deltas_sorted[len(deltas_sorted) // 2]
    return round(1.0 / median, 8) if median > 0 else 1.0


def _mean_unit(attrs: Any) -> str:
    for key in ("unit", "units", "Unit", "UNITS"):
        if key not in attrs:
            continue
        value = _json_value(attrs[key])
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value)
    return ""


def _convert_neon_value(field: str, value: float, unit: str) -> float:
    unit_key = unit.lower().replace(" ", "")
    if field == "co2":
        if "mmol" in unit_key:
            return float(value) * 1000.0
        if "mol-1" in unit_key and "umol" not in unit_key and "ppm" not in unit_key:
            return float(value) * 1_000_000.0
        return float(value)
    if field == "h2o":
        if "umol" in unit_key:
            return float(value) / 1000.0
        if "mol-1" in unit_key and "mmol" not in unit_key:
            return float(value) * 1000.0
        return float(value)
    if field == "ch4":
        if "nmol" in unit_key or "ppb" in unit_key:
            return float(value)
        if "umol" in unit_key or "ppm" in unit_key:
            return float(value) * 1000.0
        if "mmol" in unit_key:
            return float(value) * 1_000_000.0
        if "mol-1" in unit_key:
            return float(value) * 1_000_000_000.0
        return float(value)
    if field == "pressure":
        if "pa" == unit_key or unit_key.endswith(" pa"):
            return float(value) / 1000.0
        if "hpa" in unit_key or "mbar" in unit_key:
            return float(value) / 10.0
        return float(value)
    if field in {"sonic_temperature", "air_temperature"} and unit_key in {"k", "kelvin"}:
        return float(value) - 273.15
    return float(value)


def _item_value(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    return _optional_number(item.get("value"))


def _item_num_samp(item: dict[str, Any] | None) -> float | None:
    if not item:
        return None
    return _optional_number(item.get("num_samp"))


def _midpoint_datetime(start: datetime, end: datetime) -> datetime:
    return start + (end - start) / 2


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=None)


def _decode_scalar(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "item"):
        try:
            item = value.item()
            if isinstance(item, bytes):
                return item.decode("utf-8", "replace")
            return str(item)
        except Exception:
            pass
    return str(value)


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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

    if last_compact in {"rtiomoledryco2", "rtiomolewetco2"} and "/data/co2turb/" in path.lower().replace("\\", "/"):
        add("co2", 0.98, "NEON co2Turb mole-ratio dataset maps to CO2 mixing ratio")
    elif last_compact == "densmoleco2" and "/data/co2turb/" in path.lower().replace("\\", "/"):
        add("co2", 0.95, "NEON co2Turb density dataset maps to CO2 concentration")
    elif "co2" in last_compact or "carbondioxide" in _normalize_text(long_name).replace(" ", ""):
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
    if last_compact == "presatm":
        add("pressure", 0.9, "NEON atmospheric pressure dataset")
    elif last_compact == "pressum":
        add("pressure", 0.86, "NEON pressure summary dataset")
    elif last_compact == "pres" or "pressure" in normalized or "barometric" in normalized or _has_segment(
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
