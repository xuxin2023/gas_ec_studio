from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from core.storage.ghg_bundle import (
    inspect_ghg_bundle,
    load_ghg_biomet_records,
    load_ghg_normalized_frames,
    read_ghg_tabular_member,
    read_ghg_status_records,
)
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
    assert manifest.status_members == []
    assert manifest.has_li7700_status is False
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


def test_load_ghg_normalized_frames_maps_raw_rows(tmp_path: Path) -> None:
    ghg_path = tmp_path / "demo.ghg"
    _write_demo_ghg(ghg_path)

    frames = load_ghg_normalized_frames(ghg_path)

    assert len(frames) == 1
    assert frames[0].timestamp == datetime(2026, 5, 22, 10, 0, 0)
    assert frames[0].device_uid == "demo"
    assert frames[0].device_id == "ghg"
    assert frames[0].co2_ppm == 410.0
    assert '"u": 2.0' in frames[0].raw_text


def test_load_ghg_normalized_frames_maps_real_licor_datah_rows(tmp_path: Path) -> None:
    ghg_path = tmp_path / "licor_datah.ghg"
    with ZipFile(ghg_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "2021-08-21T000000_AIU-0737.data",
            "Model:\tLI-7500A Open Path CO2/H2O Analyzer\n"
            "Timestamp:\t00:00:00\n"
            "DATAH\tSeconds\tNanoseconds\tDate\tTime\tCO2 (umol/mol)\tH2O (mmol/mol)\tPressure (kPa)\tU (m/s)\tV (m/s)\tW (m/s)\tT (C)\tCH4 (umol/mol)\n"
            "DATA\t1629525600\t100000000\t2021-08-21\t00:00:00:100\t402.4\t18.0\t94.4\t1.1\t0.2\t0.3\t20.5\t1.85\n",
        )
        archive.writestr("2021-08-21T000000_AIU-0737.metadata", "site_name=LERS\n")

    rows = read_ghg_tabular_member(ghg_path, "2021-08-21T000000_AIU-0737.data")
    frames = load_ghg_normalized_frames(ghg_path)

    assert rows[0]["CO2 (umol/mol)"] == "402.4"
    assert len(frames) == 1
    assert frames[0].timestamp == datetime(2021, 8, 21, 0, 0, 0, 100000)
    assert frames[0].co2_ppm == 402.4
    assert frames[0].h2o_mmol == 18.0
    assert frames[0].pressure_kpa == 94.4
    assert frames[0].ch4_ppb == 1850.0
    assert '"w": 0.3' in frames[0].raw_text


def test_read_ghg_status_records_supports_licor_datastat_rows(tmp_path: Path) -> None:
    ghg_path = tmp_path / "licor_status.ghg"
    with ZipFile(ghg_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("2021-08-21T000000_AIU-0737.data", "timestamp\tu\tv\tw\tco2\n2021-08-21T00:00:00\t1\t0\t0.1\t400\n")
        archive.writestr(
            "2021-08-21T000000_AIU-0737-li7700.status",
            "Model:\tLI-7700\n"
            "DATASTATH\tMSEC\tSECONDS\tNANOSECONDS\tDIAG\tRSSI\tREFRSSI\tOPTICSTEMP\n"
            "DATASTAT\t1419595000\t1629525600\t87000000\t16399\t4.82149\t69.6491\t21.9707\n",
        )

    manifest = inspect_ghg_bundle(ghg_path)
    records = read_ghg_status_records(ghg_path)

    assert manifest.status_members == ["2021-08-21T000000_AIU-0737-li7700.status"]
    assert manifest.has_li7700_status is True
    assert len(records) == 1
    assert records[0]["DIAG"] == "16399"
    assert records[0]["__epoch_ns__"] == 1629525600087000000


def test_load_ghg_normalized_frames_injects_li7700_status_payload(tmp_path: Path) -> None:
    ghg_path = tmp_path / "licor_li7700_status.ghg"
    with ZipFile(ghg_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "2021-08-21T000000_AIU-0737.data",
            "Model:\tLI-7500A Open Path CO2/H2O Analyzer\n"
            "DATAH\tSeconds\tNanoseconds\tDate\tTime\tU (m/s)\tV (m/s)\tW (m/s)\tCO2 (umol/mol)\tCH4 (umol/mol)\tCH4 Signal Strength\tCH4 Diagnostic Value\n"
            "DATA\t1629525600\t100000000\t2021-08-21\t00:00:00:100\t1.1\t0.2\t0.3\t402.4\t1.85\t4.9\t16399\n",
        )
        archive.writestr(
            "2021-08-21T000000_AIU-0737-li7700.status",
            "Model:\tLI-7700\n"
            "DATASTATH\tMSEC\tSECONDS\tNANOSECONDS\tDIAG\tRSSI\tREFRSSI\tOPTICSTEMP\n"
            "DATASTAT\t1419595000\t1629525600\t87000000\t16399\t4.82149\t69.6491\t21.9707\n",
        )

    frames = load_ghg_normalized_frames(ghg_path)

    assert len(frames) == 1
    assert '"li7700_rssi": 4.9' in frames[0].raw_text
    assert '"li7700_status_word": 16399' in frames[0].raw_text
    assert '"li7700_reference_rssi": 69.6491' in frames[0].raw_text
    assert '"li7700_status_source_member": "2021-08-21T000000_AIU-0737-li7700.status"' in frames[0].raw_text
    assert '"li7700_status_match_basis": "epoch_seconds"' in frames[0].raw_text


def test_load_ghg_biomet_records_maps_real_licor_datah_rows(tmp_path: Path) -> None:
    ghg_path = tmp_path / "licor_biomet.ghg"
    with ZipFile(ghg_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("2021-08-21T000000_AIU-0737.data", "timestamp\tu\tv\tw\tco2\n2021-08-21T00:00:00\t1\t0\t0.1\t400\n")
        archive.writestr("2021-08-21T000000_AIU-0737.metadata", "site_name=LERS\n")
        archive.writestr(
            "2021-08-21T000000_AIU-0737-biomet.data",
            "Instrument:\tsf3\n"
            "DATAH\tDATE\tTIME\tTA_1_1_1(C)\tRH_1_1_1(%)\n"
            "DATA\t2021-08-21\t00:01:00:000\t22.4\t94.6\n",
        )
        archive.writestr("2021-08-21T000000_AIU-0737-biomet.metadata", "biomet_header_rows=6\n")

    rows = load_ghg_biomet_records(ghg_path)

    assert len(rows) == 1
    assert rows[0]["timestamp"] == datetime(2021, 8, 21, 0, 1, 0)
    assert rows[0]["TA_1_1_1(C)"] == "22.4"
