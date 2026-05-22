from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import load_input_rows, run_headless_batch
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _write_pipeline_ghg(path: Path, *, sample_hz: float = 10.0, samples: int = 600) -> None:
    start = datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)

    rows = [["timestamp", "u", "v", "w", "co2", "h2o", "pressure", "temperature"]]
    for index in range(samples):
        rows.append(
            [
                (start + timedelta(seconds=float(time_axis[index]))).isoformat(),
                f"{u[index]:.8f}",
                f"{v[index]:.8f}",
                f"{w[index]:.8f}",
                f"{410.0 + 9.0 * co2_signal[index]:.8f}",
                f"{12.0 + 1.3 * h2o_signal[index]:.8f}",
                "101.300",
                "24.800",
            ]
        )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("20260522-1000.data", "\n".join(",".join(row) for row in rows) + "\n")
        archive.writestr("20260522-1000.metadata", "device_uid=tower-a\ndevice_id=li-demo\nacquisition_frequency=10\n")
        archive.writestr("20260522-1000-biomet.data", "timestamp,ta,rh\n2026-05-22T10:00:00,24.8,70\n")


def test_headless_load_input_rows_accepts_ghg_bundle(tmp_path: Path) -> None:
    ghg_path = tmp_path / "pipeline.ghg"
    _write_pipeline_ghg(ghg_path)

    rows = load_input_rows(ghg_path)

    assert len(rows) == 600
    assert rows[0].device_uid == "tower-a"
    assert rows[0].device_id == "li-demo"
    assert rows[0].co2_ppm is not None
    assert rows[0].h2o_mmol is not None
    assert json.loads(rows[0].raw_text)["ghg_member"] == "20260522-1000.data"


def test_ghg_rows_run_through_rp_fcc_and_export(tmp_path: Path) -> None:
    ghg_path = tmp_path / "pipeline.ghg"
    _write_pipeline_ghg(ghg_path)
    rows = load_input_rows(ghg_path)
    metadata = MetadataBundle(
        project=ProjectProfile(code="GHG-001", name="GHG Import"),
        site=SiteProfile(station_code="GHG", station_name="GHG Tower"),
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "rotation_mode": "double",
        "detrend_mode": "linear",
        "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.0, "expected_lag_s": 0.5},
        "network_output": {"schema_target": "FLUXNET", "timestamp_refers_to": "start", "timezone_offset_hours": 0.0},
    }

    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source=str(ghg_path), time_range="ghg-demo")
    exporter = ResultExporter(tmp_path)
    exported = exporter.export_minimal_bundle(
        rp_result=result["rp_result"],
        spectral_result=result["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "GHG import"},
        report_key="report_snapshot",
        full_output_mode="standard_schema",
    )

    assert result["rp_result"].windows
    assert result["spectral_result"].windows
    assert result["manifest"]["input_row_count"] == 600
    full_output_path = Path(exported["files"]["full_output"])
    manifest_path = Path(exported["files"]["export_manifest"])
    assert full_output_path.exists()
    assert manifest_path.exists()
    with full_output_path.open("r", encoding="utf-8", newline="") as handle:
        headers = next(csv.reader(handle))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "primary_flux" in headers
    assert manifest["network_validation_summary"]["schema_target"] == "FLUXNET"
