from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.comparison import public_ec_data_discovery
from core.comparison.public_ec_data_discovery import build_public_ec_data_discovery_probe
from core.headless_batch_runner import run_cli


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
    assert payload["summary"]["can_change_full_parity_gate"] is False


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
    raise AssertionError(f"unexpected URL: {url}")
