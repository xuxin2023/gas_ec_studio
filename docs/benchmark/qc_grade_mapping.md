# EddyPro QC Grade Mapping

## Overview

This document describes the mapping between EddyPro QC flags and gas_ec_studio QC grades used in the benchmark comparison framework.

## Mapping Table

| EddyPro QC Flag | gas_ec_studio Grade | Description |
|-----------------|---------------------|-------------|
| 0 | A | Best quality — all QC tests passed |
| 1 | B | Moderate quality — some QC tests flagged |
| 2 | C | Poor quality — multiple QC tests failed |

## EddyPro QC Tests

EddyPro v7 applies the following QC tests (Mauder & Foken 2004, Foken et al. 2004):

1. **Spikes** — Number of spikes detected and removed
2. **Amplitude resolution** — Signal resolution check
3. **Drop-outs** — Data gap detection
4. **Absolute limits** — Physical plausibility check
5. **Steadiness of horizontal wind** — Non-stationarity of mean wind
6. **Stationarity test** — Integral turbulence characteristics

The overall QC flag is the maximum of individual test flags.

## gas_ec_studio QC Tests

gas_ec_studio applies a weighted QC matrix:

1. **Continuity** — Missing data ratio
2. **Lag confidence** — Covariance peak detection quality
3. **Density correction** — WPL/mixing ratio correction factor
4. **Rotation** — Double/triple rotation applied
5. **Stationarity** — Foken stationarity test
6. **Turbulence** — u* threshold and TKE check
7. **Statistical screening** — Skewness, kurtosis, spikes, dropouts
8. **Advanced tests** — Amplitude resolution, time lag, angle of attack, wind steadiness

## Limitations

1. **Different test composition** — EddyPro and gas_ec_studio may flag different issues for the same window, leading to grade discrepancies even when both are "correct"
2. **Different weighting** — gas_ec_studio uses a weighted score (0-100) with grade thresholds; EddyPro uses discrete flag aggregation
3. **Stationarity test differences** — Both implement Foken's test but may use different window subdivisions or thresholds
4. **u* threshold** — gas_ec_studio applies a configurable u* threshold; EddyPro may use a different value or method

## Benchmark Comparison Strategy

When comparing QC grades across software:

- **Default mode** (`qc_grade_must_match=False`): Grades within one step (A↔B, B↔C) are considered acceptable. This accounts for the inherent differences in QC test composition.
- **Strict mode** (`qc_grade_must_match=True`): Grades must match exactly. Use this only when comparing outputs from the same processing configuration.

## Reference

- Mauder, M., & Foken, T. (2004). Documentation and instruction manual of the eddy covariance software package TK2. *University of Bayreuth, Dept. of Micrometeorology*.
- Foken, T., et al. (2004). Post-field data quality control. In *Handbook of Micrometeorology* (pp. 181-208). Springer.
