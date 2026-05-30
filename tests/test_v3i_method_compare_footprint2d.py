from __future__ import annotations

import json
import math
import subprocess
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

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
            "land_cover_grid": [
                ["crop" if col < 8 else "forest" for col in range(16)]
                for _ in range(11)
            ],
            "land_cover_legend": {"crop": "cropland", "forest": "forest_edge"},
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


def _web_mercator_xy(lon: float, lat: float) -> tuple[float, float]:
    radius_m = 6_378_137.0
    clamped_lat = max(min(float(lat), 85.05112878), -85.05112878)
    x = radius_m * math.radians(float(lon))
    y = radius_m * math.log(math.tan(math.pi / 4.0 + math.radians(clamped_lat) / 2.0))
    return x, y


def _rasterio_project_xy(src_crs: str, dst_crs: str, x: float, y: float) -> tuple[float, float]:
    script = r'''
import json
import os
import sys

try:
    import rasterio
    from rasterio.warp import transform
except Exception as exc:
    print(json.dumps({"status": "not_available", "error": str(exc)}))
    sys.stdout.flush()
    os._exit(0)

try:
    out_x, out_y = transform(sys.argv[1], sys.argv[2], [float(sys.argv[3])], [float(sys.argv[4])])
    print(json.dumps({"status": "ok", "x": float(out_x[0]), "y": float(out_y[0])}))
except Exception as exc:
    print(json.dumps({"status": "error", "error": str(exc)}))
sys.stdout.flush()
os._exit(0)
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, src_crs, dst_crs, str(float(x)), str(float(y))],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = (completed.stdout or "").strip()
    if not stdout:
        pytest.skip(f"rasterio transform unavailable: {(completed.stderr or '').strip()}")
    payload = json.loads(stdout.splitlines()[-1])
    if payload.get("status") != "ok":
        pytest.skip(f"rasterio transform unavailable: {payload.get('error', payload.get('status'))}")
    return float(payload["x"]), float(payload["y"])


def _write_rasterio_land_cover_geotiff(
    *,
    path: Path,
    crs: str,
    transform: list[float],
    rows: list[list[int]],
    nodata: int = -9999,
) -> None:
    script = r'''
import json
import os
import sys

payload = json.loads(sys.stdin.read() or "{}")
try:
    import numpy as np
    import rasterio
    from affine import Affine
except Exception as exc:
    print(json.dumps({"status": "not_available", "error": str(exc)}))
    sys.stdout.flush()
    os._exit(0)

try:
    rows = payload["rows"]
    array = np.asarray(rows, dtype=np.int16)
    transform = Affine(*[float(value) for value in payload["transform"]])
    with rasterio.open(
        payload["path"],
        "w",
        driver="GTiff",
        height=int(array.shape[0]),
        width=int(array.shape[1]),
        count=1,
        dtype=str(array.dtype),
        crs=payload["crs"],
        transform=transform,
        nodata=int(payload["nodata"]),
    ) as dataset:
        dataset.write(array, 1)
    print(json.dumps({"status": "ok"}))
except Exception as exc:
    print(json.dumps({"status": "error", "error": str(exc)}))
sys.stdout.flush()
os._exit(0)
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"path": str(path), "crs": crs, "transform": transform, "rows": rows, "nodata": nodata}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = (completed.stdout or "").strip()
    if not stdout:
        pytest.skip(f"rasterio GeoTIFF writer unavailable: {(completed.stderr or '').strip()}")
    payload = json.loads(stdout.splitlines()[-1])
    if payload.get("status") != "ok":
        pytest.skip(f"rasterio GeoTIFF writer unavailable: {payload.get('error', payload.get('status'))}")


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
    site = SiteProfile(station_code="SITE-V3I", station_name="V3I Site", latitude=35.1234, longitude=-97.5678)
    bundle = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I", name="v3i"),
        site=site,
        report_payload={"title": "v3i"},
        report_key="method_provenance",
        full_output_mode="standard_schema",
    )
    files = bundle["files"]
    footprint_path = Path(files["footprint_2d_artifact"])
    geojson_path = Path(files["footprint_geojson_artifact"])
    geotiff_path = Path(files["footprint_geotiff_artifact"])
    overlay_path = Path(files["footprint_land_cover_overlay_artifact"])
    gis_validation_path = Path(files["footprint_gis_validation_artifact"])
    compare_path = Path(files["method_compare_artifact"])
    manifest_path = Path(files["export_manifest"])
    full_output_path = Path(files["full_output"])

    footprint_payload = json.loads(footprint_path.read_text(encoding="utf-8"))
    geojson_payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    geotiff_bytes = geotiff_path.read_bytes()
    overlay_payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    gis_validation = json.loads(gis_validation_path.read_text(encoding="utf-8"))
    compare_payload = json.loads(compare_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    full_output_csv = full_output_path.read_text(encoding="utf-8")

    assert footprint_payload["artifact_type"] == "footprint_2d_grid"
    assert footprint_payload["windows"][0]["grid"]["detail"]["grid_shape"] == [11, 16]
    assert geojson_payload["artifact_type"] == "footprint_geojson_v1"
    assert geojson_payload["status"] == "ok"
    assert geojson_payload["coordinate_reference_system"] == "EPSG:4326"
    assert geojson_payload["site"]["latitude"] == 35.1234
    assert geojson_payload["feature_count"] > 16
    assert geojson_payload["features"][0]["geometry"]["type"] == "Polygon"
    assert geotiff_bytes[:4] == b"II*\x00"
    assert struct.pack("<H", 322) in geotiff_bytes
    assert struct.pack("<H", 323) in geotiff_bytes
    assert struct.pack("<H", 324) in geotiff_bytes
    assert struct.pack("<H", 325) in geotiff_bytes
    assert struct.pack("<H", 33550) in geotiff_bytes
    assert struct.pack("<H", 34735) in geotiff_bytes
    assert overlay_payload["artifact_type"] == "footprint_land_cover_overlay_v1"
    assert overlay_payload["status"] == "ok"
    assert overlay_payload["classification_source"] == "grid"
    assert {row["land_cover"] for row in overlay_payload["classes"]} == {"cropland", "forest_edge"}
    assert math.isclose(sum(row["fraction"] for row in overlay_payload["classes"]), 1.0, rel_tol=1e-6)
    assert gis_validation["artifact_type"] == "footprint_gis_validation_v1"
    assert gis_validation["status"] == "ok_with_limitations"
    assert gis_validation["geotiff"]["status"] == "ok"
    assert gis_validation["geotiff"]["layout"] == "tiled"
    assert gis_validation["geotiff"]["tile_width"] >= 16
    assert gis_validation["geotiff"]["tile_length"] >= 16
    assert gis_validation["geotiff"]["has_internal_overviews"] is True
    assert gis_validation["geotiff"]["cog_readiness"] == "candidate"
    assert gis_validation["geotiff"]["range_readiness"] == "ok"
    assert gis_validation["geotiff"]["range_validation"]["ifd_count"] >= 2
    assert gis_validation["geotiff"]["range_validation"]["tile_data_after_metadata"] is True
    assert gis_validation["geotiff"]["range_validation"]["tile_offsets_monotonic"] is True
    assert gis_validation["geotiff"]["range_validation"]["tile_ranges_in_file"] is True
    assert gis_validation["geotiff"]["range_validation"]["reduced_image_count"] >= 1
    reader_validation = gis_validation["geotiff"]["external_reader_validation"]
    assert reader_validation["status"] in {"ok", "not_available"}
    if reader_validation["status"] == "ok":
        assert reader_validation["driver"] == "GTiff"
        assert reader_validation["crs"] == "EPSG:4326"
        assert reader_validation["width"] == 16
        assert reader_validation["height"] == 11
        assert reader_validation["overviews_band1"] == [2]
        assert math.isclose(reader_validation["data_sum_band1"], 1.0, rel_tol=1e-5, abs_tol=1e-5)
    cog_validator = gis_validation["geotiff"]["cog_validator_validation"]
    assert cog_validator["status"] in {"valid", "invalid", "not_available"}
    if cog_validator["status"] in {"valid", "invalid"}:
        assert cog_validator["package"] == "rio-cogeo"
        assert cog_validator["strict"] is True
    assert gis_validation["land_cover_overlay"]["classification_source"] == "grid"
    assert gis_validation["land_cover_raster"]["status"] == "not_configured"
    assert compare_payload["artifact_type"] == "method_compare"
    assert compare_payload["summary"]["status"] == "enabled"
    assert manifest["footprint_2d_artifact"] == str(footprint_path)
    assert manifest["footprint_geojson_artifact"] == str(geojson_path)
    assert manifest["footprint_geotiff_artifact"] == str(geotiff_path)
    assert manifest["footprint_land_cover_overlay_artifact"] == str(overlay_path)
    assert manifest["footprint_gis_validation_artifact"] == str(gis_validation_path)
    assert manifest["footprint_gis_validation"]["status"] == "ok_with_limitations"
    assert manifest["method_compare_artifact"] == str(compare_path)
    assert manifest["method_compare_summary"]["status"] == "enabled"
    assert "footprint_2d_grid_status" in full_output_csv
    assert "method_compare_summary" in full_output_csv
    assert "spectral_correction_cospectrum_match" in full_output_csv


def test_footprint_land_cover_overlay_samples_esri_ascii_raster(tmp_path: Path) -> None:
    rows = _make_rows()
    config = _v3i_config(rows)
    raster_path = tmp_path / "land_cover.asc"
    ncols = 80
    nrows = 80
    xll = -97.5688
    yll = 35.1230
    cellsize = 0.00002
    raster_rows: list[str] = []
    for row_index in range(nrows):
        row_from_bottom = nrows - 1 - row_index
        code = "2" if row_from_bottom >= 22 else "1"
        raster_rows.append(" ".join([code] * ncols))
    raster_path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xll}",
                f"yllcorner {yll}",
                f"cellsize {cellsize}",
                "NODATA_value -9999",
                *raster_rows,
            ]
        ),
        encoding="utf-8",
    )
    footprint_config = dict(config["footprint"])
    footprint_config.pop("land_cover_grid", None)
    footprint_config["land_cover_raster"] = {"path": str(raster_path), "crs": "EPSG:4326"}
    footprint_config["land_cover_legend"] = {"1": "cropland", "2": "forest_edge"}
    config["footprint"] = footprint_config

    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3I-RASTER", name="v3i raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )
    bundle = ResultExporter(runtime_root=tmp_path).export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I-RASTER", name="v3i raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site", latitude=35.1234, longitude=-97.5678),
        report_payload={"title": "raster overlay"},
        report_key="method_compare",
        full_output_mode="standard_schema",
    )

    overlay = json.loads(Path(bundle["files"]["footprint_land_cover_overlay_artifact"]).read_text(encoding="utf-8"))
    gis_validation = json.loads(Path(bundle["files"]["footprint_gis_validation_artifact"]).read_text(encoding="utf-8"))
    assert overlay["status"] == "ok"
    assert overlay["classification_source"] == "raster"
    assert overlay["summary"]["raster_source"] == str(raster_path)
    assert overlay["summary"]["raster_crs"] == "EPSG:4326"
    assert {row["land_cover"] for row in overlay["classes"]} == {"cropland", "forest_edge"}
    assert math.isclose(sum(row["fraction"] for row in overlay["classes"]), 1.0, rel_tol=1e-6)
    detail = overlay["windows"][0]["overlay_detail"]
    assert detail["raster_format"] == "esri_ascii_grid"
    assert detail["sampled_cell_count"] > 0
    assert detail["unsampled_cell_count"] == 0
    assert gis_validation["land_cover_raster"]["status"] == "ok"
    assert gis_validation["land_cover_raster"]["footprint_overlap_fraction"] == 1.0
    assert gis_validation["land_cover_overlay"]["classification_source"] == "raster"
    assert gis_validation["geotiff"]["cog_readiness"] == "candidate"
    assert gis_validation["geotiff"]["range_readiness"] == "ok"
    reader_validation = gis_validation["geotiff"]["external_reader_validation"]
    assert reader_validation["status"] in {"ok", "not_available"}
    if reader_validation["status"] == "ok":
        assert reader_validation["read_status"] == "ok"
        assert reader_validation["block_shapes"][0] == [16, 16]
    assert gis_validation["status"] in {"ok", "ok_with_limitations"}


def test_footprint_land_cover_overlay_reprojects_epsg3857_ascii_raster(tmp_path: Path) -> None:
    rows = _make_rows()
    config = _v3i_config(rows)
    raster_path = tmp_path / "land_cover_3857.asc"
    site_lon = -97.5678
    site_lat = 35.1234
    site_x, site_y = _web_mercator_xy(site_lon, site_lat)
    ncols = 32
    nrows = 44
    cellsize = 2.0
    xll = site_x - 28.0
    yll = site_y - 10.0
    raster_rows: list[str] = []
    for row_index in range(nrows):
        row_from_bottom = nrows - 1 - row_index
        code = "2" if row_from_bottom >= 7 else "1"
        raster_rows.append(" ".join([code] * ncols))
    raster_path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xll}",
                f"yllcorner {yll}",
                f"cellsize {cellsize}",
                "NODATA_value -9999",
                *raster_rows,
            ]
        ),
        encoding="utf-8",
    )
    footprint_config = dict(config["footprint"])
    footprint_config.pop("land_cover_grid", None)
    footprint_config["land_cover_raster"] = {"path": str(raster_path), "crs": "EPSG:3857"}
    footprint_config["land_cover_legend"] = {"1": "near_field", "2": "far_field"}
    config["footprint"] = footprint_config

    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3I-3857", name="v3i 3857 raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )
    bundle = ResultExporter(runtime_root=tmp_path).export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I-3857", name="v3i 3857 raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site", latitude=site_lat, longitude=site_lon),
        report_payload={"title": "raster overlay 3857"},
        report_key="method_compare",
        full_output_mode="standard_schema",
    )

    overlay = json.loads(Path(bundle["files"]["footprint_land_cover_overlay_artifact"]).read_text(encoding="utf-8"))
    gis_validation = json.loads(Path(bundle["files"]["footprint_gis_validation_artifact"]).read_text(encoding="utf-8"))
    assert overlay["status"] == "ok"
    assert overlay["classification_source"] == "raster"
    assert overlay["summary"]["raster_crs"] == "EPSG:3857"
    assert {row["land_cover"] for row in overlay["classes"]} == {"far_field", "near_field"}
    detail = overlay["windows"][0]["overlay_detail"]
    assert detail["coordinate_transform"] == "builtin_epsg4326_to_epsg3857"
    assert detail["sampled_cell_count"] > 0
    assert detail["unsampled_cell_count"] == 0
    assert detail["unsupported_crs_cell_count"] == 0
    assert gis_validation["land_cover_raster"]["status"] == "ok"
    assert gis_validation["land_cover_raster"]["crs"] == "EPSG:3857"
    assert gis_validation["land_cover_raster"]["coordinate_transform"] == "builtin_epsg4326_to_epsg3857"
    assert gis_validation["land_cover_raster"]["footprint_overlap_fraction"] == 1.0


def test_footprint_land_cover_overlay_reprojects_arbitrary_epsg_ascii_raster(tmp_path: Path) -> None:
    rows = _make_rows()
    config = _v3i_config(rows)
    raster_path = tmp_path / "land_cover_utm14.asc"
    site_lon = -97.5678
    site_lat = 35.1234
    site_x, site_y = _rasterio_project_xy("EPSG:4326", "EPSG:32614", site_lon, site_lat)
    ncols = 32
    nrows = 44
    cellsize = 2.0
    xll = site_x - 28.0
    yll = site_y - 10.0
    raster_rows: list[str] = []
    for row_index in range(nrows):
        row_from_bottom = nrows - 1 - row_index
        code = "2" if row_from_bottom >= 7 else "1"
        raster_rows.append(" ".join([code] * ncols))
    raster_path.write_text(
        "\n".join(
            [
                f"ncols {ncols}",
                f"nrows {nrows}",
                f"xllcorner {xll}",
                f"yllcorner {yll}",
                f"cellsize {cellsize}",
                "NODATA_value -9999",
                *raster_rows,
            ]
        ),
        encoding="utf-8",
    )
    footprint_config = dict(config["footprint"])
    footprint_config.pop("land_cover_grid", None)
    footprint_config["land_cover_raster"] = {"path": str(raster_path), "crs": "EPSG:32614"}
    footprint_config["land_cover_legend"] = {"1": "near_field", "2": "far_field"}
    config["footprint"] = footprint_config

    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3I-UTM", name="v3i utm raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )
    bundle = ResultExporter(runtime_root=tmp_path).export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I-UTM", name="v3i utm raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site", latitude=site_lat, longitude=site_lon),
        report_payload={"title": "raster overlay utm"},
        report_key="method_compare",
        full_output_mode="standard_schema",
    )

    overlay = json.loads(Path(bundle["files"]["footprint_land_cover_overlay_artifact"]).read_text(encoding="utf-8"))
    gis_validation = json.loads(Path(bundle["files"]["footprint_gis_validation_artifact"]).read_text(encoding="utf-8"))
    assert overlay["status"] == "ok"
    assert overlay["classification_source"] == "raster"
    assert overlay["summary"]["raster_crs"] == "EPSG:32614"
    assert {row["land_cover"] for row in overlay["classes"]} == {"far_field", "near_field"}
    detail = overlay["windows"][0]["overlay_detail"]
    assert detail["coordinate_transform"] == "rasterio_epsg4326_to_epsg32614"
    assert detail["coordinate_transform_detail"]["engine"] == "rasterio"
    assert detail["coordinate_transform_detail"]["status"] == "ok"
    assert detail["sampled_cell_count"] > 0
    assert detail["unsampled_cell_count"] == 0
    assert detail["unsupported_crs_cell_count"] == 0
    assert gis_validation["land_cover_raster"]["status"] == "ok"
    assert gis_validation["land_cover_raster"]["crs"] == "EPSG:32614"
    assert gis_validation["land_cover_raster"]["coordinate_transform"] == "rasterio_epsg4326_to_epsg32614"
    assert gis_validation["land_cover_raster"]["coordinate_transform_detail"]["engine"] == "rasterio"
    assert gis_validation["land_cover_raster"]["footprint_overlap_fraction"] == 1.0


def test_footprint_land_cover_overlay_samples_rotated_geotiff_raster(tmp_path: Path) -> None:
    rows = _make_rows()
    config = _v3i_config(rows)
    raster_path = tmp_path / "land_cover_rotated_utm14.tif"
    site_lon = -97.5678
    site_lat = 35.1234
    site_x, site_y = _rasterio_project_xy("EPSG:4326", "EPSG:32614", site_lon, site_lat)
    ncols = 64
    nrows = 64
    cellsize = 2.0
    center_col = 24.0
    center_row = 40.0
    angle = math.radians(12.0)
    a = cellsize * math.cos(angle)
    b = cellsize * math.sin(angle)
    d = cellsize * math.sin(angle)
    e = -cellsize * math.cos(angle)
    c = site_x - a * center_col - b * center_row
    f = site_y - d * center_col - e * center_row
    raster_rows = [[1 if col_index % 2 else 2 for col_index in range(ncols)] for _ in range(nrows)]
    _write_rasterio_land_cover_geotiff(
        path=raster_path,
        crs="EPSG:32614",
        transform=[a, b, c, d, e, f],
        rows=raster_rows,
    )
    footprint_config = dict(config["footprint"])
    footprint_config.pop("land_cover_grid", None)
    footprint_config["land_cover_raster"] = {"path": str(raster_path)}
    footprint_config["land_cover_legend"] = {"1": "near_field", "2": "far_field"}
    config["footprint"] = footprint_config

    result = ECRPPipeline().run(
        rows=rows,
        project=ProjectProfile(code="PRJ-V3I-GEOTIFF", name="v3i geotiff raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site"),
        config=config,
        data_source="unit-test",
        time_range="2026-04-18 09:00~09:01",
    )
    bundle = ResultExporter(runtime_root=tmp_path).export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-V3I-GEOTIFF", name="v3i geotiff raster"),
        site=SiteProfile(station_code="SITE-V3I", station_name="V3I Site", latitude=site_lat, longitude=site_lon),
        report_payload={"title": "raster overlay geotiff"},
        report_key="method_compare",
        full_output_mode="standard_schema",
    )

    overlay = json.loads(Path(bundle["files"]["footprint_land_cover_overlay_artifact"]).read_text(encoding="utf-8"))
    gis_validation = json.loads(Path(bundle["files"]["footprint_gis_validation_artifact"]).read_text(encoding="utf-8"))
    assert overlay["status"] == "ok"
    assert overlay["classification_source"] == "raster"
    assert overlay["summary"]["raster_crs"] == "EPSG:32614"
    assert {row["land_cover"] for row in overlay["classes"]} == {"far_field", "near_field"}
    detail = overlay["windows"][0]["overlay_detail"]
    assert detail["raster_format"] == "geotiff_land_cover"
    assert detail["raster_sampling_engine"] == "rasterio"
    assert detail["coordinate_transform"] == "rasterio_epsg4326_to_epsg32614"
    assert detail["coordinate_transform_detail"]["raster_sampling_detail"]["rotated_transform"] is True
    assert detail["sampled_cell_count"] > 0
    assert detail["unsupported_crs_cell_count"] == 0
    raster_validation = gis_validation["land_cover_raster"]
    assert raster_validation["status"] == "ok"
    assert raster_validation["format"] == "geotiff_land_cover"
    assert raster_validation["crs"] == "EPSG:32614"
    assert raster_validation["native_extent_source"] == "geotiff_bounds"
    assert raster_validation["metadata_reader"]["rotated_transform"] is True
    assert raster_validation["coordinate_transform_detail"]["engine"] == "rasterio"
    assert raster_validation["footprint_overlap_fraction"] == 1.0


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
        site=SiteProfile(station_code="SITE-V3J", station_name="V3J Site", latitude=35.1234, longitude=-97.5678),
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
        "footprint_geojson_artifact",
        "footprint_geotiff_artifact",
        "footprint_land_cover_overlay_artifact",
        "footprint_gis_validation_artifact",
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
    geojson = json.loads(Path(files["footprint_geojson_artifact"]).read_text(encoding="utf-8"))
    geotiff_bytes = Path(files["footprint_geotiff_artifact"]).read_bytes()
    overlay = json.loads(Path(files["footprint_land_cover_overlay_artifact"]).read_text(encoding="utf-8"))
    gis_validation = json.loads(Path(files["footprint_gis_validation_artifact"]).read_text(encoding="utf-8"))
    assert "<svg" in contour_svg
    assert ">x90</text>" in contour_svg
    assert "window_id,method,x_m,y_m,contribution" in grid_csv
    assert geojson["status"] == "ok"
    assert any(feature["properties"]["feature_type"] == "footprint_peak" for feature in geojson["features"])
    assert geotiff_bytes[:4] == b"II*\x00"
    assert overlay["status"] == "ok"
    assert overlay["summary"]["class_count"] == 2
    assert gis_validation["geotiff"]["status"] == "ok"
    assert gis_validation["geotiff"]["layout"] == "tiled"
    assert gis_validation["geotiff"]["has_internal_overviews"] is True
    assert gis_validation["geotiff"]["cog_readiness"] == "candidate"
    assert gis_validation["geotiff"]["range_validation"]["tile_data_after_metadata"] is True
    reader_validation = gis_validation["geotiff"]["external_reader_validation"]
    assert reader_validation["status"] in {"ok", "not_available"}
    cog_validator = gis_validation["geotiff"]["cog_validator_validation"]
    assert cog_validator["status"] in {"valid", "invalid", "not_available"}
    assert gis_validation["status"] == "ok_with_limitations"

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
    assert manifest["footprint_geojson_artifact"] == files["footprint_geojson_artifact"]
    assert manifest["footprint_geotiff_artifact"] == files["footprint_geotiff_artifact"]
    assert manifest["footprint_land_cover_overlay_artifact"] == files["footprint_land_cover_overlay_artifact"]
    assert manifest["footprint_gis_validation_artifact"] == files["footprint_gis_validation_artifact"]
    assert manifest["performance_profile_artifact"] == files["performance_profile_artifact"]
    assert manifest["method_parity_matrix"]["reference_profile"]["status"] == "ready"

    benchmark_summary = json.loads(Path(files["benchmark_summary_artifact"]).read_text(encoding="utf-8"))
    parity = json.loads(Path(files["parity_artifact"]).read_text(encoding="utf-8"))
    assert benchmark_summary["method_parity_matrix"]["reference_profile"]["status"] == "ready"
    assert parity["method_parity_matrix"]["reference_profile"]["status"] == "ready"
