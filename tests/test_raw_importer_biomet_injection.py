from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.headless_batch_runner import load_input_rows, run_headless_batch
from core.storage.raw_importer import load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import (
    BiometSourceMetadata,
    MetadataBundle,
    ProjectProfile,
    RawColumnMapping,
    RawFileDescriptionMetadata,
    RawFileSettingsMetadata,
    SiteProfile,
)


def _metadata_for_raw(tmp_path: Path) -> MetadataBundle:
    return MetadataBundle(
        project=ProjectProfile(code="RAW-001", name="Raw Import"),
        site=SiteProfile(station_code="RAW", station_name="Raw Tower"),
        raw_file_description=RawFileDescriptionMetadata(
            source_name="raw-fixture",
            source_type="csv",
            column_mappings=[
                RawColumnMapping(column_name="DateTime", variable="timestamp", numeric=False),
                RawColumnMapping(column_name="CO2_molmol", variable="co2_ppm", input_unit="mol/mol"),
                RawColumnMapping(column_name="H2O_molmol", variable="h2o_mmol", input_unit="mol/mol"),
                RawColumnMapping(column_name="PressurePa", variable="pressure_kpa", input_unit="Pa"),
                RawColumnMapping(column_name="TempK", variable="chamber_temp_c", input_unit="K"),
                RawColumnMapping(column_name="Ux", variable="u"),
                RawColumnMapping(column_name="Vy", variable="v"),
                RawColumnMapping(column_name="Wz", variable="w"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, delimiter=",", header_rows=1, missing_tokens=["", "NA"]),
    )


def test_load_input_rows_accepts_mapped_raw_csv_with_unit_conversion(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    raw_path.write_text(
        "DateTime,CO2_molmol,H2O_molmol,PressurePa,TempK,Ux,Vy,Wz\n"
        "2026-05-22T10:00:00,0.000410,0.012,101300,298.15,2.0,0.1,0.2\n",
        encoding="utf-8",
    )
    metadata = _metadata_for_raw(tmp_path)

    rows = load_input_rows(raw_path, metadata=metadata)

    assert len(rows) == 1
    assert rows[0].co2_ppm == 410.0
    assert rows[0].h2o_mmol == 12.0
    assert rows[0].pressure_kpa == 101.3
    assert rows[0].chamber_temp_c == 25.0
    assert json.loads(rows[0].raw_text)["w"] == 0.2


def test_raw_text_importer_handles_tob1_like_text_headers(tmp_path: Path) -> None:
    tob1_path = tmp_path / "raw.tob1"
    tob1_path.write_text(
        "timestamp\tu\tv\tw\tco2\th2o\tpressure\ttemperature\n"
        "TS\tm/s\tm/s\tm/s\tppm\tmmol/mol\tkPa\tC\n"
        "Smp\tAvg\tAvg\tAvg\tAvg\tAvg\tAvg\tAvg\n"
        "2026-05-22T10:00:00\t2.0\t0.1\t0.2\t410.0\t12.0\t101.3\t25.0\n",
        encoding="utf-8",
    )
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-001", name="TOB1"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, delimiter="\t", header_rows=3),
    )

    rows = load_raw_text_frames(tob1_path, metadata=metadata)

    assert len(rows) == 1
    assert rows[0].device_uid == "TOB1-001"
    assert rows[0].co2_ppm == 410.0
    assert json.loads(rows[0].raw_text)["u"] == 2.0


def test_external_biomet_overrides_rp_ambient_pressure_and_temperature(tmp_path: Path) -> None:
    start = datetime(2026, 5, 22, 10, 0, 0)
    sample_hz = 10.0
    samples = 600
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="bio",
                device_id="raw",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * np.roll(w, 5)[index]),
                h2o_mmol=float(12.0 + 1.3 * np.roll(w, 3)[index]),
                pressure_kpa=None,
                chamber_temp_c=None,
                raw_text=json.dumps({"u": 2.2, "v": 0.1, "w": float(w[index])}),
            )
        )
    biomet_path = tmp_path / "biomet.csv"
    biomet_path.write_text(
        "timestamp,ta,pressure_kpa\n"
        "2026-05-22T10:00:00,26.5,99.8\n"
        "2026-05-22T10:00:20,27.5,100.2\n",
        encoding="utf-8",
    )
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIO-001", name="Biomet"),
        site=SiteProfile(station_code="BIO", station_name="Biomet Tower"),
        biomet=BiometSourceMetadata(
            source_mode="external_file",
            source_path=str(biomet_path),
            fields=["ta", "pressure_kpa"],
            aggregation_method="mean",
        ),
    )
    config = {"sample_hz": sample_hz, "block_minutes": 0.5, "rotation_mode": "double", "detrend_mode": "linear"}

    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="biomet-test")
    first = result["rp_result"].windows[0]
    override = first.diagnostics["biomet_override"]

    assert override["status"] == "applied"
    assert set(override["applied_fields"]) == {"pressure_kpa", "temp_c"}
    assert round(first.mean_pressure_kpa, 3) == 100.0
    assert round(first.mean_temp_c, 3) == 27.0
    assert "pressure_kpa_missing" not in first.diagnostics["issues"]
    assert "temp_c_missing" not in first.diagnostics["issues"]
