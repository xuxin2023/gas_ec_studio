from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from core.ec_fcc.pipeline import ECFCCPipeline
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from core.storage.ghg_bundle import load_ghg_normalized_frames
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
    metadata_bundle = metadata if isinstance(metadata, MetadataBundle) else MetadataBundle.from_dict(dict(metadata))
    payload = {
        "config": config,
        "metadata": metadata_bundle.to_dict(),
        "rows": [row.to_record() for row in rows],
    }
    batch_digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    rp_pipeline = ECRPPipeline()
    spectral_pipeline = ECFCCPipeline()
    base_config = deepcopy(config)
    base_config.setdefault("metadata_bundle", metadata_bundle.to_dict())
    rp_result = rp_pipeline.run(
        rows=rows,
        project=metadata_bundle.project,
        site=metadata_bundle.site,
        config=base_config,
        data_source=data_source,
        time_range=time_range,
    )
    spectral_result = spectral_pipeline.run(
        rows=rows,
        project=metadata_bundle.project,
        site=metadata_bundle.site,
        config=base_config,
        data_source=data_source,
        time_range=time_range,
    )
    deterministic_created_at = rows[0].timestamp if rows else datetime(2000, 1, 1)
    rp_result.run_id = f"rp_det_{batch_digest}"
    rp_result.created_at = deterministic_created_at
    spectral_result.run_id = f"spectral_det_{batch_digest}"
    spectral_result.created_at = deterministic_created_at
    manifest = build_batch_manifest(
        batch_id=batch_digest,
        metadata_bundle=metadata_bundle,
        config=config,
        rows=rows,
        rp_result=rp_result,
        spectral_result=spectral_result,
    )
    return {
        "batch_id": batch_digest,
        "metadata_snapshot": metadata_bundle.to_dict(),
        "raw_import_summary": _raw_import_summary(rows),
        "project_snapshot": asdict(metadata_bundle.project),
        "site_snapshot": asdict(metadata_bundle.site),
        "rp_result": rp_result,
        "spectral_result": spectral_result,
        "manifest": manifest,
    }


def build_batch_manifest(
    *,
    batch_id: str,
    metadata_bundle: MetadataBundle,
    config: dict[str, Any],
    rows: list[NormalizedHFFrame],
    rp_result,
    spectral_result,
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
        "raw_import_summary": _raw_import_summary(rows),
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
    for row in rows[:100]:
        try:
            payload = json.loads(row.raw_text or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("raw_native_import"), dict):
            native_items.append(dict(payload["raw_native_import"]))
    if not native_items:
        return {"status": "not_native", "native": False}
    first = native_items[0]
    return {
        "status": first.get("status", "decoded"),
        "native": True,
        "format": first.get("format", ""),
        "record_count": first.get("record_count", len(rows)),
        "columns": first.get("columns", []),
        "source_file": first.get("source_file", ""),
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
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    parser.add_argument("--metadata", required=True, help="Path to JSON metadata file.")
    parser.add_argument("--input", required=True, help="Path to JSON input rows.")
    parser.add_argument("--output", required=True, help="Path to manifest JSON output.")
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
    args = parser.parse_args(argv)

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


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(run_cli())
