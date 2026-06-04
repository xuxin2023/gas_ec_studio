from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from core.ec_rp.analysis import load_eddypro_reference_with_qc_mapping, run_benchmark_comparison
from core.ec_rp.pipeline import ECRPPipeline
from core.storage.ghg_bundle import load_ghg_normalized_frames
from core.storage.raw_importer import can_load_raw_native, can_load_raw_text, load_raw_native_frames, load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


FIELD_DIAGNOSTIC_MAP: dict[str, dict[str, Any]] = {
    "primary_flux": {
        "category": "flux_calculation",
        "eddypro_engine_modules": ["src/src_rp/m_rp_main.f90", "src/src_rp/m_fluxes.f90"],
        "likely_gap": "Covariance, detrending, units, or density conversion differs from the reference pipeline.",
    },
    "primary_flux_source": {
        "category": "flux_calculation",
        "eddypro_engine_modules": ["src/src_rp/m_fluxes.f90", "src/src_rp/m_wpl.f90"],
        "likely_gap": "Flux source or correction-mode selection differs from the reference.",
    },
    "lag_seconds": {
        "category": "lag",
        "eddypro_engine_modules": ["src/src_rp/m_time_lag.f90", "src/src_rp/m_rp_main.f90"],
        "likely_gap": "Lag search/default fallback window differs from EddyPro settings.",
    },
    "lag_strategy": {
        "category": "lag",
        "eddypro_engine_modules": ["src/src_rp/m_time_lag.f90"],
        "likely_gap": "Lag strategy metadata or project-setting import differs.",
    },
    "wpl_water_vapor_term": {
        "category": "density_wpl",
        "eddypro_engine_modules": ["src/src_rp/m_wpl.f90"],
        "likely_gap": "Water-vapor density correction term or ambient inputs differ.",
    },
    "wpl_sensible_heat_term": {
        "category": "density_wpl",
        "eddypro_engine_modules": ["src/src_rp/m_wpl.f90", "src/src_rp/m_biomet.f90"],
        "likely_gap": "Sensible-heat density correction term or temperature source differs.",
    },
    "total_density_correction": {
        "category": "density_wpl",
        "eddypro_engine_modules": ["src/src_rp/m_wpl.f90"],
        "likely_gap": "Combined density-correction terms differ from reference output.",
    },
    "rotation_mode": {
        "category": "rotation",
        "eddypro_engine_modules": ["src/src_rp/m_rotations.f90", "src/src_rp/m_planar_fit.f90"],
        "likely_gap": "Coordinate-rotation mode or planar-fit coefficients differ.",
    },
    "qc_grade": {
        "category": "quality_control",
        "eddypro_engine_modules": ["src/src_rp/m_qc.f90", "src/src_rp/m_stationarity.f90"],
        "likely_gap": "QC flag mapping, stationarity, or turbulence classification differs.",
    },
    "ch4_flux_level0_nmol_m2_s": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_li7700.f90", "src/src_rp/m_trace_gas.f90"],
        "likely_gap": "Raw CH4 covariance or LI-7700 level-0 conversion differs.",
    },
    "ch4_flux_level1_spectral_nmol_m2_s": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_spectral_corrections.f90", "src/src_rp/m_li7700.f90"],
        "likely_gap": "CH4 spectral correction factor differs.",
    },
    "ch4_flux_level2_density_nmol_m2_s": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_wpl.f90", "src/src_rp/m_li7700.f90"],
        "likely_gap": "CH4 density/water-vapor correction differs.",
    },
    "ch4_flux_corrected_nmol_m2_s": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_li7700.f90"],
        "likely_gap": "LI-7700 spectroscopic/self-heating correction sequence differs.",
    },
    "ch4_flux_nmol_m2_s": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_li7700.f90", "src/src_rp/m_trace_gas.f90"],
        "likely_gap": "Final CH4 correction sequence differs.",
    },
    "ch4_method": {
        "category": "trace_gas_li7700",
        "eddypro_engine_modules": ["src/src_rp/m_li7700.f90"],
        "likely_gap": "Trace-gas method metadata differs.",
    },
}

CATEGORY_GUIDANCE: dict[str, str] = {
    "flux_calculation": "Check covariance units, detrending, density mode, and primary flux source.",
    "lag": "Check lag search window, default lag, sample frequency, and imported EddyPro project lag settings.",
    "density_wpl": "Check WPL/density correction mode plus pressure, temperature, and water-vapor ambient inputs.",
    "rotation": "Check rotation mode, planar-fit coefficients, sector selection, and sonic coordinate metadata.",
    "quality_control": "Check QC flag mapping, stationarity/turbulence thresholds, and skipped/missing values.",
    "trace_gas_li7700": "Check LI-7700 coefficient profile, spectral factor, WPL density term, spectroscopic and self-heating corrections.",
    "window_matching": "Check start times, averaging period, time zone, clock sync, and reference window IDs.",
    "raw_import": "Check raw decoder, column mapping, units, timestamp start, and native format metadata.",
    "unknown": "Inspect comparison notes and reference provenance.",
}


def run_raw_to_final_parity_harness(
    *,
    raw_path: str | Path,
    metadata: MetadataBundle | dict[str, Any] | None = None,
    rp_config: dict[str, Any] | None = None,
    reference_json_path: str | Path | None = None,
    reference_windows: list[dict[str, Any]] | None = None,
    fixture_id: str = "",
    thresholds: dict[str, Any] | None = None,
    data_source: str = "raw_to_final_parity",
    time_range: str = "",
) -> dict[str, Any]:
    """Run a raw fixture through RP and compare final windows to a reference.

    This harness is the integration bridge between raw import fixtures and
    EddyPro-style golden outputs. It intentionally reports truthfulness limits:
    a passing synthetic/raw fixture is a regression guardrail, not full EddyPro
    numeric parity without official EddyPro output for the same raw file.
    """
    source_path = Path(raw_path)
    metadata_bundle = _metadata_bundle(metadata)
    config = deepcopy(rp_config or {})
    harness_config = dict(config.pop("raw_to_final_parity", {}) or {})
    active_thresholds = {
        "flux_rel_threshold": 0.10,
        "lag_abs_threshold_s": 0.5,
        "wpl_rel_threshold": 0.20,
        "qc_grade_must_match": False,
        "time_match_tolerance_s": 60.0,
        "trace_gas_rel_threshold": 0.10,
    }
    active_thresholds.update({k: v for k, v in dict(harness_config.get("thresholds", {}) or {}).items() if v not in (None, "")})
    active_thresholds.update({k: v for k, v in dict(thresholds or {}).items() if v not in (None, "")})

    reference_json = reference_json_path or harness_config.get("reference_json_path") or harness_config.get("reference_json")
    references = list(reference_windows or harness_config.get("reference_windows") or [])
    if not references and reference_json:
        references = _load_reference_windows_with_extras(reference_json)

    rows = _load_raw_rows(source_path, metadata_bundle)
    raw_import_summary = _raw_import_summary(rows)
    project = metadata_bundle.project if metadata_bundle.project else ProjectProfile()
    site = metadata_bundle.site if metadata_bundle.site else SiteProfile()
    rp_result = ECRPPipeline().run(
        rows=rows,
        project=project,
        site=site,
        config=config,
        data_source=data_source,
        time_range=time_range or f"raw-to-final parity fixture {fixture_id or source_path.stem}",
    )
    benchmark_results = run_benchmark_comparison(
        rp_result,
        references,
        flux_rel_threshold=float(active_thresholds["flux_rel_threshold"]),
        lag_abs_threshold_s=float(active_thresholds["lag_abs_threshold_s"]),
        wpl_rel_threshold=float(active_thresholds["wpl_rel_threshold"]),
        qc_grade_must_match=bool(active_thresholds["qc_grade_must_match"]),
        time_match_tolerance_s=float(active_thresholds["time_match_tolerance_s"]),
    )
    benchmark_summary = _benchmark_summary(
        benchmark_results=benchmark_results,
        current_window_count=len(rp_result.windows),
        reference_window_count=len(references),
    )
    trace_gas_parity = _trace_gas_parity_summary(
        rp_result=rp_result,
        reference_windows=references,
        rel_threshold=float(active_thresholds["trace_gas_rel_threshold"]),
        time_match_tolerance_s=float(active_thresholds["time_match_tolerance_s"]),
    )
    if trace_gas_parity.get("status") != "not_available":
        benchmark_summary["trace_gas_parity_status"] = trace_gas_parity.get("status", "")
        benchmark_summary["trace_gas_pass_rate"] = trace_gas_parity.get("pass_rate", 0.0)
        benchmark_summary["trace_gas_failed_fields"] = list(trace_gas_parity.get("failed_fields", []) or [])
        if trace_gas_parity.get("status") == "fail":
            failed = set(benchmark_summary.get("failed_fields", []) or [])
            failed.update(str(item) for item in trace_gas_parity.get("failed_fields", []) or [] if str(item))
            benchmark_summary["failed_fields"] = sorted(failed)
    status = "pass" if benchmark_summary["status"] == "pass" and rows else "fail"
    if not references:
        status = "fail"
    if trace_gas_parity.get("status") == "fail":
        status = "fail"
    parity_diagnostics = _parity_diagnostics(
        benchmark_results=benchmark_results,
        benchmark_summary=benchmark_summary,
        trace_gas_parity=trace_gas_parity,
        raw_import_summary=raw_import_summary,
        row_count=len(rows),
        reference_window_count=len(references),
        current_window_count=len(rp_result.windows),
    )
    return {
        "artifact_type": "eddypro_raw_to_final_parity_v1",
        "fixture_id": fixture_id or source_path.stem,
        "status": status,
        "raw_input": {
            "path": str(source_path),
            "sha256": _sha256(source_path) if source_path.exists() else "",
            "exists": source_path.exists(),
            "format": _raw_format(source_path, metadata_bundle),
            "import_summary": raw_import_summary,
            "row_count": len(rows),
            "time_start": rows[0].timestamp.isoformat() if rows else "",
            "time_end": rows[-1].timestamp.isoformat() if rows else "",
        },
        "reference": {
            "reference_json_path": str(reference_json or ""),
            "reference_window_count": len(references),
            "reference_ids": sorted({str(item.get("window_id", "")) for item in references if item.get("window_id")}),
        },
        "pipeline": {
            "run_id": rp_result.run_id,
            "window_count": len(rp_result.windows),
            "data_source": rp_result.data_source,
            "time_range": rp_result.time_range,
            "summary": _jsonable(rp_result.summary),
        },
        "thresholds": _jsonable(active_thresholds),
        "benchmark_summary": benchmark_summary,
        "parity_diagnostics": parity_diagnostics,
        "trace_gas_parity": trace_gas_parity,
        "li7700_level_parity": trace_gas_parity,
        "windows": _jsonable(benchmark_results),
        "actual_windows": [_window_summary(window) for window in rp_result.windows],
        "truthfulness_note": (
            "Raw-to-final parity validates this raw fixture against the supplied reference windows. "
            "It is not a claim of complete EddyPro parity unless the reference windows are official EddyPro outputs for the same raw source."
        ),
        "known_limitations": [
            "Reference quality depends on the supplied reference_windows/reference_json_path.",
            "Synthetic fixtures are regression guardrails, not field parity evidence.",
            "LI-7700 Level 0/1/2/3 parity is only official when the reference values come from the matching EddyPro output.",
            "Official raw .ghg, TOB1/SLT/binary, LI-7700, sonic AoA, and spectra/cospectra fixtures are still needed for broad parity claims.",
        ],
    }


def write_raw_to_final_parity_artifact(payload: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_raw_rows(path: Path, metadata: MetadataBundle) -> list[NormalizedHFFrame]:
    if path.suffix.lower() == ".ghg":
        return load_ghg_normalized_frames(path)
    if can_load_raw_native(path, metadata):
        return load_raw_native_frames(path, metadata=metadata)
    if can_load_raw_text(path):
        return load_raw_text_frames(path, metadata=metadata)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Raw-to-final parity input must be a supported raw file or a JSON list of normalized rows.")
    return [
        NormalizedHFFrame(
            timestamp=datetime.fromisoformat(str(item["timestamp"])),
            device_uid=str(item.get("device_uid", "raw-to-final")),
            device_id=str(item.get("device_id", "raw")),
            mode=int(item.get("mode", 2)),
            frame_quality=FrameQuality(str(item.get("frame_quality", FrameQuality.FULL.value))),
            co2_ppm=_optional_float(item.get("co2_ppm")),
            h2o_mmol=_optional_float(item.get("h2o_mmol")),
            ch4_ppb=_optional_float(item.get("ch4_ppb")),
            n2o_ppb=_optional_float(item.get("n2o_ppb")),
            pressure_kpa=_optional_float(item.get("pressure_kpa")),
            chamber_temp_c=_optional_float(item.get("chamber_temp_c")),
            case_temp_c=_optional_float(item.get("case_temp_c")),
            status_text=str(item.get("status_text", "")) or None,
            raw_text=str(item.get("raw_text", "")),
        )
        for item in payload
    ]


def _benchmark_summary(
    *,
    benchmark_results: list[dict[str, Any]],
    current_window_count: int,
    reference_window_count: int,
) -> dict[str, Any]:
    field_total = 0
    field_passed = 0
    failed_fields: set[str] = set()
    unmatched_windows: list[str] = []
    matched_window_count = 0
    for window in benchmark_results:
        comparisons = list(window.get("comparisons", []) or [])
        if comparisons:
            matched_window_count += 1
        else:
            unmatched_windows.append(str(window.get("window_id", "")))
        for comparison in comparisons:
            field_total += 1
            if comparison.get("passed", False):
                field_passed += 1
            else:
                failed_fields.add(str(comparison.get("field_name", "")))
    pass_rate = (field_passed / field_total) if field_total else 0.0
    status = "pass"
    if failed_fields or unmatched_windows or matched_window_count != current_window_count:
        status = "fail"
    if reference_window_count <= 0 or current_window_count <= 0:
        status = "fail"
    return {
        "status": status,
        "current_window_count": current_window_count,
        "reference_window_count": reference_window_count,
        "matched_window_count": matched_window_count,
        "unmatched_windows": unmatched_windows,
        "field_comparison_count": field_total,
        "field_passed_count": field_passed,
        "pass_rate": pass_rate,
        "failed_fields": sorted(item for item in failed_fields if item),
    }


def _parity_diagnostics(
    *,
    benchmark_results: list[dict[str, Any]],
    benchmark_summary: dict[str, Any],
    trace_gas_parity: dict[str, Any],
    raw_import_summary: dict[str, Any],
    row_count: int,
    reference_window_count: int,
    current_window_count: int,
) -> dict[str, Any]:
    field_heatmap = _field_heatmap(benchmark_results, trace_gas_parity)
    failure_groups = _failure_groups(
        field_heatmap=field_heatmap,
        benchmark_results=benchmark_results,
        benchmark_summary=benchmark_summary,
        raw_import_summary=raw_import_summary,
        row_count=row_count,
        reference_window_count=reference_window_count,
        current_window_count=current_window_count,
    )
    module_counts: Counter[str] = Counter()
    for row in field_heatmap:
        if int(row.get("failed_count", 0) or 0) <= 0:
            continue
        for module in list(row.get("eddypro_engine_modules", []) or []):
            module_counts[str(module)] += int(row.get("failed_count", 0) or 0)
    return {
        "artifact_type": "raw_to_final_parity_diagnostics_v1",
        "status": "ok" if not failure_groups else "needs_attention",
        "field_heatmap": field_heatmap,
        "failure_groups": failure_groups,
        "failed_group_count": len(failure_groups),
        "failed_field_count": sum(1 for row in field_heatmap if int(row.get("failed_count", 0) or 0) > 0),
        "top_failed_fields": [
            str(row.get("field_name", ""))
            for row in sorted(field_heatmap, key=lambda item: (-int(item.get("failed_count", 0) or 0), str(item.get("field_name", ""))))
            if int(row.get("failed_count", 0) or 0) > 0
        ][:8],
        "eddypro_module_failure_counts": dict(sorted(module_counts.items())),
        "guidance": {
            str(group.get("category", "")): CATEGORY_GUIDANCE.get(str(group.get("category", "")), CATEGORY_GUIDANCE["unknown"])
            for group in failure_groups
        },
        "truthfulness_note": (
            "Diagnostics localize likely parity causes from comparison evidence. They are triage hints, "
            "not proof that a specific EddyPro source routine is solely responsible."
        ),
    }


def _field_heatmap(benchmark_results: list[dict[str, Any]], trace_gas_parity: dict[str, Any]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for window in benchmark_results:
        for comparison in list(dict(window or {}).get("comparisons", []) or []):
            _record_field_comparison(rows, comparison, window_id=str(dict(window or {}).get("window_id", "")))
    for window in list(trace_gas_parity.get("windows", []) or []):
        for comparison in list(dict(window or {}).get("comparisons", []) or []):
            _record_field_comparison(rows, comparison, window_id=str(dict(window or {}).get("window_id", "")))
    heatmap: list[dict[str, Any]] = []
    for field_name, row in sorted(rows.items()):
        total = int(row.get("comparison_count", 0) or 0)
        passed = int(row.get("passed_count", 0) or 0)
        failed = int(row.get("failed_count", 0) or 0)
        meta = FIELD_DIAGNOSTIC_MAP.get(field_name, {})
        heatmap.append(
            {
                "field_name": field_name,
                "category": str(meta.get("category", "unknown")),
                "comparison_count": total,
                "passed_count": passed,
                "failed_count": failed,
                "pass_rate": passed / total if total else 0.0,
                "max_absolute_error": row.get("max_absolute_error"),
                "max_relative_error": row.get("max_relative_error"),
                "max_threshold_ratio": row.get("max_threshold_ratio"),
                "thresholds": sorted(row.get("thresholds", [])),
                "example_notes": list(row.get("example_notes", []) or [])[:3],
                "example_windows": list(row.get("example_windows", []) or [])[:3],
                "severity": _field_severity(failed=failed, total=total, max_threshold_ratio=row.get("max_threshold_ratio")),
                "eddypro_engine_modules": list(meta.get("eddypro_engine_modules", []) or []),
                "likely_gap": str(meta.get("likely_gap", CATEGORY_GUIDANCE["unknown"])),
            }
        )
    return heatmap


def _record_field_comparison(rows: dict[str, dict[str, Any]], comparison: dict[str, Any], *, window_id: str) -> None:
    field_name = str(dict(comparison or {}).get("field_name", "") or "")
    if not field_name:
        return
    row = rows.setdefault(
        field_name,
        {
            "comparison_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "max_absolute_error": None,
            "max_relative_error": None,
            "max_threshold_ratio": None,
            "thresholds": set(),
            "example_notes": [],
            "example_windows": [],
        },
    )
    row["comparison_count"] += 1
    passed = bool(dict(comparison or {}).get("passed", False))
    row["passed_count" if passed else "failed_count"] += 1
    threshold = _safe_float(dict(comparison or {}).get("threshold"))
    if threshold is not None:
        row["thresholds"].add(threshold)
    abs_err = _safe_float(dict(comparison or {}).get("absolute_error"))
    rel_err = _safe_float(dict(comparison or {}).get("relative_error"))
    if abs_err is not None:
        row["max_absolute_error"] = max(abs_err, float(row["max_absolute_error"] or 0.0))
    if rel_err is not None:
        row["max_relative_error"] = max(rel_err, float(row["max_relative_error"] or 0.0))
    ratio = None
    if threshold is not None and threshold > 0:
        ratio_value = rel_err if rel_err is not None else abs_err
        if ratio_value is not None:
            ratio = ratio_value / threshold
            row["max_threshold_ratio"] = max(ratio, float(row["max_threshold_ratio"] or 0.0))
    if not passed:
        note = str(dict(comparison or {}).get("note", "") or "")
        if note and note not in row["example_notes"]:
            row["example_notes"].append(note)
        if window_id and window_id not in row["example_windows"]:
            row["example_windows"].append(window_id)


def _field_severity(*, failed: int, total: int, max_threshold_ratio: Any) -> str:
    if failed <= 0:
        return "pass"
    failure_rate = failed / total if total else 1.0
    ratio = _safe_float(max_threshold_ratio) or 0.0
    if failure_rate >= 0.5 or ratio >= 5.0:
        return "high"
    if failure_rate >= 0.2 or ratio >= 2.0:
        return "medium"
    return "low"


def _failure_groups(
    *,
    field_heatmap: list[dict[str, Any]],
    benchmark_results: list[dict[str, Any]],
    benchmark_summary: dict[str, Any],
    raw_import_summary: dict[str, Any],
    row_count: int,
    reference_window_count: int,
    current_window_count: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in field_heatmap:
        failed = int(row.get("failed_count", 0) or 0)
        if failed <= 0:
            continue
        category = str(row.get("category", "unknown") or "unknown")
        group = grouped.setdefault(
            category,
            {
                "category": category,
                "failed_count": 0,
                "fields": [],
                "severity": "low",
                "eddypro_engine_modules": set(),
                "suggested_action": CATEGORY_GUIDANCE.get(category, CATEGORY_GUIDANCE["unknown"]),
            },
        )
        group["failed_count"] += failed
        group["fields"].append(str(row.get("field_name", "")))
        group["severity"] = _max_severity(str(group.get("severity", "low")), str(row.get("severity", "low")))
        for module in list(row.get("eddypro_engine_modules", []) or []):
            group["eddypro_engine_modules"].add(str(module))

    unmatched = list(benchmark_summary.get("unmatched_windows", []) or [])
    if unmatched or int(benchmark_summary.get("matched_window_count", 0) or 0) != current_window_count:
        grouped["window_matching"] = {
            "category": "window_matching",
            "failed_count": max(1, len(unmatched)),
            "fields": ["window_id", "start_time"],
            "severity": "high",
            "eddypro_engine_modules": {"src/src_rp/m_rp_main.f90", "src/src_common/m_date_time.f90"},
            "suggested_action": CATEGORY_GUIDANCE["window_matching"],
            "unmatched_windows": unmatched,
        }

    if row_count <= 0 or str(raw_import_summary.get("status", "")) in {"", "empty", "error"}:
        grouped["raw_import"] = {
            "category": "raw_import",
            "failed_count": 1,
            "fields": ["raw_input"],
            "severity": "high",
            "eddypro_engine_modules": {"src/src_common/m_raw_file.f90", "src/src_common/m_fp2_to_float.f90"},
            "suggested_action": CATEGORY_GUIDANCE["raw_import"],
            "raw_import_status": str(raw_import_summary.get("status", "")),
        }

    if reference_window_count <= 0:
        grouped["window_matching"] = {
            "category": "window_matching",
            "failed_count": 1,
            "fields": ["reference_windows"],
            "severity": "high",
            "eddypro_engine_modules": {"src/src_rp/m_rp_main.f90"},
            "suggested_action": "Provide official EddyPro Full_Output-derived reference windows before claiming parity.",
        }

    return [
        {
            **{key: value for key, value in group.items() if key != "eddypro_engine_modules"},
            "fields": sorted(set(str(item) for item in list(group.get("fields", []) or []) if str(item))),
            "eddypro_engine_modules": sorted(str(item) for item in set(group.get("eddypro_engine_modules", set()))),
        }
        for group in sorted(grouped.values(), key=lambda item: (-int(item.get("failed_count", 0) or 0), str(item.get("category", ""))))
    ]


def _max_severity(left: str, right: str) -> str:
    order = {"pass": 0, "low": 1, "medium": 2, "high": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


_TRACE_GAS_LEVEL_FIELDS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "ch4_flux_level0_nmol_m2_s",
        ("ch4_flux_level0_nmol_m2_s", "ch4_level0_flux_nmol_m2_s", "li7700_level0_flux_nmol_m2_s", "FCH4_LEVEL0"),
        ("level0_flux_nmol_m2_s", "level0.flux_nmol_m2_s"),
    ),
    (
        "ch4_flux_level1_spectral_nmol_m2_s",
        (
            "ch4_flux_level1_spectral_nmol_m2_s",
            "ch4_level1_spectral_flux_nmol_m2_s",
            "li7700_level1_spectral_flux_nmol_m2_s",
            "FCH4_LEVEL1",
        ),
        ("level1_spectral_flux_nmol_m2_s", "level1.flux_nmol_m2_s"),
    ),
    (
        "ch4_flux_level2_density_nmol_m2_s",
        (
            "ch4_flux_level2_density_nmol_m2_s",
            "ch4_level2_density_flux_nmol_m2_s",
            "li7700_level2_density_flux_nmol_m2_s",
            "FCH4_LEVEL2",
        ),
        ("level2_density_flux_nmol_m2_s", "level2.flux_nmol_m2_s"),
    ),
    (
        "ch4_flux_corrected_nmol_m2_s",
        (
            "ch4_flux_corrected_nmol_m2_s",
            "ch4_flux_level3_corrected_nmol_m2_s",
            "ch4_level3_corrected_flux_nmol_m2_s",
            "li7700_level3_corrected_flux_nmol_m2_s",
            "FCH4_LEVEL3",
        ),
        ("level3_corrected_flux_nmol_m2_s", "level3.flux_nmol_m2_s"),
    ),
    (
        "ch4_flux_nmol_m2_s",
        ("ch4_flux_nmol_m2_s", "ch4_final_flux_nmol_m2_s", "li7700_final_flux_nmol_m2_s", "FCH4"),
        ("final_flux_nmol_m2_s", "level3.flux_nmol_m2_s"),
    ),
)


def _trace_gas_parity_summary(
    *,
    rp_result: Any,
    reference_windows: list[dict[str, Any]],
    rel_threshold: float,
    time_match_tolerance_s: float,
) -> dict[str, Any]:
    from models.rp_models import RPRunResult

    if not isinstance(rp_result, RPRunResult):
        return {"artifact_type": "li7700_trace_gas_parity_v1", "status": "not_available", "reason": "rp_result missing"}
    windows: list[dict[str, Any]] = []
    comparison_count = 0
    passed_count = 0
    failed_fields: set[str] = set()
    matched_reference_count = 0
    reference_trace_window_count = sum(1 for ref in reference_windows if _reference_has_trace_gas_fields(ref))
    first_diag = next((dict(window.diagnostics or {}) for window in rp_result.windows if dict(window.diagnostics or {}).get("ch4_method")), {})
    wms_line_shape_window_count = 0
    wms_statuses: set[str] = set()
    wms_fit_models: set[str] = set()

    for window in rp_result.windows:
        ref, match_strategy = _match_reference_window(
            window=window,
            reference_windows=reference_windows,
            time_match_tolerance_s=time_match_tolerance_s,
        )
        diagnostics = dict(window.diagnostics or {})
        sequence = dict(diagnostics.get("ch4_correction_sequence", {}) or {})
        spectroscopic = dict(sequence.get("components", {}).get("spectroscopic", {}) or {})
        if spectroscopic.get("mode") == "wms_line_shape" or diagnostics.get("li7700_wms_fit_quality_status"):
            wms_line_shape_window_count += 1
            if spectroscopic.get("status"):
                wms_statuses.add(str(spectroscopic.get("status")))
            if diagnostics.get("li7700_wms_fit_quality_status"):
                wms_statuses.add(str(diagnostics.get("li7700_wms_fit_quality_status")))
            if diagnostics.get("li7700_wms_selected_fit_model"):
                wms_fit_models.add(str(diagnostics.get("li7700_wms_selected_fit_model")))
        comparisons: list[dict[str, Any]] = []
        if ref is not None and _reference_has_trace_gas_fields(ref):
            matched_reference_count += 1
            for field_name, ref_aliases, sequence_aliases in _TRACE_GAS_LEVEL_FIELDS:
                ref_value = _reference_trace_value(ref, aliases=ref_aliases, sequence_aliases=sequence_aliases)
                if ref_value is None:
                    continue
                actual_value = _actual_trace_value(diagnostics, sequence, field_name=field_name, sequence_aliases=sequence_aliases)
                comparison = _trace_numeric_comparison(
                    field_name=field_name,
                    reference_value=ref_value,
                    actual_value=actual_value,
                    threshold=rel_threshold,
                )
                comparisons.append(comparison)
                comparison_count += 1
                if comparison["passed"]:
                    passed_count += 1
                else:
                    failed_fields.add(field_name)
            method_reference = _first_non_empty(
                ref,
                ("ch4_method", "trace_gas_ch4_method", "li7700_method", "spectral_correction_method"),
            )
            if method_reference and diagnostics.get("ch4_method"):
                passed = str(method_reference) == str(diagnostics.get("ch4_method"))
                comparisons.append(
                    {
                        "field_name": "ch4_method",
                        "reference_value": str(method_reference),
                        "actual_value": str(diagnostics.get("ch4_method", "")),
                        "absolute_error": None,
                        "relative_error": None,
                        "threshold": 0.0,
                        "passed": passed,
                        "note": "" if passed else f"CH4 method mismatch: ref={method_reference}, actual={diagnostics.get('ch4_method', '')}",
                    }
                )
                comparison_count += 1
                if passed:
                    passed_count += 1
                else:
                    failed_fields.add("ch4_method")
        windows.append(
            {
                "window_id": getattr(window, "window_id", ""),
                "start_time": getattr(window, "start_time", "").isoformat()
                if hasattr(getattr(window, "start_time", ""), "isoformat")
                else "",
                "matched_reference_window_id": str(dict(ref or {}).get("window_id", "")),
                "match_strategy": match_strategy,
                "status": "pass" if comparisons and all(item["passed"] for item in comparisons) else ("not_available" if not comparisons else "fail"),
                "comparisons": comparisons,
                "ch4_method": diagnostics.get("ch4_method", ""),
                "ch4_coefficient_profile_id": diagnostics.get("ch4_coefficient_profile_id", ""),
                "ch4_coefficient_registry_status": diagnostics.get("ch4_coefficient_registry_status", ""),
                "ch4_correction_sequence_status": sequence.get("status", ""),
                "ch4_spectroscopic_status": spectroscopic.get("status", ""),
                "li7700_wms_fit_quality_status": diagnostics.get("li7700_wms_fit_quality_status", ""),
                "li7700_wms_selected_fit_model": diagnostics.get("li7700_wms_selected_fit_model", ""),
            }
        )

    if comparison_count == 0:
        status = "fail" if reference_trace_window_count > 0 else "not_available"
        return {
            "artifact_type": "li7700_trace_gas_parity_v1",
            "status": status,
            "reason": (
                "CH4/LI-7700 reference level fields were supplied but no RP window matched them."
                if status == "fail"
                else "No CH4/LI-7700 reference level fields were supplied."
            ),
            "reference_trace_window_count": reference_trace_window_count,
            "window_count": len(rp_result.windows),
            "method": first_diag.get("ch4_method", ""),
            "coefficient_profile_id": first_diag.get("ch4_coefficient_profile_id", ""),
            "coefficient_registry_status": first_diag.get("ch4_coefficient_registry_status", ""),
            "wms_line_shape_window_count": wms_line_shape_window_count,
            "wms_line_shape_statuses": sorted(wms_statuses),
            "wms_line_shape_fit_models": sorted(wms_fit_models),
            "windows": windows,
        }
    pass_rate = passed_count / comparison_count if comparison_count else 0.0
    status = "pass" if not failed_fields and matched_reference_count == reference_trace_window_count else "fail"
    known_limitations = [
        "Missing reference level fields are skipped rather than inferred.",
    ]
    if wms_line_shape_window_count:
        known_limitations.insert(
            0,
            "Configured LI-7700 WMS line-shape fitting is exposed in the artifact, but firmware-equivalent WMS numeric parity still requires matching LI-7700 golden output.",
        )
    else:
        known_limitations.insert(0, "Raw WMS line-shape fitting is not reproduced by this parity layer.")
    return {
        "artifact_type": "li7700_trace_gas_parity_v1",
        "status": status,
        "method": first_diag.get("ch4_method", ""),
        "coefficient_profile_id": first_diag.get("ch4_coefficient_profile_id", ""),
        "coefficient_registry_status": first_diag.get("ch4_coefficient_registry_status", ""),
        "coefficient_profile_source_file": first_diag.get("ch4_coefficient_source_file", ""),
        "coefficient_profile_provenance": first_diag.get("ch4_coefficient_profile_provenance", ""),
        "threshold": rel_threshold,
        "window_count": len(rp_result.windows),
        "reference_trace_window_count": reference_trace_window_count,
        "matched_reference_count": matched_reference_count,
        "comparison_count": comparison_count,
        "passed_count": passed_count,
        "pass_rate": pass_rate,
        "failed_fields": sorted(failed_fields),
        "wms_line_shape_window_count": wms_line_shape_window_count,
        "wms_line_shape_statuses": sorted(wms_statuses),
        "wms_line_shape_fit_models": sorted(wms_fit_models),
        "windows": windows,
        "truthfulness_note": (
            "LI-7700 Level 0/1/2/3 parity is evaluated only for supplied CH4 reference fields. "
            "A pass is official EddyPro evidence only when those reference fields originate from the matching EddyPro run."
        ),
        "known_limitations": known_limitations,
    }


def _trace_numeric_comparison(
    *,
    field_name: str,
    reference_value: float,
    actual_value: float | None,
    threshold: float,
) -> dict[str, Any]:
    if actual_value is None:
        return {
            "field_name": field_name,
            "reference_value": reference_value,
            "actual_value": None,
            "absolute_error": None,
            "relative_error": None,
            "threshold": threshold,
            "passed": False,
            "note": "missing actual LI-7700 level value",
        }
    absolute_error = abs(actual_value - reference_value)
    relative_error = absolute_error / abs(reference_value) if abs(reference_value) > 1e-15 else None
    passed = (relative_error if relative_error is not None else absolute_error) <= threshold
    return {
        "field_name": field_name,
        "reference_value": reference_value,
        "actual_value": actual_value,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "threshold": threshold,
        "passed": passed,
        "note": ""
        if passed
        else (
            f"{field_name}: actual={actual_value:.6g}, ref={reference_value:.6g}, rel_err={relative_error:.4f}"
            if relative_error is not None
            else f"{field_name}: actual={actual_value:.6g}, ref={reference_value:.6g}, abs_err={absolute_error:.6g}"
        ),
    }


def _window_summary(window: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(window, "diagnostics", {}) or {})
    return {
        "window_id": getattr(window, "window_id", ""),
        "start_time": getattr(window, "start_time", "").isoformat() if hasattr(getattr(window, "start_time", ""), "isoformat") else "",
        "end_time": getattr(window, "end_time", "").isoformat() if hasattr(getattr(window, "end_time", ""), "isoformat") else "",
        "primary_flux": getattr(window, "primary_flux", None),
        "primary_flux_source": getattr(window, "primary_flux_source", ""),
        "lag_seconds": getattr(window, "lag_seconds", None),
        "qc_grade": getattr(window, "qc_grade", ""),
        "rotation_mode": getattr(window, "rotation_mode", ""),
        "applied_rotation_impl": diagnostics.get("applied_rotation_impl", ""),
        "ch4_method": diagnostics.get("ch4_method", ""),
        "ch4_flux_nmol_m2_s": diagnostics.get("ch4_flux_nmol_m2_s"),
        "ch4_flux_level0_nmol_m2_s": diagnostics.get("ch4_flux_level0_nmol_m2_s"),
        "ch4_flux_level1_spectral_nmol_m2_s": diagnostics.get("ch4_flux_level1_spectral_nmol_m2_s"),
        "ch4_flux_level2_density_nmol_m2_s": diagnostics.get("ch4_flux_level2_density_nmol_m2_s"),
        "ch4_flux_corrected_nmol_m2_s": diagnostics.get("ch4_flux_corrected_nmol_m2_s"),
        "ch4_coefficient_profile_id": diagnostics.get("ch4_coefficient_profile_id", ""),
        "ch4_spectroscopic_correction_factor": diagnostics.get("ch4_spectroscopic_correction_factor"),
        "ch4_correction_sequence_status": dict(diagnostics.get("ch4_correction_sequence", {}) or {}).get("status", ""),
        "li7700_wms_fit_quality_status": diagnostics.get("li7700_wms_fit_quality_status", ""),
        "li7700_wms_selected_fit_model": diagnostics.get("li7700_wms_selected_fit_model", ""),
        "li7700_wms_area_source": diagnostics.get("li7700_wms_area_source", ""),
    }


def _load_reference_windows_with_extras(path: str | Path) -> list[dict[str, Any]]:
    normalized = load_eddypro_reference_with_qc_mapping(path)
    raw_items = _raw_reference_items(path)
    if not raw_items:
        return normalized
    raw_by_id = {str(item.get("window_id", "")): dict(item) for item in raw_items if str(item.get("window_id", ""))}
    raw_by_start = {str(item.get("start_time", "")): dict(item) for item in raw_items if str(item.get("start_time", ""))}
    merged: list[dict[str, Any]] = []
    for index, item in enumerate(normalized):
        raw = raw_by_id.get(str(item.get("window_id", ""))) or raw_by_start.get(str(item.get("start_time", "")))
        if raw is None and index < len(raw_items):
            raw = dict(raw_items[index])
        merged.append({**dict(raw or {}), **dict(item)})
    return merged


def _raw_reference_items(path: str | Path) -> list[dict[str, Any]]:
    ref_path = Path(path)
    if not ref_path.exists():
        return []
    if ref_path.suffix.lower() == ".json":
        try:
            payload = json.loads(ref_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(payload, dict) and isinstance(payload.get("windows"), list):
            payload = payload["windows"]
        elif isinstance(payload, dict):
            payload = [payload]
        return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    try:
        with ref_path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _match_reference_window(
    *,
    window: Any,
    reference_windows: list[dict[str, Any]],
    time_match_tolerance_s: float,
) -> tuple[dict[str, Any] | None, str]:
    window_id = str(getattr(window, "window_id", ""))
    for ref in reference_windows:
        if str(ref.get("window_id", "")) == window_id:
            return dict(ref), "window_id_exact"
    start_time = getattr(window, "start_time", None)
    start_iso = start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time or "")
    for ref in reference_windows:
        if str(ref.get("start_time", "")) == start_iso:
            return dict(ref), "start_time_exact"
    if hasattr(start_time, "isoformat"):
        for ref in reference_windows:
            try:
                ref_dt = datetime.fromisoformat(str(ref.get("start_time", "")))
                delta = abs((start_time - ref_dt).total_seconds())
            except (TypeError, ValueError):
                continue
            if delta <= time_match_tolerance_s:
                return dict(ref), f"start_time_fuzzy({delta:.0f}s)"
    return None, "none"


def _reference_has_trace_gas_fields(reference: dict[str, Any]) -> bool:
    return any(
        _reference_trace_value(reference, aliases=aliases, sequence_aliases=sequence_aliases) is not None
        for _, aliases, sequence_aliases in _TRACE_GAS_LEVEL_FIELDS
    )


def _reference_trace_value(
    reference: dict[str, Any],
    *,
    aliases: tuple[str, ...],
    sequence_aliases: tuple[str, ...],
) -> float | None:
    for alias in aliases:
        value = reference.get(alias)
        if value in (None, ""):
            value = reference.get(alias.lower())
        number = _safe_float(value)
        if number is not None:
            return number
    sequence = _reference_sequence(reference)
    for alias in sequence_aliases:
        number = _safe_float(_nested_value(sequence, alias))
        if number is not None:
            return number
    return None


def _actual_trace_value(
    diagnostics: dict[str, Any],
    sequence: dict[str, Any],
    *,
    field_name: str,
    sequence_aliases: tuple[str, ...],
) -> float | None:
    number = _safe_float(diagnostics.get(field_name))
    if number is not None:
        return number
    if field_name == "ch4_flux_corrected_nmol_m2_s":
        number = _safe_float(diagnostics.get("ch4_flux_level3_corrected_nmol_m2_s"))
        if number is not None:
            return number
    for alias in sequence_aliases:
        number = _safe_float(_nested_value(sequence, alias))
        if number is not None:
            return number
    return None


def _reference_sequence(reference: dict[str, Any]) -> dict[str, Any]:
    for key in ("ch4_correction_sequence", "li7700_correction_sequence", "trace_gas_ch4_correction_sequence"):
        value = reference.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    return {}


def _nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        if part in current:
            current = current[part]
            continue
        levels = current.get("levels") if isinstance(current.get("levels"), dict) else None
        if isinstance(levels, dict) and part in levels:
            current = levels[part]
            continue
        return None
    return current


def _first_non_empty(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return ""


def _metadata_bundle(metadata: MetadataBundle | dict[str, Any] | None) -> MetadataBundle:
    if isinstance(metadata, MetadataBundle):
        return metadata
    if isinstance(metadata, dict):
        return MetadataBundle.from_dict(metadata)
    return MetadataBundle()


def _raw_format(path: Path, metadata: MetadataBundle) -> str:
    native_format = str(metadata.raw_file_settings.extra.get("native_format", "") or "").strip()
    if native_format:
        return native_format
    source_type = str(metadata.raw_file_description.source_type or "").strip()
    if source_type:
        return source_type
    return path.suffix.lower().lstrip(".") or "unknown"


def _raw_import_summary(rows: list[NormalizedHFFrame]) -> dict[str, Any]:
    if not rows:
        return {"status": "empty", "native": False, "format": ""}
    payload = _raw_payload(rows[0])
    native = dict(payload.get("raw_native_import", {}) or {}) if isinstance(payload.get("raw_native_import"), dict) else {}
    if native:
        return {
            "status": str(native.get("status", "")),
            "native": True,
            "format": str(native.get("format", "")),
            "data_type": str(native.get("data_type", "")),
            "column_types": list(native.get("column_types", []) or []),
            "record_count": int(native.get("record_count", 0) or 0),
            "decoded_record_count": int(native.get("decoded_record_count", native.get("record_count", 0)) or 0),
            "columns": list(native.get("columns", []) or []),
            "column_source": str(native.get("column_source", "")),
            "header_rows": int(native.get("header_rows", 0) or 0),
            "header_row_source": str(native.get("header_row_source", "")),
            "ascii_header_eol": str(native.get("ascii_header_eol", "auto")),
            "header_bytes": int(native.get("header_bytes", 0) or 0),
            "leading_ulong_columns": list(native.get("leading_ulong_columns", []) or []),
            "first_record": int(native.get("first_record", 1) or 1),
            "last_record": int(native.get("last_record", 0) or 0),
            "record_index_offset": int(native.get("record_index_offset", 0) or 0),
            "record_header_bytes": int(native.get("record_header_bytes", 0) or 0),
            "record_length_bytes": int(native.get("record_length_bytes", 0) or 0),
            "record_footer_bytes": int(native.get("record_footer_bytes", 0) or 0),
            "start_time": str(native.get("start_time", "")),
            "timestamp_source": str(native.get("timestamp_source", "")),
            "filename_timestamp": dict(native.get("filename_timestamp", {}) or {}),
            "record_timestamp": dict(native.get("record_timestamp", {}) or {}),
            "header_detection": native.get("header_detection", {}),
            "source_reference": native.get("source_reference", {}),
            "limitations": list(native.get("limitations", []) or []),
        }
    ygas = dict(payload.get("ygas_protocol_import", {}) or {}) if isinstance(payload.get("ygas_protocol_import"), dict) else {}
    if ygas:
        return {
            "status": str(ygas.get("status", "")),
            "native": False,
            "format": str(ygas.get("format", "ygas_protocol")),
            "record_count": len(rows),
            "source_reference": ygas.get("source_reference", {}),
            "limitations": list(ygas.get("limitations", []) or []),
        }
    return {"status": "decoded", "native": False, "format": "tabular_or_normalized", "record_count": len(rows)}


def _raw_payload(row: NormalizedHFFrame) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.raw_text or ""))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
