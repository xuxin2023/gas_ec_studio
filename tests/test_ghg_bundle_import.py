from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from core.storage.ghg_bundle import inspect_ghg_bundle, load_ghg_biomet_records, read_ghg_tabular_member
from models.station_models import BiometSourceMetadata, aggregate_biomet_window, load_biomet_records


def _write_demo_ghg(path: Path) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("20260522-1000.data", "timestamp\tu\tv\tw\tco2\n2026-05-22T10:00:00\t2.0\t0.1\t0.2\t410.0\n")
        archive.writestr(
            "20260522-1000.metadata",
            "canopy_height=2.4\nacquisition_frequency=10\nanemometer_model=DemoSonic\n",
        )
        archive.writestr(
            "20260522-1000-biomet.data",
            "timestamp\tta\trh\tsw_in\n"
            "2026-05-22T10:00:00\t24.0\t70\t510\n"
            "2026-05-22T10:10:00\t24.6\t71\t520\n",
        )
        archive.writestr("20260522-1000-biomet.metadata", "ta_unit=degC\nrh_unit=percent\n")


def test_inspect_ghg_bundle_classifies_raw_metadata_and_biomet(tmp_path: Path) -> None:
    ghg_path = tmp_path / "demo.ghg"
    _write_demo_ghg(ghg_path)

    manifest = inspect_ghg_bundle(ghg_path)

    assert manifest.has_embedded_biomet is True
    assert manifest.raw_data_members == ["20260522-1000.data"]
    assert manifest.raw_metadata_members == ["20260522-1000.metadata"]
    assert manifest.biomet_data_members == ["20260522-1000-biomet.data"]
    assert manifest.metadata["20260522-1000.metadata"]["canopy_height"] == "2.4"


def test_load_ghg_biomet_records_and_aggregate_window(tmp_path: Path) -> None:
    ghg_path = tmp_path / "demo.ghg"
    _write_demo_ghg(ghg_path)

    rows = load_ghg_biomet_records(ghg_path, fields=["ta", "rh"])

    assert len(rows) == 2
    assert rows[0]["timestamp"] == datetime(2026, 5, 22, 10, 0, 0)
    assert rows[0]["ta"] == "24.0"
    assert "sw_in" not in rows[0]

    source = BiometSourceMetadata(source_mode="ghg_bundle", source_path=str(ghg_path), fields=["ta", "rh"])
    loaded = load_biomet_records(source)
    aggregated = aggregate_biomet_window(
        loaded,
        window_start=datetime(2026, 5, 22, 10, 0, 0),
        window_end=datetime(2026, 5, 22, 10, 30, 0),
        fields=["ta", "rh"],
    )
    assert aggregated["sample_count"] == 2
    assert aggregated["ta"] == 24.3


def test_read_ghg_tabular_member_supports_tabular_raw_data(tmp_path: Path) -> None:
    ghg_path = tmp_path / "demo.ghg"
    _write_demo_ghg(ghg_path)

    rows = read_ghg_tabular_member(ghg_path, "20260522-1000.data")

    assert rows[0]["co2"] == "410.0"
    assert rows[0]["w"] == "0.2"
