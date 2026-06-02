# EddyPro Computation Scope Audit

`eddypro_computation_scope_audit_v1` narrows the EddyPro comparison to eddy
covariance computation capability. It is deliberately different from the full
EddyPro release gate:

- It keeps coordinate rotation, lag compensation, despiking/QC, WPL or
  mixing-ratio correction, CO2/H2O/CH4 fluxes, spectral correction,
  spectra/cospectra/ogives, random uncertainty, and footprint in the required
  computation scope.
- It treats GUI workflow parity, SmartFlux deployment plumbing, target-host
  watchdog/service management, and hardware-only GPS/PTP fixture breadth as
  deferrable for the computation-superiority claim.
- It treats additional raw dialect breadth as supporting evidence, not as a
  blocker when a compatible raw importer path already exists.
- It never upgrades source-derived computation readiness into official field
  numeric parity without raw input, EddyPro project/settings, official
  Full_Output, normalized reference, provenance, and acceptance evidence.

Build it from the headless runner:

```powershell
python -m core.headless_batch_runner `
  --build-eddypro-computation-scope-audit `
  --workspace-root . `
  --output artifacts/eddypro_release_gate/eddypro_computation_scope_audit.json
```

If an existing coverage audit has already been generated, pass it explicitly:

```powershell
python -m core.headless_batch_runner `
  --build-eddypro-computation-scope-audit `
  --workspace-root . `
  --eddypro-coverage-audit artifacts/eddypro_release_gate/eddypro_coverage_audit.json `
  --output artifacts/eddypro_release_gate/eddypro_computation_scope_audit.json
```

Result exports, formal reports, and delivery packages include the computation
scope audit next to `eddypro_coverage_audit.json`. Use the computation audit to
decide whether the engine is ahead on calculation capability; use the full
release gate for official EddyPro software-surface and numeric parity claims.
