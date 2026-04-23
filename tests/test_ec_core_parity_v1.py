from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import run_headless_batch
from core.storage.metadata_store import MetadataStore
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import (
    BiometSourceMetadata,
    DynamicMetadataConfig,
    MetadataBundle,
    ProjectProfile,
    SiteProfile,
    aggregate_biomet_window,
    load_biomet_records,
    load_dynamic_metadata_csv,
    match_dynamic_metadata,
)


def _make_rows(sample_hz: float = 10.0, samples: int = 480) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
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


def test_dynamic_metadata_and_biomet_import(tmp_path: Path) -> None:
    dynamic_path = tmp_path / "dynamic.csv"
    dynamic_path.write_text(
        "start_time,end_time,crop_stage,canopy_height_m\n"
        "2026-04-18T09:00:00,2026-04-18T09:20:00,heading,1.5\n"
        "2026-04-18T09:20:00,2026-04-18T09:40:00,grain_fill,1.7\n",
        encoding="utf-8",
    )
    biomet_path = tmp_path / "biomet.csv"
    biomet_path.write_text(
        "timestamp,ta,rh\n"
        "2026-04-18T09:00:00,24.0,70\n"
        "2026-04-18T09:10:00,24.5,71\n"
        "2026-04-18T09:20:00,25.0,72\n",
        encoding="utf-8",
    )

    dynamic = load_dynamic_metadata_csv(dynamic_path)
    matched = match_dynamic_metadata(
        dynamic.records,
        window_start=datetime(2026, 4, 18, 9, 15, 0),
        window_end=datetime(2026, 4, 18, 9, 25, 0),
    )
    assert matched is not None
    assert matched.values["crop_stage"] in {"heading", "grain_fill"}

    biomet_rows = load_biomet_records(BiometSourceMetadata(source_mode="external_file", source_path=str(biomet_path), fields=["ta", "rh"]))
    aggregated = aggregate_biomet_window(
        biomet_rows,
        window_start=datetime(2026, 4, 18, 9, 0, 0),
        window_end=datetime(2026, 4, 18, 9, 20, 0),
        fields=["ta", "rh"],
    )
    assert aggregated["sample_count"] == 3
    assert aggregated["ta"] > 24.0


def test_metadata_store_and_headless_runner_are_deterministic(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "meta")
    bundle = MetadataBundle(
        project=ProjectProfile(code="PARITY-001", name="Parity"),
        site=SiteProfile(station_code="SITE-P", station_name="Parity Site"),
        dynamic_metadata=DynamicMetadataConfig(records=[]),
    )
    store.save_alternative_metadata("parity", bundle)
    loaded = store.load_alternative_metadata("parity")
    assert loaded is not None
    assert loaded.project.code == "PARITY-001"

    rows = _make_rows()
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.4,
        "rotation_mode": "planar_fit",
        "detrend_mode": "moving_average",
        "lag_phase": {"search_window_s": 1.5, "expected_lag_s": 0.5},
        "transfer_function": {"model": "component_product", "tube_length_m": 12.0, "tube_diameter_mm": 4.0, "flow_lpm": 8.0, "sensor_separation_m": 0.3, "path_length_m": 0.12},
        "correction_factor": {"mode": "provenance_weighted", "factor_cap": 1.35},
    }
    first = run_headless_batch(config=config, metadata=bundle, rows=rows, time_range="demo")
    second = run_headless_batch(config=config, metadata=bundle, rows=rows, time_range="demo")
    assert first["batch_id"] == second["batch_id"]
    assert first["rp_result"].run_id == second["rp_result"].run_id
    assert first["spectral_result"].run_id == second["spectral_result"].run_id
    assert first["rp_result"].windows
    assert first["rp_result"].windows[0].rotation_mode in {"planar_fit", "double", "triple", "none"}
    assert first["rp_result"].windows[0].detrend_mode == "running_mean"
    assert first["rp_result"].windows[0].qc_grade in {"A", "B", "C"}
    assert first["rp_result"].windows[0].uncertainty_detail
    assert "transfer_model=component_product" in " ".join(first["spectral_result"].windows[0].provenance_notes)


def test_result_exporter_writes_full_output_and_manifest(tmp_path: Path) -> None:
    rows = _make_rows()
    bundle = MetadataBundle(project=ProjectProfile(code="PARITY-002", name="Export"), site=SiteProfile(station_code="SITE-E", station_name="Export Site"))
    result = run_headless_batch(
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.4,
            "rotation_mode": "triple",
            "detrend_mode": "linear",
            "lag_phase": {"search_window_s": 1.5, "expected_lag_s": 0.5},
            "transfer_function": {"model": "component_product", "tube_length_m": 12.0, "tube_diameter_mm": 4.0, "flow_lpm": 8.0, "sensor_separation_m": 0.3, "path_length_m": 0.12},
            "correction_factor": {"mode": "provenance_weighted", "factor_cap": 1.35},
        },
        metadata=bundle,
        rows=rows,
        time_range="demo",
    )
    exporter = ResultExporter(tmp_path)
    exported = exporter.export_minimal_bundle(
        rp_result=result["rp_result"],
        spectral_result=result["spectral_result"],
        rp_config_snapshot={"rotation_mode": "triple"},
        spectral_config_snapshot={"transfer_function": {"model": "component_product"}},
        project=bundle.project,
        site=bundle.site,
        report_payload={"title": "demo"},
        report_key="report_snapshot",
        full_output_mode="standard_schema",
    )
    full_output = Path(exported["files"]["full_output"])
    manifest = Path(exported["files"]["export_manifest"])
    assert full_output.exists()
    assert manifest.exists()
    with full_output.open("r", encoding="utf-8", newline="") as handle:
        headers = next(csv.reader(handle))
    assert "relative_uncertainty" in headers
    assert "var_u" in headers
    assert "uncertainty_provenance" in headers
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["full_output_mode"] == "standard_schema"
    assert any(field["value_status"] == "estimated" for field in manifest_payload["field_schema"])
