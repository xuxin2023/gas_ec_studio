from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np

from core.ec_rp.analysis import (
    PlanarFitCoefficients,
    analyze_lag,
    apply_planar_fit_no_velocity_bias,
    apply_planar_fit_rotation,
    compute_flux_metrics,
    compute_footprint,
    compute_footprint_2d_grid,
    compute_li7700_correction_sequence,
    compute_li7700_status_diagnostics,
    compute_spectral_correction,
    compute_uncertainty_finkelstein_sims,
    compute_uncertainty_mann_lenschow,
    rotate_wind,
)
from core.comparison.synthetic_parity import run_synthetic_eddypro_parity_suite
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import (
    BiometSourceMetadata,
    MetadataBundle,
    ProjectProfile,
    RawColumnMapping,
    RawFileDescriptionMetadata,
    RawFileSettingsMetadata,
    SiteProfile,
)


def build_eddypro_computation_stress_suite(
    *,
    workspace_root: str | Path | None = None,
    include_slow_cases: bool = False,
) -> dict[str, Any]:
    """Run deterministic source-derived stress checks for core EC calculations."""

    root = Path(workspace_root).resolve() if workspace_root not in (None, "") else Path.cwd()
    cases = [
        _pipeline_core_oracle_case(),
        _raw_biomet_ingestion_stress_case(root),
        _raw_import_edge_cases_stress_case(root),
        _rotation_lag_stress_case(),
        _flux_density_energy_closed_path_case(),
        _multi_gas_final_flux_stress_case(),
        _footprint_stress_case(),
        _uncertainty_stress_case(),
        _spectral_correction_stress_case(),
        _ch4_li7700_stress_case(),
    ]
    if include_slow_cases:
        cases.append(_long_autocorrelation_uncertainty_case())
    passed = [case for case in cases if case["status"] == "pass"]
    failed = [case for case in cases if case["status"] != "pass"]
    family_counts: dict[str, int] = {}
    for case in cases:
        family = str(case.get("family", "unknown"))
        family_counts[family] = family_counts.get(family, 0) + 1
    computation_surface = _computation_surface(cases)
    return {
        "artifact_type": "eddypro_computation_stress_suite_v1",
        "suite_id": "eddypro_computation_stress_suite_v1",
        "generated_at": datetime.now().isoformat(),
        "workspace_root": str(root),
        "status": "pass" if not failed else "fail",
        "case_count": len(cases),
        "passed_case_count": len(passed),
        "failed_case_count": len(failed),
        "pass_rate": round(len(passed) / max(1, len(cases)), 4),
        "family_counts": dict(sorted(family_counts.items())),
        "computation_surface": computation_surface,
        "failed_cases": [
            {"case_id": case["case_id"], "family": case["family"], "failure_reasons": case.get("failure_reasons", [])}
            for case in failed
        ],
        "cases": cases,
        "claim_boundary": {
            "can_support_source_derived_computational_superiority": not failed,
            "can_claim_official_field_numeric_parity": False,
            "can_replace_real_eddypro_raw_to_final_fixture": False,
            "can_ignore_real_data_blocker_for_algorithm_stress": True,
            "core_computation_surface_ready": computation_surface["status"] == "ready",
        },
        "truthfulness_boundary": (
            "This suite stress-tests EC computation families with deterministic synthetic/source-derived inputs. "
            "It strengthens algorithm-readiness evidence but does not replace public/anonymized raw EddyPro "
            "fixtures for official numeric parity."
        ),
        "known_limitations": [
            "Synthetic stress cases exercise invariants, edge conditions, and method provenance rather than site-specific field truth.",
            "Pipeline-core oracle checks are deterministic CI evidence and do not replace official EddyPro executable output.",
            "Official EddyPro raw-to-final parity remains blocked until paired raw/settings/Full_Output evidence exists.",
            "Stress cases should expand whenever new computation families or method variants are added.",
        ],
    }


def _pipeline_core_oracle_case() -> dict[str, Any]:
    suite = run_synthetic_eddypro_parity_suite()
    required_case_ids = {
        "known_covariance_density_none",
        "known_lag_covariance_max",
        "density_correction_mode_semantics",
        "double_rotation_tilt_guardrail",
        "constant_signal_qc_guardrail",
    }
    case_by_id = {str(case.get("case_id", "")): dict(case or {}) for case in list(suite.get("cases", []) or [])}
    missing = sorted(required_case_ids - set(case_by_id))
    failed_required = [
        case_id
        for case_id in sorted(required_case_ids & set(case_by_id))
        if case_by_id[case_id].get("status") != "pass"
    ]
    failures: list[str] = []
    if suite.get("status") != "pass":
        failures.append(f"synthetic_oracle_suite_status={suite.get('status')}")
    failures.extend(f"missing_required_oracle={case_id}" for case_id in missing)
    failures.extend(f"failed_required_oracle={case_id}" for case_id in failed_required)
    return _case_payload(
        case_id="pipeline_core_oracle_gate",
        family="pipeline_core",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "synthetic_oracle_status": suite.get("status"),
            "oracle_case_count": suite.get("case_count", 0),
            "required_oracle_case_count": len(required_case_ids),
            "failed_required_oracle_count": len(failed_required),
            "missing_required_oracle_count": len(missing),
        },
        details={
            "required_case_ids": sorted(required_case_ids),
            "case_summaries": [
                {
                    "case_id": str(case.get("case_id", "")),
                    "status": str(case.get("status", "")),
                    "check_count": int(case.get("check_count", 0) or 0),
                    "failed_check_count": int(case.get("failed_check_count", 0) or 0),
                }
                for case in list(suite.get("cases", []) or [])
            ],
            "truthfulness_note": suite.get("truthfulness_note", ""),
        },
    )


def _raw_biomet_ingestion_stress_case(root: Path) -> dict[str, Any]:
    from core.headless_batch_runner import load_input_rows, run_headless_batch

    case_root = root / "artifacts" / "eddypro_computation_stress_inputs" / "raw_biomet_ingestion"
    case_root.mkdir(parents=True, exist_ok=True)
    raw_path = case_root / "raw_biomet_ingestion.csv"
    biomet_path = case_root / "biomet_ambient.csv"

    samples = 600
    sample_rate_hz = 10.0
    start = datetime(2026, 6, 4, 9, 0, 0)
    axis = np.arange(samples, dtype=float) / sample_rate_hz
    w = 0.42 * np.sin(2.0 * np.pi * 0.18 * axis) + 0.06 * np.cos(2.0 * np.pi * 0.61 * axis)
    u = 2.35 + 0.12 * np.sin(2.0 * np.pi * 0.03 * axis)
    v = 0.24 * np.cos(2.0 * np.pi * 0.05 * axis)
    co2_ppm = 410.0 + 7.0 * np.roll(w, 4)
    h2o_molmol = 0.012 + 0.001 * np.roll(w, 2)
    pressure_pa = 101_300.0 + 45.0 * np.sin(2.0 * np.pi * 0.04 * axis)
    temp_k = 298.15 + 0.45 * np.sin(2.0 * np.pi * 0.08 * axis)
    ch4_ppm = 1.9 + 0.004 * np.roll(w, 3)

    raw_lines = ["DateTime,CO2_molmol,H2O_molmol,PressurePa,TempK,Ux,Vy,Wz,CH4_ppm"]
    for index in range(samples):
        timestamp = start + timedelta(seconds=float(index) / sample_rate_hz)
        raw_lines.append(
            ",".join(
                [
                    timestamp.isoformat(),
                    f"{co2_ppm[index] / 1_000_000.0:.9f}",
                    f"{h2o_molmol[index]:.9f}",
                    f"{pressure_pa[index]:.3f}",
                    f"{temp_k[index]:.5f}",
                    f"{u[index]:.6f}",
                    f"{v[index]:.6f}",
                    f"{w[index]:.6f}",
                    f"{ch4_ppm[index]:.9f}",
                ]
            )
        )
    raw_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")

    biomet_path.write_text(
        "\n".join(
            [
                "timestamp,ta,pressure_kpa,rh",
                "2026-06-04T09:00:00,22.0,99.4,58",
                "2026-06-04T09:00:20,24.0,99.8,62",
                "2026-06-04T09:00:40,26.0,100.2,66",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-RBI", name="Raw Biomet Stress"),
        site=SiteProfile(station_code="RBI", station_name="Raw Biomet Tower"),
        raw_file_description=RawFileDescriptionMetadata(
            source_name="raw-biomet-stress",
            source_type="csv",
            column_mappings=[
                RawColumnMapping(column_name="DateTime", variable="timestamp", numeric=False),
                RawColumnMapping(column_name="CO2_molmol", variable="co2_ppm", input_unit="mol/mol"),
                RawColumnMapping(column_name="H2O_molmol", variable="h2o_mmol", input_unit="mol/mol"),
                RawColumnMapping(column_name="PressurePa", variable="pressure_kpa", input_unit="Pa"),
                RawColumnMapping(column_name="TempK", variable="chamber_temp_c", input_unit="K"),
                RawColumnMapping(column_name="Ux", variable="u"),
                RawColumnMapping(column_name="Vy", variable="v"),
                RawColumnMapping(column_name="Wz", variable="w"),
                RawColumnMapping(column_name="CH4_ppm", variable="ch4_ppb", input_unit="ppm"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=sample_rate_hz,
            delimiter=",",
            header_rows=1,
            missing_tokens=["", "NA"],
        ),
        biomet=BiometSourceMetadata(
            source_mode="external_file",
            source_path=str(biomet_path),
            fields=["ta", "pressure_kpa", "rh"],
            aggregation_method="mean",
        ),
    )
    rows = load_input_rows(raw_path, metadata=metadata)
    result = run_headless_batch(
        config={
            "sample_hz": sample_rate_hz,
            "block_minutes": 0.5,
            "rotation_mode": "double",
            "detrend_mode": "linear",
            "density_correction_mode": "wpl",
        },
        metadata=metadata,
        rows=rows,
        data_source="raw-biomet-ingestion-stress",
    )
    rp_result = result["rp_result"]
    first_window = rp_result.windows[0] if rp_result.windows else None
    diagnostics = dict(first_window.diagnostics if first_window is not None else {})
    ambient_values = dict(diagnostics.get("biomet_ambient_values", {}) or {})
    applied_fields = set(diagnostics.get("biomet_ambient_applied_fields", []) or [])
    ledger = dict(diagnostics.get("flux_correction_ledger", {}) or {})
    ledger_stages = list(ledger.get("stages", []) or [])
    ambient_stage = next(
        (dict(stage or {}) for stage in ledger_stages if dict(stage or {}).get("stage") == "ambient_thermodynamics"),
        {},
    )
    first_raw_payload = json.loads(rows[0].raw_text) if rows else {}
    manifest = dict(result.get("manifest", {}) or {})
    raw_import_summary = dict(result.get("raw_import_summary", {}) or manifest.get("raw_import_summary", {}) or {})

    failures: list[str] = []
    if len(rows) != samples:
        failures.append(f"raw_row_count_expected_{samples}_got_{len(rows)}")
    if first_window is None:
        failures.append("rp_window_missing_after_raw_biomet_batch")
    if rows and not _close(rows[0].co2_ppm, float(co2_ppm[0]), abs_tol=0.002):
        failures.append("co2_molmol_to_ppm_conversion_failed")
    if rows and not _close(rows[0].h2o_mmol, float(h2o_molmol[0] * 1000.0), abs_tol=0.002):
        failures.append("h2o_molmol_to_mmol_conversion_failed")
    if rows and not _close(rows[0].pressure_kpa, float(pressure_pa[0] / 1000.0), abs_tol=0.002):
        failures.append("pressure_pa_to_kpa_conversion_failed")
    if rows and not _close(rows[0].chamber_temp_c, float(temp_k[0] - 273.15), abs_tol=0.002):
        failures.append("temperature_k_to_c_conversion_failed")
    if rows and not _close(rows[0].ch4_ppb, float(ch4_ppm[0] * 1000.0), abs_tol=0.002):
        failures.append("ch4_ppm_to_ppb_conversion_failed")
    if not _finite_number(first_raw_payload.get("u")) or not _finite_number(first_raw_payload.get("w")):
        failures.append("raw_wind_components_not_preserved")
    if diagnostics.get("biomet_ambient_status") != "applied":
        failures.append(f"biomet_ambient_status={diagnostics.get('biomet_ambient_status', '')}")
    for field in ("pressure_kpa", "temp_c", "mean_h2o_mmol"):
        if field not in applied_fields:
            failures.append(f"biomet_field_not_applied={field}")
    if diagnostics.get("biomet_ambient_h2o_source") != "derived:relative_humidity":
        failures.append(f"biomet_h2o_source={diagnostics.get('biomet_ambient_h2o_source', '')}")
    if diagnostics.get("ambient_override_status") != "applied":
        failures.append(f"ambient_override_status={diagnostics.get('ambient_override_status', '')}")
    if not _close(ambient_values.get("mean_pressure_kpa"), 99.6, abs_tol=0.02):
        failures.append(f"biomet_pressure_mean={ambient_values.get('mean_pressure_kpa')}")
    if not _close(ambient_values.get("mean_temp_c"), 23.0, abs_tol=0.02):
        failures.append(f"biomet_temp_mean={ambient_values.get('mean_temp_c')}")
    if not _positive_number(ambient_values.get("mean_h2o_mmol")):
        failures.append("biomet_h2o_not_derived_from_rh")
    if ambient_stage.get("biomet_status") != "applied":
        failures.append("flux_correction_ledger_missing_biomet_ambient_stage")
    if manifest.get("raw_import_summary", {}).get("row_count", raw_import_summary.get("row_count")) not in (None, samples):
        failures.append("manifest_raw_import_row_count_mismatch")

    return _case_payload(
        case_id="raw_biomet_ingestion_pipeline_stress",
        family="raw_biomet_ingestion",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "raw_row_count": len(rows),
            "rp_window_count": len(rp_result.windows),
            "co2_ppm_first": rows[0].co2_ppm if rows else None,
            "h2o_mmol_first": rows[0].h2o_mmol if rows else None,
            "pressure_kpa_first": rows[0].pressure_kpa if rows else None,
            "temp_c_first": rows[0].chamber_temp_c if rows else None,
            "ch4_ppb_first": rows[0].ch4_ppb if rows else None,
            "biomet_status": diagnostics.get("biomet_ambient_status", ""),
            "biomet_pressure_kpa": ambient_values.get("mean_pressure_kpa"),
            "biomet_temp_c": ambient_values.get("mean_temp_c"),
            "biomet_h2o_mmol": ambient_values.get("mean_h2o_mmol"),
            "ambient_override_status": diagnostics.get("ambient_override_status", ""),
            "ledger_biomet_status": ambient_stage.get("biomet_status", ""),
        },
        details={
            "raw_source_file": str(raw_path),
            "biomet_source_file": str(biomet_path),
            "raw_import_summary": raw_import_summary,
            "biomet_ambient": diagnostics.get("biomet_ambient", {}),
            "biomet_ambient_applied_fields": sorted(applied_fields),
            "biomet_ambient_provenance": diagnostics.get("biomet_ambient_provenance", ""),
            "flux_correction_ambient_stage": ambient_stage,
            "manifest_biomet_ambient_summary": manifest.get("biomet_ambient_summary", {}),
        },
    )


def _raw_import_edge_cases_stress_case(root: Path) -> dict[str, Any]:
    from core.headless_batch_runner import load_input_rows

    case_root = root / "artifacts" / "eddypro_computation_stress_inputs" / "raw_import_edge_cases"
    case_root.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    fixtures: dict[str, dict[str, Any]] = {}

    toa5_path = case_root / "campbell_toa5.dat"
    toa5_path.write_text(
        "\n".join(
            [
                '"TOA5","EC_TOWER","CR6","12345","ECProgram.CR6","123","EC stress"',
                '"TIMESTAMP","Ux","Vy","Wz","CO2","H2O","P","TA","CH4"',
                '"TS","m/s","m/s","m/s","ppm","mmol/mol","kPa","C","ppm"',
                '"Smp","Avg","Avg","Avg","Avg","Avg","Avg","Avg","Avg"',
                '"2026-06-04 09:00:00",2.50,-0.10,0.20,410.25,12.50,101.30,25.10,1.905',
                '"2026-06-04 09:00:00.1",2.55,-0.12,0.24,410.75,12.55,101.31,25.15,1.906',
                '"2026-06-04 09:00:00.2",2.60,-0.14,0.28,411.10,12.60,101.32,25.20,1.907',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    toa5_metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-TOA5", name="TOA5 Edge Case"),
        raw_file_description=RawFileDescriptionMetadata(
            source_name="campbell-toa5-stress",
            source_type="toa5",
            column_mappings=[
                RawColumnMapping(column_name="TIMESTAMP", variable="timestamp", numeric=False),
                RawColumnMapping(column_name="Ux", variable="u"),
                RawColumnMapping(column_name="Vy", variable="v"),
                RawColumnMapping(column_name="Wz", variable="w"),
                RawColumnMapping(column_name="CO2", variable="co2_ppm"),
                RawColumnMapping(column_name="H2O", variable="h2o_mmol"),
                RawColumnMapping(column_name="P", variable="pressure_kpa"),
                RawColumnMapping(column_name="TA", variable="chamber_temp_c"),
                RawColumnMapping(column_name="CH4", variable="ch4_ppb", input_unit="ppm"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, delimiter=",", header_rows=4),
    )
    toa5_rows = load_input_rows(toa5_path, metadata=toa5_metadata)
    toa5_payload = json.loads(toa5_rows[0].raw_text) if toa5_rows else {}
    if len(toa5_rows) != 3:
        failures.append(f"toa5_row_count_expected_3_got_{len(toa5_rows)}")
    if toa5_rows and not _close(toa5_rows[0].co2_ppm, 410.25, abs_tol=0.001):
        failures.append("toa5_actual_header_column_resolution_failed")
    if toa5_rows and not _close(toa5_rows[0].ch4_ppb, 1905.0, abs_tol=0.001):
        failures.append("toa5_ch4_ppm_to_ppb_conversion_failed")
    if not _close(toa5_payload.get("w"), 0.2, abs_tol=0.001):
        failures.append("toa5_wind_payload_not_preserved")
    fixtures["toa5_text"] = {
        "source_file": str(toa5_path),
        "row_count": len(toa5_rows),
        "first_timestamp": toa5_rows[0].timestamp.isoformat() if toa5_rows else "",
        "first_co2_ppm": toa5_rows[0].co2_ppm if toa5_rows else None,
        "first_ch4_ppb": toa5_rows[0].ch4_ppb if toa5_rows else None,
    }

    base = datetime(2026, 6, 4, 9, 0, 0)
    seconds = int((base - datetime(1990, 1, 1)).total_seconds())
    ieee4_path = case_root / "record_timestamp_ieee4.tob1"
    ieee4_header = (
        b'"TOB1","IEEE4"\r\n'
        b'"SECONDS","NANOSECONDS","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"ULONG","ULONG","ULONG","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4","IEEE4"\r\n'
    )
    ieee4_records = [
        (seconds, 0, 1, 2.50, -0.10, 0.20, 410.25, 12.50, 101.30, 25.10),
        (seconds, 100_000_000, 2, 2.55, -0.12, 0.24, 410.75, 12.55, 101.31, 25.15),
    ]
    ieee4_path.write_bytes(ieee4_header + b"".join(struct.pack("<3I7f", *record) for record in ieee4_records))
    ieee4_metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-IEEE4", name="TOB1 IEEE4 Edge Case"),
        raw_file_description=RawFileDescriptionMetadata(source_type="tob1"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0),
    )
    ieee4_rows = load_input_rows(ieee4_path, metadata=ieee4_metadata)
    ieee4_provenance = json.loads(ieee4_rows[0].raw_text).get("raw_native_import", {}) if ieee4_rows else {}
    if len(ieee4_rows) != 2:
        failures.append(f"tob1_ieee4_row_count_expected_2_got_{len(ieee4_rows)}")
    if len(ieee4_rows) > 1 and ieee4_rows[1].timestamp.isoformat() != "2026-06-04T09:00:00.100000":
        failures.append(f"tob1_ieee4_record_timestamp={ieee4_rows[1].timestamp.isoformat()}")
    if ieee4_provenance.get("timestamp_source") != "tob1_record_seconds_nanoseconds":
        failures.append(f"tob1_ieee4_timestamp_source={ieee4_provenance.get('timestamp_source', '')}")
    if ieee4_provenance.get("tob1_eddypro_compatibility", {}).get("status") != "compatible":
        failures.append("tob1_ieee4_compatibility_not_detected")
    fixtures["tob1_ieee4_record_timestamp"] = {
        "source_file": str(ieee4_path),
        "row_count": len(ieee4_rows),
        "format": ieee4_provenance.get("format", ""),
        "timestamp_source": ieee4_provenance.get("timestamp_source", ""),
        "leading_ulong_columns": ieee4_provenance.get("leading_ulong_columns", []),
    }

    fp2_path = case_root / "leading_ulong_fp2.tob1"
    fp2_header = (
        b'"TOB1","FP2"\r\n'
        b'"TIMESTAMP","RECORD","U","V","W","CO2","H2O","P","TA"\r\n'
        b'"ULONG","ULONG","FP2","FP2","FP2","FP2","FP2","FP2","FP2"\r\n'
    )
    fp2_records = [
        (
            123456,
            1,
            _fp2_word(2.5, 1),
            _fp2_word(-0.1, 1),
            _fp2_word(0.2, 1),
            _fp2_word(410.0, 1),
            _fp2_word(12.34, 2),
            _fp2_word(101.3, 1),
            _fp2_word(25.6, 1),
        ),
        (
            123457,
            2,
            _fp2_word(2.6, 1),
            _fp2_word(-0.2, 1),
            _fp2_word(0.3, 1),
            _fp2_word(411.0, 1),
            _fp2_word(12.35, 2),
            _fp2_word(101.4, 1),
            _fp2_word(25.7, 1),
        ),
    ]
    fp2_path.write_bytes(fp2_header + b"".join(struct.pack("<2I7H", *record) for record in fp2_records))
    fp2_metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-FP2", name="TOB1 FP2 Edge Case"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, extra={"start_time": "2026-06-04T09:00:00"}),
    )
    fp2_rows = load_input_rows(fp2_path, metadata=fp2_metadata)
    fp2_payload = json.loads(fp2_rows[0].raw_text) if fp2_rows else {}
    fp2_provenance = dict(fp2_payload.get("raw_native_import", {}) or {})
    if len(fp2_rows) != 2:
        failures.append(f"tob1_fp2_row_count_expected_2_got_{len(fp2_rows)}")
    if fp2_rows and not _close(fp2_rows[0].h2o_mmol, 12.34, abs_tol=0.001):
        failures.append("tob1_fp2_h2o_decode_failed")
    if fp2_provenance.get("fp2_skip_words") != 4:
        failures.append(f"tob1_fp2_skip_words={fp2_provenance.get('fp2_skip_words')}")
    if not fp2_provenance.get("preserved_leading_ulong_values"):
        failures.append("tob1_fp2_leading_ulong_values_not_preserved")
    fixtures["tob1_fp2_leading_ulong"] = {
        "source_file": str(fp2_path),
        "row_count": len(fp2_rows),
        "format": fp2_provenance.get("format", ""),
        "fp2_skip_words": fp2_provenance.get("fp2_skip_words"),
        "leading_ulong_columns": fp2_provenance.get("leading_ulong_columns", []),
        "source_reference": fp2_provenance.get("source_reference", {}),
    }

    binary_path = case_root / "framed_mixed_native.bin"
    binary_payload = bytearray(b"ASCII HEADER\n")
    binary_records = [
        (410.25, 12.50, 1013, 251, 2.50, -0.10, 0.20),
        (410.75, 12.55, 1014, 252, 2.55, -0.12, 0.24),
    ]
    for index, record in enumerate(binary_records):
        binary_payload.extend(bytes([0xA0 + index, 0x5A]))
        binary_payload.extend(struct.pack("<ffhhfff", *record))
        binary_payload.extend(b"\x00\xff")
    binary_path.write_bytes(bytes(binary_payload))
    binary_metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-BIN", name="Framed Mixed Binary Edge Case"),
        raw_file_description=RawFileDescriptionMetadata(
            source_type="binary",
            column_mappings=[
                RawColumnMapping(column_name="co2_raw", variable="co2_ppm"),
                RawColumnMapping(column_name="h2o_raw", variable="h2o_mmol"),
                RawColumnMapping(column_name="p_raw", variable="pressure_kpa", scaling=0.1),
                RawColumnMapping(column_name="ta_raw", variable="chamber_temp_c", scaling=0.1),
                RawColumnMapping(column_name="u_raw", variable="u"),
                RawColumnMapping(column_name="v_raw", variable="v"),
                RawColumnMapping(column_name="w_raw", variable="w"),
            ],
        ),
        raw_file_settings=RawFileSettingsMetadata(
            sample_hz=10.0,
            extra={
                "native_format": "binary",
                "columns": ["co2_raw", "h2o_raw", "p_raw", "ta_raw", "u_raw", "v_raw", "w_raw"],
                "column_types": {
                    "co2_raw": "float32",
                    "h2o_raw": "float32",
                    "u_raw": "float32",
                    "v_raw": "float32",
                    "w_raw": "float32",
                },
                "header_rows": 1,
                "record_header_bytes": 2,
                "record_footer_bytes": 2,
                "record_length_bytes": 30,
                "start_time": "2026-06-04T09:00:00",
            },
        ),
    )
    binary_rows = load_input_rows(binary_path, metadata=binary_metadata)
    binary_provenance = json.loads(binary_rows[0].raw_text).get("raw_native_import", {}) if binary_rows else {}
    if len(binary_rows) != 2:
        failures.append(f"native_binary_row_count_expected_2_got_{len(binary_rows)}")
    if binary_rows and not _close(binary_rows[0].pressure_kpa, 101.3, abs_tol=0.001):
        failures.append("native_binary_scaling_failed")
    if binary_provenance.get("data_type") != "mixed":
        failures.append(f"native_binary_data_type={binary_provenance.get('data_type', '')}")
    if binary_provenance.get("record_length_bytes") != 30:
        failures.append(f"native_binary_record_length={binary_provenance.get('record_length_bytes')}")
    fixtures["native_binary_mixed_framed"] = {
        "source_file": str(binary_path),
        "row_count": len(binary_rows),
        "format": binary_provenance.get("format", ""),
        "data_type": binary_provenance.get("data_type", ""),
        "record_length_bytes": binary_provenance.get("record_length_bytes"),
        "column_types": binary_provenance.get("column_types", []),
    }

    passed_format_count = sum(1 for fixture in fixtures.values() if int(fixture.get("row_count", 0) or 0) > 0)
    return _case_payload(
        case_id="raw_import_edge_cases_format_stress",
        family="raw_import_edge_cases",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "format_count": len(fixtures),
            "passed_format_count": passed_format_count,
            "toa5_row_count": len(toa5_rows),
            "tob1_ieee4_timestamp_source": ieee4_provenance.get("timestamp_source", ""),
            "tob1_fp2_skip_words": fp2_provenance.get("fp2_skip_words"),
            "native_binary_data_type": binary_provenance.get("data_type", ""),
        },
        details={
            "fixtures": fixtures,
            "source_reference": {
                "eddypro_engine_repository": "https://github.com/LI-COR-Environmental/eddypro-engine",
                "importer_focus": [
                    "TOA5 multi-row text header handling",
                    "TOB1 IEEE4 record timestamps",
                    "TOB1 FP2 leading ULONG preservation",
                    "native binary mixed-type framing",
                ],
            },
        },
    )


def _rotation_lag_stress_case() -> dict[str, Any]:
    rng = np.random.default_rng(20260604)
    samples = 1200
    sample_rate_hz = 10.0
    axis = np.arange(samples, dtype=float) / sample_rate_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * axis) + rng.normal(0.0, 0.04, samples)
    v = 0.45 + 0.12 * np.cos(2.0 * np.pi * 0.05 * axis) + rng.normal(0.0, 0.03, samples)
    w = 0.28 + 0.34 * np.sin(2.0 * np.pi * 0.17 * axis) + rng.normal(0.0, 0.04, samples)
    triple = rotate_wind(u, v, w, "triple")
    coeffs = PlanarFitCoefficients(b0=0.02, b1=0.015, b2=-0.008, sector="S02", window_count=12, r_squared=0.91)
    planar = apply_planar_fit_rotation(u, v, w, coeffs)
    planar_nvb = apply_planar_fit_no_velocity_bias(u, v, w, coeffs)

    co2_lag_samples = 8
    h2o_lag_samples = 4
    scalar_driver = 0.55 * np.sin(2.0 * np.pi * 0.21 * axis) + 0.22 * np.cos(2.0 * np.pi * 0.37 * axis)
    w_lag = scalar_driver + rng.normal(0.0, 0.015, samples)
    co2 = np.roll(w_lag, co2_lag_samples) + rng.normal(0.0, 0.015, samples)
    h2o = np.roll(w_lag, h2o_lag_samples) + rng.normal(0.0, 0.015, samples)
    lag = analyze_lag(
        vertical_velocity=w_lag,
        co2_series=co2,
        h2o_series=h2o,
        sample_rate_hz=sample_rate_hz,
        search_window_s=1.5,
        lag_strategy="covariance_max",
    )
    expected_co2_lag_s = -co2_lag_samples / sample_rate_hz
    expected_h2o_lag_s = -h2o_lag_samples / sample_rate_hz
    failures: list[str] = []
    if triple.mode != "triple" or not triple.applied:
        failures.append("triple_rotation_not_applied")
    if abs(float(np.mean(triple.w))) > 0.08:
        failures.append("triple_rotation_mean_w_not_near_zero")
    if planar.mode != "sector_wise_planar_fit" or not planar.applied:
        failures.append("sector_wise_planar_fit_not_applied")
    if "S02" not in planar.reason:
        failures.append("sector_wise_planar_fit_sector_missing")
    if planar_nvb.mode != "sector_wise_planar_fit_no_velocity_bias" or not planar_nvb.applied:
        failures.append("sector_wise_planar_fit_nvb_not_applied")
    if not _close(lag.co2_lag_seconds, expected_co2_lag_s, abs_tol=0.11):
        failures.append(f"co2_lag_expected_{expected_co2_lag_s:.2f}_got_{lag.co2_lag_seconds:.2f}")
    if not _close(lag.h2o_lag_seconds, expected_h2o_lag_s, abs_tol=0.11):
        failures.append(f"h2o_lag_expected_{expected_h2o_lag_s:.2f}_got_{lag.h2o_lag_seconds:.2f}")
    if float(lag.confidence or 0.0) < 0.4:
        failures.append("lag_confidence_below_floor")
    return _case_payload(
        case_id="rotation_lag_multi_component_sweep",
        family="rotation_lag",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "triple_mean_w_after_rotation": float(np.mean(triple.w)),
            "triple_alpha_deg": triple.alpha_deg,
            "triple_beta_deg": triple.beta_deg,
            "planar_fit_sector": coeffs.sector,
            "planar_fit_r_squared": coeffs.r_squared,
            "co2_lag_seconds": lag.co2_lag_seconds,
            "h2o_lag_seconds": lag.h2o_lag_seconds,
            "lag_confidence": lag.confidence,
        },
        details={
            "triple_rotation": {
                "mode": triple.mode,
                "applied": triple.applied,
                "reason": triple.reason,
                "mean_w_after_rotation": float(np.mean(triple.w)),
            },
            "sector_wise_planar_fit": {
                "mode": planar.mode,
                "applied": planar.applied,
                "reason": planar.reason,
            },
            "sector_wise_planar_fit_no_velocity_bias": {
                "mode": planar_nvb.mode,
                "applied": planar_nvb.applied,
                "reason": planar_nvb.reason,
            },
            "lag_components": {
                "expected_co2_lag_seconds": expected_co2_lag_s,
                "expected_h2o_lag_seconds": expected_h2o_lag_s,
                "co2_lag_seconds": lag.co2_lag_seconds,
                "h2o_lag_seconds": lag.h2o_lag_seconds,
                "blend_lag_seconds": lag.lag_seconds,
                "confidence": lag.confidence,
            },
        },
    )


def _flux_density_energy_closed_path_case() -> dict[str, Any]:
    sample_rate_hz = 10.0
    samples = 720
    axis = np.arange(samples, dtype=float) / sample_rate_hz
    w = 0.42 * np.sin(2.0 * np.pi * 0.20 * axis) + 0.05 * np.cos(2.0 * np.pi * 0.55 * axis)
    co2 = 410.0 + 7.0 * (np.roll(w, 3) + 0.02 * np.sin(2.0 * np.pi * 0.9 * axis))
    h2o = 12.0 + 0.9 * np.roll(w, 1)
    pressure = 101.3 + 0.03 * np.sin(2.0 * np.pi * 0.04 * axis)
    temp = 25.0 + 0.6 * np.sin(2.0 * np.pi * 0.17 * axis)
    cell_pressure = 101.2 + 0.04 * w
    cell_temp = 26.0 + 0.9 * w
    by_mode = {
        mode: compute_flux_metrics(
            w_series=w,
            co2_ppm=co2,
            h2o_mmol=h2o,
            pressure_kpa=pressure,
            temp_c=temp,
            cell_pressure_kpa=cell_pressure,
            cell_temp_c=cell_temp,
            detrend_mode="block_mean",
            density_correction_mode=mode,
        )
        for mode in ("none", "mixing_ratio", "wpl")
    }
    biomet_override = compute_flux_metrics(
        w_series=w,
        co2_ppm=co2,
        h2o_mmol=h2o,
        pressure_kpa=pressure,
        temp_c=temp,
        detrend_mode="block_mean",
        density_correction_mode="wpl",
        ambient_overrides={
            "source": "synthetic_biomet_stress",
            "mean_pressure_kpa": 99.8,
            "mean_temp_c": 22.4,
            "mean_h2o_mmol": 14.5,
        },
    )
    wpl = by_mode["wpl"]
    ustar = 0.37
    momentum_flux_tau_pa = float(wpl.get("air_density_kg_m3", 0.0) or 0.0) * ustar**2
    failures: list[str] = []
    if not _close(by_mode["none"].get("primary_flux"), by_mode["none"].get("raw_flux"), abs_tol=1e-12):
        failures.append("density_none_primary_flux_not_raw")
    if not _close(by_mode["mixing_ratio"].get("primary_flux"), by_mode["mixing_ratio"].get("mixing_ratio_flux"), abs_tol=1e-12):
        failures.append("mixing_ratio_primary_flux_not_mixing_ratio")
    if not _close(wpl.get("primary_flux"), wpl.get("density_corrected_flux"), abs_tol=1e-12):
        failures.append("wpl_primary_flux_not_density_corrected")
    density_expected = (
        float(wpl.get("raw_flux", 0.0) or 0.0)
        + float(wpl.get("wpl_water_vapor_term", 0.0) or 0.0)
        + float(wpl.get("wpl_sensible_heat_term", 0.0) or 0.0)
        + float(wpl.get("closed_path_cell_pressure_term", 0.0) or 0.0)
    )
    if not _close(wpl.get("density_corrected_flux"), density_expected, rel_tol=1e-9, abs_tol=1e-12):
        failures.append("wpl_density_terms_do_not_sum")
    if wpl.get("cell_thermodynamics_status") != "available":
        failures.append("closed_path_cell_thermodynamics_not_available")
    if wpl.get("wpl_sensible_heat_source") != "cell_temperature":
        failures.append("closed_path_cell_temperature_not_selected")
    if not bool(wpl.get("closed_path_density_correction_applied")):
        failures.append("closed_path_density_correction_not_applied")
    for key in (
        "sensible_heat_flux_w_m2",
        "latent_heat_flux_w_m2",
        "evapotranspiration_rate_mm_h",
        "air_density_kg_m3",
    ):
        if not _finite_number(wpl.get(key)) or abs(float(wpl.get(key, 0.0) or 0.0)) <= 1e-15:
            failures.append(f"{key}_not_finite_or_zero")
    if not _positive_number(momentum_flux_tau_pa):
        failures.append("momentum_tau_not_positive")
    if biomet_override.get("ambient_override_status") != "applied":
        failures.append("biomet_ambient_override_not_applied")
    if biomet_override.get("ambient_override_source") != "synthetic_biomet_stress":
        failures.append("biomet_ambient_override_source_missing")
    return _case_payload(
        case_id="flux_density_energy_closed_path_sweep",
        family="flux_density_energy",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "density_modes_checked": sorted(by_mode),
            "wpl_water_vapor_term": wpl.get("wpl_water_vapor_term"),
            "wpl_sensible_heat_term": wpl.get("wpl_sensible_heat_term"),
            "closed_path_density_term": wpl.get("closed_path_density_term"),
            "sensible_heat_flux_w_m2": wpl.get("sensible_heat_flux_w_m2"),
            "latent_heat_flux_w_m2": wpl.get("latent_heat_flux_w_m2"),
            "evapotranspiration_rate_mm_h": wpl.get("evapotranspiration_rate_mm_h"),
            "momentum_flux_tau_pa": momentum_flux_tau_pa,
            "biomet_override_status": biomet_override.get("ambient_override_status"),
        },
        details={
            "primary_flux_by_mode": {
                mode: {
                    "primary_flux": payload.get("primary_flux"),
                    "raw_flux": payload.get("raw_flux"),
                    "mixing_ratio_flux": payload.get("mixing_ratio_flux"),
                    "density_corrected_flux": payload.get("density_corrected_flux"),
                    "density_correction_mode": payload.get("density_correction_mode"),
                    "density_correction_reason": payload.get("density_correction_reason"),
                }
                for mode, payload in by_mode.items()
            },
            "closed_path_cell_detail": wpl.get("closed_path_cell_detail", {}),
            "biomet_override_summary": {
                "ambient_override_status": biomet_override.get("ambient_override_status"),
                "ambient_override_source": biomet_override.get("ambient_override_source"),
                "mean_pressure_kpa": biomet_override.get("mean_pressure_kpa"),
                "mean_temp_c": biomet_override.get("mean_temp_c"),
                "mean_h2o_mmol": biomet_override.get("mean_h2o_mmol"),
            },
        },
    )


def _multi_gas_final_flux_stress_case() -> dict[str, Any]:
    from core.headless_batch_runner import run_headless_batch

    rows = _make_multi_gas_rows(samples=1200, sample_rate_hz=10.0)
    metadata = MetadataBundle(
        project=ProjectProfile(code="STRESS-MG", name="Multi Gas Final Flux Stress"),
        site=SiteProfile(station_code="MG", station_name="Multi Gas Tower"),
    )
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "rotation_mode": "double",
        "detrend_mode": "linear",
        "density_correction_mode": "wpl",
        "lag_phase": {"strategy": "covariance_max", "search_window_s": 1.0, "expected_lag_s": 0.4},
        "network_output": {"schema_target": "FLUXNET", "timestamp_refers_to": "start", "timezone_offset_hours": 0.0},
        "trace_gas": {
            "ch4": {
                "coefficient_profile_id": "stress_li7700_multi_gas",
                "coefficient_registry": {
                    "stress_li7700_multi_gas": {
                        "label": "Stress LI-7700 multi-gas coefficients",
                        "source": "source_derived_stress_fixture",
                        "source_file": "core/comparison/eddypro_computation_stress_suite.py",
                        "normalization_command": "gas_ec stress-suite --family multi_gas_final_flux",
                        "spectroscopic_correction": {
                            "mode": "empirical",
                            "pressure_sensitivity_per_kpa": 0.001,
                            "temperature_sensitivity_per_c": 0.0005,
                            "h2o_sensitivity_per_molfrac": 0.1,
                        },
                        "self_heating_correction": {
                            "mode": "empirical",
                            "sensor_body_temp_c": 27.0,
                            "flux_sensitivity_per_c": 0.01,
                        },
                        "known_limitations": [
                            "Synthetic coefficients are for deterministic stress evidence only.",
                            "Official EddyPro CH4 parity still requires paired raw/settings/Full_Output evidence.",
                        ],
                    }
                },
                "spectral_correction_factor": 1.04,
                "apply_water_vapor_dilution": True,
                "status_diagnostics": {
                    "min_rssi_warning_pct": 40.0,
                    "min_signal_strength_warning_pct": 40.0,
                    "require_lock": True,
                    "allowed_status_words": [0],
                },
            },
            "n2o": {
                "enabled": False,
                "status": "not_implemented",
                "truthfulness_boundary": "N2O high-frequency flux is intentionally not claimed until a real N2O channel/model is added.",
            },
        },
    }
    result = run_headless_batch(config=config, metadata=metadata, rows=rows, data_source="multi-gas-final-flux-stress")
    rp_result = result["rp_result"]
    windows = list(rp_result.windows or [])
    first = windows[0] if windows else None
    diagnostics = dict(first.diagnostics if first is not None else {})
    trace_summary = dict(rp_result.summary.get("trace_gas_summary", {}) if isinstance(rp_result.summary, dict) else {})
    manifest = dict(result.get("manifest", {}) or {})
    manifest_trace_summary = dict(manifest.get("trace_gas_summary", {}) or {})
    ledger = dict(diagnostics.get("flux_correction_ledger", {}) or {})
    ledger_stages = list(ledger.get("stages", []) or [])
    ch4_ledger_stage = next(
        (dict(stage or {}) for stage in ledger_stages if dict(stage or {}).get("stage") == "ch4_li7700_sequence"),
        {},
    )
    first_payload = json.loads(rows[0].raw_text) if rows else {}
    trace_family = dict(diagnostics.get("trace_gas_family", {}) or {})
    ch4_family = dict(trace_family.get("ch4", {}) or {})
    ch4_sequence = dict(diagnostics.get("ch4_correction_sequence", {}) or {})

    failures: list[str] = []
    if len(windows) < 2:
        failures.append(f"multi_gas_window_count={len(windows)}")
    if first is None:
        failures.append("multi_gas_first_window_missing")
    if first is not None and not _finite_number(first.primary_flux):
        failures.append("co2_primary_flux_not_finite")
    if first is not None and not _finite_number(first.water_vapor_flux):
        failures.append("h2o_water_vapor_flux_not_finite")
    if diagnostics.get("ch4_status") != "computed":
        failures.append(f"ch4_status={diagnostics.get('ch4_status', '')}")
    if diagnostics.get("ch4_method") != "li_7700_correction_sequence_v1":
        failures.append(f"ch4_method={diagnostics.get('ch4_method', '')}")
    if not _positive_number(abs(float(diagnostics.get("ch4_flux_nmol_m2_s", 0.0) or 0.0))):
        failures.append("ch4_final_flux_not_nonzero")
    if diagnostics.get("ch4_flux_level0_nmol_m2_s") == diagnostics.get("ch4_flux_nmol_m2_s"):
        failures.append("ch4_correction_sequence_did_not_change_level0")
    if ch4_sequence.get("status") != "computed":
        failures.append(f"ch4_sequence_status={ch4_sequence.get('status', '')}")
    if ch4_ledger_stage.get("status") != "computed":
        failures.append("flux_ledger_missing_computed_ch4_stage")
    if trace_summary.get("status") != "computed":
        failures.append(f"trace_summary_status={trace_summary.get('status', '')}")
    if int(trace_summary.get("ch4_computed_window_count", 0) or 0) != len(windows):
        failures.append("trace_summary_ch4_window_count_mismatch")
    if manifest_trace_summary.get("status") != "computed":
        failures.append(f"manifest_trace_summary_status={manifest_trace_summary.get('status', '')}")
    if ch4_family.get("correction_sequence_status") != "computed":
        failures.append("trace_gas_family_ch4_sequence_not_computed")
    if "n2o_ppb" not in first_payload:
        failures.append("n2o_payload_not_preserved")
    if "n2o" in trace_family:
        failures.append("n2o_trace_family_claimed_without_model")

    return _case_payload(
        case_id="multi_gas_final_flux_window_stress",
        family="multi_gas_final_flux",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "window_count": len(windows),
            "co2_primary_flux": first.primary_flux if first is not None else None,
            "primary_flux_source": first.primary_flux_source if first is not None else "",
            "h2o_water_vapor_flux": first.water_vapor_flux if first is not None else None,
            "ch4_flux_level0_nmol_m2_s": diagnostics.get("ch4_flux_level0_nmol_m2_s"),
            "ch4_flux_nmol_m2_s": diagnostics.get("ch4_flux_nmol_m2_s"),
            "ch4_correction_sequence_status": ch4_sequence.get("status", ""),
            "trace_gas_summary_status": trace_summary.get("status", ""),
            "ch4_computed_window_count": trace_summary.get("ch4_computed_window_count", 0),
            "n2o_boundary_status": "not_implemented",
        },
        details={
            "trace_gas_summary": trace_summary,
            "manifest_trace_gas_summary": manifest_trace_summary,
            "trace_gas_family": trace_family,
            "ch4_correction_sequence": ch4_sequence,
            "flux_correction_ch4_stage": ch4_ledger_stage,
            "n2o_boundary": {
                "status": "not_implemented",
                "raw_payload_field_preserved": "n2o_ppb" in first_payload,
                "claimed_in_trace_gas_family": "n2o" in trace_family,
                "reason": "NormalizedHFFrame and RP diagnostics currently implement CH4 trace-gas flux, not N2O final flux.",
                "next_required_work": [
                    "Add an N2O high-frequency channel to normalized frames or trace-gas payload extraction.",
                    "Implement N2O covariance, density/spectral corrections, diagnostics, exporter fields, and parity mapping.",
                ],
            },
            "truthfulness_boundary": (
                "CO2/H2O/CH4 final flux paths are stress-verified here; N2O is deliberately recorded "
                "as not implemented rather than counted as a computed trace gas."
            ),
        },
    )


def _footprint_stress_case() -> dict[str, Any]:
    methods = ["kljun", "kormann_meixner", "hsieh"]
    stability_values = [-120.0, None, 160.0]
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for method in methods:
        for ol in stability_values:
            fp = compute_footprint(
                method=method,
                ustar=0.38,
                mean_wind_speed=3.4,
                sigma_v=0.92,
                z_m=4.0,
                h=1.2,
                z0=0.12,
                ol=ol,
            )
            ordered = _ordered_contribution_distances(fp.contribution_distances)
            if fp.detail.get("status") != "ok":
                failures.append(f"{method}:{ol}:status={fp.detail.get('status')}")
            if fp.peak_distance_m <= 0.0 or fp.offset_distance_m < 0.0:
                failures.append(f"{method}:{ol}:non_positive_distance")
            if not ordered:
                failures.append(f"{method}:{ol}:unordered_contributions")
            results.append(
                {
                    "method": method,
                    "ol_m": ol,
                    "peak_distance_m": fp.peak_distance_m,
                    "offset_distance_m": fp.offset_distance_m,
                    "contribution_distances": dict(fp.contribution_distances),
                    "ordered_contributions": ordered,
                    "provenance": str(fp.detail.get("provenance", "")),
                }
            )
    grid_source = compute_footprint(
        method="kljun",
        ustar=0.38,
        mean_wind_speed=3.4,
        sigma_v=0.92,
        z_m=4.0,
        h=1.2,
        z0=0.12,
        ol=-120.0,
    )
    grid = compute_footprint_2d_grid(
        footprint=grid_source,
        method="kljun",
        ustar=0.38,
        mean_wind_speed=3.4,
        sigma_v=0.92,
        z_m=4.0,
        h=1.2,
        z0=0.12,
        ol=-120.0,
        x_bins=28,
        y_bins=21,
    )
    grid_sum = float(np.sum(np.asarray(grid.contribution_grid, dtype=float)))
    if not math.isclose(grid_sum, 1.0, rel_tol=5.0e-3, abs_tol=5.0e-3):
        failures.append(f"footprint_2d_grid_sum={grid_sum:.6f}")
    return _case_payload(
        case_id="footprint_family_stability_sweep",
        family="footprint",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "method_count": len(methods),
            "scenario_count": len(results),
            "grid_sum": round(grid_sum, 6),
            "grid_peak_downwind_m": grid.peak_downwind_m,
            "grid_half_width_m": grid.half_width_m,
        },
        details={"results": results, "grid_detail": grid.detail},
    )


def _uncertainty_stress_case() -> dict[str, Any]:
    rng = np.random.default_rng(20260602)
    n = 2400
    w = rng.normal(0.0, 0.42, n)
    scalar = 0.72 * np.roll(w, 4) + rng.normal(0.0, 0.08, n)
    ml = compute_uncertainty_mann_lenschow(
        cov_w_scalar=0.045,
        var_w=0.31,
        var_scalar=1.85,
        n_samples=18000,
        averaging_period_s=1800.0,
        integral_timescale_s=7.5,
    )
    fs = compute_uncertainty_finkelstein_sims(
        w_series=w,
        scalar_series=scalar,
        sample_rate_hz=10.0,
        averaging_period_s=240.0,
    )
    failures: list[str] = []
    for result in (ml, fs):
        method = str(result.get("method", ""))
        if result.get("status") != "ok":
            failures.append(f"{method}:status={result.get('status')}")
        if not _positive_number(result.get("random_error")):
            failures.append(f"{method}:random_error_not_positive")
        lower = result.get("interval_lower")
        upper = result.get("interval_upper")
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)) or lower >= upper:
            failures.append(f"{method}:invalid_uncertainty_band")
    return _case_payload(
        case_id="random_uncertainty_family_autocorrelation_sweep",
        family="uncertainty",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "mann_lenschow_random_error": ml.get("random_error"),
            "finkelstein_sims_random_error": fs.get("random_error"),
            "mann_lenschow_relative_error": ml.get("relative_error"),
            "finkelstein_sims_relative_error": fs.get("relative_error"),
        },
        details={"mann_lenschow": ml, "finkelstein_sims": fs},
    )


def _spectral_correction_stress_case() -> dict[str, Any]:
    methods = ["massman", "horst", "ibrom", "fratini"]
    freq = np.geomspace(0.001, 5.0, 128)
    measured = np.exp(-freq / 0.8) / np.sqrt(freq)
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    for method in methods:
        result = compute_spectral_correction(
            method=method,
            path_length_m=0.18,
            sensor_sep_m=0.24,
            response_time_s=0.13,
            sample_rate_hz=20.0,
            averaging_period_s=1800.0,
            wind_speed=3.2,
            z_m=4.0,
            ustar=0.42,
            ol=-80.0,
            measured_cospectrum_freq=freq if method == "fratini" else None,
            measured_cospectrum_value=measured if method == "fratini" else None,
        )
        factor = result.get("correction_factor")
        if result.get("status") != "ok":
            failures.append(f"{method}:status={result.get('status')}")
        if not isinstance(factor, (int, float)) or not math.isfinite(float(factor)) or float(factor) < 1.0:
            failures.append(f"{method}:invalid_correction_factor={factor}")
        if method == "fratini" and not bool(result.get("components", {}).get("uses_measured_cospectrum")):
            failures.append("fratini:measured_cospectrum_not_used")
        results.append(
            {
                "method": method,
                "status": result.get("status"),
                "correction_factor": factor,
                "provenance": result.get("provenance", ""),
                "components": result.get("components", {}),
            }
        )
    return _case_payload(
        case_id="spectral_correction_family_measured_cospectrum_sweep",
        family="spectral_correction",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "method_count": len(methods),
            "max_correction_factor": max(float(item["correction_factor"]) for item in results),
            "fratini_measured_cospectrum_used": bool(results[-1]["components"].get("uses_measured_cospectrum")),
        },
        details={"results": results},
    )


def _ch4_li7700_stress_case() -> dict[str, Any]:
    rows = _make_li7700_rows()
    status = compute_li7700_status_diagnostics(
        rows=rows,
        config={"min_rssi_warning_pct": 40.0, "min_rssi_fail_pct": 20.0, "require_lock": True},
    )
    sequence = compute_li7700_correction_sequence(
        ch4_metrics={
            "status": "computed",
            "selected_method": "li_7700_level0_covariance",
            "ch4_flux_nmol_m2_s": 12.4,
        },
        mean_h2o_mmol=18.0,
        mean_pressure_kpa=98.7,
        mean_temp_c=27.0,
        spectral_correction_factor=1.18,
        config={
            "coefficient_profile_id": "stress_li7700_profile",
            "coefficient_registry_status": "source_derived_stress",
            "coefficient_profile_provenance": "deterministic stress profile",
            "li7700_status_diagnostics": status,
            "spectroscopic_correction": {
                "mode": "empirical",
                "pressure_coefficient": 0.0008,
                "temperature_coefficient": 0.0012,
                "h2o_coefficient": 0.08,
            },
            "self_heating_correction": {
                "enabled": True,
                "slope_per_c": 0.0004,
                "reference_temp_c": 20.0,
            },
        },
    )
    failures: list[str] = []
    if status.get("status") != "pass":
        failures.append(f"li7700_status={status.get('status')}")
    if sequence.get("status") != "computed":
        failures.append(f"li7700_sequence={sequence.get('status')}")
    if not _positive_number(sequence.get("final_flux_nmol_m2_s")):
        failures.append("li7700_final_flux_not_positive")
    levels = dict(sequence.get("levels", {}) or {})
    if set(levels) != {"level0", "level1", "level2", "level3"}:
        failures.append("li7700_levels_incomplete")
    if float(sequence.get("water_vapor_dilution_factor", 0.0) or 0.0) < 1.0:
        failures.append("li7700_density_factor_lt_one")
    return _case_payload(
        case_id="ch4_li7700_correction_sequence_policy_sweep",
        family="ch4_li7700",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={
            "status_diagnostics_status": status.get("status"),
            "rssi_min_pct": status.get("rssi_min_pct"),
            "final_flux_nmol_m2_s": sequence.get("final_flux_nmol_m2_s"),
            "spectral_correction_factor": sequence.get("spectral_correction_factor"),
            "water_vapor_dilution_factor": sequence.get("water_vapor_dilution_factor"),
        },
        details={"li7700_status_diagnostics": status, "li7700_correction_sequence": sequence},
    )


def _long_autocorrelation_uncertainty_case() -> dict[str, Any]:
    rng = np.random.default_rng(20260603)
    n = 6000
    w = rng.normal(0.0, 0.35, n)
    scalar = 0.5 * np.roll(w, 7) + rng.normal(0.0, 0.12, n)
    result = compute_uncertainty_finkelstein_sims(
        w_series=w,
        scalar_series=scalar,
        sample_rate_hz=20.0,
        averaging_period_s=300.0,
    )
    failures = [] if result.get("status") == "ok" and _positive_number(result.get("random_error")) else ["long_fs_uncertainty_failed"]
    return _case_payload(
        case_id="slow_random_uncertainty_long_autocorrelation",
        family="uncertainty",
        status="pass" if not failures else "fail",
        failure_reasons=failures,
        metrics={"random_error": result.get("random_error"), "n_samples": n},
        details={"finkelstein_sims": result},
    )


def _make_li7700_rows(samples: int = 120) -> list[NormalizedHFFrame]:
    start = datetime(2026, 6, 2, 9, 0, 0)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        payload = {
            "u": 2.4 + 0.1 * math.sin(index / 9.0),
            "v": 0.2 * math.cos(index / 13.0),
            "w": 0.35 * math.sin(index / 5.0),
            "li7700_rssi": 72.0 + 4.0 * math.sin(index / 17.0),
            "li7700_signal_strength": 75.0 + 3.0 * math.cos(index / 19.0),
            "mirror_dirty": False,
            "pll_lock": True,
            "li7700_status_word": 0,
        }
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=index / 10.0),
                device_uid="stress-li7700",
                device_id="LI7700",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=410.0,
                h2o_mmol=18.0,
                pressure_kpa=98.7,
                chamber_temp_c=27.0,
                ch4_ppb=1900.0 + 4.0 * math.sin(index / 6.0),
                raw_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            )
        )
    return rows


def _make_multi_gas_rows(samples: int = 1200, sample_rate_hz: float = 10.0) -> list[NormalizedHFFrame]:
    start = datetime(2026, 6, 4, 9, 0, 0)
    axis = np.arange(samples, dtype=float) / sample_rate_hz
    w = 0.46 * np.sin(2.0 * np.pi * 0.18 * axis) + 0.09 * np.cos(2.0 * np.pi * 0.59 * axis)
    u = 2.45 + 0.14 * np.sin(2.0 * np.pi * 0.03 * axis)
    v = 0.22 * np.cos(2.0 * np.pi * 0.04 * axis)
    co2 = 410.0 + 8.0 * np.roll(w, 4) + 0.04 * np.sin(2.0 * np.pi * 0.9 * axis)
    h2o = 12.2 + 1.05 * np.roll(w, 2) + 0.02 * np.cos(2.0 * np.pi * 0.7 * axis)
    ch4 = 1905.0 + 36.0 * w
    n2o = 332.0 + 1.8 * np.roll(w, 3)
    pressure = 101.25 + 0.03 * np.sin(2.0 * np.pi * 0.02 * axis)
    temp = 24.7 + 0.35 * np.sin(2.0 * np.pi * 0.05 * axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(axis[index])),
                device_uid="stress-multi-gas",
                device_id="multi-gas-li7700",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(co2[index]),
                h2o_mmol=float(h2o[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                ch4_ppb=float(ch4[index]),
                raw_text=json.dumps(
                    {
                        "u": float(u[index]),
                        "v": float(v[index]),
                        "w": float(w[index]),
                        "n2o_ppb": float(n2o[index]),
                        "li7700_rssi": float(68.0 + 2.5 * np.sin(2.0 * np.pi * 0.02 * axis[index])),
                        "li7700_signal_strength": float(74.0 + 1.5 * np.cos(2.0 * np.pi * 0.03 * axis[index])),
                        "mirror_rssi": 82.0,
                        "mirror_dirty": False,
                        "pll_locked": True,
                        "diagnostic_status": "ok",
                        "li7700_status_word": 0,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    return rows


def _fp2_word(value: float, decimals: int) -> int:
    sign_bit = 0x80 if value < 0 else 0
    mantissa = int(round(abs(value) * (10**decimals)))
    low_byte = sign_bit | ((decimals & 0x03) << 5) | ((mantissa >> 8) & 0x1F)
    high_byte = mantissa & 0xFF
    return (high_byte << 8) | low_byte


def _case_payload(
    *,
    case_id: str,
    family: str,
    status: str,
    failure_reasons: list[str],
    metrics: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": family,
        "status": status,
        "failure_reasons": failure_reasons,
        "metrics": metrics,
        "details": details,
        "claim_boundary": {
            "source_derived_stress_evidence": status == "pass",
            "official_numeric_parity_evidence": False,
        },
    }


def _computation_surface(cases: list[dict[str, Any]]) -> dict[str, Any]:
    required_families = [
        "pipeline_core",
        "raw_biomet_ingestion",
        "raw_import_edge_cases",
        "rotation_lag",
        "flux_density_energy",
        "multi_gas_final_flux",
        "footprint",
        "uncertainty",
        "spectral_correction",
        "ch4_li7700",
    ]
    case_by_family = {str(case.get("family", "")): case for case in cases}
    family_status = {
        family: str(dict(case_by_family.get(family, {}) or {}).get("status", "missing"))
        for family in required_families
    }
    blocked = [
        {
            "family": family,
            "status": status,
            "case_id": str(dict(case_by_family.get(family, {}) or {}).get("case_id", "")),
            "failure_reasons": list(dict(case_by_family.get(family, {}) or {}).get("failure_reasons", []) or []),
        }
        for family, status in family_status.items()
        if status != "pass"
    ]
    return {
        "status": "ready" if not blocked else "blocked",
        "required_families": required_families,
        "ready_family_count": len(required_families) - len(blocked),
        "blocked_family_count": len(blocked),
        "family_status": family_status,
        "blocked_families": blocked,
        "can_keep_program_closed_without_real_data": not blocked,
        "does_not_replace_official_eddypro_numeric_parity": True,
    }


def _ordered_contribution_distances(values: dict[str, Any]) -> bool:
    ordered = [float(values.get(key, 0.0) or 0.0) for key in ("x10", "x30", "x50", "x70", "x90")]
    return all(value > 0.0 for value in ordered) and ordered == sorted(ordered)


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0.0


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _close(value: Any, expected: Any, *, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    if not _finite_number(value) or not _finite_number(expected):
        return False
    return math.isclose(float(value), float(expected), rel_tol=rel_tol, abs_tol=abs_tol)
