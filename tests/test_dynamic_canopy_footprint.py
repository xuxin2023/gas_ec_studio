from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _rows(*, samples: int = 600, sample_hz: float = 10.0) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 15, 12, 0, 0)
    axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.38 * np.sin(2.0 * np.pi * 0.17 * axis) + 0.05 * np.cos(2.0 * np.pi * 0.63 * axis)
    co2 = np.roll(w, 4)
    h2o = np.roll(w, 2)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(axis[index])),
                device_uid="dyn-canopy",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2[index]),
                h2o_mmol=float(12.0 + 1.1 * h2o[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.5,
                case_temp_c=24.4,
                raw_text=json.dumps(
                    {
                        "u": float(2.2 + 0.2 * np.sin(2.0 * np.pi * 0.03 * axis[index])),
                        "v": float(0.3 * np.cos(2.0 * np.pi * 0.05 * axis[index])),
                        "w": float(w[index]),
                    }
                ),
            )
        )
    return rows


def test_dynamic_canopy_height_overrides_footprint_default(tmp_path: Path) -> None:
    schedule = tmp_path / "canopy_schedule.csv"
    schedule.write_text(
        "start_time,end_time,canopy_height_m\n"
        "2026-05-01T00:00:00,2026-06-01T00:00:00,2.4\n",
        encoding="utf-8",
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 1.0,
        "footprint": {"enabled": True, "method": "kljun", "z_m": 3.2, "grid_enabled": True},
        "metadata_bundle": {
            "dynamic_metadata": {
                "source_path": str(schedule),
                "fields": ["canopy_height_m"],
            }
        },
    }

    result = ECRPPipeline().run(
        rows=_rows(),
        project=ProjectProfile(name="Dynamic Canopy"),
        site=SiteProfile(station_name="Crop Site", station_code="DYN", canopy_height_m=1.1),
        config=config,
        data_source="unit-test",
        time_range="2026-05-15T12:00/2026-05-15T12:01",
    )

    assert result.windows
    diagnostics = result.windows[0].diagnostics
    assert diagnostics["dynamic_metadata_status"] == "matched"
    assert diagnostics["dynamic_canopy_height_m"] == 2.4
    assert diagnostics["footprint_canopy_height_m"] == 2.4
    assert diagnostics["footprint_canopy_height_source"] == "dynamic_metadata"
    assert diagnostics["footprint_detail"]["inputs"]["canopy_height_m"] == 2.4
    assert result.summary["footprint_summary"]["canopy_height_m"] == 2.4
    assert result.summary["footprint_summary"]["canopy_height_source"] == "dynamic_metadata"
    assert result.summary["footprint_summary"]["dynamic_metadata_status_counts"]["matched"] == 1


def test_dynamic_canopy_fields_reach_full_output_export(tmp_path: Path) -> None:
    schedule = tmp_path / "canopy_schedule.csv"
    schedule.write_text(
        "start_time,end_time,canopy_height_m\n"
        "2026-05-01T00:00:00,2026-06-01T00:00:00,3.6\n",
        encoding="utf-8",
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 1.0,
        "footprint": {"enabled": True, "method": "hsieh", "z_m": 4.0, "grid_enabled": False},
        "metadata_bundle": {"dynamic_metadata": {"source_path": str(schedule), "fields": ["canopy_height_m"]}},
    }
    site = SiteProfile(station_name="Crop Site", station_code="DYN", canopy_height_m=1.1)
    result = ECRPPipeline().run(
        rows=_rows(),
        project=ProjectProfile(name="Dynamic Canopy"),
        site=site,
        config=config,
        data_source="unit-test",
        time_range="",
    )

    bundle = ResultExporter(runtime_root=tmp_path).export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot=config,
        spectral_config_snapshot={},
        project=ProjectProfile(name="Dynamic Canopy"),
        site=site,
        report_payload={"title": "Dynamic canopy"},
        report_key="dynamic_canopy",
    )
    full_output = Path(bundle["files"]["full_output"]).read_text(encoding="utf-8")
    summary = json.loads(Path(bundle["files"]["summary"]).read_text(encoding="utf-8"))

    assert "dynamic_canopy_height_m" in full_output
    assert "footprint_canopy_height_source" in full_output
    assert "dynamic_metadata" in full_output
    assert summary["rp_run"]["summary"]["footprint_summary"]["dynamic_canopy_height_m"] == 3.6
