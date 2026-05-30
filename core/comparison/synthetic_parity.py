from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from core.ec_rp.analysis import compute_footprint, compute_footprint_2d_grid, compute_spectral_correction
from core.ec_rp.pipeline import ECRPPipeline
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


SYNTHETIC_PARITY_SUITE_ID = "eddypro_style_synthetic_oracle_v1"


def run_synthetic_eddypro_parity_suite() -> dict[str, Any]:
    """Run deterministic oracle cases that do not require field data.

    These cases are not a substitute for official EddyPro golden outputs. They
    pin physics and processing invariants that any EddyPro-style implementation
    should satisfy before field parity data is available.
    """
    cases = [
        _run_known_covariance_case(),
        _run_known_lag_case(),
        _run_density_mode_semantics_case(),
        _run_double_rotation_tilt_case(),
        _run_constant_signal_qc_case(),
        _run_spectral_correction_family_case(),
        _run_footprint_geometry_family_case(),
    ]
    failed = [case for case in cases if case["status"] != "pass"]
    return {
        "artifact_type": "synthetic_eddypro_parity_suite",
        "suite_id": SYNTHETIC_PARITY_SUITE_ID,
        "status": "pass" if not failed else "fail",
        "case_count": len(cases),
        "passed_case_count": len(cases) - len(failed),
        "failed_case_count": len(failed),
        "cases": cases,
        "truthfulness_note": (
            "Synthetic oracle cases validate deterministic EddyPro-style invariants "
            "without claiming real-world EddyPro numeric parity."
        ),
        "known_limitations": [
            "No vendor raw file reader or official EddyPro executable output is involved.",
            "Synthetic signals cannot cover field non-stationarity, instrument drift, canopy complexity, or hidden EddyPro implementation details.",
            "Use this suite as a CI guardrail until anonymized raw field bundles with EddyPro golden outputs are available.",
        ],
    }


def _run_known_covariance_case() -> dict[str, Any]:
    sample_hz = 10.0
    rows, oracle = _make_oracle_rows(sample_hz=sample_hz, samples=240, co2_lag_samples=0)
    config = _base_config(sample_hz=sample_hz, window_minutes=1.0)
    config.update({"rotation_mode": "none", "detrend_mode": "block_mean", "density_correction_mode": "none"})
    config["lag_phase"] = {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0}
    result = _run_pipeline(rows=rows, config=config, time_range="synthetic known covariance")
    window = result.windows[0] if result.windows else None
    checks = []
    if window is None:
        checks.append(_check(False, "window_created", "expected one RP window", None, 1, 0.0, "absolute"))
    else:
        expected = _manual_flux_oracle(oracle["w"], oracle["co2"], oracle["h2o"], oracle["pressure"], oracle["temp"])
        checks.extend(
            [
                _check_close(
                    name="raw_flux_matches_manual_covariance",
                    actual=window.raw_flux,
                    expected=expected["raw_flux"],
                    tolerance=1e-9,
                    mode="absolute",
                ),
                _check_close(
                    name="primary_flux_uses_raw_when_density_none",
                    actual=window.primary_flux,
                    expected=expected["raw_flux"],
                    tolerance=1e-9,
                    mode="absolute",
                ),
                _check_close(
                    name="constant_lag_is_zero",
                    actual=window.lag_seconds,
                    expected=0.0,
                    tolerance=1e-12,
                    mode="absolute",
                ),
            ]
        )
    return _case_payload(
        case_id="known_covariance_density_none",
        objective="Known zero-lag covariance should reproduce the manual raw CO2 flux oracle.",
        checks=checks,
        expected={"lag_seconds": 0.0, "density_correction_mode": "none"},
        actual=_window_actual(window),
    )


def _run_known_lag_case() -> dict[str, Any]:
    sample_hz = 10.0
    lag_samples = 5
    expected_lag_s = lag_samples / sample_hz
    rows, _ = _make_oracle_rows(sample_hz=sample_hz, samples=240, co2_lag_samples=-lag_samples)
    config = _base_config(sample_hz=sample_hz, window_minutes=1.0)
    config.update({"rotation_mode": "none", "detrend_mode": "block_mean", "density_correction_mode": "none"})
    config["lag_phase"] = {"strategy": "covariance_max", "search_window_s": 1.5}
    result = _run_pipeline(rows=rows, config=config, time_range="synthetic known lag")
    window = result.windows[0] if result.windows else None
    checks = []
    if window is None:
        checks.append(_check(False, "window_created", "expected one RP window", None, 1, 0.0, "absolute"))
    else:
        checks.extend(
            [
                _check_close(
                    name="covariance_max_recovers_known_lag",
                    actual=window.lag_seconds,
                    expected=expected_lag_s,
                    tolerance=0.11,
                    mode="absolute",
                ),
                _check_close(
                    name="co2_lag_matches_known_lag",
                    actual=dict(window.diagnostics or {}).get("co2_lag_seconds"),
                    expected=expected_lag_s,
                    tolerance=0.11,
                    mode="absolute",
                ),
                _check(
                    bool(float(window.lag_confidence or 0.0) > 0.4),
                    "lag_confidence_above_floor",
                    "known synthetic lag should have a clear covariance peak",
                    window.lag_confidence,
                    ">0.4",
                    0.0,
                    "logical",
                ),
            ]
        )
    return _case_payload(
        case_id="known_lag_covariance_max",
        objective="A shifted scalar series should recover the configured EddyPro-style covariance maximum lag.",
        checks=checks,
        expected={"lag_seconds": expected_lag_s, "lag_samples": lag_samples},
        actual=_window_actual(window),
    )


def _run_density_mode_semantics_case() -> dict[str, Any]:
    sample_hz = 10.0
    rows, oracle = _make_oracle_rows(sample_hz=sample_hz, samples=240, co2_lag_samples=0, temp_gain=0.35)
    base_config = _base_config(sample_hz=sample_hz, window_minutes=1.0)
    base_config.update({"rotation_mode": "none", "detrend_mode": "block_mean"})
    base_config["lag_phase"] = {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0}
    expected = _manual_flux_oracle(oracle["w"], oracle["co2"], oracle["h2o"], oracle["pressure"], oracle["temp"])
    checks = []
    actual_by_mode: dict[str, Any] = {}
    for mode, expected_key in (
        ("none", "raw_flux"),
        ("mixing_ratio", "mixing_ratio_flux"),
        ("wpl", "density_corrected_flux"),
    ):
        config = dict(base_config)
        config["density_correction_mode"] = mode
        result = _run_pipeline(rows=rows, config=config, time_range=f"synthetic density mode {mode}")
        window = result.windows[0] if result.windows else None
        actual_by_mode[mode] = _window_actual(window)
        if window is None:
            checks.append(_check(False, f"{mode}_window_created", "expected one RP window", None, 1, 0.0, "absolute"))
            continue
        checks.append(
            _check_close(
                name=f"{mode}_primary_flux_semantics",
                actual=window.primary_flux,
                expected=expected[expected_key],
                tolerance=1e-9,
                mode="absolute",
            )
        )
    return _case_payload(
        case_id="density_correction_mode_semantics",
        objective="Primary flux selection should match EddyPro-style raw, mixing-ratio, and WPL correction semantics.",
        checks=checks,
        expected={
            "none": expected["raw_flux"],
            "mixing_ratio": expected["mixing_ratio_flux"],
            "wpl": expected["density_corrected_flux"],
        },
        actual=actual_by_mode,
    )


def _run_double_rotation_tilt_case() -> dict[str, Any]:
    sample_hz = 10.0
    rows, oracle = _make_oracle_rows(sample_hz=sample_hz, samples=240, co2_lag_samples=0)
    _apply_mean_vertical_tilt(rows=rows, oracle=oracle, vertical_offset_m_s=0.36, crosswind_offset_m_s=0.18)
    config = _base_config(sample_hz=sample_hz, window_minutes=1.0)
    config.update({"rotation_mode": "double", "detrend_mode": "block_mean", "density_correction_mode": "none"})
    config["lag_phase"] = {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0}
    result = _run_pipeline(rows=rows, config=config, time_range="synthetic double rotation tilt")
    window = result.windows[0] if result.windows else None
    diagnostics = dict(getattr(window, "diagnostics", {}) or {})
    beta_deg = diagnostics.get("rotation_beta_deg")
    checks = []
    if window is None:
        checks.append(_check(False, "window_created", "expected one RP window", None, 1, 0.0, "absolute"))
    else:
        checks.extend(
            [
                _check(
                    diagnostics.get("applied_rotation_impl") == "double",
                    "double_rotation_impl_selected",
                    "configured double rotation should be the applied implementation",
                    diagnostics.get("applied_rotation_impl"),
                    "double",
                    0.0,
                    "logical",
                ),
                _check(
                    bool(diagnostics.get("rotation_applied")),
                    "rotation_applied",
                    "tilted synthetic wind should trigger an actual rotation",
                    diagnostics.get("rotation_applied"),
                    True,
                    0.0,
                    "logical",
                ),
                _check(
                    abs(float(beta_deg or 0.0)) > 1.0,
                    "tilt_beta_nonzero",
                    "mean vertical wind offset should produce a non-trivial beta angle",
                    beta_deg,
                    ">1 deg",
                    0.0,
                    "logical",
                ),
                _check(
                    abs(float(diagnostics.get("mean_rotated_w", 0.0) or 0.0)) < 0.05,
                    "rotated_w_mean_near_zero",
                    "double rotation should reduce mean rotated vertical wind",
                    diagnostics.get("mean_rotated_w"),
                    "abs < 0.05 m s-1",
                    0.0,
                    "logical",
                ),
            ]
        )
    return _case_payload(
        case_id="double_rotation_tilt_guardrail",
        objective="A tilted wind field should apply double rotation and remove most mean vertical wind bias.",
        checks=checks,
        expected={"rotation_mode": "double", "rotation_applied": True, "mean_rotated_w_abs_lt": 0.05},
        actual=_window_actual(window),
    )


def _run_constant_signal_qc_case() -> dict[str, Any]:
    sample_hz = 10.0
    rows, oracle = _make_oracle_rows(sample_hz=sample_hz, samples=240, co2_lag_samples=0)
    oracle["co2"] = np.full_like(oracle["co2"], 410.0)
    oracle["h2o"] = np.full_like(oracle["h2o"], 12.0)
    for row in rows:
        row.co2_ppm = 410.0
        row.h2o_mmol = 12.0
    config = _base_config(sample_hz=sample_hz, window_minutes=1.0)
    config.update({"rotation_mode": "none", "detrend_mode": "block_mean", "density_correction_mode": "none"})
    config["lag_phase"] = {"strategy": "constant", "expected_lag_s": 0.0, "search_window_s": 1.0}
    result = _run_pipeline(rows=rows, config=config, time_range="synthetic constant scalar qc")
    window = result.windows[0] if result.windows else None
    actual = _window_actual(window)
    issues = set(actual.get("issues", []))
    checks = []
    if window is None:
        checks.append(_check(False, "window_created", "expected one RP window", None, 1, 0.0, "absolute"))
    else:
        checks.extend(
            [
                _check(
                    window.qc_grade == "C",
                    "constant_signal_grade_c",
                    "constant scalar windows should not pass as production-grade fluxes",
                    window.qc_grade,
                    "C",
                    0.0,
                    "logical",
                ),
                _check(
                    window.anomaly_type == "constant_signal",
                    "constant_signal_anomaly_type",
                    "QC anomaly should explicitly identify constant scalar data",
                    window.anomaly_type,
                    "constant_signal",
                    0.0,
                    "logical",
                ),
                _check(
                    {"co2_ppm_constant", "h2o_mmol_constant"}.issubset(issues),
                    "constant_signal_issues_present",
                    "both CO2 and H2O constant-signal issues should be retained in diagnostics",
                    sorted(issues),
                    ["co2_ppm_constant", "h2o_mmol_constant"],
                    0.0,
                    "logical",
                ),
            ]
        )
    return _case_payload(
        case_id="constant_signal_qc_guardrail",
        objective="Constant CO2/H2O scalar inputs should be rejected by EddyPro-style QC semantics.",
        checks=checks,
        expected={"qc_grade": "C", "anomaly_type": "constant_signal"},
        actual=actual,
    )


def _run_spectral_correction_family_case() -> dict[str, Any]:
    methods = ("massman", "horst", "ibrom", "fratini")
    measured_freq = np.linspace(0.05, 4.5, 48)
    measured_cospec = np.exp(-measured_freq / 1.4)
    actual: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    for method in methods:
        kwargs: dict[str, Any] = {}
        if method == "fratini":
            kwargs["measured_cospectrum_freq"] = measured_freq
            kwargs["measured_cospectrum_value"] = measured_cospec
        correction = compute_spectral_correction(
            method=method,
            path_length_m=0.15,
            sensor_sep_m=0.20,
            response_time_s=0.10,
            sample_rate_hz=10.0,
            averaging_period_s=1800.0,
            wind_speed=3.0,
            z_m=3.0,
            ustar=0.35,
            ol=-80.0,
            **kwargs,
        )
        actual[method] = correction
        checks.extend(
            [
                _check(
                    correction.get("method") == method,
                    f"{method}_method_echo",
                    "spectral correction should preserve selected method provenance",
                    correction.get("method"),
                    method,
                    0.0,
                    "logical",
                ),
                _check(
                    correction.get("status") == "ok",
                    f"{method}_status_ok",
                    "well-conditioned synthetic inputs should produce an ok correction",
                    correction.get("status"),
                    "ok",
                    0.0,
                    "logical",
                ),
                _check(
                    float(correction.get("correction_factor", 0.0) or 0.0) >= 1.0,
                    f"{method}_factor_not_lossy",
                    "spectral correction factors should compensate attenuation, not shrink fluxes",
                    correction.get("correction_factor"),
                    ">=1.0",
                    0.0,
                    "logical",
                ),
                _check(
                    bool(correction.get("provenance")) and bool(correction.get("provenance_detail")),
                    f"{method}_provenance_present",
                    "method provenance and input provenance detail should be exportable",
                    {"provenance": correction.get("provenance"), "provenance_detail": correction.get("provenance_detail")},
                    "non-empty",
                    0.0,
                    "logical",
                ),
            ]
        )
    checks.append(
        _check(
            bool(actual["fratini"].get("components", {}).get("uses_measured_cospectrum")),
            "fratini_measured_cospectrum_used",
            "Fratini path should consume the supplied measured cospectrum",
            actual["fratini"].get("components", {}).get("uses_measured_cospectrum"),
            True,
            0.0,
            "logical",
        )
    )
    return _case_payload(
        case_id="spectral_correction_family_invariants",
        objective="Massman/Horst/Ibrom/Fratini corrections should produce stable factors and method provenance.",
        checks=checks,
        expected={"methods": list(methods), "fratini_uses_measured_cospectrum": True},
        actual=actual,
    )


def _run_footprint_geometry_family_case() -> dict[str, Any]:
    methods = ("kljun", "kormann_meixner", "hsieh")
    actual: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    for method in methods:
        footprint = compute_footprint(
            method=method,
            ustar=0.35,
            mean_wind_speed=3.0,
            sigma_v=0.9,
            z_m=3.0,
            h=0.4,
            z0=0.05,
            ol=-80.0,
        )
        distances = footprint.contribution_distances
        ordered = [float(distances.get(f"x{pct}", 0.0) or 0.0) for pct in (10, 30, 50, 70, 90)]
        actual[method] = {
            "method": footprint.method,
            "peak_distance_m": footprint.peak_distance_m,
            "offset_distance_m": footprint.offset_distance_m,
            "contribution_distances": distances,
            "detail": footprint.detail,
        }
        checks.extend(
            [
                _check(
                    footprint.method == method,
                    f"{method}_method_echo",
                    "footprint result should preserve selected method",
                    footprint.method,
                    method,
                    0.0,
                    "logical",
                ),
                _check(
                    footprint.detail.get("status") == "ok",
                    f"{method}_status_ok",
                    "well-conditioned synthetic inputs should produce an ok footprint",
                    footprint.detail.get("status"),
                    "ok",
                    0.0,
                    "logical",
                ),
                _check(
                    float(footprint.peak_distance_m) > 0.0 and float(footprint.offset_distance_m) >= 0.0,
                    f"{method}_positive_distances",
                    "peak and offset distances should be physically positive/non-negative",
                    {"peak": footprint.peak_distance_m, "offset": footprint.offset_distance_m},
                    "peak > 0 and offset >= 0",
                    0.0,
                    "logical",
                ),
                _check(
                    ordered == sorted(ordered) and all(value > 0.0 for value in ordered),
                    f"{method}_contribution_distances_monotonic",
                    "contribution distances should increase from x10 to x90",
                    ordered,
                    "monotonic positive x10..x90",
                    0.0,
                    "logical",
                ),
                _check(
                    bool(footprint.detail.get("provenance")) and bool(footprint.detail.get("limitations")),
                    f"{method}_provenance_present",
                    "footprint method should report provenance and limitations",
                    {"provenance": footprint.detail.get("provenance"), "limitations": footprint.detail.get("limitations")},
                    "non-empty",
                    0.0,
                    "logical",
                ),
            ]
        )
    grid = compute_footprint_2d_grid(
        method="kljun",
        ustar=0.35,
        mean_wind_speed=3.0,
        sigma_v=0.9,
        z_m=3.0,
        h=0.4,
        z0=0.05,
        ol=-80.0,
        x_bins=12,
        y_bins=9,
    )
    grid_sum = None
    if grid is not None:
        grid_sum = float(np.sum(np.asarray(grid.contribution_grid, dtype=float)))
        actual["kljun_2d_grid"] = {
            "method": grid.method,
            "x_bins": len(grid.x_coords_m),
            "y_bins": len(grid.y_coords_m),
            "grid_sum": grid_sum,
            "contours": grid.contribution_contours_m,
            "detail": grid.detail,
        }
    checks.extend(
        [
            _check(
                grid is not None,
                "kljun_2d_grid_created",
                "2D source-area grid should be generated from the selected footprint method",
                grid is not None,
                True,
                0.0,
                "logical",
            ),
            _check_close(
                name="kljun_2d_grid_normalized",
                actual=grid_sum,
                expected=1.0,
                tolerance=1e-6,
                mode="absolute",
            ),
            _check(
                grid is not None and {"x10", "x30", "x50", "x70", "x90"}.issubset(set(grid.contribution_contours_m)),
                "kljun_2d_contours_present",
                "2D footprint grid should retain the standard contribution contours",
                {} if grid is None else grid.contribution_contours_m,
                ["x10", "x30", "x50", "x70", "x90"],
                0.0,
                "logical",
            ),
        ]
    )
    return _case_payload(
        case_id="footprint_geometry_family_invariants",
        objective="Kljun/Kormann-Meixner/Hsieh footprints should produce positive monotonic source-area distances and normalized 2D grids.",
        checks=checks,
        expected={"methods": list(methods), "contribution_distances": ["x10", "x30", "x50", "x70", "x90"]},
        actual=actual,
    )


def _base_config(*, sample_hz: float, window_minutes: float) -> dict[str, Any]:
    return {
        "sample_hz": sample_hz,
        "block_minutes": window_minutes,
        "steps": {
            "window_sampling": {"sample_hz": sample_hz, "window_minutes": window_minutes},
        },
    }


def _run_pipeline(*, rows: list[NormalizedHFFrame], config: dict[str, Any], time_range: str) -> Any:
    return ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="SYN-EDDYPRO", name="Synthetic EddyPro Oracle"),
        site=SiteProfile(station_code="SYN", station_name="Synthetic Oracle Site"),
        config=config,
        data_source=SYNTHETIC_PARITY_SUITE_ID,
        time_range=time_range,
    )


def _make_oracle_rows(
    *,
    sample_hz: float,
    samples: int,
    co2_lag_samples: int,
    temp_gain: float = 0.0,
) -> tuple[list[NormalizedHFFrame], dict[str, np.ndarray]]:
    start = datetime(2026, 5, 25, 12, 0, 0)
    time_axis = np.arange(samples, dtype=float) / float(sample_hz)
    w = 0.62 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.21 * np.cos(2.0 * np.pi * 0.73 * time_axis)
    u = 2.6 + 0.05 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.18 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    co2_driver = np.roll(w, int(co2_lag_samples))
    h2o_driver = np.roll(w, int(co2_lag_samples))
    co2 = 410.0 + 8.0 * co2_driver
    h2o = 12.0 + 1.5 * h2o_driver
    pressure = np.full(samples, 101.3, dtype=float)
    temp = 24.0 + float(temp_gain) * w
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="synthetic-oracle",
                device_id="SYN",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(co2[index]),
                h2o_mmol=float(h2o[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                case_temp_c=float(temp[index]),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows, {"u": u, "v": v, "w": w, "co2": co2, "h2o": h2o, "pressure": pressure, "temp": temp}


def _apply_mean_vertical_tilt(
    *,
    rows: list[NormalizedHFFrame],
    oracle: dict[str, np.ndarray],
    vertical_offset_m_s: float,
    crosswind_offset_m_s: float,
) -> None:
    oracle["w"] = oracle["w"] + float(vertical_offset_m_s)
    oracle["v"] = oracle["v"] + float(crosswind_offset_m_s)
    for index, row in enumerate(rows):
        row.raw_text = json.dumps(
            {
                "u": float(oracle["u"][index]),
                "v": float(oracle["v"][index]),
                "w": float(oracle["w"][index]),
            }
        )


def _manual_flux_oracle(
    w: np.ndarray,
    co2: np.ndarray,
    h2o: np.ndarray,
    pressure_kpa: np.ndarray,
    temp_c: np.ndarray,
) -> dict[str, float]:
    w_det = w - np.mean(w)
    co2_det = co2 - np.mean(co2)
    h2o_det = h2o - np.mean(h2o)
    temp_det = temp_c - np.mean(temp_c)
    cov_w_co2 = float(np.mean(w_det * co2_det))
    cov_w_h2o = float(np.mean(w_det * h2o_det))
    cov_w_t = float(np.mean(w_det * temp_det))
    mean_p_pa = float(np.mean(pressure_kpa)) * 1000.0
    mean_t_k = float(np.mean(temp_c)) + 273.15
    gas_constant = 8.314
    air_molar_density = mean_p_pa / (gas_constant * mean_t_k)
    mean_h2o = float(np.mean(h2o))
    mean_h2o_mol_fraction = max(0.0, mean_h2o * 1.0e-3)
    mean_co2_ppm = float(np.mean(co2))
    dry_air_molar_density = air_molar_density / (1.0 + mean_h2o_mol_fraction)
    raw_flux = air_molar_density * cov_w_co2
    mixing_ratio_flux = dry_air_molar_density * (cov_w_co2 + (mean_co2_ppm * 1.0e-3) * cov_w_h2o)
    water_vapor_flux = dry_air_molar_density * cov_w_h2o
    wpl_water_vapor_term = mean_co2_ppm * water_vapor_flux * 1.0e-3
    wpl_sensible_heat_term = mean_co2_ppm * air_molar_density * (1.0 + mean_h2o_mol_fraction)
    wpl_sensible_heat_term *= cov_w_t / mean_t_k
    return {
        "cov_w_co2": cov_w_co2,
        "cov_w_h2o": cov_w_h2o,
        "raw_flux": raw_flux,
        "mixing_ratio_flux": mixing_ratio_flux,
        "density_corrected_flux": raw_flux + wpl_water_vapor_term + wpl_sensible_heat_term,
        "wpl_water_vapor_term": wpl_water_vapor_term,
        "wpl_sensible_heat_term": wpl_sensible_heat_term,
    }


def _case_payload(
    *,
    case_id: str,
    objective: str,
    checks: list[dict[str, Any]],
    expected: dict[str, Any],
    actual: Any,
) -> dict[str, Any]:
    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "case_id": case_id,
        "status": "pass" if not failed else "fail",
        "objective": objective,
        "check_count": len(checks),
        "failed_check_count": len(failed),
        "checks": checks,
        "expected": _jsonable(expected),
        "actual": _jsonable(actual),
        "provenance": "Generated by gas_ec_studio synthetic EddyPro-style oracle suite.",
    }


def _check_close(*, name: str, actual: Any, expected: float, tolerance: float, mode: str) -> dict[str, Any]:
    try:
        actual_float = float(actual)
        expected_float = float(expected)
    except (TypeError, ValueError):
        return _check(False, name, "actual or expected value is not numeric", actual, expected, tolerance, mode)
    if mode == "relative":
        delta = abs(actual_float - expected_float) / max(abs(expected_float), 1e-12)
    else:
        delta = abs(actual_float - expected_float)
    return _check(delta <= tolerance, name, "", actual_float, expected_float, tolerance, mode, delta=delta)


def _check(
    passed: bool,
    name: str,
    note: str,
    actual: Any,
    expected: Any,
    tolerance: float,
    mode: str,
    *,
    delta: float | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "actual": _jsonable(actual),
        "expected": _jsonable(expected),
        "delta": delta,
        "tolerance": tolerance,
        "tolerance_mode": mode,
        "note": note,
    }


def _window_actual(window: Any) -> dict[str, Any]:
    if window is None:
        return {}
    diagnostics = dict(window.diagnostics or {})
    return {
        "window_id": window.window_id,
        "lag_seconds": window.lag_seconds,
        "co2_lag_seconds": diagnostics.get("co2_lag_seconds"),
        "lag_confidence": window.lag_confidence,
        "raw_flux": window.raw_flux,
        "density_corrected_flux": window.density_corrected_flux,
        "primary_flux": window.primary_flux,
        "primary_flux_source": window.primary_flux_source,
        "qc_grade": window.qc_grade,
        "anomaly_type": window.anomaly_type,
        "reason": window.reason,
        "qc_flags": list(window.qc_flags),
        "issues": diagnostics.get("issues", []),
        "qc_reasons": diagnostics.get("qc_reasons", []),
        "rotation_mode": window.rotation_mode,
        "rotation_applied": diagnostics.get("rotation_applied"),
        "applied_rotation_impl": diagnostics.get("applied_rotation_impl"),
        "rotation_alpha_deg": diagnostics.get("rotation_alpha_deg"),
        "rotation_beta_deg": diagnostics.get("rotation_beta_deg"),
        "mean_rotated_w": diagnostics.get("mean_rotated_w"),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
