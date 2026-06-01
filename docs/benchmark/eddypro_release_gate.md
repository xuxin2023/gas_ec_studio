# EddyPro Release Gate

`eddypro_release_gate_v1` is the CI/release wrapper around the EddyPro coverage audit.

It now reports two separate gates:

- `can_release_full_eddypro_parity`: strict official parity. This remains blocked until full implementation breadth, official EddyPro executable-run evidence, accepted raw-to-final fixtures, and evidence-pack acceptance all pass.
- `can_release_source_derived_functional_parity`: source-derived functional parity. This can pass when public/redistributable field evidence is unavailable but the source-derived conformance fixtures, official source inventory, accepted public anchor, and delivery-chain propagation all pass.

The second gate is deliberately not a marketing shortcut. It supports software progress and CI closure; it must not be described as official field numeric parity, real hardware validation, or vendor-certified EddyPro equivalence.

It produces one machine-readable pass/block decision for full EddyPro parity release claims by checking:

- capability matrix coverage
- official EddyPro source inventory
- fixture pack validity
- official raw-to-final readiness
- official raw evidence-pack acceptance status
- optional official raw closure-run status when a closure artifact is supplied

Headless usage:

```bash
gas-ec-headless --build-eddypro-release-gate --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output eddypro_release_gate.json
```

Closure-run usage:

```bash
gas-ec-headless --build-eddypro-release-gate --workspace-root . --official-raw-closure-run official_raw_closure_run.json --output eddypro_release_gate.json
```

The command returns exit code `0` only when `can_release_full_eddypro_parity=true`. Any full-parity blocker returns exit code `2` and records the reasons in `summary.blocking_reasons`. The source-derived path has its own `surrogate_ci_exit_code` so CI summaries can show that functional parity is closed even while full official parity remains blocked.

Local release-gate runner:

```bash
python scripts/run_eddypro_release_gate.py --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output artifacts/eddypro_release_gate/eddypro_release_gate.json
```

The runner also accepts `--official-raw-closure-run official_raw_closure_run.json`. When supplied, the gate copies that artifact, reads its embedded or referenced evidence pack, and requires `official_raw_closure_run_gate_status=pass`.

The runner writes the release artifact, prints a compact blocker summary, returns the same full-parity CI exit code as the artifact, and writes a Markdown summary when `--summary-md` or `GITHUB_STEP_SUMMARY` is present. That summary includes both full parity and source-derived parity status.

GitHub Actions:

- `.github/workflows/eddypro-release-gate.yml` runs the release-gate regression tests and uploads `eddypro_release_gate.json` on pull requests and pushes.
- Normal PR/push runs are audit-only: a blocked gate is reported and uploaded, but it does not fail the workflow solely because official raw parity evidence is still incomplete.
- `workflow_dispatch` with `enforce_full_parity=true`, or tags matching `eddypro-parity-*`, fail unless the gate passes. This is the release-claim safety switch.

To let the release gate rerun safe pytest acceptance commands from the evidence pack or closure-run evidence pack, omit `--skip-release-gate-acceptance`. Use `--skip-release-gate-acceptance` only when an already accepted pack is supplied and immutable CI logs separately prove the acceptance run.

Truthfulness rule: this gate blocks marketing or release claims of full EddyPro parity unless coverage audit, official raw fixture readiness, source provenance, official closure evidence, and evidence-pack acceptance all pass together.

Public data status: see `docs/benchmark/public_ec_data_discovery.md` and `references/eddypro/public_raw_search/ec_public_data_sources.json` for the current discovery ledger. As of 2026-06-01, NEON DP4.00200.001 can expose public EC HDF5 files through the NEON API without account registration, ICOS Raw ASCII pages are discoverable but require a licence/account flow for repeatable programmatic download, and the project keeps official field numeric parity blocked until any such candidates are normalized into raw-to-final EddyPro evidence.
