# EddyPro Coverage Audit

`eddypro_coverage_audit_v1` is the delivery-chain claim gate for EddyPro parity.

It combines:

- `docs/benchmark/eddypro_capability_matrix.json`
- `references/eddypro/fixture_pack_v1.json`
- `official_raw_fixture_manifest.json`
- `official_raw_evidence_pack.json`
- `eddypro_source_inventory.json`

The audit deliberately separates three claims:

- implementation breadth: capability rows marked `covered`, `partial`, `missing`, or `beyond_eddypro`
- source provenance: local public EddyPro engine/GUI source anchors and feature-token checks
- numerical evidence: official raw-to-final fixture readiness and parity status
- acceptance evidence: official raw evidence-pack commands have run and passed
- closure readiness: machine-readable `closure_gate` and `closure_plan` entries with priority, required evidence, blocked claims, and acceptance commands

Full EddyPro parity remains blocked unless all EddyPro capability rows are covered, at least one official raw-to-final fixture is ready and passing, the fixture pack validates, the official source inventory passes, and the selected official raw evidence pack has `acceptance_gate_status=pass`.

When `--official-raw-evidence-pack` is not supplied, the audit scans standard `artifacts/` locations for an accepted `official_raw_fixture_evidence_pack_v1` or a closure run that points to one, preferring artifacts where both the evidence-pack acceptance gate and official EddyPro executable-run gate pass. Explicit CLI input still takes precedence.

`closure_gate` is intended for delivery and truthfulness checks. `closure_plan` is intended for engineering execution: work through P0 items first, attach the listed evidence, then run the listed acceptance commands before changing a capability row to `covered`.

Headless usage:

```bash
gas-ec-headless --build-eddypro-coverage-audit --workspace-root . --official-raw-evidence-pack official_raw_evidence_pack.accepted.json --output eddypro_coverage_audit.json
```

Result exports, formal reports, and delivery packages now include `eddypro_coverage_audit.json` alongside the fixture pack summary, official raw fixture manifest, fixture detail, and source inventory artifacts.

For CI/release blocking, prefer `eddypro_release_gate_v1` (`docs/benchmark/eddypro_release_gate.md`), which wraps this audit and returns exit code `0` only when the full EddyPro parity claim can be released.
