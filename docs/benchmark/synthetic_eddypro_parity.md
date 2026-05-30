# Synthetic EddyPro Parity Oracles

When real high-frequency field bundles are unavailable, gas_ec_studio uses a synthetic parity suite as a CI guardrail. The suite does not claim real EddyPro numeric parity. It checks deterministic invariants that EddyPro-style EC processors should satisfy before official golden outputs are available.

## Current Oracle Cases

- `known_covariance_density_none`: zero-lag CO2 covariance with density correction disabled must match an independently calculated raw flux.
- `known_lag_covariance_max`: a scalar signal shifted by 5 samples at 10 Hz must recover a 0.5 s covariance-maximum lag.
- `density_correction_mode_semantics`: primary flux must select raw, dry-air mixing-ratio, or WPL-corrected flux according to the configured correction mode.
- `double_rotation_tilt_guardrail`: a tilted wind field must apply double rotation and reduce mean rotated vertical wind.
- `constant_signal_qc_guardrail`: constant CO2/H2O scalar inputs must be downgraded to QC grade C with constant-signal diagnostics.
- `spectral_correction_family_invariants`: Massman, Horst, Ibrom, and Fratini corrections must return stable factors, provenance, and measured-cospectrum usage for the Fratini path.
- `footprint_geometry_family_invariants`: Kljun, Kormann-Meixner, and Hsieh footprints must return positive monotonic contribution distances plus a normalized Kljun 2D grid.

## How To Run

```powershell
python -m pytest tests/test_synthetic_eddypro_parity.py -q
```

The callable entry point is `core.comparison.synthetic_parity.run_synthetic_eddypro_parity_suite()`.

## Export Integration

Set `synthetic_eddypro_parity.enabled` to `true` in the RP config snapshot to write `synthetic_eddypro_parity_artifact.json` into the result bundle and export manifest. Headless manifests include the same suite summary when the flag is enabled.

## Limitations

- This is not a replacement for anonymized raw `.ghg`, TOB1, SLT, binary, LI-7700, or spectral EddyPro golden-output fixtures.
- Synthetic signals cannot cover field non-stationarity, instrument drift, canopy complexity, or hidden EddyPro implementation details.
- The suite is intended to prevent obvious numerical regressions while real reference data is unavailable.
