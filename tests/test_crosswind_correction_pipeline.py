from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.ec_rp.analysis import apply_crosswind_correction
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, samples: int = 600, sample_hz: float = 10.0) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 13, 0, 0)
    t = np.arange(samples, dtype=float) / sample_hz
    u = 5.8 + 0.25 * np.sin(2.0 * np.pi * 0.03 * t)
    v = 1.1 + 0.15 * np.cos(2.0 * np.pi * 0.04 * t)
    w = 0.42 * np.sin(2.0 * np.pi * 0.18 * t) + 0.06 * np.cos(2.0 * np.pi * 0.71 * t)
    co2 = 410.0 + 9.0 * np.roll(w, 3)
    h2o = 12.5 + 1.0 * np.roll(w, 2)
    return [
        NormalizedHFFrame(
            timestamp=start + timedelta(seconds=float(t[index])),
            device_uid="crosswind-demo",
            device_id="li-7500ds",
            mode=2,
            frame_quality=FrameQuality.FULL,
            co2_ppm=float(co2[index]),
            h2o_mmol=float(h2o[index]),
            pressure_kpa=101.0,
            chamber_temp_c=22.0,
            raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
        )
        for index in range(samples)
    ]


def test_crosswind_correction_applies_eddypro_style_gill_coefficients() -> None:
    u = np.array([5.0, 6.0, 7.0], dtype=float)
    v = np.array([1.0, 1.2, 1.4], dtype=float)
    temp = np.array([20.0, 20.0, 20.0], dtype=float)

    result = apply_crosswind_correction(
        u=u,
        v=v,
        temp_c=temp,
        config={"enabled": True, "sonic_manufacturer": "gill", "sonic_model": "wm"},
    )

    assert result.detail["status"] == "applied"
    assert result.detail["coefficient_source"] == "eddypro_model_registry"
    assert result.detail["coefficients"]["A"][0] == pytest.approx(0.5)
    assert result.detail["mean_delta_c"] > 0.0
    assert np.all(result.temp_c > temp)
    assert result.detail["source_reference"]["eddypro_engine_files"] == ["src/src_common/cross_wind_corr.f90"]


def test_pipeline_exports_crosswind_correction_provenance(tmp_path: Path) -> None:
    rows = _make_rows()
    metadata = MetadataBundle(
        project=ProjectProfile(code="CROSS-001", name="Crosswind Correction"),
        site=SiteProfile(station_code="CROSS", station_name="Crosswind Tower"),
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "rotation_mode": "double",
        "detrend_mode": "linear",
        "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.0},
        "crosswind_correction": {
            "enabled": True,
            "sonic_manufacturer": "gill",
            "sonic_model": "wm",
        },
    }
    result = ECRPPipeline().run(
        rows=rows,
        project=metadata.project,
        site=metadata.site,
        config=config,
        data_source="crosswind-fixture",
    )
    window = result.windows[0]
    diagnostics = window.diagnostics

    assert diagnostics["crosswind_correction_status"] == "applied"
    assert diagnostics["crosswind_correction_method"] == "liu_2001_crosswind_v1"
    assert diagnostics["crosswind_correction_mean_delta_c"] > 0.0
    assert window.mean_temp_c > 22.0
    assert "cross_wind_corr.f90" in diagnostics["crosswind_correction_detail"]["source_reference"]["eddypro_engine_files"][0]

    exporter = ResultExporter(tmp_path)
    exported = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Crosswind correction"},
        report_key="run_summary",
        full_output_mode="standard_schema",
    )

    with Path(exported["files"]["full_output"]).open("r", encoding="utf-8", newline="") as handle:
        rows_out = list(csv.DictReader(handle))
    manifest = json.loads(Path(exported["files"]["export_manifest"]).read_text(encoding="utf-8"))

    assert rows_out[0]["crosswind_correction_status"] == "applied"
    assert rows_out[0]["crosswind_correction_method"] == "liu_2001_crosswind_v1"
    assert float(rows_out[0]["crosswind_correction_mean_delta_c"]) > 0.0
    assert "Crosswind sonic-temperature correction" in rows_out[0]["crosswind_correction_provenance"]
    assert "crosswind_correction_method" in manifest["method_provenance_fields"]
