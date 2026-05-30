from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import core.comparison.official_raw_fixture_bundle as official_bundle_module
from core.comparison.official_raw_fixture_bundle import (
    build_official_eddypro_executable_readiness,
    build_official_raw_fixture_bundle_manifest,
    build_official_raw_fixture_bundle_manifest_batch,
    build_official_raw_fixture_evidence_pack,
    build_official_raw_fixture_repair_plan,
    capture_official_eddypro_run_evidence,
    discover_official_raw_fixture_bundles,
    fixture_asset_from_official_raw_bundle,
    inspect_official_raw_fixture_bundle,
    official_raw_fixture_bundle_schema,
    prepare_official_eddypro_project_for_capture,
    register_official_raw_fixture_bundle,
    register_official_raw_fixture_bundle_batch,
    run_official_raw_evidence_pack_acceptance,
    validate_official_raw_fixture_acquisition,
)
from core.headless_batch_runner import run_cli


def _write_ready_bundle(
    root: Path,
    *,
    fixture_id: str = "site_001_official",
    folder_name: str = "site_001",
    raw_name: str = "site_001.ghg",
    site_class: str = "temperate_forest",
    write_manifest: bool = True,
    write_normalized: bool = True,
    include_official_run: bool = True,
) -> Path:
    bundle = root / "references" / "eddypro" / "official_raw" / folder_name
    for child in ("raw", "metadata", "eddypro", "normalized"):
        (bundle / child).mkdir(parents=True, exist_ok=True)
    (bundle / "raw" / raw_name).write_text("synthetic raw placeholder\n", encoding="utf-8")
    metadata_name = f"{folder_name}_metadata.json"
    (bundle / "metadata" / metadata_name).write_text(
        json.dumps({"project": {}, "site": {}, "raw_file_description": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (bundle / "eddypro" / "project.eddypro").write_text("eddypro project settings placeholder\n", encoding="utf-8")
    (bundle / "eddypro" / "eddypro_full_output.csv").write_text(
        "TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\n202604180900,202604180930,1.23,0\n",
        encoding="utf-8",
    )
    if write_normalized:
        (bundle / "normalized" / "reference.json").write_text(
            json.dumps({"reference_id": "site_001_ref", "windows": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (bundle / "normalized" / "provenance.json").write_text(
            json.dumps({"normalization_script": "normalize_reference.py"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if write_manifest:
        official_run = {
            "software_version": "7.0.9",
            "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
            "command": "eddypro.exe --run eddypro/project.eddypro",
            "run_completed_at": "2026-05-28T10:00:00",
            "exit_code": 0,
            "project_file": "eddypro/project.eddypro",
            "output_files": ["eddypro/eddypro_full_output.csv"],
        }
        (bundle / "official_raw_fixture_bundle.json").write_text(
            json.dumps(
                {
                    "fixture_id": fixture_id,
                    "site_class": site_class,
                    "software": "EddyPro",
                    "software_version": "7.0.9",
                    **({"official_eddypro_run": official_run} if include_official_run else {}),
                    "files": {
                        "raw_file": f"raw/{raw_name}",
                        "metadata_json": f"metadata/{metadata_name}",
                        "eddypro_project_file": "eddypro/project.eddypro",
                        "official_full_output": "eddypro/eddypro_full_output.csv",
                        "reference_json": "normalized/reference.json",
                        "provenance_json": "normalized/provenance.json",
                    },
                    "rp_config": {"sample_hz": 10.0, "block_minutes": 30.0},
                    "thresholds": {"flux_rel_threshold": 0.1},
                    "known_limitations": ["Small official fixture used for importer validation."],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return bundle


def _fp2_word(value: float, decimals: int) -> int:
    sign_bit = 0x80 if value < 0 else 0
    mantissa = int(round(abs(float(value)) * (10**decimals)))
    low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
    high_byte = mantissa & 0xFF
    return (high_byte << 8) | low_byte


def test_official_raw_fixture_bundle_schema_documents_required_groups() -> None:
    schema = official_raw_fixture_bundle_schema()

    assert schema["artifact_type"] == "official_raw_fixture_bundle_schema_v1"
    assert "high_frequency_raw_input" in schema["required_file_groups"]
    assert "official_eddypro_full_output" in schema["required_file_groups"]


def test_inspect_official_raw_fixture_bundle_builds_registration_asset(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)

    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert inspection["status"] == "ready_for_registration"
    assert inspection["fixture_id"] == "site_001_official"
    assert not inspection["missing_required_files"]
    assert inspection["files"]["raw_file"]["exists"] is True
    assert inspection["files"]["official_full_output"]["sha256"]
    assert inspection["official_eddypro_run"]["gate_status"] == "pass"
    asset = inspection["asset_preview"]
    assert asset["tier"] == "raw_to_final_parity"
    assert asset["software"] == "EddyPro"
    assert asset["official_eddypro_output"] is True
    assert asset["official_eddypro_run"]["gate_status"] == "pass"
    assert asset["raw_file"].replace("\\", "/") == "references/eddypro/official_raw/site_001/raw/site_001.ghg"
    assert asset["expected_sha256"]["official_full_output"] == inspection["files"]["official_full_output"]["sha256"]


def test_inspect_refreshes_stale_raw_only_import_plan_when_project_is_present(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    (bundle / "eddypro" / "project.eddypro").write_text(
        "rotation_method=double\n"
        "detrend_method=linear\n"
        "averaging_period=30\n",
        encoding="utf-8",
    )
    manifest_path = bundle / "official_raw_fixture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["import_plan"] = {
        "artifact_type": "official_raw_import_plan_v1",
        "status": "raw_only_candidate",
        "unresolved": ["EddyPro project/settings are not present in the public sample archive."],
        "rp_config_draft": {"sample_hz": 10.0},
    }
    manifest["rp_config"] = {"sample_hz": 10.0}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)
    asset = inspection["asset_preview"]

    assert asset["import_plan"]["status"] == "draft_ready"
    assert asset["rp_config"]["rotation_mode"] == "double"
    assert asset["rp_config"]["detrend_mode"] == "linear"


def test_eddypro_numeric_spectral_methods_map_into_import_plan() -> None:
    spectral = official_bundle_module._spectral_correction_config_from_settings(
        {
            "hf_meth": "1",
            "lf_meth": "1",
            "measurement_height": "3.5",
            "gas_analyzer_sensor_separation": "0.25",
        }
    )

    assert spectral["enabled"] is True
    assert spectral["method"] == "moncrieff_97"
    assert spectral["low_frequency_method"] == "analytic"
    assert spectral["eddypro_hf_meth"] == "1"
    assert spectral["sensor_sep_m"] == pytest.approx(0.25)


def test_eddypro_numeric_spectral_disabled_when_hf_method_is_none() -> None:
    spectral = official_bundle_module._spectral_correction_config_from_settings({"hf_meth": "0", "lf_meth": "0"})

    assert spectral["enabled"] is False
    assert spectral["method"] == "none"
    assert spectral["low_frequency_method"] == "none"


def test_eddypro_numeric_qc_method_maps_into_import_plan() -> None:
    qc = official_bundle_module._qc_config_from_settings({"qc_meth": "1"})

    assert qc["enabled"] is True
    assert qc["method"] == "mauder_foken_04"
    assert qc["eddypro_qc_meth"] == "1"


def test_manifest_build_prefers_prepare_sidecar_raw_selection(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, write_manifest=False)
    (bundle / "raw" / "z_later.ghg").write_text("later raw placeholder\n", encoding="utf-8")
    (bundle / "official_eddypro_project_prepare.json").write_text(
        json.dumps(
            {
                "artifact_type": "official_eddypro_project_prepare_v1",
                "status": "prepared",
                "copied_raw_files": [
                    {
                        "source_relative_to_bundle": "raw/site_001.ghg",
                        "prepared_relative_to_bundle": "official_eddypro_run_home/raw_files/site_001.ghg",
                    }
                ],
                "source_project_relative_to_bundle": "eddypro/project.eddypro",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="site_001_official",
        site_class="temperate_forest",
        software_version="7.0.9",
        overwrite=True,
        workspace_root=tmp_path,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))

    assert manifest["files"]["raw_file"] == "raw/site_001.ghg"


def test_build_official_raw_bundle_manifest_infers_roles_for_manifestless_bundle(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        fixture_id="ignored_before_manifest",
        folder_name="manifestless_site",
        raw_name="manifestless_site.tob1",
        write_manifest=False,
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="manifestless_site_official",
        site_class="auto_grassland",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest_path = bundle / "official_raw_fixture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert result["status"] == "manifest_ready"
    assert manifest["fixture_id"] == "manifestless_site_official"
    assert manifest["site_class"] == "auto_grassland"
    assert manifest["files"]["raw_file"] == "raw/manifestless_site.tob1"
    assert manifest["files"]["official_full_output"] == "eddypro/eddypro_full_output.csv"
    assert manifest["official_eddypro_run_checklist"]["status"] == "needs_operator_evidence"
    assert "official_eddypro_run manifest section" in manifest["official_eddypro_run_checklist"]["missing_requirements"]
    assert manifest["generated_by"] == "gas_ec_studio_official_raw_import_wizard"
    assert "tob1" in inspection["files"]["raw_file"]["path"].lower()
    assert inspection["status"] == "ready_for_registration"
    assert inspection["declared_manifest"]["file_roles"]
    assert inspection["official_eddypro_run"]["gate_status"] == "blocked"


def test_build_official_raw_bundle_manifest_records_li7700_status_probe(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        fixture_id="ignored_before_manifest",
        folder_name="ghg_li7700_status_site",
        raw_name="ghg_li7700_status_site.ghg",
        write_manifest=False,
    )
    raw_path = bundle / "raw" / "ghg_li7700_status_site.ghg"
    with ZipFile(raw_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "2021-08-21T000000_AIU-0737.data",
            "DATAH\tSeconds\tNanoseconds\tDate\tTime\tU (m/s)\tV (m/s)\tW (m/s)\tCO2 (umol/mol)\tCH4 (umol/mol)\tCH4 Signal Strength\tCH4 Diagnostic Value\n"
            "DATA\t1629525600\t100000000\t2021-08-21\t00:00:00:100\t1.1\t0.2\t0.3\t402.4\t1.85\t4.9\t16399\n",
        )
        archive.writestr(
            "2021-08-21T000000_AIU-0737-li7700.status",
            "DATASTATH\tMSEC\tSECONDS\tNANOSECONDS\tDIAG\tRSSI\tREFRSSI\n"
            "DATASTAT\t1419595000\t1629525600\t87000000\t16399\t4.82149\t69.6491\n",
        )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="ghg_li7700_status_official",
        site_class="trace_gas_tower",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    probe = manifest["import_plan"]["raw_import_probe"]

    assert result["status"] == "manifest_ready"
    assert probe["status"] == "decoded"
    assert probe["import_summary"]["has_li7700_status"] is True
    assert probe["import_summary"]["status_member_count"] == 1
    assert probe["sample_fields"]["li7700_status_word"] == 16399
    assert probe["sample_fields"]["li7700_status_source_member"].endswith("-li7700.status")


def test_build_official_raw_bundle_manifest_imports_official_run_sidecar(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="sidecar_site",
        raw_name="sidecar_site.ghg",
        write_manifest=False,
    )
    (bundle / "official_eddypro_run.json").write_text(
        json.dumps(
            {
                "software_version": "7.0.9",
                "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
                "command": "eddypro.exe --run eddypro/project.eddypro",
                "run_completed_at": "2026-05-28T10:00:00",
                "exit_code": 0,
                "project_file": "eddypro/project.eddypro",
                "output_files": ["eddypro/eddypro_full_output.csv"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="sidecar_site_official",
        site_class="auto_sidecar",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)
    validation = validate_official_raw_fixture_acquisition(
        bundle,
        workspace_root=tmp_path,
        parity_payload={"status": "pass", "pass_rate": 1.0, "failed_fields": [], "artifact": "raw_to_final_parity.json"},
    )

    assert result["official_eddypro_run"]["gate_status"] == "pass"
    assert result["official_eddypro_run_checklist"]["status"] == "pass"
    assert manifest["official_eddypro_run"]["source_file"] == "official_eddypro_run.json"
    assert manifest["official_eddypro_run_checklist"]["status"] == "pass"
    assert inspection["official_eddypro_run"]["output_files"][0]["sha256"]
    assert inspection["official_eddypro_run_checklist"]["status"] == "pass"
    assert validation["gate_status"] == "pass"


def test_inspect_prefers_passing_official_run_sidecar_over_blocked_manifest(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    manifest_path = bundle / "official_raw_fixture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["official_eddypro_run"]["exit_code"] = 1
    manifest["official_eddypro_run"]["command"] = "embedded output only"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (bundle / "official_eddypro_run.json").write_text(
        json.dumps(
            {
                "software_version": "7.0.9",
                "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
                "command": "eddypro.exe --run prepared/project.eddypro",
                "run_completed_at": "2026-05-28T10:00:00",
                "exit_code": 0,
                "project_file": "prepared/project.eddypro",
                "output_files": ["eddypro/eddypro_full_output.csv"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert inspection["official_eddypro_run"]["gate_status"] == "pass"
    assert inspection["official_eddypro_run"]["source_file"] == "official_eddypro_run.json"
    assert inspection["official_eddypro_run"]["command"] == "eddypro.exe --run prepared/project.eddypro"


def test_capture_official_eddypro_run_evidence_executes_command_and_writes_sidecar(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="capture_site",
        raw_name="capture_site.ghg",
        write_manifest=False,
    )
    output_file = bundle / "eddypro" / "eddypro_full_output.csv"
    output_file.unlink()
    fake_eddypro = tmp_path / "fake_eddypro.py"
    fake_eddypro.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n202604180900,202604180930,2.34,0\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    capture = capture_official_eddypro_run_evidence(
        bundle,
        command=f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
        software_version="7.0.9",
        executable_path=str(fake_eddypro),
        project_file="eddypro/project.eddypro",
        output_files=["eddypro/eddypro_full_output.csv"],
        workspace_root=tmp_path,
        timeout_s=30,
    )
    sidecar = json.loads((bundle / "official_eddypro_run.json").read_text(encoding="utf-8"))
    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="capture_site_official",
        site_class="capture_site",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert capture["status"] == "pass"
    assert capture["official_eddypro_run"]["gate_status"] == "pass"
    assert sidecar["exit_code"] == 0
    assert sidecar["output_file_hashes"][0]["sha256"]
    assert sidecar["validation"]["gate_status"] == "pass"
    assert result["official_eddypro_run"]["gate_status"] == "pass"
    assert inspection["official_eddypro_run"]["declared_output_hashes"][0]["sha256"]


def test_capture_official_eddypro_run_evidence_hashes_globbed_outputs(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="capture_glob_site",
        raw_name="capture_glob_site.ghg",
        write_manifest=False,
    )
    (bundle / "eddypro" / "eddypro_full_output.csv").unlink()
    output_file = bundle / "eddypro" / "eddypro_exp_full_output_20260418.csv"
    fake_eddypro = tmp_path / "fake_eddypro_glob.py"
    fake_eddypro.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n202604180900,202604180930,3.45,0\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    capture = capture_official_eddypro_run_evidence(
        bundle,
        command=f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
        software_version="7.0.9",
        executable_path=str(fake_eddypro),
        project_file="eddypro/project.eddypro",
        output_files=["eddypro/*full_output*.csv"],
        workspace_root=tmp_path,
        timeout_s=30,
    )

    assert capture["gate_status"] == "pass"
    assert capture["sidecar"]["output_files"] == ["eddypro/eddypro_exp_full_output_20260418.csv"]
    assert capture["output_file_hashes"][0]["sha256"]


def test_capture_official_eddypro_run_evidence_syncs_manifest(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, folder_name="capture_manifest_site", raw_name="capture_manifest_site.ghg")
    output_file = bundle / "eddypro" / "eddypro_full_output.csv"
    fake_eddypro = tmp_path / "fake_eddypro_manifest.py"
    fake_eddypro.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n202604180900,202604180930,4.56,0\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    capture = capture_official_eddypro_run_evidence(
        bundle,
        command=f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
        software_version="7.0.9",
        executable_path=str(fake_eddypro),
        project_file="eddypro/project.eddypro",
        output_files=["eddypro/eddypro_full_output.csv"],
        workspace_root=tmp_path,
        timeout_s=30,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))

    assert capture["gate_status"] == "pass"
    assert manifest["official_eddypro_run"]["exit_code"] == 0
    assert manifest["official_eddypro_run"]["source_file"] == "official_eddypro_run.json"
    assert manifest["official_eddypro_run_checklist"]["status"] == "pass"


def test_official_eddypro_executable_readiness_reports_ready_to_capture_with_explicit_executable(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, include_official_run=False)

    payload = build_official_eddypro_executable_readiness(
        bundle,
        executable_path=sys.executable,
        workspace_root=tmp_path,
    )

    assert payload["artifact_type"] == "official_eddypro_executable_readiness_v1"
    assert payload["status"] == "ready_to_capture"
    assert payload["gate_status"] == "ready_to_capture"
    assert payload["bundle_status"] == "ready_for_registration"
    assert payload["present_executable_count"] == 1
    assert payload["selected_executable"]["path"] == sys.executable
    assert payload["official_eddypro_run_gate_status"] == "blocked"
    assert "exit_code=0" in payload["official_eddypro_run_missing_requirements"]
    assert "--capture-official-eddypro-run" in payload["capture_command"]


def test_official_eddypro_executable_readiness_reports_source_ready_toolchain_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = _write_ready_bundle(tmp_path, include_official_run=False)
    source = tmp_path / "eddypro-engine"
    (source / "prj").mkdir(parents=True)
    (source / "README.md").write_text("To compile the Engine use gfortran and make.\n", encoding="utf-8")
    (source / "prj" / "Makefile").write_text("rp:\n\t@echo rp\n", encoding="utf-8")
    monkeypatch.setattr(official_bundle_module, "_git_value", lambda *_args: "3cabe637" if "rev-parse" in _args else "https://github.com/LI-COR-Environmental/eddypro-engine.git")
    monkeypatch.setattr(official_bundle_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(official_bundle_module, "_common_windows_tool_paths", lambda _name: [])

    payload = build_official_eddypro_executable_readiness(
        bundle,
        source_dir=source,
        workspace_root=tmp_path,
    )

    assert payload["status"] == "source_ready_toolchain_missing"
    assert payload["source_checkout"]["status"] == "source_ready"
    assert "EddyPro RP executable not found" in payload["missing_requirements"]
    assert "gfortran compiler missing" in payload["missing_requirements"]
    assert "make/mingw32-make missing" in payload["missing_requirements"]
    assert any(command.strip().endswith(" rp") for command in payload["build_commands"])


def test_prepare_official_eddypro_project_for_capture_preserves_source_assets(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, include_official_run=False)
    source_project = bundle / "eddypro" / "project.eddypro"
    source_project.write_text("out_path=\ndata_path=\nrun_mode=1\n", encoding="utf-8")

    payload = prepare_official_eddypro_project_for_capture(
        bundle,
        workspace_root=tmp_path,
    )
    sidecar = json.loads((bundle / "official_eddypro_project_prepare.json").read_text(encoding="utf-8"))
    prepared_project = bundle / "official_eddypro_run_home" / "ini" / "processing.eddypro"
    prepared_raw = bundle / "official_eddypro_run_home" / "raw_files" / "site_001.ghg"

    assert payload["status"] == "prepared"
    assert sidecar["status"] == "prepared"
    assert source_project.read_text(encoding="utf-8") == "out_path=\ndata_path=\nrun_mode=1\n"
    assert prepared_project.exists()
    assert prepared_raw.exists()
    assert "official_eddypro_run_home/output/*full_output*.csv" in payload["recommended_capture"]["output_files"]
    assert {change["key"] for change in payload["project_changes"]} == {"out_path", "data_path"}
    assert payload["copied_raw_files"][0]["sha256"]


def test_headless_cli_prepares_official_eddypro_project(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, include_official_run=False)
    output = tmp_path / "prepare.json"

    exit_code = run_cli(
        [
            "--prepare-official-eddypro-project",
            str(bundle),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["status"] == "prepared"
    assert (bundle / "official_eddypro_run_home" / "ini" / "processing.eddypro").exists()
    assert (bundle / "official_eddypro_project_prepare.json").exists()


def test_build_official_raw_bundle_manifest_generates_reference_from_full_output(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="autonorm_site",
        raw_name="autonorm.csv",
        write_manifest=False,
        write_normalized=False,
    )
    (bundle / "raw" / "autonorm.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="autonorm_official",
        site_class="auto_reference",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    reference = json.loads((bundle / "normalized" / "reference.json").read_text(encoding="utf-8"))
    provenance = json.loads((bundle / "normalized" / "provenance.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert result["status"] == "manifest_ready"
    assert result["normalization_result"]["status"] == "normalized"
    assert result["normalization_result"]["window_count"] == 1
    assert manifest["files"]["reference_json"] == "normalized/reference.json"
    assert manifest["files"]["provenance_json"] == "normalized/provenance.json"
    assert manifest["normalization_result"]["source_file"].endswith("eddypro_full_output.csv")
    assert reference["reference_id"] == "autonorm_official_reference"
    assert reference["windows"][0]["start_time"] == "2026-04-18T09:00:00"
    assert reference["windows"][0]["end_time"] == "2026-04-18T09:30:00"
    assert reference["windows"][0]["primary_flux"] == 1.23
    assert reference["windows"][0]["qc_grade"] == "A"
    assert reference["windows"][0]["eddypro_qc_flag"] == "0"
    assert reference["method_metadata"]["density_correction"]["availability"] == "not_reported"
    assert provenance["artifact_type"] == "eddypro_full_output_normalization_provenance_v1"
    assert provenance["original_file_name"] == "eddypro_full_output.csv"
    assert provenance["normalization_command"].startswith("gas-ec-headless --build-official-raw-bundle-manifest")
    assert provenance["qc_mapping_strategy"] == "EddyPro 0/1/2 -> gas_ec_studio A/B/C"
    assert provenance["required_fields_present"] is True
    assert inspection["status"] == "ready_for_registration"
    assert inspection["files"]["reference_json"]["sha256"]
    assert inspection["files"]["provenance_json"]["sha256"]


def test_build_official_raw_bundle_manifest_generates_official_run_reference(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="official_run_norm_site",
        raw_name="official_run_norm.csv",
        write_manifest=False,
        write_normalized=False,
    )
    run_output = bundle / "official_eddypro_run_home" / "output" / "eddypro_exp_full_output_run.csv"
    run_output.parent.mkdir(parents=True, exist_ok=True)
    run_output.write_text(
        "TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\n202604180900,202604180930,2.34,0\n",
        encoding="utf-8",
    )
    (bundle / "official_eddypro_run.json").write_text(
        json.dumps(
            {
                "software_version": "7.0.9",
                "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
                "command": "eddypro.exe -m embedded -e official_eddypro_run_home",
                "run_completed_at": "2026-05-28T10:00:00",
                "exit_code": 0,
                "project_file": "official_eddypro_run_home/ini/processing.eddypro",
                "output_files": ["official_eddypro_run_home/output/*full_output*.csv"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="official_run_norm_official",
        site_class="auto_reference",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    primary_reference = json.loads((bundle / "normalized" / "reference.json").read_text(encoding="utf-8"))
    run_reference = json.loads((bundle / "normalized" / "official_eddypro_run_reference.json").read_text(encoding="utf-8"))
    run_provenance = json.loads((bundle / "normalized" / "official_eddypro_run_provenance.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)
    evidence_pack = build_official_raw_fixture_evidence_pack(bundle, workspace_root=tmp_path)

    assert result["status"] == "manifest_ready"
    assert result["official_run_normalization_result"]["status"] == "normalized"
    assert result["official_run_normalization_result"]["source_file"].endswith("eddypro_exp_full_output_run.csv")
    assert manifest["official_run_normalization_result"]["reference_json"] == "normalized/official_eddypro_run_reference.json"
    assert manifest["official_run_normalization_result"]["provenance_json"] == "normalized/official_eddypro_run_provenance.json"
    assert primary_reference["windows"][0]["primary_flux"] == pytest.approx(1.23)
    assert run_reference["reference_id"] == "official_run_norm_official_official_eddypro_run_reference"
    assert run_reference["windows"][0]["primary_flux"] == pytest.approx(2.34)
    assert run_provenance["original_file_name"] == "eddypro_exp_full_output_run.csv"
    assert "--normalize-official-eddypro-run-output" in run_provenance["normalization_command"]
    assert inspection["declared_manifest"]["has_official_run_normalization"] is True
    assert inspection["official_run_normalization_result"]["status"] == "normalized"
    assert evidence_pack["official_run_normalization"]["status"] == "normalized"


def test_build_official_raw_bundle_manifest_refreshes_existing_manifest_official_run_reference(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="existing_manifest_run_norm_site",
        raw_name="existing_manifest_run_norm.csv",
        write_manifest=True,
        write_normalized=True,
        include_official_run=False,
    )
    run_output = bundle / "official_eddypro_run_home" / "output" / "eddypro_exp_full_output_refresh.csv"
    run_output.parent.mkdir(parents=True, exist_ok=True)
    run_output.write_text(
        "TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\n202604180900,202604180930,3.45,0\n",
        encoding="utf-8",
    )
    (bundle / "official_eddypro_run.json").write_text(
        json.dumps(
            {
                "software_version": "7.0.9",
                "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
                "command": "eddypro.exe -m embedded -e official_eddypro_run_home",
                "run_completed_at": "2026-05-28T10:00:00",
                "exit_code": 0,
                "project_file": "official_eddypro_run_home/ini/processing.eddypro",
                "output_files": ["official_eddypro_run_home/output/*full_output*.csv"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="ignored_without_overwrite",
        site_class="auto_reference",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    run_reference = json.loads((bundle / "normalized" / "official_eddypro_run_reference.json").read_text(encoding="utf-8"))
    primary_reference = json.loads((bundle / "normalized" / "reference.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert result["status"] == "manifest_refreshed"
    assert result["manifest_updated"] is True
    assert result["official_run_normalization_result"]["status"] == "normalized"
    assert manifest["fixture_id"] == "site_001_official"
    assert manifest["official_eddypro_run"]["source_file"] == "official_eddypro_run.json"
    assert manifest["official_run_normalization_result"]["reference_json"] == "normalized/official_eddypro_run_reference.json"
    assert primary_reference["reference_id"] == "site_001_ref"
    assert run_reference["windows"][0]["primary_flux"] == pytest.approx(3.45)
    assert inspection["official_run_normalization_result"]["status"] == "normalized"


def test_build_official_raw_bundle_manifest_writes_import_plan_from_tob1_header(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="autoplan_tob1_site",
        raw_name="autoplan.tob1",
        write_manifest=False,
    )
    (bundle / "raw" / "autoplan.tob1").write_bytes(
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"TS","RN","m/s","m/s","m/s","ppm","mmol/mol","kPa","C"\r\n'
        b'"Smp","Smp","Avg","Avg","Avg","Avg","Avg","Avg","Avg"\r\n'
    )
    (bundle / "eddypro" / "project.eddypro").write_text(
        "sample_hz=20\n"
        "averaging_period=15\n"
        "start_time=2026-05-22T10:00:00\n"
        "rotation_method=double\n"
        "density_correction=wpl\n"
        "lag_strategy=covariance_max\n"
        "expected_lag_s=0.35\n"
        "search_window_s=2.5\n"
        "detrend_method=linear\n"
        "spectral_correction=enabled\n"
        "spectral_correction_method=fratini\n"
        "use_fcc_measured_cospectrum=true\n"
        "footprint=enabled\n"
        "footprint_method=kljun\n"
        "measurement_height=3.2\n"
        "canopy_height=1.1\n"
        "roughness_length=0.08\n"
        "uncertainty_method=finkelstein_sims\n"
        "confidence_level=0.9\n"
        "skewness_threshold=2.4\n"
        "kurtosis_threshold=8.5\n"
        "spike_sigma=4.5\n"
        "dropout_min_run=12\n"
        "discontinuity_sigma=7.5\n",
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="autoplan_tob1_official",
        site_class="auto_tob1",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    plan = manifest["import_plan"]
    settings = plan["metadata_draft"]["raw_file_settings"]
    description = plan["metadata_draft"]["raw_file_description"]
    rp_config = plan["rp_config_draft"]
    assert result["status"] == "manifest_ready"
    assert plan["artifact_type"] == "official_raw_import_plan_v1"
    assert plan["status"] == "draft_ready"
    assert plan["raw_input"]["format"] == "tob1"
    assert settings["sample_hz"] == 20.0
    assert settings["header_rows"] == 4
    assert settings["extra"]["native_format"] == "tob1_fp2"
    assert settings["extra"]["columns"] == ["U", "V", "W", "CO2", "H2O", "P", "TA"]
    assert settings["extra"]["start_time"] == "2026-05-22T10:00:00"
    assert description["source_type"] == "tob1"
    assert {item["variable"] for item in description["column_mappings"]} >= {"u", "v", "w", "co2_ppm", "h2o_mmol", "pressure_kpa", "chamber_temp_c"}
    assert manifest["rp_config"]["sample_hz"] == 20.0
    assert manifest["rp_config"]["block_minutes"] == 15.0
    assert rp_config["rotation_mode"] == "double"
    assert rp_config["steps"]["rotation"]["method"] == "double"
    assert rp_config["detrend_mode"] == "linear"
    assert rp_config["steps"]["detrend"]["method"] == "linear"
    assert rp_config["density_correction_mode"] == "wpl"
    assert rp_config["steps"]["density_correction"]["correction_mode"] == "wpl"
    assert rp_config["lag_phase"] == {"strategy": "covariance_max", "expected_lag_s": 0.35, "search_window_s": 2.5}
    assert rp_config["steps"]["lag"]["search_window_s"] == 2.5
    assert rp_config["spectral_correction"]["enabled"] is True
    assert rp_config["spectral_correction"]["method"] == "fratini"
    assert rp_config["spectral_correction"]["use_fcc_measured_cospectrum"] is True
    assert rp_config["footprint"] == {"enabled": True, "method": "kljun", "z_m": 3.2, "canopy_height_m": 1.1, "z0": 0.08}
    assert rp_config["uncertainty"] == {"method": "finkelstein_sims", "confidence_level": 0.9}
    assert rp_config["screening"] == {
        "skewness_threshold": 2.4,
        "kurtosis_threshold": 8.5,
        "spike_sigma": 4.5,
        "discontinuity_sigma": 7.5,
        "dropout_min_run": 12,
    }
    assert manifest["rp_config"]["spectral_correction"]["method"] == "fratini"
    assert manifest["rp_config"]["footprint"]["z_m"] == 3.2
    assert any(source["role"] == "rp_config_draft" for source in plan["inference_sources"])
    assert inspection["import_plan"]["metadata_draft"]["raw_file_settings"]["extra"]["native_format"] == "tob1_fp2"
    assert inspection["asset_preview"]["import_plan"]["status"] == "draft_ready"
    assert inspection["asset_preview"]["import_plan"]["rp_config_draft"]["screening"]["dropout_min_run"] == 12


def test_official_raw_import_plan_probes_native_tob1_payload(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="probe_tob1_site",
        raw_name="probe.tob1",
        write_manifest=False,
    )
    header = (
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"TS","RN","m/s","m/s","m/s","ppm","mmol/mol","kPa","C"\r\n'
        b'"Smp","Smp","Avg","Avg","Avg","Avg","Avg","Avg","Avg"\r\n'
    )
    records = [
        (
            _fp2_word(2.5, 1),
            _fp2_word(-0.1, 1),
            _fp2_word(0.2, 1),
            _fp2_word(410.0, 1),
            _fp2_word(12.34, 2),
            _fp2_word(101.3, 1),
            _fp2_word(25.6, 1),
        ),
        (
            _fp2_word(2.6, 1),
            _fp2_word(-0.2, 1),
            _fp2_word(0.3, 1),
            _fp2_word(411.0, 1),
            _fp2_word(12.35, 2),
            _fp2_word(101.4, 1),
            _fp2_word(25.7, 1),
        ),
    ]
    (bundle / "raw" / "probe.tob1").write_bytes(header + b"".join(struct.pack("<7H", *record) for record in records))
    (bundle / "eddypro" / "project.eddypro").write_text(
        "sample_hz=10\n"
        "averaging_period=30\n"
        "start_time=2026-05-22T10:00:00\n",
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="probe_tob1_official",
        site_class="native_probe",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)
    probe = manifest["import_plan"]["raw_import_probe"]

    assert result["status"] == "manifest_ready"
    assert probe["artifact_type"] == "official_raw_import_probe_v1"
    assert probe["status"] == "decoded"
    assert probe["format"] == "tob1_fp2"
    assert probe["native"] is True
    assert probe["row_count"] == 2
    assert probe["time_start"] == "2026-05-22T10:00:00"
    assert probe["import_summary"]["column_source"] == "extra"
    assert probe["import_summary"]["columns"] == ["U", "V", "W", "CO2", "H2O", "P", "TA"]
    assert probe["import_summary"]["header_detection"]["tob1_format"] == "fp2"
    assert "src/src_common/m_fp2_to_float.f90" in probe["import_summary"]["source_reference"]["eddypro_engine_files"]
    assert probe["sample_fields"]["co2_ppm"] == 410.0
    assert any(source["role"] == "raw_import_probe" and source["status"] == "decoded" for source in manifest["import_plan"]["inference_sources"])
    matrix_row = inspection["import_plan"]["raw_import_probe"]
    assert matrix_row["status"] == "decoded"


def test_build_official_raw_bundle_manifest_maps_eddypro_section_metadata(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="sectioned_project_site",
        raw_name="sectioned.csv",
        write_manifest=False,
    )
    (bundle / "raw" / "sectioned.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")
    (bundle / "eddypro" / "project.eddypro").write_text(
        "[Project]\n"
        "project_id=RIDGE-2026\n"
        "project_name=Ridge EddyPro Campaign\n"
        "principal_investigator=Flux Team\n"
        "[Site]\n"
        "site_id=RIDGE\n"
        "site_name=Ridge Tower\n"
        "latitude=35.1234\n"
        "longitude=-120.5678\n"
        "altitude=812.5\n"
        "canopy_height=2.7\n"
        "roughness_length=0.12\n"
        "dynamic_canopy_height_file=metadata/canopy_schedule.csv\n"
        "[Sonic Anemometer]\n"
        "manufacturer=Gill\n"
        "model=WindMaster Pro\n"
        "serial_number=WM-123\n"
        "firmware_version=2329.600.1\n"
        "height=3.4\n"
        "wind_format=axis\n"
        "wind_reference=axis\n"
        "w_offset=0.01\n"
        "gill_wm_w_boost=auto\n"
        "sonic_correction=true\n"
        "angle_of_attack_correction=true\n"
        "angle_of_attack_method=nakai_2012\n"
        "crosswind_correction=true\n"
        "[Gas Analyzer]\n"
        "manufacturer=LI-COR\n"
        "model=LI-7500DS\n"
        "serial_number=7500-456\n"
        "firmware_version=8.9.0\n"
        "height=3.2\n"
        "path_length_m=0.15\n"
        "sensor_separation_m=0.2\n"
        "response_time_s=0.1\n"
        "[Closed Path]\n"
        "tube_length_m=12\n"
        "tube_diameter_mm=4\n"
        "flow_lpm=8\n"
        "tube_material=Synflex\n"
        "heat_traced=yes\n"
        "cell_pressure_kpa=100.8\n"
        "cell_temperature_c=24.2\n",
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="sectioned_official",
        site_class="ridge_field",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    metadata = manifest["import_plan"]["metadata_draft"]
    rp_config = manifest["rp_config"]

    assert result["status"] == "manifest_ready"
    assert metadata["project"]["code"] == "RIDGE-2026"
    assert metadata["project"]["name"] == "Ridge EddyPro Campaign"
    assert metadata["project"]["principal"] == "Flux Team"
    assert metadata["site"]["station_code"] == "RIDGE"
    assert metadata["site"]["station_name"] == "Ridge Tower"
    assert metadata["site"]["latitude"] == 35.1234
    assert metadata["site"]["longitude"] == -120.5678
    assert metadata["site"]["canopy_height_m"] == 2.7
    assert metadata["dynamic_metadata"]["source_path"] == "metadata/canopy_schedule.csv"
    assert metadata["dynamic_metadata"]["fields"] == ["canopy_height_m"]
    assert metadata["instruments"]["sonic_manufacturer"] == "Gill"
    assert metadata["instruments"]["sonic_model"] == "WindMaster Pro"
    assert metadata["instruments"]["sonic_serial"] == "WM-123"
    assert metadata["instruments"]["sonic_height_m"] == 3.4
    assert metadata["instruments"]["analyzer_manufacturer"] == "LI-COR"
    assert metadata["instruments"]["analyzer_model"] == "LI-7500DS"
    assert metadata["instruments"]["analyzer_serial"] == "7500-456"
    assert metadata["instruments"]["analyzer_height_m"] == 3.2
    assert metadata["instruments"]["sensor_separation_m"] == 0.2
    assert metadata["instruments"]["optical_path_length_m"] == 0.15
    assert metadata["instruments"]["extra"]["sonic_wind_format"] == "axis"
    assert metadata["instruments"]["extra"]["sonic_w_offset_ms"] == 0.01
    assert metadata["instruments"]["extra"]["crosswind_enabled"] is True
    assert metadata["sampling_chain"]["tube_length_m"] == 12.0
    assert metadata["sampling_chain"]["tube_diameter_mm"] == 4.0
    assert metadata["sampling_chain"]["flow_lpm"] == 8.0
    assert metadata["sampling_chain"]["heat_traced"] is True
    assert metadata["sampling_chain"]["extra"]["cell_pressure_kpa"] == 100.8
    assert rp_config["metadata_bundle"]["instruments"]["sonic_model"] == "WindMaster Pro"
    assert rp_config["sonic_correction"]["enabled"] is True
    assert rp_config["sonic_correction"]["sonic_model"] == "WindMaster Pro"
    assert rp_config["sonic_correction"]["w_offset_ms"] == 0.01
    assert rp_config["sonic_correction"]["angle_of_attack"] == {"enabled": True, "method": "nakai_2012"}
    assert rp_config["crosswind_correction"]["enabled"] is True
    assert rp_config["crosswind_correction"]["sonic_manufacturer"] == "Gill"
    assert rp_config["spectral_correction"]["path_length_m"] == 0.15
    assert rp_config["spectral_correction"]["sensor_sep_m"] == 0.2
    assert rp_config["spectral_correction"]["response_time_s"] == 0.1


def test_build_official_raw_bundle_manifest_auto_discovers_biomet_and_dynamic_metadata(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="auto_metadata_site",
        raw_name="auto_metadata.csv",
        write_manifest=False,
    )
    (bundle / "raw" / "auto_metadata.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")
    (bundle / "metadata" / "site_biomet.csv").write_text(
        "timestamp,ta,pressure_kpa,rh\n2026-05-22T10:00:00,24.5,100.2,63\n",
        encoding="utf-8",
    )
    (bundle / "metadata" / "canopy_schedule.csv").write_text(
        "start_time,end_time,canopy_height_m\n2026-05-01T00:00:00,2026-06-01T00:00:00,2.4\n",
        encoding="utf-8",
    )
    (bundle / "eddypro" / "project.eddypro").write_text(
        "[Project]\nproject_id=AUTO-META\n[Site]\nsite_id=AUTO\n",
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="auto_metadata_official",
        site_class="auto_metadata",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    metadata = manifest["import_plan"]["metadata_draft"]
    rp_config = manifest["rp_config"]

    assert result["status"] == "manifest_ready"
    assert metadata["biomet"]["source_path"] == "metadata/site_biomet.csv"
    assert metadata["biomet"]["source_mode"] == "external_file"
    assert set(metadata["biomet"]["fields"]) >= {"ta", "pressure_kpa", "rh"}
    assert metadata["biomet"]["extra"]["auto_discovered"] is True
    assert metadata["dynamic_metadata"]["source_path"] == "metadata/canopy_schedule.csv"
    assert metadata["dynamic_metadata"]["fields"] == ["canopy_height_m"]
    assert metadata["dynamic_metadata"]["extra"]["auto_discovered"] is True
    assert rp_config["metadata_bundle"]["biomet"]["source_path"] == "metadata/site_biomet.csv"
    assert rp_config["metadata_bundle"]["dynamic_metadata"]["source_path"] == "metadata/canopy_schedule.csv"


def test_build_official_raw_bundle_manifest_maps_li7700_trace_gas_settings(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="li7700_project_site",
        raw_name="li7700_ch4.csv",
        write_manifest=False,
    )
    (bundle / "raw" / "li7700_ch4.csv").write_text("timestamp,u,v,w,co2,h2o,ch4_ppm,p,ta\n", encoding="utf-8")
    (bundle / "metadata" / "li7700_coefficients.json").write_text(
        json.dumps(
            {
                "profile_id": "tower_li7700_2026",
                "label": "Tower LI-7700 2026 coefficients",
                "source": "normalized_reference",
                "spectroscopic_correction": {
                    "mode": "empirical",
                    "pressure_sensitivity_per_kpa": 0.001,
                },
                "known_limitations": ["Fixture coefficient file requires official LI-7700 WMS validation."],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (bundle / "eddypro" / "project.eddypro").write_text(
        "[File Description]\n"
        "columns=timestamp,u,v,w,co2,h2o,ch4_ppm,p,ta\n"
        "sample_hz=10\n"
        "averaging_period=30\n"
        "[Methane Analyzer]\n"
        "manufacturer=LI-COR\n"
        "model=LI-7700\n"
        "serial_number=7700-001\n"
        "firmware_version=2.3.4\n"
        "height=3.1\n"
        "coefficient_profile_id=tower_li7700_2026\n"
        "coefficient_source_file=metadata/li7700_coefficients.json\n"
        "normalization_command=gas_ec normalize-li7700 --profile tower_li7700_2026\n"
        "known_limitations=synthetic fixture only|requires official WMS validation\n"
        "min_rssi_fail_pct=12\n"
        "min_rssi_warning_pct=24\n"
        "min_signal_strength_warning_pct=30\n"
        "max_mirror_dirty_fraction=0.02\n"
        "require_li7700_lock=true\n"
        "allowed_status_words=0\n"
        "status_bit_map=0:laser_unlocked|2:mirror_dirty\n"
        "[Trace Gas]\n"
        "ch4_enabled=true\n"
        "apply_water_vapor_dilution=true\n"
        "ch4_spectral_correction_factor=1.03\n"
        "spectroscopic_mode=empirical\n"
        "pressure_sensitivity_per_kpa=0.001\n"
        "temperature_sensitivity_per_c=0.0005\n"
        "h2o_sensitivity_per_molfrac=0.10\n"
        "self_heating_mode=empirical\n"
        "sensor_body_temp_c=27.0\n"
        "flux_sensitivity_per_c=0.01\n",
        encoding="utf-8",
    )

    result = build_official_raw_fixture_bundle_manifest(
        bundle,
        fixture_id="li7700_official",
        site_class="trace_gas_tower",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )

    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    metadata = manifest["import_plan"]["metadata_draft"]
    rp_config = manifest["rp_config"]
    mappings = metadata["raw_file_description"]["column_mappings"]
    ch4_config = rp_config["trace_gas"]["ch4"]
    profile = ch4_config["coefficient_registry"]["tower_li7700_2026"]

    assert result["status"] == "manifest_ready"
    assert {item["variable"] for item in mappings} >= {"ch4_ppb", "co2_ppm", "h2o_mmol"}
    assert metadata["instruments"]["methane_analyzer_manufacturer"] == "LI-COR"
    assert metadata["instruments"]["methane_analyzer_model"] == "LI-7700"
    assert metadata["instruments"]["methane_analyzer_serial"] == "7700-001"
    assert metadata["instruments"]["methane_analyzer_height_m"] == 3.1
    assert metadata["instruments"]["extra"]["li7700_coefficient_profile_id"] == "tower_li7700_2026"
    assert ch4_config["enabled"] is True
    assert ch4_config["method"] == "li_7700_correction_sequence_v1"
    assert ch4_config["coefficient_profile_id"] == "tower_li7700_2026"
    assert ch4_config["apply_water_vapor_dilution"] is True
    assert ch4_config["spectral_correction_factor"] == 1.03
    assert ch4_config["spectroscopic_correction"]["mode"] == "empirical"
    assert ch4_config["spectroscopic_correction"]["temperature_sensitivity_per_c"] == 0.0005
    assert ch4_config["self_heating_correction"]["mode"] == "empirical"
    assert ch4_config["self_heating_correction"]["sensor_body_temp_c"] == 27.0
    assert ch4_config["status_diagnostics"]["min_rssi_fail_pct"] == 12.0
    assert ch4_config["status_diagnostics"]["min_rssi_warning_pct"] == 24.0
    assert ch4_config["status_diagnostics"]["min_signal_strength_warning_pct"] == 30.0
    assert ch4_config["status_diagnostics"]["max_mirror_dirty_fraction"] == 0.02
    assert ch4_config["status_diagnostics"]["require_lock"] is True
    assert ch4_config["status_diagnostics"]["allowed_status_words"] == [0]
    assert ch4_config["status_diagnostics"]["status_bit_map"] == {"0": "laser_unlocked", "2": "mirror_dirty"}
    assert profile["source_file"] == "metadata/li7700_coefficients.json"
    assert profile["normalization_command"] == "gas_ec normalize-li7700 --profile tower_li7700_2026"
    assert profile["instrument_family"] == "LI-7700"
    assert profile["status_diagnostics"]["require_lock"] is True
    assert "official WMS validation" in " ".join(profile["known_limitations"])
    assert rp_config["steps"]["trace_gas"]["ch4"]["coefficient_profile_id"] == "tower_li7700_2026"


def test_fixture_asset_from_official_raw_bundle_rejects_incomplete_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "raw.csv").write_text("timestamp,u,v,w,co2\n", encoding="utf-8")

    inspection = inspect_official_raw_fixture_bundle(bundle, workspace_root=tmp_path)

    assert inspection["status"] == "incomplete"
    assert inspection["acquisition_validation"]["status"] == "blocked"
    assert "official_eddypro_full_output" in inspection["acquisition_validation"]["missing_requirements"]
    assert "official_eddypro_full_output" in inspection["missing_required_files"]
    with pytest.raises(ValueError, match="not ready for registration"):
        fixture_asset_from_official_raw_bundle(bundle, workspace_root=tmp_path)


def test_validate_official_raw_fixture_acquisition_tracks_p0_closure(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)

    pending = validate_official_raw_fixture_acquisition(bundle, workspace_root=tmp_path)

    assert pending["artifact_type"] == "official_raw_fixture_acquisition_validation_v1"
    assert pending["closure_id"] == "fixture_pack:official_raw_to_final_ready_count"
    assert pending["priority"] == "P0"
    assert pending["status"] == "ready_for_registration_pending_parity"
    assert pending["gate_status"] == "blocked"
    assert "raw_to_final_parity_pass" in pending["missing_requirements"]
    assert pending["acceptance_commands"]

    closed = validate_official_raw_fixture_acquisition(
        bundle,
        workspace_root=tmp_path,
        parity_payload={"status": "pass", "pass_rate": 1.0, "failed_fields": [], "artifact": "raw_to_final_parity.json"},
    )

    assert closed["status"] == "closure_ready"
    assert closed["gate_status"] == "pass"
    assert closed["missing_requirements"] == []
    assert closed["blocked_claims"] == []

    missing_run_bundle = _write_ready_bundle(tmp_path, folder_name="missing_run", include_official_run=False)
    blocked = validate_official_raw_fixture_acquisition(
        missing_run_bundle,
        workspace_root=tmp_path,
        parity_payload={"status": "pass", "pass_rate": 1.0, "failed_fields": [], "artifact": "raw_to_final_parity.json"},
    )
    assert blocked["gate_status"] == "blocked"
    assert "official_eddypro_executable_run" in blocked["missing_requirements"]


def test_build_official_raw_fixture_evidence_pack_records_hashes_and_gate(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    parity = {"status": "pass", "pass_rate": 1.0, "failed_fields": [], "artifact": "raw_to_final_parity.json"}

    pack = build_official_raw_fixture_evidence_pack(
        bundle,
        workspace_root=tmp_path,
        parity_payload=parity,
    )

    assert pack["artifact_type"] == "official_raw_fixture_evidence_pack_v1"
    assert pack["status"] == "complete"
    assert pack["fixture_id"] == "site_001_official"
    assert pack["source_file_count"] >= 5
    assert pack["present_source_file_count"] == pack["source_file_count"]
    assert pack["hash_manifest"]["raw_file"]["sha256"]
    assert pack["acquisition_validation"]["gate_status"] == "pass"
    assert pack["official_eddypro_run"]["gate_status"] == "pass"
    assert pack["parity_artifact"] == "raw_to_final_parity.json"
    assert pack["acceptance_commands"]
    assert pack["acceptance_status"] == "not_run"


def test_run_official_raw_evidence_pack_acceptance_executes_safe_pytest(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    pack = build_official_raw_fixture_evidence_pack(
        bundle,
        workspace_root=tmp_path,
        parity_payload={"status": "pass", "pass_rate": 1.0, "failed_fields": []},
    )
    pack_path = tmp_path / "evidence_pack.json"
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    updated = run_official_raw_evidence_pack_acceptance(
        pack_path,
        workspace_root=tmp_path,
        commands=["python -m pytest tests/test_eddypro_capability_matrix.py::test_capability_matrix_schema_and_counts_are_consistent -q"],
        timeout_s=120.0,
    )
    persisted = json.loads(pack_path.read_text(encoding="utf-8"))

    assert updated["acceptance_status"] == "pass"
    assert updated["acceptance_gate_status"] == "pass"
    assert updated["status"] == "complete"
    assert updated["acceptance_run"]["artifact_type"] == "official_raw_evidence_pack_acceptance_run_v1"
    assert updated["acceptance_run"]["passed_count"] == 1
    assert updated["acceptance_results"][0]["exit_code"] == 0
    assert persisted["acceptance_status"] == "pass"


def test_run_official_raw_evidence_pack_acceptance_skips_unsafe_commands(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    pack = build_official_raw_fixture_evidence_pack(bundle, workspace_root=tmp_path)

    updated = run_official_raw_evidence_pack_acceptance(
        pack,
        workspace_root=tmp_path,
        commands=["cmd /c echo unsafe"],
        timeout_s=5.0,
    )

    assert updated["acceptance_status"] == "blocked_unsafe_commands"
    assert updated["acceptance_gate_status"] == "blocked"
    assert updated["acceptance_results"][0]["status"] == "skipped_unsafe"
    assert "only python -m pytest" in updated["acceptance_results"][0]["rejection_reason"]


def test_register_official_raw_fixture_bundle_writes_updated_pack(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    pack_path = tmp_path / "pack.json"
    output_path = tmp_path / "updated_pack.json"
    pack_path.write_text(
        json.dumps({"fixture_pack_id": "test_pack", "version": "1.0", "assets": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = register_official_raw_fixture_bundle(
        bundle_dir=bundle,
        pack_path=pack_path,
        output_path=output_path,
        workspace_root=tmp_path,
    )

    assert result["status"] == "registered"
    assert result["acquisition_validation"]["status"] == "ready_for_registration_pending_parity"
    updated = json.loads(output_path.read_text(encoding="utf-8"))
    assert updated["assets"][0]["fixture_id"] == "site_001_official"
    assert updated["assets"][0]["official_eddypro_output"] is True

    duplicate = register_official_raw_fixture_bundle(
        bundle_dir=bundle,
        pack_path=output_path,
        output_path=tmp_path / "duplicate.json",
        workspace_root=tmp_path,
    )
    assert duplicate["status"] == "duplicate_fixture_id"


def test_headless_cli_inspects_official_raw_fixture_bundle(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    output_path = tmp_path / "inspection.json"

    exit_code = run_cli(
        [
            "--inspect-official-raw-bundle",
            str(bundle),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["artifact_type"] == "official_raw_fixture_bundle_inspection_v1"
    assert payload["status"] == "ready_for_registration"
    assert payload["asset_preview"]["fixture_id"] == "site_001_official"


def test_headless_cli_validates_official_raw_fixture_acquisition(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    output_path = tmp_path / "acquisition_validation.json"

    exit_code = run_cli(
        [
            "--validate-official-raw-bundle",
            str(bundle),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["artifact_type"] == "official_raw_fixture_acquisition_validation_v1"
    assert payload["status"] == "ready_for_registration_pending_parity"
    assert "raw_to_final_parity_pass" in payload["missing_requirements"]


def test_headless_cli_builds_official_raw_fixture_evidence_pack(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    output_path = tmp_path / "evidence_pack.json"

    exit_code = run_cli(
        [
            "--build-official-raw-evidence-pack",
            str(bundle),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["artifact_type"] == "official_raw_fixture_evidence_pack_v1"
    assert payload["status"] == "pending_closure"
    assert payload["hash_manifest"]["official_full_output"]["sha256"]
    assert payload["acceptance_status"] == "not_run"


def test_headless_cli_runs_official_raw_evidence_acceptance(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    pack = build_official_raw_fixture_evidence_pack(
        bundle,
        workspace_root=tmp_path,
        parity_payload={"status": "pass", "pass_rate": 1.0, "failed_fields": []},
    )
    pack["acceptance_commands"] = [
        "python -m pytest tests/test_eddypro_capability_matrix.py::test_capability_matrix_sources_are_official_licor_urls -q"
    ]
    pack_path = tmp_path / "evidence_pack.json"
    output_path = tmp_path / "accepted_evidence_pack.json"
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    exit_code = run_cli(
        [
            "--run-official-raw-evidence-acceptance",
            str(pack_path),
            "--workspace-root",
            str(tmp_path),
            "--acceptance-timeout-s",
            "120",
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["acceptance_status"] == "pass"
    assert payload["acceptance_run"]["command_count"] == 1
    assert payload["acceptance_results"][0]["status"] == "pass"


def test_headless_cli_captures_official_eddypro_run_sidecar(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="cli_capture_site",
        raw_name="cli_capture_site.ghg",
        write_manifest=False,
    )
    output_file = bundle / "eddypro" / "eddypro_full_output.csv"
    output_file.unlink()
    fake_eddypro = tmp_path / "fake_eddypro_cli.py"
    fake_eddypro.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text('TIMESTAMP_START,TIMESTAMP_END,FC,FC_QC\\n202604180900,202604180930,3.45,0\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "official_run_capture.json"

    exit_code = run_cli(
        [
            "--capture-official-eddypro-run",
            str(bundle),
            "--official-run-command",
            f'"{sys.executable}" "{fake_eddypro}" "{output_file}"',
            "--official-run-software-version",
            "7.0.9",
            "--official-run-executable",
            str(fake_eddypro),
            "--official-run-project-file",
            "eddypro/project.eddypro",
            "--official-run-output-files",
            "eddypro/eddypro_full_output.csv",
            "--official-run-timeout-s",
            "30",
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    sidecar = json.loads((bundle / "official_eddypro_run.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["artifact_type"] == "official_eddypro_run_capture_v1"
    assert payload["gate_status"] == "pass"
    assert sidecar["capture_status"] == "pass"
    assert sidecar["validation"]["gate_status"] == "pass"


def test_headless_cli_builds_official_eddypro_executable_readiness(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, folder_name="cli_readiness_site", include_official_run=False)
    output_path = tmp_path / "eddypro_executable_readiness.json"

    exit_code = run_cli(
        [
            "--build-official-eddypro-executable-readiness",
            str(bundle),
            "--official-run-executable",
            sys.executable,
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "ready_to_capture"
    assert payload["selected_executable"]["path"] == sys.executable


def test_headless_cli_builds_official_raw_fixture_manifest(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path, folder_name="cli_manifestless", raw_name="cli_manifestless.slt", write_manifest=False)
    output_path = tmp_path / "manifest_build.json"

    exit_code = run_cli(
        [
            "--build-official-raw-bundle-manifest",
            str(bundle),
            "--bundle-fixture-id",
            "cli_manifestless_official",
            "--bundle-site-class",
            "cli_auto_site",
            "--bundle-software-version",
            "7.0.9",
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "manifest_ready"
    assert manifest["fixture_id"] == "cli_manifestless_official"
    assert manifest["site_class"] == "cli_auto_site"
    assert manifest["files"]["raw_file"] == "raw/cli_manifestless.slt"


def test_headless_cli_builds_official_raw_fixture_manifest_tree(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    bundle = _write_ready_bundle(
        tmp_path,
        folder_name="cli_tree_manifestless",
        raw_name="cli_tree_manifestless.csv",
        write_manifest=False,
        write_normalized=False,
    )
    (bundle / "raw" / "cli_tree_manifestless.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")
    output_path = tmp_path / "manifest_tree_build.json"

    exit_code = run_cli(
        [
            "--build-official-raw-bundle-manifests",
            str(root),
            "--bundle-site-class",
            "cli_tree_site",
            "--bundle-software-version",
            "7.0.9",
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "ready"
    assert payload["generated_count"] == 1
    assert manifest["site_class"] == "cli_tree_site"
    assert manifest["normalization_result"]["status"] == "normalized"


def test_headless_cli_registers_official_raw_fixture_bundle(tmp_path: Path) -> None:
    bundle = _write_ready_bundle(tmp_path)
    pack_path = tmp_path / "pack.json"
    output_path = tmp_path / "updated_pack.json"
    pack_path.write_text(
        json.dumps({"fixture_pack_id": "test_pack", "version": "1.0", "assets": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = run_cli(
        [
            "--register-official-raw-bundle",
            str(bundle),
            "--fixture-pack",
            str(pack_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    updated = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert updated["assets"][0]["fixture_id"] == "site_001_official"
    assert updated["assets"][0]["official_eddypro_output"] is True


def test_discover_official_raw_fixture_bundles_builds_evidence_matrix(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001", raw_name="site_001.ghg")
    _write_ready_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.tob1", site_class="grassland")
    incomplete = root / "site_003_incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "official_raw_fixture_bundle.json").write_text(
        json.dumps({"fixture_id": "site_003_incomplete", "files": {"raw_file": "raw.csv"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    discovery = discover_official_raw_fixture_bundles(root, workspace_root=tmp_path)

    assert discovery["artifact_type"] == "official_raw_fixture_bundle_discovery_v1"
    assert discovery["bundle_count"] == 3
    assert discovery["ready_count"] == 2
    assert discovery["status_counts"]["ready_for_registration"] == 2
    assert discovery["status_counts"]["incomplete"] == 1
    matrix = discovery["evidence_matrix"]
    assert matrix["row_count"] == 3
    assert matrix["raw_format_counts"]["ghg"] == 1
    assert matrix["raw_format_counts"]["tob1"] == 1
    assert matrix["site_class_counts"]["grassland"] == 1
    assert matrix["official_eddypro_run_gate_counts"]["pass"] == 2
    assert matrix["official_eddypro_run_gate_counts"]["blocked"] == 1
    assert discovery["repair_plan"]["artifact_type"] == "official_raw_fixture_repair_plan_v1"
    assert discovery["repair_plan"]["status"] == "needs_repair"
    assert discovery["repair_plan"]["repair_item_count"] == 1
    assert discovery["repair_plan"]["missing_requirement_counts"]["official_eddypro_run manifest section"] == 1
    assert any(row["fixture_id"] == "site_003_incomplete" and row["status"] == "incomplete" for row in matrix["rows"])


def test_build_official_raw_fixture_repair_plan_lists_sidecar_templates(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001")
    _write_ready_bundle(tmp_path, fixture_id="site_002_missing_run", folder_name="site_002", include_official_run=False)
    incomplete = root / "site_003_incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "official_raw_fixture_bundle.json").write_text(
        json.dumps({"fixture_id": "site_003_incomplete", "files": {"raw_file": "raw.csv"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    plan = build_official_raw_fixture_repair_plan(root, workspace_root=tmp_path)

    assert plan["artifact_type"] == "official_raw_fixture_repair_plan_v1"
    assert plan["status"] == "needs_repair"
    assert plan["bundle_count"] == 3
    assert plan["ready_for_registration_count"] == 1
    assert plan["repair_item_count"] == 2
    assert plan["official_eddypro_run_pass_count"] == 1
    assert "official_eddypro_run.json" in plan["accepted_sidecar_filenames"]
    missing_run = next(item for item in plan["repair_items"] if item["fixture_id"] == "site_002_missing_run")
    assert missing_run["repair_status"] == "needs_operator_evidence"
    assert missing_run["sidecar_template"]["exit_code"] == 0
    assert any("official_eddypro_run.json" in action for action in missing_run["next_actions"])


def test_register_official_raw_fixture_bundle_batch_writes_updated_pack(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001")
    _write_ready_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.csv", site_class="cropland")
    pack_path = tmp_path / "pack.json"
    output_path = tmp_path / "updated_pack.json"
    pack_path.write_text(
        json.dumps({"fixture_pack_id": "test_pack", "version": "1.0", "assets": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = register_official_raw_fixture_bundle_batch(
        bundle_root=root,
        pack_path=pack_path,
        output_path=output_path,
        workspace_root=tmp_path,
    )

    assert result["status"] == "registered"
    assert result["registered_count"] == 2
    assert result["evidence_matrix"]["raw_format_counts"]["csv"] == 1
    updated = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {asset["fixture_id"] for asset in updated["assets"]}
    assert ids == {"site_001_official", "site_002_official"}


def test_build_official_raw_bundle_manifest_batch_generates_manifestless_tree(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    site_001 = _write_ready_bundle(
        tmp_path,
        fixture_id="site_001_official",
        folder_name="site_001",
        raw_name="site_001.csv",
        write_manifest=False,
        write_normalized=False,
    )
    site_002 = _write_ready_bundle(
        tmp_path,
        fixture_id="site_002_official",
        folder_name="site_002",
        raw_name="site_002.csv",
        write_manifest=False,
        write_normalized=False,
    )
    (site_001 / "raw" / "site_001.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")
    (site_002 / "raw" / "site_002.csv").write_text("timestamp,u,v,w,co2,h2o,p,ta\n", encoding="utf-8")

    result = build_official_raw_fixture_bundle_manifest_batch(
        root,
        site_class="auto_tree",
        software_version="7.0.9",
        workspace_root=tmp_path,
    )
    discovery = discover_official_raw_fixture_bundles(root, workspace_root=tmp_path)

    assert result["artifact_type"] == "official_raw_fixture_bundle_manifest_batch_build_v1"
    assert result["status"] == "ready"
    assert result["candidate_count"] == 2
    assert result["generated_count"] == 2
    assert result["ready_count"] == 2
    assert discovery["ready_count"] == 2
    for bundle in (site_001, site_002):
        manifest = json.loads((bundle / "official_raw_fixture_bundle.json").read_text(encoding="utf-8"))
        assert manifest["files"]["reference_json"] == "normalized/reference.json"
        assert manifest["files"]["provenance_json"] == "normalized/provenance.json"
        assert manifest["normalization_result"]["status"] == "normalized"
        assert (bundle / "normalized" / "reference.json").exists()
        assert (bundle / "normalized" / "provenance.json").exists()


def test_headless_cli_inspects_official_raw_fixture_bundle_tree(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001")
    _write_ready_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.slt")
    output_path = tmp_path / "discovery.json"

    exit_code = run_cli(
        [
            "--inspect-official-raw-bundles",
            str(root),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["bundle_count"] == 2
    assert payload["evidence_matrix"]["raw_format_counts"]["slt"] == 1


def test_headless_cli_builds_official_raw_repair_plan(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001")
    _write_ready_bundle(tmp_path, fixture_id="site_002_missing_run", folder_name="site_002", include_official_run=False)
    output_path = tmp_path / "repair_plan.json"

    exit_code = run_cli(
        [
            "--build-official-raw-repair-plan",
            str(root),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["artifact_type"] == "official_raw_fixture_repair_plan_v1"
    assert payload["repair_item_count"] == 1
    assert payload["repair_items"][0]["fixture_id"] == "site_002_missing_run"
    assert "official_eddypro_run.json" in payload["repair_items"][0]["accepted_sidecar_filenames"]


def test_headless_cli_registers_official_raw_fixture_bundle_tree(tmp_path: Path) -> None:
    root = tmp_path / "references" / "eddypro" / "official_raw"
    _write_ready_bundle(tmp_path, fixture_id="site_001_official", folder_name="site_001")
    _write_ready_bundle(tmp_path, fixture_id="site_002_official", folder_name="site_002", raw_name="site_002.csv")
    pack_path = tmp_path / "pack.json"
    output_path = tmp_path / "updated_pack.json"
    pack_path.write_text(
        json.dumps({"fixture_pack_id": "test_pack", "version": "1.0", "assets": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exit_code = run_cli(
        [
            "--register-official-raw-bundles",
            str(root),
            "--fixture-pack",
            str(pack_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    updated = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert {asset["fixture_id"] for asset in updated["assets"]} == {"site_001_official", "site_002_official"}
