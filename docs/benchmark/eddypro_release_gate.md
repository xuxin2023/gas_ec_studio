# EddyPro Release Gate

`eddypro_release_gate_v1` is the CI/release wrapper around the EddyPro coverage audit.

It now reports three separate gates:

- `can_release_full_eddypro_parity`: strict official parity. This remains blocked until full implementation breadth, official EddyPro executable-run evidence, accepted raw-to-final fixtures, and evidence-pack acceptance all pass.
- `can_release_source_derived_functional_parity`: source-derived functional parity. This can pass when public/redistributable field evidence is unavailable but the source-derived conformance fixtures, official source inventory, accepted public anchor, and delivery-chain propagation all pass.
- `can_release_source_derived_computational_superiority`: source-derived EC computation readiness. This requires the computation scope audit plus `eddypro_computation_stress_suite_v1` and its `computation_surface.status=ready`.

The source-derived gates are deliberately not marketing shortcuts. They support software progress and CI closure; they must not be described as official field numeric parity, real hardware validation, or vendor-certified EddyPro equivalence.

It produces one machine-readable pass/block decision for full EddyPro parity release claims by checking:

- capability matrix coverage
- official EddyPro source inventory
- fixture pack validity
- official raw-to-final readiness
- official raw evidence-pack acceptance status
- official raw closure-run status when a closure artifact is supplied or auto-discovered under standard `artifacts/` locations
- source-derived computation scope/stress status when supplied or auto-built by the CLI/runner

Headless usage:

```bash
gas-ec-headless --build-eddypro-release-gate --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output eddypro_release_gate.json
```

Closure-run usage:

```bash
gas-ec-headless --build-eddypro-release-gate --workspace-root . --official-raw-closure-run official_raw_closure_run.json --output eddypro_release_gate.json
```

The command returns exit code `0` only when `can_release_full_eddypro_parity=true`. Any full-parity blocker returns exit code `2` and records the reasons in `summary.blocking_reasons`. The source-derived path has its own `surrogate_ci_exit_code` so CI summaries can show that functional parity is closed even while full official parity remains blocked.

The headless release-gate mode auto-builds the computation stress suite and computation scope audit unless explicit artifacts are supplied:

```bash
gas-ec-headless --build-eddypro-release-gate --workspace-root . --eddypro-computation-stress-suite artifacts/eddypro_release_gate/eddypro_computation_stress_suite.json --eddypro-computation-scope-audit artifacts/eddypro_release_gate/eddypro_computation_scope_audit.json --output eddypro_release_gate.json
```

When a computation audit or stress suite is supplied and it fails, the full release gate is blocked as well. When no computation artifact is supplied to the Python API, the computation gate is reported as `not_supplied` for backward-compatible library usage.

Local release-gate runner:

```bash
python scripts/run_eddypro_release_gate.py --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output artifacts/eddypro_release_gate/eddypro_release_gate.json
```

The runner also accepts `--official-raw-closure-run official_raw_closure_run.json`. When supplied, the gate copies that artifact, reads its embedded or referenced evidence pack, and requires `official_raw_closure_run_gate_status=pass`.

If no closure-run path is supplied, the gate auto-discovers `official_raw_closure_run_v1` artifacts from standard `artifacts/eddypro_public_raw`, `artifacts/eddypro_release_gate`, and nested `artifacts/**` locations. It prefers closure runs where `gate_status`, raw-to-final parity, acceptance, official EddyPro executable run, and pass rate have already passed. This keeps accepted public anchors visible in release summaries without changing the full-parity claim rule.

The runner writes the release artifact, prints a compact blocker summary, returns the same full-parity CI exit code as the artifact, and writes a Markdown summary when `--summary-md` or `GITHUB_STEP_SUMMARY` is present. That summary includes full parity, source-derived functional parity, and source-derived computation gate status. Use `--skip-computation-gate` only for compatibility checks that intentionally avoid running the computation stress suite.

GitHub Actions:

- `.github/workflows/eddypro-release-gate.yml` runs the release-gate regression tests and uploads `eddypro_release_gate.json` on pull requests and pushes.
- Normal PR/push runs are audit-only: a blocked gate is reported and uploaded, but it does not fail the workflow solely because official raw parity evidence is still incomplete.
- `workflow_dispatch` with `enforce_full_parity=true`, or tags matching `eddypro-parity-*`, fail unless the gate passes. This is the release-claim safety switch.

To let the release gate rerun safe pytest acceptance commands from the evidence pack or closure-run evidence pack, omit `--skip-release-gate-acceptance`. Use `--skip-release-gate-acceptance` only when an already accepted pack is supplied and immutable CI logs separately prove the acceptance run.

Truthfulness rule: this gate blocks marketing or release claims of full EddyPro parity unless coverage audit, official raw fixture readiness, source provenance, official closure evidence, and evidence-pack acceptance all pass together.

Public data status: see `docs/benchmark/public_ec_data_discovery.md` and `references/eddypro/public_raw_search/ec_public_data_sources.json` for the current discovery ledger. As of 2026-06-01, NEON DP4.00200.001 can expose public EC HDF5 files through the NEON API without account registration, ICOS Raw ASCII pages are discoverable but require a licence/account flow for repeatable programmatic download, and the project keeps official field numeric parity blocked until any such candidates are normalized into raw-to-final EddyPro evidence.
