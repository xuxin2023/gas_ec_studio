from __future__ import annotations

import json
from pathlib import Path


def test_public_ec_data_discovery_tracks_new_candidates_without_claiming_full_parity() -> None:
    payload = json.loads(
        Path("references/eddypro/public_raw_search/ec_public_data_sources.json").read_text(encoding="utf-8")
    )

    assert payload["artifact_type"] == "public_ec_data_source_discovery_v1"
    assert payload["overall_status"] == "new_real_data_candidates_found_but_not_registered_as_eddypro_parity_fixtures"
    assert payload["local_registration_status"]["official_licor_sample_bundle"] == "registered_and_accepted"
    assert payload["local_registration_status"]["neon_dp4_candidate"] == "api_and_download_url_head_verified_not_registered"
    assert payload["local_registration_status"]["icos_raw_ascii_candidate"] == "landing_page_verified_license_flow_not_programmatically_registered"
    assert "does not change the full EddyPro parity claim gate" in payload["truthfulness_boundary"]

    sources = {item["source_id"]: item for item in payload["sources"]}
    neon = sources["neon_dp4_00200_001_harv_2023_07"]
    assert neon["access_status"] == "api_metadata_and_download_url_head_verified"
    assert neon["account_or_registration"] == "not_required_for_metadata_or_public_google_storage_url"
    assert neon["candidate_files"][0]["name"].endswith(".h5")
    assert neon["candidate_files"][0]["head_status"] == 200
    assert neon["candidate_files"][0]["head_content_length"] == 156344090
    assert neon["registration_outcome"] == "not_registered"

    icos = sources["icos_raw_ascii_ch_dav_candidate"]
    assert icos["access_status"] == "landing_page_verified_license_acceptance_required"
    assert icos["registration_outcome"] == "not_programmatically_registered"

    licor = sources["licor_eddypro_sample_data_2021"]
    assert licor["registration_outcome"] == "registered_and_accepted"
    assert licor["parity_value"] == "official_public_raw_anchor"


def test_public_ec_data_discovery_doc_points_to_machine_readable_ledger() -> None:
    text = Path("docs/benchmark/public_ec_data_discovery.md").read_text(encoding="utf-8")

    assert "references/eddypro/public_raw_search/ec_public_data_sources.json" in text
    assert "NEON DP4.00200.001" in text
    assert "ICOS Raw ASCII" in text
    assert "Until then, the project may claim source-derived functional parity only" in text
