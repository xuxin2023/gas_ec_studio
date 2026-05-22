from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.ec_rp.analysis import apply_sonic_corrections
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_rows(*, samples: int = 600, sample_hz: float = 10.0) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 12, 0, 0)
    t = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.12 * np.sin(2.0 * np.pi * 0.05 * t)
    v = 0.2 * np.cos(2.0 * np.pi * 0.04 * t)
    w = 0.34 * np.sin(2.0 * np.pi * 0.19 * t) + 0.05 * np.cos(2.0 * np.pi * 0.77 * t)
    co2 = 410.0 + 8.5 * np.roll(w, 3)
    h2o = 13.0 + 0.9 * np.roll(w, 2)
    return [
        NormalizedHFFrame(
            timestamp=start + timedelta(seconds=float(t[index])),
            device_uid="sonic-demo",
            device_id="li-7500ds",
            mode=2,
            frame_quality=FrameQuality.FULL,
            co2_ppm=float(co2[index]),
            h2o_mmol=float(h2o[index]),
            pressure_kpa=101.2,
            chamber_temp_c=24.5,
            raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
        )
        for index in range(samples)
    ]


def test_apply_sonic_corrections_applies_gill_wboost_offsets_and_aoa_gain() -> None:
    u = np.array([2.0, 2.0, 2.0], dtype=float)
    v = np.array([0.0, 0.2, -0.2], dtype=float)
    w = np.array([0.5, -0.5, 0.0], dtype=float)

    result = apply_sonic_corrections(
        u,
        v,
        w,
        {
            "enabled": True,
            "sonic_model": "wm",
            "sonic_firmware": "2329.600.1",
            "wind_reference": "axis",
            "w_offset_ms": 0.01,
            "gill_wm_w_boost": "auto",
            "angle_of_attack": {
                "enabled": True,
                "horizontal_gain_per_reference_angle": 0.02,
                "vertical_gain_per_reference_angle": 0.03,
                "reference_angle_deg": 45.0,
            },
        },
    )

    assert result.detail["status"] == "applied"
    step_names = [step["name"] for step in result.detail["steps"]]
    assert "sonic_bias_offsets" in step_names
    assert "gill_windmaster_w_boost_apply" in step_names
    assert "calibrated_angle_of_attack_gain" in step_names
    assert result.w[0] > w[0]
    assert result.w[1] < w[1]
    assert result.detail["source_reference"]["eddypro_engine_files"][0].endswith("adjust_sonic_coordinates.f90")


def test_pipeline_exports_sonic_correction_provenance(tmp_path: Path) -> None:
    rows = _make_rows()
    metadata = MetadataBundle(
        project=ProjectProfile(code="SONIC-001", name="Sonic Correction"),
        site=SiteProfile(station_code="SONIC", station_name="Sonic Tower"),
    )
    base_config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "rotation_mode": "double",
        "detrend_mode": "linear",
        "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.0},
    }
    corrected_config = {
        **base_config,
        "sonic_correction": {
            "enabled": True,
            "method": "eddypro_sonic_coordinate_v1",
            "sonic_model": "wm",
            "sonic_firmware": "2329.600.1",
            "gill_wm_w_boost": "auto",
            "w_offset_ms": 0.01,
            "angle_of_attack": {
                "enabled": True,
                "vertical_gain_per_reference_angle": 0.02,
                "reference_angle_deg": 45.0,
            },
        },
    }
    pipeline = ECRPPipeline()
    baseline = pipeline.run(
        rows=rows,
        project=metadata.project,
        site=metadata.site,
        config=base_config,
        data_source="sonic-baseline",
    )
    corrected = pipeline.run(
        rows=rows,
        project=metadata.project,
        site=metadata.site,
        config=corrected_config,
        data_source="sonic-corrected",
    )
    baseline_flux = baseline.windows[0].primary_flux
    corrected_flux = corrected.windows[0].primary_flux
    diagnostics = corrected.windows[0].diagnostics

    assert diagnostics["sonic_correction_status"] == "applied"
    assert diagnostics["sonic_correction_method"] == "eddypro_sonic_coordinate_v1"
    assert any(step["name"] == "gill_windmaster_w_boost_apply" for step in diagnostics["sonic_correction_steps"])
    assert corrected_flux != pytest.approx(baseline_flux, rel=1e-6)

    exporter = ResultExporter(tmp_path)
    exported = exporter.export_minimal_bundle(
        rp_result=corrected,
        spectral_result=None,
        rp_config_snapshot=corrected_config,
        spectral_config_snapshot={},
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "Sonic correction"},
        report_key="run_summary",
        full_output_mode="standard_schema",
    )

    with Path(exported["files"]["full_output"]).open("r", encoding="utf-8", newline="") as handle:
        full_rows = list(csv.DictReader(handle))
    manifest = json.loads(Path(exported["files"]["export_manifest"]).read_text(encoding="utf-8"))

    assert full_rows[0]["sonic_correction_status"] == "applied"
    assert full_rows[0]["sonic_correction_method"] == "eddypro_sonic_coordinate_v1"
    assert "Gill WindMaster" in full_rows[0]["sonic_correction_provenance"]
    assert "sonic_correction_method" in manifest["method_provenance_fields"]
