from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any

from core.acquisition.runtime_watchdog import attach_runtime_watchdog, build_runtime_watchdog_manifest
from core.comparison.eddypro_coverage_audit import build_eddypro_coverage_audit
from core.comparison.eddypro_release_gate import build_eddypro_release_gate
from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
from core.comparison.fixture_pack import (
    acquire_public_eddypro_fixture_files,
    build_fixture_pack_summary,
    build_official_raw_fixture_detail,
    build_official_raw_fixture_manifest,
    build_public_eddypro_fixture_catalog,
    inspect_public_official_raw_archive,
    materialize_public_official_raw_bundle_draft,
)
from core.comparison.public_ec_data_discovery import build_public_ec_data_discovery_probe
from core.comparison.official_raw_fixture_bundle import (
    build_official_raw_fixture_bundle_manifest,
    build_official_raw_fixture_bundle_manifest_batch,
    build_official_raw_fixture_evidence_pack,
    build_official_raw_fixture_repair_plan,
    build_official_eddypro_executable_readiness,
    capture_official_eddypro_run_evidence,
    discover_official_raw_fixture_bundles,
    inspect_official_raw_fixture_bundle,
    prepare_official_eddypro_project_for_capture,
    register_official_raw_fixture_bundle,
    register_official_raw_fixture_bundle_batch,
    run_official_raw_evidence_pack_acceptance,
    validate_official_raw_fixture_acquisition,
)
from core.ec_fcc.pipeline import ECFCCPipeline
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from core.storage.ghg_bundle import load_ghg_normalized_frames
from core.storage.clock_sync import apply_clock_sync_to_rows
from core.storage.raw_importer import can_load_raw_native, can_load_raw_text, load_raw_native_frames, load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle


def run_headless_batch(
    *,
    config: dict[str, Any],
    metadata: MetadataBundle | dict[str, Any],
    rows: list[NormalizedHFFrame],
    data_source: str = "headless",
    time_range: str = "",
) -> dict[str, Any]:
    batch_started_at = datetime.now()
    batch_timer = time.perf_counter()
    metadata_bundle = metadata if isinstance(metadata, MetadataBundle) else MetadataBundle.from_dict(dict(metadata))
    base_config = deepcopy(config)
    base_config.setdefault("metadata_bundle", metadata_bundle.to_dict())
    clock_sync_result = apply_clock_sync_to_rows(rows, config=base_config, metadata=metadata_bundle)
    synced_rows = clock_sync_result.rows
    clock_sync_summary = clock_sync_result.summary
    pipeline_config = deepcopy(base_config)
    pipeline_config["_clock_sync_already_applied"] = True
    pipeline_config["_clock_sync_summary"] = clock_sync_summary
    payload = {
        "config": config,
        "metadata": metadata_bundle.to_dict(),
        "rows": [row.to_record() for row in synced_rows],
        "clock_sync_summary": clock_sync_summary,
    }
    batch_digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    rp_pipeline = ECRPPipeline()
    spectral_pipeline = ECFCCPipeline()
    rp_result = rp_pipeline.run(
        rows=synced_rows,
        project=metadata_bundle.project,
        site=metadata_bundle.site,
        config=pipeline_config,
        data_source=data_source,
        time_range=time_range,
    )
    spectral_result = spectral_pipeline.run(
        rows=synced_rows,
        project=metadata_bundle.project,
        site=metadata_bundle.site,
        config=pipeline_config,
        data_source=data_source,
        time_range=time_range,
    )
    _replace_config_snapshot(rp_result, base_config)
    _replace_config_snapshot(spectral_result, base_config)
    deterministic_created_at = synced_rows[0].timestamp if synced_rows else datetime(2000, 1, 1)
    rp_result.run_id = f"rp_det_{batch_digest}"
    rp_result.created_at = deterministic_created_at
    spectral_result.run_id = f"spectral_det_{batch_digest}"
    spectral_result.created_at = deterministic_created_at
    manifest = build_batch_manifest(
        batch_id=batch_digest,
        metadata_bundle=metadata_bundle,
        config=base_config,
        rows=synced_rows,
        rp_result=rp_result,
        spectral_result=spectral_result,
        clock_sync_summary=clock_sync_summary,
        runtime_started_at=batch_started_at,
        runtime_completed_at=datetime.now(),
        runtime_elapsed_ms=round((time.perf_counter() - batch_timer) * 1000.0, 3),
    )
    return {
        "batch_id": batch_digest,
        "metadata_snapshot": metadata_bundle.to_dict(),
        "raw_import_summary": _raw_import_summary(synced_rows),
        "clock_sync_summary": clock_sync_summary,
        "runtime_watchdog_summary": manifest.get("runtime_watchdog_summary", {}),
        "project_snapshot": asdict(metadata_bundle.project),
        "site_snapshot": asdict(metadata_bundle.site),
        "rp_result": rp_result,
        "spectral_result": spectral_result,
        "manifest": manifest,
    }


def _replace_config_snapshot(run_result: Any, config: dict[str, Any]) -> None:
    public_config = deepcopy(config)
    if isinstance(getattr(run_result, "summary", None), dict):
        run_result.summary["config_snapshot"] = deepcopy(public_config)
    artifacts = getattr(run_result, "artifacts", None)
    if isinstance(artifacts, dict):
        artifacts["config_snapshot"] = deepcopy(public_config)


def _synthetic_eddypro_parity_summary(config: dict[str, Any]) -> dict[str, Any]:
    if not _synthetic_eddypro_parity_enabled(config):
        return {}
    from core.comparison.synthetic_parity import run_synthetic_eddypro_parity_suite

    return run_synthetic_eddypro_parity_suite()


def _raw_to_final_parity_summary(config: dict[str, Any], *, metadata_bundle: MetadataBundle) -> dict[str, Any]:
    cfg = dict(config.get("raw_to_final_parity", {}) or {})
    if not _truthy(cfg.get("enabled")):
        return {}
    raw_path = cfg.get("raw_path") or cfg.get("input_path")
    if not raw_path:
        return {}
    from core.comparison.raw_to_final_parity import run_raw_to_final_parity_harness

    return run_raw_to_final_parity_harness(
        raw_path=raw_path,
        metadata=cfg.get("metadata") or cfg.get("metadata_snapshot") or metadata_bundle.to_dict(),
        rp_config=config,
        reference_json_path=cfg.get("reference_json_path") or cfg.get("reference_json"),
        reference_windows=list(cfg.get("reference_windows", []) or []),
        fixture_id=str(cfg.get("fixture_id", "")),
        thresholds=dict(cfg.get("thresholds", {}) or {}),
        data_source=str(cfg.get("data_source", "raw_to_final_parity")),
        time_range=str(cfg.get("time_range", "")),
    )


def _synthetic_eddypro_parity_enabled(config: dict[str, Any]) -> bool:
    candidates = (
        config.get("synthetic_eddypro_parity"),
        config.get("synthetic_parity"),
        dict(config.get("benchmark", {}) if isinstance(config.get("benchmark", {}), dict) else {}).get("synthetic_eddypro_parity"),
    )
    for candidate in candidates:
        if isinstance(candidate, bool) and candidate:
            return True
        if isinstance(candidate, dict) and _truthy(candidate.get("enabled")):
            return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def build_batch_manifest(
    *,
    batch_id: str,
    metadata_bundle: MetadataBundle,
    config: dict[str, Any],
    rows: list[NormalizedHFFrame],
    rp_result,
    spectral_result,
    clock_sync_summary: dict[str, Any] | None = None,
    runtime_started_at: datetime | None = None,
    runtime_completed_at: datetime | None = None,
    runtime_elapsed_ms: float | None = None,
) -> dict[str, Any]:
    with TemporaryDirectory() as tmpdir:
        exporter = ResultExporter(Path(tmpdir))
        benchmark_rollup = exporter._benchmark_rollup(rp_result=rp_result, rp_config_snapshot=config)
        reference_provenance = exporter._reference_provenance_payload(rp_result=rp_result, rp_config_snapshot=config)
        network_validation, _network_files = exporter._export_network_artifacts(
            rp_result=rp_result,
            rp_config_snapshot=config,
            export_root=Path(tmpdir),
            site=metadata_bundle.site,
        )
    raw_summary = _raw_import_summary(rows)
    fixture_pack_summary = build_fixture_pack_summary()
    official_raw_fixture_manifest = build_official_raw_fixture_manifest(fixture_summary=fixture_pack_summary)
    public_eddypro_fixture_catalog = dict(
        fixture_pack_summary.get("public_eddypro_fixture_catalog", {})
        or build_public_eddypro_fixture_catalog()
    )
    eddypro_source_inventory = build_eddypro_source_inventory()
    synthetic_parity_summary = _synthetic_eddypro_parity_summary(config)
    raw_to_final_parity_summary = _raw_to_final_parity_summary(config, metadata_bundle=metadata_bundle)
    raw_to_final_trace_gas_parity = dict(raw_to_final_parity_summary.get("trace_gas_parity", {}) or {})
    raw_to_final_parity_diagnostics = dict(raw_to_final_parity_summary.get("parity_diagnostics", {}) or {})
    raw_to_final_parity_failure_groups = [
        str(item.get("category", ""))
        for item in list(raw_to_final_parity_diagnostics.get("failure_groups", []) or [])
        if str(item.get("category", ""))
    ]
    runtime_watchdog = build_runtime_watchdog_manifest(
        batch_id=batch_id,
        config=config,
        rows=rows,
        rp_result=rp_result,
        spectral_result=spectral_result,
        clock_sync_summary=clock_sync_summary or {},
        raw_import_summary=raw_summary,
        network_validation=network_validation,
        run_started_at=runtime_started_at,
        run_completed_at=runtime_completed_at,
        elapsed_ms=runtime_elapsed_ms,
    )
    attach_runtime_watchdog(rp_result, runtime_watchdog)
    attach_runtime_watchdog(spectral_result, runtime_watchdog)
    return {
        "batch_id": batch_id,
        "input_row_count": len(rows),
        "time_range": {
            "start": rows[0].timestamp.isoformat() if rows else None,
            "end": rows[-1].timestamp.isoformat() if rows else None,
        },
        "config_snapshot": deepcopy(config),
        "lag_strategy": config.get("lag_phase", {}).get("strategy", "") or config.get("lag", {}).get("lag_strategy", ""),
        "expected_lag_s": config.get("lag_phase", {}).get("expected_lag_s", "") or config.get("lag", {}).get("expected_lag_s", ""),
        "detrend_mode": config.get("detrend_mode", "") or config.get("detrend", {}).get("detrend_mode", ""),
        "rotation_mode": config.get("rotation_mode", "") or config.get("steps", {}).get("rotation", {}).get("rotation_mode", ""),
        "density_correction_mode": config.get("density_correction_mode", "") or config.get("steps", {}).get("density_correction", {}).get("correction_mode", ""),
        "screening_config": {
            "skewness_threshold": config.get("screening", {}).get("skewness_threshold", 2.0),
            "kurtosis_threshold": config.get("screening", {}).get("kurtosis_threshold", 7.0),
            "dropout_min_run": config.get("screening", {}).get("dropout_min_run", 10),
            "spike_sigma": config.get("screening", {}).get("spike_sigma", 5.0),
            "discontinuity_sigma": config.get("screening", {}).get("discontinuity_sigma", 8.0),
            "absolute_limits": config.get("screening", {}).get("absolute_limits", None),
        },
        "metadata_snapshot": metadata_bundle.to_dict(),
        "raw_import_summary": raw_summary,
        "fixture_pack_summary": fixture_pack_summary,
        "official_raw_fixture_manifest": official_raw_fixture_manifest,
        "public_eddypro_fixture_catalog": public_eddypro_fixture_catalog,
        "eddypro_source_inventory": eddypro_source_inventory,
        "synthetic_eddypro_parity": synthetic_parity_summary,
        "raw_to_final_parity": raw_to_final_parity_summary,
        "raw_to_final_parity_diagnostics": raw_to_final_parity_diagnostics,
        "raw_to_final_parity_failure_groups": raw_to_final_parity_failure_groups,
        "raw_to_final_parity_top_failed_fields": list(raw_to_final_parity_diagnostics.get("top_failed_fields", []) or []),
        "raw_to_final_trace_gas_parity": raw_to_final_trace_gas_parity,
        "raw_to_final_trace_gas_status": str(raw_to_final_trace_gas_parity.get("status", "")),
        "raw_to_final_trace_gas_pass_rate": float(raw_to_final_trace_gas_parity.get("pass_rate", 0.0) or 0.0),
        "raw_to_final_trace_gas_failed_fields": list(raw_to_final_trace_gas_parity.get("failed_fields", []) or []),
        "raw_to_final_trace_gas_coefficient_profile_id": str(raw_to_final_trace_gas_parity.get("coefficient_profile_id", "")),
        "clock_sync_summary": deepcopy(clock_sync_summary or {}),
        "runtime_watchdog_summary": deepcopy(runtime_watchdog),
        "project_snapshot": asdict(metadata_bundle.project),
        "site_snapshot": asdict(metadata_bundle.site),
        "rp_run": {
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "summary": deepcopy(rp_result.summary),
            "window_count": len(rp_result.windows),
        },
        "spectral_run": {
            "run_id": spectral_result.run_id,
            "created_at": spectral_result.created_at.isoformat(),
            "summary": deepcopy(spectral_result.summary),
            "window_count": len(spectral_result.windows),
        },
        "benchmark_status": benchmark_rollup["benchmark_status"],
        "benchmark_target": benchmark_rollup["benchmark_target"],
        "benchmark_reference_id": benchmark_rollup["benchmark_reference_id"],
        "benchmark_thresholds": benchmark_rollup["benchmark_thresholds"],
        "benchmark_deviation_summary": benchmark_rollup["benchmark_deviation_summary"],
        "pass_rate": benchmark_rollup["pass_rate"],
        "failed_fields": benchmark_rollup["failed_fields"],
        "reference_provenance": reference_provenance,
        "continuous_dataset_enabled": bool(config.get("continuous_dataset", {}).get("enabled", False)),
        "schema_target": network_validation.get("schema_target", ""),
        "fluxnet_timezone_offset_h": float(network_validation.get("timezone_offset_hours", 0.0) or 0.0),
        "fluxnet_timestamp_refers_to": network_validation.get("timestamp_refers_to", "start"),
        "network_validation_status": network_validation.get("validation_status", ""),
        "network_missing_fields": network_validation.get("missing_fields", []),
        "network_validation_summary": network_validation,
        "trace_gas_summary": deepcopy(rp_result.summary.get("trace_gas_summary", {})) if isinstance(rp_result.summary, dict) else {},
    }


def _raw_import_summary(rows: list[NormalizedHFFrame]) -> dict[str, Any]:
    native_items: list[dict[str, Any]] = []
    ygas_items: list[dict[str, Any]] = []
    decoded_column_items: list[dict[str, Any]] = []
    for row in rows[:100]:
        try:
            payload = json.loads(row.raw_text or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("raw_native_import"), dict):
            native_items.append(dict(payload["raw_native_import"]))
        if isinstance(payload, dict) and isinstance(payload.get("raw_native_columns"), dict):
            decoded_column_items.append(dict(payload["raw_native_columns"]))
        if isinstance(payload, dict) and isinstance(payload.get("ygas_protocol_import"), dict):
            ygas_items.append(dict(payload["ygas_protocol_import"]))
    if ygas_items:
        first = ygas_items[0]
        return {
            "status": first.get("status", "decoded"),
            "native": False,
            "format": first.get("format", "ygas_protocol"),
            "record_count": len(rows),
            "source_file": first.get("source_file", ""),
            "source_reference": first.get("source_reference", {}),
            "limitations": first.get("limitations", []),
            "gas_analyzer_profile": "ygas_irga",
        }
    if not native_items:
        return {"status": "not_native", "native": False}
    first = native_items[0]
    return {
        "status": first.get("status", "decoded"),
        "native": True,
        "format": first.get("format", ""),
        "data_type": first.get("data_type", ""),
        "column_types": first.get("column_types", []),
        "column_type_source": first.get("column_type_source", ""),
        "record_count": first.get("record_count", len(rows)),
        "decoded_record_count": first.get("decoded_record_count", first.get("record_count", len(rows))),
        "columns": first.get("columns", []),
        "requested_columns": first.get("requested_columns", []),
        "requested_column_source": first.get("requested_column_source", ""),
        "column_source": first.get("column_source", ""),
        "full_record_decode": bool(first.get("full_record_decode", False)),
        "preserved_leading_ulong_values": bool(first.get("preserved_leading_ulong_values", False)),
        "leading_ulong_value_prefix": first.get("leading_ulong_value_prefix", ""),
        "sample_decoded_columns": decoded_column_items[0] if decoded_column_items else {},
        "sample_decoded_column_count": len(decoded_column_items[0]) if decoded_column_items else 0,
        "header_rows": first.get("header_rows", 0),
        "header_row_source": first.get("header_row_source", ""),
        "raw_header_units": first.get("raw_header_units", []),
        "header_units": first.get("header_units", []),
        "raw_header_processing": first.get("raw_header_processing", []),
        "header_processing": first.get("header_processing", []),
        "ascii_header_eol": first.get("ascii_header_eol", "auto"),
        "header_bytes": first.get("header_bytes", 0),
        "ulongs": first.get("ulongs", 0),
        "leading_ulong_columns": first.get("leading_ulong_columns", []),
        "ulongs_source": first.get("ulongs_source", ""),
        "fp2_skip_words": first.get("fp2_skip_words", 0),
        "first_record": first.get("first_record", 1),
        "last_record": first.get("last_record", 0),
        "record_index_offset": first.get("record_index_offset", 0),
        "record_header_bytes": first.get("record_header_bytes", 0),
        "record_length_bytes": first.get("record_length_bytes", 0),
        "record_footer_bytes": first.get("record_footer_bytes", 0),
        "start_time": first.get("start_time", ""),
        "timestamp_source": first.get("timestamp_source", ""),
        "filename_timestamp": first.get("filename_timestamp", {}),
        "record_timestamp": first.get("record_timestamp", {}),
        "source_file": first.get("source_file", ""),
        "header_detection": first.get("header_detection", {}),
        "tob1_eddypro_compatibility": first.get("tob1_eddypro_compatibility", {}),
        "source_reference": first.get("source_reference", {}),
        "limitations": first.get("limitations", []),
    }


def load_config_file(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_metadata_file(path: str | Path) -> MetadataBundle:
    return MetadataBundle.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_input_rows(path: str | Path, metadata: MetadataBundle | dict[str, Any] | None = None) -> list[NormalizedHFFrame]:
    input_path = Path(path)
    metadata_bundle = metadata if isinstance(metadata, MetadataBundle) else (MetadataBundle.from_dict(dict(metadata)) if metadata else None)
    if input_path.suffix.lower() == ".ghg":
        return load_ghg_normalized_frames(input_path)
    if can_load_raw_native(input_path, metadata_bundle):
        return load_raw_native_frames(input_path, metadata=metadata_bundle)
    if can_load_raw_text(input_path):
        return load_raw_text_frames(input_path, metadata=metadata_bundle)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Input data file must contain a JSON list of row objects.")
    rows: list[NormalizedHFFrame] = []
    for item in payload:
        row = dict(item)
        rows.append(
            NormalizedHFFrame(
                timestamp=datetime.fromisoformat(str(row["timestamp"])),
                device_uid=str(row.get("device_uid", "headless")),
                device_id=str(row.get("device_id", "000")),
                mode=int(row.get("mode", 2)),
                frame_quality=FrameQuality(str(row.get("frame_quality", FrameQuality.FULL.value))),
                co2_ppm=_optional_float(row.get("co2_ppm")),
                h2o_mmol=_optional_float(row.get("h2o_mmol")),
                ch4_ppb=_optional_float(row.get("ch4_ppb")),
                pressure_kpa=_optional_float(row.get("pressure_kpa")),
                chamber_temp_c=_optional_float(row.get("chamber_temp_c")),
                case_temp_c=_optional_float(row.get("case_temp_c")),
                status_text=str(row.get("status_text", "")) or None,
                raw_text=str(row.get("raw_text", "")),
            )
        )
    return rows


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the EC core headlessly and emit a deterministic manifest.")
    parser.add_argument("--config", default="", help="Path to JSON config file.")
    parser.add_argument("--metadata", default="", help="Path to JSON metadata file.")
    parser.add_argument("--input", default="", help="Path to JSON input rows.")
    parser.add_argument("--output", default="", help="Path to manifest JSON output.")
    parser.add_argument("--data-source", default="headless_cli")
    parser.add_argument("--time-range", default="")
    parser.add_argument("--lag-strategy", default="", help="Lag strategy: none, constant, covariance_max, covariance_max_with_default")
    parser.add_argument("--expected-lag-s", default="", help="Expected lag in seconds (for constant lag strategy)")
    parser.add_argument("--detrend-mode", default="", help="Detrend mode: block_mean, linear, running_mean, exponential_running_mean")
    parser.add_argument("--skewness-threshold", default="", help="Skewness threshold for statistical screening (default: 2.0)")
    parser.add_argument("--kurtosis-threshold", default="", help="Kurtosis threshold for statistical screening (default: 7.0)")
    parser.add_argument("--dropout-min-run", default="", help="Minimum run length for dropout detection (default: 10)")
    parser.add_argument("--spike-sigma", default="", help="Spike sigma threshold for screening (default: 5.0)")
    parser.add_argument("--discontinuity-sigma", default="", help="Discontinuity sigma threshold (default: 8.0)")
    parser.add_argument("--absolute-limits-json", default="", help="Absolute limits as JSON string, e.g. '{\"co2_ppm\":[0,1500]}'")
    parser.add_argument("--rotation-mode", default="", help="Rotation mode: none, single, double, triple, planar_fit")
    parser.add_argument("--density-correction-mode", default="", help="Density correction mode: wpl, mixing_ratio, none")
    parser.add_argument("--benchmark-status", default="", help="Benchmark status: active, inactive")
    parser.add_argument("--benchmark-target", default="", help="Benchmark target software (e.g. eddypro_v7)")
    parser.add_argument("--benchmark-reference-id", default="", help="Benchmark reference dataset ID")
    parser.add_argument("--flux-rel-threshold", default="", help="Benchmark flux relative threshold (default: 0.10)")
    parser.add_argument("--lag-abs-threshold-s", default="", help="Benchmark lag absolute threshold in seconds (default: 0.5)")
    parser.add_argument("--wpl-rel-threshold", default="", help="Benchmark WPL relative threshold (default: 0.20)")
    parser.add_argument("--qc-grade-must-match", default="", help="Benchmark QC grade must match exactly (true/false, default: false)")
    parser.add_argument("--clock-sync-enabled", default="", help="Apply GPS/PTP timestamp correction before RP/FCC windowing (true/false).")
    parser.add_argument("--clock-source", default="", help="Clock source label, e.g. GPS, PTP, GPS+PTP, manual.")
    parser.add_argument("--clock-offset-s", default="", help="Correction added to raw timestamps in seconds.")
    parser.add_argument("--clock-drift-ppm", default="", help="Linear clock drift correction in parts per million.")
    parser.add_argument("--clock-events-json", default="", help="Clock event list JSON with timestamp/time and offset_seconds fields.")
    parser.add_argument("--clock-quality-threshold-s", default="", help="Clock correction quality threshold in seconds for offset span/event-step checks.")
    parser.add_argument("--runtime-profile", default="", help="Runtime profile id for the headless watchdog manifest.")
    parser.add_argument("--watchdog-max-gap-s", default="", help="Maximum allowed acquisition timestamp gap in seconds.")
    parser.add_argument("--watchdog-min-window-count", default="", help="Minimum RP/FCC windows required by the watchdog.")
    parser.add_argument("--watchdog-require-clock-sync", default="", help="Require applied clock_sync in watchdog checks (true/false).")
    parser.add_argument("--watchdog-require-clock-quality", default="", help="Require clock_sync quality gate pass in watchdog checks (true/false).")
    parser.add_argument("--watchdog-require-network-pass", default="", help="Require network validation pass in watchdog checks (true/false).")
    parser.add_argument("--build-eddypro-coverage-audit", action="store_true", help="Build a claim-gated EddyPro coverage audit JSON.")
    parser.add_argument("--build-eddypro-release-gate", action="store_true", help="Build a CI/release gate JSON for full EddyPro parity claims.")
    parser.add_argument("--build-public-eddypro-fixture-catalog", action="store_true", help="Build a public EddyPro fixture catalog/acquisition plan JSON.")
    parser.add_argument("--acquire-public-eddypro-fixtures", action="store_true", help="Download/refresh public EddyPro fixture files and validate the catalog.")
    parser.add_argument("--build-public-ec-data-discovery", action="store_true", help="Probe public real EC data candidates without registering EddyPro parity fixtures.")
    parser.add_argument("--inspect-public-official-raw-archive", default="", help="Inspect a downloaded public official raw archive ZIP without promoting parity claims.")
    parser.add_argument("--materialize-public-official-raw-bundle", default="", help="Extract a downloaded public official raw archive into an incomplete official_raw_fixture_bundle draft.")
    parser.add_argument("--public-official-raw-output-root", default="", help="Bundle directory written by --materialize-public-official-raw-bundle.")
    parser.add_argument("--public-official-raw-candidate-id", default="", help="Candidate id or folder to extract from the public official raw archive.")
    parser.add_argument("--overwrite-public-fixtures", action="store_true", help="Overwrite existing public fixture files during acquisition.")
    parser.add_argument("--overwrite-public-official-raw", action="store_true", help="Overwrite extracted raw files and manifest during public official raw bundle materialization.")
    parser.add_argument("--include-public-remote-originals", action="store_true", help="Include remote-original entries that declare local paths during public fixture acquisition.")
    parser.add_argument("--public-fixture-timeout-s", default="", help="Network timeout per public fixture download in seconds.")
    parser.add_argument("--public-ec-data-sources", default="", help="Public EC discovery source ledger JSON path.")
    parser.add_argument("--public-ec-sample-output-root", default="", help="Directory for optional public EC byte samples.")
    parser.add_argument("--public-ec-sample-bytes", default="", help="Optional byte count to sample from verified public EC candidates.")
    parser.add_argument("--public-ec-timeout-s", default="", help="Network timeout for public EC discovery probes.")
    parser.add_argument("--skip-public-ec-network", action="store_true", help="Build public EC discovery from the ledger without network probes.")
    parser.add_argument("--capability-matrix", default="", help="Capability matrix path for EddyPro coverage/release gates.")
    parser.add_argument("--official-raw-evidence-pack", default="", help="Official raw evidence pack JSON used by the EddyPro coverage audit claim gate.")
    parser.add_argument("--official-raw-closure-run", default="", help="Official raw closure-run JSON used by the EddyPro release gate.")
    parser.add_argument("--release-gate-official-raw-bundle", default="", help="Official raw bundle directory used to build evidence for the release gate.")
    parser.add_argument("--skip-release-gate-acceptance", action="store_true", help="Do not rerun evidence-pack acceptance while building the release gate.")
    parser.add_argument("--build-official-raw-bundle-manifest", default="", help="Infer files and write official_raw_fixture_bundle.json for a raw EddyPro bundle directory.")
    parser.add_argument("--build-official-raw-bundle-manifests", default="", help="Infer files and write official_raw_fixture_bundle.json for every candidate raw EddyPro bundle under a directory tree.")
    parser.add_argument("--inspect-official-raw-bundle", default="", help="Inspect an official EddyPro raw fixture bundle and write an inspection JSON.")
    parser.add_argument("--validate-official-raw-bundle", default="", help="Validate an official EddyPro raw fixture bundle against the P0 acquisition closure gate.")
    parser.add_argument("--build-official-raw-evidence-pack", default="", help="Build an official EddyPro raw fixture evidence pack JSON.")
    parser.add_argument("--build-official-eddypro-executable-readiness", default="", help="Inventory local EddyPro executable/source/toolchain readiness for a bundle.")
    parser.add_argument("--prepare-official-eddypro-project", default="", help="Prepare a non-mutating EddyPro run home for official executable capture.")
    parser.add_argument("--run-official-raw-evidence-acceptance", default="", help="Run safe acceptance commands from an official raw evidence pack JSON.")
    parser.add_argument("--run-official-raw-closure", default="", help="Run capture, manifest, registration, parity, evidence, and acceptance for one official raw bundle.")
    parser.add_argument("--capture-official-eddypro-run", default="", help="Run an operator-supplied EddyPro command for a bundle and write official_eddypro_run.json.")
    parser.add_argument("--official-run-command", default="", help="Command used with --capture-official-eddypro-run.")
    parser.add_argument("--official-run-software-version", default="", help="EddyPro software version recorded in the official run sidecar.")
    parser.add_argument("--official-run-executable", default="", help="Path to the EddyPro executable recorded in the official run sidecar.")
    parser.add_argument("--official-run-project-file", default="", help="Project/settings file recorded in the official run sidecar.")
    parser.add_argument("--official-run-output-files", default="", help="Comma-separated or JSON list of official output files relative to the bundle.")
    parser.add_argument("--official-run-working-directory", default="", help="Working directory for the official EddyPro command; relative paths are resolved under the bundle.")
    parser.add_argument("--eddypro-source-dir", default="", help="Official eddypro-engine source checkout used by --build-official-eddypro-executable-readiness.")
    parser.add_argument("--official-run-home", default="", help="Prepared EddyPro run home for --prepare-official-eddypro-project.")
    parser.add_argument("--official-run-prepare-mode", default="embedded", help="Prepared EddyPro run mode: embedded or desktop.")
    parser.add_argument("--official-run-raw-files", default="", help="Comma-separated or JSON list of raw files to copy into the prepared EddyPro run home.")
    parser.add_argument("--official-run-sidecar-name", default="official_eddypro_run.json", help="Sidecar filename written under the official raw bundle.")
    parser.add_argument("--official-run-timeout-s", default="", help="Timeout for --capture-official-eddypro-run in seconds.")
    parser.add_argument("--acceptance-timeout-s", default="", help="Timeout per official raw acceptance command in seconds.")
    parser.add_argument("--closure-fixture-pack-output", default="", help="Fixture pack path written by --run-official-raw-closure.")
    parser.add_argument("--closure-acceptance-command", action="append", default=[], help="Safe pytest command for --run-official-raw-closure acceptance; may be repeated.")
    parser.add_argument("--skip-closure-acceptance", action="store_true", help="Skip evidence-pack acceptance during --run-official-raw-closure.")
    parser.add_argument("--register-official-raw-bundle", default="", help="Register an official EddyPro raw fixture bundle into a fixture pack.")
    parser.add_argument("--inspect-official-raw-bundles", default="", help="Inspect every official EddyPro raw fixture bundle under a directory tree.")
    parser.add_argument("--build-official-raw-repair-plan", default="", help="Build a repair checklist for every official EddyPro raw fixture bundle under a directory tree.")
    parser.add_argument("--register-official-raw-bundles", default="", help="Register every complete official EddyPro raw fixture bundle under a directory tree.")
    parser.add_argument("--fixture-pack", default="", help="Fixture pack path used by --register-official-raw-bundle.")
    parser.add_argument("--workspace-root", default="", help="Workspace root for bundle relative path normalization.")
    parser.add_argument("--bundle-fixture-id", default="", help="Fixture id to write when building an official raw bundle manifest.")
    parser.add_argument("--bundle-site-class", default="", help="Site class to write when building an official raw bundle manifest.")
    parser.add_argument("--bundle-software-version", default="", help="EddyPro/software version to write when building an official raw bundle manifest.")
    parser.add_argument("--overwrite-bundle-manifest", action="store_true", help="Overwrite an existing official raw bundle manifest when building one.")
    parser.add_argument("--overwrite-official-run-home", action="store_true", help="Overwrite the prepared EddyPro run home when rebuilding project capture inputs.")
    parser.add_argument("--replace-fixture", action="store_true", help="Replace an existing fixture with the same fixture_id when registering.")
    args = parser.parse_args(argv)

    if args.build_eddypro_release_gate:
        return _run_eddypro_release_gate_cli(args, parser)

    if args.build_eddypro_coverage_audit:
        return _run_eddypro_coverage_audit_cli(args, parser)

    if args.build_public_eddypro_fixture_catalog:
        return _run_public_eddypro_fixture_catalog_cli(args, parser)

    if args.acquire_public_eddypro_fixtures:
        return _run_public_eddypro_fixture_acquisition_cli(args, parser)

    if args.build_public_ec_data_discovery:
        return _run_public_ec_data_discovery_cli(args, parser)

    if args.inspect_public_official_raw_archive:
        return _run_public_official_raw_archive_inspection_cli(args, parser)

    if args.materialize_public_official_raw_bundle:
        return _run_public_official_raw_bundle_materialize_cli(args, parser)

    if (
        args.inspect_official_raw_bundle
        or args.validate_official_raw_bundle
        or args.build_official_raw_evidence_pack
        or args.build_official_eddypro_executable_readiness
        or args.prepare_official_eddypro_project
        or args.run_official_raw_evidence_acceptance
        or args.run_official_raw_closure
        or args.capture_official_eddypro_run
        or args.build_official_raw_bundle_manifest
        or args.build_official_raw_bundle_manifests
        or args.register_official_raw_bundle
        or args.inspect_official_raw_bundles
        or args.build_official_raw_repair_plan
        or args.register_official_raw_bundles
    ):
        return _run_official_raw_bundle_cli(args, parser)

    for name in ("config", "metadata", "input", "output"):
        if not getattr(args, name):
            parser.error(f"--{name} is required unless using an official raw fixture bundle mode")

    config = load_config_file(args.config)
    metadata = load_metadata_file(args.metadata)
    rows = load_input_rows(args.input, metadata=metadata)
    if args.lag_strategy:
        config.setdefault("lag_phase", {})["strategy"] = args.lag_strategy
    if args.expected_lag_s:
        config.setdefault("lag_phase", {})["expected_lag_s"] = float(args.expected_lag_s)
    if args.detrend_mode:
        config["detrend_mode"] = args.detrend_mode
    if args.rotation_mode:
        config["rotation_mode"] = args.rotation_mode
    if args.density_correction_mode:
        config["density_correction_mode"] = args.density_correction_mode
    if args.skewness_threshold:
        config.setdefault("screening", {})["skewness_threshold"] = float(args.skewness_threshold)
    if args.kurtosis_threshold:
        config.setdefault("screening", {})["kurtosis_threshold"] = float(args.kurtosis_threshold)
    if args.dropout_min_run:
        config.setdefault("screening", {})["dropout_min_run"] = int(args.dropout_min_run)
    if args.spike_sigma:
        config.setdefault("screening", {})["spike_sigma"] = float(args.spike_sigma)
    if args.discontinuity_sigma:
        config.setdefault("screening", {})["discontinuity_sigma"] = float(args.discontinuity_sigma)
    if args.absolute_limits_json:
        config.setdefault("screening", {})["absolute_limits"] = json.loads(args.absolute_limits_json)
    if args.benchmark_status:
        config.setdefault("benchmark", {})["status"] = args.benchmark_status
    if args.benchmark_target:
        config.setdefault("benchmark", {})["target"] = args.benchmark_target
    if args.benchmark_reference_id:
        config.setdefault("benchmark", {})["reference_id"] = args.benchmark_reference_id
    if args.flux_rel_threshold:
        config.setdefault("benchmark", {})["flux_rel_threshold"] = float(args.flux_rel_threshold)
    if args.lag_abs_threshold_s:
        config.setdefault("benchmark", {})["lag_abs_threshold_s"] = float(args.lag_abs_threshold_s)
    if args.wpl_rel_threshold:
        config.setdefault("benchmark", {})["wpl_rel_threshold"] = float(args.wpl_rel_threshold)
    if args.qc_grade_must_match:
        config.setdefault("benchmark", {})["qc_grade_must_match"] = args.qc_grade_must_match.lower() in ("true", "1", "yes")
    if args.clock_sync_enabled:
        config.setdefault("clock_sync", {})["enabled"] = args.clock_sync_enabled.lower() in ("true", "1", "yes")
    if args.clock_source:
        config.setdefault("clock_sync", {})["clock_source"] = args.clock_source
    if args.clock_offset_s:
        config.setdefault("clock_sync", {})["offset_seconds"] = float(args.clock_offset_s)
    if args.clock_drift_ppm:
        config.setdefault("clock_sync", {})["drift_ppm"] = float(args.clock_drift_ppm)
    if args.clock_events_json:
        config.setdefault("clock_sync", {})["events"] = json.loads(args.clock_events_json)
    if args.clock_quality_threshold_s:
        config.setdefault("clock_sync", {})["quality_threshold_seconds"] = float(args.clock_quality_threshold_s)
    if args.runtime_profile:
        config.setdefault("runtime_profile", {})["profile_id"] = args.runtime_profile
    if args.watchdog_max_gap_s:
        config.setdefault("runtime_profile", {})["max_gap_seconds"] = float(args.watchdog_max_gap_s)
    if args.watchdog_min_window_count:
        config.setdefault("runtime_profile", {})["min_window_count"] = int(args.watchdog_min_window_count)
    if args.watchdog_require_clock_sync:
        config.setdefault("runtime_profile", {})["require_clock_sync"] = args.watchdog_require_clock_sync.lower() in ("true", "1", "yes")
    if args.watchdog_require_clock_quality:
        config.setdefault("runtime_profile", {})["require_clock_sync_quality"] = args.watchdog_require_clock_quality.lower() in ("true", "1", "yes")
    if args.watchdog_require_network_pass:
        config.setdefault("runtime_profile", {})["require_network_pass"] = args.watchdog_require_network_pass.lower() in ("true", "1", "yes")
    result = run_headless_batch(
        config=config,
        metadata=metadata,
        rows=rows,
        data_source=args.data_source,
        time_range=args.time_range,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result["manifest"], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _run_eddypro_coverage_audit_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --build-eddypro-coverage-audit.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = build_eddypro_coverage_audit(
        capability_matrix_path=args.capability_matrix or None,
        fixture_pack_path=args.fixture_pack or None,
        workspace_root=workspace_root,
        official_raw_evidence_pack=load_config_file(args.official_raw_evidence_pack) if args.official_raw_evidence_pack else None,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _run_public_eddypro_fixture_catalog_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --build-public-eddypro-fixture-catalog.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = build_public_eddypro_fixture_catalog(workspace_root=workspace_root)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("status") == "pass" else 2


def _run_public_eddypro_fixture_acquisition_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --acquire-public-eddypro-fixtures.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = acquire_public_eddypro_fixture_files(
        workspace_root=workspace_root,
        overwrite=bool(args.overwrite_public_fixtures),
        include_remote_originals=bool(args.include_public_remote_originals),
        timeout_s=float(args.public_fixture_timeout_s or 120.0),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("status") == "pass" else 2


def _run_public_ec_data_discovery_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --build-public-ec-data-discovery.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = build_public_ec_data_discovery_probe(
        manifest_path=args.public_ec_data_sources or None,
        workspace_root=workspace_root,
        sample_output_root=args.public_ec_sample_output_root or None,
        sample_bytes=int(args.public_ec_sample_bytes or 0),
        timeout_s=float(args.public_ec_timeout_s or args.public_fixture_timeout_s or 60.0),
        run_network=not bool(args.skip_public_ec_network),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("status") == "ok" else 2


def _run_public_official_raw_archive_inspection_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --inspect-public-official-raw-archive.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = inspect_public_official_raw_archive(
        args.inspect_public_official_raw_archive,
        workspace_root=workspace_root,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("status") == "pass" else 2


def _run_public_official_raw_bundle_materialize_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --materialize-public-official-raw-bundle.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    payload = materialize_public_official_raw_bundle_draft(
        args.materialize_public_official_raw_bundle,
        workspace_root=workspace_root,
        output_root=args.public_official_raw_output_root or None,
        candidate_id=args.public_official_raw_candidate_id,
        overwrite=bool(args.overwrite_public_official_raw),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload.get("status") == "draft_ready" else 2


def _run_eddypro_release_gate_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.output:
        parser.error("--output is required with --build-eddypro-release-gate.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    output_path = Path(args.output)
    payload = build_eddypro_release_gate(
        capability_matrix_path=args.capability_matrix or None,
        fixture_pack_path=args.fixture_pack or None,
        workspace_root=workspace_root,
        official_raw_bundle_dir=args.release_gate_official_raw_bundle or None,
        official_raw_evidence_pack_path=args.official_raw_evidence_pack or None,
        official_raw_closure_run_path=args.official_raw_closure_run or None,
        output_dir=output_path.parent,
        run_acceptance=not bool(args.skip_release_gate_acceptance),
        acceptance_timeout_s=float(args.acceptance_timeout_s or 300.0),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(payload.get("ci_exit_code", 2) or 2)


def _run_official_raw_bundle_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    selected_modes = [
        bool(args.build_official_raw_bundle_manifest),
        bool(args.build_official_raw_bundle_manifests),
        bool(args.inspect_official_raw_bundle),
        bool(args.validate_official_raw_bundle),
        bool(args.build_official_raw_evidence_pack),
        bool(args.build_official_eddypro_executable_readiness),
        bool(args.prepare_official_eddypro_project),
        bool(args.run_official_raw_evidence_acceptance),
        bool(args.run_official_raw_closure),
        bool(args.capture_official_eddypro_run),
        bool(args.register_official_raw_bundle),
        bool(args.inspect_official_raw_bundles),
        bool(args.build_official_raw_repair_plan),
        bool(args.register_official_raw_bundles),
    ]
    if sum(1 for enabled in selected_modes if enabled) != 1:
        parser.error(
            "Use exactly one official raw fixture mode: --build-official-raw-bundle-manifest, "
            "--build-official-raw-bundle-manifests, "
            "--inspect-official-raw-bundle, --validate-official-raw-bundle, --build-official-raw-evidence-pack, "
            "--build-official-eddypro-executable-readiness, --prepare-official-eddypro-project, "
            "--run-official-raw-evidence-acceptance, --run-official-raw-closure, "
            "--capture-official-eddypro-run, --register-official-raw-bundle, --inspect-official-raw-bundles, "
            "--build-official-raw-repair-plan, or --register-official-raw-bundles."
        )
    if not args.output:
        parser.error("--output is required for official raw fixture bundle modes.")
    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    if args.build_official_raw_bundle_manifest:
        payload = build_official_raw_fixture_bundle_manifest(
            args.build_official_raw_bundle_manifest,
            fixture_id=args.bundle_fixture_id,
            site_class=args.bundle_site_class,
            software_version=args.bundle_software_version,
            overwrite=bool(args.overwrite_bundle_manifest),
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") in {"manifest_ready", "manifest_exists", "manifest_refreshed"} else 2
    if args.build_official_raw_bundle_manifests:
        payload = build_official_raw_fixture_bundle_manifest_batch(
            args.build_official_raw_bundle_manifests,
            site_class=args.bundle_site_class,
            software_version=args.bundle_software_version,
            overwrite=bool(args.overwrite_bundle_manifest),
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") == "ready" else 2
    if args.inspect_official_raw_bundle:
        payload = inspect_official_raw_fixture_bundle(
            args.inspect_official_raw_bundle,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if not payload.get("errors") else 2
    if args.validate_official_raw_bundle:
        payload = validate_official_raw_fixture_acquisition(
            args.validate_official_raw_bundle,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") in {"closure_ready", "ready_for_registration_pending_parity"} else 2
    if args.build_official_raw_evidence_pack:
        payload = build_official_raw_fixture_evidence_pack(
            args.build_official_raw_evidence_pack,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") in {"complete", "pending_closure"} else 2
    if args.build_official_eddypro_executable_readiness:
        payload = build_official_eddypro_executable_readiness(
            args.build_official_eddypro_executable_readiness,
            source_dir=args.eddypro_source_dir or None,
            executable_path=args.official_run_executable or None,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("gate_status") == "ready_to_capture" else 2
    if args.prepare_official_eddypro_project:
        payload = prepare_official_eddypro_project_for_capture(
            args.prepare_official_eddypro_project,
            run_home=args.official_run_home or None,
            mode=args.official_run_prepare_mode or "embedded",
            raw_files=_parse_cli_list(args.official_run_raw_files),
            overwrite=bool(args.overwrite_official_run_home),
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") == "prepared" else 2
    if args.run_official_raw_evidence_acceptance:
        payload = run_official_raw_evidence_pack_acceptance(
            args.run_official_raw_evidence_acceptance,
            workspace_root=workspace_root,
            timeout_s=float(args.acceptance_timeout_s or 300.0),
            write_back=False,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("acceptance_status") == "pass" else 2
    if args.run_official_raw_closure:
        payload = _run_official_raw_closure_cli(args, parser, workspace_root=workspace_root)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("gate_status") == "pass" else 2
    if args.capture_official_eddypro_run:
        if not args.official_run_command:
            parser.error("--official-run-command is required with --capture-official-eddypro-run.")
        payload = capture_official_eddypro_run_evidence(
            args.capture_official_eddypro_run,
            command=args.official_run_command,
            software_version=args.official_run_software_version,
            executable_path=args.official_run_executable,
            project_file=args.official_run_project_file,
            output_files=_parse_cli_list(args.official_run_output_files),
            working_directory=args.official_run_working_directory or None,
            timeout_s=float(args.official_run_timeout_s or 900.0),
            workspace_root=workspace_root,
            sidecar_name=args.official_run_sidecar_name or "official_eddypro_run.json",
            write_sidecar=True,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("gate_status") == "pass" else 2
    if args.inspect_official_raw_bundles:
        payload = discover_official_raw_fixture_bundles(
            args.inspect_official_raw_bundles,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("ready_count", 0) == payload.get("bundle_count", 0) and payload.get("bundle_count", 0) else 2
    if args.build_official_raw_repair_plan:
        payload = build_official_raw_fixture_repair_plan(
            args.build_official_raw_repair_plan,
            workspace_root=workspace_root,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if payload.get("status") == "complete" else 2
    if not args.fixture_pack:
        parser.error("--fixture-pack is required with official raw fixture registration modes.")
    if args.register_official_raw_bundles:
        result = register_official_raw_fixture_bundle_batch(
            bundle_root=args.register_official_raw_bundles,
            pack_path=args.fixture_pack,
            output_path=args.output,
            workspace_root=workspace_root,
            replace=bool(args.replace_fixture),
        )
        return 0 if result.get("status") == "registered" else 2
    result = register_official_raw_fixture_bundle(
        bundle_dir=args.register_official_raw_bundle,
        pack_path=args.fixture_pack,
        output_path=args.output,
        workspace_root=workspace_root,
        replace=bool(args.replace_fixture),
    )
    return 0 if result.get("status") == "registered" else 2


def _run_official_raw_closure_cli(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    workspace_root: Path | None,
) -> dict[str, Any]:
    if not args.fixture_pack:
        parser.error("--fixture-pack is required with --run-official-raw-closure.")
    if not args.run_official_raw_closure:
        parser.error("--run-official-raw-closure requires a bundle directory.")
    if args.official_run_command and not args.official_run_output_files:
        parser.error("--official-run-output-files is required when --official-run-command is used with --run-official-raw-closure.")

    output_path = Path(args.output)
    bundle_dir = args.run_official_raw_closure
    registered_pack_path = (
        Path(args.closure_fixture_pack_output)
        if args.closure_fixture_pack_output
        else output_path.with_name("fixture_pack_v1_registered.json")
    )
    steps: list[dict[str, Any]] = []

    capture_payload: dict[str, Any] = {}
    if args.official_run_command:
        capture_payload = capture_official_eddypro_run_evidence(
            bundle_dir,
            command=args.official_run_command,
            software_version=args.official_run_software_version,
            executable_path=args.official_run_executable,
            project_file=args.official_run_project_file,
            output_files=_parse_cli_list(args.official_run_output_files),
            working_directory=args.official_run_working_directory or None,
            timeout_s=float(args.official_run_timeout_s or 900.0),
            workspace_root=workspace_root,
            sidecar_name=args.official_run_sidecar_name or "official_eddypro_run.json",
            write_sidecar=True,
        )
        steps.append(
            {
                "step": "capture_official_eddypro_run",
                "status": capture_payload.get("status", ""),
                "gate_status": capture_payload.get("gate_status", ""),
                "artifact": capture_payload.get("sidecar_path", ""),
            }
        )

    manifest_payload = build_official_raw_fixture_bundle_manifest(
        bundle_dir,
        fixture_id=args.bundle_fixture_id,
        site_class=args.bundle_site_class,
        software_version=args.bundle_software_version or args.official_run_software_version,
        overwrite=bool(args.overwrite_bundle_manifest),
        workspace_root=workspace_root,
    )
    steps.append(
        {
            "step": "build_bundle_manifest",
            "status": manifest_payload.get("status", ""),
            "artifact": manifest_payload.get("manifest_path", ""),
        }
    )

    registration_payload = register_official_raw_fixture_bundle(
        bundle_dir=bundle_dir,
        pack_path=args.fixture_pack,
        output_path=registered_pack_path,
        workspace_root=workspace_root,
        replace=bool(args.replace_fixture),
    )
    steps.append(
        {
            "step": "register_fixture",
            "status": registration_payload.get("status", ""),
            "artifact": str(registered_pack_path),
        }
    )

    fixture_id = str(
        registration_payload.get("fixture_id")
        or manifest_payload.get("fixture_id")
        or Path(str(bundle_dir)).name
    )
    fixture_summary = build_fixture_pack_summary(registered_pack_path, workspace_root=workspace_root)
    fixture_manifest = build_official_raw_fixture_manifest(
        registered_pack_path,
        workspace_root=workspace_root,
        fixture_summary=fixture_summary,
    )
    fixture_detail = build_official_raw_fixture_detail(
        registered_pack_path,
        fixture_id=fixture_id,
        workspace_root=workspace_root,
        fixture_summary=fixture_summary,
        fixture_manifest=fixture_manifest,
    )
    parity_payload = _closure_parity_payload_from_detail(fixture_detail)
    steps.append(
        {
            "step": "raw_to_final_parity",
            "status": parity_payload.get("status", ""),
            "pass_rate": parity_payload.get("pass_rate", 0.0),
            "failed_fields": parity_payload.get("failed_fields", []),
            "artifact": parity_payload.get("artifact", ""),
        }
    )

    acquisition_payload = validate_official_raw_fixture_acquisition(
        bundle_dir,
        workspace_root=workspace_root,
        parity_payload=parity_payload,
    )
    evidence_pack = build_official_raw_fixture_evidence_pack(
        bundle_dir,
        workspace_root=workspace_root,
        parity_payload=parity_payload,
        acquisition_validation=acquisition_payload,
        fixture_detail=fixture_detail,
        closure_gate={
            "registered_pack_path": str(registered_pack_path),
            "fixture_manifest_status": fixture_manifest.get("status", ""),
            "fixture_detail_status": fixture_detail.get("status", ""),
            "parity_status": parity_payload.get("status", ""),
            "parity_pass_rate": parity_payload.get("pass_rate", 0.0),
        },
    )
    evidence_path = output_path.with_name(f"{fixture_id}_official_raw_evidence_pack.json")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_pack["artifact"] = str(evidence_path)
    evidence_path.write_text(json.dumps(evidence_pack, ensure_ascii=False, indent=2), encoding="utf-8")
    steps.append(
        {
            "step": "build_evidence_pack",
            "status": evidence_pack.get("status", ""),
            "gate_status": acquisition_payload.get("gate_status", ""),
            "artifact": str(evidence_path),
        }
    )

    acceptance_payload = evidence_pack
    if not bool(args.skip_closure_acceptance):
        acceptance_payload = run_official_raw_evidence_pack_acceptance(
            evidence_path,
            workspace_root=workspace_root,
            commands=list(args.closure_acceptance_command or []) or None,
            timeout_s=float(args.acceptance_timeout_s or 300.0),
            write_back=True,
        )
        steps.append(
            {
                "step": "run_acceptance",
                "status": acceptance_payload.get("acceptance_status", ""),
                "gate_status": acceptance_payload.get("acceptance_gate_status", ""),
                "artifact": str(evidence_path),
            }
        )

    blockers = _official_raw_closure_blockers(
        capture_payload=capture_payload,
        registration_payload=registration_payload,
        parity_payload=parity_payload,
        acquisition_payload=acquisition_payload,
        acceptance_payload=acceptance_payload,
        acceptance_skipped=bool(args.skip_closure_acceptance),
    )
    gate_status = "pass" if not blockers else "blocked"
    return {
        "artifact_type": "official_raw_closure_run_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if gate_status == "pass" else "blocked",
        "gate_status": gate_status,
        "fixture_id": fixture_id,
        "bundle_root": str(bundle_dir),
        "registered_pack_path": str(registered_pack_path),
        "evidence_pack_artifact": str(evidence_path),
        "manifest_status": str(manifest_payload.get("status", "")),
        "registration_status": str(registration_payload.get("status", "")),
        "raw_to_final_parity_status": str(parity_payload.get("status", "")),
        "pass_rate": float(parity_payload.get("pass_rate", 0.0) or 0.0),
        "failed_fields": list(parity_payload.get("failed_fields", []) or []),
        "official_eddypro_run_status": str(
            dict(acceptance_payload.get("official_eddypro_run", {}) or {}).get("status", "")
        ),
        "official_eddypro_run_gate_status": str(
            dict(acceptance_payload.get("official_eddypro_run", {}) or {}).get("gate_status", "")
        ),
        "acquisition_status": str(acquisition_payload.get("status", "")),
        "acquisition_gate_status": str(acquisition_payload.get("gate_status", "")),
        "acceptance_status": str(acceptance_payload.get("acceptance_status", "skipped" if args.skip_closure_acceptance else "")),
        "acceptance_gate_status": str(
            acceptance_payload.get("acceptance_gate_status", "skipped" if args.skip_closure_acceptance else "")
        ),
        "blockers": blockers,
        "steps": steps,
        "capture": capture_payload,
        "manifest": manifest_payload,
        "registration": registration_payload,
        "fixture_summary": fixture_summary,
        "fixture_manifest": fixture_manifest,
        "fixture_detail": fixture_detail,
        "parity": parity_payload,
        "acquisition_validation": acquisition_payload,
        "evidence_pack": acceptance_payload,
        "truthfulness_note": (
            "This closure run is a headless, auditable equivalent of the Report Center closure action. "
            "It only passes when official run provenance, registration, raw-to-final parity, and acceptance all pass."
        ),
    }


def _closure_parity_payload_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    parity = dict(detail.get("parity", {}) or {})
    benchmark_summary = dict(detail.get("benchmark_summary", {}) or {})
    status = str(parity.get("status", detail.get("status", "")) or "")
    failed_fields = list(benchmark_summary.get("failed_fields", detail.get("failed_fields", [])) or [])
    pass_rate = float(benchmark_summary.get("pass_rate", detail.get("pass_rate", 0.0)) or 0.0)
    artifact = (
        str(parity.get("artifact", "") or "")
        or str(dict(detail.get("matrix_row", {}) or {}).get("artifact", "") or "")
        or str(detail.get("fixture_pack_path", "") or "")
    )
    payload = {
        "artifact_type": parity.get("artifact_type", "raw_to_final_parity_detail_v1"),
        "artifact": artifact,
        "status": status,
        "fixture_id": str(detail.get("fixture_id", parity.get("fixture_id", ""))),
        "pass_rate": pass_rate,
        "failed_fields": failed_fields,
        "benchmark_summary": benchmark_summary,
        "trace_gas_parity": dict(detail.get("trace_gas_parity", parity.get("trace_gas_parity", {})) or {}),
        "trace_gas_parity_status": str(detail.get("trace_gas_parity_status", "")),
        "trace_gas_failed_fields": list(detail.get("trace_gas_failed_fields", []) or []),
        "parity_diagnostics": dict(detail.get("parity_diagnostics", parity.get("parity_diagnostics", {})) or {}),
        "known_limitations": list(detail.get("known_limitations", parity.get("known_limitations", [])) or []),
        "truthfulness_note": str(parity.get("truthfulness_note", detail.get("truthfulness_note", ""))),
    }
    if not payload["benchmark_summary"]:
        payload["benchmark_summary"] = {"pass_rate": pass_rate, "failed_fields": failed_fields}
    return payload


def _official_raw_closure_blockers(
    *,
    capture_payload: dict[str, Any],
    registration_payload: dict[str, Any],
    parity_payload: dict[str, Any],
    acquisition_payload: dict[str, Any],
    acceptance_payload: dict[str, Any],
    acceptance_skipped: bool,
) -> list[str]:
    blockers: list[str] = []
    if capture_payload and capture_payload.get("gate_status") != "pass":
        blockers.append("official_eddypro_run_capture_gate")
    if registration_payload.get("status") != "registered":
        blockers.append("fixture_registration")
    if parity_payload.get("status") != "pass":
        blockers.append("raw_to_final_parity")
    if acquisition_payload.get("gate_status") != "pass":
        blockers.append("acquisition_validation")
    if acceptance_skipped:
        blockers.append("evidence_acceptance_skipped")
    elif acceptance_payload.get("acceptance_gate_status") != "pass":
        blockers.append("evidence_acceptance")
    return blockers


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _parse_cli_list(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("expected a JSON list")
        return [str(item) for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(run_cli())
