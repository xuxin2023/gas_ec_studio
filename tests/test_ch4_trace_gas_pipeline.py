from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import load_input_rows, run_headless_batch
from core.storage.ghg_bundle import load_ghg_normalized_frames
from core.storage.raw_importer import load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import (
    MetadataBundle,
    ProjectProfile,
    RawColumnMapping,
    RawFileDescriptionMetadata,
    RawFileSettingsMetadata,
    SiteProfile,
)


def _make_ch4_rows(*, sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 22, 10, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.35 + 0.16 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.25 * np.cos(2.0 * np.pi * 0.04 * time_axis)
    w = 0.48 * np.sin(2.0 * np.pi * 0.17 * time_axis) + 0.10 * np.cos(2.0 * np.pi * 0.63 * time_axis)
    co2_signal = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 0.9 * time_axis)
    h2o_signal = np.roll(w, 2) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="li7700-demo",
                device_id="li-7700",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.1 * h2o_signal[index]),
                ch4_ppb=float(1900.0 + 35.0 * w[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.8,
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def test_headless_json_loader_preserves_ch4_ppb(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    source = _make_ch4_rows(samples=128)[0]
    path.write_text(json.dumps([source.to_record()], ensure_ascii=False), encoding="utf-8")

    rows = load_input_rows(path)

    assert rows[0].ch4_ppb == source.ch4_ppb
    assert rows[0].to_record()["ch4_ppb"] == source.ch4_ppb


def test_raw_text_importer_maps_ch4_with_unit_conversion(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw_ch4.csv"
    raw_path.write_text(
        "DateTime,CO2_molmol,H2O_molmol,CH4_molmol,PressurePa,TempK,Ux,Vy,Wz\n"
        "2026-05-22T10:00:00,0.000410,0.012,0.00000191,101300,298.15,2.0,0.1,0.2\n",
        encoding="utf-8",
    )
    metadata = MetadataBundle(
        project=ProjectProfile(code="RAW-CH4", name="Raw CH4"),
        raw_file_description=RawFileDescriptionMetadata(
            source_name="raw-ch4",
            source_type="csv",
            column_mappings=[
                RawColumnMapping(column_name="DateTime", variable="timestamp", numeric=False),
                RawColumnMapping(column_name="CO2_molmol", variable="co2_ppm", input_unit="mol/mol"),
                RawColumnMapping(column_name="H2O_molmol", variable="h2o_mmol", input_unit="mol/mol"),
                RawColumnMapping(column_name="CH4_molmol", variable="ch4_ppb", input_unit="mol/mol"),
                RawColumnMapping(column_name="PressurePa", variable="pressure_kpa", input_unit="Pa"),
                RawColumnMapping(column_name="TempK", variable="chamber_temp_c", input_unit="K"),
                RawColumnMapping(column_name="Ux", variable="u"),
                RawColumnMapping(column_name="Vy", variable="v"),
                RawColumnMapping(column_name="Wz", variable="w"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, delimiter=",", header_rows=1, missing_tokens=["", "NA"]),
    )

    rows = load_raw_text_frames(raw_path, metadata=metadata)

    assert len(rows) == 1
    assert rows[0].ch4_ppb == 1910.0
    assert json.loads(rows[0].raw_text)["ch4_ppb"] == 1910.0

    alias_path = tmp_path / "raw_ch4_alias.csv"
    alias_path.write_text(
        "timestamp,co2,h2o,ch4_ppm,pressure,temperature,u,v,w\n"
        "2026-05-22T10:00:00,410.0,12.0,1.92,101.3,25.0,2.0,0.1,0.2\n",
        encoding="utf-8",
    )
    alias_rows = load_raw_text_frames(alias_path, metadata=MetadataBundle())
    assert alias_rows[0].ch4_ppb == 1920.0


def test_ghg_bundle_import_maps_ch4_aliases(tmp_path: Path) -> None:
    ghg_path = tmp_path / "ch4.ghg"
    with ZipFile(ghg_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "20260522-1000.data",
            "timestamp,u,v,w,co2,h2o,ch4_ppm,pressure,temperature\n"
            "2026-05-22T10:00:00,2.0,0.1,0.2,410.0,12.0,1.91,101.3,25.0\n",
        )
        archive.writestr("20260522-1000.metadata", "device_uid=tower-ch4\ndevice_id=li-7700\n")

    rows = load_ghg_normalized_frames(ghg_path)

    assert len(rows) == 1
    assert rows[0].ch4_ppb == 1910.0
    assert json.loads(rows[0].raw_text)["ch4_ppb"] == 1910.0


def test_rp_pipeline_exports_ch4_level0_covariance(tmp_path: Path) -> None:
    rows = _make_ch4_rows()
    metadata = MetadataBundle(
        project=ProjectProfile(code="CH4-001", name="CH4 Trace Gas"),
        site=SiteProfile(station_code="CH4", station_name="LI-7700 Tower"),
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "rotation_mode": "double",
        "detrend_mode": "linear",
        "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.0, "expected_lag_s": 0.4},
        "network_output": {"schema_target": "FLUXNET", "timestamp_refers_to": "start", "timezone_offset_hours": 0.0},
    }

    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="ch4-fixture")
    first_window = result["rp_result"].windows[0]
    diagnostics = first_window.diagnostics

    assert diagnostics["ch4_status"] == "computed"
    assert diagnostics["ch4_method"] == "li_7700_level0_covariance"
    assert diagnostics["ch4_flux_nmol_m2_s"] != 0.0
    assert "spectroscopic" in " ".join(diagnostics["ch4_limitations"])
    assert result["rp_result"].summary["trace_gas_summary"]["ch4_computed_window_count"] == len(result["rp_result"].windows)
    assert result["manifest"]["trace_gas_summary"]["status"] == "computed"

    exporter = ResultExporter(tmp_path)
    exported = exporter.export_minimal_bundle(
        rp_result=result["rp_result"],
        spectral_result=result["spectral_result"],
        rp_config_snapshot=config,
        spectral_config_snapshot=config,
        project=metadata.project,
        site=metadata.site,
        report_payload={"title": "CH4 trace gas"},
        report_key="run_summary",
        full_output_mode="standard_schema",
    )

    with Path(exported["files"]["full_output"]).open("r", encoding="utf-8", newline="") as handle:
        full_rows = list(csv.DictReader(handle))
    with Path(exported["files"]["rp_results"]).open("r", encoding="utf-8", newline="") as handle:
        rp_rows = list(csv.DictReader(handle))
    manifest = json.loads(Path(exported["files"]["export_manifest"]).read_text(encoding="utf-8"))
    summary = json.loads(Path(exported["files"]["summary"]).read_text(encoding="utf-8"))

    assert full_rows[0]["ch4_status"] == "computed"
    assert float(full_rows[0]["ch4_flux_nmol_m2_s"]) != 0.0
    assert "LI-7700" in full_rows[0]["ch4_provenance"]
    assert rp_rows[0]["ch4_method"] == "li_7700_level0_covariance"
    assert manifest["trace_gas_summary"]["status"] == "computed"
    assert "ch4_flux_nmol_m2_s" in manifest["trace_gas_fields"]
    assert summary["trace_gas_summary"]["ch4_computed_window_count"] == len(result["rp_result"].windows)
