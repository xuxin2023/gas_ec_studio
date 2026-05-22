# EddyPro Capability Matrix

Updated: 2026-05-22

## Current Verdict

gas_ec_studio is not yet a complete EddyPro replacement. It already goes beyond EddyPro-style desktop processing in several software-engineering areas: benchmark cockpit reruns, method parity artifacts, delivery audit manifests, reference provenance, and report-center traceability. It does not yet implement every EddyPro/SmartFlux scientific and acquisition feature family.

The machine-readable source of truth is `docs/benchmark/eddypro_capability_matrix.json`.

Primary EddyPro source-code references for parity work are:

- EddyPro Engine: https://github.com/LI-COR-Environmental/eddypro-engine
- EddyPro GUI: https://github.com/LI-COR-Environmental/eddypro-gui
- LI-COR Environmental GitHub: https://github.com/LI-COR-Environmental

## Strategic Target

The benchmark target is full public EddyPro parity across the official command-line engine and GUI feature surface, followed by differentiated capabilities that exceed EddyPro in auditability, reproducibility, automation, and delivery workflows.

Primary public repositories to track:

- EddyPro Engine: https://github.com/LI-COR-Environmental/eddypro-engine
- EddyPro GUI: https://github.com/LI-COR-Environmental/eddypro-gui
- LI-COR Environmental GitHub organization: https://github.com/LI-COR-Environmental

## Covered Or Strong

- Metadata model, dynamic metadata, external biomet, and now `.ghg` embedded biomet inspection/loading.
- Generic ASCII raw text import now maps configurable columns into `NormalizedHFFrame`, including unit conversion and TOB1/SLT-like text header skipping.
- RP pipeline basics: lag detection, detrending, coordinate rotation, planar-fit variants, QC matrix, random uncertainty, footprint families, and spectral-correction method provenance.
- Export and delivery chain: full output, FLUXNET/AmeriFlux/ICOS validation summaries, formal report, package manifest, delivery audit.
- Beyond-EddyPro auditability: method parity matrix, benchmark artifacts, reference provenance, report center/cockpit integration.

## Partial

- `.ghg` support is now real for manifest/metadata/embedded biomet and high-frequency raw rows can run through headless RP/FCC/export. Broader real-world LI-COR fixture coverage is still needed.
- Native TOB1 IEEE4, generic fixed-record binary, and SLT EdiSol/EddySoft-style int16 bridge readers now decode fixture payloads into `NormalizedHFFrame` with provenance; FP2 and broad vendor dialect parity remain incomplete.
- Biomet aggregation exists, but it does not yet override all thermodynamic ambient variables used by the RP flux equations.
- Spectral methods exist, but long-period binned spectra/cospectra assessment and EddyPro-equivalent output families need more work.
- CO2/H2O/energy flux fields exist, but full EddyPro Level 0/1/2/3 closed-path correction sequencing still needs validation.
- CH4 now has raw/GHG/headless ingestion plus an auditable LI-7700 correction sequence v1 and coefficient profile registry provenance; raw WMS line-shape fitting and public real LI-7700 numeric parity fixtures remain incomplete.
- Sonic coordinate/head correction now runs before rotation/lag/flux for common EddyPro-style orientation offsets, Gill WindMaster W-boost handling, bias offsets, and configured angle gain; full Nakai AoA lookup-table parity remains incomplete.
- Crosswind sonic-temperature correction now runs before thermodynamic flux calculations for common EddyPro A/B/C coefficient families; real instrument parity fixtures and GUI controls remain incomplete.
- GPS/PTP-style acquisition clock synchronization now applies offset/drift/event corrections before RP/FCC window slicing and daemon_telemetry v1 parses configured PTP servo/GPS PPS logs for lock, offset, and jitter provenance; direct hardware clock discipline control and broad vendor daemon dialect coverage remain incomplete.
- SmartFlux-like runtime hardening now has a headless runtime profile/watchdog manifest plus runtime_service v1 for queued headless batches, heartbeats, disk/queue telemetry, retry records, quarantined failures, delivery state, process telemetry, supervisor status, PTP/GPS logs, hardware watchdog event logs, and supervisor_integration v1 for systemd/Windows/manual status plus file/manual hardware watchdog kick/reboot handoff across report center, formal reports, delivery package, and exporter manifests; true installed embedded daemon control and direct hardware watchdog/reboot providers remain incomplete.
- Footprint v1 exists, but georeferenced GIS outputs remain missing.

## Missing

- No tracked family is currently marked fully missing in the machine-readable matrix; remaining EddyPro/SmartFlux gaps are partial parity items rather than absent feature families.

## Official Source Anchors

- EddyPro Engine repository: https://github.com/LI-COR-Environmental/eddypro-engine
- EddyPro GUI repository: https://github.com/LI-COR-Environmental/eddypro-gui
- LI-COR Environmental GitHub organization: https://github.com/LI-COR-Environmental
- LI-COR Eddy Covariance Software: https://home.licor.com/env/products/eddy-covariance/software
- LI-COR SmartFlux System: https://bio.licor.com/env/products/eddy-covariance/smartflux
- EddyPro `.ghg` file type: https://www.licor.com/support/EddyPro/topics/ghg-file-format.html
- EddyPro spectral corrections: https://www.licor.com/support/EddyPro/topics/spectral-corrections.html
- EddyPro LI-7200/LI-7700 flux calculations: https://www.licor.com/support/EddyPro/topics/calculate-flux-7200-and-7700.html
