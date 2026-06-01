# Official Raw Fixture Bundle

This bundle format is the landing path for real EddyPro raw-to-final parity evidence.

## Directory Shape

Each official fixture bundle should contain `official_raw_fixture_bundle.json` plus the files it declares:

```json
{
  "fixture_id": "site_001_official",
  "site_class": "temperate_forest",
  "software": "EddyPro",
  "software_version": "7.0.9",
  "files": {
    "raw_file": "raw/site_001.ghg",
    "metadata_json": "metadata/site_001_metadata.json",
    "eddypro_project_file": "eddypro/project.eddypro",
    "official_full_output": "eddypro/eddypro_full_output.csv",
    "reference_json": "normalized/reference.json",
    "provenance_json": "normalized/provenance.json"
  },
  "import_plan": {},
  "rp_config": {},
  "thresholds": {},
  "known_limitations": []
}
```

## Required Evidence

- `high_frequency_raw_input`: `.ghg`, TOB1, SLT, native binary, or raw text input.
- `eddypro_project_or_settings_file`: EddyPro project/settings used to produce the official output.
- `official_eddypro_full_output`: official EddyPro output for the same raw input.
- `normalized_reference_json`: normalized reference windows used by the parity harness.
- `normalization_provenance`: command, time, QC mapping, and known limitations.

## Importer API

- `inspect_official_raw_fixture_bundle(bundle_dir)` checks completeness, hashes, inferred roles, registration readiness, and an `official_raw_import_plan_v1` draft.
- `validate_official_raw_fixture_acquisition(bundle_dir)` emits `official_raw_fixture_acquisition_validation_v1`, the P0 closure-gate checklist for raw input, EddyPro project/settings, official Full_Output, normalized reference/provenance, and registered raw-to-final parity.
- `build_official_raw_fixture_evidence_pack(bundle_dir)` emits `official_raw_fixture_evidence_pack_v1`, bundling source-file hashes, normalization provenance, acquisition validation, parity artifact links, closure snapshots, and acceptance commands without embedding large raw files.
- `run_official_raw_evidence_pack_acceptance(evidence_pack_json)` executes the evidence pack's safe pytest acceptance commands, records exit code/stdout/stderr tails, and writes `official_raw_evidence_pack_acceptance_run_v1` back into the pack as delivery-chain proof.
- `build_official_eddypro_executable_readiness(bundle_dir)` emits `official_eddypro_executable_readiness_v1`, inventorying local EddyPro executables, the official `eddypro-engine` checkout, Fortran/make toolchain availability, build commands, capture commands, and the exact blockers before `official_eddypro_run.json` can truthfully pass.
- `prepare_official_eddypro_project_for_capture(bundle_dir)` emits `official_eddypro_project_prepare_v1`, preserving the original EddyPro project/raw files while creating a reproducible `ini/raw_files/output/tmp` run home for the official engine. It records copied raw-file hashes, project path rewrites, and the recommended capture command/output glob.
- `build_official_raw_fixture_bundle_manifest(...)` now writes `import_plan` into generated manifests. When a bundle has EddyPro `Full_Output` but lacks `normalized/reference.json` and `normalized/provenance.json`, it generates both artifacts without modifying the original output file. The draft includes `metadata_draft`, `rp_config_draft`, raw input provenance, `raw_import_probe`, inference sources, and unresolved review items.
- `build_official_raw_fixture_bundle_manifest_batch(...)` scans a directory tree for candidate EddyPro raw bundles, builds missing manifests in batch, and generates missing normalized reference/provenance artifacts from each bundle's `Full_Output`.
- `discover_official_raw_fixture_bundles(bundle_root)` recursively finds bundle manifests and returns an evidence matrix by raw format, site class, software, status, and missing required files.
- `fixture_asset_from_official_raw_bundle(bundle_dir)` returns a `raw_to_final_parity` fixture asset only when all required evidence is present.
- `register_official_raw_fixture_bundle(...)` writes an updated fixture pack with duplicate-ID protection.
- `register_official_raw_fixture_bundle_batch(...)` registers every complete bundle under a directory tree into one fixture pack copy and reports skipped incomplete or duplicate fixtures.

## Import Plan Draft

`official_raw_import_plan_v1` is not a parity claim. It is an auditable operator draft inferred from raw files, EddyPro project/settings, normalized references, and Full Output timestamps. Manifest generation now also records an `official_raw_full_output_normalization_v1` result when it creates `normalized/reference.json` and `normalized/provenance.json`; the provenance artifact records the source Full_Output file, normalization time, command, QC mapping, method metadata availability, raw/unmapped columns, and known limitations. Existing normalized references are preserved rather than overwritten. When an operator-captured `official_eddypro_run` declares a separate executable-run Full_Output, the manifest also writes `normalized/official_eddypro_run_reference.json` and `normalized/official_eddypro_run_provenance.json` under `official_eddypro_run_output_normalization_v1`, preserving the embedded/original reference while making the reproduced EddyPro executable output independently auditable in inspection and evidence-pack artifacts. Existing manifests are not wholesale overwritten by default; if the file roles already exist, the build command may append only the missing official-run normalization block and return `manifest_refreshed`. For TOB1 bundles it can infer FP2/IEEE4 format, hot numeric columns, header rows, sample frequency, averaging period, and start time when those are present in the bundle evidence. The draft now also performs a non-claim `raw_import_probe` with the inferred metadata, reporting decoded/empty/error status, detected raw format, native provenance, row count, time range, header detection, source-file anchors, and sample decoded fields. It now also maps EddyPro-style processing settings into `rp_config_draft`, including coordinate rotation, detrending, lag strategy/windows, WPL/density correction mode, screening thresholds, footprint method/geometry, random-uncertainty method, spectral-correction method, and measured-cospectrum usage flags. Sectioned `.eddypro` / `.metadata` files are parsed as both generic keys and section-scoped aliases, so `[Project]`, `[Site]`, `[Sonic Anemometer]`, `[Gas Analyzer]`, `[Methane Analyzer]`, `[Trace Gas]`, and `[Closed Path]` settings can populate `metadata_draft.project`, `metadata_draft.site`, `metadata_draft.instruments`, `metadata_draft.sampling_chain`, dynamic canopy metadata, and `rp_config_draft.metadata_bundle`. LI-7700 / CH4 settings are promoted into `rp_config_draft.trace_gas.ch4` with coefficient profile ID, coefficient source file, normalization command, spectroscopic/self-heating parameters, water-vapor dilution flags, provenance, and known limitations so the RP LI-7700 correction sequence can run from imported EddyPro project evidence. Bundle folders are also scanned for biomet, canopy/dynamic metadata, and LI-7700 coefficient/profile files; discovered files are recorded in the draft with provenance flags. Closed-path cell pressure/temperature from `sampling_chain.extra` can now feed configured ambient overrides for RP density/WPL calculations when external biomet does not provide those fields.

## Headless CLI

Inspect a bundle without modifying the fixture pack:

```bash
gas-ec-headless --inspect-official-raw-bundle references/eddypro/official_raw/site_001 --output inspection.json
```

Validate the same bundle against the P0 acquisition closure gate:

```bash
gas-ec-headless --validate-official-raw-bundle references/eddypro/official_raw/site_001 --output acquisition_validation.json
```

Build the evidence pack used by report center, result exports, delivery audit, and formal reports:

```bash
gas-ec-headless --build-official-raw-evidence-pack references/eddypro/official_raw/site_001 --output official_raw_evidence_pack.json
```

Check whether the current host can build or run official EddyPro before attempting capture:

```bash
gas-ec-headless --build-official-eddypro-executable-readiness references/eddypro/official_raw/site_001 --eddypro-source-dir D:/external_sources/eddypro-engine --output official_eddypro_executable_readiness.json
```

Prepare a reproducible embedded-mode run home without editing source project/raw assets:

```bash
gas-ec-headless --prepare-official-eddypro-project references/eddypro/official_raw/site_001 --output official_eddypro_project_prepare.json
```

Capture an official run after preparation. Output files may be passed as a glob so the sidecar hashes the newly produced EddyPro Full_Output rather than a preserved embedded reference:

```bash
gas-ec-headless --capture-official-eddypro-run references/eddypro/official_raw/site_001 --official-run-command "\"D:/external_sources/eddypro-engine/bin/win/eddypro_rp.exe\" -m embedded -e \"official_eddypro_run_home\"" --official-run-project-file official_eddypro_run_home/ini/processing.eddypro --official-run-output-files "official_eddypro_run_home/output/*full_output*.csv" --official-run-software-version "EddyPro source commit" --output official_eddypro_run_capture.json
```

Run the pack acceptance commands and write the updated pack:

```bash
gas-ec-headless --run-official-raw-evidence-acceptance official_raw_evidence_pack.json --output official_raw_evidence_pack.accepted.json
```

Register a complete bundle into a fixture pack copy:

```bash
gas-ec-headless --register-official-raw-bundle references/eddypro/official_raw/site_001 --fixture-pack references/eddypro/fixture_pack_v1.json --output updated_fixture_pack.json
```

Inspect a directory tree of bundles and write the discovery/evidence matrix:

```bash
gas-ec-headless --inspect-official-raw-bundles references/eddypro/official_raw --output official_raw_discovery.json
```

Register all complete bundles under a directory tree:

```bash
gas-ec-headless --register-official-raw-bundles references/eddypro/official_raw --fixture-pack references/eddypro/fixture_pack_v1.json --output updated_fixture_pack.json
```

Build manifests for every candidate bundle in a tree before registration:

```bash
gas-ec-headless --build-official-raw-bundle-manifests references/eddypro/official_raw --output manifest_batch_build.json
```

Use `--replace-fixture` only when intentionally replacing an existing `fixture_id`.

## Evidence Matrix

`official_raw_fixture_manifest.json` and the Report Center Fixture Pack page now expose `official_raw_fixture_evidence_matrix_v1`. The matrix records each fixture's raw format, site class, software version, readiness level, parity status, pass rate, failed fields, trace-gas parity status, import-probe status/format/row count, normalization status/time/source/QC mapping, required-field coverage, and missing evidence for an official claim. This keeps `.ghg`, TOB1, SLT, native binary, raw text coverage, and Full_Output normalization provenance visible instead of hiding it inside individual fixture rows.

`official_raw_fixture_detail.json`, `official_raw_evidence_pack.json`, result exports, delivery audit, and the formal report also carry the selected fixture's `normalization` block. This block is the delivery-chain source of truth for the original Full_Output path, generated reference path, provenance path, normalization command/time, QC mapping strategy, raw/unmapped columns, method metadata availability, known limitations, and whether required reference fields were present.

## Public Official Raw Acquisition Candidate

`references/eddypro/public_official_raw/manifest.json` records the official LI-COR Box-hosted EddyPro Sample Datasets ZIP as a public raw-data acquisition candidate. It is intentionally not counted as a raw-to-final parity fixture until the archive is downloaded, unpacked, inspected into `official_raw_fixture_bundle.json`, normalized, registered, and accepted through `--run-official-raw-closure`.

`references/eddypro/public_raw_search/manifest.json` records the current TOB1/SLT/native-binary public search ledger. It is a discovery artifact, not a fixture pack: documentation-only leads from Campbell Scientific, LI-COR/EddyPro, DOE WFIP2, and Swiss FluxNet are preserved with raw-format tags and promotion blockers, while `fixture_count` and `can_support_full_raw_to_final_eddypro_claim` remain zero/false until a downloadable raw-data plus EddyPro Full_Output pair is found.

When a complete public TOB1/SLT/native-binary/LI-7700 WMS bundle cannot be found, the registry now keeps moving with explicit source-derived conformance fixtures. `references/eddypro/source_derived/eddypro_source_tob1_seconds_001.tob1` is generated by `scripts/generate_source_derived_tob1_fixture.py` from EddyPro engine TOB1 source anchors (`import_tob1.f90`, `m_fp2_to_float.f90`) and registered in `fixture_pack_v1.json` as `source_derived_conformance`. `references/eddypro/source_derived/eddypro_source_slt_edisol_001.slt` and `references/eddypro/source_derived/eddypro_source_slt_eddysoft_001.slt` are generated by `scripts/generate_source_derived_slt_fixtures.py` from `import_slt_edisol.f90` and `import_slt_eddysoft.f90`, including EddySoft high-resolution analog mask provenance. `references/eddypro/source_derived/eddypro_source_native_binary_mixed_001.bin` is generated by `scripts/generate_source_derived_native_binary_fixture.py` from `import_binary.f90`, `import_native_data.f90`, and `write_processing_project_variables.f90`, including ASCII header, record framing, and mixed column-type provenance. `references/eddypro/source_derived/eddypro_source_li7700_wms_001.csv` is generated by `scripts/generate_source_derived_li7700_wms_fixture.py` from LI-7700/WMS source anchors (`m_li7700.f90`, `bpcf_li7700_analog_filters.f90`) and preserves WMS line-shape profile, fitted-area, reference-area, and trace-gas level parity provenance. These fixtures validate importer, WMS propagation, and raw-to-final harness behavior, but they are not real field datasets and do not close official raw-to-final parity gates.

To download the archive outside git:

```bash
gas-ec-headless --acquire-public-eddypro-fixtures --include-public-remote-originals --workspace-root . --output artifacts/eddypro_public_raw/public_fixture_acquisition.json
```

To inspect the downloaded archive without making a parity claim:

```bash
gas-ec-headless --inspect-public-official-raw-archive "artifacts/eddypro_public_raw/EddyPro Sample Datasets.zip" --workspace-root . --output artifacts/eddypro_public_raw/public_official_raw_archive_inspection.json
```

To materialize the inspected raw-only candidate into the official bundle directory contract:

```bash
gas-ec-headless --materialize-public-official-raw-bundle "artifacts/eddypro_public_raw/EddyPro Sample Datasets.zip" --workspace-root . --output artifacts/eddypro_public_raw/public_official_raw_bundle_draft.json
```

This creates `artifacts/eddypro_public_raw/official_raw_candidates/ghg_sample_data_2021/official_raw_fixture_bundle.json` plus extracted `.ghg` raw files. When a `.ghg` contains embedded EddyPro/SmartFlux files, the materializer also preserves `processing_*.eddypro`, `eddypro_exp_full_output_*.csv`, `eddypro.log`, and generates `normalized/reference.json` plus `normalized/provenance.json` from the embedded Full_Output. The generated bundle can become complete enough for registration, but closure remains blocked until an operator-captured EddyPro executable run sidecar with `exit_code=0` is supplied and `--run-official-raw-closure` passes.

The current public LI-COR sample archive inspection finds one candidate folder with 48 `.ghg` files. Its embedded EddyPro output can support audited reference/provenance generation for individual periods, but it remains blocked for full raw-to-final parity until executable-run evidence, registration, and closure acceptance are present.

The resulting ZIP should remain under `artifacts/` unless redistribution rights and repository size constraints are explicitly reviewed.

## Partial Capability Closure

`eddypro_partial_capability_closure.json` records the current non-blocking closure state for capability rows that still remain `partial` in `docs/benchmark/eddypro_capability_matrix.json`. It joins the accepted LI-COR official raw anchor, the TOB1/SLT/native-binary public search ledger, public EC data discovery sources, NEON HDF5 engineering validation, and the source-derived closure boundary into one delivery artifact.

Build it directly with:

```bash
gas-ec-headless --build-eddypro-partial-capability-closure --workspace-root . --output artifacts/eddypro_release_gate/eddypro_partial_capability_closure.json
```

The artifact is intentionally a current-round closure ledger, not a full-parity pass. If no redistributable raw/settings/Full_Output candidate is ready to register, it sets `closure_decision.current_round_closed=true` and keeps `claim_boundary.can_close_full_eddypro_parity=false`. Result bundles, delivery packages, and formal reports include the same artifact so the UI, manifest, export, and release evidence chain cannot drift.

## Truthfulness

Inspection only proves the bundle is complete enough to register. Full parity is claimed only after the registered asset runs through the raw-to-final harness and passes against official EddyPro output-derived reference windows.
