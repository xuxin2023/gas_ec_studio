from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from core.comparison.attribution import classify_compare_result
from core.comparison.eddypro_comparator import EddyProComparator
from models.comparison_models import EddyProCompareResult, WindowCompareResult


def _window(
    *,
    window_key: str = "w1",
    lag_delta: float | None = 0.0,
    flux_delta: float | None = 0.0,
    correction_factor_delta: float | None = 0.0,
    notes: list[str] | None = None,
) -> WindowCompareResult:
    start = datetime(2026, 4, 18, 9, 0, 0)
    end = start + timedelta(minutes=30)
    return WindowCompareResult(
        window_key=window_key,
        start_time=start,
        end_time=end,
        current_lag_seconds=2.5,
        reference_lag_seconds=2.5 - (lag_delta or 0.0),
        lag_delta=lag_delta,
        current_flux=0.52,
        reference_flux=0.52 - (flux_delta or 0.0),
        flux_delta=flux_delta,
        current_correction_factor=1.08,
        reference_correction_factor=1.08 - (correction_factor_delta or 0.0),
        correction_factor_delta=correction_factor_delta,
        current_qc_grade="可用",
        reference_qc_grade="可用",
        qc_match=True,
        notes=list(notes or []),
    )


def _compare_result(
    *,
    window_results: list[WindowCompareResult] | None = None,
    avg_lag_delta: float | None = 0.0,
    avg_flux_delta: float | None = 0.0,
    avg_correction_factor_delta: float | None = 0.0,
    unmatched_current_count: int = 0,
    unmatched_reference_count: int = 0,
    notes: list[str] | None = None,
) -> EddyProCompareResult:
    created_at = datetime(2026, 4, 19, 10, 0, 0)
    windows = list(window_results or [_window()])
    return EddyProCompareResult(
        compare_id="compare_demo",
        created_at=created_at,
        current_source={"export_dir": "runtime_data/exports/results/demo"},
        reference_source={"reference_dir": "reference/demo"},
        summary_metrics={
            "compare_id": "compare_demo",
            "created_at": created_at.isoformat(),
            "current_window_count": len(windows),
            "reference_window_count": len(windows),
            "matched_window_count": max(0, len(windows) - unmatched_current_count),
            "unmatched_current_count": unmatched_current_count,
            "unmatched_reference_count": unmatched_reference_count,
            "avg_lag_delta": avg_lag_delta,
            "avg_flux_delta": avg_flux_delta,
            "avg_correction_factor_delta": avg_correction_factor_delta,
            "qc_match_ratio": 1.0,
        },
        window_results=windows,
        risk_summary=[],
        notes=list(notes or []),
    )


def _rp_run(**window_fields):
    window = SimpleNamespace(
        window_id="w1",
        start_time=datetime(2026, 4, 18, 9, 0, 0),
        end_time=datetime(2026, 4, 18, 9, 30, 0),
        qc_score=window_fields.get("qc_score", 85.0),
        stationarity_score=window_fields.get("stationarity_score", 85.0),
        turbulence_score=window_fields.get("turbulence_score", 85.0),
        ustar=window_fields.get("ustar", 0.35),
        qc_matrix=window_fields.get("qc_matrix", {}),
        qc_reasons=window_fields.get("qc_reasons", []),
    )
    return SimpleNamespace(windows=[window])


def _spectral_run(**window_fields):
    window = SimpleNamespace(
        window_id="w1",
        start_time=datetime(2026, 4, 18, 9, 0, 0),
        end_time=datetime(2026, 4, 18, 9, 30, 0),
        correction_factor_components=window_fields.get(
            " correction_factor_components".strip(),
            {
                "base_factor": 1.08,
                "tube_component": 1.0,
                "separation_component": 1.0,
                "path_component": 1.0,
                "phase_component": 1.0,
                "total_factor": 1.08,
            },
        ),
        provenance_notes=window_fields.get("provenance_notes", []),
        transfer_function_components=window_fields.get("transfer_function_components", {}),
    )
    return SimpleNamespace(windows=[window])


def test_lag_delta_large_maps_to_lag_method_or_lag_quality() -> None:
    compare_result = _compare_result(avg_lag_delta=1.25, window_results=[_window(lag_delta=1.3)])

    result = classify_compare_result(compare_result)

    assert result.dominant_causes[0] == "lag_method_or_lag_quality"


def test_unmatched_windows_map_to_window_alignment() -> None:
    compare_result = _compare_result(
        unmatched_current_count=3,
        unmatched_reference_count=2,
        window_results=[_window(notes=["current window has no matched EddyPro reference window"])],
    )

    result = classify_compare_result(compare_result)

    assert result.dominant_causes[0] == "window_alignment"


def test_correction_factor_delta_and_high_tube_component_map_to_tube_attenuation() -> None:
    compare_result = _compare_result(avg_correction_factor_delta=0.12, window_results=[_window(correction_factor_delta=0.14)])
    current_runs = {
        "spectral_run": _spectral_run(
            correction_factor_components={
                "base_factor": 1.18,
                "tube_component": 1.12,
                "separation_component": 1.01,
                "path_component": 1.01,
                "phase_component": 1.02,
                "total_factor": 1.18,
            }
        )
    }

    result = classify_compare_result(compare_result, current_runs=current_runs)

    assert result.dominant_causes[0] == "tube_attenuation"


def test_component_specific_causes_cover_separation_path_and_phase() -> None:
    scenarios = [
        ("sensor_separation", {"separation_component": 1.11, "path_component": 1.01, "phase_component": 1.01, "tube_component": 1.01}),
        ("path_averaging", {"separation_component": 1.01, "path_component": 1.12, "phase_component": 1.01, "tube_component": 1.01}),
        ("phase_or_lag_transfer", {"separation_component": 1.01, "path_component": 1.01, "phase_component": 1.13, "tube_component": 1.01}),
    ]

    for expected_cause, component_values in scenarios:
        compare_result = _compare_result(avg_correction_factor_delta=0.10, window_results=[_window(correction_factor_delta=0.10)])
        current_runs = {
            "spectral_run": _spectral_run(
                correction_factor_components={"base_factor": 1.15, "total_factor": 1.15, **component_values}
            )
        }
        result = classify_compare_result(compare_result, current_runs=current_runs)
        assert result.dominant_causes[0] == expected_cause


def test_poor_rp_qc_or_turbulence_maps_to_rp_or_turbulence_causes() -> None:
    compare_result = _compare_result(avg_flux_delta=0.22, window_results=[_window(flux_delta=0.24)])
    current_runs = {
        "rp_run": _rp_run(qc_score=45.0, stationarity_score=48.0, turbulence_score=42.0, ustar=0.08),
    }

    result = classify_compare_result(compare_result, current_runs=current_runs)

    assert result.dominant_causes[0] in {"rp_qc_or_stationarity", "turbulence_or_ustar"}


def test_missing_metadata_notes_map_to_field_mapping_or_missing_metadata() -> None:
    compare_result = _compare_result(window_results=[_window()], notes=["spectral_qc_results.csv missing from current export"])
    current_runs = {"spectral_run": _spectral_run(provenance_notes=["tube attenuation fell back to neutral because metadata are unavailable"])}

    result = classify_compare_result(compare_result, current_runs=current_runs, reference_meta={"missing_metadata": True})

    assert result.dominant_causes[0] == "field_mapping_or_missing_metadata"


def test_insufficient_information_returns_unknown_without_crashing() -> None:
    compare_result = _compare_result(
        avg_lag_delta=0.0,
        avg_flux_delta=0.0,
        avg_correction_factor_delta=0.0,
        window_results=[_window(lag_delta=0.0, flux_delta=0.0, correction_factor_delta=0.0)],
    )

    result = classify_compare_result(compare_result)

    assert result.dominant_causes[0] == "unknown"
    assert result.summary_text


def test_comparator_helper_builds_attribution() -> None:
    comparator = EddyProComparator()
    compare_result = _compare_result(avg_lag_delta=1.1, window_results=[_window(lag_delta=1.1)])

    attribution = comparator.build_attribution(compare_result)

    assert attribution.compare_id == compare_result.compare_id
    assert attribution.dominant_causes
