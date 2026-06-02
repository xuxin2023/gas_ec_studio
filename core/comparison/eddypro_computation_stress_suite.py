from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from core.ec_rp.analysis import (
    compute_footprint,
    compute_footprint_2d_grid,
    compute_li7700_correction_sequence,
    compute_li7700_status_diagnostics,
    compute_spectral_correction,
    compute_uncertainty_finkelstein_sims,
    compute_uncertainty_mann_lenschow,
)
from models.hf_models import FrameQuality, NormalizedHFFrame


def build_eddypro_computation_stress_suite(
    *,
    workspace_root: str | Path | None = None,
    include_slow_cases: bool = False,
) -> dict[str, Any]:
    """Run deterministic source-derived stress checks for core EC calculations."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    cases = [
        _footprint_stress_case(),
        _uncertainty_stress_case(),
        _spectral_correction_stress_case(),
        _ch4_li7700_stress_case(),
    ]
    if include_slow_cases:
        cases.append(_long_autocorrelation_uncertainty_case())
    passed = [case for case in cases if case["status"] == "pass"]
    failed = [case for case in cases if case["status"] != "pass"]
    family_counts: dict[str, int] = {}
    for case in cases:
        family = str(case.get("family", "unknown"))
        family_counts[family] = family_counts.get(family, 0) + 1
    return {
        "artifact_type": "eddypro_computation_stress_suite_v1",
        "suite_id": "eddypro_computation_stress_suite_v1",
        "generated_at": datetime.now().isoformat(),
        "workspace_root": str(root),
        "status": "pass" if not failed else "fail",
        "case_count": len(cases),
        "passed_case_count": len(passed),
        "failed_case_count": len(failed),
        "pass_rate": round(len(passed) / max(1, len(cases)), 4),
        "family_counts": dict(sorted(family_counts.items())),
        "failed_cases": [
            {"case_id": case["case_id"], "family": case["family"], "failure_reasons": case.get("failure_reasons", [])}
            for case in failed
        ],
        "cases": cases,
        "claim_boundary": {
            "can_support_source_derived_computational_superiority": not failed,
            "can_claim_official_field_numeric_parity": False,
            "can_replace_real_eddypro_raw_to_final_fixture": False,
            "can_ignore_real_data_blocker_for_algorithm_stress": True,
        },
        "truthfulness_boundary": (
            "This suite stress-tests EC computation families with deterministic synthetic/source-derived inputs. "
            "It strengthens algorithm-readiness evidence but does not replace public/anonymized raw EddyPro "
            "fixtures for official numeric parity."
        ),
        "known_limitations": [
            "Synthetic stress cases exercise invariants, edge conditions, and method provenance rather than site-specific field truth.",
            "Official EddyPro raw-to-final parity remains blocked until paired raw/settings/Full_Output evidence exists.",
            "Stress cases should expand whenever new computation families or method variants are added.",
        ],
    }


def _footprint_stress_case() -> dict[str, Any]:
    methods = ["kljun", "kormann_meixner", "hsieh"]
    stability_values = [-120.0, None, 160.0]
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for method in methods:
        for ol in stability_values:
            fp = compute_footprint(
                method=method,
                ustar=0.38,
                mean_wind_speed=3.4,
                sigma_v=0.92,
                z_m=4.0,
                h=1.2,
                z0=0.12,
                ol=ol,
            )
            ordered = _ordered_contribution_distances(fp.contribution_distances)
            if fp.detail.get("status") != "ok":
                failures.append(f"{method}:{ol}:status={fp.detail.get('status')}")
            if fp.peak_distance_m <= 0.0 or fp.offset_distance_m < 0.0:
                failures.append(f"{method}:{ol}:non_positive_distance")
            if not ordered:
                failures.append(f"{method}:{ol}:unordered_contributions")
            results.append(
                {
                    "method": method,
                    "ol_m": ol,
                    "peak_distance_m": fp.peak_distance_m,
                    "offset_distance_m": fp.offset_distance_m,
                    "contribution_distances": dict(fp.contribution_distances),
                    "ordered_contributions": ordered,
                    "provenance": str(fp.detail.get("provenance", "")),
                }
            )
    grid_source = compute_footprint(
        method="kljun",
        ustar=0.38,
        mean_wind_speed=3.4,
        sigma_v=0.92,
        z_m=4.0,
        h=1.2,
        z0=0.12,
        ol=-120.0,
    )
    grid = compute_footprint_2d_grid(
        footprint=grid_source,
        method="kljun",
        ustar=0.38,
        mean_wind_speed=3.4,
        sigma_v=0.92,
        z_m=4.0,
        h=1.2,
        z0=0.12,
        ol=-120.0,
        x_bins=28,
        y_bins=21,
    )
    grid_sum = float(np.sum(np.asarray(grid.contribution_grid, dtype=float)))
    if not math.isclose(grid_sum, 1.0, rel_tol=5.0e-3, abs_tol=5.0e-3):
        failures.append(f"footprint_2d_grid_sum={grid_sum:.6f}")
    return _case_payload(
        case_id="footprint_family_stability_sweep",
        family="footprint",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "method_count": len(methods),
            "scenario_count": len(results),
            "grid_sum": round(grid_sum, 6),
            "grid_peak_downwind_m": grid.peak_downwind_m,
            "grid_half_width_m": grid.half_width_m,
        },
        details={"results": results, "grid_detail": grid.detail},
    )


def _uncertainty_stress_case() -> dict[str, Any]:
    rng = np.random.default_rng(20260602)
    n = 2400
    w = rng.normal(0.0, 0.42, n)
    scalar = 0.72 * np.roll(w, 4) + rng.normal(0.0, 0.08, n)
    ml = compute_uncertainty_mann_lenschow(
        cov_w_scalar=0.045,
        var_w=0.31,
        var_scalar=1.85,
        n_samples=18000,
        averaging_period_s=1800.0,
        integral_timescale_s=7.5,
    )
    fs = compute_uncertainty_finkelstein_sims(
        w_series=w,
        scalar_series=scalar,
        sample_rate_hz=10.0,
        averaging_period_s=240.0,
    )
    failures: list[str] = []
    for result in (ml, fs):
        method = str(result.get("method", ""))
        if result.get("status") != "ok":
            failures.append(f"{method}:status={result.get('status')}")
        if not _positive_number(result.get("random_error")):
            failures.append(f"{method}:random_error_not_positive")
        lower = result.get("interval_lower")
        upper = result.get("interval_upper")
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)) or lower >= upper:
            failures.append(f"{method}:invalid_uncertainty_band")
    return _case_payload(
        case_id="random_uncertainty_family_autocorrelation_sweep",
        family="uncertainty",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "mann_lenschow_random_error": ml.get("random_error"),
            "finkelstein_sims_random_error": fs.get("random_error"),
            "mann_lenschow_relative_error": ml.get("relative_error"),
            "finkelstein_sims_relative_error": fs.get("relative_error"),
        },
        details={"mann_lenschow": ml, "finkelstein_sims": fs},
    )


def _spectral_correction_stress_case() -> dict[str, Any]:
    methods = ["massman", "horst", "ibrom", "fratini"]
    freq = np.geomspace(0.001, 5.0, 128)
    measured = np.exp(-freq / 0.8) / np.sqrt(freq)
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    for method in methods:
        result = compute_spectral_correction(
            method=method,
            path_length_m=0.18,
            sensor_sep_m=0.24,
            response_time_s=0.13,
            sample_rate_hz=20.0,
            averaging_period_s=1800.0,
            wind_speed=3.2,
            z_m=4.0,
            ustar=0.42,
            ol=-80.0,
            measured_cospectrum_freq=freq if method == "fratini" else None,
            measured_cospectrum_value=measured if method == "fratini" else None,
        )
        factor = result.get("correction_factor")
        if result.get("status") != "ok":
            failures.append(f"{method}:status={result.get('status')}")
        if not isinstance(factor, (int, float)) or not math.isfinite(float(factor)) or float(factor) < 1.0:
            failures.append(f"{method}:invalid_correction_factor={factor}")
        if method == "fratini" and not bool(result.get("components", {}).get("uses_measured_cospectrum")):
            failures.append("fratini:measured_cospectrum_not_used")
        results.append(
            {
                "method": method,
                "status": result.get("status"),
                "correction_factor": factor,
                "provenance": result.get("provenance", ""),
                "components": result.get("components", {}),
            }
        )
    return _case_payload(
        case_id="spectral_correction_family_measured_cospectrum_sweep",
        family="spectral_correction",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "method_count": len(methods),
            "max_correction_factor": max(float(item["correction_factor"]) for item in results),
            "fratini_measured_cospectrum_used": bool(results[-1]["components"].get("uses_measured_cospectrum")),
        },
        details={"results": results},
    )


def _ch4_li7700_stress_case() -> dict[str, Any]:
    rows = _make_li7700_rows()
    status = compute_li7700_status_diagnostics(
        rows=rows,
        config={"min_rssi_warning_pct": 40.0, "min_rssi_fail_pct": 20.0, "require_lock": True},
    )
    sequence = compute_li7700_correction_sequence(
        ch4_metrics={
            "status": "computed",
            "selected_method": "li_7700_level0_covariance",
            "ch4_flux_nmol_m2_s": 12.4,
        },
        mean_h2o_mmol=18.0,
        mean_pressure_kpa=98.7,
        mean_temp_c=27.0,
        spectral_correction_factor=1.18,
        config={
            "coefficient_profile_id": "stress_li7700_profile",
            "coefficient_registry_status": "source_derived_stress",
            "coefficient_profile_provenance": "deterministic stress profile",
            "li7700_status_diagnostics": status,
            "spectroscopic_correction": {
                "mode": "empirical",
                "pressure_coefficient": 0.0008,
                "temperature_coefficient": 0.0012,
                "h2o_coefficient": 0.08,
            },
            "self_heating_correction": {
                "enabled": True,
                "slope_per_c": 0.0004,
                "reference_temp_c": 20.0,
            },
        },
    )
    failures: list[str] = []
    if status.get("status") != "pass":
        failures.append(f"li7700_status={status.get('status')}")
    if sequence.get("status") != "computed":
        failures.append(f"li7700_sequence={sequence.get('status')}")
    if not _positive_number(sequence.get("final_flux_nmol_m2_s")):
        failures.append("li7700_final_flux_not_positive")
    levels = dict(sequence.get("levels", {}) or {})
    if set(levels) != {"level0", "level1", "level2", "level3"}:
        failures.append("li7700_levels_incomplete")
    if float(sequence.get("water_vapor_dilution_factor", 0.0) or 0.0) < 1.0:
        failures.append("li7700_density_factor_lt_one")
    return _case_payload(
        case_id="ch4_li7700_correction_sequence_policy_sweep",
        family="ch4_li7700",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "status_diagnostics_status": status.get("status"),
            "rssi_min_pct": status.get("rssi_min_pct"),
            "final_flux_nmol_m2_s": sequence.get("final_flux_nmol_m2_s"),
            "spectral_correction_factor": sequence.get("spectral_correction_factor"),
            "water_vapor_dilution_factor": sequence.get("water_vapor_dilution_factor"),
        },
        details={"li7700_status_diagnostics": status, "li7700_correction_sequence": sequence},
    )


def _long_autocorrelation_uncertainty_case() -> dict[str, Any]:
    rng = np.random.default_rng(20260603)
    n = 6000
    w = rng.normal(0.0, 0.35, n)
    scalar = 0.5 * np.roll(w, 7) + rng.normal(0.0, 0.12, n)
    result = compute_uncertainty_finkelstein_sims(
        w_series=w,
        scalar_series=scalar,
        sample_rate_hz=20.0,
        averaging_period_s=300.0,
    )
    failures = [] if result.get("status") == "ok" and _positive_number(result.get("random_error")) else ["long_fs_uncertainty_failed"]
    return _case_payload(
        case_id="slow_random_uncertainty_long_autocorrelation",
        family="uncertainty",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={"random_error": result.get("random_error"), "n_samples": n},
        details={"finkelstein_sims": result},
    )


def _make_li7700_rows(samples: int = 120) -> list[NormalizedHFFrame]:
    start = datetime(2026, 6, 2, 9, 0, 0)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        payload = {
            "u": 2.4 + 0.1 * math.sin(index / 9.0),
            "v": 0.2 * math.cos(index / 13.0),
            "w": 0.35 * math.sin(index / 5.0),
            "li7700_rssi": 72.0 + 4.0 * math.sin(index / 17.0),
            "li7700_signal_strength": 75.0 + 3.0 * math.cos(index / 19.0),
            "mirror_dirty": False,
            "pll_lock": True,
            "li7700_status_word": 0,
        }
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=index / 10.0),
                device_uid="stress-li7700",
                device_id="LI7700",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=410.0,
                h2o_mmol=18.0,
                pressure_kpa=98.7,
                chamber_temp_c=27.0,
                ch4_ppb=1900.0 + 4.0 * math.sin(index / 6.0),
                raw_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
        )
    return rows


def _case_payload(
    *,
    case_id: str,
    family: str,
    status: str,
    failure_reasons: list[str],
    metrics: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": family,
        "status": status,
        "failure_reasons": failure_reasons,
        "metrics": metrics,
        "details": details,
        "claim_boundary": {
            "source_derived_stress_evidence": status == "pass",
            "official_numeric_parity_evidence": False,
        },
    }


def _ordered_contribution_distances(values: dict[str, Any]) -> bool:
    ordered = [float(values.get(key, 0.0) or 0.0) for key in ("x10", "x30", "x50", "x70", "x90")]
    return all(value > 0.0 for value in ordered) and ordered == sorted(ordered)


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0.0
