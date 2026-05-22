# EddyPro Capability Matrix

Updated: 2026-05-22

## Current Verdict

gas_ec_studio is not yet a complete EddyPro replacement. It already goes beyond EddyPro-style desktop processing in several software-engineering areas: benchmark cockpit reruns, method parity artifacts, delivery audit manifests, reference provenance, and report-center traceability. It does not yet implement every EddyPro/SmartFlux scientific and acquisition feature family.

The machine-readable source of truth is `docs/benchmark/eddypro_capability_matrix.json`.

## Covered Or Strong

- Metadata model, dynamic metadata, external biomet, and now `.ghg` embedded biomet inspection/loading.
- Generic ASCII raw text import now maps configurable columns into `NormalizedHFFrame`, including unit conversion and TOB1/SLT-like text header skipping.
- RP pipeline basics: lag detection, detrending, coordinate rotation, planar-fit variants, QC matrix, random uncertainty, footprint families, and spectral-correction method provenance.
- Export and delivery chain: full output, FLUXNET/AmeriFlux/ICOS validation summaries, formal report, package manifest, delivery audit.
- Beyond-EddyPro auditability: method parity matrix, benchmark artifacts, reference provenance, report center/cockpit integration.

## Partial

- `.ghg` support is now real for manifest/metadata/embedded biomet and high-frequency raw rows can run through headless RP/FCC/export. Broader real-world LI-COR fixture coverage is still needed.
- Biomet aggregation exists, but it does not yet override all thermodynamic ambient variables used by the RP flux equations.
- Spectral methods exist, but long-period binned spectra/cospectra assessment and EddyPro-equivalent output families need more work.
- CO2/H2O/energy flux fields exist, but full EddyPro Level 0/1/2/3 closed-path correction sequencing still needs validation.
- CH4 now has raw/GHG/headless ingestion plus Level 0 covariance flux output with LI-7700 provenance, but full LI-7700 spectroscopic, density, and self-heating corrections are still incomplete.
- Footprint v1 exists, but georeferenced GIS outputs remain missing.

## Missing

- Binary/TOB1/SLT raw file readers.
- GPS/PTP synchronization subsystem.
- Sonic head correction, flow distortion, angle-of-attack correction, and model-specific anemometer bug corrections.
- Crosswind correction.
- Full SmartFlux-like embedded/on-site runtime hardening.

## Official Source Anchors

- LI-COR Eddy Covariance Software: https://home.licor.com/env/products/eddy-covariance/software
- LI-COR SmartFlux System: https://bio.licor.com/env/products/eddy-covariance/smartflux
- EddyPro `.ghg` file type: https://www.licor.com/support/EddyPro/topics/ghg-file-format.html
- EddyPro spectral corrections: https://www.licor.com/support/EddyPro/topics/spectral-corrections.html
- EddyPro LI-7200/LI-7700 flux calculations: https://www.licor.com/support/EddyPro/topics/calculate-flux-7200-and-7700.html
