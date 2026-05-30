from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
import zipfile

from core.comparison.fixture_pack import (
    acquire_public_eddypro_fixture_files,
    build_fixture_pack_summary,
    build_official_raw_fixture_detail,
    build_official_raw_fixture_manifest,
    build_public_eddypro_fixture_catalog,
    build_public_full_output_fixture_summary,
    build_public_official_raw_fixture_summary,
    build_public_raw_search_summary,
    build_public_spectral_fixture_summary,
    inspect_public_official_raw_archive,
    load_fixture_pack,
    materialize_public_official_raw_bundle_draft,
    validate_fixture_asset,
)
from core.headless_batch_runner import build_batch_manifest, run_cli
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.rp_models import RPRunResult
from models.spectral_models import SpectralRunResult
from models.station_models import MetadataBundle


def test_fixture_pack_registry_lists_real_and_ygas_assets() -> None:
    pack = load_fixture_pack()
    ids = {asset["fixture_id"] for asset in pack["assets"]}
    tiers = {asset["tier"] for asset in pack["assets"]}

    assert pack["fixture_pack_id"] == "eddypro_real_fixture_pack_v1"
    assert "eddypro_v7_real_temperate_forest_001" in ids
    assert "eddypro_v7_real_grassland_002" in ids
    assert "synthetic_raw_csv_001" in ids
    assert "synthetic_li7700_trace_gas_001" in ids
    assert "eddypro_source_tob1_seconds_001" in ids
    assert "ygas_protocol_manual_001" in ids
    assert "real_reference_output" in tiers
    assert "raw_to_final_parity" in tiers
    assert "manual_protocol_validation" in tiers


def test_fixture_pack_summary_validates_hashes_windows_and_protocol_rows() -> None:
    summary = build_fixture_pack_summary()

    assert summary["status"] == "pass"
    assert summary["asset_count"] >= 7
    assert summary["tier_counts"]["real_reference_output"] == 2
    assert summary["tier_counts"]["raw_to_final_parity"] == 4
    assert summary["real_reference_window_count"] == 11
    assert summary["protocol_validation_row_count"] == 2
    assert summary["raw_to_final_fixture_count"] == 4
    assert summary["raw_to_final_pass_count"] == 4
    assert summary["public_spectral_status"] == "pass"
    assert summary["public_spectral_fixture_count"] == 3
    assert summary["public_full_output_status"] == "pass"
    assert summary["public_full_output_fixture_count"] == 3
    assert summary["public_official_raw_status"] == "pass"
    assert summary["public_official_raw_candidate_count"] == 1
    assert summary["public_raw_search_status"] == "pass"
    assert summary["public_raw_search_lead_count"] >= 4
    assert summary["public_raw_search_raw_data_candidate_count"] == 0
    assert summary["public_eddypro_fixture_catalog_status"] == "pass"
    assert not summary["errors"]
    assert summary["official_source_inventory"]["inventory_id"] == "eddypro_official_source_inventory_v1"
    assert summary["official_source_inventory"]["feature_count"] >= 10

    by_id = {asset["fixture_id"]: asset for asset in summary["assets"]}
    forest = by_id["eddypro_v7_real_temperate_forest_001"]
    assert forest["window_count"] == 6
    assert forest["hashes"]["reference_json"] == "5AD54CEE5B2E2DF9CEDC4325AA3131AA67AACA44C917E85B39A5B30E95987616"
    assert forest["provenance"]["normalization_script"] == "references/eddypro/normalize_reference.py"

    ygas = by_id["ygas_protocol_manual_001"]
    assert ygas["row_count"] == 2
    assert ygas["modes"] == [1, 2]
    assert ygas["device_ids"] == ["001", "087"]

    raw_to_final = by_id["synthetic_raw_csv_001"]
    assert raw_to_final["raw_row_count"] == 240
    assert raw_to_final["window_count"] == 1
    assert raw_to_final["reference_window_count"] == 1
    assert raw_to_final["raw_to_final_parity"]["status"] == "pass"
    assert raw_to_final["raw_to_final_parity"]["raw_input"]["import_summary"]["format"] == "tabular_or_normalized"
    assert raw_to_final["raw_to_final_parity"]["benchmark_summary"]["pass_rate"] == 1.0
    assert raw_to_final["raw_to_final_parity"]["parity_diagnostics"]["artifact_type"] == "raw_to_final_parity_diagnostics_v1"

    source_tob1 = by_id["eddypro_source_tob1_seconds_001"]
    assert source_tob1["status"] == "pass"
    assert source_tob1["raw_row_count"] == 600
    assert source_tob1["raw_to_final_parity"]["status"] == "pass"
    assert source_tob1["raw_to_final_parity"]["raw_input"]["format"] == "tob1_ieee4"
    assert source_tob1["raw_to_final_parity"]["raw_input"]["import_summary"]["format"] == "tob1_ieee4"
    assert source_tob1["raw_to_final_parity"]["raw_input"]["import_summary"]["timestamp_source"] == "tob1_record_seconds_nanoseconds"
    assert source_tob1["raw_to_final_parity"]["raw_input"]["import_summary"]["leading_ulong_columns"] == ["SECONDS", "NANOSECONDS", "RECORD"]
    assert source_tob1["raw_to_final_parity"]["benchmark_summary"]["pass_rate"] == 1.0
    assert raw_to_final["raw_to_final_parity"]["parity_diagnostics"]["status"] == "ok"
    assert raw_to_final["hashes"]["raw_file"] == "FFE05EEDE5539019F2E38ECEA18A273ECCD6EB470A493066762CB911732E4DDE"

    li7700 = by_id["synthetic_li7700_trace_gas_001"]
    assert li7700["raw_row_count"] == 240
    assert li7700["raw_to_final_parity"]["status"] == "pass"
    assert li7700["raw_to_final_parity"]["trace_gas_parity"]["status"] == "pass"
    assert li7700["raw_to_final_parity"]["trace_gas_parity"]["coefficient_profile_id"] == "synthetic_li7700_profile"
    assert li7700["raw_to_final_parity"]["trace_gas_parity"]["comparison_count"] == 6
    assert li7700["provenance"]["normalization_time"] == "2026-05-27T10:00:00"


def test_raw_to_final_fixture_allows_embedded_ghg_metadata_without_metadata_json(tmp_path: Path) -> None:
    raw_file = tmp_path / "sample.ghg"
    raw_file.write_text("placeholder ghg archive\n", encoding="utf-8")
    asset = {
        "fixture_id": "embedded_ghg_missing_metadata_json",
        "tier": "raw_to_final_parity",
        "software": "EddyPro",
        "raw_file": str(raw_file),
        "reference_json": "missing_reference.json",
    }

    result = validate_fixture_asset(asset, workspace_root=tmp_path)

    assert result["files"]["metadata_json"] == ""
    assert "metadata_json" not in result["hashes"]
    assert any("reference_json missing" in error for error in result["errors"])


def test_public_eddypro_spectral_fixture_validates_downloaded_zenodo_files() -> None:
    summary = build_public_spectral_fixture_summary()

    assert summary["status"] == "pass"
    assert summary["dataset_id"] == "10.5281/zenodo.13254312"
    assert summary["license"] == "CC-BY-4.0"
    assert summary["fixture_count"] == 3
    assert summary["valid_fixture_count"] == 3
    assert summary["qc_mapping"]["strategy"] == "not_applicable_spectral_fixture"
    assert "Invoke-WebRequest" in summary["normalization_command"]
    assert not summary["errors"]

    by_id = {item["file_id"]: item for item in summary["files"]}
    assert by_id["con_ec_2020_af_cospectra"]["md5"] == "2AC9C9C3D07CAE5E9D84CC8BF7B954E7"
    assert by_id["con_ec_2020_af_cospectra"]["frequency_column_count"] >= 2
    assert by_id["con_ec_2020_af_cospectra"]["numeric_row_count"] >= 30
    assert by_id["con_ec_2020_af_spectra_co2"]["md5_status"] == "pass"
    assert by_id["con_ec_2020_af_spectra_co2"]["numeric_row_count"] >= 20
    assert by_id["con_ec_2020_af_spectra_h2o"]["md5_status"] == "pass"
    assert by_id["con_ec_2020_af_spectra_h2o"]["numeric_value_count"] > by_id["con_ec_2020_af_spectra_co2"]["numeric_value_count"]


def test_public_eddypro_full_output_sample_validates_downloaded_zenodo_files() -> None:
    summary = build_public_full_output_fixture_summary()

    assert summary["status"] == "pass"
    assert summary["dataset_id"] == "10.5281/zenodo.4005781"
    assert summary["license"] == "CC-BY-4.0"
    assert summary["fixture_count"] == 3
    assert summary["valid_fixture_count"] == 3
    assert summary["sample_row_count"] >= 800
    assert summary["sample_column_count"] == 159
    assert summary["descriptor_variable_count"] >= 150
    assert summary["qc_mapping"]["strategy"] == "preserve_eddypro_qc_columns"
    assert summary["original_files"][0]["expected_md5"] == "182cd0036d0df119bdbf01c1dd31f80a"
    assert not summary["errors"]

    by_id = {item["file_id"]: item for item in summary["files"]}
    sample = by_id["namors_full_output_head_1mib"]
    assert sample["md5"] == "61A035DEF8963025B375E50BD325A519"
    assert sample["first_timestamp"] == "2005-12-04 23:00"
    assert sample["last_timestamp"]
    assert sample["missing_columns"] == []
    assert sample["has_energy_flux_fields"] is True
    assert sample["has_uncertainty_fields"] is True
    assert sample["has_footprint_fields"] is True

    descriptor = by_id["namors_varnames_units"]
    assert descriptor["md5"] == "67237F90C68E5103694D09582EFD0D8E"
    assert descriptor["missing_variables"] == []
    assert descriptor["category_counts"]["corrected_fluxes_and_quality_flags"] >= 10

    li7700_preview = by_id["dryad_flooded_larch_flux_05_2023_preview"]
    assert li7700_preview["md5"] == "2DBC5482C9E647589CC64159B2CAAA6D"
    assert li7700_preview["row_count"] == 36
    assert li7700_preview["missing_columns"] == []
    assert li7700_preview["has_ch4_flux_fields"] is True
    assert li7700_preview["has_li7700_status_fields"] is True
    assert li7700_preview["ch4_non_missing_count"] >= 30


def test_public_official_raw_candidate_records_licor_sample_archive() -> None:
    summary = build_public_official_raw_fixture_summary()

    assert summary["artifact_type"] == "public_official_raw_fixture_candidate_summary_v1"
    assert summary["status"] == "pass"
    assert summary["dataset_id"] == "licor_eddypro_sample_datasets_box_2618767615"
    assert summary["candidate_count"] == 1
    assert summary["valid_candidate_count"] == 1
    assert summary["fixture_count"] == 0
    assert summary["can_be_downloaded"] is True
    assert summary["can_be_promoted_to_official_raw_bundle"] is False
    assert summary["original_files"][0]["download_method"] == "box_shared_folder_zip"
    assert summary["original_files"][0]["expected_size_bytes"] == 88589595

    candidate = summary["candidate_bundles"][0]
    assert candidate["candidate_id"] == "licor_eddypro_sample_data_zip"
    assert candidate["status"] == "pass"
    assert candidate["can_be_downloaded"] is True
    assert "high_frequency_raw_input" in " ".join(candidate["promotion_blockers"])
    assert isinstance(candidate["local_file_exists"], bool)


def test_public_raw_binary_search_summary_records_tob1_slt_binary_leads_without_claiming_fixture() -> None:
    summary = build_public_raw_search_summary()

    assert summary["artifact_type"] == "public_raw_binary_tob1_slt_search_summary_v1"
    assert summary["status"] == "pass"
    assert summary["lead_count"] >= 4
    assert summary["valid_lead_count"] == summary["lead_count"]
    assert summary["raw_data_candidate_count"] == 0
    assert summary["raw_to_final_candidate_count"] == 0
    assert summary["fixture_count"] == 0
    assert summary["can_support_raw_fixture_acquisition"] is False
    assert summary["can_support_full_raw_to_final_eddypro_claim"] is False
    assert summary["search_status"]["status"] == "no_public_registerable_tob1_slt_bundle_found"
    assert summary["source_derived_fallback"]["fixture_id"] == "eddypro_source_tob1_seconds_001"
    assert summary["source_derived_fallback"]["status"] == "registered_raw_to_final_pass"
    assert summary["raw_format_counts"]["tob1"] >= 3
    assert summary["raw_format_counts"]["slt"] >= 2
    assert summary["raw_format_counts"]["binary"] >= 3
    assert summary["candidate_status_counts"]["documentation_only"] == summary["lead_count"]
    assert any("not a downloadable raw-data fixture" in blocker for blocker in summary["promotion_blockers"])

    by_id = {lead["lead_id"]: lead for lead in summary["leads"]}
    assert by_id["campbellsci_loggernet_tob1_format_doc"]["raw_formats"] == ["tob1"]
    assert by_id["campbellsci_loggernet_tob1_format_doc"]["can_support_raw_fixture_acquisition"] is False
    assert by_id["licor_eddypro_raw_format_doc"]["status"] == "pass"
    assert "tob1" in by_id["doe_wfip2_eddypro_manual"]["raw_formats"]


def _write_nested_public_official_raw_archive(path: Path) -> None:
    nested_buffer = BytesIO()
    with zipfile.ZipFile(nested_buffer, "w", zipfile.ZIP_DEFLATED) as nested:
        nested.writestr("EddyPro sample data/ghg_sample_data_2021/2021-08-21T000000_AIU-0737.ghg", "ghg payload")
        nested.writestr("EddyPro sample data/ghg_sample_data_2021/2021-08-21T003000_AIU-0737.ghg", "ghg payload")
        nested.writestr("__MACOSX/EddyPro sample data/ghg_sample_data_2021/._2021-08-21T003000_AIU-0737.ghg", "mac")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as outer:
        outer.writestr("EddyPro Sample Datasets/EddyPro sample data.zip", nested_buffer.getvalue())


def _write_nested_public_official_raw_archive_with_embedded_eddypro(path: Path) -> None:
    ghg_buffer = BytesIO()
    with zipfile.ZipFile(ghg_buffer, "w", zipfile.ZIP_DEFLATED) as ghg:
        ghg.writestr("2021-08-21T000000_AIU-0737.data", "DATAH\tDate\tTime\tCO2 (umol/mol)\tH2O (mmol/mol)\tU (m/s)\tV (m/s)\tW (m/s)\tT (C)\nDATA\t2021-08-21\t00:00:00:000\t401.2\t14.0\t1.0\t0.1\t0.2\t20.1\n")
        ghg.writestr("2021-08-21T000000_AIU-0737.metadata", "acquisition_frequency=10.0\nfile_duration=30\nsite_name=LERS\n")
        ghg.writestr("eddypro/processing_2021-08-21T003117_exp.eddypro", "[Project]\nsw_version=6.0.0\nproject_id=exp\n")
        ghg.writestr(
            "eddypro/eddypro_exp_full_output_2021-08-21T003117_exp.csv",
            "\n".join(
                [
                    "file_info,,,corrected_fluxes_and_quality_flags,,",
                    "filename,date,time,co2_flux,qc_co2_flux,H,LE",
                    ",[yyyy-mm-dd],[HH:MM],[umol+1s-1m-2],[#],[W+1m-2],[W+1m-2]",
                    "2021-08-21T000000_AIU-0737.ghg,2021-08-21,00:30,2.18141,2,-19.8228,-14.2844",
                ]
            )
            + "\n",
        )
        ghg.writestr("eddypro/eddypro.log", "EddyPro embedded processing log\nCompleted\n")
    nested_buffer = BytesIO()
    with zipfile.ZipFile(nested_buffer, "w", zipfile.ZIP_DEFLATED) as nested:
        nested.writestr("EddyPro sample data/ghg_sample_data_2021/2021-08-21T000000_AIU-0737.ghg", ghg_buffer.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as outer:
        outer.writestr("EddyPro Sample Datasets/EddyPro sample data.zip", nested_buffer.getvalue())


def test_public_official_raw_archive_inspection_finds_raw_candidate_without_claiming_parity(tmp_path: Path) -> None:
    archive = tmp_path / "EddyPro Sample Datasets.zip"
    _write_nested_public_official_raw_archive(archive)

    inspection = inspect_public_official_raw_archive(archive, workspace_root=tmp_path)

    assert inspection["artifact_type"] == "public_official_raw_archive_inspection_v1"
    assert inspection["status"] == "pass"
    assert inspection["nested_archive_count"] == 1
    assert inspection["raw_file_count"] == 2
    assert inspection["raw_format_counts"] == {"ghg": 2}
    assert inspection["candidate_bundle_count"] == 1
    assert inspection["candidate_bundles"][0]["status"] == "raw_only_candidate"
    assert inspection["candidate_bundles"][0]["raw_file_count"] == 2
    assert "official_full_output" in inspection["candidate_bundles"][0]["missing_roles"]
    assert inspection["can_be_promoted_to_official_raw_bundle"] is False
    assert inspection["claim_boundary"]["can_support_raw_ingestion_fixture"] is True
    assert inspection["claim_boundary"]["can_support_full_raw_to_final_eddypro_claim"] is False


def test_headless_cli_inspects_public_official_raw_archive(tmp_path: Path) -> None:
    archive = tmp_path / "EddyPro Sample Datasets.zip"
    output = tmp_path / "public_official_raw_archive_inspection.json"
    _write_nested_public_official_raw_archive(archive)

    code = run_cli(
        [
            "--inspect-public-official-raw-archive",
            str(archive),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_official_raw_archive_inspection_v1"
    assert payload["raw_file_count"] == 2
    assert payload["candidate_bundle_count"] == 1


def test_materialize_public_official_raw_bundle_draft_extracts_raw_files(tmp_path: Path) -> None:
    archive = tmp_path / "EddyPro Sample Datasets.zip"
    output_root = tmp_path / "public_raw_bundle"
    _write_nested_public_official_raw_archive(archive)

    payload = materialize_public_official_raw_bundle_draft(
        archive,
        workspace_root=tmp_path,
        output_root=output_root,
    )

    manifest = json.loads((output_root / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "public_official_raw_bundle_draft_v1"
    assert payload["status"] == "draft_ready"
    assert payload["raw_file_count"] == 2
    assert payload["bundle_inspection_status"] == "incomplete"
    assert "eddypro_project_or_settings_file" in payload["missing_required_groups"]
    assert "official_eddypro_full_output" in payload["missing_required_groups"]
    assert payload["can_run_official_raw_closure"] is False
    assert manifest["fixture_id"] == "ghg_sample_data_2021_licor_public_raw_candidate"
    assert manifest["files"]["raw_file"].startswith("raw/")
    assert manifest["raw_files"] == payload["raw_files"]
    assert manifest["import_plan"]["status"] == "raw_only_candidate"
    assert "not a raw-to-final parity claim" in " ".join(manifest["known_limitations"]).lower()
    assert all((output_root / item).exists() for item in payload["raw_files"])


def test_headless_cli_materializes_public_official_raw_bundle_draft(tmp_path: Path) -> None:
    archive = tmp_path / "EddyPro Sample Datasets.zip"
    output_root = tmp_path / "candidate_bundle"
    output = tmp_path / "public_official_raw_bundle_draft.json"
    _write_nested_public_official_raw_archive(archive)

    code = run_cli(
        [
            "--materialize-public-official-raw-bundle",
            str(archive),
            "--workspace-root",
            str(tmp_path),
            "--public-official-raw-output-root",
            str(output_root),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["status"] == "draft_ready"
    assert payload["raw_file_count"] == 2
    assert payload["bundle_inspection_status"] == "incomplete"
    assert (output_root / "official_raw_fixture_bundle.json").exists()


def test_materialize_public_official_raw_bundle_draft_extracts_embedded_eddypro_evidence(tmp_path: Path) -> None:
    archive = tmp_path / "EddyPro Sample Datasets.zip"
    output_root = tmp_path / "embedded_candidate_bundle"
    _write_nested_public_official_raw_archive_with_embedded_eddypro(archive)

    payload = materialize_public_official_raw_bundle_draft(
        archive,
        workspace_root=tmp_path,
        output_root=output_root,
    )

    manifest = json.loads((output_root / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    reference = json.loads((output_root / "normalized" / "reference.json").read_text(encoding="utf-8"))
    provenance = json.loads((output_root / "normalized" / "provenance.json").read_text(encoding="utf-8"))
    assert payload["status"] == "draft_ready"
    assert payload["bundle_inspection_status"] == "ready_for_registration"
    assert payload["missing_required_groups"] == []
    assert payload["official_eddypro_run_gate_status"] == "blocked"
    assert "exit_code=0" in payload["official_eddypro_run_missing_requirements"]
    assert payload["can_run_official_raw_closure"] is False
    assert payload["embedded_eddypro_evidence"]["status"] == "embedded_output_ready"
    assert manifest["files"]["eddypro_project_file"].endswith(".eddypro")
    assert manifest["files"]["official_full_output"].endswith(".csv")
    assert manifest["files"]["reference_json"] == "normalized/reference.json"
    assert reference["windows"][0]["primary_flux"] == 2.18141
    assert reference["windows"][0]["qc_grade"] == "C"
    assert reference["windows"][0]["start_time"] == "2021-08-21T00:00:00"
    assert reference["windows"][0]["end_time"] == "2021-08-21T00:30:00"
    assert provenance["window_count"] == 1


def test_public_eddypro_fixture_catalog_collects_acquisition_plan_and_claim_boundary() -> None:
    catalog = build_public_eddypro_fixture_catalog()

    assert catalog["artifact_type"] == "public_eddypro_fixture_catalog_v1"
    assert catalog["status"] == "pass"
    assert catalog["dataset_count"] == 4
    assert catalog["fixture_count"] == 6
    assert catalog["valid_fixture_count"] == 6
    assert catalog["spectral_status"] == "pass"
    assert catalog["full_output_status"] == "pass"
    assert catalog["official_raw_status"] == "pass"
    assert catalog["official_raw_candidate_count"] == 1
    assert catalog["raw_binary_search_status"] == "pass"
    assert catalog["raw_binary_search_lead_count"] >= 4
    assert catalog["raw_binary_search_raw_data_candidate_count"] == 0
    assert catalog["raw_binary_search_raw_format_counts"]["tob1"] >= 3
    assert catalog["claim_boundary"]["can_support_official_raw_bundle_acquisition"] is True
    assert catalog["claim_boundary"]["can_support_processed_output_schema_evidence"] is True
    assert catalog["claim_boundary"]["can_support_spectral_output_schema_evidence"] is True
    assert catalog["claim_boundary"]["can_support_full_raw_to_final_eddypro_claim"] is False
    assert any("curl.exe" in command for command in catalog["acquisition_plan"]["commands"])
    assert any("Invoke-WebRequest" in command for command in catalog["acquisition_plan"]["commands"])
    assert any("--include-public-remote-originals" in command for command in catalog["acquisition_plan"]["commands"])
    remote_sizes = {item["expected_size_bytes"] for item in catalog["remote_originals"]}
    assert 261076627 in remote_sizes
    assert 88589595 in remote_sizes
    assert 200704 in remote_sizes
    raw_search = next(item for item in catalog["datasets"] if item["kind"] == "raw_binary_search")
    assert raw_search["fixture_count"] == 0
    assert raw_search["raw_data_candidate_count"] == 0
    assert "binary" in raw_search["raw_format_counts"]
    assert catalog["raw_binary_search_summary"]["can_support_full_raw_to_final_eddypro_claim"] is False


def test_headless_cli_builds_public_eddypro_fixture_catalog(tmp_path: Path) -> None:
    output = tmp_path / "public_eddypro_fixture_catalog.json"

    code = run_cli(
        [
            "--build-public-eddypro-fixture-catalog",
            "--workspace-root",
            str(Path.cwd()),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_eddypro_fixture_catalog_v1"
    assert payload["status"] == "pass"
    assert payload["fixture_count"] == payload["valid_fixture_count"] == 6
    assert payload["official_raw_candidate_count"] == 1
    assert payload["raw_binary_search_lead_count"] >= 4
    assert payload["raw_binary_search_raw_data_candidate_count"] == 0


def test_public_eddypro_fixture_acquisition_skips_existing_and_validates_catalog() -> None:
    acquisition = acquire_public_eddypro_fixture_files(workspace_root=Path.cwd(), overwrite=False)

    assert acquisition["artifact_type"] == "public_eddypro_fixture_acquisition_run_v1"
    assert acquisition["status"] == "pass"
    assert acquisition["downloaded_count"] == 0
    assert acquisition["skipped_count"] == 6
    assert acquisition["failed_count"] == 0
    assert acquisition["catalog"]["status"] == "pass"
    assert acquisition["claim_boundary"]["can_support_full_raw_to_final_eddypro_claim"] is False
    assert all(item["action"] == "skipped_existing" for item in acquisition["items"])


def test_headless_cli_acquires_public_eddypro_fixtures_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "public_eddypro_fixture_acquisition.json"

    code = run_cli(
        [
            "--acquire-public-eddypro-fixtures",
            "--workspace-root",
            str(Path.cwd()),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_eddypro_fixture_acquisition_run_v1"
    assert payload["status"] == "pass"
    assert payload["downloaded_count"] == 0
    assert payload["skipped_count"] == 6
    assert payload["catalog"]["fixture_count"] == payload["catalog"]["valid_fixture_count"] == 6


def test_official_raw_fixture_manifest_keeps_synthetic_guardrails_separate() -> None:
    summary = build_fixture_pack_summary()
    manifest = build_official_raw_fixture_manifest(fixture_summary=summary)

    assert manifest["artifact_type"] == "official_raw_fixture_pack_manifest_v2"
    assert manifest["status"] == "needs_official_raw_fixtures"
    assert manifest["official_raw_to_final_ready_count"] == 1
    assert manifest["registered_raw_to_final_fixture_count"] == 4
    assert manifest["synthetic_guardrail_count"] == 3
    assert manifest["readiness_counts"]["source_derived_conformance"] == 1
    assert manifest["device_protocol_guardrail_count"] == 1
    assert manifest["missing_official_bundle_count"] >= 1
    assert "high_frequency_raw_input" in manifest["required_official_bundle_files"]
    assert manifest["official_bundle_schema"]["artifact_type"] == "official_raw_fixture_bundle_schema_v1"
    assert manifest["evidence_matrix"]["artifact_type"] == "official_raw_fixture_evidence_matrix_v1"
    assert manifest["evidence_matrix"]["row_count"] == len(manifest["assets"])
    assert manifest["evidence_matrix"]["raw_format_counts"]["csv"] >= 2
    assert manifest["public_spectral_status"] == "pass"
    assert manifest["public_spectral_fixture_count"] == 3
    assert manifest["public_full_output_status"] == "pass"
    assert manifest["public_full_output_fixture_count"] == 3
    assert manifest["public_eddypro_fixture_catalog_status"] == "pass"
    assert manifest["official_run_normalization_status_counts"]["normalized"] >= 1
    assert manifest["official_run_normalization_ready_count"] >= 1

    by_id = {asset["fixture_id"]: asset for asset in manifest["assets"]}
    raw_guardrail = by_id["synthetic_raw_csv_001"]
    assert raw_guardrail["readiness_level"] == "synthetic_guardrail"
    assert raw_guardrail["raw_to_final_status"] == "pass"
    assert raw_guardrail["has_raw_input"] is True
    assert raw_guardrail["has_normalized_reference"] is True
    assert raw_guardrail["normalization_status"] in {"present", "ready"}
    assert raw_guardrail["normalization"]["source_file"]
    assert raw_guardrail["parity_diagnostics"]["status"] == "ok"
    assert raw_guardrail["parity_top_failed_fields"] == []
    assert "official_eddypro_executable_output" in raw_guardrail["missing_for_official_claim"]
    li7700_guardrail = by_id["synthetic_li7700_trace_gas_001"]
    assert li7700_guardrail["trace_gas_parity_status"] == "pass"
    assert li7700_guardrail["trace_gas_coefficient_profile_id"] == "synthetic_li7700_profile"
    source_tob1 = by_id["eddypro_source_tob1_seconds_001"]
    assert source_tob1["readiness_level"] == "source_derived_conformance"
    assert source_tob1["evidence_role"] == "source_derived_raw_import_conformance"
    assert source_tob1["raw_to_final_status"] == "pass"
    assert source_tob1["missing_for_official_claim"] == [
        "eddypro_project_or_settings_file",
        "official_eddypro_full_output",
    ]
    public_ghg = by_id["ghg_sample_data_2021_licor_public_raw_candidate"]
    assert public_ghg["official_eddypro_run"]["gate_status"] == "pass"
    assert public_ghg["official_run_normalization_status"] == "normalized"
    assert public_ghg["official_run_normalization"]["reference_json"].endswith("official_eddypro_run_reference.json")
    assert public_ghg["official_run_normalization"]["provenance_json"].endswith("official_eddypro_run_provenance.json")
    assert public_ghg["official_run_normalization"]["required_fields_present"] is True
    assert public_ghg["official_run_normalization"]["qc_mapping_strategy"] == "EddyPro 0/1/2 -> gas_ec_studio A/B/C"
    matrix_by_id = {row["fixture_id"]: row for row in manifest["evidence_matrix"]["rows"]}
    assert matrix_by_id["synthetic_li7700_trace_gas_001"]["trace_gas_parity_status"] == "pass"
    assert matrix_by_id["synthetic_raw_csv_001"]["normalization_status"] in {"present", "ready"}
    assert matrix_by_id["synthetic_raw_csv_001"]["qc_mapping_strategy"]
    assert matrix_by_id["eddypro_source_tob1_seconds_001"]["readiness_level"] == "source_derived_conformance"
    assert matrix_by_id["eddypro_source_tob1_seconds_001"]["raw_format"] == "tob1"
    assert matrix_by_id["ghg_sample_data_2021_licor_public_raw_candidate"]["official_run_normalization_status"] == "normalized"
    assert matrix_by_id["ghg_sample_data_2021_licor_public_raw_candidate"]["official_run_normalization_required_fields_present"] is True
    detail = build_official_raw_fixture_detail(
        fixture_id="ghg_sample_data_2021_licor_public_raw_candidate",
        fixture_summary=summary,
        fixture_manifest=manifest,
    )
    assert detail["official_run_normalization_status"] == "normalized"
    assert detail["official_run_normalization"]["normalization_time"]
    assert "normalization_status_counts" in manifest["evidence_matrix"]
    assert manifest["evidence_matrix"]["official_run_normalization_status_counts"]["normalized"] >= 1
    assert manifest["official_source_inventory"]["inventory_id"] == "eddypro_official_source_inventory_v1"


def test_fixture_pack_summary_uses_explicit_workspace_root_from_other_cwd(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path.cwd()
    monkeypatch.chdir(tmp_path)

    summary = build_fixture_pack_summary(workspace_root=repo_root)

    assert summary["status"] == "pass"
    assert summary["fixture_pack_id"] == "eddypro_real_fixture_pack_v1"
    assert summary["real_reference_window_count"] == 11


def test_fixture_pack_summary_falls_back_when_workspace_root_is_runtime_dir(tmp_path: Path) -> None:
    summary = build_fixture_pack_summary(workspace_root=tmp_path)

    assert summary["status"] == "pass"
    assert summary["protocol_validation_row_count"] == 2


def test_fixture_pack_asset_validation_fails_on_wrong_expected_hash(tmp_path: Path) -> None:
    source = tmp_path / "fixture.json"
    source.write_text(json.dumps({"reference_id": "bad", "windows": []}), encoding="utf-8")
    asset = {
        "fixture_id": "bad_fixture",
        "tier": "synthetic_regression_reference",
        "reference_json": str(source),
        "expected_sha256": {"reference_json": "0" * 64},
    }

    result = validate_fixture_asset(asset, workspace_root=Path.cwd())

    assert result["status"] == "fail"
    assert any("sha256 mismatch" in error for error in result["errors"])


def test_headless_manifest_includes_fixture_pack_summary() -> None:
    rows = [
        NormalizedHFFrame(
            timestamp=datetime(2026, 5, 25, 8, 0, 0),
            device_uid="dev",
            device_id="001",
            mode=1,
            frame_quality=FrameQuality.FULL,
            co2_ppm=410.0,
            h2o_mmol=12.0,
            pressure_kpa=101.3,
        )
    ]
    metadata = MetadataBundle()
    rp_result = RPRunResult(run_id="rp", created_at=datetime(2026, 5, 25, 8, 0, 0), data_source="test", time_range="", windows=[], summary={}, artifacts={})
    spectral_result = SpectralRunResult(run_id="sp", created_at=datetime(2026, 5, 25, 8, 0, 0), data_source="test", time_range="", qc_only=False, windows=[], summary={}, artifacts={})

    manifest = build_batch_manifest(
        batch_id="fixture-test",
        metadata_bundle=metadata,
        config={},
        rows=rows,
        rp_result=rp_result,
        spectral_result=spectral_result,
    )

    assert manifest["fixture_pack_summary"]["status"] == "pass"
    assert manifest["fixture_pack_summary"]["real_reference_window_count"] == 11
    assert manifest["fixture_pack_summary"]["raw_to_final_pass_count"] == 4
    assert manifest["fixture_pack_summary"]["public_spectral_status"] == "pass"
    assert manifest["fixture_pack_summary"]["public_full_output_status"] == "pass"
    assert manifest["fixture_pack_summary"]["public_eddypro_fixture_catalog_status"] == "pass"
    assert manifest["official_raw_fixture_manifest"]["status"] == "needs_official_raw_fixtures"
    assert manifest["official_raw_fixture_manifest"]["registered_raw_to_final_fixture_count"] == 4
    assert manifest["official_raw_fixture_manifest"]["public_spectral_status"] == "pass"
    assert manifest["official_raw_fixture_manifest"]["public_full_output_status"] == "pass"
    assert manifest["official_raw_fixture_manifest"]["public_eddypro_fixture_catalog_status"] == "pass"
    assert manifest["public_eddypro_fixture_catalog"]["status"] == "pass"
    assert manifest["eddypro_source_inventory"]["inventory_id"] == "eddypro_official_source_inventory_v1"


def test_fixture_pack_summary_exposes_manifest_ready_counts() -> None:
    summary = build_fixture_pack_summary()

    assert summary["status"] == "pass"
    assert summary["protocol_validation_row_count"] == 2
    assert summary["raw_to_final_fixture_count"] == 4
    assert summary["raw_to_final_pass_count"] == 4
    assert summary["public_spectral_fixture_count"] == 3
    assert summary["public_full_output_fixture_count"] == 3
    assert summary["public_eddypro_fixture_catalog_status"] == "pass"
    assert summary["official_source_inventory"]["feature_count"] >= 10
