# Public EC Data Discovery

Updated: 2026-06-01

This page records the current status of public real eddy-covariance data that could eventually replace source-derived parity closures with direct raw-to-final evidence.

Machine-readable ledger: `references/eddypro/public_raw_search/ec_public_data_sources.json`.

## Current Verdict

New real-data candidates exist, but they are not yet registered EddyPro parity fixtures.

- LI-COR EddyPro sample data is already materialized locally and is the current accepted official raw anchor.
- NEON DP4.00200.001 can return public EC HDF5 metadata and a Google Storage HDF5 URL without account registration.
- ICOS Raw ASCII object pages are discoverable, but repeatable programmatic download still needs an accepted licence/authenticated flow.
- AmeriFlux/FLUXNET remains useful for processed flux validation, not as a complete high-frequency raw plus EddyPro Full_Output parity pair by default.

## Verified This Round

NEON API probe:

```text
GET https://data.neonscience.org/api/v0/data/query?productCode=DP4.00200.001&siteCode=HARV&startDateMonth=2023-07&endDateMonth=2023-07&release=RELEASE-2025&includeProvisional=false
```

Result: HTTP 200, with one HDF5 candidate. A HEAD request to the returned Google Storage URL also returned HTTP 200:

```text
NEON.D01.HARV.DP4.00200.001.nsae.2023-07.basic.20250122T131642Z.h5
size_bytes=156344090
md5=02c7e93f6f8f7309915831c8306ab8c4
head_content_type=application/octet-stream
```

ICOS probe:

```text
GET https://meta.icos-cp.eu/objects/QGFJjyiRVSqOvwQA_jaNIW2D
```

Result: HTTP 200 and a Raw ASCII landing page. The licence URL also returned HTTP 200, but the noninteractive `licence_accept` request redirected back to the licence form, so no repeatable direct download was registered in this run.

## Registration Status

The only currently successful local raw-to-final registration remains the LI-COR public EddyPro sample-data anchor. NEON and ICOS are newly useful candidates, but they still need download, hash validation, metadata mapping, importer support, and either official EddyPro output or a clearly scoped validation target before they can affect `can_release_full_eddypro_parity`.

## Headless Probe Artifact

The source ledger can now be converted into a repeatable probe artifact without registering a parity fixture:

```powershell
@'
from core.headless_batch_runner import run_cli

raise SystemExit(run_cli([
    "--build-public-ec-data-discovery",
    "--workspace-root", ".",
    "--output", "artifacts/public_ec_data/public_ec_data_discovery_probe.json",
    "--public-ec-sample-bytes", "4096",
]))
'@ | python -
```

For CI or documentation checks that must not touch the network, add `--skip-public-ec-network`. The probe records the source ledger path, provider status, NEON API/HDF5 HEAD verification, optional byte-range sample metadata, ICOS licence-flow status, and `can_change_full_parity_gate=false`.

## NEON HDF5 Metadata Smoke

After a probe artifact verifies the NEON HDF5 candidate, the file can be downloaded into ignored local artifacts and inspected for EC field candidates:

```powershell
@'
from core.headless_batch_runner import run_cli

raise SystemExit(run_cli([
    "--download-neon-hdf5-candidate",
    "artifacts/public_ec_data/public_ec_data_discovery_probe.json",
    "--workspace-root", ".",
    "--output", "artifacts/public_ec_data/neon_hdf5_download.json",
    "--neon-hdf5-output-root", "artifacts/public_ec_data/neon",
]))
'@ | python -
```

Then run the metadata smoke on the downloaded `local_path`:

```powershell
@'
import json
from pathlib import Path
from core.headless_batch_runner import run_cli

download = json.loads(Path("artifacts/public_ec_data/neon_hdf5_download.json").read_text(encoding="utf-8"))
raise SystemExit(run_cli([
    "--build-neon-hdf5-metadata-smoke",
    download["local_path"],
    "--workspace-root", ".",
    "--output", "artifacts/public_ec_data/neon_hdf5_metadata_smoke.json",
    "--neon-hdf5-discovery-artifact", "artifacts/public_ec_data/public_ec_data_discovery_probe.json",
    "--neon-hdf5-source-id", download["source_id"],
]))
'@ | python -
```

The smoke artifact records HDF5 readability, file hashes, group/dataset counts, root/dataset attributes, inferred canonical EC field mappings, missing fields, known limitations, and `ready_for_raw_to_final_registration=false`.

## Truthfulness Boundary

Public discovery is not parity. A candidate becomes full-parity evidence only after it has:

- Redistributable raw input.
- EddyPro project/settings or a rigorously documented equivalent mapping.
- Official EddyPro output or a declared validation target.
- Normalized reference and provenance.
- Passing raw-to-final parity artifact.
- Accepted evidence-pack commands.

Until then, the project may claim source-derived functional parity only, not official field numeric parity.
