from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from core.comparison import neon_hdf5_importer
from core.comparison.neon_hdf5_importer import (
    build_neon_hdf5_fixture_profile,
    build_neon_hdf5_metadata_smoke,
    build_neon_hdf5_row_extraction_smoke,
    build_neon_hdf5_validation_package,
    download_neon_hdf5_candidate,
    row_records_to_normalized_frames,
)
from core.headless_batch_runner import run_cli


def test_neon_hdf5_metadata_smoke_infers_ec_field_mapping(tmp_path: Path) -> None:
    hdf5_path = _write_neon_like_hdf5(tmp_path / "neon_like.h5")

    payload = build_neon_hdf5_metadata_smoke(
        hdf5_path,
        workspace_root=tmp_path,
        source_id="neon_test",
        source_discovery_artifact=tmp_path / "discovery.json",
    )

    assert payload["artifact_type"] == "neon_hdf5_metadata_smoke_v1"
    assert payload["status"] == "mapping_ready_for_importer_smoke"
    assert payload["source_id"] == "neon_test"
    assert payload["hdf5_summary"]["dataset_count"] >= 7
    assert payload["canonical_field_coverage"]["missing_required_fields"] == []
    assert payload["field_mappings"]["time"]["path"] == "/dp01/data/time"
    assert payload["field_mappings"]["u"]["path"] == "/dp01/data/wind/u"
    assert payload["field_mappings"]["w"]["path"] == "/dp01/data/wind/w"
    assert payload["field_mappings"]["co2"]["path"] == "/dp01/data/gases/co2_mol_m3"
    assert payload["importer_smoke"]["can_open_hdf5"] is True
    assert payload["importer_smoke"]["can_change_full_parity_gate"] is False


def test_headless_cli_builds_neon_hdf5_metadata_smoke(tmp_path: Path) -> None:
    hdf5_path = _write_neon_like_hdf5(tmp_path / "neon_cli.h5")
    output = tmp_path / "neon_hdf5_metadata_smoke.json"

    code = run_cli(
        [
            "--build-neon-hdf5-metadata-smoke",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
            "--neon-hdf5-source-id",
            "neon_cli",
            "--neon-hdf5-max-datasets",
            "20",
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["status"] == "mapping_ready_for_importer_smoke"
    assert payload["field_mappings"]["h2o"]["path"] == "/dp01/data/gases/h2o_mol_m3"
    assert payload["importer_smoke"]["ready_for_raw_to_final_registration"] is False


def test_neon_hdf5_metadata_smoke_detects_neon_sonic_compound_aliases(tmp_path: Path) -> None:
    hdf5_path = _write_neon_compound_alias_hdf5(tmp_path / "neon_compound.h5")

    payload = build_neon_hdf5_metadata_smoke(hdf5_path, workspace_root=tmp_path, max_datasets=2)

    assert payload["status"] == "mapping_ready_for_importer_smoke"
    assert payload["hdf5_summary"]["dataset_truncated"] is True
    assert payload["field_mappings"]["time"]["reason"] == "compound dataset dtype contains timeBgn/timeEnd fields"
    assert payload["field_mappings"]["u"]["path"].endswith("/veloXaxsErth")
    assert payload["field_mappings"]["v"]["path"].endswith("/veloYaxsErth")
    assert payload["field_mappings"]["w"]["path"].endswith("/veloZaxsErth")
    assert payload["field_mappings"]["sonic_temperature"]["path"].endswith("/tempSoni")
    assert payload["field_mappings"]["co2"]["path"].endswith("/rtioMoleDryCo2")
    assert payload["field_mappings"]["co2"]["confidence"] > 0.9


def test_neon_hdf5_candidate_download_validates_provider_md5(monkeypatch, tmp_path: Path) -> None:
    hdf5_path = _write_neon_like_hdf5(tmp_path / "download_source.h5")
    hdf5_bytes = hdf5_path.read_bytes()
    manifest = tmp_path / "public_ec_probe.json"
    manifest.write_text(
        json.dumps(
            {
                "artifact_type": "public_ec_data_discovery_probe_v1",
                "sources": [
                    {
                        "source_id": "neon_test",
                        "provider": "NEON",
                        "candidate_files": [
                            {
                                "name": "NEON.TEST.DP4.00200.001.nsae.2023-07.basic.h5",
                                "size_bytes": len(hdf5_bytes),
                                "md5": hashlib.md5(hdf5_bytes).hexdigest(),  # noqa: S324
                                "url": "https://example.test/neon.h5",
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(neon_hdf5_importer, "urlopen", lambda request, timeout=0: _FakeResponse(hdf5_bytes))

    download = download_neon_hdf5_candidate(
        manifest,
        workspace_root=tmp_path,
        output_root=tmp_path / "downloads",
        source_id="neon_test",
    )
    smoke = build_neon_hdf5_metadata_smoke(download["local_path"], workspace_root=tmp_path)

    assert download["status"] == "pass"
    assert download["action"] == "downloaded"
    assert Path(download["local_path"]).exists()
    assert download["md5"] == hashlib.md5(hdf5_bytes).hexdigest()  # noqa: S324
    assert smoke["status"] == "mapping_ready_for_importer_smoke"


def test_neon_hdf5_row_extraction_smoke_writes_normalized_rows(tmp_path: Path) -> None:
    hdf5_path = _write_neon_compound_alias_hdf5(tmp_path / "neon_rows.h5", rows=96)
    rows_path = tmp_path / "neon_rows.json"

    payload = build_neon_hdf5_row_extraction_smoke(
        hdf5_path,
        workspace_root=tmp_path,
        rows_output_path=rows_path,
        max_rows=80,
        include_row_records=True,
    )
    frames = row_records_to_normalized_frames(list(payload["row_records"]))

    assert payload["artifact_type"] == "neon_hdf5_row_extraction_smoke_v1"
    assert payload["status"] == "pass"
    assert payload["row_count"] == 80
    assert payload["rp_smoke_ready"] is True
    assert payload["estimated_sample_rate_hz"] == 0.01666667
    assert payload["qc_mapping"]["u"]["status"] == "mapped"
    assert payload["qc_flag_summary"]["u"]["matched_flag_count"] == 80
    assert payload["qc_flag_summary"]["u"]["flag_counts"] == {"0": 80}
    assert payload["units_conversion_audit"]["co2"]["conversion_rule"] == "identity_umol_mol_to_ppm"
    assert payload["variable_context"]["co2"]["product_family"] == "co2Turb"
    assert payload["variable_context"]["co2"]["height_m"] == 1.0
    assert payload["alignment_summary"]["mixed_averaging_intervals"] is False
    assert rows_path.exists()
    assert frames[0].co2_ppm is not None and frames[0].co2_ppm > 390.0
    assert frames[0].h2o_mmol is not None and frames[0].h2o_mmol > 9.0
    assert frames[0].pressure_kpa == 101.3
    assert '"w"' in frames[0].raw_text
    assert payload["ready_for_raw_to_final_registration"] is False


def test_headless_cli_runs_neon_hdf5_rp_smoke(tmp_path: Path) -> None:
    hdf5_path = _write_neon_compound_alias_hdf5(tmp_path / "neon_rp.h5", rows=140)
    output = tmp_path / "neon_rp_smoke.json"

    code = run_cli(
        [
            "--run-neon-hdf5-rp-smoke",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
            "--neon-hdf5-max-rows",
            "130",
            "--neon-hdf5-rp-block-minutes",
            "64",
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifact_type"] == "neon_hdf5_rp_smoke_v1"
    assert payload["status"] == "pass"
    assert payload["window_count"] >= 1
    assert payload["row_smoke"]["row_count"] == 130
    assert payload["can_change_full_parity_gate"] is False


def test_neon_hdf5_validation_package_closes_metadata_row_and_rp_smoke(tmp_path: Path) -> None:
    hdf5_path = _write_neon_compound_alias_hdf5(tmp_path / "neon_validation.h5", rows=150)
    metadata_path = tmp_path / "metadata.json"
    row_path = tmp_path / "row.json"
    rp_path = tmp_path / "rp.json"
    package_path = tmp_path / "validation_package.json"

    assert run_cli(
        [
            "--build-neon-hdf5-metadata-smoke",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(metadata_path),
        ]
    ) == 0
    assert run_cli(
        [
            "--build-neon-hdf5-row-smoke",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(row_path),
            "--neon-hdf5-metadata-smoke",
            str(metadata_path),
            "--neon-hdf5-max-rows",
            "120",
        ]
    ) == 0
    assert run_cli(
        [
            "--run-neon-hdf5-rp-smoke",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(rp_path),
            "--neon-hdf5-metadata-smoke",
            str(metadata_path),
            "--neon-hdf5-max-rows",
            "120",
        ]
    ) == 0
    code = run_cli(
        [
            "--build-neon-hdf5-validation-package",
            str(hdf5_path),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(package_path),
            "--neon-hdf5-metadata-smoke",
            str(metadata_path),
            "--neon-hdf5-row-smoke",
            str(row_path),
            "--neon-hdf5-rp-smoke",
            str(rp_path),
        ]
    )
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    direct_payload = build_neon_hdf5_validation_package(
        hdf5_path,
        workspace_root=tmp_path,
        metadata_smoke_path=metadata_path,
        row_smoke_path=row_path,
        rp_smoke_path=rp_path,
    )

    assert code == 0
    assert payload["artifact_type"] == "neon_hdf5_validation_package_v1"
    assert payload["status"] == "pass"
    assert payload["metadata_status"] == "mapping_ready_for_importer_smoke"
    assert payload["row_status"] == "pass"
    assert payload["rp_status"] == "pass"
    assert payload["claim_boundary"]["can_claim_neon_engineering_validation"] is True
    assert payload["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["qc_flag_summary"]["u"]["flag_counts"] == {"0": 120}
    assert payload["units_conversion_audit"]["h2o"]["conversion_rule"] == "identity_mmol_mol"
    assert payload["variable_context"]["u"]["product_family"] == "soni"
    assert direct_payload["status"] == "pass"


def test_neon_hdf5_fixture_profile_keeps_official_parity_blocked(tmp_path: Path) -> None:
    validation_path = tmp_path / "validation.json"
    download_path = tmp_path / "download.json"
    runbook_path = tmp_path / "runbook.json"
    validation_payload = {
        "artifact_type": "neon_hdf5_validation_package_v1",
        "status": "pass",
        "source_id": "neon_dp4_test",
        "source_file": "NEON.TEST.h5",
        "row_count": 120,
        "rp_window_count": 1,
        "row_estimated_sample_rate_hz": 0.01666667,
        "field_mappings": {"u": {"path": "/soni/u"}, "co2": {"path": "/co2/rtioMoleDryCo2"}},
        "field_units": {"u": "m s-1", "co2": "umolCo2 mol-1"},
        "qc_mapping": {"u": {"status": "mapped"}},
        "claim_boundary": {
            "can_claim_neon_engineering_validation": True,
            "can_claim_eddypro_raw_to_final_parity": False,
        },
        "known_limitations": ["NEON DP4 HDF5 variables are aggregated products."],
    }
    download_payload = {
        "artifact_type": "neon_hdf5_candidate_download_v1",
        "status": "pass",
        "source_id": "neon_dp4_test",
        "candidate_name": "NEON.TEST.DP4.00200.001.h5",
        "candidate_url": "https://example.test/neon.h5",
    }
    runbook_payload = {
        "artifact_type": "public_ec_acquisition_runbook_v1",
        "status": "engineering_validated_registration_pending",
        "actions": [
            {
                "source_id": "neon_dp4_test",
                "provider": "NEON",
                "acquisition_status": "public_download_engineering_validated",
                "automation_state": "engineering_validated_registration_pending",
            }
        ],
    }
    validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    download_path.write_text(json.dumps(download_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    runbook_path.write_text(json.dumps(runbook_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = build_neon_hdf5_fixture_profile(
        validation_package_path=validation_path,
        download_path=download_path,
        acquisition_runbook_path=runbook_path,
        workspace_root=tmp_path,
    )

    assert payload["artifact_type"] == "neon_hdf5_fixture_profile_v1"
    assert payload["status"] == "engineering_fixture_ready_official_parity_blocked"
    assert payload["registration_profile"]["can_register_as_public_engineering_fixture"] is True
    assert payload["registration_profile"]["can_register_as_official_eddypro_raw_to_final_fixture"] is False
    assert "official_eddypro_full_output" in payload["registration_profile"]["missing_for_official_eddypro_parity"]
    assert payload["claim_boundary"]["can_claim_public_raw_engineering_validation"] is True
    assert payload["claim_boundary"]["can_claim_eddypro_raw_to_final_parity"] is False
    assert payload["candidate_name"] == "NEON.TEST.DP4.00200.001.h5"


def test_headless_cli_builds_neon_hdf5_fixture_profile(tmp_path: Path) -> None:
    validation_path = tmp_path / "validation.json"
    output = tmp_path / "fixture_profile.json"
    validation_path.write_text(
        json.dumps(
            {
                "artifact_type": "neon_hdf5_validation_package_v1",
                "status": "pass",
                "source_id": "neon_cli_profile",
                "source_file": "NEON.CLI.h5",
                "row_count": 80,
                "claim_boundary": {"can_claim_neon_engineering_validation": True},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    code = run_cli(
        [
            "--build-neon-hdf5-fixture-profile",
            "--workspace-root",
            str(tmp_path),
            "--neon-hdf5-validation-package",
            str(validation_path),
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["artifact_type"] == "neon_hdf5_fixture_profile_v1"
    assert payload["source_id"] == "neon_cli_profile"
    assert payload["claim_boundary"]["can_change_full_parity_gate"] is False


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.status = 200

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


def _write_neon_like_hdf5(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as hdf:
        hdf.attrs["source"] = "NEON DP4.00200.001 synthetic layout smoke"
        data = hdf.create_group("dp01/data")
        time = data.create_dataset("time", data=[0, 100, 200, 300])
        time.attrs["units"] = "milliseconds since 2023-07-01T00:00:00Z"
        wind = data.create_group("wind")
        u = wind.create_dataset("u", data=[1.0, 1.1, 1.2, 1.3])
        u.attrs["units"] = "m s-1"
        u.attrs["long_name"] = "u wind component"
        v = wind.create_dataset("v", data=[0.1, 0.2, 0.3, 0.4])
        v.attrs["units"] = "m s-1"
        v.attrs["long_name"] = "v wind component"
        w = wind.create_dataset("w", data=[0.01, 0.02, 0.03, 0.04])
        w.attrs["units"] = "m s-1"
        w.attrs["long_name"] = "vertical wind component"
        gases = data.create_group("gases")
        co2 = gases.create_dataset("co2_mol_m3", data=[16.1, 16.2, 16.3, 16.4])
        co2.attrs["units"] = "mmol m-3"
        co2.attrs["long_name"] = "carbon dioxide concentration"
        h2o = gases.create_dataset("h2o_mol_m3", data=[410.1, 410.2, 410.3, 410.4])
        h2o.attrs["units"] = "mmol m-3"
        h2o.attrs["long_name"] = "water vapor concentration"
        temp = data.create_group("temperature")
        sonic = temp.create_dataset("sonic_temperature", data=[289.1, 289.2, 289.3, 289.4])
        sonic.attrs["units"] = "K"
        sonic.attrs["long_name"] = "sonic temperature"
        qc = data.create_group("qc")
        qc.create_dataset("quality_flags", data=[0, 0, 1, 0])
    return path


def _write_neon_compound_alias_hdf5(path: Path, *, rows: int = 4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dtype = np.dtype(
        [
            ("mean", "<f8"),
            ("min", "<f8"),
            ("max", "<f8"),
            ("vari", "<f8"),
            ("numSamp", "<f8"),
            ("timeBgn", "S24"),
            ("timeEnd", "S24"),
        ]
    )
    data = np.zeros(rows, dtype=dtype)
    for index in range(rows):
        minute = index % 60
        hour = index // 60
        data["timeBgn"][index] = f"2023-07-01T{hour:02d}:{minute:02d}:00.000Z".encode("ascii")
        data["timeEnd"][index] = f"2023-07-01T{hour:02d}:{minute:02d}:59.950Z".encode("ascii")
        data["mean"][index] = float(index)
        data["min"][index] = float(index) - 0.1
        data["max"][index] = float(index) + 0.1
        data["vari"][index] = 0.01
        data["numSamp"][index] = 1200.0
    with h5py.File(path, "w") as hdf:
        soni = hdf.create_group("HARV/dp01/data/soni/000_060_01m")
        velo_x = data.copy()
        velo_x["mean"] = 1.2 + 0.05 * np.sin(np.arange(rows) / 8.0)
        velo_y = data.copy()
        velo_y["mean"] = 0.4 + 0.04 * np.cos(np.arange(rows) / 9.0)
        velo_z = data.copy()
        velo_z["mean"] = 0.15 * np.sin(np.arange(rows) / 5.0)
        temp_soni = data.copy()
        temp_soni["mean"] = 22.0 + 0.2 * np.cos(np.arange(rows) / 24.0)
        for name, values, unit in [
            ("veloXaxsErth", velo_x, "m s-1"),
            ("veloYaxsErth", velo_y, "m s-1"),
            ("veloZaxsErth", velo_z, "m s-1"),
            ("tempSoni", temp_soni, "C"),
        ]:
            dataset = soni.create_dataset(name, data=values)
            dataset.attrs["unit"] = np.array([unit, unit, unit, unit, "NA", "NA", "NA"], dtype="S12")
        co2 = hdf.create_group("HARV/dp01/data/co2Turb/000_060_01m")
        co2_values = data.copy()
        co2_values["mean"] = 410.0 + 8.0 * np.sin(np.arange(rows) / 5.0)
        co2_dataset = co2.create_dataset("rtioMoleDryCo2", data=co2_values)
        co2_dataset.attrs["unit"] = np.array(["umolCo2 mol-1", "umolCo2 mol-1", "umolCo2 mol-1", "umol2Co2 mol-2", "NA", "NA", "NA"], dtype="S18")
        h2o = hdf.create_group("HARV/dp01/data/h2oTurb/000_060_01m")
        h2o_values = data.copy()
        h2o_values["mean"] = 12.0 + 1.1 * np.cos(np.arange(rows) / 7.0)
        h2o_dataset = h2o.create_dataset("rtioMoleWetH2o", data=h2o_values)
        h2o_dataset.attrs["unit"] = np.array(["mmolH2o mol-1", "mmolH2o mol-1", "mmolH2o mol-1", "mmol2H2o mol-2", "NA", "NA", "NA"], dtype="S18")
        pressure = hdf.create_group("HARV/dp01/data/presBaro/000_060_01m")
        pressure_values = data.copy()
        pressure_values["mean"] = 101.3
        pressure_dataset = pressure.create_dataset("presAtm", data=pressure_values)
        pressure_dataset.attrs["unit"] = np.array(["kPa", "kPa", "kPa", "kPa2", "NA", "NA", "NA"], dtype="S8")
        qf = hdf.create_group("HARV/dp01/qfqm/soni/000_060_01m")
        qf_dtype = np.dtype([("qfFinl", "<i4"), ("timeBgn", "S24"), ("timeEnd", "S24")])
        qf_values = np.zeros(rows, dtype=qf_dtype)
        qf_values["timeBgn"] = data["timeBgn"]
        qf_values["timeEnd"] = data["timeEnd"]
        for name in ["veloXaxsErth", "veloYaxsErth", "veloZaxsErth", "tempSoni"]:
            qf.create_dataset(name, data=qf_values)
    return path
