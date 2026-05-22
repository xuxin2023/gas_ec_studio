from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.ec_rp.analysis import compute_footprint_2d_grid, run_method_compare
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.5 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.08 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.8 + 0.25 * np.cos(2.0 * np.pi * 0.02 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.3 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                case_temp_c=float(temp[index] - 0.1),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def _v3i_config(rows: list[NormalizedHFFrame]) -> dict[str, object]:
    freq = np.linspace(0.05, 4.0, 32)
    cospectrum = np.exp(-freq / 1.5)
    return {
        "steps": {
            "window_sampling": {"sample_hz": 10.0, "window_minutes": 0.5},
            "lag": {"search_window_s": 1.5, "expected_lag_s": 0.5},
            "rotation": {"rotation_mode": "double"},
        },
        "footprint": {
            "enabled": True,
            "method": "kljun",
            "z_m": 3.0,
            "canopy_height_m": 5.0,
            "z0": 0.12,
            "ol": -100.0,
            "grid_enabled": True,
            "grid_x_bins": 16,
            "grid_y_bins": 11,
        },
        "uncertainty": {
            "method": "mann_lenschow",
            "integral_timescale_s": 5.0,
            "confidence_level": 0.95,
        },
        "spectral_correction": {
            "enabled": True,
            "method": "fratini",
            "path_length_m": 0.15,
            "sensor_sep_m": 0.2,
            "response_time_s": 0.1,
            "z_m": 3.0,
            "ol": -100.0,
            "use_fcc_measured_cospectrum": True,
            "fcc_source_run_id": "fcc_test_run",
            "fcc_measured_cospectra": [
                {
                    "window_id": "fcc_w001",
                    "start_time": rows[0].timestamp.isoformat(),
                    "end_time": rows[299].timestamp.isoformat(),
                    "cross_freq": [float(value) for value in freq],
                    "cross_value": [float(value) for value in cospectrum],
                    "source_run_id": "fcc_test_run",
                    "source_qc_grade": "A",
                    "provenance_notes": ["synthetic measured cospectrum for v3i test"],
                }
            ],
        },
        "method_compare": {
            "enabled": True,
            "families": ["footprint", "uncertainty", "spectral_correction"],
            "deviation_threshold": 0.20,
            "footprint_methods": ["kljun", "kormann_meixner", "hsieh"],
            "uncertainty_methods": ["mann_lenschow", "finkelstein_sims"],
            "spectral_correction_methods": ["massman", "horst", "ibrom", "fratini"],
        },
        "network_output": {"schema_target": "FLUXNET", "timestamp_refers_to": "start"},
    }


def test_footprint_2d_grid_is_normalized_and_exportable() -> None:
    grid = compute_footprint_2d_grid(
        method="kljun",
        ustar=0.32,
        mean_wind_speed=2.7,
        sigma_v=0.42,
        z_m=3.0,
        h=5.0,
        ol=-100.0,
        x_bins=18,
        y_bins=13,
    )
    assert grid is not None
    assert grid.method == "kljun"
    assert len(grid.x_coords_m) == 18
    assert len(grid.y_coords_m) == 13
    assert len(grid.contribution_grid) == 13
    assert len(grid.contribution_grid[0]) == 18
    assert math.isclose(sum(sum(row) for row in grid.contribution_grid), 1.0, rel_tol=1e-4, abs_tol=1e-4)
    assert grid.peak_downwind_m > 0.0
    assert "x90" in grid.contribution_contours_m
    assert "Diagnostic 2D" in grid.detail["limitations"][0]


def test_run_method_compare_returns_family_recommendations() -> None:
    result = run_method_compare(
        method_family="spectral_correction",
        selected_method="fratini",
        methods_to_run=["massman", "horst", "ibrom", "fratini"],
        window_params={
            "path_length_m": 0.15,
            "sensor_sep_m": 0.2,
            "response_time_s": 0.1,
            "sample_rate_hz": 10.0,
            "averaging_period_s": 30.0,
            "wind_speed": 2.6,
            "z_m": 3.0,
            "ustar": 0.31,
            "ol": -80.0,
            "measured_cospectrum_freq": np.linspace(0.05, 4.0, 32),
            "measured_cospectrum_value": np.exp(-np.linspace(0.05, 4.0, 32) / 1.5),
        },
    )
    assert result.status == "ok"
    assert result.primary_metric == "correction_factor"
    assert "fratini" in result.primary_outputs
    assert result.consensus_value is not None
    assert result.recommendation


def test_pipeline_exports_footprint_2d_method_compare_and_cospectrum_match(tmp_path: Path) -> None:
    rows = _make_rows()
    config = _v3i_config(rows)
    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3I", name="v3i"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )

    assert result.summary["status"] == "ok"
    first = result.windows[0]
    diagnostics = first.diagnostics
    assert diagnostics["footprint_2d_grid_status"] == "ok"
    assert diagnostics["footprint_2d_grid"]["detail"]["grid_shape"] == [11, 16]
    assert diagnostics["method_compare_enabled"] is True
    assert set(diagnostics["method_compare_summary"]) == {"footprint", "uncertainty", "spectral_correction"}
    assert diagnostics["method_compare_recommendations"]
    assert diagnostics["spectral_correction_measured_cospectrum_source"] == "fcc_auto"
    assert diagnostics["spectral_correction_cospectrum_match"]["match_strategy"] == "exact_time"
    assert diagnostics["spectral_correction_cospectrum_match"]["match_quality"] == 1.0

    assert result.summary["footprint_2d_summary"]["window_count"] >= 1
    assert result.summary["method_compare_summary"]["status"] == "enabled"
    assert "method_rollup" in result.artifacts
    assert result.artifacts["method_rollup"]["method_compare_summary"]["status"] == "enabled"

    exporter = ResultExporter(runtime_root=tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I", name="v3i"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        report_payload={"title": "v3i"},
        report_key="method_provenance",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    footprint_path = Path(files["footprint_2d_artifact"])
    compare_path = Path(files["method_compare_artifact"])
    manifest_path = Path(files["export_manifest"])
    full_output_path = Path(files["full_output"])

    footprint_payload = json.loads(footprint_path.read_text(encoding="utf-8"))
    compare_payload = json.loads(compare_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    full_output_csv = full_output_path.read_text(encoding="utf-8")

    assert footprint_payload["artifact_type"] == "footprint_2d_grid"
    assert footprint_payload["windows"][0]["grid"]["detail"]["grid_shape"] == [11, 16]
    assert compare_payload["artifact_type"] == "method_compare"
    assert compare_payload["summary"]["status"] == "enabled"
    assert manifest["footprint_2d_artifact"] == str(footprint_path)
    assert manifest["method_compare_artifact"] == str(compare_path)
    assert manifest["method_compare_summary"]["status"] == "enabled"
    assert "footprint_2d_grid_status" in full_output_csv
    assert "method_compare_summary" in full_output_csv
    assert "spectral_correction_cospectrum_match" in full_output_csv


def test_v3j_exports_method_parity_contour_and_performance_profile(tmp_path: Path) -> None:
    rows = _make_rows(samples=900)
    config = _v3i_config(rows)
    config.update(
        {
            "rotation_mode": "double",
            "detrend_mode": "block_mean",
            "density_correction_mode": "wpl",
            "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.5, "expected_lag_s": 0.5},
            "benchmark": {
                "status": "active",
                "target": "EddyPro synthetic reference",
                "reference_id": "eddypro_v7_synthetic_001",
                "flux_rel_threshold": 0.20,
                "lag_abs_threshold_s": 0.5,
                "wpl_rel_threshold": 0.20,
                "qc_grade_must_match": False,
            },
        }
    )
    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3J", name="v3j"),
        site=SiteProfile(station_code="SITE-V3J", station_name="V3J Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:02",
    )

    assert result.summary["performance_profile"]["status"] == "ok"
    assert result.summary["performance_profile"]["profiled_window_count"] >= 1
    assert result.summary["performance_profile"]["footprint_2d_profiled"] is True
    assert result.summary["performance_profile"]["method_compare_profiled"] is True

    exporter = ResultExporter(runtime_root=tmp_path)
    bundle = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3J", name="v3j"),
        site=SiteProfile(station_code="SITE-V3J", station_name="V3J Site"),
        report_payload={"title": "v3j"},
        report_key="method_compare",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    required = [
        "method_parity_matrix_artifact",
        "method_parity_matrix_csv",
        "footprint_2d_contour_svg",
        "footprint_2d_grid_csv",
        "performance_profile_artifact",
        "benchmark_summary_artifact",
        "parity_artifact",
    ]
    for key in required:
        assert key in files
        assert Path(files[key]).exists()

    matrix = json.loads(Path(files["method_parity_matrix_artifact"]).read_text(encoding="utf-8"))
    matrix_rows = {row["family"]: row for row in matrix["rows"]}
    assert matrix["reference_profile"]["status"] == "ready"
    assert matrix["metadata_coverage"]["reported_count"] == 5
    assert matrix["metadata_coverage"]["total_count"] == 7
    assert set(matrix["not_reported_families"]) == {"footprint", "uncertainty"}
    assert matrix_rows["rotation"]["status"] == "match"
    assert matrix_rows["rotation"]["reference_field"] == "rotation_mode"
    assert matrix_rows["rotation"]["reference_evidence_source"] == "processing_settings"
    assert matrix_rows["rotation"]["normalized_gas_ec_studio_method"] == "double"
    assert matrix_rows["detrend"]["normalized_eddypro_method"] == "block_mean"
    assert matrix_rows["lag"]["status"] == "match"
    assert matrix_rows["density_correction"]["status"] == "match"
    assert matrix_rows["footprint"]["status"] == "not_reported"
    assert matrix_rows["footprint"]["reference_evidence_source"] == "missing_from_reference_metadata"
    assert matrix_rows["uncertainty"]["status"] == "not_reported"
    assert matrix["truthfulness_note"]

    contour_svg = Path(files["footprint_2d_contour_svg"]).read_text(encoding="utf-8")
    grid_csv = Path(files["footprint_2d_grid_csv"]).read_text(encoding="utf-8")
    assert "<svg" in contour_svg
    assert ">x90</text>" in contour_svg
    assert "window_id,method,x_m,y_m,contribution" in grid_csv

    performance = json.loads(Path(files["performance_profile_artifact"]).read_text(encoding="utf-8"))
    assert performance["artifact_type"] == "performance_profile"
    assert performance["run_summary"]["profiled_window_count"] >= 1
    assert performance["windows"][0]["sections_ms"]["footprint_2d_ms"] >= 0.0
    assert performance["windows"][0]["sections_ms"]["method_compare_ms"] >= 0.0

    manifest = json.loads(Path(files["export_manifest"]).read_text(encoding="utf-8"))
    assert manifest["method_parity_matrix_artifact"] == files["method_parity_matrix_artifact"]
    assert manifest["method_parity_matrix_csv"] == files["method_parity_matrix_csv"]
    assert manifest["footprint_2d_contour_svg"] == files["footprint_2d_contour_svg"]
    assert manifest["footprint_2d_grid_csv"] == files["footprint_2d_grid_csv"]
    assert manifest["performance_profile_artifact"] == files["performance_profile_artifact"]
    assert manifest["method_parity_matrix"]["reference_profile"]["status"] == "ready"

    benchmark_summary = json.loads(Path(files["benchmark_summary_artifact"]).read_text(encoding="utf-8"))
    parity = json.loads(Path(files["parity_artifact"]).read_text(encoding="utf-8"))
    assert benchmark_summary["method_parity_matrix"]["reference_profile"]["status"] == "ready"
    assert parity["method_parity_matrix"]["reference_profile"]["status"] == "ready"
