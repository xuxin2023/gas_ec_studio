from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
import math

import numpy as np

from core.ec_rp.analysis import (
    analyze_lag,
    apply_lag,
    apply_planar_fit_no_velocity_bias,
    apply_planar_fit_rotation,
    build_window_series,
    build_uncertainty_band,
    compute_flux_metrics,
    compute_footprint,
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
from models.hf_models import NormalizedHFFrame
from models.rp_models import RPRunResult, WindowRPResult
from models.station_models import ProjectProfile, SiteProfile


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
        created_at = datetime.now()
        run_id = f"rp_{created_at:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        sorted_rows = sorted(rows, key=lambda row: row.timestamp)
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
        benchmark_summary = _default_benchmark_summary(benchmark_config=benchmark_config, window_count=0)
        reference_provenance = _build_reference_provenance_artifact(benchmark_config.get("reference_id", ""))
        method_summary = _summarize_method_outputs(
            windows=[],
            footprint_config=footprint_config,
            uncertainty_method_config=uncertainty_method_config,
            spectral_correction_config=spectral_correction_config,
        )
        slices = pick_window_slices(len(sorted_rows), sample_rate_hz, block_minutes=block_minutes)
        if not sorted_rows or not slices:
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
                        )
                    )
                except Exception:
                    pass
            if first_pass_windows:
                u_list = [np.array(w.diagnostics.get("rotation_u", [])) for w in first_pass_windows if w.diagnostics.get("rotation_u") is not None]
                v_list = [np.array(w.diagnostics.get("rotation_v", [])) for w in first_pass_windows if w.diagnostics.get("rotation_v") is not None]
                w_list = [np.array(w.diagnostics.get("rotation_w", [])) for w in first_pass_windows if w.diagnostics.get("rotation_w") is not None]
                if not u_list:
                    prepared_list = [build_window_series(sorted_rows[s:e], sample_rate_hz) for s, e in slices if s < len(sorted_rows)]
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
    ) -> WindowRPResult:
        prepared = build_window_series(rows, sample_rate_hz)
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
            "metadata_summary": {
                "sample_rate_hz": float(sample_rate_hz),
                "sample_count": prepared.sample_count,
                "valid_sample_count": prepared.valid_sample_count,
                "continuity_ratio": float(prepared.continuity_ratio),
                "mean_co2_ppm": float(np.mean(lagged_co2)),
                "mean_h2o_mmol": float(np.mean(lagged_h2o)),
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
        if spectral_correction_config and spectral_correction_config.get("enabled", False):
            measured_cospectrum_freq = None
            measured_cospectrum_value = None
            measured_cospectrum_meta = {
                "enabled": bool(spectral_correction_config.get("use_fcc_measured_cospectrum", False)),
                "used": False,
                "source": "disabled",
                "matched_window_id": "",
                "source_run_id": str(spectral_correction_config.get("fcc_source_run_id", "")),
            }
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
                provenance_detail = dict(sc.get("provenance_detail", {}) or {})
                provenance_detail["measured_cospectrum_source"] = sc["measured_cospectrum_source"]
                provenance_detail["measured_cospectrum_source_run_id"] = sc["measured_cospectrum_source_run_id"]
                provenance_detail["measured_cospectrum_window_id"] = sc["measured_cospectrum_window_id"]
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


def _density_correction_factor(*, raw_flux: float, density_corrected_flux: float) -> float:
    if abs(raw_flux) <= 1e-12:
        return 1.0 if abs(density_corrected_flux) <= 1e-12 else 1.5
    return float(density_corrected_flux / raw_flux)


def _failed_window_result(
    *,
    run_id: str,
    window_index: int,
    rows: list[NormalizedHFFrame],
    rotation_mode: str,
    detrend_mode: str,
    reason: str,
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
        diagnostics={"issues": ["processing_error"], "qc_reasons": [reason]},
    )


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
    ]:
        value = _config_value(config, f"footprint.{key}", f"steps.footprint.{key}", default=default)
        fc[key] = value
    return fc


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
        return None, None, {"enabled": False, "used": False, "source": "disabled", "matched_window_id": ""}

    matched: dict[str, Any] | None = None
    tolerance_s = 2.0
    for item in candidates:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(str(item.get("start_time", "")))
            end = datetime.fromisoformat(str(item.get("end_time", "")))
        except ValueError:
            continue
        if abs((start - window_start).total_seconds()) <= tolerance_s and abs((end - window_end).total_seconds()) <= tolerance_s:
            matched = item
            break
        latest_start = max(start, window_start)
        earliest_end = min(end, window_end)
        if (earliest_end - latest_start).total_seconds() > 0:
            matched = item
            break

    if matched is None:
        return None, None, {
            "enabled": True,
            "used": False,
            "source": "fcc_auto_no_match",
            "matched_window_id": "",
            "source_run_id": str(config.get("fcc_source_run_id", "")),
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
) -> dict[str, Any]:
    benchmark_deviation_summary = dict(benchmark_summary.get("benchmark_deviation_summary", {}))
    footprint_summary = dict(method_summary.get("footprint_summary", {}))
    uncertainty_summary = dict(method_summary.get("uncertainty_summary", {}))
    spectral_summary = dict(method_summary.get("spectral_correction_summary", {}))
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
            "spectral_correction_limitations": spectral_summary.get("limitations", []),
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
        "limitations": list(_first_non_empty_mapping(spectral_diags).get("limitations", [])),
        "detail": _first_non_empty_mapping(spectral_diags),
    }

    return {
        "footprint_method": footprint_summary.get("method", ""),
        "footprint_summary": footprint_summary,
        "uncertainty_method": uncertainty_summary.get("method", ""),
        "uncertainty_summary": uncertainty_summary,
        "spectral_correction_method": spectral_summary.get("method", ""),
        "spectral_correction_summary": spectral_summary,
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
        notes.append(
            f"spectral_correction: {spectral_method}{factor_text}{source_text}"
            + (f" [{spectral_provenance}]" if spectral_provenance else "")
        )
    return notes


def _attach_method_context_to_benchmark(window: WindowRPResult, benchmark_payload: dict[str, Any]) -> None:
    diagnostics = window.diagnostics or {}
    benchmark_payload["footprint_method"] = diagnostics.get("footprint_method", "")
    benchmark_payload["uncertainty_method"] = diagnostics.get("uncertainty_method", "")
    benchmark_payload["spectral_correction_method"] = diagnostics.get("spectral_correction_method", "")
    benchmark_payload["primary_flux_random_error"] = diagnostics.get("primary_flux_random_error")
    benchmark_payload["primary_flux_relative_uncertainty"] = diagnostics.get("primary_flux_relative_uncertainty")
    benchmark_payload["primary_flux_uncertainty_band"] = diagnostics.get("primary_flux_uncertainty_band")
    benchmark_payload["primary_flux_ci_lower"] = diagnostics.get("primary_flux_ci_lower")
    benchmark_payload["primary_flux_ci_upper"] = diagnostics.get("primary_flux_ci_upper")
    benchmark_payload["primary_flux_ci_level"] = diagnostics.get("primary_flux_ci_level")
    benchmark_payload["method_deviation_notes"] = _build_method_deviation_notes_from_window(window)
