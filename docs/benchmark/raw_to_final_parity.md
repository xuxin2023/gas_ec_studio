# Raw-To-Final EddyPro Parity Harness

The raw-to-final parity harness runs a raw fixture through `gas_ec_studio` RP processing and compares final window outputs to supplied EddyPro-style reference windows.

## What It Validates

- Raw fixture loading through text, native binary/TOB1/SLT, `.ghg`, or normalized-row JSON paths.
- Native import provenance in `raw_input.import_summary`, including actual decoded format such as `tob1_fp2`, data type, TOB1 header-derived format/columns/header rows, EddySoft SLT analog high-resolution mask decoding, per-column data types for mixed binary records, record count, decoded record count, one-based first/last record selection, ASCII header EOL mode, columns, optional record framing/stride, EddyPro source-file anchors, and reader limitations.
- Source-derived TOB1 conformance fixtures can be registered when public TOB1/SLT bundles are unavailable. `eddypro_source_tob1_seconds_001` is generated from EddyPro engine source anchors, preserves TOB1 `SECONDS`/`NANOSECONDS` leading ULONG timestamps, passes the raw-to-final harness, and is reported as `source_derived_conformance` rather than official field parity.
- RP pipeline execution using the fixture config snapshot.
- Window matching by exact/fuzzy start time or window ID.
- Final field comparisons for primary flux, lag, WPL terms, primary flux source, rotation method, lag strategy, and QC grade.
- LI-7700 / CH4 trace-gas level comparisons when references provide `ch4_flux_level0_nmol_m2_s`, `ch4_flux_level1_spectral_nmol_m2_s`, `ch4_flux_level2_density_nmol_m2_s`, `ch4_flux_corrected_nmol_m2_s`, or `ch4_flux_nmol_m2_s`. These are written under `trace_gas_parity` / `li7700_level_parity` with coefficient-profile provenance and failed fields.
- Export, headless, delivery, and formal-report artifact propagation when enabled.

## How To Enable In Export Config

```json
{
  "raw_to_final_parity": {
    "enabled": true,
    "fixture_id": "site_raw_fixture_001",
    "raw_path": "path/to/raw.csv",
    "metadata": {},
    "reference_json_path": "references/eddypro/site_reference.json",
    "thresholds": {
      "flux_rel_threshold": 0.1,
      "lag_abs_threshold_s": 0.5,
      "wpl_rel_threshold": 0.2,
      "trace_gas_rel_threshold": 0.1,
      "qc_grade_must_match": false
    }
  }
}
```

The exported artifact is `raw_to_final_parity_artifact.json`.

## Fixture Pack Registry

`references/eddypro/fixture_pack_v1.json` includes `synthetic_raw_csv_001` as a `raw_to_final_parity` fixture. The registered asset preserves:

- raw CSV fixture path and SHA-256
- metadata JSON path and SHA-256
- reference/golden JSON path and SHA-256
- provenance JSON path and SHA-256
- RP config and benchmark thresholds used by the harness

`build_fixture_pack_summary()` runs the harness for this tier and reports `raw_to_final_fixture_count`, `raw_to_final_pass_count`, row count, window count, reference count, raw import summary, and benchmark summary.

`build_official_raw_fixture_manifest()` produces `official_raw_fixture_manifest.json` for exports, headless manifests, delivery packages, formal reports, and the report center. This artifact separates:

- official raw-to-final ready bundles
- synthetic raw-to-final guardrails
- normalized EddyPro output-only references
- device protocol guardrails
- missing files required for an official parity claim

The required official bundle files are raw high-frequency input, EddyPro project/settings, official EddyPro output, normalized reference JSON, and normalization provenance. Manifest generation can now create the normalized reference/provenance pair from EddyPro `Full_Output` when those artifacts are absent, while preserving the original `Full_Output` file and recording the normalization command, time, QC mapping, method metadata availability, raw columns, unmapped columns, and known limitations.

The same manifest also includes `evidence_matrix`, a run-independent rollup for raw format coverage, site classes, software versions, readiness levels, parity status, pass rate, failed fields, trace-gas parity status, trace-gas failed fields, import-probe status/format/row count, normalization status/time/source/QC mapping, required-field coverage, and missing official evidence. This is the cockpit surface for checking whether real `.ghg`, TOB1, SLT, native binary, raw-text, and LI-7700 EddyPro bundles are represented, whether their inferred metadata can decode the raw input, and whether their Full_Output-derived reference/provenance artifacts are auditable before parity is claimed.

See `docs/benchmark/official_raw_fixture_bundle.md` for the directory contract and importer API.

For field campaigns with many sites, `build_official_raw_fixture_bundle_manifest_batch()` and the headless `--build-official-raw-bundle-manifests` command can prepare an entire official raw bundle tree before registration. Report Center's Fixture Pack controls expose the same tree-level build path, and tree registration will re-run the non-destructive manifest build pass so manifestless bundles can move into the active fixture pack once they are complete.

## Truthfulness

A passing harness result means the current raw fixture matches the supplied reference under the configured thresholds. It is not full EddyPro parity unless the reference windows are official EddyPro outputs for the same raw source.
