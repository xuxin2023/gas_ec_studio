# EddyPro Release Gate

`eddypro_release_gate_v1` is the CI/release wrapper around the EddyPro coverage audit.

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

The command returns exit code `0` only when `can_release_full_eddypro_parity=true`. Any blocker returns exit code `2` and records the reasons in `summary.blocking_reasons`.

Local release-gate runner:

```bash
python scripts/run_eddypro_release_gate.py --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output artifacts/eddypro_release_gate/eddypro_release_gate.json
```

The runner also accepts `--official-raw-closure-run official_raw_closure_run.json`. When supplied, the gate copies that artifact, reads its embedded or referenced evidence pack, and requires `official_raw_closure_run_gate_status=pass`.

The runner writes the release artifact, prints a compact blocker summary, returns the same CI exit code as the artifact, and writes a Markdown summary when `--summary-md` or `GITHUB_STEP_SUMMARY` is present.

GitHub Actions:

- `.github/workflows/eddypro-release-gate.yml` runs the release-gate regression tests and uploads `eddypro_release_gate.json` on pull requests and pushes.
- Normal PR/push runs are audit-only: a blocked gate is reported and uploaded, but it does not fail the workflow solely because official raw parity evidence is still incomplete.
- `workflow_dispatch` with `enforce_full_parity=true`, or tags matching `eddypro-parity-*`, fail unless the gate passes. This is the release-claim safety switch.

To let the release gate rerun safe pytest acceptance commands from the evidence pack or closure-run evidence pack, omit `--skip-release-gate-acceptance`. Use `--skip-release-gate-acceptance` only when an already accepted pack is supplied and immutable CI logs separately prove the acceptance run.

Truthfulness rule: this gate blocks marketing or release claims of full EddyPro parity unless coverage audit, official raw fixture readiness, source provenance, official closure evidence, and evidence-pack acceptance all pass together.
