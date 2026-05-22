from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any

from models.hf_models import NormalizedHFFrame


@dataclass(slots=True)
class ClockSyncResult:
    rows: list[NormalizedHFFrame]
    summary: dict[str, Any]


def apply_clock_sync_to_rows(
    rows: list[NormalizedHFFrame],
    *,
    config: dict[str, Any],
    metadata: object | dict[str, Any] | None = None,
) -> ClockSyncResult:
    """Apply deterministic acquisition-clock alignment before window slicing.

    ``offset_seconds`` is defined as the correction added to the raw acquisition
    timestamp: ``corrected_timestamp = raw_timestamp + offset_seconds``.
    """

    clock_config = extract_clock_sync_config(config=config, metadata=metadata)
    method = str(clock_config.get("method", "gps_ptp_offset_drift_v1") or "gps_ptp_offset_drift_v1")
    clock_source = str(clock_config.get("clock_source", "") or "")
    enabled = _is_enabled(clock_config)
    if not enabled:
        return ClockSyncResult(
            rows=list(rows),
            summary=_disabled_summary(
                method=method,
                clock_source=clock_source,
                reason="clock_sync.enabled is false and no explicit offset/drift/events were provided.",
            ),
        )
    if not rows:
        return ClockSyncResult(
            rows=[],
            summary={
                "artifact_type": "acquisition_clock_sync",
                "status": "no_rows",
                "enabled": True,
                "method": method,
                "clock_source": clock_source,
                "sample_count": 0,
                "provenance": "Clock synchronization was requested, but no high-frequency rows were available.",
                "limitations": ["No timestamp correction could be applied without input rows."],
            },
        )

    sorted_events = _parse_clock_events(clock_config, row_reference=rows[0].timestamp)
    reference_time = _parse_datetime(clock_config.get("reference_time"), row_reference=rows[0].timestamp) or rows[0].timestamp
    base_offset = _optional_float(clock_config.get("offset_seconds"), 0.0)
    drift_ppm = _optional_float(clock_config.get("drift_ppm"), 0.0)
    source_file = str(clock_config.get("source_file", "") or clock_config.get("clock_log_file", "") or "")
    corrected_rows: list[NormalizedHFFrame] = []
    offsets: list[float] = []
    original_times: list[datetime] = []
    corrected_times: list[datetime] = []

    for row in rows:
        offset_s = _offset_for_timestamp(
            timestamp=row.timestamp,
            events=sorted_events,
            reference_time=reference_time,
            base_offset=base_offset,
            drift_ppm=drift_ppm,
        )
        corrected_time = row.timestamp + timedelta(seconds=offset_s)
        offsets.append(offset_s)
        original_times.append(row.timestamp)
        corrected_times.append(corrected_time)
        corrected_rows.append(
            _copy_frame_with_clock_sync(
                row,
                corrected_time=corrected_time,
                offset_seconds=offset_s,
                method=method,
                clock_source=clock_source,
            )
        )

    summary = {
        "artifact_type": "acquisition_clock_sync",
        "status": "applied",
        "enabled": True,
        "method": method,
        "clock_source": clock_source,
        "sample_count": len(rows),
        "event_count": len(sorted_events),
        "offset_seconds": base_offset,
        "drift_ppm": drift_ppm,
        "reference_time": reference_time.isoformat(),
        "first_original_time": original_times[0].isoformat(),
        "first_corrected_time": corrected_times[0].isoformat(),
        "last_original_time": original_times[-1].isoformat(),
        "last_corrected_time": corrected_times[-1].isoformat(),
        "min_offset_seconds": round(min(offsets), 9),
        "max_offset_seconds": round(max(offsets), 9),
        "mean_offset_seconds": round(sum(offsets) / len(offsets), 9),
        "jitter_threshold_seconds": _optional_float(clock_config.get("jitter_threshold_seconds"), None),
        "source_file": source_file,
        "correction_sign": "corrected_timestamp = raw_timestamp + offset_seconds",
        "event_interpolation": "linear_clamped" if sorted_events else "offset_plus_linear_drift",
        "source_reference": {
            "smartflux": "https://bio.licor.com/env/products/eddy-covariance/smartflux",
            "eddypro_capability": "SmartFlux deployments use GPS/PTP synchronization for acquisition timing.",
        },
        "provenance": (
            "Post-acquisition GPS/PTP clock alignment applied before RP/FCC window slicing. "
            "The original row timestamp is preserved inside raw_text.clock_sync.original_timestamp."
        ),
        "limitations": [
            "This aligns recorded timestamps and does not discipline the physical acquisition clock.",
            "PTP servo and GPS PPS logs are parsed by daemon_telemetry for health provenance; clock_sync still expects offset/drift/events or controller-supplied corrections for timestamp discipline.",
            "Event offsets are linearly interpolated and clamped outside the event range.",
        ],
    }
    if sorted_events:
        summary["events"] = [
            {"timestamp": item["timestamp"].isoformat(), "offset_seconds": item["offset_seconds"]}
            for item in sorted_events
        ]
    return ClockSyncResult(rows=corrected_rows, summary=summary)


def extract_clock_sync_config(
    *,
    config: dict[str, Any],
    metadata: object | dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    metadata_dict = _metadata_to_dict(metadata) or _metadata_to_dict(config.get("metadata_bundle"))
    for payload in (
        _nested(metadata_dict, "raw_file_description", "extra", "clock_sync"),
        _nested(metadata_dict, "raw_file_settings", "extra", "clock_sync"),
        _nested(metadata_dict, "instruments", "extra", "clock_sync"),
        _nested(config, "timing"),
        _nested(config, "steps", "clock_sync"),
        _nested(config, "clock_sync"),
    ):
        if isinstance(payload, dict):
            merged.update(payload)
    timing = _nested(config, "timing")
    if isinstance(timing, dict) and timing.get("clock_source") and "clock_source" not in merged:
        merged["clock_source"] = timing.get("clock_source")
    raw_extra = _nested(metadata_dict, "raw_file_settings", "extra")
    if isinstance(raw_extra, dict):
        for source_key, target_key in (
            ("clock_source", "clock_source"),
            ("clock_offset_seconds", "offset_seconds"),
            ("clock_drift_ppm", "drift_ppm"),
            ("clock_reference_time", "reference_time"),
        ):
            if source_key in raw_extra and target_key not in merged:
                merged[target_key] = raw_extra[source_key]
    merged.setdefault("method", "gps_ptp_offset_drift_v1")
    merged.setdefault("clock_source", "")
    return merged


def clock_sync_diagnostics(summary: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(summary or {})
    return {
        "clock_sync_status": payload.get("status", "disabled"),
        "clock_sync_method": payload.get("method", ""),
        "clock_sync_source": payload.get("clock_source", ""),
        "clock_sync_mean_offset_s": payload.get("mean_offset_seconds"),
        "clock_sync_min_offset_s": payload.get("min_offset_seconds"),
        "clock_sync_max_offset_s": payload.get("max_offset_seconds"),
        "clock_sync_event_count": payload.get("event_count", 0),
        "clock_sync_reference_time": payload.get("reference_time", ""),
        "clock_sync_provenance": payload.get("provenance", ""),
        "clock_sync_detail": payload,
    }


def _is_enabled(config: dict[str, Any]) -> bool:
    explicit = config.get("enabled", config.get("apply", config.get("sync_enabled")))
    if explicit is not None:
        return _truthy(explicit)
    return any(
        key in config and config.get(key) not in (None, "", [], {})
        for key in ("offset_seconds", "drift_ppm", "events", "clock_events")
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "enabled", "apply", "on"}


def _disabled_summary(*, method: str, clock_source: str, reason: str) -> dict[str, Any]:
    return {
        "artifact_type": "acquisition_clock_sync",
        "status": "disabled",
        "enabled": False,
        "method": method,
        "clock_source": clock_source,
        "sample_count": 0,
        "event_count": 0,
        "reason": reason,
        "provenance": "Clock synchronization was not applied.",
        "limitations": [],
    }


def _offset_for_timestamp(
    *,
    timestamp: datetime,
    events: list[dict[str, Any]],
    reference_time: datetime,
    base_offset: float,
    drift_ppm: float,
) -> float:
    if not events:
        elapsed_s = (timestamp - reference_time).total_seconds()
        return float(base_offset + elapsed_s * drift_ppm * 1e-6)
    if timestamp <= events[0]["timestamp"]:
        return float(events[0]["offset_seconds"])
    if timestamp >= events[-1]["timestamp"]:
        return float(events[-1]["offset_seconds"])
    for left, right in zip(events, events[1:]):
        left_ts = left["timestamp"]
        right_ts = right["timestamp"]
        if left_ts <= timestamp <= right_ts:
            span_s = max((right_ts - left_ts).total_seconds(), 1e-12)
            ratio = (timestamp - left_ts).total_seconds() / span_s
            return float(left["offset_seconds"] + ratio * (right["offset_seconds"] - left["offset_seconds"]))
    return float(events[-1]["offset_seconds"])


def _parse_clock_events(config: dict[str, Any], *, row_reference: datetime) -> list[dict[str, Any]]:
    raw_events = config.get("events", config.get("clock_events", []))
    if isinstance(raw_events, str):
        try:
            raw_events = json.loads(raw_events)
        except json.JSONDecodeError:
            raw_events = []
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        timestamp = _parse_datetime(
            item.get("timestamp", item.get("time", item.get("source_time"))),
            row_reference=row_reference,
        )
        offset = _optional_float(
            item.get("offset_seconds", item.get("offset_s", item.get("correction_seconds"))),
            None,
        )
        if timestamp is None or offset is None:
            continue
        events.append({"timestamp": timestamp, "offset_seconds": float(offset)})
    return sorted(events, key=lambda item: item["timestamp"])


def _parse_datetime(value: Any, *, row_reference: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if row_reference.tzinfo is None and parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    if row_reference.tzinfo is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=row_reference.tzinfo)
    return parsed


def _optional_float(value: Any, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _copy_frame_with_clock_sync(
    row: NormalizedHFFrame,
    *,
    corrected_time: datetime,
    offset_seconds: float,
    method: str,
    clock_source: str,
) -> NormalizedHFFrame:
    raw_payload = _raw_payload(row.raw_text)
    raw_payload["clock_sync"] = {
        "status": "applied",
        "method": method,
        "clock_source": clock_source,
        "original_timestamp": row.timestamp.isoformat(),
        "corrected_timestamp": corrected_time.isoformat(),
        "offset_seconds": round(offset_seconds, 9),
    }
    status_text = str(row.status_text or "")
    status_suffix = f"clock_sync={method}"
    if status_text and status_suffix not in status_text:
        status_text = f"{status_text}; {status_suffix}"
    elif not status_text:
        status_text = status_suffix
    return NormalizedHFFrame(
        timestamp=corrected_time,
        device_uid=row.device_uid,
        device_id=row.device_id,
        mode=row.mode,
        frame_quality=row.frame_quality,
        co2_ppm=row.co2_ppm,
        h2o_mmol=row.h2o_mmol,
        pressure_kpa=row.pressure_kpa,
        chamber_temp_c=row.chamber_temp_c,
        case_temp_c=row.case_temp_c,
        status_text=status_text,
        raw_text=json.dumps(raw_payload, ensure_ascii=False, separators=(",", ":")),
        ch4_ppb=row.ch4_ppb,
    )


def _raw_payload(raw_text: str) -> dict[str, Any]:
    if not raw_text:
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"raw_text_original": raw_text}
    if isinstance(payload, dict):
        return payload
    return {"raw_text_original": payload}


def _metadata_to_dict(metadata: object | dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return dict(metadata)
    to_dict = getattr(metadata, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except (TypeError, ValueError):
            return {}
    return {}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
