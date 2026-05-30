# Spectral Assessment Export

`spectral_assessment_export_v1` formalizes the FCC spectra/cospectra/ogive delivery family.

Each result export now includes:

- `spectral_assessment.json`: run-level summary, provenance, binned ensemble rows, companion file index, and known limitations.
- `spectral_binned_ensemble.csv`: log-frequency ensemble means for measured power spectrum, reference spectrum, cospectrum, ogive, observed transfer, and model total transfer function.
- `spectral_full_windows.csv`: original per-window frequency/value rows for each spectral family.
- `spectral_ogive_ensemble.csv`: delivery-friendly ogive/cospectrum ensemble table.
- `spectral_assessment_library.json`: reusable long-period spectral library built from one or more `SpectralRunResult` objects, with month/QC/risk stratified groups, ensemble means, ensemble standard deviations, run/window provenance, and known limitations.
- `spectral_assessment_library_groups.csv` and `spectral_assessment_library_bins.csv`: delivery-friendly library group index and grouped frequency-bin table.

`RunResultStore.build_spectral_assessment_library(...)` can build the same library from stored FCC runs, so month-scale assessment can be accumulated across batches rather than reconstructed manually from individual exports.

This advances EddyPro-style spectral output coverage without claiming full raw-to-final EddyPro parity. `references/eddypro/public_spectral/manifest.json` now registers a public Zenodo EddyPro-derived spectra/cospectra subset with MD5/SHA-256, row-count, and frequency-range validation, while official LI-COR/EddyPro spectral golden-output fixtures remain required for stronger acceptance-level numeric parity.
