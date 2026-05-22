from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
import math
import time

import numpy as np

from core.ec_rp.analysis import (
    analyze_lag,
    apply_lag,
    apply_planar_fit_no_velocity_bias,
    apply_planar_fit_rotation,
    apply_crosswind_correction,
    apply_sonic_corrections,
    build_window_series,
    build_uncertainty_band,
    compute_ch4_flux_metrics,
    compute_flux_metrics,
    compute_li7700_correction_sequence,
    compute_footprint,
    compute_footprint_2d_grid,
    compute_planar_fit_coefficients,
    compute_spectral_correction,
    compute_stationarity_metrics,
    compute_turbulence_metrics,
    compute_uncertainty_finkelstein_sims,
    compute_uncertainty_mann_lenschow,
    compute_uncertainty_metrics,
    infer_sample_rate,
    normalize_density_correction_mode,
    normalize_detrend_mode,
    normalize_lag_strategy,
    normalize_rotation_mode,
    optimize_h2o_lag_rh,
    optimize_lag,
    pick_window_slices,
    rotate_wind,
    run_method_compare,
    run_statistical_screening,
    check_amplitude_resolution,
    check_angle_of_attack,
    check_steadiness_of_horizontal_wind,
    check_time_lag,
    generate_reference_provenance,
    run_benchmark_comparison,
    load_eddypro_reference_json,
)
from core.ec_rp.qc import classify_window_qc
from core.storage.clock_sync import apply_clock_sync_to_rows, clock_sync_diagnostics
from models.hf_models import NormalizedHFFrame
from models.rp_models import RPRunResult, WindowRPResult
from models.station_models import BiometSourceMetadata, ProjectProfile, SiteProfile, aggregate_biomet_window, load_biomet_records


LI7700_BUILTIN_COEFFICIENT_PROFILES: dict[str, dict[str, Any]] = {
    "li7700_factory_compensated": {
        "profile_id": "li7700_factory_compensated",
        "label": "LI-7700 factory-compensated mixing-ratio stream",
        "instrument_family": "LI-7700",
        "source": "builtin",
        "source_file": "builtin:li7700_factory_compensated",
        "normalization_command": "gas_ec_studio builtin li7700_factory_compensated",
        "spectroscopic_correction": {"mode": "input_corrected"},
        "self_heating_correction": {"mode": "not_configured"},
        "apply_water_vapor_dilution": True,
        "use_spectral_correction_factor": True,
        "provenance": (
            "Built-in LI-7700 profile assuming CH4 mixing-ratio input has already received "
            "factory spectroscopic compensation; no extra empirical coefficients are applied."
        ),
        "known_limitations": [
            "Raw WMS line-shape fitting is not reproduced.",
            "Instrument-specific empirical coefficients should be supplied for numeric EddyPro parity.",
        ],
    }
}


class ECRPPipeline:
    def run(
        self,
        *,
        rows: list[NormalizedHFFrame],
        project: ProjectProfile,
        site: SiteProfile,
        config: dict[str, Any],
        data_source: str = "",
        time_range: str = "",
    ) -> RPRunResult:
        run_timer_start = time.perf_counter()
        created_at = datetime.now()
        run_id = f"rp_{created_at:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        if config.get("_clock_sync_already_applied"):
            working_rows = list(rows)
            clock_sync_summary = dict(config.get("_clock_sync_summary", {}) or {})
        else:
            clock_sync_result = apply_clock_sync_to_rows(rows, config=config)
            working_rows = clock_sync_result.rows
            clock_sync_summary = clock_sync_result.summary
        sorted_rows = sorted(working_rows, key=lambda row: row.timestamp)
        sample_rate_hz = infer_sample_rate(sorted_rows, fallback_hz=float(_config_value(config, "sample_hz", "steps.window_sampling.sample_hz", default=10.0)))
        block_minutes = float(_config_value(config, "block_minutes", "steps.window_sampling.block_minutes", "steps.window_sampling.window_minutes", default=30.0))
        rotation_mode = normalize_rotation_mode(_config_value(config, "rotation_mode", "steps.rotation.rotation_mode", "steps.rotation.method", default="double"))
        detrend_mode = normalize_detrend_mode(_config_value(config, "detrend_mode", "steps.detrend.detrend_mode", "steps.detrend.method", default="block_mean"))
        density_correction_mode = normalize_density_correction_mode(_config_value(config, "density_correction_mode", "steps.density_correction.correction_mode", "steps.density_correction.method", default="wpl"))
        search_window_s = float(_config_value(config, "lag_phase.search_window_s", "lag.search_window_s", "steps.lag.search_window_s", default=4.0))
        lag_strategy = normalize_lag_strategy(_config_value(config, "lag_phase.strategy", "lag.strategy", "steps.lag.strategy", default="covariance_max"))
        expected_lag_s = _config_value(config, "lag_phase.expected_lag_s", "lag.expected_lag_s", "steps.lag.expected_lag_s", default=None)
        if expected_lag_s is not None:
            expected_lag_s = float(expected_lag_s)
        screening_config = _extract_screening_config(config)
        advanced_test_config = _extract_advanced_test_config(config)
        benchmark_config = _extract_benchmark_config(config)
        network_output_config = _extract_network_output_config(config)
        footprint_config = _extract_footprint_config(config)
        uncertainty_method_config = _extract_uncertainty_method_config(config)
        spectral_correction_config = _extract_spectral_correction_config(config)
        trace_gas_config = _extract_trace_gas_config(config)
        sonic_correction_config = _extract_sonic_correction_config(config)
        crosswind_correction_config = _extract_crosswind_correction_config(config)
        method_compare_config = _extract_method_compare_config(config)
        biomet_context = _build_biomet_context(config)
        benchmark_summary = _default_benchmark_summary(benchmark_config=benchmark_config, window_count=0)
        reference_provenance = _build_reference_provenance_artifact(benchmark_config.get("reference_id", ""))
        method_summary = _summarize_method_outputs(
            windows=[],
            footprint_config=footprint_config,
            uncertainty_method_config=uncertainty_method_config,
            spectral_correction_config=spectral_correction_config,
            method_compare_config=method_compare_config,
        )
        slices = pick_window_slices(len(sorted_rows), sample_rate_hz, block_minutes=block_minutes)
        if not sorted_rows or not slices:
            performance_profile = _summarize_performance_profile(
                windows=[],
                run_elapsed_ms=round((time.perf_counter() - run_timer_start) * 1000.0, 3),
                expected_window_count=len(slices),
            )
            return RPRunResult(
                run_id=run_id,
                created_at=created_at,
                data_source=data_source,
                time_range=time_range,
                summary=_empty_summary(
                    sample_rate_hz=sample_rate_hz,
                    message="Insufficient high-frequency input for RP window generation.",
                    project=project,
                    site=site,
                    config=config,
                    benchmark_summary=benchmark_summary,
                    reference_provenance=reference_provenance,
                    network_output_config=network_output_config,
                    method_summary=method_summary,
                    clock_sync_summary=clock_sync_summary,
                    performance_profile=performance_profile,
                ),
                windows=[],
                artifacts=_artifacts(
                    project=project,
                    site=site,
                    config=config,
                    sample_rate_hz=sample_rate_hz,
                    window_count=0,
                    benchmark_summary=benchmark_summary,
                    reference_provenance=reference_provenance,
                    network_output_config=network_output_config,
                    method_summary=method_summary,
                    clock_sync_summary=clock_sync_summary,
                    performance_profile=performance_profile,
                ),
            )

        windows: list[WindowRPResult] = []
        planar_fit_coefficients = None
        if rotation_mode in ("planar_fit", "sector_wise_planar_fit", "sector_wise_planar_fit_no_velocity_bias"):
            first_pass_windows: list[WindowRPResult] = []
            for index, (start, end) in enumerate(slices, start=1):
                window_rows = sorted_rows[start:end]
                try:
                    first_pass_windows.append(
                        self._process_window(
                            run_id=run_id,
                            window_index=index,
                            rows=window_rows,
                            sample_rate_hz=sample_rate_hz,
                            rotation_mode="double",
                            detrend_mode=detrend_mode,
                            density_correction_mode=density_correction_mode,
                            search_window_s=search_window_s,
                            lag_strategy=lag_strategy,
                            expected_lag_s=expected_lag_s,
                            screening_config=screening_config,
                            advanced_test_config=advanced_test_config,
                            benchmark_config=benchmark_config,
                            network_output_config=network_output_config,
                            footprint_config=footprint_config,
                            uncertainty_method_config=uncertainty_method_config,
                            spectral_correction_config=spectral_correction_config,
                            trace_gas_config=trace_gas_config,
                            sonic_correction_config=sonic_correction_config,
                            crosswind_correction_config=crosswind_correction_config,
                            method_compare_config=method_compare_config,
                            clock_sync_summary=clock_sync_summary,
                            biomet_override=_biomet_override_for_rows(window_rows, biomet_context),
                        )
                    )
                except Exception:
                    pass
            if first_pass_windows:
                u_list = [np.array(w.diagnostics.get("rotation_u", [])) for w in first_pass_windows if w.diagnostics.get("rotation_u") is not None]
                v_list = [np.array(w.diagnostics.get("rotation_v", [])) for w in first_pass_windows if w.diagnostics.get("rotation_v") is not None]
                w_list = [np.array(w.diagnostics.get("rotation_w", [])) for w in first_pass_windows if w.diagnostics.get("rotation_w") is not None]
                if not u_list:
                    prepared_list = [
                        _prepare_window_series(sorted_rows[s:e], sample_rate_hz, sonic_correction_config)[0]
                        for s, e in slices
                        if s < len(sorted_rows)
                    ]
                    u_list = [p.u for p in prepared_list]
                    v_list = [p.v for p in prepared_list]
                    w_list = [p.w for p in prepared_list]
                planar_fit_coefficients = compute_planar_fit_coefficients(u_list, v_list, w_list)

        for index, (start, end) in enumerate(slices, start=1):
            window_rows = sorted_rows[start:end]
            try:
                windows.append(
                    self._process_window(
                        run_id=run_id,
                        window_index=index,
                        rows=window_rows,
                        sample_rate_hz=sample_rate_hz,
                        rotation_mode=rotation_mode,
                        detrend_mode=detrend_mode,
                        density_correction_mode=density_correction_mode,
                        search_window_s=search_window_s,
                        lag_strategy=lag_strategy,
                        expected_lag_s=expected_lag_s,
                        screening_config=screening_config,
                        planar_fit_coefficients=planar_fit_coefficients,
                        advanced_test_config=advanced_test_config,
                        benchmark_config=benchmark_config,
                        network_output_config=network_output_config,
                        footprint_config=footprint_config,
                        uncertainty_method_config=uncertainty_method_config,
                        spectral_correction_config=spectral_correction_config,
                        trace_gas_config=trace_gas_config,
                        sonic_correction_config=sonic_correction_config,
                        crosswind_correction_config=crosswind_correction_config,
                        method_compare_config=method_compare_config,
                        clock_sync_summary=clock_sync_summary,
                        biomet_override=_biomet_override_for_rows(window_rows, biomet_context),
                    )
                )
            except Exception as exc:  # pragma: no cover
                windows.append(
                    _failed_window_result(
                        run_id=run_id,
                        window_index=index,
                        rows=window_rows,
                        rotation_mode=rotation_mode,
                        detrend_mode=detrend_mode,
                        reason=f"window processing failed: {exc}",
                        clock_sync_summary=clock_sync_summary,
                    )
                )

        if benchmark_config.get("status") == "active" and benchmark_config.get("reference_id"):
            _auto_fill_benchmark_deviation(windows=windows, benchmark_config=benchmark_config)
        benchmark_summary = _summarize_benchmark_windows(windows=windows, benchmark_config=benchmark_config)
        reference_provenance = _build_reference_provenance_artifact(benchmark_config.get("reference_id", ""))
        method_summary = _summarize_method_outputs(
            windows=windows,
            footprint_config=footprint_config,
            uncertainty_method_config=uncertainty_method_config,
            spectral_correction_config=spectral_correction_config,
            method_compare_config=method_compare_config,
        )
        performance_profile = _summarize_performance_profile(
            windows=windows,
            run_elapsed_ms=round((time.perf_counter() - run_timer_start) * 1000.0, 3),
            expected_window_count=len(slices),
        )

        return RPRunResult(
            run_id=run_id,
            created_at=created_at,
            data_source=data_source,
            time_range=time_range,
            summary=_build_summary(
                windows=windows,
                sample_rate_hz=sample_rate_hz,
                project=project,
                site=site,
                config=config,
                benchmark_summary=benchmark_summary,
                reference_provenance=reference_provenance,
                network_output_config=network_output_config,
                method_summary=method_summary,
                clock_sync_summary=clock_sync_summary,
                performance_profile=performance_profile,
            ),
            windows=windows,
            artifacts=_artifacts(
                project=project,
                site=site,
                config=config,
                sample_rate_hz=sample_rate_hz,
                window_count=len(windows),
                benchmark_summary=benchmark_summary,
                reference_provenance=reference_provenance,
                network_output_config=network_output_config,
                method_summary=method_summary,
                clock_sync_summary=clock_sync_summary,
                performance_profile=performance_profile,
            ),
        )

    def _process_window(
        self,
        *,
        run_id: str,
        window_index: int,
        rows: list[NormalizedHFFrame],
        sample_rate_hz: float,
        rotation_mode: str,
        detrend_mode: str,
        density_correction_mode: str = "wpl",
        search_window_s: float,
        lag_strategy: str = "covariance_max",
        expected_lag_s: float | None = None,
        screening_config: dict[str, Any] | None = None,
        planar_fit_coefficients: dict[str, Any] | None = None,
        advanced_test_config: dict[str, Any] | None = None,
        benchmark_config: dict[str, Any] | None = None,
        network_output_config: dict[str, Any] | None = None,
        footprint_config: dict[str, Any] | None = None,
        uncertainty_method_config: dict[str, Any] | None = None,
        spectral_correction_config: dict[str, Any] | None = None,
        trace_gas_config: dict[str, Any] | None = None,
        sonic_correction_config: dict[str, Any] | None = None,
        crosswind_correction_config: dict[str, Any] | None = None,
        method_compare_config: dict[str, Any] | None = None,
        clock_sync_summary: dict[str, Any] | None = None,
        biomet_override: dict[str, Any] | None = None,
    ) -> WindowRPResult:
        window_timer_start = time.perf_counter()
        performance_sections: dict[str, float] = {}
        prepared, sonic_correction_detail = _prepare_window_series(rows, sample_rate_hz, sonic_correction_config)
        if biomet_override:
            _apply_biomet_override(prepared, biomet_override)
        crosswind_result = apply_crosswind_correction(
            u=prepared.u,
            v=prepared.v,
            temp_c=prepared.temp_c,
            config=crosswind_correction_config,
        )
        if crosswind_result.detail.get("applied"):
            prepared.temp_c = crosswind_result.temp_c
        crosswind_correction_detail = crosswind_result.detail
        if rotation_mode in ("sector_wise_planar_fit", "sector_wise_planar_fit_no_velocity_bias") and planar_fit_coefficients:
            mean_u = float(np.mean(prepared.u))
            mean_v = float(np.mean(prepared.v))
            wind_dir = math.degrees(math.atan2(mean_v, mean_u)) % 360.0
            n_sectors = len(planar_fit_coefficients)
            sector_width = 360.0 / max(1, n_sectors)
            sector_idx = min(int(wind_dir / sector_width), n_sectors - 1)
            sector_label = f"S{sector_idx:02d}"
            coefficients = planar_fit_coefficients.get(sector_label)
            if rotation_mode == "sector_wise_planar_fit_no_velocity_bias" and coefficients:
                rotation = apply_planar_fit_no_velocity_bias(prepared.u, prepared.v, prepared.w, coefficients)
            elif coefficients:
                rotation = apply_planar_fit_rotation(prepared.u, prepared.v, prepared.w, coefficients)
            else:
                rotation = rotate_wind(prepared.u, prepared.v, prepared.w, "double")
        elif rotation_mode in ("planar_fit", "sector_wise_planar_fit", "sector_wise_planar_fit_no_velocity_bias"):
            rotation = rotate_wind(prepared.u, prepared.v, prepared.w, "planar_fit")
        else:
            rotation = rotate_wind(prepared.u, prepared.v, prepared.w, rotation_mode)
        lag_result = analyze_lag(rotation.w, prepared.co2_ppm, prepared.h2o_mmol, sample_rate_hz=sample_rate_hz, search_window_s=search_window_s, lag_strategy=lag_strategy, expected_lag_s=expected_lag_s)
        lagged_co2 = apply_lag(prepared.co2_ppm, lag_result.co2_lag_seconds, sample_rate_hz)
        lagged_h2o = apply_lag(prepared.h2o_mmol, lag_result.h2o_lag_seconds, sample_rate_hz)
        flux_metrics = compute_flux_metrics(w_series=rotation.w, co2_ppm=lagged_co2, h2o_mmol=lagged_h2o, pressure_kpa=prepared.pressure_kpa, temp_c=prepared.temp_c, detrend_mode=detrend_mode, density_correction_mode=density_correction_mode)
        ch4_metrics = compute_ch4_flux_metrics(
            w_series=rotation.w,
            ch4_ppb=prepared.ch4_ppb,
            air_molar_density=float(flux_metrics["air_molar_density"]),
            detrend_mode=detrend_mode,
            valid_ratio=float(prepared.diagnostics.get("ch4_valid_ratio", 0.0)),
        )
        density_correction_factor = _density_correction_factor(raw_flux=flux_metrics["raw_flux"], density_corrected_flux=flux_metrics["density_corrected_flux"])
        stationarity = compute_stationarity_metrics(w_series=rotation.w, scalar_series=lagged_co2, detrend_mode=detrend_mode)
        turbulence = compute_turbulence_metrics(
            u_series=rotation.u,
            v_series=rotation.v,
            w_series=rotation.w,
            detrend_mode=detrend_mode,
            u_valid_ratio=float(prepared.diagnostics.get("u_valid_ratio", 0.0)),
            v_valid_ratio=float(prepared.diagnostics.get("v_valid_ratio", 0.0)),
            w_valid_ratio=float(prepared.diagnostics.get("w_raw_valid_ratio", 0.0)),
        )
        uncertainty = compute_uncertainty_metrics(
            flux_metrics=flux_metrics,
            lag_confidence=float(lag_result.confidence),
            stationarity=stationarity,
            turbulence=turbulence,
            continuity_ratio=float(prepared.continuity_ratio),
            missing_ratio=float(prepared.missing_ratio),
        )
        screening = run_statistical_screening(
            {
                "co2_ppm": lagged_co2,
                "h2o_mmol": lagged_h2o,
                "w": rotation.w,
            },
            skewness_threshold=screening_config.get("skewness_threshold", 2.0) if screening_config else 2.0,
            kurtosis_threshold=screening_config.get("kurtosis_threshold", 7.0) if screening_config else 7.0,
            dropout_min_run=int(screening_config.get("dropout_min_run", 10)) if screening_config else 10,
            spike_sigma=screening_config.get("spike_sigma", 5.0) if screening_config else 5.0,
            discontinuity_sigma=screening_config.get("discontinuity_sigma", 8.0) if screening_config else 8.0,
            absolute_limits=screening_config.get("absolute_limits") if screening_config else None,
        )

        advanced_tests: dict[str, Any] = {}
        advanced_tests["amplitude_resolution_co2"] = check_amplitude_resolution(prepared.co2_ppm, resolution=advanced_test_config.get("amplitude_resolution_resolution") if advanced_test_config else None, ratio_threshold=float(advanced_test_config.get("amplitude_resolution_ratio_threshold", 10.0)) if advanced_test_config else 10.0)
        advanced_tests["amplitude_resolution_h2o"] = check_amplitude_resolution(prepared.h2o_mmol, resolution=advanced_test_config.get("amplitude_resolution_resolution") if advanced_test_config else None, ratio_threshold=float(advanced_test_config.get("amplitude_resolution_ratio_threshold", 10.0)) if advanced_test_config else 10.0)
        advanced_tests["time_lag_co2"] = check_time_lag(rotation.w, prepared.co2_ppm, sample_rate_hz, max_lag_s=float(advanced_test_config.get("time_lag_max_lag_s", 5.0)) if advanced_test_config else 5.0, confidence_threshold=float(advanced_test_config.get("time_lag_confidence_threshold", 0.4)) if advanced_test_config else 0.4)
        advanced_tests["time_lag_h2o"] = check_time_lag(rotation.w, prepared.h2o_mmol, sample_rate_hz, max_lag_s=float(advanced_test_config.get("time_lag_max_lag_s", 5.0)) if advanced_test_config else 5.0, confidence_threshold=float(advanced_test_config.get("time_lag_confidence_threshold", 0.4)) if advanced_test_config else 0.4)
        advanced_tests["angle_of_attack"] = check_angle_of_attack(rotation.u, rotation.w, max_angle_deg=float(advanced_test_config.get("angle_of_attack_max_angle_deg", 40.0)) if advanced_test_config else 40.0)
        advanced_tests["steadiness_of_horizontal_wind"] = check_steadiness_of_horizontal_wind(rotation.u, rotation.v, cv_threshold=float(advanced_test_config.get("steadiness_cv_threshold", 0.50)) if advanced_test_config else 0.50)
        advanced_fail_count = sum(1 for v in advanced_tests.values() if v.get("status") == "fail")
        advanced_pass_count = sum(1 for v in advanced_tests.values() if v.get("status") == "pass")
        advanced_other_count = len(advanced_tests) - advanced_fail_count - advanced_pass_count
        combined_issues = list(prepared.issues) + [issue for issue in screening["issues"] if issue not in prepared.issues]
        combined_qc_reasons = list(prepared.qc_reasons) + [reason for reason in screening["qc_reasons"] if reason not in prepared.qc_reasons]
        qc = classify_window_qc(
            issues=combined_issues,
            continuity_ratio=prepared.continuity_ratio,
            missing_ratio=prepared.missing_ratio,
            lag_confidence=lag_result.confidence,
            density_correction_factor=density_correction_factor,
            rotation_applied=rotation.applied or rotation.mode == "none",
            mean_rotated_w=float(np.mean(rotation.w)),
            stationarity_score=stationarity.score,
            stationarity_detail=stationarity.detail,
            turbulence_score=turbulence.score,
            turbulence_detail=turbulence.detail,
            ustar=turbulence.ustar,
            advanced_tests=advanced_tests,
        )
        diagnostics = {
            **prepared.diagnostics,
            **clock_sync_diagnostics(clock_sync_summary),
            "issues": list(combined_issues),
            "qc_reasons": list(combined_qc_reasons),
            "rotation_applied": bool(rotation.applied),
            "rotation_reason": rotation.reason,
            "requested_rotation_mode": rotation_mode,
            "applied_rotation_impl": rotation.mode,
            "rotation_alpha_deg": float(rotation.alpha_deg),
            "rotation_beta_deg": float(rotation.beta_deg),
            "max_gap_seconds": float(prepared.max_gap_seconds),
            "lag_curve_x": list(lag_result.lag_curve_x),
            "lag_curve_y": list(lag_result.lag_curve_y),
            "co2_lag_seconds": float(lag_result.co2_lag_seconds),
            "h2o_lag_seconds": float(lag_result.h2o_lag_seconds),
            "lag_strategy": lag_strategy,
            "lag_fallback_reason": lag_result.fallback_reason if hasattr(lag_result, "fallback_reason") else "",
            "density_correction_factor": float(density_correction_factor),
            "density_correction_mode": flux_metrics.get("density_correction_mode", "wpl"),
            "density_correction_reason": flux_metrics.get("density_correction_reason", ""),
            "primary_flux_source": flux_metrics.get("density_correction_mode", "wpl"),
            "wpl_water_vapor_term": flux_metrics.get("wpl_water_vapor_term", 0.0),
            "wpl_sensible_heat_term": flux_metrics.get("wpl_sensible_heat_term", 0.0),
            "qc_score": float(qc["qc_score"]),
            "stationarity_detail": stationarity.detail,
            "turbulence_detail": turbulence.detail,
            "uncertainty_detail": uncertainty.detail,
            "screening_detail": screening.get("detail", {}),
            "screening_config": screening_config or {},
            "screening_summary": f"issues={len(screening.get('detail', {}).get('issues', []))}, passed={sum(1 for v in screening.get('detail', {}).values() if isinstance(v, dict) and not v.get('issues'))}; advanced_tests: pass={advanced_pass_count}, fail={advanced_fail_count}, other={advanced_other_count}",
            "qc_details": advanced_tests,
            "advanced_qc_contribution": {
                k: {"status": v.get("status"), "weight": 1.0, "score_contribution": 100.0 if v.get("status") == "pass" else (25.0 if v.get("status") == "fail" else 35.0)}
                for k, v in advanced_tests.items()
            },
            "advanced_test_weights": {k: 1.0 for k in advanced_tests},
            "advanced_test_thresholds": advanced_test_config or {},
            "wpl_benchmark_status": _wpl_benchmark_status(flux_metrics),
            "sonic_correction_status": sonic_correction_detail.get("status", ""),
            "sonic_correction_method": sonic_correction_detail.get("method", ""),
            "sonic_correction_detail": sonic_correction_detail,
            "sonic_correction_steps": sonic_correction_detail.get("steps", []),
            "sonic_correction_provenance": sonic_correction_detail.get("provenance", ""),
            "sonic_correction_limitations": sonic_correction_detail.get("limitations", []),
            "sonic_correction_source_reference": sonic_correction_detail.get("source_reference", {}),
            "crosswind_correction_status": crosswind_correction_detail.get("status", ""),
            "crosswind_correction_method": crosswind_correction_detail.get("method", ""),
            "crosswind_correction_detail": crosswind_correction_detail,
            "crosswind_correction_provenance": crosswind_correction_detail.get("provenance", ""),
            "crosswind_correction_limitations": crosswind_correction_detail.get("limitations", []),
            "crosswind_correction_mean_delta_c": crosswind_correction_detail.get("mean_delta_c"),
            "crosswind_correction_max_abs_delta_c": crosswind_correction_detail.get("max_abs_delta_c"),
            "trace_gas_family": {
                "ch4": {
                    "status": ch4_metrics.get("status", "not_available"),
                    "method": ch4_metrics.get("selected_method", "not_available"),
                    "valid_ratio": ch4_metrics.get("valid_ratio", 0.0),
                    "flux_units": "nmol m-2 s-1",
                    "provenance": ch4_metrics.get("provenance", ""),
                    "limitations": ch4_metrics.get("limitations", []),
                }
            },
            "ch4_detail": ch4_metrics,
            "ch4_status": ch4_metrics.get("status", "not_available"),
            "ch4_flux_nmol_m2_s": ch4_metrics.get("ch4_flux_nmol_m2_s"),
            "cov_w_ch4_ppb": ch4_metrics.get("cov_w_ch4_ppb"),
            "mean_ch4_ppb": ch4_metrics.get("mean_ch4_ppb"),
            "ch4_valid_ratio": ch4_metrics.get("valid_ratio", prepared.diagnostics.get("ch4_valid_ratio", 0.0)),
            "ch4_method": ch4_metrics.get("selected_method", "not_available"),
            "ch4_provenance": ch4_metrics.get("provenance", ""),
            "ch4_limitations": ch4_metrics.get("limitations", []),
            "metadata_summary": {
                "sample_rate_hz": float(sample_rate_hz),
                "sample_count": prepared.sample_count,
                "valid_sample_count": prepared.valid_sample_count,
                "continuity_ratio": float(prepared.continuity_ratio),
                "mean_co2_ppm": float(np.mean(lagged_co2)),
                "mean_h2o_mmol": float(np.mean(lagged_h2o)),
                "mean_ch4_ppb": ch4_metrics.get("mean_ch4_ppb"),
                "ch4_status": ch4_metrics.get("status", "not_available"),
                "mean_pressure_kpa": float(np.mean(prepared.pressure_kpa)),
                "mean_temp_c": float(np.mean(prepared.temp_c)),
            },
            "qc_matrix": qc["qc_matrix"],
            "qc_flags": qc["qc_flags"],
            "ustar": turbulence.ustar,
            "benchmark_status": benchmark_config.get("status", "") if benchmark_config else "",
            "benchmark_target": benchmark_config.get("target", "") if benchmark_config else "",
            "benchmark_reference_id": benchmark_config.get("reference_id", "") if benchmark_config else "",
            "benchmark_thresholds": {
                "flux_rel_threshold": float(benchmark_config.get("flux_rel_threshold", 0.10)) if benchmark_config else 0.10,
                "lag_abs_threshold_s": float(benchmark_config.get("lag_abs_threshold_s", 0.5)) if benchmark_config else 0.5,
                "wpl_rel_threshold": float(benchmark_config.get("wpl_rel_threshold", 0.20)) if benchmark_config else 0.20,
                "qc_grade_must_match": bool(benchmark_config.get("qc_grade_must_match", False)) if benchmark_config else False,
            },
            "benchmark_deviation_summary": {},
            "schema_target": network_output_config.get("schema_target", "") if network_output_config else "",
            "fluxnet_timestamp_refers_to": network_output_config.get("timestamp_refers_to", "start") if network_output_config else "start",
            "fluxnet_timezone_offset_h": float(network_output_config.get("timezone_offset_hours", 0.0)) if network_output_config else 0.0,
            "fluxnet_gap_fill_value": float(network_output_config.get("gap_fill_value", -9999.0)) if network_output_config else -9999.0,
        }
        if footprint_config and footprint_config.get("enabled", False) and turbulence.ustar is not None and turbulence.ustar > 1e-6:
            fp = compute_footprint(
                method=footprint_config.get("method", "kljun"),
                ustar=turbulence.ustar,
                mean_wind_speed=float(np.mean(rotation.u)) if rotation.u.size > 0 else 0.0,
                sigma_v=float(np.std(rotation.v)) if rotation.v.size > 0 else 0.0,
                z_m=footprint_config.get("z_m", 0.0),
                h=footprint_config.get("canopy_height_m", 0.0),
                z0=footprint_config.get("z0"),
                ol=footprint_config.get("ol"),
            )
            diagnostics["footprint_method"] = fp.method
            diagnostics["footprint_peak_distance_m"] = fp.peak_distance_m
            diagnostics["footprint_offset_distance_m"] = fp.offset_distance_m
            diagnostics["footprint_contribution_distances"] = fp.contribution_distances
            diagnostics["footprint_detail"] = fp.detail
            if footprint_config.get("grid_enabled", True):
                section_start = time.perf_counter()
                fp_grid = compute_footprint_2d_grid(
                    footprint=fp,
                    method=footprint_config.get("method", "kljun"),
                    ustar=turbulence.ustar,
                    mean_wind_speed=float(np.mean(rotation.u)) if rotation.u.size > 0 else 0.0,
                    sigma_v=float(np.std(rotation.v)) if rotation.v.size > 0 else 0.0,
                    z_m=footprint_config.get("z_m", 0.0),
                    h=footprint_config.get("canopy_height_m", 0.0),
                    z0=footprint_config.get("z0"),
                    ol=footprint_config.get("ol"),
                    x_bins=int(footprint_config.get("grid_x_bins", 32) or 32),
                    y_bins=int(footprint_config.get("grid_y_bins", 25) or 25),
                    max_downwind_m=footprint_config.get("grid_max_downwind_m"),
                    max_crosswind_m=footprint_config.get("grid_max_crosswind_m"),
                )
                if fp_grid is not None:
                    fp_grid_payload = asdict(fp_grid)
                    diagnostics["footprint_2d_grid_status"] = "ok"
                    diagnostics["footprint_2d_grid"] = fp_grid_payload
                    diagnostics["footprint_2d_peak_downwind_m"] = fp_grid.peak_downwind_m
                    diagnostics["footprint_2d_peak_crosswind_m"] = fp_grid.peak_crosswind_m
                    diagnostics["footprint_2d_half_width_m"] = fp_grid.half_width_m
                    diagnostics["footprint_2d_contribution_contours_m"] = fp_grid.contribution_contours_m
                else:
                    diagnostics["footprint_2d_grid_status"] = "insufficient_data"
                performance_sections["footprint_2d_ms"] = round((time.perf_counter() - section_start) * 1000.0, 3)
        if uncertainty_method_config and uncertainty_method_config.get("method") in ("mann_lenschow", "finkelstein_sims"):
            selected_method = uncertainty_method_config["method"]
            if selected_method == "mann_lenschow":
                ml_result = compute_uncertainty_mann_lenschow(
                    cov_w_scalar=flux_metrics["cov_w_co2"],
                    var_w=float(np.var(rotation.w)) if rotation.w.size > 1 else 0.0,
                    var_scalar=float(np.var(lagged_co2)) if lagged_co2.size > 1 else 0.0,
                    n_samples=prepared.sample_count,
                    averaging_period_s=prepared.sample_count / max(sample_rate_hz, 1.0),
                    integral_timescale_s=uncertainty_method_config.get("integral_timescale_s"),
                )
                diagnostics["uncertainty_method"] = "mann_lenschow"
                diagnostics["uncertainty_method_detail"] = ml_result
                uncertainty.detail["selected_method"] = "mann_lenschow"
                uncertainty.detail["random_error"] = ml_result.get("random_error")
                uncertainty.detail["relative_error"] = ml_result.get("relative_error")
                uncertainty.detail["relative_uncertainty"] = ml_result.get("relative_error")
                uncertainty.detail["components"] = ml_result.get("components", {})
                uncertainty.detail["limitations"] = ml_result.get("limitations", [])
                uncertainty.detail["provenance"] = ml_result.get("provenance", "")
            elif selected_method == "finkelstein_sims":
                fs_result = compute_uncertainty_finkelstein_sims(
                    w_series=rotation.w,
                    scalar_series=lagged_co2,
                    sample_rate_hz=sample_rate_hz,
                    averaging_period_s=prepared.sample_count / max(sample_rate_hz, 1.0),
                )
                diagnostics["uncertainty_method"] = "finkelstein_sims"
                diagnostics["uncertainty_method_detail"] = fs_result
                uncertainty.detail["selected_method"] = "finkelstein_sims"
                uncertainty.detail["random_error"] = fs_result.get("random_error")
                uncertainty.detail["relative_error"] = fs_result.get("relative_error")
                uncertainty.detail["relative_uncertainty"] = fs_result.get("relative_error")
                uncertainty.detail["components"] = fs_result.get("components", {})
                uncertainty.detail["limitations"] = fs_result.get("limitations", [])
                uncertainty.detail["provenance"] = fs_result.get("provenance", "")
        uncertainty_confidence_level = float(
            uncertainty_method_config.get("confidence_level", uncertainty.detail.get("confidence_level", 0.95))
            if uncertainty_method_config
            else uncertainty.detail.get("confidence_level", 0.95)
        )
        propagated_uncertainty = _propagate_uncertainty_to_primary_flux(
            primary_flux=float(flux_metrics["primary_flux"]),
            flux_metrics=flux_metrics,
            uncertainty_detail=uncertainty.detail,
            confidence_level=uncertainty_confidence_level,
        )
        uncertainty.detail["confidence_level"] = propagated_uncertainty.get("primary_flux_ci_level")
        uncertainty.detail["primary_flux_random_error"] = propagated_uncertainty.get("primary_flux_random_error")
        uncertainty.detail["primary_flux_relative_uncertainty"] = propagated_uncertainty.get("primary_flux_relative_uncertainty")
        uncertainty.detail["primary_flux_uncertainty_band"] = propagated_uncertainty.get("primary_flux_uncertainty_band")
        uncertainty.detail["primary_flux_ci_lower"] = propagated_uncertainty.get("primary_flux_ci_lower")
        uncertainty.detail["primary_flux_ci_upper"] = propagated_uncertainty.get("primary_flux_ci_upper")
        method_detail = diagnostics.get("uncertainty_method_detail")
        if isinstance(method_detail, dict):
            method_detail["confidence_level"] = propagated_uncertainty.get("primary_flux_ci_level")
            method_detail["primary_flux_random_error"] = propagated_uncertainty.get("primary_flux_random_error")
            method_detail["primary_flux_relative_uncertainty"] = propagated_uncertainty.get("primary_flux_relative_uncertainty")
            method_detail["primary_flux_uncertainty_band"] = propagated_uncertainty.get("primary_flux_uncertainty_band")
            method_detail["primary_flux_ci_lower"] = propagated_uncertainty.get("primary_flux_ci_lower")
            method_detail["primary_flux_ci_upper"] = propagated_uncertainty.get("primary_flux_ci_upper")
        diagnostics.update(propagated_uncertainty)
        measured_cospectrum_freq = None
        measured_cospectrum_value = None
        measured_cospectrum_meta = {
            "enabled": bool(spectral_correction_config.get("use_fcc_measured_cospectrum", False)) if spectral_correction_config else False,
            "used": False,
            "source": "disabled",
            "matched_window_id": "",
            "source_run_id": str(spectral_correction_config.get("fcc_source_run_id", "")) if spectral_correction_config else "",
            "match_strategy": "disabled",
            "match_quality": 0.0,
            "frequency_count": 0,
        }
        if spectral_correction_config and spectral_correction_config.get("enabled", False):
            section_start = time.perf_counter()
            if str(spectral_correction_config.get("method", "massman")) == "fratini":
                measured_cospectrum_freq, measured_cospectrum_value, measured_cospectrum_meta = _resolve_fcc_measured_cospectrum(
                    window_start=rows[0].timestamp,
                    window_end=rows[-1].timestamp,
                    spectral_correction_config=spectral_correction_config,
                )
                if measured_cospectrum_freq is None or measured_cospectrum_value is None:
                    local_freq, local_value = _measured_cospectrum_from_series(
                        w_series=rotation.w,
                        scalar_series=lagged_co2,
                        sample_rate_hz=sample_rate_hz,
                    )
                    if local_freq is not None and local_value is not None:
                        measured_cospectrum_freq = local_freq
                        measured_cospectrum_value = local_value
                        fallback_source = "rp_local" if not measured_cospectrum_meta.get("enabled") else "rp_local_fallback"
                        measured_cospectrum_meta = {
                            **measured_cospectrum_meta,
                            "used": True,
                            "source": fallback_source,
                            "frequency_count": int(local_freq.size),
                            "match_strategy": str(measured_cospectrum_meta.get("match_strategy", "local_fallback")),
                            "match_quality": float(measured_cospectrum_meta.get("match_quality", 0.35) or 0.35),
                            "fallback_reason": str(measured_cospectrum_meta.get("source", "")),
                        }
            sc = compute_spectral_correction(
                method=spectral_correction_config.get("method", "massman"),
                path_length_m=spectral_correction_config.get("path_length_m", 0.15),
                sensor_sep_m=spectral_correction_config.get("sensor_sep_m", 0.20),
                response_time_s=spectral_correction_config.get("response_time_s", 0.1),
                sample_rate_hz=sample_rate_hz,
                averaging_period_s=prepared.sample_count / max(sample_rate_hz, 1.0),
                wind_speed=float(np.mean(rotation.u)) if rotation.u.size > 0 else 0.0,
                z_m=spectral_correction_config.get("z_m", 0.0),
                ustar=turbulence.ustar or 0.0,
                ol=spectral_correction_config.get("ol"),
                measured_cospectrum_freq=measured_cospectrum_freq,
                measured_cospectrum_value=measured_cospectrum_value,
            )
            if str(sc.get("method", "")) == "fratini":
                sc = dict(sc)
                sc["measured_cospectrum_enabled"] = bool(measured_cospectrum_meta.get("enabled", False))
                sc["measured_cospectrum_used"] = bool(measured_cospectrum_meta.get("used", False))
                sc["measured_cospectrum_source"] = str(measured_cospectrum_meta.get("source", "disabled"))
                sc["measured_cospectrum_source_run_id"] = str(measured_cospectrum_meta.get("source_run_id", ""))
                sc["measured_cospectrum_window_id"] = str(measured_cospectrum_meta.get("matched_window_id", ""))
                sc["measured_cospectrum_frequency_count"] = int(measured_cospectrum_meta.get("frequency_count", 0) or 0)
                sc["measured_cospectrum_notes"] = list(measured_cospectrum_meta.get("provenance_notes", []))
                sc["measured_cospectrum_match"] = {
                    "enabled": bool(measured_cospectrum_meta.get("enabled", False)),
                    "used": bool(measured_cospectrum_meta.get("used", False)),
                    "source": str(measured_cospectrum_meta.get("source", "disabled")),
                    "match_strategy": str(measured_cospectrum_meta.get("match_strategy", "")),
                    "match_quality": float(measured_cospectrum_meta.get("match_quality", 0.0) or 0.0),
                    "matched_window_id": str(measured_cospectrum_meta.get("matched_window_id", "")),
                    "source_run_id": str(measured_cospectrum_meta.get("source_run_id", "")),
                    "source_qc_grade": str(measured_cospectrum_meta.get("source_qc_grade", "")),
                    "frequency_count": int(measured_cospectrum_meta.get("frequency_count", 0) or 0),
                    "time_delta_s": measured_cospectrum_meta.get("time_delta_s"),
                    "overlap_seconds": measured_cospectrum_meta.get("overlap_seconds"),
                    "fallback_reason": str(measured_cospectrum_meta.get("fallback_reason", "")),
                    "mismatch_warning": str(measured_cospectrum_meta.get("mismatch_warning", "")),
                }
                provenance_detail = dict(sc.get("provenance_detail", {}) or {})
                provenance_detail["measured_cospectrum_source"] = sc["measured_cospectrum_source"]
                provenance_detail["measured_cospectrum_source_run_id"] = sc["measured_cospectrum_source_run_id"]
                provenance_detail["measured_cospectrum_window_id"] = sc["measured_cospectrum_window_id"]
                provenance_detail["measured_cospectrum_match"] = sc["measured_cospectrum_match"]
                sc["provenance_detail"] = provenance_detail
            diagnostics["spectral_correction_method"] = sc.get("method", "")
            diagnostics["spectral_correction_factor"] = sc.get("correction_factor", 1.0)
            diagnostics["spectral_correction_detail"] = sc
            spectral_provenance = str(sc.get("provenance", ""))
            if str(sc.get("method", "")) == "fratini":
                spectral_provenance = (
                    f"{spectral_provenance}; measured_cospectrum={sc.get('measured_cospectrum_source', 'disabled')}"
                ).strip("; ")
            diagnostics["spectral_correction_provenance"] = spectral_provenance
            diagnostics["spectral_correction_limitations"] = sc.get("limitations", [])
            diagnostics["spectral_correction_measured_cospectrum_enabled"] = bool(sc.get("measured_cospectrum_enabled", False))
            diagnostics["spectral_correction_measured_cospectrum_used"] = bool(sc.get("measured_cospectrum_used", False))
            diagnostics["spectral_correction_measured_cospectrum_source"] = str(sc.get("measured_cospectrum_source", ""))
            diagnostics["spectral_correction_measured_cospectrum_source_run_id"] = str(sc.get("measured_cospectrum_source_run_id", ""))
            diagnostics["spectral_correction_measured_cospectrum_window_id"] = str(sc.get("measured_cospectrum_window_id", ""))
            diagnostics["spectral_correction_cospectrum_match"] = dict(sc.get("measured_cospectrum_match", {}))
            performance_sections["spectral_correction_ms"] = round((time.perf_counter() - section_start) * 1000.0, 3)
        ch4_config = dict((trace_gas_config or {}).get("ch4", {}) or {})
        diagnostics["ch4_coefficient_profile_id"] = ch4_config.get("coefficient_profile_id", "")
        diagnostics["ch4_coefficient_registry_status"] = ch4_config.get("coefficient_registry_status", "")
        diagnostics["ch4_coefficient_profile_label"] = ch4_config.get("coefficient_profile_label", "")
        diagnostics["ch4_coefficient_profile_source"] = ch4_config.get("coefficient_profile_source", "")
        diagnostics["ch4_coefficient_source_file"] = ch4_config.get("coefficient_profile_source_file", "")
        diagnostics["ch4_coefficient_normalization_command"] = ch4_config.get("coefficient_profile_normalization_command", "")
        diagnostics["ch4_coefficient_profile_provenance"] = ch4_config.get("coefficient_profile_provenance", "")
        diagnostics["ch4_coefficient_profile_limitations"] = list(ch4_config.get("coefficient_profile_limitations", []) or [])
        diagnostics["ch4_coefficient_profile"] = dict(ch4_config.get("coefficient_profile", {}) or {})
        diagnostics["trace_gas_family"]["ch4"].update(
            {
                "coefficient_profile_id": diagnostics["ch4_coefficient_profile_id"],
                "coefficient_registry_status": diagnostics["ch4_coefficient_registry_status"],
                "coefficient_profile_source_file": diagnostics["ch4_coefficient_source_file"],
                "coefficient_profile_provenance": diagnostics["ch4_coefficient_profile_provenance"],
            }
        )
        if ch4_config.get("use_spectral_correction_factor", True):
            ch4_spectral_factor = ch4_config.get("spectral_correction_factor", diagnostics.get("spectral_correction_factor", 1.0))
        else:
            ch4_spectral_factor = ch4_config.get("spectral_correction_factor", 1.0)
        ch4_sequence = compute_li7700_correction_sequence(
            ch4_metrics=ch4_metrics,
            mean_h2o_mmol=float(np.mean(lagged_h2o)),
            mean_pressure_kpa=float(np.mean(prepared.pressure_kpa)),
            mean_temp_c=float(np.mean(prepared.temp_c)),
            spectral_correction_factor=float(ch4_spectral_factor or 1.0),
            config=ch4_config,
        )
        diagnostics["ch4_correction_sequence"] = ch4_sequence
        diagnostics["ch4_coefficient_profile_id"] = ch4_sequence.get("coefficient_profile_id", diagnostics["ch4_coefficient_profile_id"])
        diagnostics["ch4_coefficient_registry_status"] = ch4_sequence.get("coefficient_registry_status", diagnostics["ch4_coefficient_registry_status"])
        diagnostics["ch4_coefficient_profile_label"] = ch4_sequence.get("coefficient_profile_label", diagnostics["ch4_coefficient_profile_label"])
        diagnostics["ch4_coefficient_source_file"] = ch4_sequence.get("coefficient_source_file", diagnostics["ch4_coefficient_source_file"])
        diagnostics["ch4_coefficient_normalization_command"] = ch4_sequence.get("coefficient_normalization_command", diagnostics["ch4_coefficient_normalization_command"])
        diagnostics["ch4_coefficient_profile_provenance"] = ch4_sequence.get("coefficient_profile_provenance", diagnostics["ch4_coefficient_profile_provenance"])
        diagnostics["ch4_coefficient_profile"] = ch4_sequence.get("coefficient_profile", diagnostics["ch4_coefficient_profile"])
        diagnostics["ch4_detail"] = {
            **ch4_metrics,
            "coefficient_profile": diagnostics["ch4_coefficient_profile"],
            "li7700_correction_sequence": ch4_sequence,
        }
        if ch4_sequence.get("status") == "computed":
            diagnostics["ch4_status"] = "computed"
            diagnostics["ch4_method"] = ch4_sequence.get("selected_method", "li_7700_correction_sequence_v1")
            diagnostics["ch4_flux_level0_nmol_m2_s"] = ch4_sequence.get("level0_flux_nmol_m2_s")
            diagnostics["ch4_flux_level1_spectral_nmol_m2_s"] = ch4_sequence.get("level1_spectral_flux_nmol_m2_s")
            diagnostics["ch4_flux_level2_density_nmol_m2_s"] = ch4_sequence.get("level2_density_flux_nmol_m2_s")
            diagnostics["ch4_flux_corrected_nmol_m2_s"] = ch4_sequence.get("level3_corrected_flux_nmol_m2_s")
            diagnostics["ch4_flux_nmol_m2_s"] = ch4_sequence.get("final_flux_nmol_m2_s")
            diagnostics["ch4_spectral_correction_factor"] = ch4_sequence.get("spectral_correction_factor")
            diagnostics["ch4_water_vapor_dilution_factor"] = ch4_sequence.get("water_vapor_dilution_factor")
            diagnostics["ch4_spectroscopic_correction_factor"] = ch4_sequence.get("spectroscopic_correction_factor")
            diagnostics["ch4_self_heating_correction_factor"] = ch4_sequence.get("self_heating_correction_factor")
            diagnostics["ch4_provenance"] = ch4_sequence.get("provenance", "")
            diagnostics["ch4_limitations"] = ch4_sequence.get("limitations", [])
            diagnostics["trace_gas_family"]["ch4"].update(
                {
                    "method": diagnostics["ch4_method"],
                    "flux_nmol_m2_s": diagnostics["ch4_flux_nmol_m2_s"],
                    "level0_flux_nmol_m2_s": diagnostics["ch4_flux_level0_nmol_m2_s"],
                    "correction_sequence_status": ch4_sequence.get("status", ""),
                    "coefficient_profile_id": diagnostics["ch4_coefficient_profile_id"],
                    "coefficient_registry_status": diagnostics["ch4_coefficient_registry_status"],
                    "coefficient_profile_source_file": diagnostics["ch4_coefficient_source_file"],
                    "coefficient_profile_provenance": diagnostics["ch4_coefficient_profile_provenance"],
                    "provenance": diagnostics["ch4_provenance"],
                    "limitations": diagnostics["ch4_limitations"],
                }
            )
        if method_compare_config and method_compare_config.get("enabled", False):
            section_start = time.perf_counter()
            compare_payload: dict[str, Any] = {}
            recommendations: dict[str, str] = {}
            deviation_flags: list[dict[str, Any]] = []
            deviation_threshold = float(method_compare_config.get("deviation_threshold", 0.25) or 0.25)
            families = {
                str(item).strip()
                for item in method_compare_config.get("families", ["footprint", "uncertainty", "spectral_correction"])
                if str(item).strip()
            }
            averaging_period_s = prepared.sample_count / max(sample_rate_hz, 1.0)
            if "footprint" in families and footprint_config and footprint_config.get("enabled", False):
                footprint_compare = run_method_compare(
                    method_family="footprint",
                    selected_method=str(footprint_config.get("method", "")),
                    methods_to_run=method_compare_config.get("footprint_methods", ["kljun", "kormann_meixner", "hsieh"]),
                    window_params={
                        "ustar": turbulence.ustar or 0.0,
                        "mean_wind_speed": float(np.mean(rotation.u)) if rotation.u.size > 0 else 0.0,
                        "sigma_v": float(np.std(rotation.v)) if rotation.v.size > 0 else 0.0,
                        "z_m": footprint_config.get("z_m", 0.0),
                        "h": footprint_config.get("canopy_height_m", 0.0),
                        "z0": footprint_config.get("z0"),
                        "ol": footprint_config.get("ol"),
                    },
                )
                compare_payload["footprint"] = asdict(footprint_compare)
            if "uncertainty" in families and uncertainty_method_config and uncertainty_method_config.get("method"):
                uncertainty_compare = run_method_compare(
                    method_family="uncertainty",
                    selected_method=str(uncertainty_method_config.get("method", "")),
                    methods_to_run=method_compare_config.get("uncertainty_methods", ["mann_lenschow", "finkelstein_sims"]),
                    method_configs={
                        "mann_lenschow": {
                            "integral_timescale_s": uncertainty_method_config.get("integral_timescale_s"),
                        }
                    },
                    window_params={
                        "cov_w_scalar": flux_metrics["cov_w_co2"],
                        "var_w": float(np.var(rotation.w)) if rotation.w.size > 1 else 0.0,
                        "var_scalar": float(np.var(lagged_co2)) if lagged_co2.size > 1 else 0.0,
                        "n_samples": prepared.sample_count,
                        "averaging_period_s": averaging_period_s,
                        "sample_rate_hz": sample_rate_hz,
                        "integral_timescale_s": uncertainty_method_config.get("integral_timescale_s"),
                        "w_series": rotation.w,
                        "scalar_series": lagged_co2,
                        "max_compare_samples": int(method_compare_config.get("max_samples", 4096) or 4096),
                    },
                )
                compare_payload["uncertainty"] = asdict(uncertainty_compare)
            if "spectral_correction" in families and spectral_correction_config and spectral_correction_config.get("enabled", False):
                spectral_compare = run_method_compare(
                    method_family="spectral_correction",
                    selected_method=str(spectral_correction_config.get("method", "")),
                    methods_to_run=method_compare_config.get("spectral_correction_methods", ["massman", "horst", "ibrom", "fratini"]),
                    window_params={
                        "path_length_m": spectral_correction_config.get("path_length_m", 0.15),
                        "sensor_sep_m": spectral_correction_config.get("sensor_sep_m", 0.20),
                        "response_time_s": spectral_correction_config.get("response_time_s", 0.1),
                        "sample_rate_hz": sample_rate_hz,
                        "averaging_period_s": averaging_period_s,
                        "wind_speed": float(np.mean(rotation.u)) if rotation.u.size > 0 else 0.0,
                        "z_m": spectral_correction_config.get("z_m", 0.0),
                        "ustar": turbulence.ustar or 0.0,
                        "ol": spectral_correction_config.get("ol"),
                        "measured_cospectrum_freq": measured_cospectrum_freq,
                        "measured_cospectrum_value": measured_cospectrum_value,
                    },
                )
                compare_payload["spectral_correction"] = asdict(spectral_compare)
            for family, result in compare_payload.items():
                if isinstance(result, dict):
                    recommendation = str(result.get("recommendation", ""))
                    if recommendation:
                        recommendations[family] = recommendation
                    for method_name, deviation in dict(result.get("deviations", {}) or {}).items():
                        if isinstance(deviation, (int, float)) and abs(float(deviation)) > deviation_threshold:
                            deviation_flags.append(
                                {
                                    "family": family,
                                    "method": method_name,
                                    "relative_deviation": round(float(deviation), 6),
                                    "threshold": deviation_threshold,
                                }
                            )
            diagnostics["method_compare_enabled"] = True
            diagnostics["method_compare_summary"] = compare_payload
            diagnostics["method_compare_recommendations"] = recommendations
            diagnostics["method_compare_deviation_flags"] = deviation_flags
            performance_sections["method_compare_ms"] = round((time.perf_counter() - section_start) * 1000.0, 3)
        diagnostics["performance_profile"] = {
            "window_elapsed_ms": round((time.perf_counter() - window_timer_start) * 1000.0, 3),
            "sections_ms": performance_sections,
            "sample_count": int(prepared.sample_count),
            "sample_rate_hz": float(sample_rate_hz),
            "method_compare_enabled": bool(method_compare_config and method_compare_config.get("enabled", False)),
            "footprint_2d_enabled": bool(footprint_config and footprint_config.get("enabled", False) and footprint_config.get("grid_enabled", True)),
        }
        return WindowRPResult(
            window_id=f"{run_id}_w{window_index:03d}",
            start_time=rows[0].timestamp,
            end_time=rows[-1].timestamp,
            sample_count=prepared.sample_count,
            valid_sample_count=prepared.valid_sample_count,
            continuity_ratio=float(prepared.continuity_ratio),
            missing_ratio=float(prepared.missing_ratio),
            rotation_mode=rotation.mode,
            detrend_mode=detrend_mode,
            lag_seconds=float(lag_result.lag_seconds),
            lag_confidence=float(lag_result.confidence),
            cov_w_co2=float(flux_metrics["cov_w_co2"]),
            cov_w_h2o=float(flux_metrics["cov_w_h2o"]),
            raw_flux=float(flux_metrics["raw_flux"]),
            mixing_ratio_flux=float(flux_metrics["mixing_ratio_flux"]),
            density_corrected_flux=float(flux_metrics["density_corrected_flux"]),
            primary_flux=float(flux_metrics["primary_flux"]),
            primary_flux_source=str(flux_metrics.get("density_correction_mode", "wpl")),
            water_vapor_flux=float(flux_metrics["water_vapor_flux"]),
            air_molar_density=float(flux_metrics["air_molar_density"]),
            dry_air_molar_density=float(flux_metrics["dry_air_molar_density"]),
            mean_co2_ppm=float(np.mean(lagged_co2)),
            mean_h2o_mmol=float(np.mean(lagged_h2o)),
            mean_pressure_kpa=float(np.mean(prepared.pressure_kpa)),
            mean_temp_c=float(np.mean(prepared.temp_c)),
            qc_score=float(qc["qc_score"]),
            stationarity_score=stationarity.score,
            turbulence_score=turbulence.score,
            ustar=turbulence.ustar,
            qc_grade=str(qc["qc_grade"]),
            anomaly_type=str(qc["anomaly_type"]),
            reason=str(qc["reason"]),
            qc_matrix=dict(qc["qc_matrix"]),
            qc_flags=[str(item) for item in qc.get("qc_flags", [])],
            qc_reasons=[str(item) for item in qc.get("qc_reasons", [])],
            stationarity_detail=dict(stationarity.detail),
            turbulence_detail=dict(turbulence.detail),
            uncertainty_detail=dict(uncertainty.detail),
            diagnostics=diagnostics,
        )


def _config_value(config: dict[str, Any], *paths: str, default: Any) -> Any:
    for path in paths:
        current: Any = config
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current
    return default


def _prepare_window_series(
    rows: list[NormalizedHFFrame],
    sample_rate_hz: float,
    sonic_correction_config: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any]]:
    prepared = build_window_series(rows, sample_rate_hz)
    sonic_result = apply_sonic_corrections(prepared.u, prepared.v, prepared.w, sonic_correction_config)
    if sonic_result.detail.get("applied"):
        prepared.u = sonic_result.u
        prepared.v = sonic_result.v
        prepared.w = sonic_result.w
    prepared.diagnostics["sonic_correction_status"] = sonic_result.detail.get("status", "")
    prepared.diagnostics["sonic_correction_method"] = sonic_result.detail.get("method", "")
    prepared.diagnostics["sonic_correction_detail"] = sonic_result.detail
    return prepared, sonic_result.detail


def _density_correction_factor(*, raw_flux: float, density_corrected_flux: float) -> float:
    if abs(raw_flux) <= 1e-12:
        return 1.0 if abs(density_corrected_flux) <= 1e-12 else 1.5
    return float(density_corrected_flux / raw_flux)


def _build_biomet_context(config: dict[str, Any]) -> dict[str, Any]:
    metadata_payload = config.get("metadata_bundle", {})
    if not isinstance(metadata_payload, dict):
        return {}
    biomet_payload = metadata_payload.get("biomet", {})
    if not isinstance(biomet_payload, dict):
        return {}
    source = BiometSourceMetadata(
        source_mode=str(biomet_payload.get("source_mode", "none")),
        source_path=str(biomet_payload.get("source_path", "")),
        time_column=str(biomet_payload.get("time_column", "timestamp")),
        aggregation_method=str(biomet_payload.get("aggregation_method", "mean")),
        fields=_coerce_string_list(biomet_payload.get("fields", [])),
        directory_glob=str(biomet_payload.get("directory_glob", "*.csv")),
        notes=str(biomet_payload.get("notes", "")),
        extra=dict(biomet_payload.get("extra", {}) if isinstance(biomet_payload.get("extra", {}), dict) else {}),
    )
    if source.source_mode == "none" or not source.source_path:
        return {}
    records = load_biomet_records(source)
    if not records:
        return {}
    fields = source.fields or [
        "ta",
        "air_temperature",
        "temperature",
        "temp",
        "chamber_temp_c",
        "pressure_kpa",
        "pressure",
        "pa",
        "air_pressure",
    ]
    return {"source": source, "records": records, "fields": fields}


def _biomet_override_for_rows(rows: list[NormalizedHFFrame], context: dict[str, Any]) -> dict[str, Any]:
    if not rows or not context:
        return {}
    source = context.get("source")
    records = list(context.get("records", []) or [])
    fields = list(context.get("fields", []) or [])
    if not records or not fields or not isinstance(source, BiometSourceMetadata):
        return {}
    aggregated = aggregate_biomet_window(
        records,
        window_start=rows[0].timestamp,
        window_end=rows[-1].timestamp,
        fields=fields,
        aggregation_method=source.aggregation_method,
    )
    if not aggregated:
        return {}
    return {
        "source_mode": source.source_mode,
        "source_path": source.source_path,
        "aggregation_method": source.aggregation_method,
        "window_start": rows[0].timestamp.isoformat(),
        "window_end": rows[-1].timestamp.isoformat(),
        "fields": fields,
        "aggregated": aggregated,
    }


def _apply_biomet_override(prepared: Any, override: dict[str, Any]) -> None:
    aggregated = dict(override.get("aggregated", {}) or {})
    pressure = _pick_numeric(aggregated, ("pressure_kpa", "pressure", "pa", "air_pressure"))
    temperature = _pick_numeric(aggregated, ("ta", "air_temperature", "temperature", "temp", "chamber_temp_c"))
    applied_fields: list[str] = []
    if pressure is not None and prepared.pressure_kpa.size:
        prepared.pressure_kpa = np.full_like(prepared.pressure_kpa, _coerce_pressure_kpa(pressure), dtype=float)
        _prune_prepared_issue(prepared, "pressure_kpa")
        applied_fields.append("pressure_kpa")
    if temperature is not None and prepared.temp_c.size:
        prepared.temp_c = np.full_like(prepared.temp_c, _coerce_temperature_c(temperature), dtype=float)
        _prune_prepared_issue(prepared, "temp_c")
        applied_fields.append("temp_c")
    if applied_fields:
        prepared.diagnostics["biomet_override"] = {
            "status": "applied",
            "applied_fields": applied_fields,
            "source_mode": override.get("source_mode", ""),
            "source_path": override.get("source_path", ""),
            "aggregation_method": override.get("aggregation_method", ""),
            "sample_count": aggregated.get("sample_count", 0),
            "window_start": override.get("window_start", ""),
            "window_end": override.get("window_end", ""),
        }


def _pick_numeric(payload: dict[str, Any], aliases: tuple[str, ...]) -> float | None:
    lookup = {str(key).lower(): value for key, value in payload.items()}
    for alias in aliases:
        value = lookup.get(alias.lower())
        if isinstance(value, (int, float)):
            return float(value)
        if value not in (None, ""):
            try:
                return float(str(value))
            except ValueError:
                continue
    return None


def _coerce_pressure_kpa(value: float) -> float:
    if value > 2000.0:
        return value / 1000.0
    if value > 200.0:
        return value / 10.0
    return value


def _coerce_temperature_c(value: float) -> float:
    return value - 273.15 if value > 150.0 else value


def _prune_prepared_issue(prepared: Any, field_prefix: str) -> None:
    prepared.issues = [issue for issue in prepared.issues if not str(issue).startswith(f"{field_prefix}_")]
    prepared.qc_reasons = [reason for reason in prepared.qc_reasons if field_prefix not in str(reason)]


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _failed_window_result(
    *,
    run_id: str,
    window_index: int,
    rows: list[NormalizedHFFrame],
    rotation_mode: str,
    detrend_mode: str,
    reason: str,
    clock_sync_summary: dict[str, Any] | None = None,
) -> WindowRPResult:
    start_time = rows[0].timestamp if rows else datetime.now()
    end_time = rows[-1].timestamp if rows else start_time
    return WindowRPResult(
        window_id=f"{run_id}_w{window_index:03d}",
        start_time=start_time,
        end_time=end_time,
        sample_count=len(rows),
        valid_sample_count=0,
        continuity_ratio=0.0,
        missing_ratio=1.0,
        rotation_mode=rotation_mode,
        detrend_mode=detrend_mode,
        lag_seconds=0.0,
        lag_confidence=0.0,
        cov_w_co2=0.0,
        cov_w_h2o=0.0,
        raw_flux=0.0,
            mixing_ratio_flux=0.0,
            density_corrected_flux=0.0,
            primary_flux=0.0,
            primary_flux_source="",
            water_vapor_flux=0.0,
        air_molar_density=0.0,
        dry_air_molar_density=0.0,
        mean_co2_ppm=0.0,
        mean_h2o_mmol=0.0,
        mean_pressure_kpa=0.0,
        mean_temp_c=0.0,
        qc_score=0.0,
        stationarity_score=None,
        turbulence_score=None,
        ustar=None,
        qc_grade="C",
        anomaly_type="processing_error",
        reason=reason,
        qc_matrix={},
        qc_flags=["processing_error"],
        qc_reasons=[reason],
        stationarity_detail={"status": "processing_error", "reason": reason},
        turbulence_detail={"status": "processing_error", "reason": reason},
        uncertainty_detail={"status": "placeholder", "reason": reason},
        diagnostics={
            "issues": ["processing_error"],
            "qc_reasons": [reason],
            **clock_sync_diagnostics(clock_sync_summary),
        },
    )


def _summarize_trace_gas_windows(windows: list[WindowRPResult]) -> dict[str, Any]:
    if not windows:
        return {
            "status": "not_available",
            "ch4_window_count": 0,
            "ch4_computed_window_count": 0,
            "average_ch4_flux_nmol_m2_s": None,
            "average_ch4_level0_flux_nmol_m2_s": None,
            "method": "not_available",
            "coefficient_profile_id": "",
            "coefficient_registry_status": "",
            "coefficient_profile_source_file": "",
            "coefficient_profile_provenance": "",
            "provenance": "",
            "limitations": [],
        }
    diagnostics = [dict(window.diagnostics or {}) for window in windows]
    computed = [
        diag
        for diag in diagnostics
        if diag.get("ch4_status") == "computed" and isinstance(diag.get("ch4_flux_nmol_m2_s"), (int, float))
    ]
    level0 = [
        diag
        for diag in diagnostics
        if isinstance(diag.get("ch4_flux_level0_nmol_m2_s"), (int, float))
    ]
    first = next((diag for diag in diagnostics if diag.get("ch4_method")), diagnostics[0])
    return {
        "status": "computed" if computed else "not_available",
        "ch4_window_count": len(windows),
        "ch4_computed_window_count": len(computed),
        "average_ch4_flux_nmol_m2_s": (
            sum(float(diag["ch4_flux_nmol_m2_s"]) for diag in computed) / len(computed)
            if computed
            else None
        ),
        "average_ch4_level0_flux_nmol_m2_s": (
            sum(float(diag["ch4_flux_level0_nmol_m2_s"]) for diag in level0) / len(level0)
            if level0
            else None
        ),
        "method": first.get("ch4_method", "not_available"),
        "correction_sequence": first.get("ch4_correction_sequence", {}),
        "coefficient_profile_id": first.get("ch4_coefficient_profile_id", ""),
        "coefficient_registry_status": first.get("ch4_coefficient_registry_status", ""),
        "coefficient_profile_label": first.get("ch4_coefficient_profile_label", ""),
        "coefficient_profile_source_file": first.get("ch4_coefficient_source_file", ""),
        "coefficient_profile_normalization_command": first.get("ch4_coefficient_normalization_command", ""),
        "coefficient_profile_provenance": first.get("ch4_coefficient_profile_provenance", ""),
        "coefficient_profile_limitations": list(first.get("ch4_coefficient_profile_limitations", []) or []),
        "provenance": first.get("ch4_provenance", ""),
        "limitations": list(first.get("ch4_limitations", []) or []),
    }


def _empty_summary(
    *,
    sample_rate_hz: float,
    message: str,
    project: ProjectProfile,
    site: SiteProfile,
    config: dict[str, Any],
    benchmark_summary: dict[str, Any] | None = None,
    reference_provenance: dict[str, Any] | None = None,
    network_output_config: dict[str, Any] | None = None,
    method_summary: dict[str, Any] | None = None,
    clock_sync_summary: dict[str, Any] | None = None,
    performance_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "status": "empty",
        "message": message,
        "sample_rate_hz": float(sample_rate_hz),
        "window_count": 0,
        "valid_window_count": 0,
        "good_window_count": 0,
        "attention_window_count": 0,
        "average_qc_score": 0.0,
        "average_stationarity_score": 0.0,
        "average_turbulence_score": 0.0,
        "average_ustar": 0.0,
        "trace_gas_summary": {
            "status": "not_available",
            "ch4_window_count": 0,
            "ch4_computed_window_count": 0,
            "average_ch4_flux_nmol_m2_s": None,
            "average_ch4_level0_flux_nmol_m2_s": None,
            "method": "not_available",
            "coefficient_profile_id": "",
            "coefficient_registry_status": "",
            "coefficient_profile_source_file": "",
            "coefficient_profile_provenance": "",
        },
        "project_code": project.code,
        "site_code": site.station_code,
        "config_snapshot": config,
    }
    return _with_summary_context(
        summary=summary,
        benchmark_summary=benchmark_summary or {},
        reference_provenance=reference_provenance or {},
        network_output_config=network_output_config or {},
        method_summary=method_summary or {},
        clock_sync_summary=clock_sync_summary or {},
        performance_profile=performance_profile or {},
    )


def _build_summary(
    *,
    windows: list[WindowRPResult],
    sample_rate_hz: float,
    project: ProjectProfile,
    site: SiteProfile,
    config: dict[str, Any],
    benchmark_summary: dict[str, Any] | None = None,
    reference_provenance: dict[str, Any] | None = None,
    network_output_config: dict[str, Any] | None = None,
    method_summary: dict[str, Any] | None = None,
    clock_sync_summary: dict[str, Any] | None = None,
    performance_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not windows:
        return _empty_summary(
            sample_rate_hz=sample_rate_hz,
            message="No RP windows were produced.",
            project=project,
            site=site,
            config=config,
            benchmark_summary=benchmark_summary,
            reference_provenance=reference_provenance,
            network_output_config=network_output_config,
            method_summary=method_summary,
            clock_sync_summary=clock_sync_summary,
            performance_profile=performance_profile,
        )
    summary = {
        "status": "ok",
        "message": "Minimal RP pipeline completed.",
        "sample_rate_hz": float(sample_rate_hz),
        "window_count": len(windows),
        "valid_window_count": sum(1 for window in windows if window.qc_grade in {"A", "B"}),
        "good_window_count": sum(1 for window in windows if window.qc_grade == "A"),
        "attention_window_count": sum(1 for window in windows if window.qc_grade in {"B", "C"}),
        "average_lag_seconds": float(np.mean([window.lag_seconds for window in windows])),
        "average_lag_confidence": float(np.mean([window.lag_confidence for window in windows])),
        "average_raw_flux": float(np.mean([window.raw_flux for window in windows])),
        "average_density_corrected_flux": float(np.mean([window.density_corrected_flux for window in windows])),
        "average_qc_score": float(np.mean([window.qc_score for window in windows])),
        "average_stationarity_score": float(np.mean([window.stationarity_score or 0.0 for window in windows])),
        "average_turbulence_score": float(np.mean([window.turbulence_score or 0.0 for window in windows])),
        "average_ustar": float(np.mean([window.ustar or 0.0 for window in windows])),
        "trace_gas_summary": _summarize_trace_gas_windows(windows),
        "project_code": project.code,
        "site_code": site.station_code,
        "config_snapshot": config,
    }
    return _with_summary_context(
        summary=summary,
        benchmark_summary=benchmark_summary or {},
        reference_provenance=reference_provenance or {},
        network_output_config=network_output_config or {},
        method_summary=method_summary or {},
        clock_sync_summary=clock_sync_summary or {},
        performance_profile=performance_profile or {},
    )


def _artifacts(
    *,
    project: ProjectProfile,
    site: SiteProfile,
    config: dict[str, Any],
    sample_rate_hz: float,
    window_count: int,
    benchmark_summary: dict[str, Any] | None = None,
    reference_provenance: dict[str, Any] | None = None,
    network_output_config: dict[str, Any] | None = None,
    method_summary: dict[str, Any] | None = None,
    clock_sync_summary: dict[str, Any] | None = None,
    performance_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "project_snapshot": asdict(project),
        "site_snapshot": asdict(site),
        "config_snapshot": config,
        "sample_rate_hz": float(sample_rate_hz),
        "window_count": int(window_count),
        "benchmark": benchmark_summary or {},
        "reference_provenance": reference_provenance or {},
        "network_output": network_output_config or {},
        "method_rollup": method_summary or {},
        "method_provenance": method_summary or {},
        "clock_sync": clock_sync_summary or {},
        "performance_profile": performance_profile or {},
    }


def _extract_screening_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract screening parameters from config, supporting multiple path conventions."""
    sc: dict[str, Any] = {}
    for key, default in [
        ("skewness_threshold", 2.0),
        ("kurtosis_threshold", 7.0),
        ("dropout_min_run", 10),
        ("spike_sigma", 5.0),
        ("discontinuity_sigma", 8.0),
    ]:
        value = _config_value(config, f"screening.{key}", f"steps.screening.{key}", default=default)
        sc[key] = value
    absolute_limits = _config_value(config, "screening.absolute_limits", "steps.screening.absolute_limits", default=None)
    if absolute_limits is not None:
        sc["absolute_limits"] = absolute_limits
    return sc


def _extract_advanced_test_config(config: dict[str, Any]) -> dict[str, Any]:
    atc: dict[str, Any] = {}
    for key, default in [
        ("amplitude_resolution_ratio_threshold", 10.0),
        ("amplitude_resolution_resolution", None),
        ("time_lag_max_lag_s", 5.0),
        ("time_lag_confidence_threshold", 0.4),
        ("angle_of_attack_max_angle_deg", 40.0),
        ("steadiness_cv_threshold", 0.50),
    ]:
        value = _config_value(config, f"advanced_tests.{key}", f"steps.advanced_tests.{key}", default=default)
        atc[key] = value
    return atc


def _extract_footprint_config(config: dict[str, Any]) -> dict[str, Any]:
    fc: dict[str, Any] = {}
    for key, default in [
        ("enabled", False),
        ("method", "kljun"),
        ("z_m", 0.0),
        ("canopy_height_m", 0.0),
        ("z0", None),
        ("ol", None),
        ("grid_enabled", True),
        ("grid_x_bins", 32),
        ("grid_y_bins", 25),
        ("grid_max_downwind_m", None),
        ("grid_max_crosswind_m", None),
    ]:
        value = _config_value(config, f"footprint.{key}", f"steps.footprint.{key}", default=default)
        fc[key] = value
    return fc


def _extract_method_compare_config(config: dict[str, Any]) -> dict[str, Any]:
    mc = config.get("method_compare", {})
    if not isinstance(mc, dict):
        mc = {}
    steps_mc = config.get("steps", {}).get("method_compare", {}) if isinstance(config.get("steps"), dict) else {}
    if isinstance(steps_mc, dict):
        mc = {**steps_mc, **mc}

    def _method_list(key: str, default: list[str]) -> list[str]:
        value = mc.get(key, default)
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return list(default)

    families = _method_list("families", ["footprint", "uncertainty", "spectral_correction"])
    return {
        "enabled": bool(mc.get("enabled", False)),
        "families": families,
        "deviation_threshold": float(mc.get("deviation_threshold", 0.25) or 0.25),
        "max_samples": int(mc.get("max_samples", 4096) or 4096),
        "footprint_methods": _method_list("footprint_methods", ["kljun", "kormann_meixner", "hsieh"]),
        "uncertainty_methods": _method_list("uncertainty_methods", ["mann_lenschow", "finkelstein_sims"]),
        "spectral_correction_methods": _method_list("spectral_correction_methods", ["massman", "horst", "ibrom", "fratini"]),
    }


def _extract_uncertainty_method_config(config: dict[str, Any]) -> dict[str, Any]:
    uc: dict[str, Any] = {}
    for key, default in [
        ("method", ""),
        ("integral_timescale_s", None),
        ("confidence_level", 0.95),
    ]:
        value = _config_value(config, f"uncertainty.{key}", f"steps.uncertainty.{key}", default=default)
        uc[key] = value
    return uc


def _extract_spectral_correction_config(config: dict[str, Any]) -> dict[str, Any]:
    sc: dict[str, Any] = {}
    for key, default in [
        ("enabled", False),
        ("method", "massman"),
        ("path_length_m", 0.15),
        ("sensor_sep_m", 0.20),
        ("response_time_s", 0.1),
        ("z_m", 0.0),
        ("ol", None),
        ("use_fcc_measured_cospectrum", False),
        ("fcc_source_run_id", ""),
    ]:
        value = _config_value(config, f"spectral_correction.{key}", f"steps.spectral_correction.{key}", default=default)
        sc[key] = value
    measured = _config_value(
        config,
        "spectral_correction.fcc_measured_cospectra",
        "steps.spectral_correction.fcc_measured_cospectra",
        default=[],
    )
    sc["fcc_measured_cospectra"] = list(measured) if isinstance(measured, list) else []
    return sc


def _extract_sonic_correction_config(config: dict[str, Any]) -> dict[str, Any]:
    steps = config.get("steps", {}) if isinstance(config.get("steps"), dict) else {}
    sonic = dict(steps.get("sonic_correction", {}) or {}) if isinstance(steps.get("sonic_correction", {}), dict) else {}
    root = config.get("sonic_correction", {})
    if isinstance(root, dict):
        sonic = {**sonic, **root}
    metadata = config.get("metadata_bundle", {})
    instruments = metadata.get("instruments", {}) if isinstance(metadata, dict) else {}
    extra = instruments.get("extra", {}) if isinstance(instruments, dict) else {}
    if isinstance(instruments, dict):
        sonic.setdefault("sonic_model", instruments.get("sonic_model", ""))
        sonic.setdefault("sonic_firmware", instruments.get("sonic_firmware", ""))
        sonic.setdefault("sonic_manufacturer", instruments.get("sonic_manufacturer", ""))
    if isinstance(extra, dict):
        for source_key, target_key in [
            ("sonic_wind_format", "wind_format"),
            ("sonic_wind_reference", "wind_reference"),
            ("sonic_north_offset_deg", "north_offset_deg"),
            ("sonic_u_offset_ms", "u_offset_ms"),
            ("sonic_v_offset_ms", "v_offset_ms"),
            ("sonic_w_offset_ms", "w_offset_ms"),
            ("gill_wm_w_boost", "gill_wm_w_boost"),
        ]:
            if source_key in extra and target_key not in sonic:
                sonic[target_key] = extra[source_key]
    sonic.setdefault("enabled", False)
    sonic.setdefault("method", "eddypro_sonic_coordinate_v1")
    sonic.setdefault("wind_format", "cartesian")
    sonic.setdefault("wind_reference", "")
    sonic.setdefault("apply_model_orientation", True)
    sonic.setdefault("north_offset_deg", 0.0)
    sonic.setdefault("u_offset_ms", 0.0)
    sonic.setdefault("v_offset_ms", 0.0)
    sonic.setdefault("w_offset_ms", 0.0)
    sonic.setdefault("gill_wm_w_boost", "auto")
    return sonic


def _extract_crosswind_correction_config(config: dict[str, Any]) -> dict[str, Any]:
    steps = config.get("steps", {}) if isinstance(config.get("steps"), dict) else {}
    crosswind = (
        dict(steps.get("crosswind_correction", {}) or {})
        if isinstance(steps.get("crosswind_correction", {}), dict)
        else {}
    )
    root = config.get("crosswind_correction", {})
    if isinstance(root, dict):
        crosswind = {**crosswind, **root}
    metadata = config.get("metadata_bundle", {})
    instruments = metadata.get("instruments", {}) if isinstance(metadata, dict) else {}
    extra = instruments.get("extra", {}) if isinstance(instruments, dict) else {}
    if isinstance(instruments, dict):
        crosswind.setdefault("sonic_model", instruments.get("sonic_model", ""))
        crosswind.setdefault("sonic_manufacturer", instruments.get("sonic_manufacturer", ""))
    if isinstance(extra, dict):
        for source_key, target_key in [
            ("crosswind_enabled", "enabled"),
            ("crosswind_temperature_divisor", "temperature_divisor"),
            ("crosswind_coefficients", "coefficients"),
        ]:
            if source_key in extra and target_key not in crosswind:
                crosswind[target_key] = extra[source_key]
    crosswind.setdefault("enabled", False)
    crosswind.setdefault("method", "liu_2001_crosswind_v1")
    crosswind.setdefault("temperature_divisor", 1209.0)
    return crosswind


def _extract_trace_gas_config(config: dict[str, Any]) -> dict[str, Any]:
    trace = dict(config.get("trace_gas", {}) or {}) if isinstance(config.get("trace_gas", {}), dict) else {}
    steps_trace = config.get("steps", {}).get("trace_gas", {}) if isinstance(config.get("steps"), dict) else {}
    if isinstance(steps_trace, dict):
        trace = {**steps_trace, **trace}
    ch4 = dict(trace.get("ch4", {}) or {}) if isinstance(trace.get("ch4", {}), dict) else {}
    li7700 = dict(trace.get("li7700", {}) or {}) if isinstance(trace.get("li7700", {}), dict) else {}
    ch4 = {**li7700, **ch4}
    coefficient_resolution = _resolve_li7700_coefficient_profile(
        config=config,
        trace=trace,
        li7700=li7700,
        ch4=ch4,
    )
    profile_config = _li7700_profile_to_ch4_config(coefficient_resolution.get("profile", {}))
    ch4 = _merge_nested_dict(profile_config, ch4)
    ch4.setdefault("enabled", True)
    ch4.setdefault("method", "li_7700_correction_sequence_v1")
    ch4.setdefault("apply_water_vapor_dilution", True)
    ch4.setdefault("use_spectral_correction_factor", True)
    if "spectroscopic_correction" not in ch4:
        ch4["spectroscopic_correction"] = {"mode": "input_corrected"}
    if "self_heating_correction" not in ch4:
        ch4["self_heating_correction"] = {"mode": "not_configured"}
    ch4["coefficient_profile_id"] = coefficient_resolution.get("profile_id", "")
    ch4["coefficient_registry_status"] = coefficient_resolution.get("status", "")
    ch4["coefficient_profile_label"] = coefficient_resolution.get("label", "")
    ch4["coefficient_profile_source"] = coefficient_resolution.get("source", "")
    ch4["coefficient_profile_source_file"] = coefficient_resolution.get("source_file", "")
    ch4["coefficient_profile_normalization_command"] = coefficient_resolution.get("normalization_command", "")
    ch4["coefficient_profile_provenance"] = coefficient_resolution.get("provenance", "")
    ch4["coefficient_profile_limitations"] = list(coefficient_resolution.get("known_limitations", []) or [])
    ch4["coefficient_profile"] = coefficient_resolution.get("profile", {})
    return {"ch4": ch4, "coefficient_registry": {"li7700": coefficient_resolution}}


def _resolve_li7700_coefficient_profile(
    *,
    config: dict[str, Any],
    trace: dict[str, Any],
    li7700: dict[str, Any],
    ch4: dict[str, Any],
) -> dict[str, Any]:
    registry = _collect_li7700_coefficient_profiles(config=config, trace=trace, li7700=li7700, ch4=ch4)
    profile_id = _selected_li7700_profile_id(config=config, trace=trace, li7700=li7700, ch4=ch4)
    status = "resolved"
    if not profile_id:
        profile_id = "li7700_factory_compensated"
        status = "builtin_default"
    profile = dict(registry.get(str(profile_id), {}) or {})
    if not profile:
        return {
            "profile_id": str(profile_id),
            "status": "profile_not_found",
            "label": "",
            "source": "",
            "source_file": "",
            "normalization_command": "",
            "provenance": f"LI-7700 coefficient profile '{profile_id}' was requested but not found.",
            "known_limitations": ["Requested LI-7700 coefficient profile was not found; conservative defaults were used."],
            "available_profile_ids": sorted(registry),
            "profile": {},
        }
    profile.setdefault("profile_id", str(profile_id))
    profile.setdefault("label", str(profile_id))
    profile.setdefault("source", "custom")
    profile.setdefault("source_file", "")
    profile.setdefault("normalization_command", "")
    profile.setdefault("provenance", f"LI-7700 coefficient profile '{profile_id}' resolved from coefficient registry.")
    limitations = profile.get("known_limitations", profile.get("limitations", []))
    if isinstance(limitations, str):
        limitations = [limitations]
    return {
        "profile_id": str(profile.get("profile_id", profile_id)),
        "status": status,
        "label": str(profile.get("label", profile_id)),
        "source": str(profile.get("source", "")),
        "source_file": str(profile.get("source_file", "")),
        "normalization_command": str(profile.get("normalization_command", "")),
        "provenance": str(profile.get("provenance", "")),
        "known_limitations": [str(item) for item in limitations if str(item)],
        "available_profile_ids": sorted(registry),
        "profile": profile,
    }


def _selected_li7700_profile_id(
    *,
    config: dict[str, Any],
    trace: dict[str, Any],
    li7700: dict[str, Any],
    ch4: dict[str, Any],
) -> str:
    for payload in (ch4, li7700, trace):
        for key in ("coefficient_profile_id", "coefficient_profile", "profile_id", "li7700_profile_id"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, dict):
                value = value.get("profile_id", value.get("id", value.get("coefficient_profile_id", "")))
            if value not in (None, ""):
                return str(value)
    metadata = config.get("metadata_bundle", {})
    instruments = metadata.get("instruments", {}) if isinstance(metadata, dict) else {}
    extra = instruments.get("extra", {}) if isinstance(instruments, dict) else {}
    for payload in (extra, instruments):
        if not isinstance(payload, dict):
            continue
        for key in ("ch4_coefficient_profile_id", "li7700_coefficient_profile_id", "coefficient_profile_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _collect_li7700_coefficient_profiles(
    *,
    config: dict[str, Any],
    trace: dict[str, Any],
    li7700: dict[str, Any],
    ch4: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {
        key: dict(value) for key, value in LI7700_BUILTIN_COEFFICIENT_PROFILES.items()
    }
    metadata = config.get("metadata_bundle", {})
    instruments = metadata.get("instruments", {}) if isinstance(metadata, dict) else {}
    extra = instruments.get("extra", {}) if isinstance(instruments, dict) else {}
    containers = [
        config.get("trace_gas_coefficient_registry"),
        config.get("coefficient_registry"),
        trace.get("coefficient_registry"),
        trace.get("li7700_coefficient_registry"),
        trace.get("coefficient_profile"),
        li7700.get("coefficient_registry"),
        li7700.get("coefficient_profile"),
        ch4.get("coefficient_registry"),
        ch4.get("coefficient_profile"),
        instruments.get("trace_gas_coefficient_registry") if isinstance(instruments, dict) else None,
        instruments.get("li7700_coefficient_registry") if isinstance(instruments, dict) else None,
        extra.get("trace_gas_coefficient_registry") if isinstance(extra, dict) else None,
        extra.get("li7700_coefficient_registry") if isinstance(extra, dict) else None,
    ]
    for container in containers:
        for profile_id, profile in _iter_li7700_registry_profiles(container):
            if profile_id:
                profiles[str(profile_id)] = profile
    return profiles


def _iter_li7700_registry_profiles(container: Any) -> list[tuple[str, dict[str, Any]]]:
    if not container:
        return []
    if isinstance(container, list):
        results: list[tuple[str, dict[str, Any]]] = []
        for item in container:
            if isinstance(item, dict):
                profile_id = str(item.get("profile_id", item.get("id", item.get("coefficient_profile_id", ""))))
                if profile_id:
                    profile = dict(item)
                    profile.setdefault("profile_id", profile_id)
                    results.append((profile_id, profile))
        return results
    if not isinstance(container, dict):
        return []
    if _looks_like_li7700_profile(container):
        profile_id = str(container.get("profile_id", container.get("id", container.get("coefficient_profile_id", ""))))
        if profile_id:
            profile = dict(container)
            profile.setdefault("profile_id", profile_id)
            return [(profile_id, profile)]
    results = []
    for key, value in container.items():
        if not isinstance(value, dict):
            continue
        if not _looks_like_li7700_profile(value) and any(isinstance(item, dict) for item in value.values()):
            results.extend(_iter_li7700_registry_profiles(value))
            continue
        profile = dict(value)
        profile_id = str(profile.get("profile_id", profile.get("id", profile.get("coefficient_profile_id", key))))
        profile.setdefault("profile_id", profile_id)
        results.append((profile_id, profile))
    return results


def _looks_like_li7700_profile(payload: dict[str, Any]) -> bool:
    profile_keys = {
        "profile_id",
        "coefficient_profile_id",
        "spectroscopic_correction",
        "self_heating_correction",
        "source_file",
        "normalization_command",
        "instrument_family",
    }
    return any(key in payload for key in profile_keys)


def _li7700_profile_to_ch4_config(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict) or not profile:
        return {}
    config: dict[str, Any] = {}
    for key in ("apply_water_vapor_dilution", "use_spectral_correction_factor", "spectral_correction_factor"):
        if key in profile:
            config[key] = profile[key]
    for key in ("spectroscopic_correction", "self_heating_correction"):
        value = profile.get(key)
        if isinstance(value, dict):
            config[key] = dict(value)
    return config


def _merge_nested_dict(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested_dict(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _extract_network_output_config(config: dict[str, Any]) -> dict[str, Any]:
    network = config.get("network_output", {})
    if not isinstance(network, dict):
        network = {}
    timestamp_refers_to = str(network.get("timestamp_refers_to", "start")).strip().lower()
    if "end" in timestamp_refers_to:
        timestamp_refers_to = "end"
    elif timestamp_refers_to not in {"start", "end"}:
        timestamp_refers_to = "start"
    return {
        "schema_target": str(network.get("schema_target", "")).strip(),
        "timezone_offset_hours": float(network.get("timezone_offset_hours", 0.0) or 0.0),
        "timestamp_refers_to": timestamp_refers_to,
        "gap_fill_value": float(network.get("gap_fill_value", -9999.0) or -9999.0),
    }


def _resolve_fcc_measured_cospectrum(
    *,
    window_start: datetime,
    window_end: datetime,
    spectral_correction_config: dict[str, Any] | None,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any]]:
    config = spectral_correction_config or {}
    candidates = config.get("fcc_measured_cospectra", [])
    if not config.get("use_fcc_measured_cospectrum") or not isinstance(candidates, list):
        return None, None, {
            "enabled": False,
            "used": False,
            "source": "disabled",
            "matched_window_id": "",
            "source_run_id": str(config.get("fcc_source_run_id", "")),
            "match_strategy": "disabled",
            "match_quality": 0.0,
            "frequency_count": 0,
        }

    matched: dict[str, Any] | None = None
    match_meta: dict[str, Any] = {}
    tolerance_s = float(config.get("fcc_match_tolerance_s", 2.0) or 2.0)
    nearest_tolerance_s = float(config.get("fcc_nearest_tolerance_s", 120.0) or 120.0)
    target_duration_s = max((window_end - window_start).total_seconds(), 1.0)
    target_center = window_start + (window_end - window_start) / 2
    for item in candidates:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(str(item.get("start_time", "")))
            end = datetime.fromisoformat(str(item.get("end_time", "")))
        except ValueError:
            continue
        candidate_duration_s = max((end - start).total_seconds(), 1.0)
        candidate_center = start + (end - start) / 2
        start_delta_s = abs((start - window_start).total_seconds())
        end_delta_s = abs((end - window_end).total_seconds())
        center_delta_s = abs((candidate_center - target_center).total_seconds())
        latest_start = max(start, window_start)
        earliest_end = min(end, window_end)
        overlap_seconds = max((earliest_end - latest_start).total_seconds(), 0.0)
        overlap_ratio = overlap_seconds / max(min(target_duration_s, candidate_duration_s), 1.0)
        strategy = "none"
        quality = 0.0
        if start_delta_s <= tolerance_s and end_delta_s <= tolerance_s:
            strategy = "exact_time"
            quality = 1.0
        elif overlap_seconds > 0.0:
            strategy = "overlap"
            quality = min(0.95, max(0.50, overlap_ratio))
        elif center_delta_s <= nearest_tolerance_s:
            strategy = "nearest"
            quality = max(0.10, 0.50 * (1.0 - center_delta_s / max(nearest_tolerance_s, 1.0)))
        if strategy == "none":
            continue
        if matched is None or quality > float(match_meta.get("match_quality", -1.0)):
            matched = item
            match_meta = {
                "match_strategy": strategy,
                "match_quality": round(float(quality), 4),
                "time_delta_s": round(float(center_delta_s), 3),
                "start_delta_s": round(float(start_delta_s), 3),
                "end_delta_s": round(float(end_delta_s), 3),
                "overlap_seconds": round(float(overlap_seconds), 3),
                "overlap_ratio": round(float(overlap_ratio), 4),
                "mismatch_warning": "" if quality >= 0.75 else "FCC/RP window timing mismatch is material; review match provenance.",
            }

    if matched is None:
        return None, None, {
            "enabled": True,
            "used": False,
            "source": "fcc_auto_no_match",
            "matched_window_id": "",
            "source_run_id": str(config.get("fcc_source_run_id", "")),
            "match_strategy": "none",
            "match_quality": 0.0,
            "frequency_count": 0,
            "fallback_reason": "no FCC cospectrum candidate matched RP window timing",
            "mismatch_warning": "No FCC measured cospectrum window matched this RP window.",
        }

    freq = np.asarray(matched.get("cross_freq", []), dtype=float)
    value = np.asarray(matched.get("cross_value", []), dtype=float)
    valid = np.isfinite(freq) & np.isfinite(value) & (freq > 0.0)
    if np.count_nonzero(valid) < 8:
        return None, None, {
            "enabled": True,
            "used": False,
            "source": "fcc_auto_insufficient",
            "matched_window_id": str(matched.get("window_id", "")),
            "source_run_id": str(matched.get("source_run_id", config.get("fcc_source_run_id", ""))),
            "frequency_count": int(np.count_nonzero(valid)),
            "source_qc_grade": str(matched.get("source_qc_grade", "")),
            "fallback_reason": "matched FCC cospectrum had fewer than 8 valid positive frequency bins",
            **match_meta,
        }

    return freq[valid], value[valid], {
        "enabled": True,
        "used": True,
        "source": "fcc_auto",
        "matched_window_id": str(matched.get("window_id", "")),
        "source_run_id": str(matched.get("source_run_id", config.get("fcc_source_run_id", ""))),
        "frequency_count": int(np.count_nonzero(valid)),
        "source_qc_grade": str(matched.get("source_qc_grade", "")),
        "provenance_notes": list(matched.get("provenance_notes", [])) if isinstance(matched.get("provenance_notes"), list) else [],
        **match_meta,
    }


def _propagate_uncertainty_to_primary_flux(
    *,
    primary_flux: float,
    flux_metrics: dict[str, float],
    uncertainty_detail: dict[str, Any],
    confidence_level: float,
) -> dict[str, Any]:
    cov_flux = float(flux_metrics.get("cov_w_co2", 0.0) or 0.0)
    flux_scale = abs(primary_flux / cov_flux) if abs(cov_flux) > 1e-15 else 0.0
    method_random_error = uncertainty_detail.get("random_error")
    if isinstance(method_random_error, (int, float)) and flux_scale > 0.0:
        primary_flux_random_error = abs(float(method_random_error)) * flux_scale
    elif isinstance(method_random_error, (int, float)):
        primary_flux_random_error = abs(float(method_random_error))
    else:
        relative_uncertainty = uncertainty_detail.get("relative_uncertainty", uncertainty_detail.get("relative_error"))
        primary_flux_random_error = (
            abs(primary_flux) * abs(float(relative_uncertainty))
            if isinstance(relative_uncertainty, (int, float))
            else None
        )

    relative_uncertainty = uncertainty_detail.get("relative_uncertainty", uncertainty_detail.get("relative_error"))
    if not isinstance(relative_uncertainty, (int, float)) and isinstance(primary_flux_random_error, (int, float)) and abs(primary_flux) > 1e-15:
        relative_uncertainty = primary_flux_random_error / abs(primary_flux)

    band = build_uncertainty_band(
        estimate=primary_flux,
        random_error=primary_flux_random_error if isinstance(primary_flux_random_error, (int, float)) else None,
        relative_uncertainty=relative_uncertainty if isinstance(relative_uncertainty, (int, float)) else None,
        confidence_level=confidence_level,
    )
    return {
        "primary_flux_random_error": round(float(primary_flux_random_error), 6) if isinstance(primary_flux_random_error, (int, float)) else None,
        "primary_flux_relative_uncertainty": round(float(relative_uncertainty), 4) if isinstance(relative_uncertainty, (int, float)) else None,
        "primary_flux_ci_level": band.get("confidence_level"),
        "primary_flux_uncertainty_band": band.get("uncertainty_band_half_width"),
        "primary_flux_ci_lower": band.get("interval_lower"),
        "primary_flux_ci_upper": band.get("interval_upper"),
    }


def _wpl_benchmark_status(flux_metrics: dict[str, float]) -> dict[str, Any]:
    wpl_wv = flux_metrics.get("wpl_water_vapor_term", 0.0)
    wpl_sh = flux_metrics.get("wpl_sensible_heat_term", 0.0)
    raw = flux_metrics.get("raw_flux", 0.0)
    corrected = flux_metrics.get("density_corrected_flux", 0.0)
    total_correction = wpl_wv + wpl_sh
    correction_ratio = abs(total_correction / raw) if abs(raw) > 1e-15 else 0.0
    sensible_heat_dominant = abs(wpl_sh) > abs(wpl_wv)
    sensible_heat_same_sign_as_total = (wpl_sh * total_correction) >= 0
    magnitude_reasonable = correction_ratio < 0.5
    status = "pass"
    notes = []
    if abs(wpl_sh) > 1e-15:
        if not sensible_heat_same_sign_as_total:
            status = "attention"
            notes.append("sensible_heat_term opposes total correction direction")
        if correction_ratio > 0.3:
            status = "attention"
            notes.append(f"total WPL correction ratio is large ({correction_ratio:.3f})")
    else:
        notes.append("sensible_heat_term is negligible")
    if not magnitude_reasonable:
        status = "fail"
        notes.append(f"total WPL correction ratio exceeds 0.5 ({correction_ratio:.3f})")
    return {
        "status": status,
        "wpl_water_vapor_term": wpl_wv,
        "wpl_sensible_heat_term": wpl_sh,
        "total_density_correction": total_correction,
        "correction_ratio": correction_ratio,
        "sensible_heat_dominant": sensible_heat_dominant,
        "sensible_heat_same_sign_as_total": sensible_heat_same_sign_as_total,
        "magnitude_reasonable": magnitude_reasonable,
        "notes": notes,
    }


def _extract_benchmark_config(config: dict[str, Any]) -> dict[str, Any]:
    bm = config.get("benchmark", {})
    return {
        "status": str(bm.get("status", "")),
        "target": str(bm.get("target", "")),
        "reference_id": str(bm.get("reference_id", "")),
        "flux_rel_threshold": float(bm.get("flux_rel_threshold", 0.10)),
        "lag_abs_threshold_s": float(bm.get("lag_abs_threshold_s", 0.5)),
        "wpl_rel_threshold": float(bm.get("wpl_rel_threshold", 0.20)),
        "qc_grade_must_match": bool(bm.get("qc_grade_must_match", False)),
    }


def _benchmark_thresholds(benchmark_config: dict[str, Any] | None) -> dict[str, Any]:
    config = benchmark_config or {}
    return {
        "flux_rel_threshold": float(config.get("flux_rel_threshold", 0.10)),
        "lag_abs_threshold_s": float(config.get("lag_abs_threshold_s", 0.5)),
        "wpl_rel_threshold": float(config.get("wpl_rel_threshold", 0.20)),
        "qc_grade_must_match": bool(config.get("qc_grade_must_match", False)),
    }


def _default_benchmark_summary(*, benchmark_config: dict[str, Any], window_count: int) -> dict[str, Any]:
    return {
        "status": "inactive" if benchmark_config.get("status") != "active" else "pending",
        "benchmark_status": benchmark_config.get("status", ""),
        "benchmark_target": benchmark_config.get("target", ""),
        "benchmark_reference_id": benchmark_config.get("reference_id", ""),
        "benchmark_thresholds": _benchmark_thresholds(benchmark_config),
        "benchmark_deviation_summary": {
            "window_count": int(window_count),
            "matched_window_count": 0,
            "pass_window_count": 0,
            "failed_window_count": 0,
            "missing_reference_window_count": int(window_count),
            "max_abs_error": 0.0,
            "max_rel_error": 0.0,
            "field_summary": {},
        },
        "pass_rate": 0.0,
        "failed_fields": [],
    }


def _summarize_benchmark_windows(*, windows: list[WindowRPResult], benchmark_config: dict[str, Any]) -> dict[str, Any]:
    summary = _default_benchmark_summary(benchmark_config=benchmark_config, window_count=len(windows))
    if benchmark_config.get("status") != "active":
        return summary

    field_summary: dict[str, dict[str, Any]] = {}
    failed_fields: set[str] = set()
    matched_window_count = 0
    pass_window_count = 0
    failed_window_count = 0
    missing_reference_window_count = 0
    max_abs_error = 0.0
    max_rel_error = 0.0
    reference_not_found = False

    for window in windows:
        diagnostics = window.diagnostics or {}
        deviation = diagnostics.get("benchmark_deviation_summary", {})
        if not deviation:
            missing_reference_window_count += 1
            continue
        if deviation.get("status") == "reference_not_found":
            reference_not_found = True
            missing_reference_window_count += 1
            continue
        if deviation.get("match_strategy") == "none":
            missing_reference_window_count += 1
        else:
            matched_window_count += 1
            if deviation.get("overall_pass", True):
                pass_window_count += 1
            else:
                failed_window_count += 1
        for comparison in deviation.get("comparisons", []):
            field_name = str(comparison.get("field_name", "")).strip()
            if not field_name:
                continue
            field = field_summary.setdefault(
                field_name,
                {"total": 0, "passed": 0, "failed": 0, "max_abs_error": 0.0, "max_rel_error": 0.0},
            )
            field["total"] += 1
            if comparison.get("passed", True):
                field["passed"] += 1
            else:
                field["failed"] += 1
                failed_fields.add(field_name)
            absolute_error = comparison.get("absolute_error")
            relative_error = comparison.get("relative_error")
            if absolute_error is not None:
                field["max_abs_error"] = max(field["max_abs_error"], float(absolute_error))
                max_abs_error = max(max_abs_error, float(absolute_error))
            if relative_error is not None:
                field["max_rel_error"] = max(field["max_rel_error"], float(relative_error))
                max_rel_error = max(max_rel_error, float(relative_error))

    pass_rate_denominator = matched_window_count or max(pass_window_count + failed_window_count, 1)
    status = "reference_not_found" if reference_not_found else "inactive"
    if matched_window_count > 0:
        if failed_window_count == 0:
            status = "pass"
        elif pass_window_count > 0:
            status = "partial"
        else:
            status = "fail"
    elif not reference_not_found:
        status = "no_matches"

    summary.update(
        {
            "status": status,
            "benchmark_deviation_summary": {
                "window_count": len(windows),
                "matched_window_count": matched_window_count,
                "pass_window_count": pass_window_count,
                "failed_window_count": failed_window_count,
                "missing_reference_window_count": missing_reference_window_count,
                "max_abs_error": max_abs_error,
                "max_rel_error": max_rel_error,
                "field_summary": field_summary,
            },
            "pass_rate": pass_window_count / pass_rate_denominator if pass_rate_denominator > 0 else 0.0,
            "failed_fields": sorted(failed_fields),
        }
    )
    return summary


def _reference_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "references" / "eddypro"


def _reference_json_path(reference_id: str) -> Path | None:
    if not reference_id:
        return None
    root = _reference_root()
    matches = sorted(root.rglob(f"{reference_id}.json"))
    return matches[0] if matches else None


def _build_reference_provenance_artifact(reference_id: str) -> dict[str, Any]:
    if not reference_id:
        return {}
    json_path = _reference_json_path(reference_id)
    if json_path is None:
        return {
            "status": "reference_not_found",
            "reference_id": reference_id,
            "source_file": "",
            "normalization_command": "",
        }
    provenance = generate_reference_provenance(json_path)
    provenance["status"] = "ready"
    provenance["source_file"] = provenance.get("original_file", "")
    provenance["qc_mapping"] = provenance.get("qc_mapping_strategy", "")
    provenance_path = json_path.parent / f"{json_path.stem}_provenance.json"
    normalization_script = str(provenance.get("normalization_script") or "references/eddypro/normalize_reference.py")
    source_file = str(provenance.get("original_file") or json_path.with_suffix(".csv"))
    provenance["provenance_file"] = str(provenance_path)
    provenance["normalization_command"] = (
        f'python {normalization_script} "{source_file}" "{json_path}" --provenance "{provenance_path}"'
    )
    return provenance


def _with_summary_context(
    *,
    summary: dict[str, Any],
    benchmark_summary: dict[str, Any],
    reference_provenance: dict[str, Any],
    network_output_config: dict[str, Any],
    method_summary: dict[str, Any],
    clock_sync_summary: dict[str, Any],
    performance_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmark_deviation_summary = dict(benchmark_summary.get("benchmark_deviation_summary", {}))
    footprint_summary = dict(method_summary.get("footprint_summary", {}))
    footprint_2d_summary = dict(method_summary.get("footprint_2d_summary", footprint_summary.get("footprint_2d_summary", {})) or {})
    uncertainty_summary = dict(method_summary.get("uncertainty_summary", {}))
    spectral_summary = dict(method_summary.get("spectral_correction_summary", {}))
    method_compare_summary = dict(method_summary.get("method_compare_summary", {}) or {})
    summary.update(
        {
            "benchmark_status": benchmark_summary.get("benchmark_status", ""),
            "benchmark_target": benchmark_summary.get("benchmark_target", ""),
            "benchmark_reference_id": benchmark_summary.get("benchmark_reference_id", ""),
            "benchmark_thresholds": benchmark_summary.get("benchmark_thresholds", {}),
            "benchmark_deviation_summary": benchmark_deviation_summary,
            "pass_rate": float(benchmark_summary.get("pass_rate", 0.0) or 0.0),
            "failed_fields": list(benchmark_summary.get("failed_fields", [])),
            "reference_provenance": reference_provenance,
            "schema_target": network_output_config.get("schema_target", ""),
            "fluxnet_timestamp_refers_to": network_output_config.get("timestamp_refers_to", "start"),
            "fluxnet_timezone_offset_h": float(network_output_config.get("timezone_offset_hours", 0.0) or 0.0),
            "fluxnet_gap_fill_value": float(network_output_config.get("gap_fill_value", -9999.0) or -9999.0),
            "footprint_method": method_summary.get("footprint_method", ""),
            "footprint_summary": footprint_summary,
            "footprint_peak_distance_m": footprint_summary.get("peak_distance_m"),
            "footprint_offset_distance_m": footprint_summary.get("offset_distance_m"),
            "footprint_contribution_distances": footprint_summary.get("contribution_distances", {}),
            "footprint_provenance": footprint_summary.get("provenance", ""),
            "footprint_limitations": footprint_summary.get("limitations", []),
            "footprint_2d_summary": footprint_2d_summary,
            "footprint_2d_grid_status": footprint_2d_summary.get("status", ""),
            "footprint_2d_peak_downwind_m": footprint_2d_summary.get("peak_downwind_m"),
            "footprint_2d_peak_crosswind_m": footprint_2d_summary.get("peak_crosswind_m"),
            "footprint_2d_half_width_m": footprint_2d_summary.get("half_width_m"),
            "uncertainty_method": method_summary.get("uncertainty_method", ""),
            "uncertainty_summary": uncertainty_summary,
            "uncertainty_relative_uncertainty": uncertainty_summary.get("relative_uncertainty"),
            "uncertainty_random_error": uncertainty_summary.get("primary_flux_random_error", uncertainty_summary.get("random_error")),
            "uncertainty_band": uncertainty_summary.get("uncertainty_band"),
            "uncertainty_confidence_level": uncertainty_summary.get("confidence_level"),
            "uncertainty_components": uncertainty_summary.get("components", {}),
            "uncertainty_provenance": uncertainty_summary.get("provenance", ""),
            "uncertainty_limitations": uncertainty_summary.get("limitations", []),
            "spectral_correction_method": method_summary.get("spectral_correction_method", ""),
            "spectral_correction_summary": spectral_summary,
            "spectral_correction_factor": spectral_summary.get("correction_factor"),
            "spectral_correction_provenance": spectral_summary.get("provenance", ""),
            "spectral_correction_measured_cospectrum_enabled": spectral_summary.get("measured_cospectrum_enabled", False),
            "spectral_correction_measured_cospectrum_used": spectral_summary.get("measured_cospectrum_used", False),
            "spectral_correction_measured_cospectrum_source": spectral_summary.get("measured_cospectrum_source", ""),
            "spectral_correction_cospectrum_match_summary": spectral_summary.get("cospectrum_match_summary", {}),
            "spectral_correction_limitations": spectral_summary.get("limitations", []),
            "method_compare_summary": method_compare_summary,
            "method_compare_recommendations": method_summary.get("method_compare_recommendations", method_compare_summary.get("recommendations", {})),
            "clock_sync_summary": clock_sync_summary,
            "clock_sync_status": clock_sync_summary.get("status", "disabled"),
            "clock_sync_method": clock_sync_summary.get("method", ""),
            "clock_sync_source": clock_sync_summary.get("clock_source", ""),
            "clock_sync_mean_offset_s": clock_sync_summary.get("mean_offset_seconds"),
            "performance_profile": performance_profile or {},
        }
    )
    return summary


def _auto_fill_benchmark_deviation(windows: list[WindowRPResult], benchmark_config: dict[str, Any]) -> None:
    reference_id = benchmark_config.get("reference_id", "")
    reference_paths = [
        Path("references/eddypro") / f"{reference_id}.json",
        Path("references/eddypro") / f"{reference_id}.csv",
    ]
    reference_windows = None
    for ref_path in reference_paths:
        if ref_path.exists():
            try:
                reference_windows = load_eddypro_reference_json(ref_path)
                break
            except Exception:
                continue
    if reference_windows is None:
        for window in windows:
            window.diagnostics["benchmark_deviation_summary"] = {
                "status": "reference_not_found",
                "reference_id": reference_id,
                "note": f"Reference file {reference_id} not found in references/eddypro/",
            }
        return
    benchmark_results = run_benchmark_comparison(
        rp_result=RPRunResult(
            run_id="benchmark_auto",
            created_at=datetime.now(),
            windows=windows,
            summary={},
            data_source="benchmark_auto",
            time_range="",
        ),
        reference_windows=reference_windows,
        flux_rel_threshold=benchmark_config.get("flux_rel_threshold", 0.10),
        lag_abs_threshold_s=benchmark_config.get("lag_abs_threshold_s", 0.5),
        wpl_rel_threshold=benchmark_config.get("wpl_rel_threshold", 0.20),
        qc_grade_must_match=benchmark_config.get("qc_grade_must_match", False),
    )
    bench_by_window: dict[str, dict[str, Any]] = {}
    for br in benchmark_results:
        bench_by_window[br.get("window_id", "")] = br
    for window in windows:
        br = bench_by_window.get(window.window_id)
        if br is not None:
            window.diagnostics["benchmark_deviation_summary"] = br
        else:
            window.diagnostics["benchmark_deviation_summary"] = {
                "window_id": window.window_id,
                "comparisons": [],
                "overall_pass": True,
                "notes": ["no matching reference window"],
            }
        _attach_method_context_to_benchmark(window, window.diagnostics["benchmark_deviation_summary"])


def _measured_cospectrum_from_series(
    *,
    w_series: np.ndarray,
    scalar_series: np.ndarray,
    sample_rate_hz: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    n = min(w_series.size, scalar_series.size)
    if n < 64 or sample_rate_hz <= 0.0:
        return None, None
    w = w_series[:n] - float(np.mean(w_series[:n]))
    s = scalar_series[:n] - float(np.mean(scalar_series[:n]))
    window = np.hanning(n)
    scale = float(np.sum(window ** 2))
    if scale <= 1e-12:
        return None, None
    w_fft = np.fft.rfft(w * window)
    s_fft = np.fft.rfft(s * window)
    freq = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    cospectrum = np.real(w_fft * np.conjugate(s_fft)) / scale
    valid = np.isfinite(freq) & np.isfinite(cospectrum) & (freq > 0.0)
    if np.count_nonzero(valid) < 8:
        return None, None
    return freq[valid], cospectrum[valid]


def _mean_or_none(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return round(float(np.mean(clean)), 4)


def _aggregate_numeric_mapping(mappings: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted({key for mapping in mappings for key, value in mapping.items() if isinstance(value, (int, float))})
    aggregated: dict[str, float] = {}
    for key in keys:
        values = [float(mapping[key]) for mapping in mappings if isinstance(mapping.get(key), (int, float))]
        if values:
            aggregated[key] = round(float(np.mean(values)), 4)
    return aggregated


def _summarize_performance_profile(
    *,
    windows: list[WindowRPResult],
    run_elapsed_ms: float,
    expected_window_count: int,
) -> dict[str, Any]:
    profiles = [
        dict(window.diagnostics.get("performance_profile", {}))
        for window in windows
        if isinstance(window.diagnostics.get("performance_profile"), dict)
    ]
    window_elapsed = [
        float(profile.get("window_elapsed_ms"))
        for profile in profiles
        if isinstance(profile.get("window_elapsed_ms"), (int, float))
    ]
    section_names = sorted(
        {
            name
            for profile in profiles
            for name, value in dict(profile.get("sections_ms", {}) or {}).items()
            if isinstance(value, (int, float))
        }
    )
    section_summary: dict[str, Any] = {}
    for name in section_names:
        values = [
            float(dict(profile.get("sections_ms", {}) or {}).get(name))
            for profile in profiles
            if isinstance(dict(profile.get("sections_ms", {}) or {}).get(name), (int, float))
        ]
        if values:
            section_summary[name] = {
                "average_ms": round(float(np.mean(values)), 3),
                "max_ms": round(float(np.max(values)), 3),
                "window_count": len(values),
            }
    return {
        "status": "ok" if profiles or expected_window_count == 0 else "no_window_profiles",
        "run_elapsed_ms": float(run_elapsed_ms),
        "expected_window_count": int(expected_window_count),
        "profiled_window_count": len(profiles),
        "average_window_elapsed_ms": round(float(np.mean(window_elapsed)), 3) if window_elapsed else 0.0,
        "max_window_elapsed_ms": round(float(np.max(window_elapsed)), 3) if window_elapsed else 0.0,
        "sections_ms": section_summary,
        "sample_count_range": [
            int(min(profile.get("sample_count", 0) for profile in profiles)) if profiles else 0,
            int(max(profile.get("sample_count", 0) for profile in profiles)) if profiles else 0,
        ],
        "method_compare_profiled": any(bool(profile.get("method_compare_enabled", False)) for profile in profiles),
        "footprint_2d_profiled": any(bool(profile.get("footprint_2d_enabled", False)) for profile in profiles),
    }


def _first_non_empty_mapping(values: list[dict[str, Any]]) -> dict[str, Any]:
    for value in values:
        if value:
            return dict(value)
    return {}


def _first_non_empty_text(values: list[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _summarize_method_outputs(
    *,
    windows: list[WindowRPResult],
    footprint_config: dict[str, Any],
    uncertainty_method_config: dict[str, Any],
    spectral_correction_config: dict[str, Any],
    method_compare_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    footprint_diags = [dict(window.diagnostics.get("footprint_detail", {})) for window in windows if window.diagnostics.get("footprint_detail")]
    footprint_contrib = [
        dict(window.diagnostics.get("footprint_contribution_distances", {}))
        for window in windows
        if isinstance(window.diagnostics.get("footprint_contribution_distances"), dict)
    ]
    footprint_summary = {
        "status": "enabled" if footprint_config.get("enabled", False) else "disabled",
        "method": _first_non_empty_text([window.diagnostics.get("footprint_method", "") for window in windows]) or (str(footprint_config.get("method", "")) if footprint_config.get("enabled", False) else ""),
        "window_count": len(footprint_diags),
        "peak_distance_m": _mean_or_none([window.diagnostics.get("footprint_peak_distance_m") for window in windows if isinstance(window.diagnostics.get("footprint_peak_distance_m"), (int, float))]),
        "offset_distance_m": _mean_or_none([window.diagnostics.get("footprint_offset_distance_m") for window in windows if isinstance(window.diagnostics.get("footprint_offset_distance_m"), (int, float))]),
        "contribution_distances": _aggregate_numeric_mapping(footprint_contrib),
        "provenance": _first_non_empty_text([detail.get("provenance", "") for detail in footprint_diags]),
        "limitations": list(_first_non_empty_mapping(footprint_diags).get("limitations", [])),
        "detail": _first_non_empty_mapping(footprint_diags),
    }
    footprint_grid_payloads = [
        dict(window.diagnostics.get("footprint_2d_grid", {}))
        for window in windows
        if isinstance(window.diagnostics.get("footprint_2d_grid"), dict)
    ]
    footprint_2d_summary = {
        "status": "enabled" if footprint_config.get("grid_enabled", True) and footprint_config.get("enabled", False) else "disabled",
        "window_count": len(footprint_grid_payloads),
        "grid_shape": _first_non_empty_mapping([dict(payload.get("detail", {})) for payload in footprint_grid_payloads]).get("grid_shape", []),
        "peak_downwind_m": _mean_or_none(
            [
                window.diagnostics.get("footprint_2d_peak_downwind_m")
                for window in windows
                if isinstance(window.diagnostics.get("footprint_2d_peak_downwind_m"), (int, float))
            ]
        ),
        "peak_crosswind_m": _mean_or_none(
            [
                window.diagnostics.get("footprint_2d_peak_crosswind_m")
                for window in windows
                if isinstance(window.diagnostics.get("footprint_2d_peak_crosswind_m"), (int, float))
            ]
        ),
        "half_width_m": _mean_or_none(
            [
                window.diagnostics.get("footprint_2d_half_width_m")
                for window in windows
                if isinstance(window.diagnostics.get("footprint_2d_half_width_m"), (int, float))
            ]
        ),
        "contribution_contours_m": _aggregate_numeric_mapping(
            [
                dict(window.diagnostics.get("footprint_2d_contribution_contours_m", {}))
                for window in windows
                if isinstance(window.diagnostics.get("footprint_2d_contribution_contours_m"), dict)
            ]
        ),
        "provenance": _first_non_empty_text(
            [
                dict(payload.get("detail", {})).get("provenance", "")
                for payload in footprint_grid_payloads
                if isinstance(payload.get("detail", {}), dict)
            ]
        ),
        "limitations": list(
            _first_non_empty_mapping(
                [
                    dict(payload.get("detail", {}))
                    for payload in footprint_grid_payloads
                    if isinstance(payload.get("detail", {}), dict)
                ]
            ).get("limitations", [])
        ),
    }
    footprint_summary["footprint_2d_summary"] = footprint_2d_summary

    uncertainty_diags: list[dict[str, Any]] = []
    for window in windows:
        method_detail = window.diagnostics.get("uncertainty_method_detail", {})
        final_detail = window.uncertainty_detail or {}
        if method_detail or final_detail:
            uncertainty_diags.append(
                {
                    **(dict(method_detail) if isinstance(method_detail, dict) else {}),
                    **(dict(final_detail) if isinstance(final_detail, dict) else {}),
                }
            )
    uncertainty_diags = [detail for detail in uncertainty_diags if detail]
    uncertainty_components = [
        dict(detail.get("components", {}))
        for detail in uncertainty_diags
        if isinstance(detail.get("components"), dict)
    ]
    uncertainty_summary = {
        "status": "enabled" if uncertainty_method_config.get("method") else "disabled",
        "method": _first_non_empty_text([window.diagnostics.get("uncertainty_method", "") for window in windows]) or str(uncertainty_method_config.get("method", "")),
        "selected_method": _first_non_empty_text([detail.get("selected_method", "") for detail in uncertainty_diags]) or str(uncertainty_method_config.get("method", "")),
        "window_count": len(uncertainty_diags),
        "relative_uncertainty": _mean_or_none(
            [
                detail.get("relative_error", detail.get("relative_uncertainty"))
                for detail in uncertainty_diags
                if isinstance(detail.get("relative_error", detail.get("relative_uncertainty")), (int, float))
            ]
        ),
        "random_error": _mean_or_none(
            [detail.get("random_error") for detail in uncertainty_diags if isinstance(detail.get("random_error"), (int, float))]
        ),
        "primary_flux_random_error": _mean_or_none(
            [
                detail.get("primary_flux_random_error")
                for detail in uncertainty_diags
                if isinstance(detail.get("primary_flux_random_error"), (int, float))
            ]
        ),
        "uncertainty_band": _mean_or_none(
            [
                detail.get("primary_flux_uncertainty_band")
                for detail in uncertainty_diags
                if isinstance(detail.get("primary_flux_uncertainty_band"), (int, float))
            ]
        ),
        "confidence_level": _mean_or_none(
            [
                detail.get("confidence_level")
                for detail in uncertainty_diags
                if isinstance(detail.get("confidence_level"), (int, float))
            ]
        ),
        "components": _aggregate_numeric_mapping(uncertainty_components),
        "provenance": _first_non_empty_text([detail.get("provenance", "") for detail in uncertainty_diags]),
        "limitations": list(_first_non_empty_mapping(uncertainty_diags).get("limitations", [])),
        "detail": _first_non_empty_mapping(uncertainty_diags),
    }

    spectral_diags = [dict(window.diagnostics.get("spectral_correction_detail", {})) for window in windows if window.diagnostics.get("spectral_correction_detail")]
    spectral_components = [
        dict(detail.get("components", {}))
        for detail in spectral_diags
        if isinstance(detail.get("components"), dict)
    ]
    spectral_summary = {
        "status": "enabled" if spectral_correction_config.get("enabled", False) else "disabled",
        "method": _first_non_empty_text([window.diagnostics.get("spectral_correction_method", "") for window in windows]) or (str(spectral_correction_config.get("method", "")) if spectral_correction_config.get("enabled", False) else ""),
        "window_count": len(spectral_diags),
        "correction_factor": _mean_or_none(
            [window.diagnostics.get("spectral_correction_factor") for window in windows if isinstance(window.diagnostics.get("spectral_correction_factor"), (int, float))]
        ),
        "components": _aggregate_numeric_mapping(spectral_components),
        "provenance": _first_non_empty_text([detail.get("provenance", "") for detail in spectral_diags]),
        "measured_cospectrum_enabled": any(bool(detail.get("measured_cospectrum_enabled", False)) for detail in spectral_diags),
        "measured_cospectrum_used": any(bool(detail.get("measured_cospectrum_used", False)) for detail in spectral_diags),
        "measured_cospectrum_source": _first_non_empty_text([detail.get("measured_cospectrum_source", "") for detail in spectral_diags]),
        "measured_cospectrum_source_run_id": _first_non_empty_text([detail.get("measured_cospectrum_source_run_id", "") for detail in spectral_diags]),
        "cospectrum_match_summary": {
            "window_count": len(
                [
                    window
                    for window in windows
                    if isinstance(window.diagnostics.get("spectral_correction_cospectrum_match"), dict)
                ]
            ),
            "match_strategy": _first_non_empty_text(
                [
                    dict(window.diagnostics.get("spectral_correction_cospectrum_match", {})).get("match_strategy", "")
                    for window in windows
                    if isinstance(window.diagnostics.get("spectral_correction_cospectrum_match"), dict)
                ]
            ),
            "average_match_quality": _mean_or_none(
                [
                    dict(window.diagnostics.get("spectral_correction_cospectrum_match", {})).get("match_quality")
                    for window in windows
                    if isinstance(dict(window.diagnostics.get("spectral_correction_cospectrum_match", {})).get("match_quality"), (int, float))
                ]
            ),
            "mismatch_warnings": list(
                dict.fromkeys(
                    str(dict(window.diagnostics.get("spectral_correction_cospectrum_match", {})).get("mismatch_warning", "")).strip()
                    for window in windows
                    if str(dict(window.diagnostics.get("spectral_correction_cospectrum_match", {})).get("mismatch_warning", "")).strip()
                )
            ),
        },
        "limitations": list(_first_non_empty_mapping(spectral_diags).get("limitations", [])),
        "detail": _first_non_empty_mapping(spectral_diags),
    }
    method_compare_windows = [
        dict(window.diagnostics.get("method_compare_summary", {}))
        for window in windows
        if isinstance(window.diagnostics.get("method_compare_summary"), dict)
    ]
    families = sorted({family for payload in method_compare_windows for family in payload.keys()})
    family_summaries: dict[str, Any] = {}
    for family in families:
        family_payloads = [
            dict(payload.get(family, {}))
            for payload in method_compare_windows
            if isinstance(payload.get(family), dict)
        ]
        recommendations = [
            str(payload.get("recommendation", "")).strip()
            for payload in family_payloads
            if str(payload.get("recommendation", "")).strip()
        ]
        recommendation_counts = {
            value: recommendations.count(value)
            for value in sorted(set(recommendations))
        }
        deviations = [
            abs(float(value))
            for payload in family_payloads
            for value in dict(payload.get("deviations", {}) or {}).values()
            if isinstance(value, (int, float))
        ]
        family_summaries[family] = {
            "window_count": len(family_payloads),
            "selected_method": _first_non_empty_text([payload.get("selected_method", "") for payload in family_payloads]),
            "primary_metric": _first_non_empty_text([payload.get("primary_metric", "") for payload in family_payloads]),
            "methods_run": sorted(
                {
                    str(method_name)
                    for payload in family_payloads
                    for method_name in list(payload.get("methods_run", []) or [])
                }
            ),
            "consensus_value": _mean_or_none(
                [
                    payload.get("consensus_value")
                    for payload in family_payloads
                    if isinstance(payload.get("consensus_value"), (int, float))
                ]
            ),
            "max_abs_relative_deviation": round(max(deviations), 6) if deviations else None,
            "recommendation_counts": recommendation_counts,
            "recommendation": max(recommendation_counts, key=recommendation_counts.get) if recommendation_counts else "",
            "status_counts": {
                value: [
                    str(payload.get("status", ""))
                    for payload in family_payloads
                ].count(value)
                for value in sorted({str(payload.get("status", "")) for payload in family_payloads})
            },
        }
    deviation_flags = [
        dict(flag)
        for window in windows
        for flag in (window.diagnostics.get("method_compare_deviation_flags", []) or [])
        if isinstance(flag, dict)
    ]
    method_compare_summary = {
        "status": "enabled" if (method_compare_config or {}).get("enabled", False) else "disabled",
        "window_count": len(method_compare_windows),
        "families": family_summaries,
        "recommendations": {
            family: summary.get("recommendation", "")
            for family, summary in family_summaries.items()
            if summary.get("recommendation")
        },
        "deviation_flags": deviation_flags,
        "provenance": "run-level rollup of per-window method-family comparison artifacts",
    }

    return {
        "footprint_method": footprint_summary.get("method", ""),
        "footprint_summary": footprint_summary,
        "footprint_2d_summary": footprint_2d_summary,
        "uncertainty_method": uncertainty_summary.get("method", ""),
        "uncertainty_summary": uncertainty_summary,
        "spectral_correction_method": spectral_summary.get("method", ""),
        "spectral_correction_summary": spectral_summary,
        "method_compare_summary": method_compare_summary,
        "method_compare_recommendations": method_compare_summary.get("recommendations", {}),
    }


def _build_method_deviation_notes_from_window(window: WindowRPResult) -> list[str]:
    diagnostics = window.diagnostics or {}
    notes: list[str] = []
    footprint_method = diagnostics.get("footprint_method", "")
    if footprint_method:
        footprint_detail = diagnostics.get("footprint_detail", {})
        footprint_provenance = footprint_detail.get("provenance", "") if isinstance(footprint_detail, dict) else ""
        notes.append(f"footprint: {footprint_method}" + (f" ({footprint_provenance})" if footprint_provenance else ""))
    uncertainty_method = diagnostics.get("uncertainty_method", "")
    if uncertainty_method:
        uncertainty_detail = diagnostics.get("uncertainty_method_detail", {}) or window.uncertainty_detail or {}
        uncertainty_provenance = uncertainty_detail.get("provenance", "") if isinstance(uncertainty_detail, dict) else ""
        uncertainty_band = diagnostics.get("primary_flux_uncertainty_band")
        band_text = f"; band={float(uncertainty_band):.6f}" if isinstance(uncertainty_band, (int, float)) else ""
        notes.append(
            f"uncertainty: {uncertainty_method}{band_text}" + (f" ({uncertainty_provenance})" if uncertainty_provenance else "")
        )
    spectral_method = diagnostics.get("spectral_correction_method", "")
    if spectral_method:
        spectral_provenance = diagnostics.get("spectral_correction_provenance", "")
        spectral_factor = diagnostics.get("spectral_correction_factor")
        factor_text = f" (factor={spectral_factor})" if isinstance(spectral_factor, (int, float)) else ""
        measured_source = diagnostics.get("spectral_correction_measured_cospectrum_source", "")
        source_text = f"; cospectrum={measured_source}" if measured_source else ""
        cospectrum_match = diagnostics.get("spectral_correction_cospectrum_match", {})
        if isinstance(cospectrum_match, dict) and cospectrum_match.get("match_strategy"):
            source_text = (
                f"{source_text}; match={cospectrum_match.get('match_strategy')}"
                f"/q={cospectrum_match.get('match_quality', 0.0)}"
            )
        notes.append(
            f"spectral_correction: {spectral_method}{factor_text}{source_text}"
            + (f" [{spectral_provenance}]" if spectral_provenance else "")
        )
    sonic_method = diagnostics.get("sonic_correction_method", "")
    sonic_status = diagnostics.get("sonic_correction_status", "")
    if sonic_method and sonic_status not in {"", "disabled"}:
        steps = diagnostics.get("sonic_correction_steps", [])
        step_count = len(steps) if isinstance(steps, list) else 0
        notes.append(f"sonic_correction: {sonic_method}; status={sonic_status}; steps={step_count}")
    crosswind_method = diagnostics.get("crosswind_correction_method", "")
    crosswind_status = diagnostics.get("crosswind_correction_status", "")
    if crosswind_method and crosswind_status not in {"", "disabled"}:
        delta = diagnostics.get("crosswind_correction_mean_delta_c")
        delta_text = f"; mean_delta_c={float(delta):.6f}" if isinstance(delta, (int, float)) else ""
        notes.append(f"crosswind_correction: {crosswind_method}; status={crosswind_status}{delta_text}")
    clock_status = diagnostics.get("clock_sync_status", "")
    if clock_status and clock_status not in {"", "disabled"}:
        mean_offset = diagnostics.get("clock_sync_mean_offset_s")
        offset_text = f"; mean_offset_s={float(mean_offset):.6f}" if isinstance(mean_offset, (int, float)) else ""
        notes.append(
            f"clock_sync: {diagnostics.get('clock_sync_method', '')}; "
            f"source={diagnostics.get('clock_sync_source', '')}; status={clock_status}{offset_text}"
        )
    ch4_method = diagnostics.get("ch4_method", "")
    if ch4_method:
        ch4_flux = diagnostics.get("ch4_flux_nmol_m2_s")
        ch4_level0 = diagnostics.get("ch4_flux_level0_nmol_m2_s")
        final_text = f"; final={float(ch4_flux):.6f} nmol m-2 s-1" if isinstance(ch4_flux, (int, float)) else ""
        level0_text = f"; level0={float(ch4_level0):.6f}" if isinstance(ch4_level0, (int, float)) else ""
        coefficient_profile = diagnostics.get("ch4_coefficient_profile_id", "")
        coefficient_text = f"; coefficient_profile={coefficient_profile}" if coefficient_profile else ""
        notes.append(f"trace_gas_ch4: {ch4_method}{level0_text}{final_text}{coefficient_text}")
    method_compare = diagnostics.get("method_compare_recommendations", {})
    if isinstance(method_compare, dict) and method_compare:
        notes.append(
            "method_compare: "
            + ", ".join(f"{family}={recommendation}" for family, recommendation in sorted(method_compare.items()))
        )
    return notes


def _attach_method_context_to_benchmark(window: WindowRPResult, benchmark_payload: dict[str, Any]) -> None:
    diagnostics = window.diagnostics or {}
    benchmark_payload["footprint_method"] = diagnostics.get("footprint_method", "")
    benchmark_payload["footprint_2d_grid_status"] = diagnostics.get("footprint_2d_grid_status", "")
    benchmark_payload["footprint_2d_peak_downwind_m"] = diagnostics.get("footprint_2d_peak_downwind_m")
    benchmark_payload["footprint_2d_peak_crosswind_m"] = diagnostics.get("footprint_2d_peak_crosswind_m")
    benchmark_payload["uncertainty_method"] = diagnostics.get("uncertainty_method", "")
    benchmark_payload["spectral_correction_method"] = diagnostics.get("spectral_correction_method", "")
    benchmark_payload["sonic_correction_method"] = diagnostics.get("sonic_correction_method", "")
    benchmark_payload["sonic_correction_status"] = diagnostics.get("sonic_correction_status", "")
    benchmark_payload["sonic_correction_steps"] = diagnostics.get("sonic_correction_steps", [])
    benchmark_payload["crosswind_correction_method"] = diagnostics.get("crosswind_correction_method", "")
    benchmark_payload["crosswind_correction_status"] = diagnostics.get("crosswind_correction_status", "")
    benchmark_payload["crosswind_correction_mean_delta_c"] = diagnostics.get("crosswind_correction_mean_delta_c")
    benchmark_payload["clock_sync_status"] = diagnostics.get("clock_sync_status", "")
    benchmark_payload["clock_sync_method"] = diagnostics.get("clock_sync_method", "")
    benchmark_payload["clock_sync_source"] = diagnostics.get("clock_sync_source", "")
    benchmark_payload["clock_sync_mean_offset_s"] = diagnostics.get("clock_sync_mean_offset_s")
    benchmark_payload["clock_sync_detail"] = diagnostics.get("clock_sync_detail", {})
    benchmark_payload["ch4_method"] = diagnostics.get("ch4_method", "")
    benchmark_payload["ch4_correction_sequence"] = diagnostics.get("ch4_correction_sequence", {})
    benchmark_payload["ch4_flux_nmol_m2_s"] = diagnostics.get("ch4_flux_nmol_m2_s")
    benchmark_payload["ch4_flux_level0_nmol_m2_s"] = diagnostics.get("ch4_flux_level0_nmol_m2_s")
    benchmark_payload["ch4_coefficient_profile_id"] = diagnostics.get("ch4_coefficient_profile_id", "")
    benchmark_payload["ch4_coefficient_registry_status"] = diagnostics.get("ch4_coefficient_registry_status", "")
    benchmark_payload["ch4_coefficient_profile_provenance"] = diagnostics.get("ch4_coefficient_profile_provenance", "")
    benchmark_payload["spectral_correction_cospectrum_match"] = diagnostics.get("spectral_correction_cospectrum_match", {})
    benchmark_payload["primary_flux_random_error"] = diagnostics.get("primary_flux_random_error")
    benchmark_payload["primary_flux_relative_uncertainty"] = diagnostics.get("primary_flux_relative_uncertainty")
    benchmark_payload["primary_flux_uncertainty_band"] = diagnostics.get("primary_flux_uncertainty_band")
    benchmark_payload["primary_flux_ci_lower"] = diagnostics.get("primary_flux_ci_lower")
    benchmark_payload["primary_flux_ci_upper"] = diagnostics.get("primary_flux_ci_upper")
    benchmark_payload["primary_flux_ci_level"] = diagnostics.get("primary_flux_ci_level")
    benchmark_payload["method_compare_summary"] = diagnostics.get("method_compare_summary", {})
    benchmark_payload["method_compare_recommendations"] = diagnostics.get("method_compare_recommendations", {})
    benchmark_payload["method_deviation_notes"] = _build_method_deviation_notes_from_window(window)
