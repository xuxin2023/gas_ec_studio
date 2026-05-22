from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.acquisition.runtime_install import (
    build_installable_runtime_profile,
    build_runtime_deployment_artifact,
    has_runtime_install_config,
)
from core.ec_rp.analysis import generate_reference_provenance
from core.exports.report_exporter import write_report_snapshot
from models.rp_models import RPRunResult, WindowRPResult
from models.spectral_models import SpectralRunResult, WindowSpectralResult


FULL_OUTPUT_SCHEMA = [
    ("window_id", "diagnostics", "real"),
    ("start_time", "diagnostics", "real"),
    ("end_time", "diagnostics", "real"),
    ("qc_grade", "diagnostics", "real"),
    ("lag_seconds", "lag", "real"),
    ("lag_confidence", "lag", "real"),
    ("lag_strategy", "lag", "real"),
    ("lag_fallback_reason", "lag", "estimated"),
    ("rotation_mode", "rotation", "real"),
    ("detrend_mode", "rotation", "real"),
    ("raw_flux", "flux", "real"),
    ("density_corrected_flux", "flux", "real"),
    ("correction_factor", "flux", "real"),
    ("corrected_flux_after", "flux", "real"),
    ("stationarity_score", "turbulence", "real"),
    ("turbulence_score", "turbulence", "real"),
    ("ustar", "turbulence", "real"),
    ("relative_uncertainty", "uncertainty", "estimated"),
    ("primary_flux_random_error", "uncertainty", "estimated"),
    ("primary_flux_relative_uncertainty", "uncertainty", "estimated"),
    ("primary_flux_uncertainty_band", "uncertainty", "estimated"),
    ("primary_flux_ci_lower", "uncertainty", "estimated"),
    ("primary_flux_ci_upper", "uncertainty", "estimated"),
    ("primary_flux_ci_level", "uncertainty", "estimated"),
    ("uncertainty_status", "uncertainty", "estimated"),
    ("uncertainty_provenance", "uncertainty", "estimated"),
    ("var_u", "variances", "real"),
    ("var_v", "variances", "real"),
    ("var_w", "variances", "real"),
    ("cov_uw", "covariances", "real"),
    ("cov_vw", "covariances", "real"),
    ("turbulence_intermediate", "turbulence", "real"),
    ("diagnostics_flags", "diagnostics", "real"),
    ("diagnostics_issues", "diagnostics", "real"),
    ("screening_detail", "diagnostics", "real"),
    ("screening_config", "diagnostics", "real"),
    ("density_correction_mode", "flux", "real"),
    ("density_correction_reason", "flux", "real"),
    ("primary_flux", "flux", "real"),
    ("primary_flux_source", "flux", "real"),
    ("sonic_correction_status", "preprocessing", "real"),
    ("sonic_correction_method", "preprocessing", "real"),
    ("sonic_correction_steps", "preprocessing", "real"),
    ("sonic_correction_provenance", "preprocessing", "real"),
    ("sonic_correction_detail", "preprocessing", "real"),
    ("crosswind_correction_status", "preprocessing", "real"),
    ("crosswind_correction_method", "preprocessing", "real"),
    ("crosswind_correction_mean_delta_c", "preprocessing", "real"),
    ("crosswind_correction_max_abs_delta_c", "preprocessing", "real"),
    ("crosswind_correction_provenance", "preprocessing", "real"),
    ("crosswind_correction_detail", "preprocessing", "real"),
    ("clock_sync_status", "acquisition", "real"),
    ("clock_sync_method", "acquisition", "real"),
    ("clock_sync_source", "acquisition", "real"),
    ("clock_sync_mean_offset_s", "acquisition", "real"),
    ("clock_sync_min_offset_s", "acquisition", "real"),
    ("clock_sync_max_offset_s", "acquisition", "real"),
    ("clock_sync_provenance", "acquisition", "real"),
    ("clock_sync_detail", "acquisition", "real"),
    ("runtime_watchdog_status", "acquisition", "real"),
    ("runtime_watchdog_profile", "acquisition", "real"),
    ("runtime_watchdog_fail_count", "acquisition", "real"),
    ("runtime_watchdog_warn_count", "acquisition", "real"),
    ("runtime_watchdog_detail", "acquisition", "real"),
    ("runtime_service_status", "acquisition", "real"),
    ("runtime_service_id", "acquisition", "real"),
    ("runtime_service_run_id", "acquisition", "real"),
    ("runtime_service_delivery_state", "acquisition", "real"),
    ("runtime_service_quarantine_count", "acquisition", "real"),
    ("runtime_service_restart_count", "acquisition", "real"),
    ("runtime_service_detail", "acquisition", "real"),
    ("daemon_telemetry_status", "acquisition", "real"),
    ("supervisor_state", "acquisition", "real"),
    ("ptp_lock_status", "acquisition", "real"),
    ("gps_pps_lock_status", "acquisition", "real"),
    ("hardware_watchdog_status", "acquisition", "real"),
    ("os_supervisor_status", "acquisition", "real"),
    ("os_supervisor_state", "acquisition", "real"),
    ("watchdog_provider_status", "acquisition", "real"),
    ("installable_runtime_status", "acquisition", "real"),
    ("installable_runtime_profile_id", "acquisition", "real"),
    ("installable_runtime_targets", "acquisition", "real"),
    ("runtime_deployment_status", "acquisition", "real"),
    ("runtime_deployment_execution_mode", "acquisition", "real"),
    ("installable_runtime_detail", "acquisition", "real"),
    ("supervisor_integration_detail", "acquisition", "real"),
    ("daemon_telemetry_detail", "acquisition", "real"),
    ("ch4_status", "trace_gas", "real"),
    ("ch4_flux_nmol_m2_s", "trace_gas", "real"),
    ("ch4_flux_level0_nmol_m2_s", "trace_gas", "real"),
    ("ch4_flux_level1_spectral_nmol_m2_s", "trace_gas", "real"),
    ("ch4_flux_level2_density_nmol_m2_s", "trace_gas", "real"),
    ("ch4_flux_corrected_nmol_m2_s", "trace_gas", "real"),
    ("cov_w_ch4_ppb", "trace_gas", "real"),
    ("mean_ch4_ppb", "trace_gas", "real"),
    ("ch4_valid_ratio", "trace_gas", "real"),
    ("ch4_method", "trace_gas", "real"),
    ("ch4_coefficient_profile_id", "trace_gas", "real"),
    ("ch4_coefficient_registry_status", "trace_gas", "real"),
    ("ch4_coefficient_profile_source_file", "trace_gas", "real"),
    ("ch4_coefficient_profile_provenance", "trace_gas", "real"),
    ("ch4_spectral_correction_factor", "trace_gas", "real"),
    ("ch4_water_vapor_dilution_factor", "trace_gas", "real"),
    ("ch4_spectroscopic_correction_factor", "trace_gas", "real"),
    ("ch4_self_heating_correction_factor", "trace_gas", "real"),
    ("ch4_correction_sequence", "trace_gas", "real"),
    ("ch4_provenance", "trace_gas", "real"),
    ("ch4_limitations", "trace_gas", "real"),
    ("ch4_detail", "trace_gas", "real"),
    ("trace_gas_family", "trace_gas", "real"),
    ("requested_rotation_mode", "rotation", "real"),
    ("applied_rotation_impl", "rotation", "real"),
    ("lag_fallback_reason", "lag", "real"),
    ("screening_summary", "diagnostics", "real"),
    ("qc_details", "diagnostics", "real"),
    ("metadata_summary", "diagnostics", "real"),
    ("wpl_water_vapor_term", "flux", "real"),
    ("wpl_sensible_heat_term", "flux", "real"),
    ("advanced_qc_contribution", "diagnostics", "real"),
    ("advanced_test_weights", "diagnostics", "real"),
    ("advanced_test_thresholds", "diagnostics", "real"),
    ("wpl_benchmark_status", "diagnostics", "real"),
    ("benchmark_status", "benchmark", "real"),
    ("benchmark_target", "benchmark", "real"),
    ("benchmark_deviation_summary", "benchmark", "real"),
    ("benchmark_reference_id", "benchmark", "real"),
    ("benchmark_thresholds", "benchmark", "real"),
    ("continuous_dataset_enabled", "diagnostics", "real"),
    ("footprint_peak_distance_m", "footprint", "real"),
    ("footprint_method", "footprint", "real"),
    ("footprint_offset_distance_m", "footprint", "real"),
    ("footprint_contribution_distances", "footprint", "real"),
    ("footprint_2d_grid_status", "footprint", "real"),
    ("footprint_2d_peak_downwind_m", "footprint", "real"),
    ("footprint_2d_peak_crosswind_m", "footprint", "real"),
    ("footprint_2d_half_width_m", "footprint", "real"),
    ("footprint_2d_contribution_contours_m", "footprint", "real"),
    ("uncertainty_method", "uncertainty", "real"),
    ("uncertainty_method_detail", "uncertainty", "real"),
    ("spectral_correction_method", "spectral", "real"),
    ("spectral_correction_factor", "spectral", "real"),
    ("spectral_correction_detail", "spectral", "real"),
    ("spectral_correction_provenance", "spectral", "real"),
    ("spectral_correction_measured_cospectrum_enabled", "spectral", "real"),
    ("spectral_correction_measured_cospectrum_used", "spectral", "real"),
    ("spectral_correction_measured_cospectrum_source", "spectral", "real"),
    ("spectral_correction_cospectrum_match", "spectral", "real"),
    ("spectral_correction_limitations", "spectral", "real"),
    ("method_compare_summary", "method_compare", "real"),
    ("method_compare_recommendations", "method_compare", "real"),
    ("method_compare_deviation_flags", "method_compare", "real"),
    ("performance_profile", "performance", "real"),
    ("schema_target", "diagnostics", "real"),
    ("fluxnet_timestamp_refers_to", "diagnostics", "real"),
    ("fluxnet_timezone_offset_h", "diagnostics", "real"),
    ("fluxnet_gap_fill_value", "diagnostics", "real"),
]


class ResultExporter:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.exports_root = self.runtime_root / "exports" / "results"
        self.exports_root.mkdir(parents=True, exist_ok=True)

    def export_minimal_bundle(
        self,
        *,
        rp_result: RPRunResult | None,
        spectral_result: SpectralRunResult | None,
        rp_config_snapshot: dict[str, Any],
        spectral_config_snapshot: dict[str, Any],
        project: object,
        site: object,
        report_payload: dict[str, Any],
        report_key: str,
        full_output_mode: str = "only_available",
    ) -> dict[str, Any]:
        timestamp = datetime.now()
        suffix = self._bundle_suffix(rp_result=rp_result, spectral_result=spectral_result, timestamp=timestamp)
        export_root = self.exports_root / suffix
        export_root.mkdir(parents=True, exist_ok=True)

        rp_results_path = export_root / "rp_results.csv"
        spectral_results_path = export_root / "spectral_qc_results.csv"
        full_output_path = export_root / "full_output.csv"
        summary_path = export_root / "summary.json"
        config_path = export_root / "config_snapshot.json"
        project_site_path = export_root / "project_site_snapshot.json"
        manifest_path = export_root / "export_manifest.json"

        self._write_csv(rp_results_path, [self._rp_row(window) for window in (rp_result.windows if rp_result else [])], self._rp_headers())
        self._write_csv(spectral_results_path, [self._spectral_row(window) for window in (spectral_result.windows if spectral_result else [])], self._spectral_headers())
        full_output_rows = self._full_output_rows(rp_result=rp_result, spectral_result=spectral_result, mode=full_output_mode)
        full_output_headers = self._full_output_headers(mode=full_output_mode)
        self._write_csv(full_output_path, full_output_rows, full_output_headers)
        benchmark_rollup = self._benchmark_rollup(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        method_summary = self._method_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        trace_gas_summary = self._trace_gas_summary(rp_result=rp_result)
        method_rollup_path = self.export_method_rollup_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        footprint_2d_path = self.export_footprint_2d_artifact(
            rp_result=rp_result,
            export_root=export_root,
        )
        method_compare_path = self.export_method_compare_artifact(
            rp_result=rp_result,
            export_root=export_root,
        )
        performance_profile_path = self.export_performance_profile_artifact(
            rp_result=rp_result,
            export_root=export_root,
        )
        runtime_watchdog_path = self.export_runtime_watchdog_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        runtime_service_path = self.export_runtime_service_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        daemon_telemetry_path = self.export_daemon_telemetry_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        supervisor_integration_path = self.export_supervisor_integration_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        installable_runtime_path = self.export_installable_runtime_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        runtime_deployment_path, runtime_deployment_files = self.export_runtime_deployment_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        clock_sync_path = self.export_clock_sync_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        method_parity_matrix_path = self.export_method_parity_matrix_artifact(
            rp_result=rp_result,
            export_root=export_root,
            reference_id=benchmark_rollup["benchmark_reference_id"],
        )
        method_parity_companion_files: dict[str, str] = {}
        footprint_2d_companion_files: dict[str, str] = {}
        benchmark_results = benchmark_rollup["benchmark_results"]
        benchmark_summary_path = self.export_benchmark_summary_artifact(
            rp_result=rp_result,
            benchmark_results=benchmark_results,
            export_root=export_root,
            reference_id=benchmark_rollup["benchmark_reference_id"],
            thresholds=benchmark_rollup["benchmark_thresholds"],
        )
        parity_artifact_path = self.export_parity_artifact(
            rp_result=rp_result,
            benchmark_results=benchmark_results,
            export_root=export_root,
            reference_id=benchmark_rollup["benchmark_reference_id"],
            thresholds=benchmark_rollup["benchmark_thresholds"],
        )
        reference_provenance_path = self.export_reference_provenance_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        reference_provenance = self._reference_provenance_payload(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        network_validation, network_files = self._export_network_artifacts(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
            site=site,
        )

        exported_files = [
            "rp_results.csv",
            "spectral_qc_results.csv",
            "full_output.csv",
            "summary.json",
            "config_snapshot.json",
            "project_site_snapshot.json",
            "report_snapshot.json",
            "export_manifest.json",
        ]
        if benchmark_summary_path is not None:
            exported_files.append(benchmark_summary_path.name)
        if method_rollup_path is not None:
            exported_files.append(method_rollup_path.name)
        if footprint_2d_path is not None:
            exported_files.append(footprint_2d_path.name)
        if method_compare_path is not None:
            exported_files.append(method_compare_path.name)
        if performance_profile_path is not None:
            exported_files.append(performance_profile_path.name)
        if runtime_watchdog_path is not None:
            exported_files.append(runtime_watchdog_path.name)
        if runtime_service_path is not None:
            exported_files.append(runtime_service_path.name)
        if daemon_telemetry_path is not None:
            exported_files.append(daemon_telemetry_path.name)
        if supervisor_integration_path is not None:
            exported_files.append(supervisor_integration_path.name)
        if installable_runtime_path is not None:
            exported_files.append(installable_runtime_path.name)
        if runtime_deployment_path is not None:
            exported_files.append(runtime_deployment_path.name)
        for path in runtime_deployment_files.values():
            exported_files.append(Path(path).name)
        if clock_sync_path is not None:
            exported_files.append(clock_sync_path.name)
        if method_parity_matrix_path is not None:
            exported_files.append(method_parity_matrix_path.name)
            try:
                matrix_payload = json.loads(method_parity_matrix_path.read_text(encoding="utf-8"))
                method_parity_companion_files = dict(matrix_payload.get("companion_files", {}) or {})
                for companion in method_parity_companion_files.values():
                    if companion:
                        exported_files.append(Path(companion).name)
            except (json.JSONDecodeError, OSError):
                pass
        if footprint_2d_path is not None:
            try:
                footprint_payload = json.loads(footprint_2d_path.read_text(encoding="utf-8"))
                footprint_2d_companion_files = dict(footprint_payload.get("companion_files", {}) or {})
                for companion in footprint_2d_companion_files.values():
                    if companion:
                        exported_files.append(Path(companion).name)
            except (json.JSONDecodeError, OSError):
                pass
        if parity_artifact_path is not None:
            exported_files.append(parity_artifact_path.name)
        if reference_provenance_path is not None:
            exported_files.append(reference_provenance_path.name)
        for path in network_files.values():
            exported_files.append(Path(path).name)
        exported_files = list(dict.fromkeys(exported_files))
        self._write_json(
            summary_path,
            {
                "exported_at": timestamp.isoformat(),
                "rp_run": self._run_summary(rp_result),
                "spectral_run": self._run_summary(spectral_result),
                "benchmark": {
                    "status": benchmark_rollup["benchmark_status"],
                    "target": benchmark_rollup["benchmark_target"],
                    "reference_id": benchmark_rollup["benchmark_reference_id"],
                    "pass_rate": benchmark_rollup["pass_rate"],
                    "failed_fields": benchmark_rollup["failed_fields"],
                    "deviation_summary": benchmark_rollup["benchmark_deviation_summary"],
                },
                "method_summary": method_summary,
                "trace_gas_summary": trace_gas_summary,
                "method_rollup_artifact": str(method_rollup_path) if method_rollup_path is not None else "",
                "footprint_2d_artifact": str(footprint_2d_path) if footprint_2d_path is not None else "",
                "method_compare_artifact": str(method_compare_path) if method_compare_path is not None else "",
                "method_parity_matrix_artifact": str(method_parity_matrix_path) if method_parity_matrix_path is not None else "",
                "performance_profile_artifact": str(performance_profile_path) if performance_profile_path is not None else "",
                "runtime_watchdog_artifact": str(runtime_watchdog_path) if runtime_watchdog_path is not None else "",
                "runtime_watchdog_summary": self._runtime_watchdog_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "runtime_service_artifact": str(runtime_service_path) if runtime_service_path is not None else "",
                "runtime_service_summary": self._runtime_service_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "daemon_telemetry_artifact": str(daemon_telemetry_path) if daemon_telemetry_path is not None else "",
                "daemon_telemetry_summary": self._daemon_telemetry_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "supervisor_integration_artifact": str(supervisor_integration_path) if supervisor_integration_path is not None else "",
                "supervisor_integration_summary": self._supervisor_integration_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "installable_runtime_artifact": str(installable_runtime_path) if installable_runtime_path is not None else "",
                "installable_runtime_summary": self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "runtime_deployment_artifact": str(runtime_deployment_path) if runtime_deployment_path is not None else "",
                "runtime_deployment_summary": self._runtime_deployment_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "clock_sync_artifact": str(clock_sync_path) if clock_sync_path is not None else "",
                "clock_sync_summary": self._clock_sync_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "reference_provenance": reference_provenance,
                "network_validation": network_validation,
                "exported_files": exported_files,
            },
        )
        self._write_json(config_path, {"rp_config_snapshot": rp_config_snapshot, "spectral_config_snapshot": spectral_config_snapshot})
        self._write_json(project_site_path, {"project": self._to_jsonable(project), "site": self._to_jsonable(site)})
        report_snapshot_path = write_report_snapshot(export_root=export_root, report_payload=report_payload, report_key=report_key)
        manifest_payload = {
            "exported_at": timestamp.isoformat(),
            "full_output_mode": full_output_mode,
            "data_sources": {
                "rp_run_id": rp_result.run_id if rp_result else None,
                "spectral_run_id": spectral_result.run_id if spectral_result else None,
            },
            "screening_config": self._extract_screening_config(rp_config_snapshot),
            "advanced_test_thresholds": self._extract_advanced_test_thresholds(rp_config_snapshot),
            "benchmark_status": benchmark_rollup["benchmark_status"],
            "benchmark_target": benchmark_rollup["benchmark_target"],
            "benchmark_reference_id": benchmark_rollup["benchmark_reference_id"],
            "benchmark_thresholds": benchmark_rollup["benchmark_thresholds"],
            "benchmark_deviation_summary": benchmark_rollup["benchmark_deviation_summary"],
            "pass_rate": benchmark_rollup["pass_rate"],
            "failed_fields": benchmark_rollup["failed_fields"],
            "reference_provenance": reference_provenance,
            "continuous_dataset_enabled": bool(rp_config_snapshot.get("continuous_dataset", {}).get("enabled", False)),
            "density_correction_mode": rp_config_snapshot.get("density_correction_mode", "wpl"),
            "rotation_mode": rp_config_snapshot.get("rotation_mode", "double"),
            "detrend_mode": rp_config_snapshot.get("detrend_mode", "block_mean"),
            "lag_strategy": rp_config_snapshot.get("lag_phase", {}).get("strategy", ""),
            "footprint_method": method_summary.get("footprint_method", ""),
            "footprint_summary": method_summary.get("footprint_summary", {}),
            "footprint_provenance": method_summary.get("footprint_summary", {}).get("provenance", ""),
            "uncertainty_method": method_summary.get("uncertainty_method", ""),
            "uncertainty_summary": method_summary.get("uncertainty_summary", {}),
            "uncertainty_provenance": method_summary.get("uncertainty_summary", {}).get("provenance", ""),
            "spectral_correction_method": method_summary.get("spectral_correction_method", ""),
            "spectral_correction_summary": method_summary.get("spectral_correction_summary", {}),
            "spectral_correction_provenance": method_summary.get("spectral_correction_summary", {}).get("provenance", ""),
            "method_rollup": method_summary,
            "trace_gas_summary": trace_gas_summary,
            "trace_gas_fields": [
                "ch4_status",
                "ch4_flux_nmol_m2_s",
                "ch4_flux_level0_nmol_m2_s",
                "ch4_flux_level1_spectral_nmol_m2_s",
                "ch4_flux_level2_density_nmol_m2_s",
                "ch4_flux_corrected_nmol_m2_s",
                "cov_w_ch4_ppb",
                "mean_ch4_ppb",
                "ch4_valid_ratio",
                "ch4_method",
                "ch4_coefficient_profile_id",
                "ch4_coefficient_registry_status",
                "ch4_coefficient_profile_source_file",
                "ch4_coefficient_profile_provenance",
                "ch4_spectral_correction_factor",
                "ch4_water_vapor_dilution_factor",
                "ch4_spectroscopic_correction_factor",
                "ch4_self_heating_correction_factor",
                "ch4_correction_sequence",
                "ch4_provenance",
                "ch4_limitations",
            ],
            "method_rollup_artifact": str(method_rollup_path) if method_rollup_path is not None else "",
            "footprint_2d_summary": method_summary.get("footprint_2d_summary", {}),
            "footprint_2d_artifact": str(footprint_2d_path) if footprint_2d_path is not None else "",
            "footprint_2d_contour_svg": str(footprint_2d_companion_files.get("contour_svg", "")),
            "footprint_2d_grid_csv": str(footprint_2d_companion_files.get("grid_csv", "")),
            "method_compare_summary": method_summary.get("method_compare_summary", {}),
            "method_compare_recommendations": method_summary.get("method_compare_recommendations", {}),
            "method_compare_artifact": str(method_compare_path) if method_compare_path is not None else "",
            "method_parity_matrix": self._method_parity_matrix(rp_result=rp_result, reference_id=benchmark_rollup["benchmark_reference_id"]),
            "method_parity_matrix_artifact": str(method_parity_matrix_path) if method_parity_matrix_path is not None else "",
            "method_parity_matrix_csv": str(method_parity_companion_files.get("csv", "")),
            "performance_profile": self._performance_profile_payload(rp_result=rp_result),
            "performance_profile_artifact": str(performance_profile_path) if performance_profile_path is not None else "",
            "runtime_watchdog_summary": self._runtime_watchdog_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "runtime_watchdog_artifact": str(runtime_watchdog_path) if runtime_watchdog_path is not None else "",
            "runtime_service_summary": self._runtime_service_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "runtime_service_artifact": str(runtime_service_path) if runtime_service_path is not None else "",
            "daemon_telemetry_summary": self._daemon_telemetry_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "daemon_telemetry_artifact": str(daemon_telemetry_path) if daemon_telemetry_path is not None else "",
            "supervisor_integration_summary": self._supervisor_integration_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "supervisor_integration_artifact": str(supervisor_integration_path) if supervisor_integration_path is not None else "",
            "installable_runtime_summary": self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "installable_runtime_artifact": str(installable_runtime_path) if installable_runtime_path is not None else "",
            "runtime_deployment_summary": self._runtime_deployment_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "runtime_deployment_artifact": str(runtime_deployment_path) if runtime_deployment_path is not None else "",
            "runtime_deployment_scripts": runtime_deployment_files,
            "clock_sync_summary": self._clock_sync_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "clock_sync_artifact": str(clock_sync_path) if clock_sync_path is not None else "",
            "schema_target": network_validation.get("schema_target", ""),
            "network_validation_status": network_validation.get("validation_status", ""),
            "network_missing_fields": network_validation.get("missing_fields", []),
            "network_validation_summary": network_validation,
            "network_method_fields": [
                "FOOTPRINT_METHOD",
                "UNCERTAINTY_METHOD",
                "SPECTRAL_CORRECTION_METHOD",
                "METHOD_DEVIATION_NOTES",
                "CLOCK_SYNC_STATUS",
                "CLOCK_SYNC_METHOD",
                "CLOCK_SYNC_SOURCE",
                "CLOCK_SYNC_MEAN_OFFSET_S",
                "RUNTIME_WATCHDOG_STATUS",
                "RUNTIME_WATCHDOG_PROFILE",
                "RUNTIME_WATCHDOG_FAIL_COUNT",
                "RUNTIME_SERVICE_STATUS",
                "RUNTIME_SERVICE_DELIVERY_STATE",
                "RUNTIME_SERVICE_QUARANTINE_COUNT",
                "DAEMON_TELEMETRY_STATUS",
                "SUPERVISOR_STATE",
                "PTP_LOCK_STATUS",
                "GPS_PPS_LOCK_STATUS",
                "HARDWARE_WATCHDOG_STATUS",
                "OS_SUPERVISOR_STATUS",
                "OS_SUPERVISOR_STATE",
                "WATCHDOG_PROVIDER_STATUS",
                "INSTALLABLE_RUNTIME_STATUS",
                "INSTALLABLE_RUNTIME_TARGETS",
                "RUNTIME_DEPLOYMENT_STATUS",
            ],
            "network_uncertainty_fields": [
                "FC_RANDOM_ERROR",
                "FC_REL_UNCERTAINTY",
                "FC_CI_LOWER",
                "FC_CI_UPPER",
                "FC_CI_LEVEL",
            ],
            "network_trace_gas_fields": [
                "FCH4",
                "FCH4_QC",
            ],
            "method_provenance_fields": [
                "primary_flux_source",
                "applied_rotation_impl",
                "requested_rotation_mode",
                "lag_strategy",
                "lag_fallback_reason",
                "density_correction_mode",
                "density_correction_reason",
                "sonic_correction_method",
                "sonic_correction_status",
                "sonic_correction_provenance",
                "crosswind_correction_method",
                "crosswind_correction_status",
                "crosswind_correction_provenance",
                "clock_sync_status",
                "clock_sync_method",
                "clock_sync_source",
                "clock_sync_mean_offset_s",
                "clock_sync_provenance",
                "runtime_watchdog_status",
                "runtime_watchdog_profile",
                "runtime_watchdog_fail_count",
                "runtime_watchdog_warn_count",
                "runtime_service_status",
                "runtime_service_id",
                "runtime_service_delivery_state",
                "runtime_service_quarantine_count",
                "runtime_service_restart_count",
                "daemon_telemetry_status",
                "supervisor_state",
                "ptp_lock_status",
                "gps_pps_lock_status",
                "hardware_watchdog_status",
                "os_supervisor_status",
                "os_supervisor_state",
                "watchdog_provider_status",
                "installable_runtime_status",
                "installable_runtime_profile_id",
                "installable_runtime_targets",
                "runtime_deployment_status",
                "runtime_deployment_execution_mode",
                "screening_config",
                "screening_summary",
                "footprint_method",
                "footprint_provenance",
                "uncertainty_method",
                "uncertainty_provenance",
                "spectral_correction_method",
                "spectral_correction_provenance",
                "spectral_correction_limitations",
                "method_deviation_notes",
            ],
            "field_schema": [
                {"name": name, "group": group, "value_status": value_status}
                for name, group, value_status in FULL_OUTPUT_SCHEMA
                if full_output_mode == "standard_schema" or any(row.get(name) not in ("", None) for row in full_output_rows)
            ],
            "exported_files": exported_files,
        }
        self._write_json(
            manifest_path,
            manifest_payload,
        )
        files = {
            "rp_results": str(rp_results_path),
            "spectral_qc_results": str(spectral_results_path),
            "full_output": str(full_output_path),
            "summary": str(summary_path),
            "config_snapshot": str(config_path),
            "project_site_snapshot": str(project_site_path),
            "report_snapshot": str(report_snapshot_path),
            "export_manifest": str(manifest_path),
        }
        if benchmark_summary_path is not None:
            files["benchmark_summary_artifact"] = str(benchmark_summary_path)
        if method_rollup_path is not None:
            files["method_rollup_artifact"] = str(method_rollup_path)
        if footprint_2d_path is not None:
            files["footprint_2d_artifact"] = str(footprint_2d_path)
        if method_compare_path is not None:
            files["method_compare_artifact"] = str(method_compare_path)
        if performance_profile_path is not None:
            files["performance_profile_artifact"] = str(performance_profile_path)
        if runtime_watchdog_path is not None:
            files["runtime_watchdog_artifact"] = str(runtime_watchdog_path)
        if runtime_service_path is not None:
            files["runtime_service_artifact"] = str(runtime_service_path)
        if daemon_telemetry_path is not None:
            files["daemon_telemetry_artifact"] = str(daemon_telemetry_path)
        if supervisor_integration_path is not None:
            files["supervisor_integration_artifact"] = str(supervisor_integration_path)
        if installable_runtime_path is not None:
            files["installable_runtime_artifact"] = str(installable_runtime_path)
        if runtime_deployment_path is not None:
            files["runtime_deployment_artifact"] = str(runtime_deployment_path)
            files.update(runtime_deployment_files)
        if clock_sync_path is not None:
            files["clock_sync_artifact"] = str(clock_sync_path)
        if method_parity_matrix_path is not None:
            files["method_parity_matrix_artifact"] = str(method_parity_matrix_path)
            try:
                matrix_payload = json.loads(method_parity_matrix_path.read_text(encoding="utf-8"))
                companion_files = dict(matrix_payload.get("companion_files", {}) or {})
                if companion_files.get("csv"):
                    files["method_parity_matrix_csv"] = str(companion_files["csv"])
            except (json.JSONDecodeError, OSError):
                pass
        if footprint_2d_path is not None:
            try:
                footprint_payload = json.loads(footprint_2d_path.read_text(encoding="utf-8"))
                companion_files = dict(footprint_payload.get("companion_files", {}) or {})
                if companion_files.get("contour_svg"):
                    files["footprint_2d_contour_svg"] = str(companion_files["contour_svg"])
                if companion_files.get("grid_csv"):
                    files["footprint_2d_grid_csv"] = str(companion_files["grid_csv"])
            except (json.JSONDecodeError, OSError):
                pass
        if parity_artifact_path is not None:
            files["parity_artifact"] = str(parity_artifact_path)
        if reference_provenance_path is not None:
            files["reference_provenance_artifact"] = str(reference_provenance_path)
            provenance_artifact_payload = json.loads(reference_provenance_path.read_text(encoding="utf-8"))
            for key, file_key in (
                ("copied_source_file", "reference_source_file"),
                ("copied_json_source", "reference_normalized_json"),
                ("copied_provenance_file", "reference_provenance_file"),
            ):
                copied = provenance_artifact_payload.get(key)
                if copied:
                    files[file_key] = str(copied)
        files.update(network_files)
        return {
            "export_root": str(export_root),
            "summary_text": self._summary_text(rp_result=rp_result, spectral_result=spectral_result),
            "files": files,
        }

    def _bundle_suffix(self, *, rp_result: RPRunResult | None, spectral_result: SpectralRunResult | None, timestamp: datetime) -> str:
        if spectral_result is not None:
            return f"result_bundle_{spectral_result.run_id}"
        if rp_result is not None:
            return f"result_bundle_{rp_result.run_id}"
        return f"result_bundle_{timestamp:%Y%m%d_%H%M%S}"

    def _summary_text(self, *, rp_result: RPRunResult | None, spectral_result: SpectralRunResult | None) -> str:
        return f"Exported RP windows={len(rp_result.windows) if rp_result else 0}, spectral/QC windows={len(spectral_result.windows) if spectral_result else 0}."

    def _run_summary(self, run_result: RPRunResult | SpectralRunResult | None) -> dict[str, Any]:
        if run_result is None:
            return {"status": "missing", "run_id": None, "window_count": 0, "summary": {}}
        return {"status": "ok", "run_id": run_result.run_id, "created_at": run_result.created_at.isoformat(), "window_count": len(run_result.windows), "summary": self._to_jsonable(run_result.summary)}

    def _rp_row(self, window: WindowRPResult) -> dict[str, Any]:
        diagnostics = window.diagnostics or {}
        return {
            "window_id": window.window_id,
            "start_time": window.start_time.isoformat(),
            "end_time": window.end_time.isoformat(),
            "sample_count": window.sample_count,
            "valid_sample_count": window.valid_sample_count,
            "continuity_ratio": window.continuity_ratio,
            "missing_ratio": window.missing_ratio,
            "rotation_mode": window.rotation_mode,
            "detrend_mode": window.detrend_mode,
            "lag_seconds": window.lag_seconds,
            "lag_confidence": window.lag_confidence,
            "lag_strategy": window.diagnostics.get("lag_strategy", "") if window.diagnostics else "",
            "cov_w_co2": window.cov_w_co2,
            "cov_w_h2o": window.cov_w_h2o,
            "raw_flux": window.raw_flux,
            "mixing_ratio_flux": window.mixing_ratio_flux,
            "density_corrected_flux": window.density_corrected_flux,
            "primary_flux": window.primary_flux,
            "primary_flux_source": window.primary_flux_source,
            "water_vapor_flux": window.water_vapor_flux,
            "sonic_correction_status": diagnostics.get("sonic_correction_status", ""),
            "sonic_correction_method": diagnostics.get("sonic_correction_method", ""),
            "sonic_correction_steps": json.dumps(diagnostics.get("sonic_correction_steps", []), ensure_ascii=False) if diagnostics.get("sonic_correction_steps") else "",
            "sonic_correction_provenance": diagnostics.get("sonic_correction_provenance", ""),
            "crosswind_correction_status": diagnostics.get("crosswind_correction_status", ""),
            "crosswind_correction_method": diagnostics.get("crosswind_correction_method", ""),
            "crosswind_correction_mean_delta_c": diagnostics.get("crosswind_correction_mean_delta_c", ""),
            "crosswind_correction_max_abs_delta_c": diagnostics.get("crosswind_correction_max_abs_delta_c", ""),
            "crosswind_correction_provenance": diagnostics.get("crosswind_correction_provenance", ""),
            "clock_sync_status": diagnostics.get("clock_sync_status", ""),
            "clock_sync_method": diagnostics.get("clock_sync_method", ""),
            "clock_sync_source": diagnostics.get("clock_sync_source", ""),
            "clock_sync_mean_offset_s": diagnostics.get("clock_sync_mean_offset_s", ""),
            "clock_sync_provenance": diagnostics.get("clock_sync_provenance", ""),
            "runtime_watchdog_status": diagnostics.get("runtime_watchdog_status", ""),
            "runtime_watchdog_profile": diagnostics.get("runtime_watchdog_profile", ""),
            "runtime_watchdog_fail_count": diagnostics.get("runtime_watchdog_fail_count", ""),
            "runtime_watchdog_warn_count": diagnostics.get("runtime_watchdog_warn_count", ""),
            "runtime_watchdog_detail": json.dumps(diagnostics.get("runtime_watchdog_detail", {}), ensure_ascii=False) if diagnostics.get("runtime_watchdog_detail") else "",
            "runtime_service_status": diagnostics.get("runtime_service_status", ""),
            "runtime_service_id": diagnostics.get("runtime_service_id", ""),
            "runtime_service_run_id": diagnostics.get("runtime_service_run_id", ""),
            "runtime_service_delivery_state": diagnostics.get("runtime_service_delivery_state", ""),
            "runtime_service_quarantine_count": diagnostics.get("runtime_service_quarantine_count", ""),
            "runtime_service_restart_count": diagnostics.get("runtime_service_restart_count", ""),
            "runtime_service_detail": json.dumps(diagnostics.get("runtime_service_detail", {}), ensure_ascii=False) if diagnostics.get("runtime_service_detail") else "",
            "daemon_telemetry_status": diagnostics.get("daemon_telemetry_status", ""),
            "supervisor_state": diagnostics.get("supervisor_state", ""),
            "ptp_lock_status": diagnostics.get("ptp_lock_status", ""),
            "gps_pps_lock_status": diagnostics.get("gps_pps_lock_status", ""),
            "hardware_watchdog_status": diagnostics.get("hardware_watchdog_status", ""),
            "os_supervisor_status": diagnostics.get("os_supervisor_status", ""),
            "os_supervisor_state": diagnostics.get("os_supervisor_state", ""),
            "watchdog_provider_status": diagnostics.get("watchdog_provider_status", ""),
            "installable_runtime_status": diagnostics.get("installable_runtime_status", ""),
            "installable_runtime_profile_id": diagnostics.get("installable_runtime_profile_id", ""),
            "installable_runtime_targets": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
            if isinstance(diagnostics.get("installable_runtime_targets"), list)
            else diagnostics.get("installable_runtime_targets", ""),
            "runtime_deployment_status": diagnostics.get("runtime_deployment_status", ""),
            "runtime_deployment_execution_mode": diagnostics.get("runtime_deployment_execution_mode", ""),
            "installable_runtime_detail": json.dumps(diagnostics.get("installable_runtime_detail", {}), ensure_ascii=False) if diagnostics.get("installable_runtime_detail") else "",
            "supervisor_integration_detail": json.dumps(diagnostics.get("supervisor_integration_detail", {}), ensure_ascii=False) if diagnostics.get("supervisor_integration_detail") else "",
            "daemon_telemetry_detail": json.dumps(diagnostics.get("daemon_telemetry_detail", {}), ensure_ascii=False) if diagnostics.get("daemon_telemetry_detail") else "",
            "ch4_status": diagnostics.get("ch4_status", ""),
            "ch4_flux_nmol_m2_s": diagnostics.get("ch4_flux_nmol_m2_s", ""),
            "ch4_flux_level0_nmol_m2_s": diagnostics.get("ch4_flux_level0_nmol_m2_s", ""),
            "ch4_flux_corrected_nmol_m2_s": diagnostics.get("ch4_flux_corrected_nmol_m2_s", ""),
            "cov_w_ch4_ppb": diagnostics.get("cov_w_ch4_ppb", ""),
            "mean_ch4_ppb": diagnostics.get("mean_ch4_ppb", ""),
            "ch4_valid_ratio": diagnostics.get("ch4_valid_ratio", ""),
            "ch4_method": diagnostics.get("ch4_method", ""),
            "ch4_coefficient_profile_id": diagnostics.get("ch4_coefficient_profile_id", ""),
            "ch4_coefficient_registry_status": diagnostics.get("ch4_coefficient_registry_status", ""),
            "ch4_coefficient_profile_source_file": diagnostics.get("ch4_coefficient_source_file", ""),
            "ch4_coefficient_profile_provenance": diagnostics.get("ch4_coefficient_profile_provenance", ""),
            "ch4_spectral_correction_factor": diagnostics.get("ch4_spectral_correction_factor", ""),
            "ch4_water_vapor_dilution_factor": diagnostics.get("ch4_water_vapor_dilution_factor", ""),
            "qc_grade": window.qc_grade,
            "anomaly_type": window.anomaly_type,
            "reason": window.reason,
        }

    def _spectral_row(self, window: WindowSpectralResult) -> dict[str, Any]:
        return {
            "window_id": window.window_id,
            "start_time": window.start_time.isoformat(),
            "end_time": window.end_time.isoformat(),
            "qc_grade": window.qc_grade,
            "anomaly_type": window.anomaly_type,
            "lag_seconds": window.lag_seconds,
            "lag_confidence": window.lag_confidence,
            "correction_factor": window.correction_factor,
            "high_freq_loss_risk": window.high_freq_loss_risk,
            "reason": window.reason,
            "corrected_flux_before": window.corrected_flux_before,
            "corrected_flux_after": window.corrected_flux_after,
            "sample_count": window.sample_count,
        }

    def _full_output_rows(self, *, rp_result: RPRunResult | None, spectral_result: SpectralRunResult | None, mode: str) -> list[dict[str, Any]]:
        rp_windows = {window.window_id: window for window in (rp_result.windows if rp_result else [])}
        spectral_windows = {window.window_id: window for window in (spectral_result.windows if spectral_result else [])}
        ordered_ids = list(dict.fromkeys([*rp_windows.keys(), *spectral_windows.keys()]))
        rows: list[dict[str, Any]] = []
        for window_id in ordered_ids:
            rp_window = rp_windows.get(window_id)
            spectral_window = spectral_windows.get(window_id)
            uncertainty = rp_window.uncertainty_detail if rp_window else {}
            turbulence = rp_window.turbulence_detail if rp_window else {}
            diagnostics = rp_window.diagnostics if rp_window else {}
            row = {
                "window_id": window_id,
                "start_time": (rp_window.start_time if rp_window else spectral_window.start_time).isoformat() if (rp_window or spectral_window) else "",
                "end_time": (rp_window.end_time if rp_window else spectral_window.end_time).isoformat() if (rp_window or spectral_window) else "",
                "qc_grade": rp_window.qc_grade if rp_window else (spectral_window.qc_grade if spectral_window else ""),
                "lag_seconds": rp_window.lag_seconds if rp_window else (spectral_window.lag_seconds if spectral_window else ""),
                "lag_confidence": rp_window.lag_confidence if rp_window else (spectral_window.lag_confidence if spectral_window else ""),
                "lag_strategy": diagnostics.get("lag_strategy", "") if diagnostics else "",
                "lag_fallback_reason": diagnostics.get("lag_fallback_reason", "") if diagnostics else "",
                "rotation_mode": rp_window.rotation_mode if rp_window else "",
                "detrend_mode": rp_window.detrend_mode if rp_window else "",
                "raw_flux": rp_window.raw_flux if rp_window else "",
                "density_corrected_flux": rp_window.density_corrected_flux if rp_window else "",
                "correction_factor": spectral_window.correction_factor if spectral_window else "",
                "corrected_flux_after": spectral_window.corrected_flux_after if spectral_window else "",
                "stationarity_score": rp_window.stationarity_score if rp_window else "",
                "turbulence_score": rp_window.turbulence_score if rp_window else "",
                "ustar": rp_window.ustar if rp_window else "",
                "relative_uncertainty": uncertainty.get("relative_uncertainty", uncertainty.get("relative_error", "")) if uncertainty else "",
                "primary_flux_random_error": diagnostics.get("primary_flux_random_error", uncertainty.get("primary_flux_random_error", "")) if (diagnostics or uncertainty) else "",
                "primary_flux_relative_uncertainty": diagnostics.get("primary_flux_relative_uncertainty", uncertainty.get("primary_flux_relative_uncertainty", "")) if (diagnostics or uncertainty) else "",
                "primary_flux_uncertainty_band": diagnostics.get("primary_flux_uncertainty_band", uncertainty.get("primary_flux_uncertainty_band", "")) if (diagnostics or uncertainty) else "",
                "primary_flux_ci_lower": diagnostics.get("primary_flux_ci_lower", uncertainty.get("primary_flux_ci_lower", "")) if (diagnostics or uncertainty) else "",
                "primary_flux_ci_upper": diagnostics.get("primary_flux_ci_upper", uncertainty.get("primary_flux_ci_upper", "")) if (diagnostics or uncertainty) else "",
                "primary_flux_ci_level": diagnostics.get("primary_flux_ci_level", uncertainty.get("confidence_level", "")) if (diagnostics or uncertainty) else "",
                "uncertainty_status": uncertainty.get("status", "placeholder") if uncertainty else "placeholder",
                "uncertainty_provenance": json.dumps(
                    {
                        "selected_method": uncertainty.get("selected_method"),
                        "provenance": uncertainty.get("provenance"),
                        "limitations": uncertainty.get("limitations", []),
                        "components": uncertainty.get("components", {}),
                        "relative_uncertainty": uncertainty.get("relative_uncertainty", uncertainty.get("relative_error")),
                        "primary_flux_random_error": diagnostics.get("primary_flux_random_error", uncertainty.get("primary_flux_random_error")),
                        "primary_flux_uncertainty_band": diagnostics.get("primary_flux_uncertainty_band", uncertainty.get("primary_flux_uncertainty_band")),
                        "primary_flux_ci_lower": diagnostics.get("primary_flux_ci_lower", uncertainty.get("primary_flux_ci_lower")),
                        "primary_flux_ci_upper": diagnostics.get("primary_flux_ci_upper", uncertainty.get("primary_flux_ci_upper")),
                        "primary_flux_ci_level": diagnostics.get("primary_flux_ci_level", uncertainty.get("confidence_level")),
                    },
                    ensure_ascii=False,
                )
                if uncertainty
                else "",
                "var_u": turbulence.get("var_u", "") if rp_window else "",
                "var_v": turbulence.get("var_v", "") if rp_window else "",
                "var_w": turbulence.get("var_w", "") if rp_window else "",
                "cov_uw": turbulence.get("cov_uw", "") if rp_window else "",
                "cov_vw": turbulence.get("cov_vw", "") if rp_window else "",
                "turbulence_intermediate": json.dumps(turbulence, ensure_ascii=False) if turbulence else "",
                "diagnostics_flags": ",".join(str(item) for item in rp_window.qc_flags) if rp_window and rp_window.qc_flags else "",
                "diagnostics_issues": ",".join(str(item) for item in diagnostics.get("issues", [])) if diagnostics else "",
                "screening_detail": json.dumps(diagnostics.get("screening_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("screening_detail") else "",
                "screening_config": json.dumps(diagnostics.get("screening_config", {}), ensure_ascii=False) if diagnostics and diagnostics.get("screening_config") else "",
                "density_correction_mode": diagnostics.get("density_correction_mode", "") if diagnostics else "",
                "density_correction_reason": diagnostics.get("density_correction_reason", "") if diagnostics else "",
                "primary_flux": rp_window.primary_flux if rp_window else "",
                "primary_flux_source": rp_window.primary_flux_source if rp_window else "",
                "sonic_correction_status": diagnostics.get("sonic_correction_status", "") if diagnostics else "",
                "sonic_correction_method": diagnostics.get("sonic_correction_method", "") if diagnostics else "",
                "sonic_correction_steps": json.dumps(diagnostics.get("sonic_correction_steps", []), ensure_ascii=False) if diagnostics and diagnostics.get("sonic_correction_steps") else "",
                "sonic_correction_provenance": diagnostics.get("sonic_correction_provenance", "") if diagnostics else "",
                "sonic_correction_detail": json.dumps(diagnostics.get("sonic_correction_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("sonic_correction_detail") else "",
                "crosswind_correction_status": diagnostics.get("crosswind_correction_status", "") if diagnostics else "",
                "crosswind_correction_method": diagnostics.get("crosswind_correction_method", "") if diagnostics else "",
                "crosswind_correction_mean_delta_c": diagnostics.get("crosswind_correction_mean_delta_c", "") if diagnostics else "",
                "crosswind_correction_max_abs_delta_c": diagnostics.get("crosswind_correction_max_abs_delta_c", "") if diagnostics else "",
                "crosswind_correction_provenance": diagnostics.get("crosswind_correction_provenance", "") if diagnostics else "",
                "crosswind_correction_detail": json.dumps(diagnostics.get("crosswind_correction_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("crosswind_correction_detail") else "",
                "clock_sync_status": diagnostics.get("clock_sync_status", "") if diagnostics else "",
                "clock_sync_method": diagnostics.get("clock_sync_method", "") if diagnostics else "",
                "clock_sync_source": diagnostics.get("clock_sync_source", "") if diagnostics else "",
                "clock_sync_mean_offset_s": diagnostics.get("clock_sync_mean_offset_s", "") if diagnostics else "",
                "clock_sync_min_offset_s": diagnostics.get("clock_sync_min_offset_s", "") if diagnostics else "",
                "clock_sync_max_offset_s": diagnostics.get("clock_sync_max_offset_s", "") if diagnostics else "",
                "clock_sync_provenance": diagnostics.get("clock_sync_provenance", "") if diagnostics else "",
                "clock_sync_detail": json.dumps(diagnostics.get("clock_sync_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("clock_sync_detail") else "",
                "runtime_watchdog_status": diagnostics.get("runtime_watchdog_status", "") if diagnostics else "",
                "runtime_watchdog_profile": diagnostics.get("runtime_watchdog_profile", "") if diagnostics else "",
                "runtime_watchdog_fail_count": diagnostics.get("runtime_watchdog_fail_count", "") if diagnostics else "",
                "runtime_watchdog_warn_count": diagnostics.get("runtime_watchdog_warn_count", "") if diagnostics else "",
                "runtime_watchdog_detail": json.dumps(diagnostics.get("runtime_watchdog_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("runtime_watchdog_detail") else "",
                "runtime_service_status": diagnostics.get("runtime_service_status", "") if diagnostics else "",
                "runtime_service_id": diagnostics.get("runtime_service_id", "") if diagnostics else "",
                "runtime_service_run_id": diagnostics.get("runtime_service_run_id", "") if diagnostics else "",
                "runtime_service_delivery_state": diagnostics.get("runtime_service_delivery_state", "") if diagnostics else "",
                "runtime_service_quarantine_count": diagnostics.get("runtime_service_quarantine_count", "") if diagnostics else "",
                "runtime_service_restart_count": diagnostics.get("runtime_service_restart_count", "") if diagnostics else "",
                "runtime_service_detail": json.dumps(diagnostics.get("runtime_service_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("runtime_service_detail") else "",
                "daemon_telemetry_status": diagnostics.get("daemon_telemetry_status", "") if diagnostics else "",
                "supervisor_state": diagnostics.get("supervisor_state", "") if diagnostics else "",
                "ptp_lock_status": diagnostics.get("ptp_lock_status", "") if diagnostics else "",
                "gps_pps_lock_status": diagnostics.get("gps_pps_lock_status", "") if diagnostics else "",
                "hardware_watchdog_status": diagnostics.get("hardware_watchdog_status", "") if diagnostics else "",
                "os_supervisor_status": diagnostics.get("os_supervisor_status", "") if diagnostics else "",
                "os_supervisor_state": diagnostics.get("os_supervisor_state", "") if diagnostics else "",
                "watchdog_provider_status": diagnostics.get("watchdog_provider_status", "") if diagnostics else "",
                "installable_runtime_status": diagnostics.get("installable_runtime_status", "") if diagnostics else "",
                "installable_runtime_profile_id": diagnostics.get("installable_runtime_profile_id", "") if diagnostics else "",
                "installable_runtime_targets": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
                if diagnostics and isinstance(diagnostics.get("installable_runtime_targets"), list)
                else (diagnostics.get("installable_runtime_targets", "") if diagnostics else ""),
                "runtime_deployment_status": diagnostics.get("runtime_deployment_status", "") if diagnostics else "",
                "runtime_deployment_execution_mode": diagnostics.get("runtime_deployment_execution_mode", "") if diagnostics else "",
                "installable_runtime_detail": json.dumps(diagnostics.get("installable_runtime_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("installable_runtime_detail") else "",
                "supervisor_integration_detail": json.dumps(diagnostics.get("supervisor_integration_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("supervisor_integration_detail") else "",
                "daemon_telemetry_detail": json.dumps(diagnostics.get("daemon_telemetry_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("daemon_telemetry_detail") else "",
                "ch4_status": diagnostics.get("ch4_status", "") if diagnostics else "",
                "ch4_flux_nmol_m2_s": diagnostics.get("ch4_flux_nmol_m2_s", "") if diagnostics else "",
                "ch4_flux_level0_nmol_m2_s": diagnostics.get("ch4_flux_level0_nmol_m2_s", "") if diagnostics else "",
                "ch4_flux_level1_spectral_nmol_m2_s": diagnostics.get("ch4_flux_level1_spectral_nmol_m2_s", "") if diagnostics else "",
                "ch4_flux_level2_density_nmol_m2_s": diagnostics.get("ch4_flux_level2_density_nmol_m2_s", "") if diagnostics else "",
                "ch4_flux_corrected_nmol_m2_s": diagnostics.get("ch4_flux_corrected_nmol_m2_s", "") if diagnostics else "",
                "cov_w_ch4_ppb": diagnostics.get("cov_w_ch4_ppb", "") if diagnostics else "",
                "mean_ch4_ppb": diagnostics.get("mean_ch4_ppb", "") if diagnostics else "",
                "ch4_valid_ratio": diagnostics.get("ch4_valid_ratio", "") if diagnostics else "",
                "ch4_method": diagnostics.get("ch4_method", "") if diagnostics else "",
                "ch4_coefficient_profile_id": diagnostics.get("ch4_coefficient_profile_id", "") if diagnostics else "",
                "ch4_coefficient_registry_status": diagnostics.get("ch4_coefficient_registry_status", "") if diagnostics else "",
                "ch4_coefficient_profile_source_file": diagnostics.get("ch4_coefficient_source_file", "") if diagnostics else "",
                "ch4_coefficient_profile_provenance": diagnostics.get("ch4_coefficient_profile_provenance", "") if diagnostics else "",
                "ch4_spectral_correction_factor": diagnostics.get("ch4_spectral_correction_factor", "") if diagnostics else "",
                "ch4_water_vapor_dilution_factor": diagnostics.get("ch4_water_vapor_dilution_factor", "") if diagnostics else "",
                "ch4_spectroscopic_correction_factor": diagnostics.get("ch4_spectroscopic_correction_factor", "") if diagnostics else "",
                "ch4_self_heating_correction_factor": diagnostics.get("ch4_self_heating_correction_factor", "") if diagnostics else "",
                "ch4_correction_sequence": json.dumps(diagnostics.get("ch4_correction_sequence", {}), ensure_ascii=False) if diagnostics and diagnostics.get("ch4_correction_sequence") else "",
                "ch4_provenance": diagnostics.get("ch4_provenance", "") if diagnostics else "",
                "ch4_limitations": json.dumps(diagnostics.get("ch4_limitations", []), ensure_ascii=False) if diagnostics and diagnostics.get("ch4_limitations") else "",
                "ch4_detail": json.dumps(diagnostics.get("ch4_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("ch4_detail") else "",
                "trace_gas_family": json.dumps(diagnostics.get("trace_gas_family", {}), ensure_ascii=False) if diagnostics and diagnostics.get("trace_gas_family") else "",
                "requested_rotation_mode": diagnostics.get("requested_rotation_mode", "") if diagnostics else "",
                "applied_rotation_impl": diagnostics.get("applied_rotation_impl", "") if diagnostics else "",
                "lag_fallback_reason": diagnostics.get("lag_fallback_reason", "") if diagnostics else "",
                "screening_summary": diagnostics.get("screening_summary", "") if diagnostics else "",
                "qc_details": json.dumps(diagnostics.get("qc_details", {}), ensure_ascii=False) if diagnostics and diagnostics.get("qc_details") else "",
                "metadata_summary": json.dumps(diagnostics.get("metadata_summary", {}), ensure_ascii=False) if diagnostics and diagnostics.get("metadata_summary") else "",
                "wpl_water_vapor_term": diagnostics.get("wpl_water_vapor_term", "") if diagnostics else "",
                "wpl_sensible_heat_term": diagnostics.get("wpl_sensible_heat_term", "") if diagnostics else "",
                "advanced_qc_contribution": json.dumps(diagnostics.get("advanced_qc_contribution", {}), ensure_ascii=False) if diagnostics and diagnostics.get("advanced_qc_contribution") else "",
                "advanced_test_weights": json.dumps(diagnostics.get("advanced_test_weights", {}), ensure_ascii=False) if diagnostics and diagnostics.get("advanced_test_weights") else "",
                "advanced_test_thresholds": json.dumps(diagnostics.get("advanced_test_thresholds", {}), ensure_ascii=False) if diagnostics and diagnostics.get("advanced_test_thresholds") else "",
                "wpl_benchmark_status": json.dumps(diagnostics.get("wpl_benchmark_status", {}), ensure_ascii=False) if diagnostics and diagnostics.get("wpl_benchmark_status") else "",
                "benchmark_status": diagnostics.get("benchmark_status", "") if diagnostics else "",
                "benchmark_target": diagnostics.get("benchmark_target", "") if diagnostics else "",
                "benchmark_deviation_summary": json.dumps(diagnostics.get("benchmark_deviation_summary", {}), ensure_ascii=False) if diagnostics and diagnostics.get("benchmark_deviation_summary") else "",
                "benchmark_reference_id": diagnostics.get("benchmark_reference_id", "") if diagnostics else "",
                "benchmark_thresholds": json.dumps(diagnostics.get("benchmark_thresholds", {}), ensure_ascii=False) if diagnostics and diagnostics.get("benchmark_thresholds") else "",
                "continuous_dataset_enabled": diagnostics.get("continuous_dataset_enabled", False) if diagnostics else False,
                "footprint_peak_distance_m": diagnostics.get("footprint_peak_distance_m", "") if diagnostics else "",
                "footprint_method": diagnostics.get("footprint_method", "") if diagnostics else "",
                "footprint_offset_distance_m": diagnostics.get("footprint_offset_distance_m", "") if diagnostics else "",
                "footprint_contribution_distances": json.dumps(diagnostics.get("footprint_contribution_distances", {}), ensure_ascii=False) if diagnostics and diagnostics.get("footprint_contribution_distances") else "",
                "footprint_2d_grid_status": diagnostics.get("footprint_2d_grid_status", "") if diagnostics else "",
                "footprint_2d_peak_downwind_m": diagnostics.get("footprint_2d_peak_downwind_m", "") if diagnostics else "",
                "footprint_2d_peak_crosswind_m": diagnostics.get("footprint_2d_peak_crosswind_m", "") if diagnostics else "",
                "footprint_2d_half_width_m": diagnostics.get("footprint_2d_half_width_m", "") if diagnostics else "",
                "footprint_2d_contribution_contours_m": json.dumps(diagnostics.get("footprint_2d_contribution_contours_m", {}), ensure_ascii=False) if diagnostics and diagnostics.get("footprint_2d_contribution_contours_m") else "",
                "uncertainty_method": diagnostics.get("uncertainty_method", "") if diagnostics else "",
                "uncertainty_method_detail": json.dumps(diagnostics.get("uncertainty_method_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("uncertainty_method_detail") else "",
                "spectral_correction_method": diagnostics.get("spectral_correction_method", "") if diagnostics else "",
                "spectral_correction_factor": diagnostics.get("spectral_correction_factor", "") if diagnostics else "",
                "spectral_correction_detail": json.dumps(diagnostics.get("spectral_correction_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("spectral_correction_detail") else "",
                "spectral_correction_provenance": diagnostics.get("spectral_correction_provenance", "") if diagnostics else "",
                "spectral_correction_measured_cospectrum_enabled": diagnostics.get("spectral_correction_measured_cospectrum_enabled", False) if diagnostics else False,
                "spectral_correction_measured_cospectrum_used": diagnostics.get("spectral_correction_measured_cospectrum_used", False) if diagnostics else False,
                "spectral_correction_measured_cospectrum_source": diagnostics.get("spectral_correction_measured_cospectrum_source", "") if diagnostics else "",
                "spectral_correction_cospectrum_match": json.dumps(diagnostics.get("spectral_correction_cospectrum_match", {}), ensure_ascii=False) if diagnostics and diagnostics.get("spectral_correction_cospectrum_match") else "",
                "spectral_correction_limitations": json.dumps(diagnostics.get("spectral_correction_limitations", []), ensure_ascii=False) if diagnostics and diagnostics.get("spectral_correction_limitations") else "",
                "method_compare_summary": json.dumps(diagnostics.get("method_compare_summary", {}), ensure_ascii=False) if diagnostics and diagnostics.get("method_compare_summary") else "",
                "method_compare_recommendations": json.dumps(diagnostics.get("method_compare_recommendations", {}), ensure_ascii=False) if diagnostics and diagnostics.get("method_compare_recommendations") else "",
                "method_compare_deviation_flags": json.dumps(diagnostics.get("method_compare_deviation_flags", []), ensure_ascii=False) if diagnostics and diagnostics.get("method_compare_deviation_flags") else "",
                "performance_profile": json.dumps(diagnostics.get("performance_profile", {}), ensure_ascii=False) if diagnostics and diagnostics.get("performance_profile") else "",
                "schema_target": diagnostics.get("schema_target", "") if diagnostics else "",
                "fluxnet_timestamp_refers_to": diagnostics.get("fluxnet_timestamp_refers_to", "") if diagnostics else "",
                "fluxnet_timezone_offset_h": diagnostics.get("fluxnet_timezone_offset_h", "") if diagnostics else "",
                "fluxnet_gap_fill_value": diagnostics.get("fluxnet_gap_fill_value", "") if diagnostics else "",
            }
            if mode == "only_available":
                row = {key: value for key, value in row.items() if value not in ("", None)}
            rows.append(row)
        return rows

    def _full_output_headers(self, *, mode: str) -> list[str]:
        if mode == "standard_schema":
            return [name for name, _group, _status in FULL_OUTPUT_SCHEMA]
        return [name for name, _group, _status in FULL_OUTPUT_SCHEMA if _status != "placeholder"]

    def _rp_headers(self) -> list[str]:
        return list(self._rp_row(self._empty_rp_window()).keys())

    def _spectral_headers(self) -> list[str]:
        return list(self._spectral_row(self._empty_spectral_window()).keys())

    def _write_csv(self, path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            if rows:
                writer.writerows(rows)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(self._to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def _sha256_text(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _to_jsonable(self, payload: Any) -> Any:
        if is_dataclass(payload):
            return self._to_jsonable(asdict(payload))
        if isinstance(payload, dict):
            return {key: self._to_jsonable(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._to_jsonable(item) for item in payload]
        if isinstance(payload, datetime):
            return payload.isoformat()
        if isinstance(payload, Path):
            return str(payload)
        return payload

    def _empty_rp_window(self) -> WindowRPResult:
        now = datetime(2000, 1, 1)
        return WindowRPResult(window_id="", start_time=now, end_time=now, sample_count=0, valid_sample_count=0, continuity_ratio=0.0, missing_ratio=0.0, rotation_mode="", detrend_mode="", lag_seconds=0.0, lag_confidence=0.0, cov_w_co2=0.0, cov_w_h2o=0.0, raw_flux=0.0, mixing_ratio_flux=0.0, density_corrected_flux=0.0, water_vapor_flux=0.0, air_molar_density=0.0, dry_air_molar_density=0.0, mean_co2_ppm=0.0, mean_h2o_mmol=0.0, mean_pressure_kpa=0.0, mean_temp_c=0.0, qc_grade="", anomaly_type="", reason="")

    def _extract_screening_config(self, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        screening = rp_config_snapshot.get("screening", {})
        return {
            "skewness_threshold": screening.get("skewness_threshold", 2.0),
            "kurtosis_threshold": screening.get("kurtosis_threshold", 7.0),
            "dropout_min_run": screening.get("dropout_min_run", 10),
            "spike_sigma": screening.get("spike_sigma", 5.0),
            "discontinuity_sigma": screening.get("discontinuity_sigma", 8.0),
            "absolute_limits": screening.get("absolute_limits", None),
        }

    def _extract_advanced_test_thresholds(self, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        adv = rp_config_snapshot.get("advanced_tests", {})
        return {
            "amplitude_resolution_ratio_threshold": adv.get("amplitude_resolution_ratio_threshold", 10.0),
            "time_lag_max_lag_s": adv.get("time_lag_max_lag_s", 5.0),
            "time_lag_confidence_threshold": adv.get("time_lag_confidence_threshold", 0.4),
            "angle_of_attack_max_angle_deg": adv.get("angle_of_attack_max_angle_deg", 40.0),
            "steadiness_cv_threshold": adv.get("steadiness_cv_threshold", 0.50),
        }

    def _extract_benchmark_thresholds(self, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        bm = rp_config_snapshot.get("benchmark", {})
        return {
            "flux_rel_threshold": float(bm.get("flux_rel_threshold", 0.10)),
            "lag_abs_threshold_s": float(bm.get("lag_abs_threshold_s", 0.5)),
            "wpl_rel_threshold": float(bm.get("wpl_rel_threshold", 0.20)),
            "qc_grade_must_match": bool(bm.get("qc_grade_must_match", False)),
        }

    def _benchmark_results_for_run(self, rp_result: RPRunResult | None) -> list[dict[str, Any]]:
        if not rp_result or not rp_result.windows:
            return []
        results: list[dict[str, Any]] = []
        for window in rp_result.windows:
            diagnostics = window.diagnostics or {}
            benchmark = diagnostics.get("benchmark_deviation_summary", {})
            if benchmark:
                results.append(dict(benchmark))
        return results

    def _trace_gas_summary(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        if not rp_result or not rp_result.windows:
            return {
                "status": "not_available",
                "ch4_window_count": 0,
                "ch4_computed_window_count": 0,
                "average_ch4_flux_nmol_m2_s": None,
                "average_ch4_level0_flux_nmol_m2_s": None,
                "method": "not_available",
                "coefficient_profile_id": "",
                "coefficient_registry_status": "",
                "coefficient_profile_source_file": "",
                "coefficient_profile_provenance": "",
                "provenance": "",
                "limitations": [],
            }
        diagnostics = [dict(window.diagnostics or {}) for window in rp_result.windows]
        computed = [
            diag
            for diag in diagnostics
            if diag.get("ch4_status") == "computed" and isinstance(diag.get("ch4_flux_nmol_m2_s"), (int, float))
        ]
        level0 = [
            diag
            for diag in diagnostics
            if isinstance(diag.get("ch4_flux_level0_nmol_m2_s"), (int, float))
        ]
        first = next((diag for diag in diagnostics if diag.get("ch4_method")), diagnostics[0] if diagnostics else {})
        return {
            "status": "computed" if computed else "not_available",
            "ch4_window_count": len(diagnostics),
            "ch4_computed_window_count": len(computed),
            "average_ch4_flux_nmol_m2_s": (
                sum(float(diag["ch4_flux_nmol_m2_s"]) for diag in computed) / len(computed)
                if computed
                else None
            ),
            "average_ch4_level0_flux_nmol_m2_s": (
                sum(float(diag["ch4_flux_level0_nmol_m2_s"]) for diag in level0) / len(level0)
                if level0
                else None
            ),
            "method": first.get("ch4_method", "not_available"),
            "correction_sequence": first.get("ch4_correction_sequence", {}),
            "coefficient_profile_id": first.get("ch4_coefficient_profile_id", ""),
            "coefficient_registry_status": first.get("ch4_coefficient_registry_status", ""),
            "coefficient_profile_label": first.get("ch4_coefficient_profile_label", ""),
            "coefficient_profile_source_file": first.get("ch4_coefficient_source_file", ""),
            "coefficient_profile_normalization_command": first.get("ch4_coefficient_normalization_command", ""),
            "coefficient_profile_provenance": first.get("ch4_coefficient_profile_provenance", ""),
            "coefficient_profile_limitations": list(first.get("ch4_coefficient_profile_limitations", []) or []),
            "provenance": first.get("ch4_provenance", ""),
            "limitations": list(first.get("ch4_limitations", []) or []),
        }

    def _benchmark_rollup(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        benchmark_results = self._benchmark_results_for_run(rp_result)
        benchmark_cfg = dict(rp_config_snapshot.get("benchmark", {}))
        if rp_result and isinstance(rp_result.summary, dict):
            benchmark_cfg.setdefault("status", rp_result.summary.get("benchmark_status", benchmark_cfg.get("status", "")))
            benchmark_cfg.setdefault("target", rp_result.summary.get("benchmark_target", benchmark_cfg.get("target", "")))
            benchmark_cfg.setdefault("reference_id", rp_result.summary.get("benchmark_reference_id", benchmark_cfg.get("reference_id", "")))
        summary = self.compute_benchmark_summary(rp_result=rp_result, benchmark_results=benchmark_results)
        if rp_result and isinstance(rp_result.summary, dict):
            benchmark_deviation_summary = rp_result.summary.get("benchmark_deviation_summary")
            if isinstance(benchmark_deviation_summary, dict) and benchmark_deviation_summary:
                summary["field_summary"] = benchmark_deviation_summary.get("field_summary", summary.get("field_summary", {}))
        return {
            "benchmark_status": str(benchmark_cfg.get("status", "")),
            "benchmark_target": str(benchmark_cfg.get("target", "")),
            "benchmark_reference_id": str(benchmark_cfg.get("reference_id", "")),
            "benchmark_thresholds": self._extract_benchmark_thresholds(rp_config_snapshot),
            "benchmark_deviation_summary": {
                "status": summary.get("status", "no_benchmark"),
                "windows_compared": int(summary.get("windows_compared", 0)),
                "windows_pass": int(summary.get("windows_pass", 0)),
                "windows_fail": int(summary.get("windows_fail", 0)),
                "field_summary": summary.get("field_summary", {}),
            },
            "pass_rate": float(summary.get("pass_rate", 0.0) or 0.0),
            "failed_fields": sorted(
                field_name
                for field_name, field_summary in (summary.get("field_summary", {}) or {}).items()
                if int(field_summary.get("failed", 0)) > 0
            ),
            "benchmark_results": benchmark_results,
            "summary": summary,
        }

    def _method_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            "footprint_method": "",
            "footprint_summary": {},
            "footprint_2d_summary": {},
            "uncertainty_method": "",
            "uncertainty_summary": {},
            "spectral_correction_method": "",
            "spectral_correction_summary": {},
            "method_compare_summary": {},
            "method_compare_recommendations": {},
        }
        if rp_result is None:
            return defaults
        artifacts = dict(rp_result.artifacts or {})
        method_rollup = dict(artifacts.get("method_rollup", {}) or artifacts.get("method_provenance", {}) or {})
        if method_rollup:
            normalized = {
                "footprint_method": str(method_rollup.get("footprint_method", "")),
                "footprint_summary": dict(method_rollup.get("footprint_summary", {}) or {}),
                "footprint_2d_summary": dict(method_rollup.get("footprint_2d_summary", {}) or {}),
                "uncertainty_method": str(method_rollup.get("uncertainty_method", "")),
                "uncertainty_summary": dict(method_rollup.get("uncertainty_summary", {}) or {}),
                "spectral_correction_method": str(method_rollup.get("spectral_correction_method", "")),
                "spectral_correction_summary": dict(method_rollup.get("spectral_correction_summary", {}) or {}),
                "method_compare_summary": dict(method_rollup.get("method_compare_summary", {}) or {}),
                "method_compare_recommendations": dict(method_rollup.get("method_compare_recommendations", {}) or {}),
            }
            if any(normalized.values()):
                return normalized
        summary = dict(rp_result.summary or {})
        method_summary = {
            "footprint_method": str(summary.get("footprint_method", "")),
            "footprint_summary": dict(summary.get("footprint_summary", {}) or {}),
            "footprint_2d_summary": dict(summary.get("footprint_2d_summary", {}) or {}),
            "uncertainty_method": str(summary.get("uncertainty_method", "")),
            "uncertainty_summary": dict(summary.get("uncertainty_summary", {}) or {}),
            "spectral_correction_method": str(summary.get("spectral_correction_method", "")),
            "spectral_correction_summary": dict(summary.get("spectral_correction_summary", {}) or {}),
            "method_compare_summary": dict(summary.get("method_compare_summary", {}) or {}),
            "method_compare_recommendations": dict(summary.get("method_compare_recommendations", {}) or {}),
        }
        if any(method_summary.values()):
            return method_summary
        if not rp_result.windows:
            return defaults
        first_diag = dict(rp_result.windows[0].diagnostics or {})
        footprint_detail = dict(first_diag.get("footprint_detail", {}) or {})
        uncertainty_detail = dict(first_diag.get("uncertainty_method_detail", {}) or rp_result.windows[0].uncertainty_detail or {})
        spectral_detail = dict(first_diag.get("spectral_correction_detail", {}) or {})
        return {
            "footprint_method": str(first_diag.get("footprint_method", "")),
            "footprint_summary": {
                "method": str(first_diag.get("footprint_method", "")),
                "peak_distance_m": first_diag.get("footprint_peak_distance_m"),
                "offset_distance_m": first_diag.get("footprint_offset_distance_m"),
                "contribution_distances": dict(first_diag.get("footprint_contribution_distances", {}) or {}),
                "provenance": footprint_detail.get("provenance", ""),
                "limitations": footprint_detail.get("limitations", []),
                "detail": footprint_detail,
            },
            "footprint_2d_summary": {
                "status": first_diag.get("footprint_2d_grid_status", ""),
                "peak_downwind_m": first_diag.get("footprint_2d_peak_downwind_m"),
                "peak_crosswind_m": first_diag.get("footprint_2d_peak_crosswind_m"),
                "half_width_m": first_diag.get("footprint_2d_half_width_m"),
                "contribution_contours_m": dict(first_diag.get("footprint_2d_contribution_contours_m", {}) or {}),
            },
            "uncertainty_method": str(first_diag.get("uncertainty_method", "")),
            "uncertainty_summary": {
                "method": str(first_diag.get("uncertainty_method", "")),
                "selected_method": uncertainty_detail.get("selected_method", ""),
                "relative_uncertainty": uncertainty_detail.get("relative_uncertainty", uncertainty_detail.get("relative_error")),
                "primary_flux_random_error": uncertainty_detail.get("primary_flux_random_error"),
                "uncertainty_band": uncertainty_detail.get("primary_flux_uncertainty_band"),
                "confidence_level": uncertainty_detail.get("confidence_level"),
                "components": dict(uncertainty_detail.get("components", {}) or {}),
                "provenance": uncertainty_detail.get("provenance", ""),
                "limitations": uncertainty_detail.get("limitations", []),
                "detail": uncertainty_detail,
            },
            "spectral_correction_method": str(first_diag.get("spectral_correction_method", "")),
            "spectral_correction_summary": {
                "method": str(first_diag.get("spectral_correction_method", "")),
                "correction_factor": first_diag.get("spectral_correction_factor"),
                "provenance": first_diag.get("spectral_correction_provenance", ""),
                "measured_cospectrum_enabled": first_diag.get("spectral_correction_measured_cospectrum_enabled", False),
                "measured_cospectrum_used": first_diag.get("spectral_correction_measured_cospectrum_used", False),
                "measured_cospectrum_source": first_diag.get("spectral_correction_measured_cospectrum_source", ""),
                "cospectrum_match_summary": dict(first_diag.get("spectral_correction_cospectrum_match", {}) or {}),
                "limitations": first_diag.get("spectral_correction_limitations", []),
                "detail": spectral_detail,
            },
            "method_compare_summary": dict(first_diag.get("method_compare_summary", {}) or {}),
            "method_compare_recommendations": dict(first_diag.get("method_compare_recommendations", {}) or {}),
        }

    def export_method_rollup_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        method_summary = self._method_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not any(method_summary.values()):
            return None
        path = export_root / "method_rollup.json"
        self._write_json(path, method_summary)
        return path

    def export_footprint_2d_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        windows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            diagnostics = dict(window.diagnostics or {})
            grid = diagnostics.get("footprint_2d_grid")
            if not isinstance(grid, dict):
                continue
            windows.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "qc_grade": window.qc_grade,
                    "method": diagnostics.get("footprint_method", grid.get("method", "")),
                    "grid_status": diagnostics.get("footprint_2d_grid_status", "ok"),
                    "peak_downwind_m": diagnostics.get("footprint_2d_peak_downwind_m"),
                    "peak_crosswind_m": diagnostics.get("footprint_2d_peak_crosswind_m"),
                    "half_width_m": diagnostics.get("footprint_2d_half_width_m"),
                    "contribution_contours_m": diagnostics.get("footprint_2d_contribution_contours_m", {}),
                    "grid": grid,
                }
            )
        if not windows:
            return None
        payload = {
            "artifact_type": "footprint_2d_grid",
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "summary": dict(rp_result.summary.get("footprint_2d_summary", {}) if isinstance(rp_result.summary, dict) else {}),
            "window_count": len(windows),
            "windows": windows,
            "provenance": "Per-window 2D footprint grids exported from RP diagnostics.",
        }
        grid_csv_path = export_root / "footprint_2d_grid.csv"
        contour_svg_path = export_root / "footprint_2d_contour.svg"
        self._write_footprint_2d_grid_csv(grid_csv_path, windows)
        self._write_footprint_2d_contour_svg(contour_svg_path, windows[0])
        payload["companion_files"] = {
            "grid_csv": str(grid_csv_path),
            "contour_svg": str(contour_svg_path),
        }
        path = export_root / "footprint_2d_artifact.json"
        self._write_json(path, payload)
        return path

    def _write_footprint_2d_grid_csv(self, path: Path, windows: list[dict[str, Any]]) -> None:
        rows: list[dict[str, Any]] = []
        for window in windows:
            grid_payload = dict(window.get("grid", {}) or {})
            x_coords = list(grid_payload.get("x_coords_m", []) or [])
            y_coords = list(grid_payload.get("y_coords_m", []) or [])
            grid = list(grid_payload.get("contribution_grid", []) or [])
            for y_index, row in enumerate(grid):
                if not isinstance(row, list):
                    continue
                for x_index, contribution in enumerate(row):
                    rows.append(
                        {
                            "window_id": window.get("window_id", ""),
                            "method": window.get("method", ""),
                            "x_m": x_coords[x_index] if x_index < len(x_coords) else "",
                            "y_m": y_coords[y_index] if y_index < len(y_coords) else "",
                            "contribution": contribution,
                        }
                    )
        self._write_csv(path, rows, ["window_id", "method", "x_m", "y_m", "contribution"])

    def _write_footprint_2d_contour_svg(self, path: Path, window: dict[str, Any]) -> None:
        grid_payload = dict(window.get("grid", {}) or {})
        x_coords = [float(value) for value in list(grid_payload.get("x_coords_m", []) or [])]
        y_coords = [float(value) for value in list(grid_payload.get("y_coords_m", []) or [])]
        grid = [
            [float(value) for value in row]
            for row in list(grid_payload.get("contribution_grid", []) or [])
            if isinstance(row, list)
        ]
        if not x_coords or not y_coords or not grid:
            path.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"640\" height=\"360\"></svg>", encoding="utf-8")
            return
        width, height = 840, 520
        margin_left, margin_top, margin_right, margin_bottom = 72, 40, 32, 70
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom
        rows = len(grid)
        cols = len(grid[0]) if rows else 0
        cell_w = plot_w / max(cols, 1)
        cell_h = plot_h / max(rows, 1)
        max_value = max(max(row) for row in grid) if grid else 0.0

        def _color(value: float) -> str:
            ratio = min(max(value / max(max_value, 1e-12), 0.0), 1.0)
            red = int(34 + 206 * ratio)
            green = int(72 + 111 * (1.0 - abs(ratio - 0.45)))
            blue = int(92 + 120 * (1.0 - ratio))
            return f"rgb({red},{green},{blue})"

        rects: list[str] = []
        for row_index, row in enumerate(grid):
            for col_index, value in enumerate(row):
                x = margin_left + col_index * cell_w
                y = margin_top + row_index * cell_h
                rects.append(
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_w + 0.35:.2f}" '
                    f'height="{cell_h + 0.35:.2f}" fill="{_color(float(value))}" opacity="0.92" />'
                )
        contours = dict(window.get("contribution_contours_m", {}) or {})
        contour_lines: list[str] = []
        x_max = max(x_coords) if x_coords else 1.0
        for label, x_value in contours.items():
            try:
                x_pos = margin_left + min(max(float(x_value) / max(x_max, 1e-9), 0.0), 1.0) * plot_w
            except (TypeError, ValueError):
                continue
            contour_lines.append(
                f'<line x1="{x_pos:.2f}" y1="{margin_top}" x2="{x_pos:.2f}" y2="{margin_top + plot_h}" '
                'stroke="#ffffff" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.85" />'
                f'<text x="{x_pos + 4:.2f}" y="{margin_top + 16}" fill="#ffffff" font-size="12">{label}</text>'
            )
        peak_x = window.get("peak_downwind_m", "")
        peak_y = window.get("peak_crosswind_m", "")
        title = f"2D Footprint Contour - {window.get('window_id', '')} ({window.get('method', '')})"
        subtitle = f"peak=({peak_x} m downwind, {peak_y} m crosswind), grid={cols}x{rows}"
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#0f172a" />
  <text x="{margin_left}" y="24" fill="#f8fafc" font-size="18" font-family="Segoe UI, sans-serif">{title}</text>
  <text x="{margin_left}" y="{height - 24}" fill="#cbd5e1" font-size="13" font-family="Segoe UI, sans-serif">{subtitle}</text>
  <g>{''.join(rects)}</g>
  <g>{''.join(contour_lines)}</g>
  <rect x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#e2e8f0" stroke-width="1" />
  <text x="{margin_left + plot_w / 2:.1f}" y="{height - 44}" fill="#e2e8f0" font-size="13" text-anchor="middle" font-family="Segoe UI, sans-serif">Downwind distance (m)</text>
  <text x="22" y="{margin_top + plot_h / 2:.1f}" fill="#e2e8f0" font-size="13" text-anchor="middle" transform="rotate(-90 22 {margin_top + plot_h / 2:.1f})" font-family="Segoe UI, sans-serif">Crosswind distance (m)</text>
  <text x="{margin_left}" y="{margin_top + plot_h + 20}" fill="#cbd5e1" font-size="12" font-family="Segoe UI, sans-serif">0</text>
  <text x="{margin_left + plot_w - 56}" y="{margin_top + plot_h + 20}" fill="#cbd5e1" font-size="12" font-family="Segoe UI, sans-serif">{x_max:.1f} m</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")

    def export_method_compare_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        windows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            diagnostics = dict(window.diagnostics or {})
            compare = diagnostics.get("method_compare_summary")
            if not isinstance(compare, dict) or not compare:
                continue
            windows.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "qc_grade": window.qc_grade,
                    "method_compare": compare,
                    "recommendations": diagnostics.get("method_compare_recommendations", {}),
                    "deviation_flags": diagnostics.get("method_compare_deviation_flags", []),
                    "method_deviation_notes": _build_method_deviation_notes(diagnostics, {}),
                }
            )
        if not windows:
            return None
        summary = dict(rp_result.summary.get("method_compare_summary", {}) if isinstance(rp_result.summary, dict) else {})
        payload = {
            "artifact_type": "method_compare",
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "summary": summary,
            "window_count": len(windows),
            "windows": windows,
            "provenance": "Run-level method-family comparison exported from RP diagnostics.",
        }
        path = export_root / "method_compare_artifact.json"
        self._write_json(path, payload)
        return path

    def _performance_profile_payload(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        if rp_result is None:
            return {"status": "missing", "run_summary": {}, "windows": []}
        windows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            profile = dict(window.diagnostics.get("performance_profile", {}) if window.diagnostics else {})
            if not profile:
                continue
            windows.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "qc_grade": window.qc_grade,
                    **profile,
                }
            )
        return {
            "artifact_type": "performance_profile",
            "status": "ok" if windows or rp_result.summary.get("performance_profile") else "no_profiles",
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "run_summary": dict(rp_result.summary.get("performance_profile", {}) if isinstance(rp_result.summary, dict) else {}),
            "window_count": len(windows),
            "windows": windows,
            "provenance": "Measured with time.perf_counter during RP pipeline execution.",
        }

    def export_performance_profile_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        payload = self._performance_profile_payload(rp_result=rp_result)
        if payload.get("status") in {"missing", "no_profiles"}:
            return None
        path = export_root / "performance_profile.json"
        self._write_json(path, payload)
        return path

    def _runtime_watchdog_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("runtime_watchdog"), dict) and artifacts["runtime_watchdog"]:
                return dict(artifacts["runtime_watchdog"])
            summary = dict(rp_result.summary or {})
            if isinstance(summary.get("runtime_watchdog_summary"), dict) and summary["runtime_watchdog_summary"]:
                return dict(summary["runtime_watchdog_summary"])
        cfg = dict(rp_config_snapshot.get("runtime_profile", {}) if isinstance(rp_config_snapshot.get("runtime_profile", {}), dict) else {})
        if cfg:
            return {
                "artifact_type": "runtime_watchdog",
                "status": "configured_not_run",
                "profile_id": str(cfg.get("profile_id", "headless_watchdog_v1")),
                "deployment_mode": str(cfg.get("deployment_mode", "headless_batch")),
                "restart_policy": str(cfg.get("restart_policy", "manual_review")),
                "provenance": "Runtime watchdog is configured in the export snapshot, but no headless watchdog summary was available.",
                "limitations": ["No per-run watchdog checks were available without a headless batch manifest."],
            }
        return {}

    def export_runtime_watchdog_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._runtime_watchdog_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "runtime_watchdog",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Runtime watchdog artifact exported from headless batch summary.",
        }
        path = export_root / "runtime_watchdog_artifact.json"
        self._write_json(path, payload)
        return path

    def _runtime_service_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("runtime_service"), dict) and artifacts["runtime_service"]:
                return dict(artifacts["runtime_service"])
            summary = dict(rp_result.summary or {})
            if isinstance(summary.get("runtime_service_summary"), dict) and summary["runtime_service_summary"]:
                return dict(summary["runtime_service_summary"])
        cfg = dict(rp_config_snapshot.get("runtime_service", {}) if isinstance(rp_config_snapshot.get("runtime_service", {}), dict) else {})
        if cfg:
            return {
                "artifact_type": "runtime_service",
                "status": "configured_not_run",
                "service_id": str(cfg.get("service_id", "embedded_runtime_service_v1")),
                "deployment_mode": str(cfg.get("deployment_mode", "supervised_headless")),
                "restart_policy": str(cfg.get("restart_policy", "retry_failed_batch_once")),
                "delivery_state": "not_run",
                "provenance": "Runtime service is configured in the export snapshot, but no service run manifest was available.",
                "limitations": ["No heartbeats, quarantine records, or host telemetry were available without a runtime service run."],
            }
        return {}

    def export_runtime_service_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._runtime_service_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "runtime_service",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Runtime service artifact exported from the service-level headless manifest.",
        }
        path = export_root / "runtime_service_artifact.json"
        self._write_json(path, payload)
        return path

    def _daemon_telemetry_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("daemon_telemetry"), dict) and artifacts["daemon_telemetry"]:
                return dict(artifacts["daemon_telemetry"])
            service = dict(artifacts.get("runtime_service", {}) or {})
            if isinstance(service.get("daemon_telemetry"), dict) and service["daemon_telemetry"]:
                return dict(service["daemon_telemetry"])
            summary = dict(rp_result.summary or {})
            service_summary = dict(summary.get("runtime_service_summary", {}) or {})
            if isinstance(service_summary.get("daemon_telemetry"), dict) and service_summary["daemon_telemetry"]:
                return dict(service_summary["daemon_telemetry"])
            if isinstance(summary.get("daemon_telemetry_summary"), dict) and summary["daemon_telemetry_summary"]:
                return dict(summary["daemon_telemetry_summary"])
        cfg = dict(rp_config_snapshot.get("daemon_telemetry", {}) if isinstance(rp_config_snapshot.get("daemon_telemetry", {}), dict) else {})
        if cfg:
            return {
                "artifact_type": "daemon_telemetry",
                "status": "configured_not_run",
                "profile_id": str(cfg.get("profile_id", "daemon_telemetry_v1")),
                "provenance": "Daemon telemetry is configured in the export snapshot, but no runtime service telemetry artifact was available.",
                "limitations": ["No supervisor, PTP/GPS, process, or hardware watchdog telemetry was collected without a runtime service run."],
            }
        return {}

    def export_daemon_telemetry_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._daemon_telemetry_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "daemon_telemetry",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Daemon telemetry artifact exported from the runtime service manifest.",
        }
        path = export_root / "daemon_telemetry_artifact.json"
        self._write_json(path, payload)
        return path

    def _supervisor_integration_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        daemon = self._daemon_telemetry_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if isinstance(daemon.get("supervisor_integration"), dict) and daemon["supervisor_integration"]:
            return dict(daemon["supervisor_integration"])
        cfg = dict(
            rp_config_snapshot.get("supervisor_integration", {})
            if isinstance(rp_config_snapshot.get("supervisor_integration", {}), dict)
            else {}
        )
        provider = dict(
            rp_config_snapshot.get("hardware_watchdog_provider", {})
            if isinstance(rp_config_snapshot.get("hardware_watchdog_provider", {}), dict)
            else {}
        )
        if cfg or provider:
            return {
                "artifact_type": "supervisor_integration",
                "status": "configured_not_run",
                "profile_id": str(cfg.get("profile_id", "os_supervisor_integration_v1")),
                "provenance": "Supervisor integration is configured in the export snapshot, but no runtime service supervisor artifact was available.",
                "limitations": ["No OS supervisor adapter or hardware watchdog provider attempt was collected without a runtime service run."],
            }
        return {}

    def export_supervisor_integration_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._supervisor_integration_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "supervisor_integration",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Supervisor integration artifact exported from daemon telemetry.",
        }
        path = export_root / "supervisor_integration_artifact.json"
        self._write_json(path, payload)
        return path

    def _installable_runtime_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("installable_runtime_profile"), dict) and artifacts["installable_runtime_profile"]:
                return dict(artifacts["installable_runtime_profile"])
        supervisor = self._supervisor_integration_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if isinstance(supervisor.get("installable_runtime_profile"), dict) and supervisor["installable_runtime_profile"]:
            return dict(supervisor["installable_runtime_profile"])
        if has_runtime_install_config(rp_config_snapshot):
            return build_installable_runtime_profile(config=rp_config_snapshot, runtime_root=self.runtime_root)
        return {}

    def export_installable_runtime_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "installable_runtime_profile",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Installable runtime artifact exported from supervisor integration or config snapshot.",
        }
        path = export_root / "installable_runtime_artifact.json"
        self._write_json(path, payload)
        return path

    def _runtime_deployment_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        installable_runtime = self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not installable_runtime:
            return {}
        deployment = build_runtime_deployment_artifact(installable_runtime_profile=installable_runtime)
        if not deployment:
            return {}
        return {
            key: value
            for key, value in deployment.items()
            if key not in {"scripts", "generated_at"}
        }

    def export_runtime_deployment_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> tuple[Path | None, dict[str, str]]:
        installable_runtime = self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not installable_runtime:
            return None, {}
        deployment = build_runtime_deployment_artifact(installable_runtime_profile=installable_runtime)
        if not deployment:
            return None, {}
        companion_files: dict[str, str] = {}
        for script in list(deployment.get("scripts", []) or []):
            payload = dict(script or {})
            filename = Path(str(payload.get("filename", ""))).name
            content = str(payload.get("content", ""))
            if not filename or not content:
                continue
            path = export_root / filename
            path.write_text(content, encoding="utf-8", newline="\n")
            companion_files[f"runtime_deployment_{filename.replace('.', '_')}"] = str(path)
            payload["path"] = str(path)
            payload["sha256"] = self._sha256_text(content)
            payload.pop("content", None)
            script.clear()
            script.update(payload)
        deployment["companion_files"] = companion_files
        payload = {
            "artifact_type": "runtime_deployment",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": deployment,
            "provenance": "Runtime deployment artifact exported with operator-gated install and rollback companion scripts.",
        }
        path = export_root / "runtime_deployment_artifact.json"
        self._write_json(path, payload)
        return path, companion_files

    def _clock_sync_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("clock_sync"), dict) and artifacts["clock_sync"]:
                return dict(artifacts["clock_sync"])
            summary = dict(rp_result.summary or {})
            if isinstance(summary.get("clock_sync_summary"), dict) and summary["clock_sync_summary"]:
                return dict(summary["clock_sync_summary"])
            if rp_result.windows:
                detail = dict(rp_result.windows[0].diagnostics.get("clock_sync_detail", {}) if rp_result.windows[0].diagnostics else {})
                if detail:
                    return detail
        cfg = dict(rp_config_snapshot.get("clock_sync", {}) if isinstance(rp_config_snapshot.get("clock_sync", {}), dict) else {})
        if cfg:
            return {
                "artifact_type": "acquisition_clock_sync",
                "status": "configured_not_run",
                "enabled": bool(cfg.get("enabled", False)),
                "method": str(cfg.get("method", "gps_ptp_offset_drift_v1")),
                "clock_source": str(cfg.get("clock_source", "")),
                "offset_seconds": cfg.get("offset_seconds"),
                "drift_ppm": cfg.get("drift_ppm"),
                "provenance": "Clock synchronization is configured in the export snapshot, but no RP run summary was available.",
                "limitations": ["No per-row clock_sync provenance could be verified without RP diagnostics."],
            }
        return {}

    def export_clock_sync_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._clock_sync_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        windows: list[dict[str, Any]] = []
        for window in (rp_result.windows if rp_result else []):
            diagnostics = dict(window.diagnostics or {})
            if not diagnostics.get("clock_sync_status"):
                continue
            windows.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "clock_sync_status": diagnostics.get("clock_sync_status", ""),
                    "clock_sync_method": diagnostics.get("clock_sync_method", ""),
                    "clock_sync_source": diagnostics.get("clock_sync_source", ""),
                    "clock_sync_mean_offset_s": diagnostics.get("clock_sync_mean_offset_s"),
                }
            )
        payload = {
            "artifact_type": "acquisition_clock_sync",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "window_count": len(windows),
            "windows": windows,
            "provenance": "Clock synchronization artifact exported from RP run diagnostics.",
        }
        path = export_root / "clock_sync_artifact.json"
        self._write_json(path, payload)
        return path

    def _reference_method_profile(self, reference_id: str) -> dict[str, Any]:
        json_path = self._reference_json_path(reference_id)
        if json_path is None:
            return {
                "status": "reference_not_found" if reference_id else "not_requested",
                "reference_id": reference_id,
                "source_file": "",
                "processing_settings": {},
                "method_metadata": {},
                "metadata_coverage": {},
                "source": "",
            }
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {
                "status": "read_error",
                "reference_id": reference_id,
                "source_file": str(json_path),
                "processing_settings": {},
                "method_metadata": {},
                "metadata_coverage": {},
                "source": "",
            }
        settings = dict(payload.get("processing_settings", {}) if isinstance(payload, dict) else {})
        provenance = generate_reference_provenance(json_path)
        method_metadata = self._coerce_reference_method_metadata(
            provided=payload.get("method_metadata", {}) if isinstance(payload, dict) else {},
            settings=settings,
        )
        coverage = dict(payload.get("method_metadata_coverage", {}) if isinstance(payload, dict) else {})
        if not coverage:
            available = [family for family, metadata in method_metadata.items() if metadata.get("availability") == "reported"]
            not_reported = [family for family, metadata in method_metadata.items() if metadata.get("availability") == "not_reported"]
            coverage = {
                "reported_families": available,
                "not_reported_families": not_reported,
                "reported_count": len(available),
                "total_count": len(method_metadata),
            }
        return {
            "status": "ready",
            "reference_id": reference_id,
            "source_file": str(json_path),
            "source": str(payload.get("source", "") if isinstance(payload, dict) else ""),
            "processing_settings": settings,
            "method_metadata": method_metadata,
            "metadata_coverage": coverage,
            "normalization_command": provenance.get("normalization_command", ""),
            "normalization_time": provenance.get("normalization_time", ""),
            "qc_mapping": provenance.get("qc_mapping_strategy", ""),
            "known_limitations": list(provenance.get("known_limitations", []) or []),
        }

    def _coerce_reference_method_metadata(
        self,
        *,
        provided: Any,
        settings: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        defaults = self._reference_method_metadata(settings=settings)
        if not isinstance(provided, dict) or not provided:
            return defaults
        coerced = dict(defaults)
        for family, payload in provided.items():
            if not isinstance(payload, dict):
                continue
            raw_method = payload.get("raw_method", payload.get("method", payload.get("normalized_method", "")))
            coerced[str(family)] = {
                "reference_field": str(payload.get("reference_field", defaults.get(str(family), {}).get("reference_field", ""))),
                "raw_method": str(raw_method or ""),
                "normalized_method": str(payload.get("normalized_method") or self._normalize_method_name(raw_method, family=str(family))),
                "availability": str(payload.get("availability") or ("reported" if raw_method else "not_reported")),
                "evidence_source": str(payload.get("evidence_source") or ("method_metadata" if raw_method else "missing_from_reference_metadata")),
            }
        return coerced

    def _reference_method_metadata(self, *, settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
        definitions = {
            "rotation": "rotation_mode",
            "lag": "lag_determination",
            "detrend": "detrend_method",
            "density_correction": "density_correction",
            "footprint": "footprint_method",
            "uncertainty": "uncertainty_method",
            "spectral_correction": "frequency_correction",
        }
        metadata: dict[str, dict[str, Any]] = {}
        for family, field_name in definitions.items():
            raw_method = settings.get(field_name, "")
            if family == "spectral_correction" and not raw_method:
                raw_method = settings.get("spectral_correction_method", "")
                field_name = "spectral_correction_method"
            normalized_method = self._normalize_method_name(raw_method, family=family)
            metadata[family] = {
                "reference_field": field_name,
                "raw_method": str(raw_method or ""),
                "normalized_method": normalized_method,
                "availability": "reported" if raw_method else "not_reported",
                "evidence_source": "processing_settings" if raw_method else "missing_from_reference_metadata",
            }
        return metadata

    def _normalize_method_name(self, value: Any, *, family: str = "") -> str:
        method = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "block_average": "block_mean",
            "block_averaging": "block_mean",
            "covariance_maximum": "covariance_max",
            "max_covariance": "covariance_max",
            "double_rotation": "double",
            "wpl_correction": "wpl",
            "webb_pearman_leuning": "wpl",
            "analytical_frequency_correction": "analytical",
        }
        normalized = aliases.get(method, method)
        if family == "density_correction" and normalized == "wpl":
            return "wpl"
        return normalized

    def _method_parity_status(self, *, gas_method: str, reference_method: str, family: str) -> tuple[str, str]:
        gas = str(gas_method or "").strip().lower()
        ref = str(reference_method or "").strip().lower()
        if not ref:
            return "not_reported", "Reference did not expose this method family."
        if not gas:
            return "not_enabled", "gas_ec_studio did not enable this method family."
        gas_norm = self._normalize_method_name(gas, family=family)
        ref_norm = self._normalize_method_name(ref, family=family)
        if gas_norm == ref_norm or gas_norm in ref_norm or ref_norm in gas_norm:
            return "match", "Method names match after normalization."
        if family == "spectral_correction" and ref_norm == "analytical" and gas_norm in {"massman", "horst", "ibrom"}:
            return "compatible_family", "EddyPro reports analytical frequency correction; selected method is an analytical transfer-function family."
        if family == "density_correction" and gas_norm == "wpl" and ref_norm == "wpl":
            return "match", "Both chains use WPL density correction."
        return "differs", f"Method differs: gas_ec_studio={gas_method}, reference={reference_method}."

    def _method_parity_matrix(self, *, rp_result: RPRunResult | None, reference_id: str = "") -> dict[str, Any]:
        method_summary = self._method_summary(rp_result=rp_result, rp_config_snapshot={})
        summary = dict(rp_result.summary or {}) if rp_result is not None else {}
        config_snapshot = dict(summary.get("config_snapshot", {}) if isinstance(summary.get("config_snapshot", {}), dict) else {})
        reference_profile = self._reference_method_profile(reference_id)
        settings = dict(reference_profile.get("processing_settings", {}) or {})
        reference_metadata = dict(reference_profile.get("method_metadata", {}) or self._reference_method_metadata(settings=settings))
        method_compare = dict(method_summary.get("method_compare_summary", {}) or summary.get("method_compare_summary", {}) or {})
        compare_families = dict(method_compare.get("families", {}) or {})
        lag_config = dict(config_snapshot.get("lag_phase", {}) if isinstance(config_snapshot.get("lag_phase", {}), dict) else {})
        steps_config = dict(config_snapshot.get("steps", {}) if isinstance(config_snapshot.get("steps", {}), dict) else {})
        step_lag_config = dict(steps_config.get("lag", {}) if isinstance(steps_config.get("lag", {}), dict) else {})
        step_rotation_config = dict(steps_config.get("rotation", {}) if isinstance(steps_config.get("rotation", {}), dict) else {})
        step_detrend_config = dict(steps_config.get("detrend", {}) if isinstance(steps_config.get("detrend", {}), dict) else {})
        step_density_config = dict(steps_config.get("density_correction", {}) if isinstance(steps_config.get("density_correction", {}), dict) else {})
        rows: list[dict[str, Any]] = []
        definitions = [
            ("rotation", config_snapshot.get("rotation_mode") or step_rotation_config.get("rotation_mode") or summary.get("rotation_mode", ""), settings.get("rotation_mode", "")),
            ("lag", lag_config.get("strategy") or step_lag_config.get("lag_strategy") or step_lag_config.get("strategy") or "", settings.get("lag_determination", "")),
            ("detrend", config_snapshot.get("detrend_mode") or step_detrend_config.get("detrend_mode") or summary.get("detrend_mode", ""), settings.get("detrend_method", "")),
            ("density_correction", config_snapshot.get("density_correction_mode") or step_density_config.get("correction_mode") or summary.get("density_correction_mode", ""), settings.get("density_correction", "")),
            ("footprint", method_summary.get("footprint_method", ""), settings.get("footprint_method", "")),
            ("uncertainty", method_summary.get("uncertainty_method", ""), settings.get("uncertainty_method", "")),
            ("spectral_correction", method_summary.get("spectral_correction_method", ""), settings.get("frequency_correction", settings.get("spectral_correction_method", ""))),
        ]
        for family, gas_method, reference_method in definitions:
            metadata = dict(reference_metadata.get(family, {}) or {})
            reference_method = metadata.get("raw_method", reference_method)
            status, note = self._method_parity_status(
                gas_method=str(gas_method or ""),
                reference_method=str(reference_method or ""),
                family=family,
            )
            compare_summary = dict(compare_families.get(family, {}) or {})
            rows.append(
                {
                    "family": family,
                    "gas_ec_studio_method": str(gas_method or ""),
                    "eddypro_method": str(reference_method or ""),
                    "normalized_gas_ec_studio_method": self._normalize_method_name(gas_method, family=family),
                    "normalized_eddypro_method": metadata.get("normalized_method", self._normalize_method_name(reference_method, family=family)),
                    "reference_field": metadata.get("reference_field", ""),
                    "reference_evidence_source": metadata.get("evidence_source", ""),
                    "reference_availability": metadata.get("availability", "reported" if reference_method else "not_reported"),
                    "status": status,
                    "note": note,
                    "method_compare_recommendation": compare_summary.get("recommendation", ""),
                    "method_compare_max_abs_relative_deviation": compare_summary.get("max_abs_relative_deviation"),
                    "method_compare_methods_run": compare_summary.get("methods_run", []),
                }
            )
        status_counts = {
            status: sum(1 for row in rows if row["status"] == status)
            for status in sorted({row["status"] for row in rows})
        }
        coverage = dict(reference_profile.get("metadata_coverage", {}) or {})
        return {
            "artifact_type": "method_parity_matrix",
            "reference_id": reference_id,
            "reference_profile": reference_profile,
            "metadata_coverage": coverage,
            "directly_comparable_families": [
                row["family"]
                for row in rows
                if row.get("reference_availability") == "reported" and row.get("status") in {"match", "differs", "compatible_family"}
            ],
            "not_reported_families": [row["family"] for row in rows if row.get("status") == "not_reported"],
            "status_counts": status_counts,
            "rows": rows,
            "truthfulness_note": "Only method families present in EddyPro reference metadata are judged directly; missing EddyPro fields are marked not_reported.",
        }

    def export_method_parity_matrix_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
        reference_id: str = "",
    ) -> Path | None:
        if rp_result is None:
            return None
        matrix = self._method_parity_matrix(rp_result=rp_result, reference_id=reference_id)
        path = export_root / "method_parity_matrix.json"
        self._write_json(path, matrix)
        csv_path = export_root / "method_parity_matrix.csv"
        rows = list(matrix.get("rows", []) or [])
        if rows:
            self._write_csv(
                csv_path,
                rows,
                [
                    "family",
                    "gas_ec_studio_method",
                    "eddypro_method",
                    "normalized_gas_ec_studio_method",
                    "normalized_eddypro_method",
                    "reference_field",
                    "reference_evidence_source",
                    "reference_availability",
                    "status",
                    "note",
                    "method_compare_recommendation",
                    "method_compare_max_abs_relative_deviation",
                    "method_compare_methods_run",
                ],
            )
            matrix["companion_files"] = {"csv": str(csv_path)}
            self._write_json(path, matrix)
        return path

    def _reference_json_path(self, reference_id: str) -> Path | None:
        if not reference_id:
            return None
        references_root = Path(__file__).resolve().parent.parent.parent / "references" / "eddypro"
        matches = sorted(references_root.rglob(f"{reference_id}.json"))
        return matches[0] if matches else None

    def _reference_provenance_payload(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        artifact = {}
        if rp_result:
            artifact = dict(rp_result.artifacts.get("reference_provenance", {}) or {})
            if artifact:
                return artifact
        reference_id = str(rp_config_snapshot.get("benchmark", {}).get("reference_id", ""))
        if not reference_id:
            return {}
        json_path = self._reference_json_path(reference_id)
        if json_path is None:
            return {
                "status": "reference_not_found",
                "reference_id": reference_id,
                "source_file": "",
                "normalization_command": "",
            }
        provenance = generate_reference_provenance(json_path)
        provenance["status"] = "ready"
        provenance["source_file"] = provenance.get("original_file", "")
        provenance["qc_mapping"] = provenance.get("qc_mapping_strategy", "")
        provenance_path = json_path.parent / f"{json_path.stem}_provenance.json"
        provenance["provenance_file"] = str(provenance_path)
        provenance["normalization_command"] = (
            f'python {provenance.get("normalization_script", "references/eddypro/normalize_reference.py")} '
            f'"{provenance.get("original_file", json_path.with_suffix(".csv"))}" "{json_path}" --provenance "{provenance_path}"'
        )
        return provenance

    def _copy_artifact_file(self, *, path: str | Path | None, export_root: Path, target_name: str | None = None) -> str:
        if not path:
            return ""
        source = Path(path)
        if not source.exists() or not source.is_file():
            return ""
        target = export_root / (target_name or source.name)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    def export_reference_provenance_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        provenance = self._reference_provenance_payload(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not provenance:
            return None
        artifact = dict(provenance)
        source_file = self._copy_artifact_file(path=artifact.get("source_file"), export_root=export_root)
        json_source = self._copy_artifact_file(path=artifact.get("json_source"), export_root=export_root)
        provenance_file = self._copy_artifact_file(path=artifact.get("provenance_file"), export_root=export_root)
        artifact["copied_source_file"] = source_file
        artifact["copied_json_source"] = json_source
        artifact["copied_provenance_file"] = provenance_file
        artifact["qc_mapping"] = artifact.get("qc_mapping", artifact.get("qc_mapping_strategy", ""))
        path = export_root / "reference_provenance_artifact.json"
        self._write_json(path, artifact)
        return path

    def _network_output_config(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any], site: object | None = None) -> dict[str, Any]:
        config = dict(rp_config_snapshot.get("network_output", {}) or {})
        first_diag = {}
        if rp_result and rp_result.windows:
            first_diag = dict(rp_result.windows[0].diagnostics or {})
        schema_target = str(config.get("schema_target") or first_diag.get("schema_target") or "")
        timestamp_refers_to = str(config.get("timestamp_refers_to") or first_diag.get("fluxnet_timestamp_refers_to") or "start")
        if "end" in timestamp_refers_to.lower():
            timestamp_refers_to = "end"
        else:
            timestamp_refers_to = "start"
        timezone_offset_hours = float(config.get("timezone_offset_hours", first_diag.get("fluxnet_timezone_offset_h", 0.0)) or 0.0)
        gap_fill_value = float(config.get("gap_fill_value", first_diag.get("fluxnet_gap_fill_value", -9999.0)) or -9999.0)
        site_id = getattr(site, "station_code", "") if site is not None else ""
        return {
            "schema_target": schema_target,
            "timestamp_refers_to": timestamp_refers_to,
            "timezone_offset_hours": timezone_offset_hours,
            "gap_fill_value": gap_fill_value,
            "site_id": str(site_id or ""),
        }

    def _network_validation_summary_from_path(self, path: Path | None, *, schema_target: str) -> dict[str, Any]:
        if path is None or not path.exists():
            return {
                "schema_target": schema_target,
                "validation_status": "not_requested" if not schema_target else "artifact_missing",
                "missing_fields": [],
                "artifact": "",
            }
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "schema_target": str(metadata.get("schema_target", schema_target)),
            "validation_status": str(metadata.get("validation_status", "unknown")),
            "missing_fields": list(metadata.get("missing_fields", [])),
            "error_count": int(metadata.get("error_count", 0) or 0),
            "artifact": str(path),
        }

    def _export_network_artifacts(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
        site: object | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        config = self._network_output_config(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot, site=site)
        schema_target = config.get("schema_target", "")
        if not schema_target:
            return (
                {
                    "schema_target": "",
                    "validation_status": "not_requested",
                    "missing_fields": [],
                    "error_count": 0,
                    "artifact": "",
                },
                {},
            )

        files: dict[str, str] = {}
        metadata_path: Path | None = None
        if schema_target == "FLUXNET":
            foundation_path = self.export_fluxnet_half_hourly_artifact(
                rp_result=rp_result,
                export_root=export_root,
                timezone_offset_hours=float(config["timezone_offset_hours"]),
                timestamp_refers_to=str(config["timestamp_refers_to"]),
                gap_fill_value=float(config["gap_fill_value"]),
                site_id=str(config["site_id"]),
            )
            submission_path = self.export_fluxnet_full_submission(
                rp_result=rp_result,
                export_root=export_root,
                timezone_offset_hours=float(config["timezone_offset_hours"]),
                timestamp_refers_to=str(config["timestamp_refers_to"]),
                gap_fill_value=float(config["gap_fill_value"]),
                site_id=str(config["site_id"]),
            )
            if foundation_path is not None:
                files["fluxnet_half_hourly_artifact"] = str(foundation_path)
                csv_path = foundation_path.with_suffix(".csv")
                if csv_path.exists():
                    files["fluxnet_half_hourly_csv"] = str(csv_path)
                metadata_path = foundation_path
            if submission_path is not None:
                files["fluxnet_full_submission"] = str(submission_path)
                csv_path = export_root / "fluxnet_full_submission_data.csv"
                if csv_path.exists():
                    files["fluxnet_full_submission_csv"] = str(csv_path)
        elif schema_target == "AmeriFlux":
            artifact_path = self.export_ameriflux_artifact(
                rp_result=rp_result,
                export_root=export_root,
                timezone_offset_hours=float(config["timezone_offset_hours"]),
                timestamp_refers_to=str(config["timestamp_refers_to"]),
                gap_fill_value=float(config["gap_fill_value"]),
                site_id=str(config["site_id"]),
            )
            if artifact_path is not None:
                metadata_path = artifact_path
                files["ameriflux_artifact"] = str(artifact_path)
                csv_path = export_root / "ameriflux_artifact.csv"
                if csv_path.exists():
                    files["ameriflux_csv"] = str(csv_path)
        elif schema_target == "ICOS":
            artifact_path = self.export_icos_artifact(
                rp_result=rp_result,
                export_root=export_root,
                timezone_offset_hours=float(config["timezone_offset_hours"]),
                timestamp_refers_to=str(config["timestamp_refers_to"]),
                gap_fill_value=float(config["gap_fill_value"]),
                site_id=str(config["site_id"]),
            )
            if artifact_path is not None:
                metadata_path = artifact_path
                files["icos_artifact"] = str(artifact_path)
                csv_path = export_root / "icos_artifact.csv"
                if csv_path.exists():
                    files["icos_csv"] = str(csv_path)

        summary = self._network_validation_summary_from_path(metadata_path, schema_target=schema_target)
        summary.update(
            {
                "timestamp_refers_to": config["timestamp_refers_to"],
                "timezone_offset_hours": config["timezone_offset_hours"],
                "gap_fill_value": config["gap_fill_value"],
            }
        )
        summary_path = export_root / "network_validation_summary.json"
        self._write_json(summary_path, summary)
        files["network_validation_summary"] = str(summary_path)
        return summary, files

    def _empty_spectral_window(self) -> WindowSpectralResult:
        now = datetime(2000, 1, 1)
        return WindowSpectralResult(window_id="", start_time=now, end_time=now, qc_grade="", anomaly_type="", lag_seconds=0.0, lag_confidence=0.0, correction_factor=0.0, high_freq_loss_risk="", reason="")

    def generate_continuous_dataset(
        self,
        *,
        rp_result: RPRunResult | None,
        averaging_period_minutes: float = 30.0,
    ) -> list[dict[str, Any]]:
        if not rp_result or not rp_result.windows:
            return []
        from datetime import timedelta
        period = timedelta(minutes=averaging_period_minutes)
        first_start = min(w.start_time for w in rp_result.windows)
        last_end = max(w.end_time for w in rp_result.windows)
        window_map: dict[int, WindowRPResult] = {}
        for w in rp_result.windows:
            offset = w.start_time - first_start
            slot = int(offset.total_seconds() / period.total_seconds() + 0.5)
            window_map[slot] = w
        total_slots = int((last_end - first_start).total_seconds() / period.total_seconds() + 0.5)
        rows: list[dict[str, Any]] = []
        for slot in range(total_slots):
            slot_start = first_start + slot * period
            slot_end = slot_start + period
            window = window_map.get(slot)
            if window is not None:
                rows.append(self._rp_row(window))
            else:
                rows.append({
                    "window_id": f"gap_{slot_start.isoformat()}",
                    "start_time": slot_start.isoformat(),
                    "end_time": slot_end.isoformat(),
                    "sample_count": 0,
                    "valid_sample_count": 0,
                    "continuity_ratio": 0.0,
                    "missing_ratio": 1.0,
                    "rotation_mode": "",
                    "detrend_mode": "",
                    "lag_seconds": "",
                    "lag_confidence": "",
                    "lag_strategy": "",
                    "cov_w_co2": "",
                    "cov_w_h2o": "",
                    "raw_flux": "",
                    "mixing_ratio_flux": "",
                    "density_corrected_flux": "",
                    "primary_flux": "",
                    "primary_flux_source": "",
                    "water_vapor_flux": "",
                    "sonic_correction_status": "",
                    "sonic_correction_method": "",
                    "sonic_correction_steps": "",
                    "sonic_correction_provenance": "",
                    "crosswind_correction_status": "",
                    "crosswind_correction_method": "",
                    "crosswind_correction_mean_delta_c": "",
                    "crosswind_correction_max_abs_delta_c": "",
                    "crosswind_correction_provenance": "",
                    "clock_sync_status": "",
                    "clock_sync_method": "",
                    "clock_sync_source": "",
                    "clock_sync_mean_offset_s": "",
                    "clock_sync_provenance": "",
                    "ch4_status": "",
                    "ch4_flux_nmol_m2_s": "",
                    "ch4_flux_level0_nmol_m2_s": "",
                    "ch4_flux_corrected_nmol_m2_s": "",
                    "cov_w_ch4_ppb": "",
                    "mean_ch4_ppb": "",
                    "ch4_valid_ratio": "",
                    "ch4_method": "",
                    "ch4_coefficient_profile_id": "",
                    "ch4_coefficient_registry_status": "",
                    "ch4_coefficient_profile_source_file": "",
                    "ch4_coefficient_profile_provenance": "",
                    "ch4_spectral_correction_factor": "",
                    "ch4_water_vapor_dilution_factor": "",
                    "qc_grade": "",
                    "anomaly_type": "gap",
                    "reason": "no data for this averaging period",
                })
        return rows

    def export_qc_details_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            qc = window.diagnostics.get("qc_details", {}) if window.diagnostics else {}
            row = {"window_id": window.window_id, "start_time": window.start_time.isoformat()}
            for test_key, test_result in qc.items():
                if isinstance(test_result, dict):
                    row[f"adv_{test_key}_status"] = test_result.get("status", "")
                    row[f"adv_{test_key}_detail"] = json.dumps(test_result.get("detail", {}), ensure_ascii=False)
            rows.append(row)
        path = export_root / "qc_details.json"
        self._write_json(path, rows)
        return path

    def export_metadata_summary_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            ms = window.diagnostics.get("metadata_summary", {}) if window.diagnostics else {}
            row = {"window_id": window.window_id, "start_time": window.start_time.isoformat()}
            row.update(ms)
            rows.append(row)
        path = export_root / "metadata_summary.json"
        self._write_json(path, rows)
        return path

    def export_stats_foundation_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            turb = window.turbulence_detail or {}
            stat = window.stationarity_detail or {}
            row = {
                "window_id": window.window_id,
                "start_time": window.start_time.isoformat(),
                "end_time": window.end_time.isoformat(),
                "qc_grade": window.qc_grade,
                "stationarity_score": window.stationarity_score,
                "turbulence_score": window.turbulence_score,
                "ustar": window.ustar,
                "var_u": turb.get("var_u", ""),
                "var_v": turb.get("var_v", ""),
                "var_w": turb.get("var_w", ""),
                "cov_uw": turb.get("cov_uw", ""),
                "cov_vw": turb.get("cov_vw", ""),
                "mean_wind_speed": turb.get("mean_wind_speed", ""),
                "mean_wind_dir": turb.get("mean_wind_dir", ""),
            }
            rows.append(row)
        path = export_root / "stats_foundation.json"
        self._write_json(path, rows)
        return path

    def compute_benchmark_summary(
        self,
        *,
        rp_result: RPRunResult | None,
        benchmark_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not benchmark_results:
            return {"status": "no_benchmark", "windows_compared": 0, "windows_pass": 0, "windows_fail": 0, "field_summary": {}}
        total = len(benchmark_results)
        passed = sum(1 for r in benchmark_results if r.get("overall_pass", False))
        field_summary: dict[str, Any] = {}
        for result in benchmark_results:
            for comp in result.get("comparisons", []):
                fname = comp.get("field_name", "")
                if fname not in field_summary:
                    field_summary[fname] = {"total": 0, "passed": 0, "failed": 0, "max_abs_error": 0.0, "max_rel_error": 0.0}
                field_summary[fname]["total"] += 1
                if comp.get("passed", True):
                    field_summary[fname]["passed"] += 1
                else:
                    field_summary[fname]["failed"] += 1
                abs_err = comp.get("absolute_error")
                rel_err = comp.get("relative_error")
                if abs_err is not None:
                    field_summary[fname]["max_abs_error"] = max(field_summary[fname]["max_abs_error"], abs_err)
                if rel_err is not None:
                    field_summary[fname]["max_rel_error"] = max(field_summary[fname]["max_rel_error"], rel_err)
        return {
            "status": "pass" if passed == total else "partial" if passed > 0 else "fail",
            "windows_compared": total,
            "windows_pass": passed,
            "windows_fail": total - passed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "field_summary": field_summary,
        }

    def export_benchmark_summary_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        benchmark_results: list[dict[str, Any]],
        export_root: Path,
        reference_id: str = "",
        thresholds: dict[str, Any] | None = None,
    ) -> Path | None:
        if not benchmark_results:
            return None
        window_lookup = {window.window_id: window for window in (rp_result.windows if rp_result else [])}
        summary = self.compute_benchmark_summary(rp_result=rp_result, benchmark_results=benchmark_results)
        summary["reference_id"] = reference_id
        summary["thresholds"] = thresholds or {}
        summary["method_parity_matrix"] = self._method_parity_matrix(rp_result=rp_result, reference_id=reference_id)
        per_window: list[dict[str, Any]] = []
        for br in benchmark_results:
            entry: dict[str, Any] = {"window_id": br.get("window_id", ""), "overall_pass": br.get("overall_pass", True)}
            window = window_lookup.get(str(br.get("window_id", "")))
            diagnostics = dict(window.diagnostics or {}) if window is not None else {}
            for comp in br.get("comparisons", []):
                fname = comp.get("field_name", "")
                entry[f"{fname}_abs_error"] = comp.get("absolute_error")
                entry[f"{fname}_rel_error"] = comp.get("relative_error")
                entry[f"{fname}_passed"] = comp.get("passed")
                entry[f"{fname}_threshold"] = comp.get("threshold")
                if comp.get("note"):
                    entry[f"{fname}_note"] = comp["note"]
            entry["footprint_method"] = br.get("footprint_method", diagnostics.get("footprint_method", ""))
            entry["footprint_2d_grid_status"] = br.get("footprint_2d_grid_status", diagnostics.get("footprint_2d_grid_status", ""))
            entry["footprint_2d_peak_downwind_m"] = br.get("footprint_2d_peak_downwind_m", diagnostics.get("footprint_2d_peak_downwind_m"))
            entry["footprint_2d_peak_crosswind_m"] = br.get("footprint_2d_peak_crosswind_m", diagnostics.get("footprint_2d_peak_crosswind_m"))
            entry["uncertainty_method"] = br.get("uncertainty_method", diagnostics.get("uncertainty_method", ""))
            entry["spectral_correction_method"] = br.get("spectral_correction_method", diagnostics.get("spectral_correction_method", ""))
            entry["spectral_correction_cospectrum_match"] = br.get("spectral_correction_cospectrum_match", diagnostics.get("spectral_correction_cospectrum_match", {}))
            entry["sonic_correction_method"] = br.get("sonic_correction_method", diagnostics.get("sonic_correction_method", ""))
            entry["sonic_correction_status"] = br.get("sonic_correction_status", diagnostics.get("sonic_correction_status", ""))
            entry["sonic_correction_steps"] = br.get("sonic_correction_steps", diagnostics.get("sonic_correction_steps", []))
            entry["crosswind_correction_method"] = br.get("crosswind_correction_method", diagnostics.get("crosswind_correction_method", ""))
            entry["crosswind_correction_status"] = br.get("crosswind_correction_status", diagnostics.get("crosswind_correction_status", ""))
            entry["crosswind_correction_mean_delta_c"] = br.get("crosswind_correction_mean_delta_c", diagnostics.get("crosswind_correction_mean_delta_c"))
            entry["clock_sync_status"] = br.get("clock_sync_status", diagnostics.get("clock_sync_status", ""))
            entry["clock_sync_method"] = br.get("clock_sync_method", diagnostics.get("clock_sync_method", ""))
            entry["clock_sync_source"] = br.get("clock_sync_source", diagnostics.get("clock_sync_source", ""))
            entry["clock_sync_mean_offset_s"] = br.get("clock_sync_mean_offset_s", diagnostics.get("clock_sync_mean_offset_s"))
            entry["ch4_method"] = br.get("ch4_method", diagnostics.get("ch4_method", ""))
            entry["ch4_flux_nmol_m2_s"] = br.get("ch4_flux_nmol_m2_s", diagnostics.get("ch4_flux_nmol_m2_s"))
            entry["ch4_flux_level0_nmol_m2_s"] = br.get("ch4_flux_level0_nmol_m2_s", diagnostics.get("ch4_flux_level0_nmol_m2_s"))
            entry["ch4_correction_sequence"] = br.get("ch4_correction_sequence", diagnostics.get("ch4_correction_sequence", {}))
            entry["ch4_coefficient_profile_id"] = br.get("ch4_coefficient_profile_id", diagnostics.get("ch4_coefficient_profile_id", ""))
            entry["ch4_coefficient_registry_status"] = br.get("ch4_coefficient_registry_status", diagnostics.get("ch4_coefficient_registry_status", ""))
            entry["ch4_coefficient_profile_provenance"] = br.get("ch4_coefficient_profile_provenance", diagnostics.get("ch4_coefficient_profile_provenance", ""))
            entry["primary_flux_random_error"] = br.get("primary_flux_random_error", diagnostics.get("primary_flux_random_error"))
            entry["primary_flux_relative_uncertainty"] = br.get("primary_flux_relative_uncertainty", diagnostics.get("primary_flux_relative_uncertainty"))
            entry["primary_flux_uncertainty_band"] = br.get("primary_flux_uncertainty_band", diagnostics.get("primary_flux_uncertainty_band"))
            entry["primary_flux_ci_lower"] = br.get("primary_flux_ci_lower", diagnostics.get("primary_flux_ci_lower"))
            entry["primary_flux_ci_upper"] = br.get("primary_flux_ci_upper", diagnostics.get("primary_flux_ci_upper"))
            entry["primary_flux_ci_level"] = br.get("primary_flux_ci_level", diagnostics.get("primary_flux_ci_level"))
            entry["method_compare_summary"] = br.get("method_compare_summary", diagnostics.get("method_compare_summary", {}))
            entry["method_compare_recommendations"] = br.get("method_compare_recommendations", diagnostics.get("method_compare_recommendations", {}))
            entry["method_deviation_notes"] = br.get("method_deviation_notes") or _build_method_deviation_notes(diagnostics, br)
            per_window.append(entry)
        summary["per_window"] = per_window
        path = export_root / "benchmark_summary.json"
        self._write_json(path, summary)
        return path

    def export_fluxnet_half_hourly_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
        timezone_offset_hours: float = 0.0,
        timestamp_refers_to: str = "start",
        gap_fill_value: float = -9999.0,
        site_id: str = "",
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        from datetime import timedelta
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            row = self._fluxnet_half_hourly_row(
                window=window,
                timezone_offset_hours=timezone_offset_hours,
                timestamp_refers_to=timestamp_refers_to,
                gap_fill_value=gap_fill_value,
            )
            rows.append(row)
        continuous = self.generate_continuous_dataset(rp_result=rp_result, averaging_period_minutes=30.0)
        for cont_row in continuous:
            if cont_row.get("anomaly_type") == "gap":
                gap_row = self._fluxnet_gap_row(
                    cont_row=cont_row,
                    timezone_offset_hours=timezone_offset_hours,
                    timestamp_refers_to=timestamp_refers_to,
                    gap_fill_value=gap_fill_value,
                )
                rows.append(gap_row)
        rows.sort(key=lambda r: r.get("TIMESTAMP_START", ""))
        all_errors: list[str] = []
        for row in rows:
            all_errors.extend(validate_fluxnet_row(row, schema_target="FLUXNET"))
        missing_fields = self._detect_missing_fields(rows, NETWORK_SCHEMA_REGISTRY["FLUXNET"]["field_map"])
        metadata = {
            "site_id": site_id,
            "schema_target": "FLUXNET",
            "timezone_offset_hours": timezone_offset_hours,
            "timestamp_refers_to": timestamp_refers_to,
            "gap_fill_value": gap_fill_value,
            "averaging_period_minutes": 30,
            "record_count": len(rows),
            "data_count": sum(1 for r in rows if r.get("FC") != gap_fill_value),
            "gap_count": sum(1 for r in rows if r.get("FC") == gap_fill_value),
            "validation_status": "pass" if not all_errors else "errors_found",
            "error_count": len(all_errors),
            "missing_fields": missing_fields,
            "exported_at": datetime.now().isoformat(),
        }
        artifact = {"metadata": metadata, "rows": rows}
        path = export_root / "fluxnet_half_hourly_foundation.json"
        self._write_json(path, artifact)
        csv_path = export_root / "fluxnet_half_hourly_foundation.csv"
        if rows:
            headers = list(rows[0].keys())
            self._write_csv(csv_path, rows, headers)
        return path

    def _fluxnet_half_hourly_row(
        self,
        *,
        window: WindowRPResult,
        timezone_offset_hours: float,
        timestamp_refers_to: str,
        gap_fill_value: float,
    ) -> dict[str, Any]:
        from datetime import timedelta
        start_utc = window.start_time
        end_utc = window.end_time
        local_start = start_utc + timedelta(hours=timezone_offset_hours)
        local_end = end_utc + timedelta(hours=timezone_offset_hours)
        if timestamp_refers_to == "end":
            ts_start = end_utc.strftime("%Y%m%d%H%M")
            ts_end = (end_utc + timedelta(minutes=30)).strftime("%Y%m%d%H%M")
        else:
            ts_start = start_utc.strftime("%Y%m%d%H%M")
            ts_end = end_utc.strftime("%Y%m%d%H%M")
        doy = local_start.timetuple().tm_yday
        hour = local_start.hour
        minute = local_start.minute
        fc = window.primary_flux if window.primary_flux != 0.0 or window.raw_flux != 0.0 else gap_fill_value
        le = window.water_vapor_flux if window.water_vapor_flux != 0.0 else gap_fill_value
        qc = window.qc_grade
        qc_num = {"A": 0, "B": 1, "C": 2}.get(qc, 2)
        diagnostics = dict(window.diagnostics or {})
        ch4_flux = diagnostics.get("ch4_flux_nmol_m2_s", gap_fill_value)
        ch4_qc = qc_num if diagnostics.get("ch4_status") == "computed" else gap_fill_value
        return {
            "TIMESTAMP_START": ts_start,
            "TIMESTAMP_END": ts_end,
            "DOY": doy,
            "HOUR": hour,
            "MINUTE": minute,
            "FC": fc,
            "FC_QC": qc_num,
            "LE": le,
            "USTAR": window.ustar if window.ustar is not None else gap_fill_value,
            "TA": window.mean_temp_c if window.mean_temp_c != 0.0 else gap_fill_value,
            "PA": window.mean_pressure_kpa * 10.0 if window.mean_pressure_kpa != 0.0 else gap_fill_value,
            "CO2": window.mean_co2_ppm if window.mean_co2_ppm != 0.0 else gap_fill_value,
            "H2O": window.mean_h2o_mmol if window.mean_h2o_mmol != 0.0 else gap_fill_value,
            "FCH4": ch4_flux,
            "FCH4_QC": ch4_qc,
            "FC_RANDOM_ERROR": diagnostics.get("primary_flux_random_error", gap_fill_value),
            "FC_REL_UNCERTAINTY": diagnostics.get("primary_flux_relative_uncertainty", gap_fill_value),
            "FC_CI_LOWER": diagnostics.get("primary_flux_ci_lower", gap_fill_value),
            "FC_CI_UPPER": diagnostics.get("primary_flux_ci_upper", gap_fill_value),
            "FC_CI_LEVEL": diagnostics.get("primary_flux_ci_level", gap_fill_value),
            "FOOTPRINT_METHOD": diagnostics.get("footprint_method", ""),
            "UNCERTAINTY_METHOD": diagnostics.get("uncertainty_method", ""),
            "SPECTRAL_CORRECTION_METHOD": diagnostics.get("spectral_correction_method", ""),
            "METHOD_DEVIATION_NOTES": " | ".join(_build_method_deviation_notes(diagnostics, {})),
            "CLOCK_SYNC_STATUS": diagnostics.get("clock_sync_status", ""),
            "CLOCK_SYNC_METHOD": diagnostics.get("clock_sync_method", ""),
            "CLOCK_SYNC_SOURCE": diagnostics.get("clock_sync_source", ""),
            "CLOCK_SYNC_MEAN_OFFSET_S": diagnostics.get("clock_sync_mean_offset_s", ""),
            "RUNTIME_WATCHDOG_STATUS": diagnostics.get("runtime_watchdog_status", "not_run"),
            "RUNTIME_WATCHDOG_PROFILE": diagnostics.get("runtime_watchdog_profile", "not_configured"),
            "RUNTIME_WATCHDOG_FAIL_COUNT": diagnostics.get("runtime_watchdog_fail_count", 0),
            "RUNTIME_SERVICE_STATUS": diagnostics.get("runtime_service_status", "not_run"),
            "RUNTIME_SERVICE_DELIVERY_STATE": diagnostics.get("runtime_service_delivery_state", "not_run"),
            "RUNTIME_SERVICE_QUARANTINE_COUNT": diagnostics.get("runtime_service_quarantine_count", 0),
            "DAEMON_TELEMETRY_STATUS": diagnostics.get("daemon_telemetry_status", "not_run"),
            "SUPERVISOR_STATE": diagnostics.get("supervisor_state", "not_configured"),
            "PTP_LOCK_STATUS": diagnostics.get("ptp_lock_status", "not_configured"),
            "GPS_PPS_LOCK_STATUS": diagnostics.get("gps_pps_lock_status", "not_configured"),
            "HARDWARE_WATCHDOG_STATUS": diagnostics.get("hardware_watchdog_status", "not_configured"),
            "OS_SUPERVISOR_STATUS": diagnostics.get("os_supervisor_status", "not_configured"),
            "OS_SUPERVISOR_STATE": diagnostics.get("os_supervisor_state", "not_configured"),
            "WATCHDOG_PROVIDER_STATUS": diagnostics.get("watchdog_provider_status", "not_configured"),
            "INSTALLABLE_RUNTIME_STATUS": diagnostics.get("installable_runtime_status", "not_configured"),
            "INSTALLABLE_RUNTIME_TARGETS": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
            if isinstance(diagnostics.get("installable_runtime_targets"), list)
            else diagnostics.get("installable_runtime_targets", ""),
            "RUNTIME_DEPLOYMENT_STATUS": diagnostics.get("runtime_deployment_status", "not_configured"),
            "WIND_SPEED": "",
            "WIND_DIR": "",
            "TIMEZONE_OFFSET_H": timezone_offset_hours,
            "TIMESTAMP_REFERS_TO": timestamp_refers_to,
        }

    def _fluxnet_gap_row(
        self,
        *,
        cont_row: dict[str, Any],
        timezone_offset_hours: float,
        timestamp_refers_to: str,
        gap_fill_value: float,
    ) -> dict[str, Any]:
        from datetime import datetime as _dt, timedelta
        start_iso = cont_row.get("start_time", "")
        end_iso = cont_row.get("end_time", "")
        try:
            start_utc = _dt.fromisoformat(start_iso)
            end_utc = _dt.fromisoformat(end_iso)
        except (ValueError, TypeError):
            start_utc = _dt(2000, 1, 1)
            end_utc = start_utc + timedelta(minutes=30)
        local_start = start_utc + timedelta(hours=timezone_offset_hours)
        if timestamp_refers_to == "end":
            ts_start = end_utc.strftime("%Y%m%d%H%M")
            ts_end = (end_utc + timedelta(minutes=30)).strftime("%Y%m%d%H%M")
        else:
            ts_start = start_utc.strftime("%Y%m%d%H%M")
            ts_end = end_utc.strftime("%Y%m%d%H%M")
        doy = local_start.timetuple().tm_yday
        return {
            "TIMESTAMP_START": ts_start,
            "TIMESTAMP_END": ts_end,
            "DOY": doy,
            "HOUR": local_start.hour,
            "MINUTE": local_start.minute,
            "FC": gap_fill_value,
            "FC_QC": 2,
            "LE": gap_fill_value,
            "USTAR": gap_fill_value,
            "TA": gap_fill_value,
            "PA": gap_fill_value,
            "CO2": gap_fill_value,
            "H2O": gap_fill_value,
            "FCH4": gap_fill_value,
            "FCH4_QC": 2,
            "FC_RANDOM_ERROR": gap_fill_value,
            "FC_REL_UNCERTAINTY": gap_fill_value,
            "FC_CI_LOWER": gap_fill_value,
            "FC_CI_UPPER": gap_fill_value,
            "FC_CI_LEVEL": gap_fill_value,
            "FOOTPRINT_METHOD": "",
            "UNCERTAINTY_METHOD": "",
            "SPECTRAL_CORRECTION_METHOD": "",
            "METHOD_DEVIATION_NOTES": "",
            "CLOCK_SYNC_STATUS": "",
            "CLOCK_SYNC_METHOD": "",
            "CLOCK_SYNC_SOURCE": "",
            "CLOCK_SYNC_MEAN_OFFSET_S": "",
            "RUNTIME_WATCHDOG_STATUS": "gap_fill",
            "RUNTIME_WATCHDOG_PROFILE": "not_configured",
            "RUNTIME_WATCHDOG_FAIL_COUNT": 0,
            "RUNTIME_SERVICE_STATUS": "gap_fill",
            "RUNTIME_SERVICE_DELIVERY_STATE": "not_run",
            "RUNTIME_SERVICE_QUARANTINE_COUNT": 0,
            "DAEMON_TELEMETRY_STATUS": "gap_fill",
            "SUPERVISOR_STATE": "not_configured",
            "PTP_LOCK_STATUS": "not_configured",
            "GPS_PPS_LOCK_STATUS": "not_configured",
            "HARDWARE_WATCHDOG_STATUS": "not_configured",
            "OS_SUPERVISOR_STATUS": "not_configured",
            "OS_SUPERVISOR_STATE": "not_configured",
            "WATCHDOG_PROVIDER_STATUS": "not_configured",
            "INSTALLABLE_RUNTIME_STATUS": "not_configured",
            "INSTALLABLE_RUNTIME_TARGETS": "",
            "RUNTIME_DEPLOYMENT_STATUS": "not_configured",
            "WIND_SPEED": "",
            "WIND_DIR": "",
            "TIMEZONE_OFFSET_H": timezone_offset_hours,
            "TIMESTAMP_REFERS_TO": timestamp_refers_to,
        }

    def export_fluxnet_full_submission(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
        timezone_offset_hours: float = 0.0,
        timestamp_refers_to: str = "start",
        gap_fill_value: float = -9999.0,
        site_id: str = "",
        pi_name: str = "",
        pi_email: str = "",
        site_description: str = "",
        vegetation_type: str = "",
        latitude: float = 0.0,
        longitude: float = 0.0,
        elevation_m: float = 0.0,
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        half_hourly_path = self.export_fluxnet_half_hourly_artifact(
            rp_result=rp_result, export_root=export_root,
            timezone_offset_hours=timezone_offset_hours,
            timestamp_refers_to=timestamp_refers_to,
            gap_fill_value=gap_fill_value, site_id=site_id,
        )
        if half_hourly_path is None:
            return None
        half_hourly_data = json.loads(half_hourly_path.read_text(encoding="utf-8"))
        rows = half_hourly_data.get("rows", [])
        badm_header = {
            "SITE_ID": site_id,
            "SUBMITTER_NAME": pi_name,
            "SUBMITTER_EMAIL": pi_email,
            "SITE_NAME": site_description or site_id,
            "VEGETATION_TYPE": vegetation_type,
            "LATITUDE": latitude,
            "LONGITUDE": longitude,
            "ELEVATION_M": elevation_m,
            "TIMEZONE_OFFSET_H": timezone_offset_hours,
            "TIMESTAMP_REFERS_TO": timestamp_refers_to,
            "GAP_FILL_VALUE": gap_fill_value,
            "AVERAGING_PERIOD_MIN": 30,
        }
        variable_list = []
        for field_name, fmt, description in FLUXNET_HALF_HOURLY_SCHEMA:
            variable_list.append({"name": field_name, "format": fmt, "description": description})
        all_errors: list[str] = []
        for row in rows:
            row_errors = validate_fluxnet_row(row, schema_target="FLUXNET")
            all_errors.extend(row_errors)
        missing_fields = self._detect_missing_fields(rows, NETWORK_SCHEMA_REGISTRY["FLUXNET"]["field_map"])
        validation_summary = {
            "total_rows": len(rows),
            "data_rows": sum(1 for r in rows if r.get("FC") != gap_fill_value),
            "gap_rows": sum(1 for r in rows if r.get("FC") == gap_fill_value),
            "error_count": len(all_errors),
            "unique_errors": list(dict.fromkeys(all_errors))[:20],
            "valid": len(all_errors) == 0,
        }
        submission = {
            "metadata": {
                "schema_target": "FLUXNET",
                "validation_status": "pass" if not all_errors else "errors_found",
                "missing_fields": missing_fields,
                "error_count": len(all_errors),
                "record_count": len(rows),
            },
            "badm_header": badm_header,
            "variable_list": variable_list,
            "validation_summary": validation_summary,
            "half_hourly_data_file": "fluxnet_half_hourly_foundation.json",
            "half_hourly_csv_file": "fluxnet_half_hourly_foundation.csv",
            "exported_at": datetime.now().isoformat(),
        }
        path = export_root / "fluxnet_full_submission.json"
        self._write_json(path, submission)
        csv_path = export_root / "fluxnet_full_submission_data.csv"
        if rows:
            headers = list(rows[0].keys())
            self._write_csv(csv_path, rows, headers)
        return path

    def export_ameriflux_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
        timezone_offset_hours: float = 0.0,
        timestamp_refers_to: str = "start",
        gap_fill_value: float = -9999.0,
        site_id: str = "",
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        from datetime import timedelta
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            internal_row = self._fluxnet_half_hourly_row(
                window=window,
                timezone_offset_hours=timezone_offset_hours,
                timestamp_refers_to=timestamp_refers_to,
                gap_fill_value=gap_fill_value,
            )
            ameriflux_row = self._remap_row(internal_row, AMERIFLUX_FIELD_MAP)
            start_utc = window.start_time
            local_start = start_utc + timedelta(hours=timezone_offset_hours)
            ameriflux_row["TIMESTAMP_START"] = local_start.strftime("%Y-%m-%d %H:%M")
            end_local = window.end_time + timedelta(hours=timezone_offset_hours)
            ameriflux_row["TIMESTAMP_END"] = end_local.strftime("%Y-%m-%d %H:%M")
            rows.append(ameriflux_row)
        continuous = self.generate_continuous_dataset(rp_result=rp_result, averaging_period_minutes=30.0)
        for cont_row in continuous:
            if cont_row.get("anomaly_type") == "gap":
                gap_internal = self._fluxnet_gap_row(
                    cont_row=cont_row,
                    timezone_offset_hours=timezone_offset_hours,
                    timestamp_refers_to=timestamp_refers_to,
                    gap_fill_value=gap_fill_value,
                )
                ameriflux_gap = self._remap_row(gap_internal, AMERIFLUX_FIELD_MAP)
                try:
                    from datetime import datetime as _dt
                    ts = _dt.strptime(gap_internal["TIMESTAMP_START"], "%Y%m%d%H%M") + timedelta(hours=timezone_offset_hours)
                    ameriflux_gap["TIMESTAMP_START"] = ts.strftime("%Y-%m-%d %H:%M")
                    ts_end = _dt.strptime(gap_internal["TIMESTAMP_END"], "%Y%m%d%H%M") + timedelta(hours=timezone_offset_hours)
                    ameriflux_gap["TIMESTAMP_END"] = ts_end.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    pass
                rows.append(ameriflux_gap)
        rows.sort(key=lambda r: r.get("TIMESTAMP_START", ""))
        all_errors: list[str] = []
        for row in rows:
            row_errors = validate_fluxnet_row(row, schema_target="AmeriFlux")
            all_errors.extend(row_errors)
        missing_fields = self._detect_missing_fields(rows, AMERIFLUX_FIELD_MAP)
        validation_status = "pass" if not all_errors else "errors_found"
        metadata = {
            "site_id": site_id,
            "schema_target": "AmeriFlux",
            "timezone_offset_hours": timezone_offset_hours,
            "timestamp_refers_to": timestamp_refers_to,
            "gap_fill_value": gap_fill_value,
            "record_count": len(rows),
            "validation_status": validation_status,
            "error_count": len(all_errors),
            "missing_fields": missing_fields,
            "exported_at": datetime.now().isoformat(),
        }
        artifact = {"metadata": metadata, "rows": rows}
        path = export_root / "ameriflux_artifact.json"
        self._write_json(path, artifact)
        csv_path = export_root / "ameriflux_artifact.csv"
        if rows:
            headers = list(rows[0].keys())
            self._write_csv(csv_path, rows, headers)
        return path

    def export_icos_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
        timezone_offset_hours: float = 0.0,
        timestamp_refers_to: str = "start",
        gap_fill_value: float = -9999.0,
        site_id: str = "",
    ) -> Path | None:
        if not rp_result or not rp_result.windows:
            return None
        from datetime import timedelta
        rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            internal_row = self._fluxnet_half_hourly_row(
                window=window,
                timezone_offset_hours=timezone_offset_hours,
                timestamp_refers_to=timestamp_refers_to,
                gap_fill_value=gap_fill_value,
            )
            icos_row = self._remap_row(internal_row, ICOS_FIELD_MAP)
            icos_row["TIMESTAMP_START"] = window.start_time.isoformat()
            icos_row["TIMESTAMP_END"] = window.end_time.isoformat()
            rows.append(icos_row)
        continuous = self.generate_continuous_dataset(rp_result=rp_result, averaging_period_minutes=30.0)
        for cont_row in continuous:
            if cont_row.get("anomaly_type") == "gap":
                gap_internal = self._fluxnet_gap_row(
                    cont_row=cont_row,
                    timezone_offset_hours=timezone_offset_hours,
                    timestamp_refers_to=timestamp_refers_to,
                    gap_fill_value=gap_fill_value,
                )
                icos_gap = self._remap_row(gap_internal, ICOS_FIELD_MAP)
                icos_gap["TIMESTAMP_START"] = cont_row.get("start_time", "")
                icos_gap["TIMESTAMP_END"] = cont_row.get("end_time", "")
                rows.append(icos_gap)
        rows.sort(key=lambda r: r.get("TIMESTAMP_START", ""))
        all_errors: list[str] = []
        for row in rows:
            row_errors = validate_fluxnet_row(row, schema_target="ICOS")
            all_errors.extend(row_errors)
        missing_fields = self._detect_missing_fields(rows, ICOS_FIELD_MAP)
        validation_status = "pass" if not all_errors else "errors_found"
        metadata = {
            "site_id": site_id,
            "schema_target": "ICOS",
            "timezone_offset_hours": timezone_offset_hours,
            "timestamp_refers_to": timestamp_refers_to,
            "gap_fill_value": gap_fill_value,
            "record_count": len(rows),
            "validation_status": validation_status,
            "error_count": len(all_errors),
            "missing_fields": missing_fields,
            "exported_at": datetime.now().isoformat(),
        }
        artifact = {"metadata": metadata, "rows": rows}
        path = export_root / "icos_artifact.json"
        self._write_json(path, artifact)
        csv_path = export_root / "icos_artifact.csv"
        if rows:
            headers = list(rows[0].keys())
            self._write_csv(csv_path, rows, headers)
        return path

    def _remap_row(self, internal_row: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
        remapped: dict[str, Any] = {}
        for internal_key, external_key in field_map.items():
            val = internal_row.get(internal_key)
            remapped[external_key] = val
        return remapped

    def _detect_missing_fields(self, rows: list[dict[str, Any]], field_map: dict[str, str]) -> list[str]:
        if not rows:
            return list(field_map.values())
        missing: list[str] = []
        for internal_key, external_key in field_map.items():
            all_empty = all(
                row.get(external_key) in (None, "", -9999, -9999.0)
                for row in rows
            )
            if all_empty and internal_key not in ("WIND_SPEED", "WIND_DIR"):
                missing.append(external_key)
        return missing

    def export_parity_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        benchmark_results: list[dict[str, Any]],
        export_root: Path,
        reference_id: str = "",
        thresholds: dict[str, Any] | None = None,
    ) -> Path | None:
        if not rp_result or not rp_result.windows or not benchmark_results:
            return None
        per_window: list[dict[str, Any]] = []
        for window in rp_result.windows:
            diag = window.diagnostics or {}
            bm_dev = diag.get("benchmark_deviation_summary", {})
            if not bm_dev or bm_dev.get("status") == "reference_not_found":
                per_window.append({
                    "window_id": window.window_id,
                    "primary_flux": window.primary_flux,
                    "source": window.primary_flux_source,
                    "lag_seconds": window.lag_seconds,
                    "lag_strategy": diag.get("lag_strategy", ""),
                    "rotation_mode": window.rotation_mode,
                    "applied_rotation_impl": diag.get("applied_rotation_impl", ""),
                    "wpl_water_vapor_term": diag.get("wpl_water_vapor_term"),
                    "wpl_sensible_heat_term": diag.get("wpl_sensible_heat_term"),
                    "qc_grade": window.qc_grade,
                "qc_mapping": "EddyPro 0/1/2 -> A/B/C",
                "match_strategy": "none",
                "absolute_error": None,
                "relative_error": None,
                "pass_rate": None,
                "notes": "no matching reference window",
                "primary_flux_random_error": diag.get("primary_flux_random_error"),
                "primary_flux_relative_uncertainty": diag.get("primary_flux_relative_uncertainty"),
                "primary_flux_uncertainty_band": diag.get("primary_flux_uncertainty_band"),
                "primary_flux_ci_lower": diag.get("primary_flux_ci_lower"),
                "primary_flux_ci_upper": diag.get("primary_flux_ci_upper"),
                "primary_flux_ci_level": diag.get("primary_flux_ci_level"),
                "footprint_method": diag.get("footprint_method", ""),
                "footprint_2d_grid_status": diag.get("footprint_2d_grid_status", ""),
                "footprint_2d_peak_downwind_m": diag.get("footprint_2d_peak_downwind_m"),
                "footprint_2d_peak_crosswind_m": diag.get("footprint_2d_peak_crosswind_m"),
                "uncertainty_method": diag.get("uncertainty_method", ""),
                "spectral_correction_method": diag.get("spectral_correction_method", ""),
                "spectral_correction_cospectrum_match": diag.get("spectral_correction_cospectrum_match", {}),
                "sonic_correction_method": diag.get("sonic_correction_method", ""),
                "sonic_correction_status": diag.get("sonic_correction_status", ""),
                "sonic_correction_steps": diag.get("sonic_correction_steps", []),
                "crosswind_correction_method": diag.get("crosswind_correction_method", ""),
                "crosswind_correction_status": diag.get("crosswind_correction_status", ""),
                "crosswind_correction_mean_delta_c": diag.get("crosswind_correction_mean_delta_c"),
                "clock_sync_status": diag.get("clock_sync_status", ""),
                "clock_sync_method": diag.get("clock_sync_method", ""),
                "clock_sync_source": diag.get("clock_sync_source", ""),
                "clock_sync_mean_offset_s": diag.get("clock_sync_mean_offset_s"),
                "ch4_method": diag.get("ch4_method", ""),
                "ch4_flux_nmol_m2_s": diag.get("ch4_flux_nmol_m2_s"),
                "ch4_flux_level0_nmol_m2_s": diag.get("ch4_flux_level0_nmol_m2_s"),
                "ch4_correction_sequence": diag.get("ch4_correction_sequence", {}),
                "ch4_coefficient_profile_id": diag.get("ch4_coefficient_profile_id", ""),
                "ch4_coefficient_registry_status": diag.get("ch4_coefficient_registry_status", ""),
                "ch4_coefficient_profile_provenance": diag.get("ch4_coefficient_profile_provenance", ""),
                "method_compare_summary": diag.get("method_compare_summary", {}),
                "method_compare_recommendations": diag.get("method_compare_recommendations", {}),
                "method_deviation_notes": _build_method_deviation_notes(diag, {}),
            })
                continue
            comparisons = bm_dev.get("comparisons", [])
            overall_pass = bm_dev.get("overall_pass", True)
            match_strategy = bm_dev.get("match_strategy", "")
            matched_ref_id = bm_dev.get("matched_reference_window_id", "")
            flux_comp = next((c for c in comparisons if c.get("field_name") == "primary_flux"), {})
            per_window.append({
                "window_id": window.window_id,
                "primary_flux": window.primary_flux,
                "source": window.primary_flux_source,
                "lag_seconds": window.lag_seconds,
                "lag_strategy": diag.get("lag_strategy", ""),
                "rotation_mode": window.rotation_mode,
                "applied_rotation_impl": diag.get("applied_rotation_impl", ""),
                "wpl_water_vapor_term": diag.get("wpl_water_vapor_term"),
                "wpl_sensible_heat_term": diag.get("wpl_sensible_heat_term"),
                "qc_grade": window.qc_grade,
                "qc_mapping": "EddyPro 0/1/2 -> A/B/C",
                "match_strategy": match_strategy,
                "matched_reference_window_id": matched_ref_id,
                "absolute_error": flux_comp.get("absolute_error"),
                "relative_error": flux_comp.get("relative_error"),
                "pass_rate": 1.0 if overall_pass else 0.0,
                "notes": "; ".join(c.get("note", "") for c in comparisons if c.get("note")),
                "primary_flux_random_error": diag.get("primary_flux_random_error"),
                "primary_flux_relative_uncertainty": diag.get("primary_flux_relative_uncertainty"),
                "primary_flux_uncertainty_band": diag.get("primary_flux_uncertainty_band"),
                "primary_flux_ci_lower": diag.get("primary_flux_ci_lower"),
                "primary_flux_ci_upper": diag.get("primary_flux_ci_upper"),
                "primary_flux_ci_level": diag.get("primary_flux_ci_level"),
                "footprint_method": diag.get("footprint_method", ""),
                "footprint_2d_grid_status": diag.get("footprint_2d_grid_status", ""),
                "footprint_2d_peak_downwind_m": diag.get("footprint_2d_peak_downwind_m"),
                "footprint_2d_peak_crosswind_m": diag.get("footprint_2d_peak_crosswind_m"),
                "uncertainty_method": diag.get("uncertainty_method", ""),
                "spectral_correction_method": diag.get("spectral_correction_method", ""),
                "spectral_correction_cospectrum_match": diag.get("spectral_correction_cospectrum_match", {}),
                "sonic_correction_method": diag.get("sonic_correction_method", ""),
                "sonic_correction_status": diag.get("sonic_correction_status", ""),
                "sonic_correction_steps": diag.get("sonic_correction_steps", []),
                "crosswind_correction_method": diag.get("crosswind_correction_method", ""),
                "crosswind_correction_status": diag.get("crosswind_correction_status", ""),
                "crosswind_correction_mean_delta_c": diag.get("crosswind_correction_mean_delta_c"),
                "clock_sync_status": diag.get("clock_sync_status", ""),
                "clock_sync_method": diag.get("clock_sync_method", ""),
                "clock_sync_source": diag.get("clock_sync_source", ""),
                "clock_sync_mean_offset_s": diag.get("clock_sync_mean_offset_s"),
                "ch4_method": diag.get("ch4_method", ""),
                "ch4_flux_nmol_m2_s": diag.get("ch4_flux_nmol_m2_s"),
                "ch4_flux_level0_nmol_m2_s": diag.get("ch4_flux_level0_nmol_m2_s"),
                "ch4_correction_sequence": diag.get("ch4_correction_sequence", {}),
                "ch4_coefficient_profile_id": diag.get("ch4_coefficient_profile_id", ""),
                "ch4_coefficient_registry_status": diag.get("ch4_coefficient_registry_status", ""),
                "ch4_coefficient_profile_provenance": diag.get("ch4_coefficient_profile_provenance", ""),
                "method_compare_summary": diag.get("method_compare_summary", {}),
                "method_compare_recommendations": diag.get("method_compare_recommendations", {}),
                "method_deviation_notes": _build_method_deviation_notes(diag, bm_dev),
            })
        total = len(per_window)
        matched = [w for w in per_window if w.get("match_strategy") != "none"]
        passed = sum(1 for w in matched if w.get("pass_rate") == 1.0)
        overall_pass_rate = passed / len(matched) if matched else 0.0
        artifact = {
            "reference_id": reference_id,
            "thresholds": thresholds or {},
            "method_parity_matrix": self._method_parity_matrix(rp_result=rp_result, reference_id=reference_id),
            "total_windows": total,
            "matched_windows": len(matched),
            "passed_windows": passed,
            "overall_pass_rate": overall_pass_rate,
            "per_window": per_window,
            "exported_at": datetime.now().isoformat(),
        }
        path = export_root / "cross_software_parity_artifact.json"
        self._write_json(path, artifact)
        return path


def _build_method_deviation_notes(diag: dict[str, Any], bm_dev: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    fp_method = diag.get("footprint_method", "")
    if fp_method:
        fp_detail = diag.get("footprint_detail", {})
        fp_prov = fp_detail.get("provenance", "") if isinstance(fp_detail, dict) else ""
        fp_grid = diag.get("footprint_2d_grid_status", "")
        grid_text = f"; grid2d={fp_grid}" if fp_grid else ""
        notes.append(f"footprint: {fp_method}{grid_text}" + (f" ({fp_prov})" if fp_prov else ""))
    unc_method = diag.get("uncertainty_method", "")
    if unc_method:
        unc_detail = diag.get("uncertainty_method_detail", {})
        unc_prov = unc_detail.get("provenance", "") if isinstance(unc_detail, dict) else ""
        unc_band = diag.get("primary_flux_uncertainty_band")
        band_text = f"; band={float(unc_band):.6f}" if isinstance(unc_band, (int, float)) else ""
        notes.append(f"uncertainty: {unc_method}{band_text}" + (f" ({unc_prov})" if unc_prov else ""))
    sc_method = diag.get("spectral_correction_method", "")
    if sc_method:
        sc_factor = diag.get("spectral_correction_factor", 1.0)
        sc_prov = diag.get("spectral_correction_provenance", "")
        cospectrum_source = diag.get("spectral_correction_measured_cospectrum_source", "")
        source_text = f"; cospectrum={cospectrum_source}" if cospectrum_source else ""
        cospectrum_match = diag.get("spectral_correction_cospectrum_match", {})
        if isinstance(cospectrum_match, dict) and cospectrum_match.get("match_strategy"):
            source_text = (
                f"{source_text}; match={cospectrum_match.get('match_strategy')}"
                f"/q={cospectrum_match.get('match_quality', 0.0)}"
            )
        notes.append(
            f"spectral_correction: {sc_method} (factor={sc_factor}){source_text}"
            + (f" [{sc_prov}]" if sc_prov else "")
        )
    sonic_method = diag.get("sonic_correction_method", "")
    sonic_status = diag.get("sonic_correction_status", "")
    if sonic_method and sonic_status not in {"", "disabled"}:
        steps = diag.get("sonic_correction_steps", [])
        step_count = len(steps) if isinstance(steps, list) else 0
        notes.append(f"sonic_correction: {sonic_method}; status={sonic_status}; steps={step_count}")
    crosswind_method = diag.get("crosswind_correction_method", "")
    crosswind_status = diag.get("crosswind_correction_status", "")
    if crosswind_method and crosswind_status not in {"", "disabled"}:
        delta = diag.get("crosswind_correction_mean_delta_c")
        delta_text = f"; mean_delta_c={float(delta):.6f}" if isinstance(delta, (int, float)) else ""
        notes.append(f"crosswind_correction: {crosswind_method}; status={crosswind_status}{delta_text}")
    clock_status = diag.get("clock_sync_status", "")
    if clock_status and clock_status not in {"", "disabled"}:
        mean_offset = diag.get("clock_sync_mean_offset_s")
        offset_text = f"; mean_offset_s={float(mean_offset):.6f}" if isinstance(mean_offset, (int, float)) else ""
        notes.append(
            f"clock_sync: {diag.get('clock_sync_method', '')}; "
            f"source={diag.get('clock_sync_source', '')}; status={clock_status}{offset_text}"
        )
    ch4_method = diag.get("ch4_method", "")
    if ch4_method:
        ch4_flux = diag.get("ch4_flux_nmol_m2_s")
        ch4_level0 = diag.get("ch4_flux_level0_nmol_m2_s")
        final_text = f"; final={float(ch4_flux):.6f} nmol m-2 s-1" if isinstance(ch4_flux, (int, float)) else ""
        level0_text = f"; level0={float(ch4_level0):.6f}" if isinstance(ch4_level0, (int, float)) else ""
        coefficient_profile = diag.get("ch4_coefficient_profile_id", "")
        coefficient_text = f"; coefficient_profile={coefficient_profile}" if coefficient_profile else ""
        notes.append(f"trace_gas_ch4: {ch4_method}{level0_text}{final_text}{coefficient_text}")
    method_compare = diag.get("method_compare_recommendations", {})
    if isinstance(method_compare, dict) and method_compare:
        notes.append(
            "method_compare: "
            + ", ".join(f"{family}={recommendation}" for family, recommendation in sorted(method_compare.items()))
        )
    return notes


FLUXNET_HALF_HOURLY_SCHEMA = [
    ("TIMESTAMP_START", "YYYYMMDDHHmm", "UTC start of averaging period"),
    ("TIMESTAMP_END", "YYYYMMDDHHmm", "UTC end of averaging period"),
    ("DOY", "1-366", "Day of year in local time"),
    ("HOUR", "0-23", "Hour in local time"),
    ("MINUTE", "0-59", "Minute in local time"),
    ("FC", "umol m-2 s-1", "CO2 flux"),
    ("FC_QC", "0/1/2", "QC flag: 0=best, 1=moderate, 2=poor"),
    ("LE", "W m-2", "Latent heat flux"),
    ("USTAR", "m s-1", "Friction velocity"),
    ("TA", "degC", "Air temperature"),
    ("PA", "kPa*10", "Atmospheric pressure (in hPa)"),
    ("CO2", "umol mol-1", "CO2 mixing ratio"),
    ("H2O", "mmol m-3", "H2O concentration"),
    ("FCH4", "nmol m-2 s-1", "Methane flux"),
    ("FCH4_QC", "0/1/2", "Methane flux QC flag"),
    ("FC_RANDOM_ERROR", "umol m-2 s-1", "Random uncertainty propagated to flux space"),
    ("FC_REL_UNCERTAINTY", "fraction", "Relative uncertainty propagated to primary flux"),
    ("FC_CI_LOWER", "umol m-2 s-1", "Lower confidence bound for FC"),
    ("FC_CI_UPPER", "umol m-2 s-1", "Upper confidence bound for FC"),
    ("FC_CI_LEVEL", "0-1", "Confidence level used for FC interval"),
    ("FOOTPRINT_METHOD", "text", "Footprint model used for the run"),
    ("UNCERTAINTY_METHOD", "text", "Random uncertainty method used for the run"),
    ("SPECTRAL_CORRECTION_METHOD", "text", "Spectral correction method used for the run"),
    ("METHOD_DEVIATION_NOTES", "text", "Method provenance notes for benchmark/export review"),
    ("CLOCK_SYNC_STATUS", "text", "Acquisition clock synchronization status"),
    ("CLOCK_SYNC_METHOD", "text", "Clock synchronization method"),
    ("CLOCK_SYNC_SOURCE", "text", "GPS/PTP/manual clock source label"),
    ("CLOCK_SYNC_MEAN_OFFSET_S", "seconds", "Mean timestamp correction applied before windowing"),
    ("RUNTIME_WATCHDOG_STATUS", "text", "Headless/SmartFlux-style runtime watchdog status"),
    ("RUNTIME_WATCHDOG_PROFILE", "text", "Runtime watchdog profile id"),
    ("RUNTIME_WATCHDOG_FAIL_COUNT", "count", "Failed runtime watchdog checks"),
    ("RUNTIME_SERVICE_STATUS", "text", "Headless runtime service status"),
    ("RUNTIME_SERVICE_DELIVERY_STATE", "text", "Runtime service delivery readiness state"),
    ("RUNTIME_SERVICE_QUARANTINE_COUNT", "count", "Inputs quarantined by runtime service"),
    ("DAEMON_TELEMETRY_STATUS", "text", "Daemon telemetry aggregate status"),
    ("SUPERVISOR_STATE", "text", "Runtime supervisor state"),
    ("PTP_LOCK_STATUS", "text", "PTP servo lock status"),
    ("GPS_PPS_LOCK_STATUS", "text", "GPS PPS lock status"),
    ("HARDWARE_WATCHDOG_STATUS", "text", "Hardware watchdog event status"),
    ("OS_SUPERVISOR_STATUS", "text", "OS supervisor integration status"),
    ("OS_SUPERVISOR_STATE", "text", "Normalized OS supervisor service state"),
    ("WATCHDOG_PROVIDER_STATUS", "text", "Hardware watchdog provider handoff status"),
    ("TIMEZONE_OFFSET_H", "hours", "UTC offset for local time"),
    ("TIMESTAMP_REFERS_TO", "start/end", "Whether timestamp refers to start or end of period"),
]

AMERIFLUX_FIELD_MAP = {
    "TIMESTAMP_START": "TIMESTAMP_START",
    "TIMESTAMP_END": "TIMESTAMP_END",
    "FC": "FC",
    "FC_QC": "QC_FLAG",
    "LE": "LE",
    "USTAR": "USTAR",
    "TA": "TA",
    "PA": "PA",
    "CO2": "CO2",
    "H2O": "H2O",
    "FCH4": "FCH4",
    "FCH4_QC": "FCH4_QC",
    "FC_RANDOM_ERROR": "FC_RANDOM_ERROR",
    "FC_REL_UNCERTAINTY": "FC_REL_UNCERTAINTY",
    "FC_CI_LOWER": "FC_CI_LOWER",
    "FC_CI_UPPER": "FC_CI_UPPER",
    "FC_CI_LEVEL": "FC_CI_LEVEL",
    "FOOTPRINT_METHOD": "FOOTPRINT_METHOD",
    "UNCERTAINTY_METHOD": "UNCERTAINTY_METHOD",
    "SPECTRAL_CORRECTION_METHOD": "SPECTRAL_CORRECTION_METHOD",
    "METHOD_DEVIATION_NOTES": "METHOD_DEVIATION_NOTES",
    "CLOCK_SYNC_STATUS": "CLOCK_SYNC_STATUS",
    "CLOCK_SYNC_METHOD": "CLOCK_SYNC_METHOD",
    "CLOCK_SYNC_SOURCE": "CLOCK_SYNC_SOURCE",
    "CLOCK_SYNC_MEAN_OFFSET_S": "CLOCK_SYNC_MEAN_OFFSET_S",
    "RUNTIME_WATCHDOG_STATUS": "RUNTIME_WATCHDOG_STATUS",
    "RUNTIME_WATCHDOG_PROFILE": "RUNTIME_WATCHDOG_PROFILE",
    "RUNTIME_WATCHDOG_FAIL_COUNT": "RUNTIME_WATCHDOG_FAIL_COUNT",
    "RUNTIME_SERVICE_STATUS": "RUNTIME_SERVICE_STATUS",
    "RUNTIME_SERVICE_DELIVERY_STATE": "RUNTIME_SERVICE_DELIVERY_STATE",
    "RUNTIME_SERVICE_QUARANTINE_COUNT": "RUNTIME_SERVICE_QUARANTINE_COUNT",
    "DAEMON_TELEMETRY_STATUS": "DAEMON_TELEMETRY_STATUS",
    "SUPERVISOR_STATE": "SUPERVISOR_STATE",
    "PTP_LOCK_STATUS": "PTP_LOCK_STATUS",
    "GPS_PPS_LOCK_STATUS": "GPS_PPS_LOCK_STATUS",
    "HARDWARE_WATCHDOG_STATUS": "HARDWARE_WATCHDOG_STATUS",
    "OS_SUPERVISOR_STATUS": "OS_SUPERVISOR_STATUS",
    "OS_SUPERVISOR_STATE": "OS_SUPERVISOR_STATE",
    "WATCHDOG_PROVIDER_STATUS": "WATCHDOG_PROVIDER_STATUS",
    "WIND_SPEED": "WS",
    "WIND_DIR": "WD",
}

ICOS_FIELD_MAP = {
    "TIMESTAMP_START": "TIMESTAMP_START",
    "TIMESTAMP_END": "TIMESTAMP_END",
    "FC": "Fc",
    "FC_QC": "Fc_QC",
    "LE": "LE",
    "USTAR": "ustar",
    "TA": "Ta",
    "PA": "Pa",
    "CO2": "CO2",
    "H2O": "H2O",
    "FCH4": "FCH4",
    "FCH4_QC": "FCH4_QC",
    "FC_RANDOM_ERROR": "FcRandomError",
    "FC_REL_UNCERTAINTY": "FcRelUncertainty",
    "FC_CI_LOWER": "FcCiLower",
    "FC_CI_UPPER": "FcCiUpper",
    "FC_CI_LEVEL": "FcCiLevel",
    "FOOTPRINT_METHOD": "FootprintMethod",
    "UNCERTAINTY_METHOD": "UncertaintyMethod",
    "SPECTRAL_CORRECTION_METHOD": "SpectralCorrectionMethod",
    "METHOD_DEVIATION_NOTES": "MethodDeviationNotes",
    "CLOCK_SYNC_STATUS": "ClockSyncStatus",
    "CLOCK_SYNC_METHOD": "ClockSyncMethod",
    "CLOCK_SYNC_SOURCE": "ClockSyncSource",
    "CLOCK_SYNC_MEAN_OFFSET_S": "ClockSyncMeanOffsetS",
    "RUNTIME_WATCHDOG_STATUS": "RuntimeWatchdogStatus",
    "RUNTIME_WATCHDOG_PROFILE": "RuntimeWatchdogProfile",
    "RUNTIME_WATCHDOG_FAIL_COUNT": "RuntimeWatchdogFailCount",
    "RUNTIME_SERVICE_STATUS": "RuntimeServiceStatus",
    "RUNTIME_SERVICE_DELIVERY_STATE": "RuntimeServiceDeliveryState",
    "RUNTIME_SERVICE_QUARANTINE_COUNT": "RuntimeServiceQuarantineCount",
    "DAEMON_TELEMETRY_STATUS": "DaemonTelemetryStatus",
    "SUPERVISOR_STATE": "SupervisorState",
    "PTP_LOCK_STATUS": "PtpLockStatus",
    "GPS_PPS_LOCK_STATUS": "GpsPpsLockStatus",
    "HARDWARE_WATCHDOG_STATUS": "HardwareWatchdogStatus",
    "OS_SUPERVISOR_STATUS": "OsSupervisorStatus",
    "OS_SUPERVISOR_STATE": "OsSupervisorState",
    "WATCHDOG_PROVIDER_STATUS": "WatchdogProviderStatus",
    "WIND_SPEED": "WindSpeed",
    "WIND_DIR": "WindDir",
}

NETWORK_SCHEMA_REGISTRY = {
    "FLUXNET": {
        "field_map": {k: k for k, _, _ in FLUXNET_HALF_HOURLY_SCHEMA},
        "timestamp_format": "YYYYMMDDHHmm",
        "gap_value": -9999,
        "qc_scale": "0-2",
        "averaging_period_min": 30,
    },
    "AmeriFlux": {
        "field_map": AMERIFLUX_FIELD_MAP,
        "timestamp_format": "YYYY-MM-DD HH:MM",
        "gap_value": -9999,
        "qc_scale": "0-2",
        "averaging_period_min": 30,
    },
    "ICOS": {
        "field_map": ICOS_FIELD_MAP,
        "timestamp_format": "ISO8601",
        "gap_value": -9999,
        "qc_scale": "0-2",
        "averaging_period_min": 30,
    },
}


def validate_fluxnet_row(row: dict[str, Any], *, schema_target: str = "FLUXNET") -> list[str]:
    errors: list[str] = []
    schema = NETWORK_SCHEMA_REGISTRY.get(schema_target)
    if schema is None:
        errors.append(f"Unknown schema_target: {schema_target}")
        return errors
    field_map = schema["field_map"]
    ts_start_key = field_map.get("TIMESTAMP_START", "TIMESTAMP_START")
    fc_key = field_map.get("FC", "FC")
    qc_key = field_map.get("FC_QC", "FC_QC")
    doy_key = field_map.get("DOY", "DOY")
    gap_value = schema["gap_value"]
    ts_start = row.get(ts_start_key, "")
    if not ts_start or ts_start == str(gap_value):
        errors.append("TIMESTAMP_START is missing or gap-filled")
    fc = row.get(fc_key)
    if fc is not None and fc != gap_value:
        try:
            fc_val = float(fc)
            if abs(fc_val) > 100:
                errors.append(f"FC value {fc_val} exceeds plausible range [-100, 100] umol m-2 s-1")
        except (ValueError, TypeError):
            errors.append(f"FC is not numeric: {fc}")
    qc = row.get(qc_key)
    if qc is not None and qc != gap_value:
        try:
            qc_val = int(qc)
            if qc_val not in (0, 1, 2):
                errors.append(f"FC_QC value {qc_val} not in valid range 0-2")
        except (ValueError, TypeError):
            errors.append(f"FC_QC is not integer: {qc}")
    doy = row.get(doy_key)
    if doy is not None and doy != gap_value:
        try:
            doy_val = int(doy)
            if doy_val < 1 or doy_val > 366:
                errors.append(f"DOY value {doy_val} not in valid range 1-366")
        except (ValueError, TypeError):
            errors.append(f"DOY is not integer: {doy}")
    return errors
