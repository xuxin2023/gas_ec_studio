# EddyPro Computation Stress Suite

`eddypro_computation_stress_suite_v1` is a deterministic, source-derived
stress artifact for core eddy-covariance calculations. It keeps the program
closed when public raw/settings/Full_Output evidence is unavailable, without
promoting synthetic checks to official EddyPro field numeric parity.

## Covered Families

- Footprint: Kljun, Kormann-Meixner, and Hsieh stability sweeps plus a 2D grid
  mass-conservation check.
- Pipeline core oracle: known covariance, covariance-max lag recovery,
  density-correction mode semantics, double-rotation tilt removal, and
  constant-signal QC rejection through the RP pipeline.
- Rotation and lag: triple rotation, sector-wise planar fit, sector-wise planar
  fit with no-velocity-bias correction, and separate CO2/H2O covariance-max lag
  recovery.
- Flux, density, and energy: raw/mixing-ratio/WPL primary-flux selection,
  closed-path cell thermodynamic density terms, configured biomet ambient
  overrides, sensible heat, latent heat, evapotranspiration, and momentum
  flux unit sanity checks.
- Random uncertainty: Mann & Lenschow and Finkelstein & Sims positive-error and
  uncertainty-band checks.
- Spectral correction: Massman, Horst, Ibrom, and Fratini correction-factor
  checks, including measured-cospectrum routing for Fratini.
- CH4 / LI-7700: status diagnostics plus Level 0/1/2/3/final correction-chain
  checks for water-vapor dilution, spectroscopic, self-heating, and spectral
  propagation.

## Claim Boundary

Passing this suite supports source-derived algorithm stress readiness. It does
not prove official field numeric parity. Full EddyPro parity still requires
paired raw data, project/settings, and official EddyPro Full_Output evidence.

Non-computational blockers can be deferred from the computation gate when they
do not affect EC calculations directly, for example GUI workflow parity,
SmartFlux deployment plumbing, target-host watchdog service management, and
hardware-only GPS/PTP breadth.

## CLI

```powershell
python -m core.headless_batch_runner `
  --build-eddypro-computation-stress-suite `
  --workspace-root . `
  --output artifacts/eddypro_release_gate/eddypro_computation_stress_suite.json
```

The computation scope audit can consume an existing stress artifact:

```powershell
python -m core.headless_batch_runner `
  --build-eddypro-computation-scope-audit `
  --workspace-root . `
  --eddypro-computation-stress-suite artifacts/eddypro_release_gate/eddypro_computation_stress_suite.json `
  --output artifacts/eddypro_release_gate/eddypro_computation_scope_audit.json
```

Result exports write `eddypro_computation_stress_suite.json` next to
`eddypro_coverage_audit.json` and `eddypro_computation_scope_audit.json`, then
propagate all three through the formal report and delivery package manifests.
The artifact also includes `computation_surface`, a compact ready/blocked
rollup for the seven required computation families.
