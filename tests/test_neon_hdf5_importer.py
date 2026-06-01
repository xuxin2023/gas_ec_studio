from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from core.comparison import neon_hdf5_importer
from core.comparison.neon_hdf5_importer import (
    build_neon_hdf5_metadata_smoke,
    download_neon_hdf5_candidate,
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
    assert payload["field_mappings"]["co2"]["path"].endswith("/densMoleCo2")
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


def _write_neon_compound_alias_hdf5(path: Path) -> Path:
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
    rows = np.zeros(4, dtype=dtype)
    rows["timeBgn"] = b"2023-07-01T00:00:00.000Z"
    rows["timeEnd"] = b"2023-07-01T00:00:00.100Z"
    with h5py.File(path, "w") as hdf:
        soni = hdf.create_group("HARV/dp01/data/soni/000_060_01m")
        soni.create_dataset("veloXaxsErth", data=rows)
        soni.create_dataset("veloYaxsErth", data=rows)
        soni.create_dataset("veloZaxsErth", data=rows)
        soni.create_dataset("tempSoni", data=rows)
        co2 = hdf.create_group("HARV/dp01/data/co2Turb/000_060_01m")
        co2.create_dataset("densMoleCo2", data=rows)
        h2o = hdf.create_group("HARV/dp01/data/h2oTurb/000_060_01m")
        h2o.create_dataset("rtioMoleWetH2o", data=rows)
    return path
