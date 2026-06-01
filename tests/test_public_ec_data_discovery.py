from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path

from core.comparison import public_ec_data_discovery
from core.comparison.public_ec_data_discovery import (
    build_public_ec_acquisition_closure,
    build_public_ec_acquisition_runbook,
    build_public_ec_data_discovery_probe,
    build_public_raw_importer_smoke_plan,
    build_public_raw_sample_importer_smoke,
    build_public_raw_sample_rp_smoke,
)
from core.headless_batch_runner import run_cli


def test_public_ec_data_discovery_tracks_new_candidates_without_claiming_full_parity() -> None:
    payload = json.loads(
        Path("references/eddypro/public_raw_search/ec_public_data_sources.json").read_text(encoding="utf-8")
    )

    assert payload["artifact_type"] == "public_ec_data_source_discovery_v1"
    assert payload["overall_status"] == "new_real_data_candidates_found_but_not_registered_as_eddypro_parity_fixtures"
    assert payload["local_registration_status"]["official_licor_sample_bundle"] == "registered_and_accepted"
    assert payload["local_registration_status"]["neon_dp4_candidate"] == "api_and_download_url_head_verified_not_registered"
    assert payload["local_registration_status"]["crocus_uic_high_frequency_candidate"] == "landing_page_verified_real_raw_not_eddypro_pair"
    assert payload["local_registration_status"]["bas_arctic_cruise_high_frequency_candidate"] == "landing_page_verified_large_raw_not_eddypro_pair"
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

    crocus = sources["crocus_uic_high_frequency_2023"]
    assert crocus["registration_evidence"]["raw_input"] is True
    assert crocus["registration_evidence"]["official_eddypro_full_output"] is False
    assert crocus["registration_outcome"] == "not_registered"

    bas = sources["bas_arctic_cruise_raw_2021"]
    assert bas["registration_evidence"]["raw_input"] is True
    assert bas["registration_evidence"]["eddypro_project_or_settings"] is False

    licor = sources["licor_eddypro_sample_data_2021"]
    assert licor["registration_outcome"] == "registered_and_accepted"
    assert licor["parity_value"] == "official_public_raw_anchor"


def test_public_ec_data_discovery_doc_points_to_machine_readable_ledger() -> None:
    text = Path("docs/benchmark/public_ec_data_discovery.md").read_text(encoding="utf-8")

    assert "references/eddypro/public_raw_search/ec_public_data_sources.json" in text
    assert "NEON DP4.00200.001" in text
    assert "CROCUS" in text
    assert "BAS Arctic cruise" in text
    assert "ICOS Raw ASCII" in text
    assert "Until then, the project may claim source-derived functional parity only" in text


def test_public_ec_data_discovery_probe_can_run_without_network(tmp_path: Path) -> None:
    output = tmp_path / "public_ec_probe.json"

    code = run_cli(
        [
            "--build-public-ec-data-discovery",
            "--workspace-root",
            str(Path.cwd()),
            "--skip-public-ec-network",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_ec_data_discovery_probe_v1"
    assert payload["run_network"] is False
    assert payload["summary"]["can_change_full_parity_gate"] is False
    assert any(item["source_id"] == "neon_dp4_00200_001_harv_2023_07" for item in payload["sources"])
    assert all(item["status"] == "skipped_network" for item in payload["sources"])


def test_public_ec_data_discovery_probe_verifies_neon_and_writes_byte_sample(monkeypatch, tmp_path: Path) -> None:
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_id": "test_public_ec_sources",
                "sources": [
                    {
                        "source_id": "neon_test",
                        "provider": "NEON",
                        "source_url": "https://data.neonscience.org/data-products/DP4.00200.001",
                        "api_query_url": "https://example.test/neon-api",
                        "access_status": "api_metadata_verified",
                        "registration_outcome": "not_registered",
                        "parity_value": "real_ec_hdf5_candidate_not_eddypro_output",
                    },
                    {
                        "source_id": "icos_test",
                        "provider": "ICOS Carbon Portal",
                        "source_url": "https://example.test/icos-object",
                        "licence_url": "https://example.test/icos-licence",
                        "registration_outcome": "not_programmatically_registered",
                        "parity_value": "real_raw_ascii_candidate_not_registered",
                    },
                    {
                        "source_id": "crocus_test",
                        "provider": "DOE OSTI / CROCUS",
                        "source_url": "https://example.test/crocus",
                        "landing_probe_keywords": ["CROCUS", "10 Hz", "raw"],
                        "registration_outcome": "not_registered",
                        "parity_value": "real_high_frequency_raw_candidate_not_eddypro_output",
                        "registration_evidence": {
                            "raw_input": True,
                            "eddypro_project_or_settings": False,
                            "official_eddypro_full_output": False,
                            "normalized_reference": False,
                            "normalization_provenance": False,
                            "acceptance_evidence": False,
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(public_ec_data_discovery, "urlopen", _fake_public_ec_urlopen)

    payload = build_public_ec_data_discovery_probe(
        manifest_path=manifest,
        workspace_root=tmp_path,
        sample_output_root=tmp_path / "samples",
        sample_bytes=8,
        timeout_s=1.0,
        run_network=True,
    )

    sources = {item["source_id"]: item for item in payload["sources"]}
    neon = sources["neon_test"]
    assert payload["status"] == "ok"
    assert neon["status"] == "candidate_verified"
    assert neon["download_url_status"] == "verified"
    assert neon["candidate_files"][0]["name"] == "NEON.TEST.DP4.00200.001.nsae.2023-07.basic.h5"
    assert neon["candidate_files"][0]["head"]["status_code"] == 200
    assert neon["candidate_files"][0]["byte_sample"]["size_bytes"] == 8
    assert neon["candidate_files"][0]["byte_sample"]["sha256"] == hashlib.sha256(b"HDF5TEST").hexdigest().upper()
    assert Path(neon["candidate_files"][0]["byte_sample"]["path"]).read_bytes() == b"HDF5TEST"
    assert sources["icos_test"]["status"] == "licence_flow_verified"
    assert sources["icos_test"]["licence_acceptance_required"] is True
    assert sources["crocus_test"]["status"] == "landing_verified"
    assert sources["crocus_test"]["landing_keyword_hits"] == ["CROCUS", "10 Hz", "raw"]
    assert sources["crocus_test"]["registration_readiness"]["has_raw_input"] is True
    assert sources["crocus_test"]["registration_readiness"]["status"] == "blocked_missing_registration_evidence"
    assert "official_eddypro_full_output" in sources["crocus_test"]["registration_readiness"]["missing_requirements"]
    assert payload["summary"]["raw_without_eddypro_pair_count"] == 2
    assert payload["summary"]["ready_to_register_candidate_count"] == 0
    assert payload["summary"]["can_change_full_parity_gate"] is False

    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plan = build_public_raw_importer_smoke_plan(
        discovery_probe_path=probe_path,
        workspace_root=tmp_path,
        max_sample_bytes=2048,
    )
    plans = {item["source_id"]: item for item in plan["candidate_plans"]}
    assert plan["artifact_type"] == "public_raw_importer_smoke_plan_v1"
    assert plan["status"] == "ready_for_importer_smoke"
    assert plan["can_change_full_parity_gate"] is False
    assert plan["real_raw_candidate_count"] == 3
    assert plan["direct_byte_sample_candidate_count"] == 1
    assert plan["operator_subset_required_count"] == 2
    assert plans["neon_test"]["sample_mode"] == "byte_range"
    assert plans["neon_test"]["sample_byte_budget"] == 2048
    assert plans["crocus_test"]["sample_mode"] == "operator_subset"
    assert plans["crocus_test"]["recommended_smoke"]["smoke_type"] == "generic_high_frequency_raw_sample"
    assert plans["icos_test"]["missing_for_eddypro_parity"]


def test_public_raw_importer_smoke_plan_cli_can_use_probe(tmp_path: Path) -> None:
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(
        json.dumps(
            {
                "artifact_type": "public_ec_data_discovery_probe_v1",
                "sources": [
                    {
                        "source_id": "bas_test",
                        "provider": "British Antarctic Survey",
                        "source_url": "https://example.test/bas",
                        "status": "landing_verified",
                        "parity_value": "real_large_high_frequency_raw_candidate_not_eddypro_pair",
                        "registration_readiness": {
                            "status": "blocked_missing_registration_evidence",
                            "has_raw_input": True,
                            "missing_requirements": ["official_eddypro_full_output"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "smoke_plan.json"

    code = run_cli(
        [
            "--build-public-raw-importer-smoke-plan",
            "--workspace-root",
            str(tmp_path),
            "--public-ec-discovery-probe",
            str(probe_path),
            "--public-raw-smoke-max-sample-bytes",
            "1024",
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["real_raw_candidate_count"] == 1
    assert payload["candidate_plans"][0]["source_id"] == "bas_test"
    assert payload["candidate_plans"][0]["sample_mode"] == "operator_subset"
    assert payload["candidate_plans"][0]["recommended_smoke"]["smoke_type"] == "large_raw_subset_stress_sample"


def test_public_raw_sample_importer_smoke_loads_operator_subset(tmp_path: Path) -> None:
    sample = tmp_path / "operator_public_subset.csv"
    sample_text = "\n".join(
        [
            "timestamp,u,v,w,co2,h2o,pressure,temperature,ch4",
            "2023-07-01T00:00:00,2.1,0.1,0.05,410.1,12.2,101.2,22.1,1900",
            "2023-07-01T00:00:00.1,2.2,0.0,0.06,410.4,12.1,101.2,22.1,1901",
            "2023-07-01T00:00:00.2,2.0,-0.1,0.04,409.9,12.3,101.1,22.2,1899",
            "2023-07-01T00:00:00.3,2.3,0.2,0.07,410.7,12.0,101.3,22.2,1902",
        ]
    )
    sample.write_text(sample_text, encoding="utf-8-sig")

    payload = build_public_raw_sample_importer_smoke(
        sample_path=sample,
        source_id="crocus_operator_subset",
        workspace_root=tmp_path,
        max_rows=3,
    )

    assert payload["artifact_type"] == "public_raw_sample_importer_smoke_v1"
    assert payload["status"] == "pass"
    assert payload["import_status"] == "loaded"
    assert payload["raw_format"] == "text"
    assert payload["row_count"] == 3
    assert payload["loaded_row_count"] == 4
    assert payload["sample_hash"] == hashlib.sha256(sample.read_bytes()).hexdigest().upper()
    assert payload["field_coverage"]["complete_for_rp_smoke"] is True
    assert payload["field_coverage"]["missing_required_fields"] == []
    assert payload["field_coverage"]["field_counts"]["w"] == 3
    assert payload["time_range"]["start"] == "2023-07-01T00:00:00"
    assert payload["time_range"]["end"] == "2023-07-01T00:00:00.200000"
    assert payload["ready_for_raw_to_final_registration"] is False
    assert payload["can_change_full_parity_gate"] is False
    assert "settings" in payload["claim_boundary"]


def test_public_raw_sample_importer_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    sample = tmp_path / "public_subset.csv"
    sample.write_text(
        "\n".join(
            [
                "timestamp,u,v,w,co2_ppm,h2o_mmol,pressure_kpa",
                "2023-07-01T00:00:00,2.1,0.1,0.05,410.1,12.2,101.2",
                "2023-07-01T00:00:00.1,2.2,0.0,0.06,410.4,12.1,101.2",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "public_raw_sample_smoke.json"

    code = run_cli(
        [
            "--build-public-raw-sample-importer-smoke",
            str(sample),
            "--workspace-root",
            str(tmp_path),
            "--public-raw-source-id",
            "operator_subset_cli",
            "--public-raw-smoke-max-rows",
            "10",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["status"] == "pass"
    assert payload["source_id"] == "operator_subset_cli"
    assert payload["row_count"] == 2
    assert payload["field_coverage"]["complete_for_rp_smoke"] is True
    assert payload["provenance"]["loader"] == "core.storage.raw_importer"
    assert payload["can_change_full_parity_gate"] is False


def test_public_raw_sample_rp_smoke_runs_pipeline_without_parity_claim(tmp_path: Path) -> None:
    sample = _write_public_raw_rp_sample(tmp_path / "operator_rp_subset.csv", rows=130)

    payload = build_public_raw_sample_rp_smoke(
        sample_path=sample,
        workspace_root=tmp_path,
        source_id="operator_subset_rp",
        max_rows=120,
        min_rows=64,
        block_minutes=0.1,
    )

    assert payload["artifact_type"] == "public_raw_sample_rp_smoke_v1"
    assert payload["status"] == "pass"
    assert payload["importer_smoke"]["status"] == "pass"
    assert payload["row_count"] == 120
    assert payload["window_count"] >= 1
    assert payload["rp_summary"]["sample_rate_hz"] > 0.0
    assert payload["field_coverage"]["complete_for_rp_smoke"] is True
    assert payload["can_change_full_parity_gate"] is False
    assert payload["ready_for_raw_to_final_registration"] is False


def test_public_raw_sample_validation_package_cli_closes_importer_and_rp_smoke(tmp_path: Path) -> None:
    sample = _write_public_raw_rp_sample(tmp_path / "operator_package_subset.csv", rows=130)
    output = tmp_path / "public_raw_validation_package.json"

    code = run_cli(
        [
            "--build-public-raw-sample-validation-package",
            str(sample),
            "--workspace-root",
            str(tmp_path),
            "--public-raw-source-id",
            "operator_subset_package",
            "--public-raw-smoke-max-rows",
            "120",
            "--public-raw-rp-min-rows",
            "64",
            "--public-raw-rp-block-minutes",
            "0.1",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_raw_sample_validation_package_v1"
    assert payload["status"] == "pass"
    assert payload["importer_status"] == "pass"
    assert payload["rp_status"] == "pass"
    assert payload["rp_window_count"] >= 1
    assert payload["claim_boundary"]["can_claim_public_raw_engineering_validation"] is True
    assert payload["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["claim_boundary"]["can_release_full_eddypro_parity"] is False
    assert payload["ready_for_raw_to_final_registration"] is False


def test_public_ec_acquisition_closure_summarizes_downloaded_and_blocked_sources(tmp_path: Path) -> None:
    inputs = _write_acquisition_closure_inputs(tmp_path)

    payload = build_public_ec_acquisition_closure(
        discovery_probe_path=inputs["probe"],
        smoke_plan_path=inputs["plan"],
        neon_download_path=inputs["neon_download"],
        neon_validation_package_path=inputs["neon_validation"],
        public_raw_sample_validation_package_path=inputs["public_raw_validation"],
        workspace_root=tmp_path,
    )

    sources = {item["source_id"]: item for item in payload["sources"]}
    assert payload["artifact_type"] == "public_ec_acquisition_closure_v1"
    assert payload["status"] == "engineering_validation_closed_full_parity_blocked"
    assert payload["summary"]["source_count"] == 4
    assert payload["summary"]["candidate_count"] == 3
    assert payload["summary"]["downloaded_candidate_count"] == 1
    assert payload["summary"]["engineering_validation_pass_count"] == 2
    assert payload["summary"]["ready_to_register_candidate_count"] == 0
    assert payload["summary"]["status_counts"]["public_download_engineering_validated"] == 1
    assert payload["summary"]["status_counts"]["blocked_operator_subset_required"] == 1
    assert payload["summary"]["status_counts"]["blocked_license_or_operator_subset_required"] == 1
    assert payload["neon_download_summary"]["status"] == "pass"
    assert payload["neon_validation_summary"]["status"] == "pass"
    assert payload["public_raw_sample_validation_summary"]["status"] == "pass"
    assert sources["neon_test"]["acquisition_status"] == "public_download_engineering_validated"
    assert sources["crocus_test"]["acquisition_status"] == "blocked_operator_subset_required"
    assert sources["icos_test"]["acquisition_status"] == "blocked_license_or_operator_subset_required"
    assert sources["licor_anchor"]["acquisition_status"] == "registered_anchor"
    assert payload["claim_boundary"]["can_claim_public_raw_engineering_validation"] is True
    assert payload["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["claim_boundary"]["can_release_full_eddypro_parity"] is False
    assert any("official Full_Output" in blocker for blocker in payload["blockers"])


def test_public_ec_acquisition_closure_cli_writes_non_blocking_artifact(tmp_path: Path) -> None:
    inputs = _write_acquisition_closure_inputs(tmp_path)
    output = tmp_path / "public_ec_acquisition_closure.json"

    code = run_cli(
        [
            "--build-public-ec-acquisition-closure",
            "--workspace-root",
            str(tmp_path),
            "--public-ec-discovery-probe",
            str(inputs["probe"]),
            "--public-raw-importer-smoke-plan",
            str(inputs["plan"]),
            "--neon-hdf5-download",
            str(inputs["neon_download"]),
            "--neon-hdf5-validation-package",
            str(inputs["neon_validation"]),
            "--public-raw-sample-validation-package",
            str(inputs["public_raw_validation"]),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_ec_acquisition_closure_v1"
    assert payload["summary"]["can_change_full_parity_gate"] is False
    assert payload["truthfulness_boundary"].startswith("This artifact closes the acquisition/engineering round only.")


def test_public_ec_acquisition_runbook_records_safe_and_external_actions(tmp_path: Path) -> None:
    inputs = _write_acquisition_closure_inputs(tmp_path)
    closure = build_public_ec_acquisition_closure(
        discovery_probe_path=inputs["probe"],
        smoke_plan_path=inputs["plan"],
        neon_download_path=inputs["neon_download"],
        neon_validation_package_path=inputs["neon_validation"],
        public_raw_sample_validation_package_path=inputs["public_raw_validation"],
        workspace_root=tmp_path,
    )

    payload = build_public_ec_acquisition_runbook(
        acquisition_closure=closure,
        discovery_probe_path=inputs["probe"],
        workspace_root=tmp_path,
        max_sample_bytes=2048,
    )

    actions = {item["source_id"]: item for item in payload["actions"]}
    assert payload["artifact_type"] == "public_ec_acquisition_runbook_v1"
    assert payload["status"] == "engineering_validated_registration_pending"
    assert payload["summary"]["engineering_validated_registration_pending_count"] == 1
    assert payload["summary"]["external_evidence_required_count"] == 2
    assert actions["neon_test"]["automation_state"] == "engineering_validated_registration_pending"
    assert actions["crocus_test"]["automation_state"] == "operator_subset_required"
    assert actions["icos_test"]["automation_state"] == "license_or_auth_required"
    assert actions["licor_anchor"]["automation_state"] == "accepted_anchor"
    assert actions["icos_test"]["requires_external_action"] is True
    assert any(command["step"] == "validate_operator_supplied_subset" for command in actions["icos_test"]["commands"])
    assert payload["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["automation_policy"]["may_auto_accept_licence_or_create_accounts"] is False


def test_public_ec_acquisition_runbook_cli_writes_action_artifact(tmp_path: Path) -> None:
    inputs = _write_acquisition_closure_inputs(tmp_path)
    closure_path = tmp_path / "closure.json"
    closure = build_public_ec_acquisition_closure(
        discovery_probe_path=inputs["probe"],
        smoke_plan_path=inputs["plan"],
        neon_download_path=inputs["neon_download"],
        neon_validation_package_path=inputs["neon_validation"],
        public_raw_sample_validation_package_path=inputs["public_raw_validation"],
        workspace_root=tmp_path,
    )
    closure_path.write_text(json.dumps(closure, ensure_ascii=False, indent=2), encoding="utf-8")
    output = tmp_path / "runbook.json"

    code = run_cli(
        [
            "--build-public-ec-acquisition-runbook",
            "--workspace-root",
            str(tmp_path),
            "--public-ec-acquisition-closure",
            str(closure_path),
            "--public-ec-discovery-probe",
            str(inputs["probe"]),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "public_ec_acquisition_runbook_v1"
    assert payload["summary"]["source_count"] == 4
    assert payload["truthfulness_boundary"].startswith("This runbook makes acquisition actions explicit")


def _write_public_raw_rp_sample(path: Path, *, rows: int) -> Path:
    start = datetime(2023, 7, 1, 0, 0, 0)
    lines = ["timestamp,u,v,w,co2_ppm,h2o_mmol,pressure_kpa,ch4_ppb"]
    for index in range(rows):
        t = index / 10.0
        vertical = math.sin(2.0 * math.pi * 0.18 * t) + 0.35 * math.sin(2.0 * math.pi * 0.72 * t)
        co2 = 410.0 + 5.0 * vertical + 0.15 * math.cos(2.0 * math.pi * 0.4 * t)
        h2o = 12.0 + 0.8 * vertical + 0.05 * math.sin(2.0 * math.pi * 0.5 * t)
        timestamp = start + timedelta(seconds=t)
        lines.append(
            ",".join(
                [
                    timestamp.isoformat(),
                    f"{2.2 + 0.1 * math.sin(0.2 * t):.6f}",
                    f"{0.1 * math.cos(0.3 * t):.6f}",
                    f"{vertical:.6f}",
                    f"{co2:.6f}",
                    f"{h2o:.6f}",
                    f"{101.3 + 0.02 * vertical:.6f}",
                    f"{1900.0 + 2.0 * vertical:.6f}",
                ]
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return path


def _write_acquisition_closure_inputs(tmp_path: Path) -> dict[str, Path]:
    probe = tmp_path / "probe.json"
    plan = tmp_path / "plan.json"
    neon_download = tmp_path / "neon_download.json"
    neon_validation = tmp_path / "neon_validation.json"
    public_raw_validation = tmp_path / "public_raw_validation.json"
    probe.write_text(
        json.dumps(
            {
                "artifact_type": "public_ec_data_discovery_probe_v1",
                "sources": [
                    {
                        "source_id": "neon_test",
                        "provider": "NEON",
                        "source_url": "https://example.test/neon",
                        "status": "candidate_verified",
                        "registration_outcome": "not_registered",
                        "parity_value": "real_ec_hdf5_candidate_not_eddypro_output",
                    },
                    {
                        "source_id": "crocus_test",
                        "provider": "DOE OSTI / CROCUS",
                        "source_url": "https://example.test/crocus",
                        "status": "landing_verified",
                        "registration_outcome": "not_registered",
                        "parity_value": "real_high_frequency_raw_candidate_not_eddypro_output",
                    },
                    {
                        "source_id": "icos_test",
                        "provider": "ICOS Carbon Portal",
                        "source_url": "https://example.test/icos",
                        "status": "licence_flow_verified",
                        "registration_outcome": "not_programmatically_registered",
                        "parity_value": "real_raw_ascii_candidate_not_registered",
                    },
                    {
                        "source_id": "licor_anchor",
                        "provider": "LI-COR",
                        "source_url": "https://example.test/licor",
                        "status": "static_ledger_only",
                        "registration_outcome": "registered_and_accepted",
                        "parity_value": "official_public_raw_anchor",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    missing = [
        "eddypro_project_or_settings",
        "official_eddypro_full_output",
        "normalized_reference",
        "normalization_provenance",
        "acceptance_evidence",
    ]
    plan.write_text(
        json.dumps(
            {
                "artifact_type": "public_raw_importer_smoke_plan_v1",
                "candidate_plans": [
                    {
                        "source_id": "neon_test",
                        "provider": "NEON",
                        "source_url": "https://example.test/neon",
                        "sample_mode": "byte_range",
                        "downloadable_file_count": 1,
                        "registration_readiness_status": "blocked_missing_registration_evidence",
                        "missing_for_eddypro_parity": missing,
                        "can_register_as_eddypro_parity_fixture": False,
                    },
                    {
                        "source_id": "crocus_test",
                        "provider": "DOE OSTI / CROCUS",
                        "source_url": "https://example.test/crocus",
                        "sample_mode": "operator_subset",
                        "registration_readiness_status": "blocked_missing_registration_evidence",
                        "missing_for_eddypro_parity": missing,
                        "can_register_as_eddypro_parity_fixture": False,
                    },
                    {
                        "source_id": "icos_test",
                        "provider": "ICOS Carbon Portal",
                        "source_url": "https://example.test/icos",
                        "sample_mode": "operator_subset",
                        "registration_readiness_status": "blocked_missing_registration_evidence",
                        "missing_for_eddypro_parity": missing,
                        "can_register_as_eddypro_parity_fixture": False,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    neon_download.write_text(
        json.dumps(
            {
                "status": "pass",
                "source_id": "neon_test",
                "candidate_name": "NEON.TEST.DP4.00200.001.nsae.2023-07.basic.h5",
                "local_path": str(tmp_path / "neon.h5"),
                "size_bytes": 156344090,
                "md5": "02c7e93f6f8f7309915831c8306ab8c4",
                "sha256": "A2C1BC67BF54123FAB0014CB78427C00BCFE46334169AC56EB9A6036E80E821C",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    neon_validation.write_text(
        json.dumps(
            {
                "status": "pass",
                "source_id": "neon_test",
                "source_file": str(tmp_path / "neon.h5"),
                "row_count": 160,
                "rp_status": "pass",
                "rp_window_count": 1,
                "claim_boundary": {
                    "can_claim_neon_engineering_validation": True,
                    "can_claim_eddypro_raw_to_final_parity": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    public_raw_validation.write_text(
        json.dumps(
            {
                "status": "pass",
                "source_id": "operator_subset_global",
                "source_file": str(tmp_path / "operator_subset.csv"),
                "row_count": 120,
                "importer_status": "pass",
                "rp_status": "pass",
                "rp_window_count": 1,
                "claim_boundary": {
                    "can_claim_public_raw_engineering_validation": True,
                    "can_claim_eddypro_raw_to_final_parity": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "probe": probe,
        "plan": plan,
        "neon_download": neon_download,
        "neon_validation": neon_validation,
        "public_raw_validation": public_raw_validation,
    }


class _FakeResponse:
    def __init__(self, data: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._data = data
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._data)
        chunk = self._data[:size]
        self._data = self._data[size:]
        return chunk


def _fake_public_ec_urlopen(request, timeout: float = 0):  # noqa: ANN001
    url = request.full_url
    method = request.get_method()
    if url == "https://example.test/neon-api":
        return _FakeResponse(
            json.dumps(
                {
                    "data": {
                        "releases": [
                            {
                                "release": "RELEASE-TEST",
                                "packages": [
                                    {
                                        "siteCode": "TEST",
                                        "month": "2023-07",
                                        "packageType": "basic",
                                        "files": [
                                            {
                                                "name": "NEON.TEST.DP4.00200.001.nsae.2023-07.basic.h5",
                                                "size": 1234,
                                                "md5": "abc123",
                                                "url": "https://example.test/neon-file.h5",
                                            },
                                            {
                                                "name": "NEON.TEST.readme.txt",
                                                "size": 10,
                                                "url": "https://example.test/readme.txt",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            ).encode("utf-8")
        )
    if url == "https://example.test/neon-file.h5" and method == "HEAD":
        return _FakeResponse(
            b"",
            status=200,
            headers={
                "Content-Length": "1234",
                "Content-Type": "application/octet-stream",
                "Accept-Ranges": "bytes",
                "x-goog-hash": "md5=abc123",
            },
        )
    if url == "https://example.test/neon-file.h5":
        return _FakeResponse(b"HDF5TESTEXTRA", status=206, headers={"Content-Length": "8"})
    if url == "https://example.test/icos-object":
        return _FakeResponse(b"<html>Raw ASCII object</html>")
    if url == "https://example.test/icos-licence":
        return _FakeResponse(b"<html>I hereby confirm licence_accept</html>")
    if url == "https://example.test/crocus":
        return _FakeResponse(b"<html>CROCUS eddy covariance raw 10 Hz data</html>")
    raise AssertionError(f"unexpected URL: {url}")
