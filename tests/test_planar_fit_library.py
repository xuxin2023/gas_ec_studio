from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(sample_hz: float = 10.0, samples: int = 1200) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.20 + 0.08 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.04 + 0.015 * u - 0.008 * v + 0.10 * np.sin(2.0 * np.pi * 0.19 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
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
                pressure_kpa=101.3,
                chamber_temp_c=24.8,
                case_temp_c=24.7,
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def _run_with_config(config: dict[str, object]):
    return ECRPPipeline().run(
        rows=_make_rows(),
        project=ProjectProfile(name="Planar Fit", code="PF"),
        site=SiteProfile(station_name="PF Site", station_code="PF-SITE"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.2,
            "rotation_mode": "sector_wise_planar_fit",
            "planar_fit": {
                "n_sectors": 12,
                "min_windows_per_sector": 5,
                **config,
            },
        },
        data_source="planar-fit-test",
        time_range="",
    )


def test_planar_fit_library_generated_saved_and_diagnosed(tmp_path: Path) -> None:
    library_path = tmp_path / "planar_fit_library.json"

    result = _run_with_config({"save_coefficient_library_path": str(library_path)})

    assert library_path.exists()
    saved_payload = json.loads(library_path.read_text(encoding="utf-8"))
    assert saved_payload["artifact_type"] == "planar_fit_coefficient_library_v1"
    assert saved_payload["coefficients"]
    assert result.summary["planar_fit_library_status"] == "generated"
    assert result.summary["planar_fit_library_save_status"] == "saved"
    assert result.summary["planar_fit_library_saved_path"] == str(library_path)
    assert result.artifacts["planar_fit_library"]["coefficients"]

    first_diag = result.windows[0].diagnostics
    assert first_diag["planar_fit_library_status"] == "generated"
    assert first_diag["planar_fit_library_save_status"] == "saved"
    assert first_diag["planar_fit_selected_sector"].startswith("S")
    assert first_diag["planar_fit_selected_sector_window_count"] >= 5
    assert isinstance(first_diag["planar_fit_library_detail"], dict)


def test_planar_fit_library_loaded_from_previous_run(tmp_path: Path) -> None:
    library_path = tmp_path / "planar_fit_library.json"
    _run_with_config({"save_coefficient_library_path": str(library_path)})

    result = _run_with_config({"coefficient_library_path": str(library_path)})

    assert result.summary["planar_fit_library_status"] == "loaded"
    assert result.summary["planar_fit_library_source"] == "file"
    assert result.summary["planar_fit_library_path"] == str(library_path)
    assert result.windows[0].diagnostics["planar_fit_library_status"] == "loaded"
    assert result.windows[0].diagnostics["planar_fit_library_source"] == "file"


def test_planar_fit_library_export_fields_and_artifact(tmp_path: Path) -> None:
    result = _run_with_config({"save_coefficient_library_path": str(tmp_path / "planar_fit_library.json")})
    exporter = ResultExporter(tmp_path / "exports")

    schema_names = [name for name, _group, _status in FULL_OUTPUT_SCHEMA]
    assert "planar_fit_library_status" in schema_names
    assert "planar_fit_selected_sector" in schema_names
    rows = exporter._full_output_rows(rp_result=result, spectral_result=None, mode="standard_schema")
    assert rows[0]["planar_fit_library_status"] == "generated"
    assert rows[0]["planar_fit_selected_sector"].startswith("S")

    artifact_path = exporter.export_planar_fit_library_artifact(
        rp_result=result,
        export_root=tmp_path,
    )
    assert artifact_path is not None
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["artifact_type"] == "planar_fit_coefficient_library_v1"
    assert artifact["coefficients"]
