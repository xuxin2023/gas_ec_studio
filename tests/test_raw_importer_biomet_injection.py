from __future__ import annotations

import json
import struct
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.headless_batch_runner import load_input_rows, run_headless_batch
from core.exports.result_exporter import ResultExporter
from core.storage.raw_importer import _fp2_word_to_float, _inspect_tob1_header, load_raw_native_frames, load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import (
    BiometSourceMetadata,
    MetadataBundle,
    ProjectProfile,
    RawColumnMapping,
    RawFileDescriptionMetadata,
    RawFileSettingsMetadata,
    SamplingChainMetadata,
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
    assert rows[0].pressure_kpa == pytest.approx(101.3)
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


def test_native_tob1_ieee4_bridge_reads_binary_records(tmp_path: Path) -> None:
    tob1_path = tmp_path / "native.tob1"
    header = b"TOB1 fixture\r\nTIMESTAMP,U,V,W,CO2,H2O,P,TA\r\n"
    values = [
        (2.0, 0.1, 0.2, 410.0, 12.0, 101.3, 25.0),
        (2.1, 0.2, 0.3, 411.0, 12.5, 101.4, 25.1),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<7f", *row) for row in values))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1N-001", name="Native TOB1"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            header_rows=2,
            extra={
                "native_format": "tob1_ieee4",
                "columns": ["u", "v", "w", "co2", "h2o", "pressure", "temperature"],
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert rows[0].co2_ppm == 410.0
    assert json.loads(rows[0].raw_text)["raw_native_import"]["format"] == "tob1_ieee4"


def test_native_tob1_ieee4_auto_skips_leading_ulong_fields(tmp_path: Path) -> None:
    tob1_path = tmp_path / "ulong_ieee4.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.2, 410.0),
        (123457, 2, 2.6, 0.3, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I3f", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-ULONG-IEEE4", name="TOB1 ULONG IEEE4"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={"start_time": "2026-05-22T10:00:00"},
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-ulong-ieee4",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["u"] == pytest.approx(2.5)
    assert first_payload["w"] == pytest.approx(0.2)
    assert first_payload["raw_native_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert first_payload["raw_native_columns"]["tob1_leading_RECORD"] == 1
    assert provenance["columns"] == ["U", "W", "CO2"]
    assert provenance["tob1_eddypro_compatibility"]["status"] == "compatible"
    assert provenance["ulongs"] == 2
    assert provenance["leading_ulong_columns"] == ["TIMESTAMP", "RECORD"]
    assert provenance["preserved_leading_ulong_values"] is True
    assert provenance["leading_ulong_value_prefix"] == "tob1_leading_"
    assert provenance["raw_header_units"] == []
    assert provenance["raw_header_processing"] == []
    assert provenance["ulongs_source"] == "tob1_header"
    assert provenance["fp2_skip_words"] == 0
    assert manifest["raw_import_summary"]["leading_ulong_columns"] == ["TIMESTAMP", "RECORD"]
    assert manifest["raw_import_summary"]["preserved_leading_ulong_values"] is True
    assert manifest["raw_import_summary"]["leading_ulong_value_prefix"] == "tob1_leading_"
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_RECORD"] == 1


def test_native_tob1_ieee4_uses_record_seconds_nanoseconds_without_configured_start_time(tmp_path: Path) -> None:
    tob1_path = tmp_path / "seconds_ieee4.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"SECONDS","NANOSECONDS","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","ULONG","IEEE4","IEEE4","IEEE4"\r\n'
    )
    base = datetime(2026, 5, 22, 10, 0, 0)
    seconds = int((base - datetime(1990, 1, 1)).total_seconds())
    records = [
        (seconds, 0, 1, 2.5, 0.2, 410.0),
        (seconds, 100_000_000, 2, 2.6, 0.3, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<3I3f", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-SECONDS-IEEE4", name="TOB1 Seconds IEEE4"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-seconds-ieee4",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert first_payload["raw_native_columns"]["tob1_leading_SECONDS"] == seconds
    assert first_payload["raw_native_columns"]["tob1_leading_NANOSECONDS"] == 0
    assert provenance["timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert provenance["record_timestamp"]["status"] == "applied"
    assert provenance["record_timestamp"]["seconds_column"] == "tob1_leading_SECONDS"
    assert provenance["record_timestamp"]["nanoseconds_column"] == "tob1_leading_NANOSECONDS"
    assert provenance["record_timestamp"]["applied_count"] == 2
    assert provenance["filename_timestamp"]["status"] == "not_inferred"
    assert manifest["raw_import_summary"]["timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert manifest["raw_import_summary"]["record_timestamp"]["status"] == "applied"
    assert manifest["raw_import_summary"]["record_timestamp"]["first_timestamp"] == "2026-05-22T10:00:00"


def test_native_tob1_ieee4_decodes_header_mixed_ulong_payload_fields(tmp_path: Path) -> None:
    tob1_path = tmp_path / "mixed_ulong_ieee4.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","W","DIAG","CO2"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","ULONG","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.2, 65535, 410.0),
        (123457, 2, 2.6, 0.3, 65534, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I2fIf", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-MIXED-IEEE4", name="TOB1 Mixed IEEE4"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={"start_time": "2026-05-22T10:00:00"},
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-mixed-ulong-ieee4",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["u"] == pytest.approx(2.5)
    assert first_payload["w"] == pytest.approx(0.2)
    assert first_payload["raw_native_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert first_payload["raw_native_columns"]["tob1_leading_RECORD"] == 1
    assert first_payload["raw_native_columns"]["DIAG"] == 65535
    assert first_payload["raw_native_columns"]["CO2"] == pytest.approx(410.0)
    assert provenance["columns"] == ["U", "W", "DIAG", "CO2"]
    assert provenance["data_type"] == "mixed"
    assert provenance["column_types"] == ["float32", "float32", "uint32", "float32"]
    assert provenance["column_type_source"] == "tob1_header"
    assert provenance["tob1_eddypro_compatibility"]["status"] == "compatible"
    assert manifest["raw_import_summary"]["column_types"] == ["float32", "float32", "uint32", "float32"]
    assert manifest["raw_import_summary"]["column_type_source"] == "tob1_header"
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_RECORD"] == 1
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["DIAG"] == 65535
    assert manifest["raw_import_summary"]["sample_decoded_column_count"] == 6


def test_native_tob1_header_decodes_full_record_when_metadata_maps_subset(tmp_path: Path) -> None:
    tob1_path = tmp_path / "subset_mapped_ieee4.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","V","W","DIAG","CO2","H2O","P","TA"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","IEEE4","ULONG","IEEE4","IEEE4","IEEE4","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.1, 0.2, 65535, 410.0, 12.3, 101.3, 25.0),
        (123457, 2, 2.6, 0.2, 0.3, 65534, 411.0, 12.4, 101.4, 25.1),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I3fI4f", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-SUBSET", name="TOB1 Subset Mapping"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="tob1",
            column_mappings=[
                RawColumnMapping(column_name="CO2", variable="co2_ppm"),
                RawColumnMapping(column_name="W", variable="w"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={"start_time": "2026-05-22T10:00:00"},
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-subset-mapping",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["w"] == pytest.approx(0.2)
    assert first_payload["raw_native_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert first_payload["raw_native_columns"]["tob1_leading_RECORD"] == 1
    assert first_payload["raw_native_columns"]["DIAG"] == 65535
    assert first_payload["raw_native_columns"]["TA"] == pytest.approx(25.0)
    assert provenance["column_source"] == "tob1_header"
    assert provenance["full_record_decode"] is True
    assert provenance["columns"] == ["U", "V", "W", "DIAG", "CO2", "H2O", "P", "TA"]
    assert provenance["column_types"] == ["float32", "float32", "float32", "uint32", "float32", "float32", "float32", "float32"]
    assert provenance["column_type_source"] == "tob1_header"
    assert manifest["raw_import_summary"]["column_source"] == "tob1_header"
    assert manifest["raw_import_summary"]["full_record_decode"] is True
    assert manifest["raw_import_summary"]["preserved_leading_ulong_values"] is True
    assert manifest["raw_import_summary"]["sample_decoded_column_count"] == 10
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_RECORD"] == 1
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["DIAG"] == 65535


def test_native_tob1_explicit_subset_decodes_header_full_record_width(tmp_path: Path) -> None:
    tob1_path = tmp_path / "explicit_subset_ieee4.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","W","DIAG","CO2"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","ULONG","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.2, 65535, 410.0),
        (123457, 2, 2.6, 0.3, 65534, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I2fIf", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-EXPLICIT-SUBSET", name="TOB1 Explicit Subset"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "columns": ["W", "DIAG", "CO2"],
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-explicit-subset",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["u"] == pytest.approx(2.5)
    assert first_payload["w"] == pytest.approx(0.2)
    assert first_payload["raw_native_columns"]["DIAG"] == 65535
    assert provenance["requested_columns"] == ["W", "DIAG", "CO2"]
    assert provenance["requested_column_source"] == "extra"
    assert provenance["columns"] == ["U", "W", "DIAG", "CO2"]
    assert provenance["column_source"] == "tob1_header"
    assert provenance["full_record_decode"] is True
    assert provenance["column_types"] == ["float32", "float32", "uint32", "float32"]
    assert manifest["raw_import_summary"]["requested_columns"] == ["W", "DIAG", "CO2"]
    assert manifest["raw_import_summary"]["columns"] == ["U", "W", "DIAG", "CO2"]
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["U"] == pytest.approx(2.5)
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["DIAG"] == 65535


def test_native_tob1_infers_start_time_from_filename(tmp_path: Path) -> None:
    tob1_path = tmp_path / "tower_20260522-1000.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.2, 410.0),
        (123457, 2, 2.6, 0.3, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I3f", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-FILENAME-TS", name="TOB1 Filename Timestamp"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-filename-time",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert provenance["start_time"] == "2026-05-22T10:00:00"
    assert provenance["timestamp_source"] == "filename_auto"
    assert provenance["filename_timestamp"]["status"] == "inferred"
    assert manifest["raw_import_summary"]["start_time"] == "2026-05-22T10:00:00"
    assert manifest["raw_import_summary"]["timestamp_source"] == "filename_auto"
    assert manifest["raw_import_summary"]["filename_timestamp"]["filename"] == "tower_20260522-1000.tob1"


def test_native_tob1_infers_template_filename_doy_midnight_rollover(tmp_path: Path) -> None:
    tob1_path = tmp_path / "tower_2026143_2400.tob1"
    header = (
        b'"TOB1","IEEE4"\r\n'
        b'"TIMESTAMP","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","IEEE4","IEEE4","IEEE4"\r\n'
    )
    records = [
        (123456, 1, 2.5, 0.2, 410.0),
        (123457, 2, 2.6, 0.3, 411.0),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I3f", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-FILENAME-TEMPLATE", name="TOB1 Filename Template"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "filename_timestamp_template": "tower_yyyyddd_HHMM.tob1",
                "filename_timestamp_doy": True,
            },
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert rows[0].timestamp.isoformat() == "2026-05-24T00:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-24T00:00:00.100000"
    assert provenance["timestamp_source"] == "filename_template"
    assert provenance["filename_timestamp"]["template"] == "tower_yyyyddd_HHMM.tob1"
    assert provenance["filename_timestamp"]["doy_format"] is True


def test_native_tob1_fp2_bridge_decodes_campbell_words(tmp_path: Path) -> None:
    assert _fp2_word_to_float(1) == pytest.approx(256.0)
    assert _fp2_word_to_float(33) == pytest.approx(25.6)
    assert _fp2_word_to_float(65) == pytest.approx(2.56)
    assert _fp2_word_to_float(97) == pytest.approx(0.256)
    assert _fp2_word_to_float(129) == pytest.approx(-256.0)
    assert _fp2_word_to_float(289) == pytest.approx(25.7)

    def fp2_word(value: float, decimals: int) -> int:
        sign_bit = 0x80 if value < 0 else 0
        mantissa = int(round(abs(value) * (10**decimals)))
        low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
        high_byte = mantissa & 0xFF
        return (high_byte << 8) | low_byte

    tob1_path = tmp_path / "native_fp2.tob1"
    header = b'"TOB1","FP2"\r\nTIMESTAMP,U,V,W,CO2,H2O,P,TA\r\n'
    records = [
        (fp2_word(2.5, 1), fp2_word(-0.1, 1), fp2_word(0.2, 1), fp2_word(410.0, 1), fp2_word(12.34, 2), fp2_word(101.3, 1), fp2_word(25.6, 1)),
        (fp2_word(2.6, 1), fp2_word(-0.2, 1), fp2_word(0.3, 1), fp2_word(411.0, 1), fp2_word(12.35, 2), fp2_word(101.4, 1), fp2_word(25.7, 1)),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<7H", *row) for row in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1FP2-001", name="Native TOB1 FP2"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            header_rows=2,
            extra={
                "columns": ["u", "v", "w", "co2", "h2o", "pressure", "temperature"],
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert rows[0].h2o_mmol == pytest.approx(12.34)
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["v"] == pytest.approx(-0.1)
    assert provenance["format"] == "tob1_fp2"
    assert provenance["data_type"] == "fp2"
    assert "src/src_common/m_fp2_to_float.f90" in provenance["source_reference"]["eddypro_engine_files"]


def test_native_tob1_header_autodetects_format_columns_and_header_rows(tmp_path: Path) -> None:
    def fp2_word(value: float, decimals: int) -> int:
        sign_bit = 0x80 if value < 0 else 0
        mantissa = int(round(abs(value) * (10**decimals)))
        low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
        high_byte = mantissa & 0xFF
        return (high_byte << 8) | low_byte

    tob1_path = tmp_path / "autodetect_fp2.tob1"
    header = (
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"TS","RN","m/s","m/s","m/s","ppm","mmol/mol","kPa","C"\r\n'
        b'"Smp","Smp","Avg","Avg","Avg","Avg","Avg","Avg","Avg"\r\n'
    )
    records = [
        (fp2_word(2.5, 1), fp2_word(-0.1, 1), fp2_word(0.2, 1), fp2_word(410.0, 1), fp2_word(12.34, 2), fp2_word(101.3, 1), fp2_word(25.6, 1)),
        (fp2_word(2.6, 1), fp2_word(-0.2, 1), fp2_word(0.3, 1), fp2_word(411.0, 1), fp2_word(12.35, 2), fp2_word(101.4, 1), fp2_word(25.7, 1)),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<7H", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-AUTO", name="Auto TOB1"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={"start_time": "2026-05-22T10:00:00"},
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert rows[0].h2o_mmol == pytest.approx(12.34)
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["u"] == pytest.approx(2.5)
    assert provenance["format"] == "tob1_fp2"
    assert provenance["header_rows"] == 4
    assert provenance["header_row_source"] == "tob1_header"
    assert provenance["column_source"] == "tob1_header"
    assert provenance["columns"] == ["U", "V", "W", "CO2", "H2O", "P", "TA"]
    assert provenance["header_detection"]["raw_columns"] == ["TIMESTAMP", "RECORD", "U", "V", "W", "CO2", "H2O", "P", "TA"]
    assert provenance["raw_header_units"] == ["TS", "RN", "m/s", "m/s", "m/s", "ppm", "mmol/mol", "kPa", "C"]
    assert provenance["header_units"] == ["m/s", "m/s", "m/s", "ppm", "mmol/mol", "kPa", "C"]
    assert provenance["raw_header_processing"] == ["Smp", "Smp", "Avg", "Avg", "Avg", "Avg", "Avg", "Avg", "Avg"]
    assert provenance["header_processing"] == ["Avg", "Avg", "Avg", "Avg", "Avg", "Avg", "Avg"]
    assert provenance["header_detection"]["raw_units"] == provenance["raw_header_units"]
    assert provenance["header_detection"]["raw_processing"] == provenance["raw_header_processing"]
    assert provenance["tob1_eddypro_compatibility"]["status"] == "assumed_compatible"
    assert manifest["raw_import_summary"]["format"] == "tob1_fp2"
    assert manifest["raw_import_summary"]["header_detection"]["tob1_format"] == "fp2"
    assert manifest["raw_import_summary"]["header_detection"]["eddypro_compatibility"]["status"] == "assumed_compatible"
    assert manifest["raw_import_summary"]["tob1_eddypro_compatibility"]["status"] == "assumed_compatible"
    assert manifest["raw_import_summary"]["column_source"] == "tob1_header"
    assert manifest["raw_import_summary"]["raw_header_units"] == provenance["raw_header_units"]
    assert manifest["raw_import_summary"]["header_units"] == provenance["header_units"]
    assert manifest["raw_import_summary"]["raw_header_processing"] == provenance["raw_header_processing"]
    assert manifest["raw_import_summary"]["header_processing"] == provenance["header_processing"]


def test_native_tob1_header_reports_eddypro_data_type_compatibility(tmp_path: Path) -> None:
    compatible = tmp_path / "compatible.tob1"
    compatible.write_bytes(
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","FP2","FP2","FP2"\r\n'
        b"\x00\x00"
    )
    incompatible = tmp_path / "incompatible.tob1"
    incompatible.write_bytes(
        b'"TOB1","MIXED"\r\n'
        b'"TIMESTAMP","U","RECORD","W","CO2"\r\n'
        b'"ULONG","FP2","ULONG","FP2","IEEE4"\r\n'
        b"\x00\x00"
    )

    good = _inspect_tob1_header(compatible)["eddypro_compatibility"]
    bad = _inspect_tob1_header(incompatible)["eddypro_compatibility"]

    assert good["status"] == "compatible"
    assert good["leading_ulong_count"] == 2
    assert good["data_types"] == ["ULONG", "ULONG", "FP2", "FP2", "FP2"]
    assert bad["status"] == "incompatible"
    assert bad["compatible"] is False
    assert any("mixed IEEE4 and FP2" in reason for reason in bad["reasons"])
    assert any("ULONG fields to appear before FP2" in reason for reason in bad["reasons"])


def test_native_tob1_fp2_auto_skips_leading_ulong_fields(tmp_path: Path) -> None:
    def fp2_word(value: float, decimals: int) -> int:
        sign_bit = 0x80 if value < 0 else 0
        mantissa = int(round(abs(value) * (10**decimals)))
        low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
        high_byte = mantissa & 0xFF
        return (high_byte << 8) | low_byte

    tob1_path = tmp_path / "ulong_fp2.tob1"
    header = (
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","FP2","FP2","FP2"\r\n'
    )
    records = [
        (123456, 1, fp2_word(2.5, 1), fp2_word(0.2, 1), fp2_word(410.0, 1)),
        (123457, 2, fp2_word(2.6, 1), fp2_word(0.3, 1), fp2_word(411.0, 1)),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<2I3H", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-ULONG-FP2", name="TOB1 ULONG FP2"),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={"start_time": "2026-05-22T10:00:00"},
        ),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-ulong-fp2",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["u"] == pytest.approx(2.5)
    assert first_payload["w"] == pytest.approx(0.2)
    assert first_payload["raw_native_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert first_payload["raw_native_columns"]["tob1_leading_RECORD"] == 1
    assert provenance["columns"] == ["U", "W", "CO2"]
    assert provenance["tob1_eddypro_compatibility"]["status"] == "compatible"
    assert provenance["ulongs"] == 2
    assert provenance["leading_ulong_columns"] == ["TIMESTAMP", "RECORD"]
    assert provenance["preserved_leading_ulong_values"] is True
    assert provenance["leading_ulong_value_prefix"] == "tob1_leading_"
    assert provenance["ulongs_source"] == "tob1_header"
    assert provenance["fp2_skip_words"] == 4
    assert manifest["raw_import_summary"]["fp2_skip_words"] == 4
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_TIMESTAMP"] == 123456
    assert manifest["raw_import_summary"]["sample_decoded_columns"]["tob1_leading_RECORD"] == 1


def test_native_tob1_fp2_uses_record_seconds_nanoseconds_without_configured_start_time(tmp_path: Path) -> None:
    def fp2_word(value: float, decimals: int) -> int:
        sign_bit = 0x80 if value < 0 else 0
        mantissa = int(round(abs(value) * (10**decimals)))
        low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
        high_byte = mantissa & 0xFF
        return (high_byte << 8) | low_byte

    tob1_path = tmp_path / "seconds_fp2.tob1"
    header = (
        b'"TOB1","FP2"\r\n'
        b'"SECONDS","NANOSECONDS","RECORD","U","W","CO2"\r\n'
        b'"ULONG","ULONG","ULONG","FP2","FP2","FP2"\r\n'
    )
    base = datetime(2026, 5, 22, 10, 0, 0)
    seconds = int((base - datetime(1990, 1, 1)).total_seconds())
    records = [
        (seconds, 0, 1, fp2_word(2.5, 1), fp2_word(0.2, 1), fp2_word(410.0, 1)),
        (seconds, 100_000_000, 2, fp2_word(2.6, 1), fp2_word(0.3, 1), fp2_word(411.0, 1)),
    ]
    tob1_path.write_bytes(header + b"".join(struct.pack("<3I3H", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="TOB1-SECONDS-FP2", name="TOB1 Seconds FP2"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0),
    )

    rows = load_input_rows(tob1_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "none"},
        metadata=metadata,
        rows=rows,
        data_source="auto-tob1-seconds-fp2",
    )["manifest"]
    first_payload = json.loads(rows[0].raw_text)
    provenance = first_payload["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00"
    assert rows[1].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert first_payload["raw_native_columns"]["CO2"] == pytest.approx(410.0)
    assert provenance["timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert provenance["record_timestamp"]["status"] == "applied"
    assert provenance["fp2_skip_words"] == 6
    assert manifest["raw_import_summary"]["timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert manifest["raw_import_summary"]["record_timestamp"]["applied_count"] == 2


def test_native_generic_binary_bridge_uses_column_mappings_and_manifest(tmp_path: Path) -> None:
    binary_path = tmp_path / "native.bin"
    records = [
        (4100, 120, 1013, 250, 20, 1, 2),
        (4110, 121, 1014, 251, 21, 2, 3),
    ]
    binary_path.write_bytes(b"".join(struct.pack("<7h", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIN-001", name="Binary Raw"),
        site=SiteProfile(station_code="BIN", station_name="Binary Tower"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="binary",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm", scaling=0.1),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol", scaling=0.1),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u", scaling=0.1),
                RawColumnMapping(column_name="v_raw", variable="v", scaling=0.1),
                RawColumnMapping(column_name="w_raw", variable="w", scaling=0.1),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "binary_int16",
                "data_type": "int16",
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_raw_native_frames(binary_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="native-binary",
    )["manifest"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == 410.0
    assert rows[0].h2o_mmol == 12.0
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["u"] == 2.0
    assert manifest["raw_import_summary"]["native"] is True
    assert manifest["raw_import_summary"]["format"] == "binary_int16"


def test_native_generic_binary_bridge_respects_record_framing(tmp_path: Path) -> None:
    binary_path = tmp_path / "framed_native.bin"
    records = [
        (4100, 120, 1013, 250, 20, 1, 2),
        (4110, 121, 1014, 251, 21, 2, 3),
    ]
    payload = bytearray(b"ASCII HEADER\n")
    for index, record in enumerate(records):
        payload.extend(bytes([0xA0 + index, 0x5A]))
        payload.extend(struct.pack("<7h", *record))
        payload.extend(b"\x00\xff")
    binary_path.write_bytes(bytes(payload))
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIN-FRAMED", name="Framed Binary Raw"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="binary",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm", scaling=0.1),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol", scaling=0.1),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u", scaling=0.1),
                RawColumnMapping(column_name="v_raw", variable="v", scaling=0.1),
                RawColumnMapping(column_name="w_raw", variable="w", scaling=0.1),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            header_rows=1,
            extra={
                "native_format": "binary_int16",
                "data_type": "int16",
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "header_rows": 1,
                "record_header_bytes": 2,
                "record_footer_bytes": 2,
                "record_length_bytes": 18,
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_raw_native_frames(binary_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="framed-native-binary",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == 410.0
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["u"] == 2.0
    assert provenance["record_header_bytes"] == 2
    assert provenance["record_footer_bytes"] == 2
    assert provenance["record_length_bytes"] == 18


def test_native_generic_binary_bridge_respects_header_eol_and_record_selection(tmp_path: Path) -> None:
    binary_path = tmp_path / "record_selection_native.bin"
    records = [
        (4000, 110, 1000, 240, 10, 1, 2),
        (4100, 120, 1013, 250, 20, 2, 3),
        (4110, 121, 1014, 251, 21, 3, 4),
    ]
    header = b"first header line\rsecond header line\r"
    binary_path.write_bytes(header + b"".join(struct.pack("<7h", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIN-SELECT", name="Selected Binary Raw"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="binary",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm", scaling=0.1),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol", scaling=0.1),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u", scaling=0.1),
                RawColumnMapping(column_name="v_raw", variable="v", scaling=0.1),
                RawColumnMapping(column_name="w_raw", variable="w", scaling=0.1),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "binary_int16",
                "data_type": "int16",
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "header_rows": 2,
                "ascii_header_eol": "CR",
                "first_record": 2,
                "last_record": 3,
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_raw_native_frames(binary_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="selected-native-binary",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].timestamp.isoformat() == "2026-05-22T10:00:00.100000"
    assert rows[0].co2_ppm == 410.0
    assert rows[1].co2_ppm == 411.0
    assert provenance["decoded_record_count"] == 3
    assert provenance["record_count"] == 2
    assert provenance["ascii_header_eol"] == "cr"
    assert provenance["header_bytes"] == len(header)
    assert provenance["first_record"] == 2
    assert provenance["last_record"] == 3
    assert provenance["record_index_offset"] == 1
    assert manifest["raw_import_summary"]["decoded_record_count"] == 3
    assert manifest["raw_import_summary"]["ascii_header_eol"] == "cr"
    assert manifest["raw_import_summary"]["first_record"] == 2


def test_native_generic_binary_bridge_decodes_mixed_column_types(tmp_path: Path) -> None:
    binary_path = tmp_path / "mixed_native.bin"
    records = [
        (410.25, 12.5, 1013, 251, 2.2, 0.1, 0.2),
        (411.50, 12.7, 1014, 252, 2.3, 0.2, 0.3),
    ]
    binary_path.write_bytes(b"".join(struct.pack("<ffhhfff", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIN-MIXED", name="Mixed Binary Raw"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="binary",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm"),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol"),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u"),
                RawColumnMapping(column_name="v_raw", variable="v"),
                RawColumnMapping(column_name="w_raw", variable="w"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "binary",
                "data_type": "int16",
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "column_types": {
                    "co2_raw": "float32",
                    "h2o_raw": "float32",
                    "u_raw": "float32",
                    "v_raw": "float32",
                    "w_raw": "float32",
                },
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_raw_native_frames(binary_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="mixed-native-binary",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].co2_ppm == pytest.approx(410.25)
    assert rows[0].h2o_mmol == pytest.approx(12.5)
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["u"] == pytest.approx(2.2)
    assert provenance["data_type"] == "mixed"
    assert provenance["column_types"] == ["float32", "float32", "int16", "int16", "float32", "float32", "float32"]
    assert manifest["raw_import_summary"]["data_type"] == "mixed"
    assert manifest["raw_import_summary"]["column_types"] == provenance["column_types"]


def test_native_slt_edisol_bridge_reads_int16_payload(tmp_path: Path) -> None:
    slt_path = tmp_path / "native.slt"
    header = bytes(range(20))
    records = [
        (4100, 120, 1013, 250, 20, 1, 2),
        (4110, 121, 1014, 251, 21, 2, 3),
    ]
    slt_path.write_bytes(header + b"".join(struct.pack("<7h", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="SLT-001", name="SLT"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="slt_edisol",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm", scaling=0.1),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol", scaling=0.1),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u", scaling=0.1),
                RawColumnMapping(column_name="v_raw", variable="v", scaling=0.1),
                RawColumnMapping(column_name="w_raw", variable="w", scaling=0.1),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "slt_edisol",
                "header_bytes": 20,
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_input_rows(slt_path, metadata=metadata)

    assert len(rows) == 2
    assert rows[0].co2_ppm == 410.0
    assert rows[0].device_id == "slt_edisol"
    assert json.loads(rows[0].raw_text)["raw_native_import"]["source_reference"]["eddypro_engine_files"] == [
        "src/src_common/import_slt_edisol.f90"
    ]


def test_native_slt_eddysoft_bridge_applies_high_resolution_mask(tmp_path: Path) -> None:
    slt_path = tmp_path / "eddysoft.slt"
    columns = ["u_raw", "v_raw", "w_raw", "ts_raw", "co2_raw", "h2o_raw", "p_raw"]
    header = bytearray(8 + (len(columns) - 4) * 2)
    header[8] = 1
    header[10] = 2
    header[12] = 3
    records = [
        (20, 1, 2, 250, -20900, 120, -23987),
        (21, 2, 3, 251, -20890, 121, -23986),
    ]
    slt_path.write_bytes(bytes(header) + b"".join(struct.pack("<7h", *record) for record in records))
    metadata = MetadataBundle(
        project=ProjectProfile(code="SLT-EDDY", name="SLT EddySoft"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="slt_eddysoft",
            column_mappings=[
                RawColumnMapping(column_name="u_raw", variable="u", scaling=0.1),
                RawColumnMapping(column_name="v_raw", variable="v", scaling=0.1),
                RawColumnMapping(column_name="w_raw", variable="w", scaling=0.1),
                RawColumnMapping(column_name="ts_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm"),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol", scaling=0.1),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "slt_eddysoft",
                "columns": columns,
                "start_time": "2026-05-22T10:00:00",
            },
        ),
    )

    rows = load_input_rows(slt_path, metadata=metadata)
    manifest = run_headless_batch(
        config={"sample_hz": 10.0, "block_minutes": 0.1, "rotation_mode": "double"},
        metadata=metadata,
        rows=rows,
        data_source="slt-eddysoft",
    )["manifest"]
    provenance = json.loads(rows[0].raw_text)["raw_native_import"]

    assert len(rows) == 2
    assert rows[0].device_id == "slt_eddysoft"
    assert rows[0].co2_ppm == pytest.approx(410.0)
    assert rows[0].h2o_mmol == pytest.approx(12.0)
    assert rows[0].pressure_kpa == pytest.approx(101.3)
    assert json.loads(rows[0].raw_text)["u"] == pytest.approx(2.0)
    assert provenance["header_detection"]["mask_bytes"] == [1, 2, 3]
    assert provenance["header_detection"]["high_resolution_columns"] == ["co2_raw", "p_raw"]
    assert provenance["header_detection"]["low_resolution_columns"] == ["h2o_raw"]
    assert "src/src_common/import_slt_eddysoft.f90" in provenance["source_reference"]["eddypro_engine_files"]
    assert manifest["raw_import_summary"]["header_detection"]["high_resolution_columns"] == ["co2_raw", "p_raw"]


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
        "timestamp,ta,pressure_kpa,rh\n"
        "2026-05-22T10:00:00,26.5,99.8,62\n"
        "2026-05-22T10:00:20,27.5,100.2,64\n",
        encoding="utf-8",
    )
    metadata = MetadataBundle(
        project=ProjectProfile(code="BIO-001", name="Biomet"),
        site=SiteProfile(station_code="BIO", station_name="Biomet Tower"),
        biomet=BiometSourceMetadata(
            source_mode="external_file",
            source_path=str(biomet_path),
            fields=["ta", "pressure_kpa", "rh"],
            aggregation_method="mean",
        ),
    )
    config = {"sample_hz": sample_hz, "block_minutes": 0.5, "rotation_mode": "double", "detrend_mode": "linear"}

    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="biomet-test")
    first = result["rp_result"].windows[0]
    override = first.diagnostics["biomet_override"]

    assert override["status"] == "applied"
    assert set(override["applied_fields"]) == {"pressure_kpa", "temp_c", "mean_h2o_mmol"}
    assert round(first.mean_pressure_kpa, 3) == 100.0
    assert round(first.mean_temp_c, 3) == 27.0
    assert first.mean_h2o_mmol == pytest.approx(22.48, rel=0.02)
    assert first.diagnostics["biomet_ambient_status"] == "applied"
    assert first.diagnostics["biomet_ambient_values"]["mean_h2o_mmol"] == pytest.approx(first.mean_h2o_mmol)
    assert first.diagnostics["biomet_ambient_h2o_source"] == "derived:relative_humidity"
    ledger_stages = first.diagnostics["flux_correction_ledger"]["stages"]
    assert any(stage["stage"] == "ambient_thermodynamics" and stage["biomet_status"] == "applied" for stage in ledger_stages)
    export_rows = ResultExporter(tmp_path / "exports")._full_output_rows(
        rp_result=result["rp_result"],
        spectral_result=None,
        mode="standard_schema",
    )
    assert export_rows[0]["biomet_ambient_status"] == "applied"
    assert "mean_h2o_mmol" in export_rows[0]["biomet_ambient_applied_fields"]
    assert "pressure_kpa_missing" not in first.diagnostics["issues"]
    assert "temp_c_missing" not in first.diagnostics["issues"]


def test_closed_path_cell_metadata_overrides_rp_ambient_when_biomet_missing(tmp_path: Path) -> None:
    start = datetime(2026, 5, 22, 10, 0, 0)
    sample_hz = 10.0
    samples = 600
    time_axis = np.arange(samples, dtype=float) / sample_hz
    w = 0.45 * np.sin(2.0 * np.pi * 0.21 * time_axis) + 0.08 * np.cos(2.0 * np.pi * 0.61 * time_axis)
    rows = [
        NormalizedHFFrame(
            timestamp=start + timedelta(seconds=float(time_axis[index])),
            device_uid="closed-path",
            device_id="raw",
            mode=2,
            frame_quality=FrameQuality.FULL,
            co2_ppm=float(411.0 + 8.0 * np.roll(w, 4)[index]),
            h2o_mmol=float(11.5 + 1.1 * np.roll(w, 2)[index]),
            pressure_kpa=None,
            chamber_temp_c=None,
            raw_text=json.dumps({"u": 2.0, "v": 0.1, "w": float(w[index])}),
        )
        for index in range(samples)
    ]
    metadata = MetadataBundle(
        project=ProjectProfile(code="CELL-001", name="Closed Path Cell"),
        site=SiteProfile(station_code="CELL", station_name="Closed Path Tower"),
        sampling_chain=SamplingChainMetadata(
            tube_length_m=12.0,
            tube_diameter_mm=4.0,
            flow_lpm=8.0,
            extra={"cell_pressure_kpa": 99.6, "cell_temperature_c": 24.4},
        ),
    )
    config = {"sample_hz": sample_hz, "block_minutes": 0.5, "rotation_mode": "double", "detrend_mode": "linear"}

    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="closed-path-cell-test")
    first = result["rp_result"].windows[0]
    diagnostics = first.diagnostics

    assert diagnostics["configured_ambient_status"] == "applied"
    assert diagnostics["configured_ambient_values"] == {"mean_pressure_kpa": 99.6, "mean_temp_c": 24.4}
    assert diagnostics["ambient_override_source"] == "configured_closed_path"
    assert round(first.mean_pressure_kpa, 3) == 99.6
    assert round(first.mean_temp_c, 3) == 24.4
    assert "pressure_kpa_missing" not in diagnostics["issues"]
    assert "temp_c_missing" not in diagnostics["issues"]
    ledger_stages = diagnostics["flux_correction_ledger"]["stages"]
    assert any(stage["stage"] == "ambient_thermodynamics" and stage["configured_status"] == "applied" for stage in ledger_stages)

    export_rows = ResultExporter(tmp_path / "exports")._full_output_rows(
        rp_result=result["rp_result"],
        spectral_result=None,
        mode="standard_schema",
    )
    assert export_rows[0]["configured_ambient_status"] == "applied"
    assert "pressure_kpa" in export_rows[0]["configured_ambient_applied_fields"]
