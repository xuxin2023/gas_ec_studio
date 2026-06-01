from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import struct
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.acquisition.runtime_install import (
    build_installable_runtime_profile,
    build_runtime_deployment_artifact,
    build_runtime_deployment_feedback_artifact,
    has_runtime_deployment_feedback_config,
    has_runtime_install_config,
)
from core.comparison.eddypro_coverage_audit import build_eddypro_coverage_audit
from core.comparison.eddypro_release_gate import build_eddypro_release_gate
from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
from core.comparison.fixture_pack import (
    build_fixture_pack_summary,
    build_official_raw_fixture_detail,
    build_official_raw_fixture_manifest,
    build_public_eddypro_fixture_catalog,
)
from core.comparison.partial_capability_closure import build_eddypro_partial_capability_closure
from core.comparison.public_ec_data_discovery import build_public_ec_acquisition_closure
from core.comparison.public_ec_data_discovery import build_public_ec_acquisition_runbook
from core.comparison.raw_to_final_parity import run_raw_to_final_parity_harness
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
    ("ambient_override_status", "biomet", "real"),
    ("ambient_override_source", "biomet", "real"),
    ("biomet_ambient_status", "biomet", "real"),
    ("biomet_ambient_applied_fields", "biomet", "real"),
    ("biomet_ambient_source_mode", "biomet", "real"),
    ("biomet_ambient_source_path", "biomet", "real"),
    ("biomet_ambient_aggregation_method", "biomet", "real"),
    ("biomet_ambient_values", "biomet", "real"),
    ("biomet_ambient_provenance", "biomet", "real"),
    ("biomet_ambient_limitations", "biomet", "real"),
    ("configured_ambient_status", "biomet", "real"),
    ("configured_ambient_applied_fields", "biomet", "real"),
    ("configured_ambient_source_mode", "biomet", "real"),
    ("configured_ambient_values", "biomet", "real"),
    ("configured_ambient_provenance", "biomet", "real"),
    ("configured_ambient_limitations", "biomet", "real"),
    ("primary_flux", "flux", "real"),
    ("primary_flux_source", "flux", "real"),
    ("water_vapor_flux", "flux", "real"),
    ("sensible_heat_flux_w_m2", "energy", "real"),
    ("latent_heat_flux_w_m2", "energy", "real"),
    ("evapotranspiration_rate_mm_h", "energy", "real"),
    ("evapotranspiration_window_mm", "energy", "real"),
    ("momentum_flux_kg_m_s2", "energy", "real"),
    ("momentum_flux_tau_pa", "energy", "real"),
    ("air_density_kg_m3", "energy", "real"),
    ("latent_heat_vaporization_j_kg", "energy", "real"),
    ("energy_flux_detail", "energy", "real"),
    ("flux_correction_ledger_status", "flux", "real"),
    ("flux_correction_stage_count", "flux", "real"),
    ("flux_correction_ledger", "flux", "real"),
    ("sonic_correction_status", "preprocessing", "real"),
    ("sonic_correction_method", "preprocessing", "real"),
    ("sonic_correction_steps", "preprocessing", "real"),
    ("sonic_correction_provenance", "preprocessing", "real"),
    ("sonic_correction_detail", "preprocessing", "real"),
    ("sonic_angle_of_attack_status", "preprocessing", "real"),
    ("sonic_angle_of_attack_method", "preprocessing", "real"),
    ("sonic_angle_of_attack_summary", "preprocessing", "real"),
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
    ("clock_sync_quality_status", "acquisition", "real"),
    ("clock_sync_quality_gate_status", "acquisition", "real"),
    ("clock_sync_quality_metric_s", "acquisition", "real"),
    ("clock_sync_quality_threshold_s", "acquisition", "real"),
    ("clock_sync_max_event_step_s", "acquisition", "real"),
    ("clock_sync_offset_span_s", "acquisition", "real"),
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
    ("target_host_validation_status", "acquisition", "real"),
    ("target_host_validation_gate_status", "acquisition", "real"),
    ("target_host_validation_fixture_id", "acquisition", "real"),
    ("target_host_validation_target_host_id", "acquisition", "real"),
    ("target_host_validation_detail", "acquisition", "real"),
    ("supervisor_state", "acquisition", "real"),
    ("ptp_lock_status", "acquisition", "real"),
    ("gps_pps_lock_status", "acquisition", "real"),
    ("clock_discipline_status", "acquisition", "real"),
    ("clock_discipline_offset_ns", "acquisition", "real"),
    ("clock_discipline_frequency_ppm", "acquisition", "real"),
    ("hardware_watchdog_status", "acquisition", "real"),
    ("os_supervisor_status", "acquisition", "real"),
    ("os_supervisor_state", "acquisition", "real"),
    ("watchdog_provider_status", "acquisition", "real"),
    ("watchdog_provider_type", "acquisition", "real"),
    ("watchdog_kick_delivered", "acquisition", "real"),
    ("watchdog_reboot_recorded", "acquisition", "real"),
    ("installable_runtime_status", "acquisition", "real"),
    ("installable_runtime_profile_id", "acquisition", "real"),
    ("installable_runtime_targets", "acquisition", "real"),
    ("runtime_deployment_status", "acquisition", "real"),
    ("runtime_deployment_execution_mode", "acquisition", "real"),
    ("runtime_deployment_feedback_status", "acquisition", "real"),
    ("runtime_deployment_feedback_detail", "acquisition", "real"),
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
    ("li7700_diagnostics_status", "trace_gas", "real"),
    ("li7700_rssi_mean_pct", "trace_gas", "real"),
    ("li7700_rssi_min_pct", "trace_gas", "real"),
    ("li7700_signal_strength_mean_pct", "trace_gas", "real"),
    ("li7700_mirror_dirty_fraction", "trace_gas", "real"),
    ("li7700_diagnostic_fault_count", "trace_gas", "real"),
    ("li7700_diagnostic_flags", "trace_gas", "real"),
    ("li7700_status_diagnostics", "trace_gas", "real"),
    ("li7700_wms_fit_quality_status", "trace_gas", "real"),
    ("li7700_wms_selected_fit_model", "trace_gas", "real"),
    ("li7700_wms_fit_normalized_rmse", "trace_gas", "real"),
    ("li7700_wms_area_source", "trace_gas", "real"),
    ("li7700_wms_fit_diagnostics", "trace_gas", "real"),
    ("ch4_provenance", "trace_gas", "real"),
    ("ch4_limitations", "trace_gas", "real"),
    ("ch4_detail", "trace_gas", "real"),
    ("trace_gas_family", "trace_gas", "real"),
    ("requested_rotation_mode", "rotation", "real"),
    ("applied_rotation_impl", "rotation", "real"),
    ("planar_fit_library_status", "rotation", "real"),
    ("planar_fit_library_source", "rotation", "real"),
    ("planar_fit_library_path", "rotation", "real"),
    ("planar_fit_library_save_status", "rotation", "real"),
    ("planar_fit_library_saved_path", "rotation", "real"),
    ("planar_fit_library_id", "rotation", "real"),
    ("planar_fit_sector_count", "rotation", "real"),
    ("planar_fit_valid_sector_count", "rotation", "real"),
    ("planar_fit_selected_sector", "rotation", "real"),
    ("planar_fit_selected_sector_window_count", "rotation", "real"),
    ("planar_fit_selected_sector_r_squared", "rotation", "real"),
    ("planar_fit_wind_direction_deg", "rotation", "real"),
    ("planar_fit_library_detail", "rotation", "real"),
    ("lag_fallback_reason", "lag", "real"),
    ("screening_summary", "diagnostics", "real"),
    ("qc_details", "diagnostics", "real"),
    ("metadata_summary", "diagnostics", "real"),
    ("wpl_water_vapor_term", "flux", "real"),
    ("wpl_sensible_heat_term", "flux", "real"),
    ("wpl_sensible_heat_source", "flux", "real"),
    ("cell_thermodynamics_status", "flux", "real"),
    ("cell_thermodynamics_source", "flux", "real"),
    ("cell_pressure_valid_ratio", "flux", "real"),
    ("cell_temp_valid_ratio", "flux", "real"),
    ("cell_mean_pressure_kpa", "flux", "real"),
    ("cell_mean_temp_c", "flux", "real"),
    ("cov_w_cell_pressure_kpa", "flux", "real"),
    ("cov_w_cell_temp_c", "flux", "real"),
    ("closed_path_cell_temperature_term", "flux", "real"),
    ("closed_path_cell_pressure_term", "flux", "real"),
    ("closed_path_density_term", "flux", "real"),
    ("closed_path_density_correction_applied", "flux", "real"),
    ("closed_path_cell_detail", "flux", "real"),
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
    ("footprint_z_m", "footprint", "real"),
    ("footprint_z_m_source", "footprint", "real"),
    ("footprint_canopy_height_m", "footprint", "real"),
    ("footprint_canopy_height_source", "footprint", "real"),
    ("dynamic_canopy_height_m", "footprint", "real"),
    ("dynamic_metadata_status", "metadata", "real"),
    ("dynamic_metadata_source_path", "metadata", "real"),
    ("dynamic_metadata_source_row", "metadata", "real"),
    ("dynamic_metadata_detail", "metadata", "real"),
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
        external_artifacts: dict[str, Any] | None = None,
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
        spectral_assessment_path, spectral_assessment_companion_files = self.export_spectral_assessment_artifact(
            spectral_result=spectral_result,
            export_root=export_root,
        )
        spectral_assessment_summary = self._read_json_if_available(spectral_assessment_path)
        spectral_library_path, spectral_library_companion_files = self.export_spectral_assessment_library_artifact(
            spectral_runs=[spectral_result] if spectral_result is not None else [],
            export_root=export_root,
            dataset_id=f"{spectral_result.run_id}_library" if spectral_result is not None else "",
        )
        spectral_library_summary = self._read_json_if_available(spectral_library_path)
        benchmark_rollup = self._benchmark_rollup(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        method_summary = self._method_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        trace_gas_summary = self._trace_gas_summary(rp_result=rp_result)
        li7700_wms_fit_acceptance_path = self.export_li7700_wms_fit_acceptance_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        li7700_wms_fit_acceptance = self._read_json_if_available(li7700_wms_fit_acceptance_path)
        method_rollup_path = self.export_method_rollup_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        planar_fit_library_path = self.export_planar_fit_library_artifact(
            rp_result=rp_result,
            export_root=export_root,
        )
        planar_fit_library_summary = self._planar_fit_library_summary(rp_result=rp_result)
        footprint_2d_path = self.export_footprint_2d_artifact(
            rp_result=rp_result,
            export_root=export_root,
        )
        footprint_geojson_path = self.export_footprint_geojson_artifact(
            rp_result=rp_result,
            site=site,
            export_root=export_root,
        )
        footprint_geotiff_path = self.export_footprint_geotiff_artifact(
            rp_result=rp_result,
            site=site,
            export_root=export_root,
        )
        footprint_land_cover_overlay_path = self.export_footprint_land_cover_overlay_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            site=site,
            export_root=export_root,
        )
        footprint_gis_validation_path = self.export_footprint_gis_validation_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            site=site,
            export_root=export_root,
            footprint_geojson_path=footprint_geojson_path,
            footprint_geotiff_path=footprint_geotiff_path,
            footprint_land_cover_overlay_path=footprint_land_cover_overlay_path,
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
        runtime_feedback_path = self.export_runtime_deployment_feedback_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        clock_sync_path = self.export_clock_sync_artifact(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
        )
        flux_correction_ledger_path = self.export_flux_correction_ledger_artifact(
            rp_result=rp_result,
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
        benchmark_config_snapshot = dict(rp_config_snapshot.get("benchmark", {}) or {})
        official_raw_benchmark = {
            "fixture_id": str(benchmark_config_snapshot.get("official_raw_fixture_id", "")),
            "parity_status": str(benchmark_config_snapshot.get("official_raw_parity_status", "")),
            "pass_rate": float(benchmark_config_snapshot.get("official_raw_pass_rate", 0.0) or 0.0),
            "failed_fields": list(benchmark_config_snapshot.get("official_raw_failed_fields", []) or []),
            "parity_artifact": str(benchmark_config_snapshot.get("official_raw_parity_artifact", "")),
            "fixture_detail_artifact": str(benchmark_config_snapshot.get("official_raw_fixture_detail_artifact", "")),
            "fixture_pack_path": str(benchmark_config_snapshot.get("official_raw_fixture_pack_path", "")),
            "batch_status": str(benchmark_config_snapshot.get("official_raw_batch_status", "")),
            "batch_registered_count": int(benchmark_config_snapshot.get("official_raw_batch_registered_count", 0) or 0),
            "batch_pass_count": int(benchmark_config_snapshot.get("official_raw_batch_pass_count", 0) or 0),
            "batch_failed_fields": list(benchmark_config_snapshot.get("official_raw_batch_failed_fields", []) or []),
            "batch_parity_artifact": str(benchmark_config_snapshot.get("official_raw_batch_parity_artifact", "")),
            "trace_gas_parity_status": str(benchmark_config_snapshot.get("official_raw_trace_gas_parity_status", "")),
            "trace_gas_pass_rate": float(benchmark_config_snapshot.get("official_raw_trace_gas_pass_rate", 0.0) or 0.0),
            "trace_gas_failed_fields": list(benchmark_config_snapshot.get("official_raw_trace_gas_failed_fields", []) or []),
            "trace_gas_coefficient_profile_id": str(benchmark_config_snapshot.get("official_raw_trace_gas_coefficient_profile_id", "")),
            "batch_trace_gas_pass_count": int(benchmark_config_snapshot.get("official_raw_batch_trace_gas_pass_count", 0) or 0),
            "batch_trace_gas_failed_count": int(benchmark_config_snapshot.get("official_raw_batch_trace_gas_failed_count", 0) or 0),
            "batch_trace_gas_failed_fields": list(benchmark_config_snapshot.get("official_raw_batch_trace_gas_failed_fields", []) or []),
        }
        fixture_pack_path = str(rp_config_snapshot.get("fixture_pack_path", "") or "").strip()
        fixture_pack_workspace_root = str(rp_config_snapshot.get("fixture_pack_workspace_root", "") or "").strip()
        fixture_pack_summary = build_fixture_pack_summary(
            fixture_pack_path or None,
            workspace_root=fixture_pack_workspace_root or None,
        )
        fixture_pack_summary_path = export_root / "fixture_pack_summary.json"
        self._write_json(fixture_pack_summary_path, fixture_pack_summary)
        public_eddypro_fixture_catalog = dict(
            fixture_pack_summary.get("public_eddypro_fixture_catalog", {})
            or build_public_eddypro_fixture_catalog(workspace_root=fixture_pack_workspace_root or None)
        )
        public_eddypro_fixture_catalog_path = export_root / "public_eddypro_fixture_catalog.json"
        self._write_json(public_eddypro_fixture_catalog_path, public_eddypro_fixture_catalog)
        official_raw_fixture_manifest = build_official_raw_fixture_manifest(
            fixture_pack_path or None,
            workspace_root=fixture_pack_workspace_root or None,
            fixture_summary=fixture_pack_summary,
        )
        official_raw_fixture_manifest_path = export_root / "official_raw_fixture_manifest.json"
        self._write_json(official_raw_fixture_manifest_path, official_raw_fixture_manifest)
        official_raw_bundle_config = dict(rp_config_snapshot.get("official_raw_bundle", {}) or {})
        official_raw_closure_run = dict(official_raw_bundle_config.get("closure_run", {}) or {})
        if official_raw_closure_run:
            official_raw_closure_run.setdefault("source_artifact", str(official_raw_bundle_config.get("closure_run_artifact", "")))
        else:
            official_raw_closure_run = {
                "artifact_type": "official_raw_closure_run_v1",
                "status": "not_available",
                "gate_status": "blocked",
                "steps": [],
                "blockers": ["official_raw_closure_run"],
                "truthfulness_note": "No Report Center official raw closure run was available for this export.",
            }
        official_raw_closure_run_path = export_root / "official_raw_closure_run.json"
        self._write_json(official_raw_closure_run_path, official_raw_closure_run)
        official_raw_repair_plan = dict(official_raw_bundle_config.get("repair_plan", {}) or {})
        if official_raw_repair_plan:
            official_raw_repair_plan.setdefault("source_artifact", str(official_raw_bundle_config.get("repair_plan_artifact", "")))
        else:
            official_raw_repair_plan = {
                "artifact_type": "official_raw_fixture_repair_plan_v1",
                "status": "not_available",
                "bundle_count": 0,
                "ready_for_registration_count": 0,
                "repair_item_count": 0,
                "official_eddypro_run_pass_count": 0,
                "official_eddypro_run_blocked_count": 0,
                "missing_requirement_counts": {},
                "accepted_sidecar_filenames": [
                    "official_eddypro_run.json",
                    "eddypro_run.json",
                    "eddypro_executable_run.json",
                    "run_provenance.json",
                ],
                "repair_items": [],
                "ready_items": [],
                "truthfulness_note": "No Report Center official raw bundle tree repair plan was available for this export.",
            }
        official_raw_repair_plan_path = export_root / "official_raw_repair_plan.json"
        self._write_json(official_raw_repair_plan_path, official_raw_repair_plan)
        selected_official_raw_fixture_id = (
            str(benchmark_config_snapshot.get("official_raw_fixture_id", "") or "").strip()
            or str(official_raw_bundle_config.get("selected_fixture_id", "") or "").strip()
        )
        official_raw_fixture_detail = build_official_raw_fixture_detail(
            fixture_pack_path or None,
            fixture_id=selected_official_raw_fixture_id,
            workspace_root=fixture_pack_workspace_root or None,
            fixture_summary=fixture_pack_summary,
            fixture_manifest=official_raw_fixture_manifest,
        )
        official_raw_fixture_detail_path = export_root / "official_raw_fixture_detail.json"
        self._write_json(official_raw_fixture_detail_path, official_raw_fixture_detail)
        official_raw_normalization = dict(official_raw_fixture_detail.get("normalization", {}) or {})
        official_raw_acquisition_validation = dict(official_raw_fixture_detail.get("acquisition_validation", {}) or {})
        official_raw_evidence_pack_source = str(official_raw_bundle_config.get("evidence_pack_artifact", "") or "").strip()
        official_raw_evidence_pack = self._read_json_if_available(Path(official_raw_evidence_pack_source)) if official_raw_evidence_pack_source else {}
        if not official_raw_evidence_pack:
            official_raw_evidence_pack = {
                "artifact_type": "official_raw_fixture_evidence_pack_v1",
                "status": "not_available",
                "fixture_id": str(official_raw_fixture_detail.get("fixture_id", "")),
                "acquisition_validation": official_raw_acquisition_validation,
                "fixture_detail_summary": {
                    "readiness_level": str(official_raw_fixture_detail.get("readiness_level", "")),
                    "site_class": str(official_raw_fixture_detail.get("site_class", "")),
                    "software": str(official_raw_fixture_detail.get("software", "")),
                },
                "truthfulness_note": "No report-center official raw evidence pack artifact was available for this export.",
                "acceptance_status": "not_run",
                "acceptance_gate_status": "not_run",
                "acceptance_run": {},
                "official_eddypro_run": {
                    "artifact_type": "official_eddypro_executable_run_v1",
                    "status": "not_available",
                    "gate_status": "blocked",
                    "missing_requirements": ["official_eddypro_run"],
                    "truthfulness_note": "No official EddyPro executable-run provenance was available for this export.",
                },
            }
        official_eddypro_run = dict(official_raw_evidence_pack.get("official_eddypro_run", {}) or {})
        official_eddypro_run_status = str(official_eddypro_run.get("status", "not_available") or "not_available")
        official_eddypro_run_gate_status = str(official_eddypro_run.get("gate_status", "blocked") or "blocked")
        official_raw_acceptance_run = dict(official_raw_evidence_pack.get("acceptance_run", {}) or {})
        official_raw_acceptance_status = str(
            official_raw_evidence_pack.get("acceptance_status", official_raw_acceptance_run.get("status", "not_run"))
            or "not_run"
        )
        official_raw_acceptance_gate_status = str(
            official_raw_evidence_pack.get("acceptance_gate_status", official_raw_acceptance_run.get("gate_status", "not_run"))
            or "not_run"
        )
        official_raw_official_run_normalization = dict(official_raw_fixture_detail.get("official_run_normalization", {}) or {})
        manifest_official_run_normalization = next(
            (
                dict(asset.get("official_run_normalization", {}) or {})
                for asset in list(official_raw_fixture_manifest.get("assets", []) or [])
                if str(dict(asset.get("official_run_normalization", {}) or {}).get("status", "") or "not_available")
                not in {"", "not_available"}
            ),
            {},
        )
        evidence_official_run_normalization = dict(official_raw_evidence_pack.get("official_run_normalization", {}) or {})
        if str(official_raw_official_run_normalization.get("status", "") or "not_available") in {"", "not_available"}:
            official_raw_official_run_normalization = manifest_official_run_normalization or evidence_official_run_normalization
        official_raw_evidence_pack_path = export_root / "official_raw_evidence_pack.json"
        self._write_json(official_raw_evidence_pack_path, official_raw_evidence_pack)
        eddypro_source_inventory = build_eddypro_source_inventory()
        eddypro_source_inventory_path = export_root / "eddypro_source_inventory.json"
        self._write_json(eddypro_source_inventory_path, eddypro_source_inventory)
        coverage_official_raw_evidence_pack = (
            official_raw_evidence_pack if official_raw_acceptance_gate_status == "pass" else None
        )
        eddypro_coverage_audit = build_eddypro_coverage_audit(
            fixture_pack_path=fixture_pack_path or None,
            workspace_root=fixture_pack_workspace_root or None,
            fixture_summary=fixture_pack_summary,
            official_raw_manifest=official_raw_fixture_manifest,
            official_raw_evidence_pack=coverage_official_raw_evidence_pack,
            source_inventory=eddypro_source_inventory,
        )
        eddypro_closure_gate = dict(eddypro_coverage_audit.get("closure_gate", {}) or {})
        eddypro_closure_plan = dict(eddypro_coverage_audit.get("closure_plan", {}) or {})
        eddypro_surrogate_evidence_closure = dict(eddypro_coverage_audit.get("surrogate_evidence_closure", {}) or {})
        eddypro_coverage_audit_path = export_root / "eddypro_coverage_audit.json"
        self._write_json(eddypro_coverage_audit_path, eddypro_coverage_audit)
        eddypro_surrogate_evidence_closure_path = export_root / "eddypro_surrogate_evidence_closure.json"
        self._write_json(eddypro_surrogate_evidence_closure_path, eddypro_surrogate_evidence_closure)
        eddypro_release_gate = build_eddypro_release_gate(
            fixture_pack_path=fixture_pack_path or None,
            workspace_root=fixture_pack_workspace_root or None,
            official_raw_evidence_pack=official_raw_evidence_pack,
            fixture_summary=fixture_pack_summary,
            official_raw_manifest=official_raw_fixture_manifest,
            source_inventory=eddypro_source_inventory,
            coverage_audit=eddypro_coverage_audit,
            run_acceptance=False,
        )
        eddypro_release_gate.setdefault("artifacts", {}).update(
            {
                "official_raw_evidence_pack": str(official_raw_evidence_pack_path),
                "eddypro_coverage_audit": str(eddypro_coverage_audit_path),
                "surrogate_evidence_closure": str(eddypro_surrogate_evidence_closure_path),
            }
        )
        eddypro_release_gate_path = export_root / "eddypro_release_gate.json"
        self._write_json(eddypro_release_gate_path, eddypro_release_gate)
        synthetic_parity_path = self.export_synthetic_eddypro_parity_artifact(
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
            report_key=report_key,
        )
        synthetic_parity_summary = self._read_json_if_available(synthetic_parity_path)
        raw_to_final_parity_path = self.export_raw_to_final_parity_artifact(
            rp_config_snapshot=rp_config_snapshot,
            export_root=export_root,
            report_key=report_key,
        )
        raw_to_final_parity_summary = self._read_json_if_available(raw_to_final_parity_path)
        raw_to_final_trace_gas_parity = dict(raw_to_final_parity_summary.get("trace_gas_parity", {}) or {})
        raw_to_final_parity_diagnostics = dict(raw_to_final_parity_summary.get("parity_diagnostics", {}) or {})
        raw_to_final_parity_failure_groups = [
            str(item.get("category", ""))
            for item in list(raw_to_final_parity_diagnostics.get("failure_groups", []) or [])
            if str(item.get("category", ""))
        ]
        raw_to_final_parity_top_failed_fields = list(raw_to_final_parity_diagnostics.get("top_failed_fields", []) or [])
        configured_external_artifacts = dict(rp_config_snapshot.get("external_artifacts", {}) or {})
        configured_external_artifacts.update(dict(external_artifacts or {}))
        external_artifact_files, external_artifact_payloads = self._copy_external_artifacts(
            configured_external_artifacts,
            export_root=export_root,
        )
        neon_hdf5_validation_package = dict(external_artifact_payloads.get("neon_hdf5_validation_package_artifact", {}) or {})
        public_raw_sample_validation_package = dict(
            external_artifact_payloads.get("public_raw_sample_validation_package_artifact", {}) or {}
        )
        public_ec_acquisition_closure = dict(
            external_artifact_payloads.get("public_ec_acquisition_closure_artifact", {}) or {}
        )
        if not public_ec_acquisition_closure:
            public_ec_acquisition_closure = build_public_ec_acquisition_closure(
                discovery_probe_path=external_artifact_files.get("public_ec_discovery_probe_artifact") or None,
                smoke_plan_path=external_artifact_files.get("public_raw_importer_smoke_plan_artifact") or None,
                workspace_root=fixture_pack_workspace_root or None,
                neon_download_path=external_artifact_files.get("neon_hdf5_download_artifact") or None,
                neon_validation_package_path=external_artifact_files.get("neon_hdf5_validation_package_artifact") or None,
                public_raw_sample_validation_package_path=external_artifact_files.get(
                    "public_raw_sample_validation_package_artifact"
                )
                or None,
            )
        public_ec_acquisition_closure_path = export_root / "public_ec_acquisition_closure.json"
        self._write_json(public_ec_acquisition_closure_path, public_ec_acquisition_closure)
        external_artifact_files["public_ec_acquisition_closure_artifact"] = str(public_ec_acquisition_closure_path)
        public_ec_acquisition_runbook = dict(
            external_artifact_payloads.get("public_ec_acquisition_runbook_artifact", {}) or {}
        )
        if not public_ec_acquisition_runbook:
            public_ec_acquisition_runbook = build_public_ec_acquisition_runbook(
                acquisition_closure=public_ec_acquisition_closure,
                discovery_probe_path=external_artifact_files.get("public_ec_discovery_probe_artifact") or None,
                smoke_plan_path=external_artifact_files.get("public_raw_importer_smoke_plan_artifact") or None,
                workspace_root=fixture_pack_workspace_root or None,
            )
        public_ec_acquisition_runbook_path = export_root / "public_ec_acquisition_runbook.json"
        self._write_json(public_ec_acquisition_runbook_path, public_ec_acquisition_runbook)
        external_artifact_files["public_ec_acquisition_runbook_artifact"] = str(public_ec_acquisition_runbook_path)
        public_ec_acquisition_summary = dict(public_ec_acquisition_closure.get("summary", {}) or {})
        public_ec_acquisition_claim_boundary = dict(public_ec_acquisition_closure.get("claim_boundary", {}) or {})
        eddypro_partial_capability_closure = build_eddypro_partial_capability_closure(
            workspace_root=fixture_pack_workspace_root or None,
            coverage_audit=eddypro_coverage_audit,
            release_gate=eddypro_release_gate,
            neon_validation_package=neon_hdf5_validation_package or None,
            public_raw_sample_validation_package=public_raw_sample_validation_package or None,
        )
        eddypro_partial_capability_closure_path = export_root / "eddypro_partial_capability_closure.json"
        self._write_json(eddypro_partial_capability_closure_path, eddypro_partial_capability_closure)

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
        if planar_fit_library_path is not None:
            exported_files.append(planar_fit_library_path.name)
        if li7700_wms_fit_acceptance_path is not None:
            exported_files.append(li7700_wms_fit_acceptance_path.name)
        if spectral_assessment_path is not None:
            exported_files.append(spectral_assessment_path.name)
            for companion in spectral_assessment_companion_files.values():
                if companion:
                    exported_files.append(Path(companion).name)
        if spectral_library_path is not None:
            exported_files.append(spectral_library_path.name)
            for companion in spectral_library_companion_files.values():
                if companion:
                    exported_files.append(Path(companion).name)
        if footprint_2d_path is not None:
            exported_files.append(footprint_2d_path.name)
        if footprint_geojson_path is not None:
            exported_files.append(footprint_geojson_path.name)
        if footprint_geotiff_path is not None:
            exported_files.append(footprint_geotiff_path.name)
        if footprint_land_cover_overlay_path is not None:
            exported_files.append(footprint_land_cover_overlay_path.name)
        if footprint_gis_validation_path is not None:
            exported_files.append(footprint_gis_validation_path.name)
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
        if runtime_feedback_path is not None:
            exported_files.append(runtime_feedback_path.name)
        if clock_sync_path is not None:
            exported_files.append(clock_sync_path.name)
        if flux_correction_ledger_path is not None:
            exported_files.append(flux_correction_ledger_path.name)
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
        exported_files.append(fixture_pack_summary_path.name)
        exported_files.append(public_eddypro_fixture_catalog_path.name)
        exported_files.append(official_raw_fixture_manifest_path.name)
        exported_files.append(official_raw_closure_run_path.name)
        exported_files.append(official_raw_repair_plan_path.name)
        exported_files.append(official_raw_fixture_detail_path.name)
        exported_files.append(official_raw_evidence_pack_path.name)
        exported_files.append(eddypro_source_inventory_path.name)
        exported_files.append(eddypro_coverage_audit_path.name)
        exported_files.append(eddypro_surrogate_evidence_closure_path.name)
        exported_files.append(eddypro_release_gate_path.name)
        exported_files.append(eddypro_partial_capability_closure_path.name)
        exported_files.append(public_ec_acquisition_closure_path.name)
        exported_files.append(public_ec_acquisition_runbook_path.name)
        if synthetic_parity_path is not None:
            exported_files.append(synthetic_parity_path.name)
        if raw_to_final_parity_path is not None:
            exported_files.append(raw_to_final_parity_path.name)
        for path in network_files.values():
            exported_files.append(Path(path).name)
        for path in external_artifact_files.values():
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
                "li7700_wms_fit_acceptance": li7700_wms_fit_acceptance,
                "li7700_wms_fit_acceptance_artifact": str(li7700_wms_fit_acceptance_path) if li7700_wms_fit_acceptance_path is not None else "",
                "spectral_assessment": spectral_assessment_summary,
                "spectral_assessment_artifact": str(spectral_assessment_path) if spectral_assessment_path is not None else "",
                "spectral_assessment_files": spectral_assessment_companion_files,
                "spectral_assessment_library": spectral_library_summary,
                "spectral_assessment_library_artifact": str(spectral_library_path) if spectral_library_path is not None else "",
                "spectral_assessment_library_files": spectral_library_companion_files,
                "method_rollup_artifact": str(method_rollup_path) if method_rollup_path is not None else "",
                "footprint_2d_artifact": str(footprint_2d_path) if footprint_2d_path is not None else "",
                "footprint_geojson_artifact": str(footprint_geojson_path) if footprint_geojson_path is not None else "",
                "footprint_geotiff_artifact": str(footprint_geotiff_path) if footprint_geotiff_path is not None else "",
                "footprint_land_cover_overlay_artifact": str(footprint_land_cover_overlay_path) if footprint_land_cover_overlay_path is not None else "",
                "footprint_gis_validation_artifact": str(footprint_gis_validation_path) if footprint_gis_validation_path is not None else "",
                "footprint_gis_validation": self._read_json_if_available(footprint_gis_validation_path),
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
                "runtime_deployment_feedback_artifact": str(runtime_feedback_path) if runtime_feedback_path is not None else "",
                "runtime_deployment_feedback_summary": self._runtime_deployment_feedback_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "clock_sync_artifact": str(clock_sync_path) if clock_sync_path is not None else "",
                "clock_sync_summary": self._clock_sync_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
                "flux_correction_ledger_artifact": str(flux_correction_ledger_path) if flux_correction_ledger_path is not None else "",
                "flux_correction_ledger_summary": self._flux_correction_ledger_summary(rp_result=rp_result),
                "reference_provenance": reference_provenance,
                "fixture_pack_path": fixture_pack_path,
                "fixture_pack_summary": fixture_pack_summary,
                "fixture_pack_summary_artifact": str(fixture_pack_summary_path),
                "public_eddypro_fixture_catalog": public_eddypro_fixture_catalog,
                "public_eddypro_fixture_catalog_artifact": str(public_eddypro_fixture_catalog_path),
                "public_eddypro_fixture_catalog_status": str(public_eddypro_fixture_catalog.get("status", "")),
                "public_eddypro_fixture_count": int(public_eddypro_fixture_catalog.get("fixture_count", 0) or 0),
                "public_eddypro_valid_fixture_count": int(public_eddypro_fixture_catalog.get("valid_fixture_count", 0) or 0),
                "official_raw_fixture_manifest": official_raw_fixture_manifest,
                "official_raw_fixture_manifest_artifact": str(official_raw_fixture_manifest_path),
                "official_raw_closure_run": official_raw_closure_run,
                "official_raw_closure_run_artifact": str(official_raw_closure_run_path),
                "official_raw_closure_run_status": str(official_raw_closure_run.get("status", "")),
                "official_raw_closure_run_gate_status": str(official_raw_closure_run.get("gate_status", "")),
                "official_raw_closure_run_blockers": list(official_raw_closure_run.get("blockers", []) or []),
                "official_raw_repair_plan": official_raw_repair_plan,
                "official_raw_repair_plan_artifact": str(official_raw_repair_plan_path),
                "official_raw_repair_plan_status": str(official_raw_repair_plan.get("status", "")),
                "official_raw_repair_item_count": int(official_raw_repair_plan.get("repair_item_count", 0) or 0),
                "official_raw_repair_missing_requirement_counts": dict(official_raw_repair_plan.get("missing_requirement_counts", {}) or {}),
                "official_raw_fixture_detail": official_raw_fixture_detail,
                "official_raw_fixture_detail_artifact": str(official_raw_fixture_detail_path),
                "official_raw_acquisition_validation": official_raw_acquisition_validation,
                "official_raw_acquisition_status": str(official_raw_acquisition_validation.get("status", "")),
                "official_raw_acquisition_gate_status": str(official_raw_acquisition_validation.get("gate_status", "")),
                "official_raw_acquisition_missing_requirements": list(official_raw_acquisition_validation.get("missing_requirements", []) or []),
                "official_raw_evidence_pack": official_raw_evidence_pack,
                "official_raw_evidence_pack_artifact": str(official_raw_evidence_pack_path),
                "official_raw_evidence_pack_status": str(official_raw_evidence_pack.get("status", "")),
                "official_raw_evidence_pack_acceptance_status": official_raw_acceptance_status,
                "official_raw_evidence_pack_acceptance_gate_status": official_raw_acceptance_gate_status,
                "official_raw_evidence_pack_acceptance_command_count": int(official_raw_acceptance_run.get("command_count", 0) or 0),
                "official_raw_evidence_pack_acceptance_passed_count": int(official_raw_acceptance_run.get("passed_count", 0) or 0),
                "official_raw_evidence_pack_acceptance_failed_count": int(official_raw_acceptance_run.get("failed_count", 0) or 0),
                "official_eddypro_run": official_eddypro_run,
                "official_eddypro_run_status": official_eddypro_run_status,
                "official_eddypro_run_gate_status": official_eddypro_run_gate_status,
                "official_eddypro_software_version": str(official_eddypro_run.get("software_version", "")),
                "official_eddypro_run_command": str(official_eddypro_run.get("command", "")),
                "official_raw_normalization": official_raw_normalization,
                "official_raw_normalization_status": str(official_raw_normalization.get("status", "")),
                "official_raw_normalization_time": str(official_raw_normalization.get("normalization_time", "")),
                "official_raw_qc_mapping_strategy": str(official_raw_normalization.get("qc_mapping_strategy", "")),
                "official_raw_official_run_normalization": official_raw_official_run_normalization,
                "official_raw_official_run_normalization_status": str(official_raw_official_run_normalization.get("status", "")),
                "official_raw_official_run_normalization_time": str(official_raw_official_run_normalization.get("normalization_time", "")),
                "official_raw_official_run_reference_json": str(official_raw_official_run_normalization.get("reference_json", "")),
                "official_raw_official_run_provenance_json": str(official_raw_official_run_normalization.get("provenance_json", "")),
                "official_raw_official_run_qc_mapping_strategy": str(official_raw_official_run_normalization.get("qc_mapping_strategy", "")),
                "official_raw_benchmark": official_raw_benchmark,
                "eddypro_source_inventory": eddypro_source_inventory,
                "eddypro_source_inventory_artifact": str(eddypro_source_inventory_path),
                "eddypro_coverage_audit": eddypro_coverage_audit,
                "eddypro_coverage_audit_artifact": str(eddypro_coverage_audit_path),
                "eddypro_surrogate_evidence_closure": eddypro_surrogate_evidence_closure,
                "eddypro_surrogate_evidence_closure_artifact": str(eddypro_surrogate_evidence_closure_path),
                "eddypro_surrogate_evidence_closure_status": str(eddypro_surrogate_evidence_closure.get("status", "")),
                "can_claim_source_derived_functional_parity": bool(
                    eddypro_coverage_audit.get("can_claim_source_derived_functional_parity", False)
                ),
                "eddypro_release_gate": eddypro_release_gate,
                "eddypro_release_gate_artifact": str(eddypro_release_gate_path),
                "eddypro_release_gate_status": str(eddypro_release_gate.get("status", "")),
                "can_release_full_eddypro_parity": bool(eddypro_release_gate.get("can_release_full_eddypro_parity", False)),
                "can_release_source_derived_functional_parity": bool(
                    eddypro_release_gate.get("can_release_source_derived_functional_parity", False)
                ),
                "eddypro_partial_capability_closure": eddypro_partial_capability_closure,
                "eddypro_partial_capability_closure_artifact": str(eddypro_partial_capability_closure_path),
                "eddypro_partial_capability_closure_status": str(eddypro_partial_capability_closure.get("status", "")),
                "eddypro_partial_capability_count": int(
                    eddypro_partial_capability_closure.get("partial_capability_count", 0) or 0
                ),
                "eddypro_ready_public_raw_candidate_count": int(
                    dict(eddypro_partial_capability_closure.get("public_search_closure", {}) or {}).get(
                        "ready_to_register_public_raw_candidate_count",
                        0,
                    )
                    or 0
                ),
                "eddypro_closure_gate": eddypro_closure_gate,
                "eddypro_closure_plan": eddypro_closure_plan,
                "eddypro_closure_gate_status": str(eddypro_closure_gate.get("status", "")),
                "eddypro_closure_open_item_count": int(eddypro_closure_gate.get("open_item_count", 0) or 0),
                "eddypro_closure_top_priority": str(eddypro_closure_gate.get("top_priority", "")),
                "synthetic_eddypro_parity": synthetic_parity_summary,
                "synthetic_eddypro_parity_artifact": str(synthetic_parity_path) if synthetic_parity_path is not None else "",
                "raw_to_final_parity": raw_to_final_parity_summary,
                "raw_to_final_parity_diagnostics": raw_to_final_parity_diagnostics,
                "raw_to_final_parity_failure_groups": raw_to_final_parity_failure_groups,
                "raw_to_final_parity_top_failed_fields": raw_to_final_parity_top_failed_fields,
                "raw_to_final_trace_gas_parity": raw_to_final_trace_gas_parity,
                "raw_to_final_trace_gas_status": str(raw_to_final_trace_gas_parity.get("status", "")),
                "raw_to_final_trace_gas_pass_rate": float(raw_to_final_trace_gas_parity.get("pass_rate", 0.0) or 0.0),
                "raw_to_final_trace_gas_failed_fields": list(raw_to_final_trace_gas_parity.get("failed_fields", []) or []),
                "raw_to_final_trace_gas_coefficient_profile_id": str(raw_to_final_trace_gas_parity.get("coefficient_profile_id", "")),
                "raw_to_final_parity_artifact": str(raw_to_final_parity_path) if raw_to_final_parity_path is not None else "",
                "external_artifacts": external_artifact_files,
                "neon_hdf5_validation_package": neon_hdf5_validation_package,
                "neon_hdf5_validation_package_artifact": external_artifact_files.get("neon_hdf5_validation_package_artifact", ""),
                "public_raw_sample_validation_package": public_raw_sample_validation_package,
                "public_raw_sample_validation_package_artifact": external_artifact_files.get(
                    "public_raw_sample_validation_package_artifact",
                    "",
                ),
                "public_ec_acquisition_closure": public_ec_acquisition_closure,
                "public_ec_acquisition_closure_artifact": str(public_ec_acquisition_closure_path),
                "public_ec_acquisition_runbook": public_ec_acquisition_runbook,
                "public_ec_acquisition_runbook_artifact": str(public_ec_acquisition_runbook_path),
                "public_ec_acquisition_runbook_status": str(public_ec_acquisition_runbook.get("status", "")),
                "public_ec_acquisition_closure_status": str(public_ec_acquisition_closure.get("status", "")),
                "public_ec_acquisition_candidate_count": int(public_ec_acquisition_summary.get("candidate_count", 0) or 0),
                "public_ec_acquisition_engineering_validation_pass_count": int(
                    public_ec_acquisition_summary.get("engineering_validation_pass_count", 0) or 0
                ),
                "public_ec_acquisition_ready_to_register_candidate_count": int(
                    public_ec_acquisition_summary.get("ready_to_register_candidate_count", 0) or 0
                ),
                "public_ec_acquisition_can_claim_engineering_validation": bool(
                    public_ec_acquisition_claim_boundary.get("can_claim_public_raw_engineering_validation", False)
                ),
                "public_ec_acquisition_can_claim_eddypro_raw_to_final_parity": bool(
                    public_ec_acquisition_claim_boundary.get("can_claim_eddypro_raw_to_final_parity", False)
                ),
                "public_ec_acquisition_can_release_full_eddypro_parity": bool(
                    public_ec_acquisition_claim_boundary.get("can_release_full_eddypro_parity", False)
                ),
                "network_validation": network_validation,
                "network_supported_schema_targets": list(NETWORK_SCHEMA_REGISTRY.keys()),
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
            "planar_fit_library": planar_fit_library_summary,
            "planar_fit_library_artifact": str(planar_fit_library_path) if planar_fit_library_path is not None else "",
            "planar_fit_library_status": planar_fit_library_summary.get("status", ""),
            "planar_fit_library_source": planar_fit_library_summary.get("source", ""),
            "planar_fit_library_path": planar_fit_library_summary.get("coefficient_library_path", ""),
            "planar_fit_valid_sector_count": int(planar_fit_library_summary.get("valid_sector_count", 0) or 0),
            "fixture_pack_path": fixture_pack_path,
            "fixture_pack_summary": fixture_pack_summary,
            "fixture_pack_summary_artifact": str(fixture_pack_summary_path),
            "public_eddypro_fixture_catalog": public_eddypro_fixture_catalog,
            "public_eddypro_fixture_catalog_artifact": str(public_eddypro_fixture_catalog_path),
            "public_eddypro_fixture_catalog_status": str(public_eddypro_fixture_catalog.get("status", "")),
            "public_eddypro_fixture_count": int(public_eddypro_fixture_catalog.get("fixture_count", 0) or 0),
            "public_eddypro_valid_fixture_count": int(public_eddypro_fixture_catalog.get("valid_fixture_count", 0) or 0),
            "official_raw_fixture_manifest": official_raw_fixture_manifest,
            "official_raw_fixture_manifest_artifact": str(official_raw_fixture_manifest_path),
            "official_raw_closure_run": official_raw_closure_run,
            "official_raw_closure_run_artifact": str(official_raw_closure_run_path),
            "official_raw_closure_run_status": str(official_raw_closure_run.get("status", "")),
            "official_raw_closure_run_gate_status": str(official_raw_closure_run.get("gate_status", "")),
            "official_raw_closure_run_blockers": list(official_raw_closure_run.get("blockers", []) or []),
            "official_raw_repair_plan": official_raw_repair_plan,
            "official_raw_repair_plan_artifact": str(official_raw_repair_plan_path),
            "official_raw_repair_plan_status": str(official_raw_repair_plan.get("status", "")),
            "official_raw_repair_item_count": int(official_raw_repair_plan.get("repair_item_count", 0) or 0),
            "official_raw_repair_missing_requirement_counts": dict(official_raw_repair_plan.get("missing_requirement_counts", {}) or {}),
            "official_raw_fixture_detail": official_raw_fixture_detail,
            "official_raw_fixture_detail_artifact": str(official_raw_fixture_detail_path),
            "official_raw_acquisition_validation": official_raw_acquisition_validation,
            "official_raw_acquisition_status": str(official_raw_acquisition_validation.get("status", "")),
            "official_raw_acquisition_gate_status": str(official_raw_acquisition_validation.get("gate_status", "")),
            "official_raw_acquisition_missing_requirements": list(official_raw_acquisition_validation.get("missing_requirements", []) or []),
            "official_raw_evidence_pack": official_raw_evidence_pack,
            "official_raw_evidence_pack_artifact": str(official_raw_evidence_pack_path),
            "official_raw_evidence_pack_status": str(official_raw_evidence_pack.get("status", "")),
            "official_raw_evidence_pack_acceptance_status": official_raw_acceptance_status,
            "official_raw_evidence_pack_acceptance_gate_status": official_raw_acceptance_gate_status,
            "official_raw_evidence_pack_acceptance_command_count": int(official_raw_acceptance_run.get("command_count", 0) or 0),
            "official_raw_evidence_pack_acceptance_passed_count": int(official_raw_acceptance_run.get("passed_count", 0) or 0),
            "official_raw_evidence_pack_acceptance_failed_count": int(official_raw_acceptance_run.get("failed_count", 0) or 0),
            "official_eddypro_run": official_eddypro_run,
            "official_eddypro_run_status": official_eddypro_run_status,
            "official_eddypro_run_gate_status": official_eddypro_run_gate_status,
            "official_eddypro_software_version": str(official_eddypro_run.get("software_version", "")),
            "official_eddypro_run_command": str(official_eddypro_run.get("command", "")),
            "official_raw_normalization": official_raw_normalization,
            "official_raw_normalization_status": str(official_raw_normalization.get("status", "")),
            "official_raw_normalization_time": str(official_raw_normalization.get("normalization_time", "")),
            "official_raw_qc_mapping_strategy": str(official_raw_normalization.get("qc_mapping_strategy", "")),
            "official_raw_official_run_normalization": official_raw_official_run_normalization,
            "official_raw_official_run_normalization_status": str(official_raw_official_run_normalization.get("status", "")),
            "official_raw_official_run_normalization_time": str(official_raw_official_run_normalization.get("normalization_time", "")),
            "official_raw_official_run_reference_json": str(official_raw_official_run_normalization.get("reference_json", "")),
            "official_raw_official_run_provenance_json": str(official_raw_official_run_normalization.get("provenance_json", "")),
            "official_raw_official_run_qc_mapping_strategy": str(official_raw_official_run_normalization.get("qc_mapping_strategy", "")),
            "official_raw_benchmark": official_raw_benchmark,
            "eddypro_source_inventory": eddypro_source_inventory,
            "eddypro_source_inventory_artifact": str(eddypro_source_inventory_path),
            "eddypro_coverage_audit": eddypro_coverage_audit,
            "eddypro_coverage_audit_artifact": str(eddypro_coverage_audit_path),
            "eddypro_surrogate_evidence_closure": eddypro_surrogate_evidence_closure,
            "eddypro_surrogate_evidence_closure_artifact": str(eddypro_surrogate_evidence_closure_path),
            "eddypro_surrogate_evidence_closure_status": str(eddypro_surrogate_evidence_closure.get("status", "")),
            "can_claim_source_derived_functional_parity": bool(
                eddypro_coverage_audit.get("can_claim_source_derived_functional_parity", False)
            ),
            "eddypro_release_gate": eddypro_release_gate,
            "eddypro_release_gate_artifact": str(eddypro_release_gate_path),
            "eddypro_release_gate_status": str(eddypro_release_gate.get("status", "")),
            "can_release_full_eddypro_parity": bool(eddypro_release_gate.get("can_release_full_eddypro_parity", False)),
            "can_release_source_derived_functional_parity": bool(
                eddypro_release_gate.get("can_release_source_derived_functional_parity", False)
            ),
            "eddypro_partial_capability_closure": eddypro_partial_capability_closure,
            "eddypro_partial_capability_closure_artifact": str(eddypro_partial_capability_closure_path),
            "eddypro_partial_capability_closure_status": str(eddypro_partial_capability_closure.get("status", "")),
            "eddypro_partial_capability_count": int(
                eddypro_partial_capability_closure.get("partial_capability_count", 0) or 0
            ),
            "eddypro_ready_public_raw_candidate_count": int(
                dict(eddypro_partial_capability_closure.get("public_search_closure", {}) or {}).get(
                    "ready_to_register_public_raw_candidate_count",
                    0,
                )
                or 0
            ),
            "eddypro_closure_gate": eddypro_closure_gate,
            "eddypro_closure_plan": eddypro_closure_plan,
            "eddypro_closure_gate_status": str(eddypro_closure_gate.get("status", "")),
            "eddypro_closure_open_item_count": int(eddypro_closure_gate.get("open_item_count", 0) or 0),
            "eddypro_closure_top_priority": str(eddypro_closure_gate.get("top_priority", "")),
            "synthetic_eddypro_parity": synthetic_parity_summary,
            "synthetic_eddypro_parity_artifact": str(synthetic_parity_path) if synthetic_parity_path is not None else "",
            "raw_to_final_parity": raw_to_final_parity_summary,
            "raw_to_final_parity_diagnostics": raw_to_final_parity_diagnostics,
            "raw_to_final_parity_failure_groups": raw_to_final_parity_failure_groups,
            "raw_to_final_parity_top_failed_fields": raw_to_final_parity_top_failed_fields,
            "raw_to_final_trace_gas_parity": raw_to_final_trace_gas_parity,
            "raw_to_final_trace_gas_status": str(raw_to_final_trace_gas_parity.get("status", "")),
            "raw_to_final_trace_gas_pass_rate": float(raw_to_final_trace_gas_parity.get("pass_rate", 0.0) or 0.0),
            "raw_to_final_trace_gas_failed_fields": list(raw_to_final_trace_gas_parity.get("failed_fields", []) or []),
            "raw_to_final_trace_gas_coefficient_profile_id": str(raw_to_final_trace_gas_parity.get("coefficient_profile_id", "")),
            "raw_to_final_parity_artifact": str(raw_to_final_parity_path) if raw_to_final_parity_path is not None else "",
            "external_artifacts": external_artifact_files,
            "neon_hdf5_validation_package": neon_hdf5_validation_package,
            "neon_hdf5_validation_package_artifact": external_artifact_files.get("neon_hdf5_validation_package_artifact", ""),
            "neon_hdf5_validation_status": str(neon_hdf5_validation_package.get("status", "")),
            "neon_hdf5_row_status": str(neon_hdf5_validation_package.get("row_status", "")),
            "neon_hdf5_rp_status": str(neon_hdf5_validation_package.get("rp_status", "")),
            "public_raw_sample_validation_package": public_raw_sample_validation_package,
            "public_raw_sample_validation_package_artifact": external_artifact_files.get(
                "public_raw_sample_validation_package_artifact",
                "",
            ),
            "public_raw_sample_validation_status": str(public_raw_sample_validation_package.get("status", "")),
            "public_raw_sample_importer_status": str(public_raw_sample_validation_package.get("importer_status", "")),
            "public_raw_sample_rp_status": str(public_raw_sample_validation_package.get("rp_status", "")),
            "public_raw_sample_row_count": int(public_raw_sample_validation_package.get("row_count", 0) or 0),
            "public_raw_sample_rp_window_count": int(
                public_raw_sample_validation_package.get("rp_window_count", 0) or 0
            ),
            "public_raw_sample_can_claim_engineering_validation": bool(
                dict(public_raw_sample_validation_package.get("claim_boundary", {}) or {}).get(
                    "can_claim_public_raw_engineering_validation",
                    False,
                )
            ),
            "public_raw_sample_can_claim_eddypro_raw_to_final_parity": bool(
                dict(public_raw_sample_validation_package.get("claim_boundary", {}) or {}).get(
                    "can_claim_eddypro_raw_to_final_parity",
                    False,
                )
            ),
            "public_ec_acquisition_closure": public_ec_acquisition_closure,
            "public_ec_acquisition_closure_artifact": str(public_ec_acquisition_closure_path),
            "public_ec_acquisition_runbook": public_ec_acquisition_runbook,
            "public_ec_acquisition_runbook_artifact": str(public_ec_acquisition_runbook_path),
            "public_ec_acquisition_runbook_status": str(public_ec_acquisition_runbook.get("status", "")),
            "public_ec_acquisition_closure_status": str(public_ec_acquisition_closure.get("status", "")),
            "public_ec_acquisition_candidate_count": int(public_ec_acquisition_summary.get("candidate_count", 0) or 0),
            "public_ec_acquisition_engineering_validation_pass_count": int(
                public_ec_acquisition_summary.get("engineering_validation_pass_count", 0) or 0
            ),
            "public_ec_acquisition_ready_to_register_candidate_count": int(
                public_ec_acquisition_summary.get("ready_to_register_candidate_count", 0) or 0
            ),
            "public_ec_acquisition_can_claim_engineering_validation": bool(
                public_ec_acquisition_claim_boundary.get("can_claim_public_raw_engineering_validation", False)
            ),
            "public_ec_acquisition_can_claim_eddypro_raw_to_final_parity": bool(
                public_ec_acquisition_claim_boundary.get("can_claim_eddypro_raw_to_final_parity", False)
            ),
            "public_ec_acquisition_can_release_full_eddypro_parity": bool(
                public_ec_acquisition_claim_boundary.get("can_release_full_eddypro_parity", False)
            ),
            "spectral_assessment": spectral_assessment_summary,
            "spectral_assessment_artifact": str(spectral_assessment_path) if spectral_assessment_path is not None else "",
            "spectral_assessment_files": spectral_assessment_companion_files,
            "spectral_assessment_library": spectral_library_summary,
            "spectral_assessment_library_artifact": str(spectral_library_path) if spectral_library_path is not None else "",
            "spectral_assessment_library_files": spectral_library_companion_files,
            "continuous_dataset_enabled": bool(rp_config_snapshot.get("continuous_dataset", {}).get("enabled", False)),
            "density_correction_mode": rp_config_snapshot.get("density_correction_mode", "wpl"),
            "rotation_mode": rp_config_snapshot.get("rotation_mode", "double"),
            "detrend_mode": rp_config_snapshot.get("detrend_mode", "block_mean"),
            "lag_strategy": rp_config_snapshot.get("lag_phase", {}).get("strategy", ""),
            "biomet_ambient_summary": self._biomet_ambient_summary(rp_result=rp_result),
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
            "planar_fit_library": planar_fit_library_summary,
            "planar_fit_library_artifact": str(planar_fit_library_path) if planar_fit_library_path is not None else "",
            "planar_fit_library_status": planar_fit_library_summary.get("status", ""),
            "planar_fit_library_source": planar_fit_library_summary.get("source", ""),
            "planar_fit_library_path": planar_fit_library_summary.get("coefficient_library_path", ""),
            "planar_fit_valid_sector_count": int(planar_fit_library_summary.get("valid_sector_count", 0) or 0),
            "trace_gas_summary": trace_gas_summary,
            "li7700_wms_fit_acceptance": li7700_wms_fit_acceptance,
            "li7700_wms_fit_acceptance_artifact": str(li7700_wms_fit_acceptance_path) if li7700_wms_fit_acceptance_path is not None else "",
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
                "li7700_diagnostics_status",
                "li7700_rssi_mean_pct",
                "li7700_rssi_min_pct",
                "li7700_signal_strength_mean_pct",
                "li7700_mirror_dirty_fraction",
                "li7700_diagnostic_fault_count",
                "li7700_diagnostic_flags",
                "li7700_status_diagnostics",
                "li7700_wms_fit_quality_status",
                "li7700_wms_selected_fit_model",
                "li7700_wms_fit_normalized_rmse",
                "li7700_wms_area_source",
                "li7700_wms_fit_diagnostics",
                "ch4_provenance",
                "ch4_limitations",
            ],
            "method_rollup_artifact": str(method_rollup_path) if method_rollup_path is not None else "",
            "footprint_2d_summary": method_summary.get("footprint_2d_summary", {}),
            "footprint_2d_artifact": str(footprint_2d_path) if footprint_2d_path is not None else "",
            "footprint_2d_contour_svg": str(footprint_2d_companion_files.get("contour_svg", "")),
            "footprint_2d_grid_csv": str(footprint_2d_companion_files.get("grid_csv", "")),
            "footprint_geojson_artifact": str(footprint_geojson_path) if footprint_geojson_path is not None else "",
            "footprint_geotiff_artifact": str(footprint_geotiff_path) if footprint_geotiff_path is not None else "",
            "footprint_land_cover_overlay_artifact": str(footprint_land_cover_overlay_path) if footprint_land_cover_overlay_path is not None else "",
            "footprint_gis_validation": self._read_json_if_available(footprint_gis_validation_path),
            "footprint_gis_validation_artifact": str(footprint_gis_validation_path) if footprint_gis_validation_path is not None else "",
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
            "runtime_deployment_feedback_summary": self._runtime_deployment_feedback_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "runtime_deployment_feedback_artifact": str(runtime_feedback_path) if runtime_feedback_path is not None else "",
            "clock_sync_summary": self._clock_sync_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot),
            "clock_sync_artifact": str(clock_sync_path) if clock_sync_path is not None else "",
            "flux_correction_ledger_summary": self._flux_correction_ledger_summary(rp_result=rp_result),
            "flux_correction_ledger_artifact": str(flux_correction_ledger_path) if flux_correction_ledger_path is not None else "",
            "schema_target": network_validation.get("schema_target", ""),
            "network_supported_schema_targets": list(NETWORK_SCHEMA_REGISTRY.keys()),
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
                "CLOCK_SYNC_QUALITY_STATUS",
                "CLOCK_SYNC_QUALITY_GATE_STATUS",
                "CLOCK_SYNC_QUALITY_METRIC_S",
                "CLOCK_SYNC_QUALITY_THRESHOLD_S",
                "CLOCK_SYNC_MAX_EVENT_STEP_S",
                "RUNTIME_WATCHDOG_STATUS",
                "RUNTIME_WATCHDOG_PROFILE",
                "RUNTIME_WATCHDOG_FAIL_COUNT",
                "RUNTIME_SERVICE_STATUS",
                "RUNTIME_SERVICE_DELIVERY_STATE",
                "RUNTIME_SERVICE_QUARANTINE_COUNT",
                "DAEMON_TELEMETRY_STATUS",
                "TARGET_HOST_VALIDATION_STATUS",
                "TARGET_HOST_VALIDATION_GATE_STATUS",
                "TARGET_HOST_VALIDATION_FIXTURE_ID",
                "TARGET_HOST_ID",
                "SUPERVISOR_STATE",
                "PTP_LOCK_STATUS",
                "GPS_PPS_LOCK_STATUS",
                "CLOCK_DISCIPLINE_STATUS",
                "CLOCK_DISCIPLINE_OFFSET_NS",
                "CLOCK_DISCIPLINE_FREQUENCY_PPM",
                "HARDWARE_WATCHDOG_STATUS",
                "OS_SUPERVISOR_STATUS",
                "OS_SUPERVISOR_STATE",
                "WATCHDOG_PROVIDER_STATUS",
                "WATCHDOG_PROVIDER_TYPE",
                "WATCHDOG_KICK_DELIVERED",
                "WATCHDOG_REBOOT_RECORDED",
                "INSTALLABLE_RUNTIME_STATUS",
                "INSTALLABLE_RUNTIME_TARGETS",
                "RUNTIME_DEPLOYMENT_STATUS",
                "RUNTIME_DEPLOYMENT_FEEDBACK_STATUS",
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
            "network_energy_fields": [
                "H",
                "LE",
                "ET",
                "TAU",
            ],
            "method_provenance_fields": [
                "primary_flux_source",
                "applied_rotation_impl",
                "requested_rotation_mode",
                "planar_fit_library_status",
                "planar_fit_library_source",
                "planar_fit_library_path",
                "planar_fit_selected_sector",
                "planar_fit_selected_sector_r_squared",
                "lag_strategy",
                "lag_fallback_reason",
                "density_correction_mode",
                "density_correction_reason",
                "ambient_override_status",
                "ambient_override_source",
                "biomet_ambient_status",
                "biomet_ambient_applied_fields",
                "biomet_ambient_source_mode",
                "biomet_ambient_source_path",
                "biomet_ambient_aggregation_method",
                "biomet_ambient_provenance",
                "configured_ambient_status",
                "configured_ambient_applied_fields",
                "configured_ambient_source_mode",
                "configured_ambient_provenance",
                "flux_correction_ledger_status",
                "flux_correction_stage_count",
                "sonic_correction_method",
                "sonic_correction_status",
                "sonic_correction_provenance",
                "sonic_angle_of_attack_method",
                "sonic_angle_of_attack_status",
                "crosswind_correction_method",
                "crosswind_correction_status",
                "crosswind_correction_provenance",
                "clock_sync_status",
                "clock_sync_method",
                "clock_sync_source",
                "clock_sync_mean_offset_s",
                "clock_sync_quality_status",
                "clock_sync_quality_gate_status",
                "clock_sync_quality_metric_s",
                "clock_sync_quality_threshold_s",
                "clock_sync_max_event_step_s",
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
                "clock_discipline_status",
                "clock_discipline_offset_ns",
                "clock_discipline_frequency_ppm",
                "hardware_watchdog_status",
                "os_supervisor_status",
                "os_supervisor_state",
                "watchdog_provider_status",
                "watchdog_provider_type",
                "watchdog_kick_delivered",
                "watchdog_reboot_recorded",
                "installable_runtime_status",
                "installable_runtime_profile_id",
                "installable_runtime_targets",
                "runtime_deployment_status",
                "runtime_deployment_execution_mode",
                "runtime_deployment_feedback_status",
                "screening_config",
                "screening_summary",
                "planar_fit_library_status",
                "planar_fit_library_source",
                "planar_fit_library_path",
                "planar_fit_selected_sector",
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
        if planar_fit_library_path is not None:
            files["planar_fit_library_artifact"] = str(planar_fit_library_path)
        if li7700_wms_fit_acceptance_path is not None:
            files["li7700_wms_fit_acceptance_artifact"] = str(li7700_wms_fit_acceptance_path)
        if spectral_assessment_path is not None:
            files["spectral_assessment_artifact"] = str(spectral_assessment_path)
            files.update(spectral_assessment_companion_files)
        if spectral_library_path is not None:
            files["spectral_assessment_library_artifact"] = str(spectral_library_path)
            files.update(spectral_library_companion_files)
        if footprint_2d_path is not None:
            files["footprint_2d_artifact"] = str(footprint_2d_path)
        if footprint_geojson_path is not None:
            files["footprint_geojson_artifact"] = str(footprint_geojson_path)
        if footprint_geotiff_path is not None:
            files["footprint_geotiff_artifact"] = str(footprint_geotiff_path)
        if footprint_land_cover_overlay_path is not None:
            files["footprint_land_cover_overlay_artifact"] = str(footprint_land_cover_overlay_path)
        if footprint_gis_validation_path is not None:
            files["footprint_gis_validation_artifact"] = str(footprint_gis_validation_path)
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
        if runtime_feedback_path is not None:
            files["runtime_deployment_feedback_artifact"] = str(runtime_feedback_path)
        if clock_sync_path is not None:
            files["clock_sync_artifact"] = str(clock_sync_path)
        if flux_correction_ledger_path is not None:
            files["flux_correction_ledger_artifact"] = str(flux_correction_ledger_path)
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
        files["fixture_pack_summary_artifact"] = str(fixture_pack_summary_path)
        files["public_eddypro_fixture_catalog_artifact"] = str(public_eddypro_fixture_catalog_path)
        files["official_raw_fixture_manifest_artifact"] = str(official_raw_fixture_manifest_path)
        files["official_raw_closure_run_artifact"] = str(official_raw_closure_run_path)
        files["official_raw_repair_plan_artifact"] = str(official_raw_repair_plan_path)
        files["official_raw_fixture_detail_artifact"] = str(official_raw_fixture_detail_path)
        files["official_raw_evidence_pack_artifact"] = str(official_raw_evidence_pack_path)
        files["eddypro_source_inventory_artifact"] = str(eddypro_source_inventory_path)
        files["eddypro_coverage_audit_artifact"] = str(eddypro_coverage_audit_path)
        files["eddypro_surrogate_evidence_closure_artifact"] = str(eddypro_surrogate_evidence_closure_path)
        files["eddypro_release_gate_artifact"] = str(eddypro_release_gate_path)
        files["eddypro_partial_capability_closure_artifact"] = str(eddypro_partial_capability_closure_path)
        files["public_ec_acquisition_closure_artifact"] = str(public_ec_acquisition_closure_path)
        files["public_ec_acquisition_runbook_artifact"] = str(public_ec_acquisition_runbook_path)
        if synthetic_parity_path is not None:
            files["synthetic_eddypro_parity_artifact"] = str(synthetic_parity_path)
        if raw_to_final_parity_path is not None:
            files["raw_to_final_parity_artifact"] = str(raw_to_final_parity_path)
        files.update(network_files)
        files.update(external_artifact_files)
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
            "flux_correction_ledger_status": diagnostics.get("flux_correction_ledger", {}).get("status", "") if isinstance(diagnostics.get("flux_correction_ledger"), dict) else "",
            "flux_correction_stage_count": diagnostics.get("flux_correction_ledger", {}).get("stage_count", "") if isinstance(diagnostics.get("flux_correction_ledger"), dict) else "",
            "flux_correction_ledger": json.dumps(diagnostics.get("flux_correction_ledger", {}), ensure_ascii=False) if diagnostics.get("flux_correction_ledger") else "",
            "wpl_sensible_heat_source": diagnostics.get("wpl_sensible_heat_source", ""),
            "cell_thermodynamics_status": diagnostics.get("cell_thermodynamics_status", ""),
            "cell_thermodynamics_source": diagnostics.get("cell_thermodynamics_source", ""),
            "cell_pressure_valid_ratio": diagnostics.get("cell_pressure_valid_ratio", ""),
            "cell_temp_valid_ratio": diagnostics.get("cell_temp_valid_ratio", ""),
            "cell_mean_pressure_kpa": diagnostics.get("cell_mean_pressure_kpa", ""),
            "cell_mean_temp_c": diagnostics.get("cell_mean_temp_c", ""),
            "cov_w_cell_pressure_kpa": diagnostics.get("cov_w_cell_pressure_kpa", ""),
            "cov_w_cell_temp_c": diagnostics.get("cov_w_cell_temp_c", ""),
            "closed_path_cell_temperature_term": diagnostics.get("closed_path_cell_temperature_term", ""),
            "closed_path_cell_pressure_term": diagnostics.get("closed_path_cell_pressure_term", ""),
            "closed_path_density_term": diagnostics.get("closed_path_density_term", ""),
            "closed_path_density_correction_applied": diagnostics.get("closed_path_density_correction_applied", ""),
            "closed_path_cell_detail": json.dumps(diagnostics.get("closed_path_cell_detail", {}), ensure_ascii=False)
            if diagnostics.get("closed_path_cell_detail")
            else "",
            "ambient_override_status": diagnostics.get("ambient_override_status", ""),
            "ambient_override_source": diagnostics.get("ambient_override_source", ""),
            "biomet_ambient_status": diagnostics.get("biomet_ambient_status", ""),
            "biomet_ambient_applied_fields": "|".join(diagnostics.get("biomet_ambient_applied_fields", []) or [])
            if isinstance(diagnostics.get("biomet_ambient_applied_fields"), list)
            else diagnostics.get("biomet_ambient_applied_fields", ""),
            "biomet_ambient_source_mode": diagnostics.get("biomet_ambient_source_mode", ""),
            "biomet_ambient_source_path": diagnostics.get("biomet_ambient_source_path", ""),
            "biomet_ambient_aggregation_method": diagnostics.get("biomet_ambient_aggregation_method", ""),
            "biomet_ambient_values": json.dumps(diagnostics.get("biomet_ambient_values", {}), ensure_ascii=False) if diagnostics.get("biomet_ambient_values") else "",
            "biomet_ambient_provenance": diagnostics.get("biomet_ambient_provenance", ""),
            "biomet_ambient_limitations": json.dumps(diagnostics.get("biomet_ambient_limitations", []), ensure_ascii=False) if diagnostics.get("biomet_ambient_limitations") else "",
            "configured_ambient_status": diagnostics.get("configured_ambient_status", ""),
            "configured_ambient_applied_fields": "|".join(diagnostics.get("configured_ambient_applied_fields", []) or [])
            if isinstance(diagnostics.get("configured_ambient_applied_fields"), list)
            else diagnostics.get("configured_ambient_applied_fields", ""),
            "configured_ambient_source_mode": diagnostics.get("configured_ambient_source_mode", ""),
            "configured_ambient_values": json.dumps(diagnostics.get("configured_ambient_values", {}), ensure_ascii=False) if diagnostics.get("configured_ambient_values") else "",
            "configured_ambient_provenance": diagnostics.get("configured_ambient_provenance", ""),
            "configured_ambient_limitations": json.dumps(diagnostics.get("configured_ambient_limitations", []), ensure_ascii=False) if diagnostics.get("configured_ambient_limitations") else "",
            "water_vapor_flux": window.water_vapor_flux,
            "sensible_heat_flux_w_m2": diagnostics.get("sensible_heat_flux_w_m2", ""),
            "latent_heat_flux_w_m2": diagnostics.get("latent_heat_flux_w_m2", ""),
            "evapotranspiration_rate_mm_h": diagnostics.get("evapotranspiration_rate_mm_h", ""),
            "evapotranspiration_window_mm": diagnostics.get("evapotranspiration_window_mm", ""),
            "momentum_flux_kg_m_s2": diagnostics.get("momentum_flux_kg_m_s2", ""),
            "momentum_flux_tau_pa": diagnostics.get("momentum_flux_tau_pa", ""),
            "air_density_kg_m3": diagnostics.get("air_density_kg_m3", ""),
            "latent_heat_vaporization_j_kg": diagnostics.get("latent_heat_vaporization_j_kg", ""),
            "energy_flux_detail": json.dumps(diagnostics.get("energy_flux_detail", {}), ensure_ascii=False) if diagnostics.get("energy_flux_detail") else "",
            "sonic_correction_status": diagnostics.get("sonic_correction_status", ""),
            "sonic_correction_method": diagnostics.get("sonic_correction_method", ""),
            "sonic_correction_steps": json.dumps(diagnostics.get("sonic_correction_steps", []), ensure_ascii=False) if diagnostics.get("sonic_correction_steps") else "",
            "sonic_correction_provenance": diagnostics.get("sonic_correction_provenance", ""),
            "sonic_angle_of_attack_status": diagnostics.get("sonic_angle_of_attack_status", ""),
            "sonic_angle_of_attack_method": diagnostics.get("sonic_angle_of_attack_method", ""),
            "sonic_angle_of_attack_summary": json.dumps(diagnostics.get("sonic_angle_of_attack_summary", {}), ensure_ascii=False)
            if diagnostics.get("sonic_angle_of_attack_summary")
            else "",
            "crosswind_correction_status": diagnostics.get("crosswind_correction_status", ""),
            "crosswind_correction_method": diagnostics.get("crosswind_correction_method", ""),
            "crosswind_correction_mean_delta_c": diagnostics.get("crosswind_correction_mean_delta_c", ""),
            "crosswind_correction_max_abs_delta_c": diagnostics.get("crosswind_correction_max_abs_delta_c", ""),
            "crosswind_correction_provenance": diagnostics.get("crosswind_correction_provenance", ""),
            "clock_sync_status": diagnostics.get("clock_sync_status", ""),
            "clock_sync_method": diagnostics.get("clock_sync_method", ""),
            "clock_sync_source": diagnostics.get("clock_sync_source", ""),
            "clock_sync_mean_offset_s": diagnostics.get("clock_sync_mean_offset_s", ""),
            "clock_sync_quality_status": diagnostics.get("clock_sync_quality_status", ""),
            "clock_sync_quality_gate_status": diagnostics.get("clock_sync_quality_gate_status", ""),
            "clock_sync_quality_metric_s": diagnostics.get("clock_sync_quality_metric_s", ""),
            "clock_sync_quality_threshold_s": diagnostics.get("clock_sync_quality_threshold_s", ""),
            "clock_sync_max_event_step_s": diagnostics.get("clock_sync_max_event_step_s", ""),
            "clock_sync_offset_span_s": diagnostics.get("clock_sync_offset_span_s", ""),
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
            "target_host_validation_status": diagnostics.get("target_host_validation_status", ""),
            "target_host_validation_gate_status": diagnostics.get("target_host_validation_gate_status", ""),
            "target_host_validation_fixture_id": diagnostics.get("target_host_validation_fixture_id", ""),
            "target_host_validation_target_host_id": diagnostics.get("target_host_validation_target_host_id", ""),
            "target_host_validation_detail": json.dumps(diagnostics.get("target_host_validation_detail", {}), ensure_ascii=False) if diagnostics.get("target_host_validation_detail") else "",
            "supervisor_state": diagnostics.get("supervisor_state", ""),
            "ptp_lock_status": diagnostics.get("ptp_lock_status", ""),
            "gps_pps_lock_status": diagnostics.get("gps_pps_lock_status", ""),
            "clock_discipline_status": diagnostics.get("clock_discipline_status", ""),
            "clock_discipline_offset_ns": diagnostics.get("clock_discipline_offset_ns", ""),
            "clock_discipline_frequency_ppm": diagnostics.get("clock_discipline_frequency_ppm", ""),
            "hardware_watchdog_status": diagnostics.get("hardware_watchdog_status", ""),
            "os_supervisor_status": diagnostics.get("os_supervisor_status", ""),
            "os_supervisor_state": diagnostics.get("os_supervisor_state", ""),
            "watchdog_provider_status": diagnostics.get("watchdog_provider_status", ""),
            "watchdog_provider_type": diagnostics.get("watchdog_provider_type", ""),
            "watchdog_kick_delivered": diagnostics.get("watchdog_kick_delivered", ""),
            "watchdog_reboot_recorded": diagnostics.get("watchdog_reboot_recorded", ""),
            "installable_runtime_status": diagnostics.get("installable_runtime_status", ""),
            "installable_runtime_profile_id": diagnostics.get("installable_runtime_profile_id", ""),
            "installable_runtime_targets": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
            if isinstance(diagnostics.get("installable_runtime_targets"), list)
            else diagnostics.get("installable_runtime_targets", ""),
            "runtime_deployment_status": diagnostics.get("runtime_deployment_status", ""),
            "runtime_deployment_execution_mode": diagnostics.get("runtime_deployment_execution_mode", ""),
            "runtime_deployment_feedback_status": diagnostics.get("runtime_deployment_feedback_status", ""),
            "runtime_deployment_feedback_detail": json.dumps(diagnostics.get("runtime_deployment_feedback_detail", {}), ensure_ascii=False) if diagnostics.get("runtime_deployment_feedback_detail") else "",
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
            "li7700_diagnostics_status": diagnostics.get("li7700_diagnostics_status", ""),
            "li7700_rssi_mean_pct": diagnostics.get("li7700_rssi_mean_pct", ""),
            "li7700_rssi_min_pct": diagnostics.get("li7700_rssi_min_pct", ""),
            "li7700_signal_strength_mean_pct": diagnostics.get("li7700_signal_strength_mean_pct", ""),
            "li7700_mirror_dirty_fraction": diagnostics.get("li7700_mirror_dirty_fraction", ""),
            "li7700_diagnostic_fault_count": diagnostics.get("li7700_diagnostic_fault_count", ""),
            "li7700_diagnostic_flags": "|".join(diagnostics.get("li7700_diagnostic_flags", []) or [])
            if isinstance(diagnostics.get("li7700_diagnostic_flags"), list)
            else diagnostics.get("li7700_diagnostic_flags", ""),
            "li7700_status_diagnostics": json.dumps(diagnostics.get("li7700_status_diagnostics", {}), ensure_ascii=False)
            if diagnostics.get("li7700_status_diagnostics")
            else "",
            "li7700_wms_fit_quality_status": diagnostics.get("li7700_wms_fit_quality_status", ""),
            "li7700_wms_selected_fit_model": diagnostics.get("li7700_wms_selected_fit_model", ""),
            "li7700_wms_fit_normalized_rmse": diagnostics.get("li7700_wms_fit_normalized_rmse", ""),
            "li7700_wms_area_source": diagnostics.get("li7700_wms_area_source", ""),
            "li7700_wms_fit_diagnostics": json.dumps(diagnostics.get("li7700_wms_fit_diagnostics", {}), ensure_ascii=False)
            if diagnostics.get("li7700_wms_fit_diagnostics")
            else "",
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
                "ambient_override_status": diagnostics.get("ambient_override_status", "") if diagnostics else "",
                "ambient_override_source": diagnostics.get("ambient_override_source", "") if diagnostics else "",
                "biomet_ambient_status": diagnostics.get("biomet_ambient_status", "") if diagnostics else "",
                "biomet_ambient_applied_fields": "|".join(diagnostics.get("biomet_ambient_applied_fields", []) or [])
                if diagnostics and isinstance(diagnostics.get("biomet_ambient_applied_fields"), list)
                else (diagnostics.get("biomet_ambient_applied_fields", "") if diagnostics else ""),
                "biomet_ambient_source_mode": diagnostics.get("biomet_ambient_source_mode", "") if diagnostics else "",
                "biomet_ambient_source_path": diagnostics.get("biomet_ambient_source_path", "") if diagnostics else "",
                "biomet_ambient_aggregation_method": diagnostics.get("biomet_ambient_aggregation_method", "") if diagnostics else "",
                "biomet_ambient_values": json.dumps(diagnostics.get("biomet_ambient_values", {}), ensure_ascii=False) if diagnostics and diagnostics.get("biomet_ambient_values") else "",
                "biomet_ambient_provenance": diagnostics.get("biomet_ambient_provenance", "") if diagnostics else "",
                "biomet_ambient_limitations": json.dumps(diagnostics.get("biomet_ambient_limitations", []), ensure_ascii=False) if diagnostics and diagnostics.get("biomet_ambient_limitations") else "",
                "configured_ambient_status": diagnostics.get("configured_ambient_status", "") if diagnostics else "",
                "configured_ambient_applied_fields": "|".join(diagnostics.get("configured_ambient_applied_fields", []) or [])
                if diagnostics and isinstance(diagnostics.get("configured_ambient_applied_fields"), list)
                else (diagnostics.get("configured_ambient_applied_fields", "") if diagnostics else ""),
                "configured_ambient_source_mode": diagnostics.get("configured_ambient_source_mode", "") if diagnostics else "",
                "configured_ambient_values": json.dumps(diagnostics.get("configured_ambient_values", {}), ensure_ascii=False) if diagnostics and diagnostics.get("configured_ambient_values") else "",
                "configured_ambient_provenance": diagnostics.get("configured_ambient_provenance", "") if diagnostics else "",
                "configured_ambient_limitations": json.dumps(diagnostics.get("configured_ambient_limitations", []), ensure_ascii=False) if diagnostics and diagnostics.get("configured_ambient_limitations") else "",
                "primary_flux": rp_window.primary_flux if rp_window else "",
                "primary_flux_source": rp_window.primary_flux_source if rp_window else "",
                "flux_correction_ledger_status": diagnostics.get("flux_correction_ledger", {}).get("status", "") if diagnostics and isinstance(diagnostics.get("flux_correction_ledger"), dict) else "",
                "flux_correction_stage_count": diagnostics.get("flux_correction_ledger", {}).get("stage_count", "") if diagnostics and isinstance(diagnostics.get("flux_correction_ledger"), dict) else "",
                "flux_correction_ledger": json.dumps(diagnostics.get("flux_correction_ledger", {}), ensure_ascii=False) if diagnostics and diagnostics.get("flux_correction_ledger") else "",
                "sonic_correction_status": diagnostics.get("sonic_correction_status", "") if diagnostics else "",
                "sonic_correction_method": diagnostics.get("sonic_correction_method", "") if diagnostics else "",
                "sonic_correction_steps": json.dumps(diagnostics.get("sonic_correction_steps", []), ensure_ascii=False) if diagnostics and diagnostics.get("sonic_correction_steps") else "",
                "sonic_correction_provenance": diagnostics.get("sonic_correction_provenance", "") if diagnostics else "",
                "sonic_correction_detail": json.dumps(diagnostics.get("sonic_correction_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("sonic_correction_detail") else "",
                "sonic_angle_of_attack_status": diagnostics.get("sonic_angle_of_attack_status", "") if diagnostics else "",
                "sonic_angle_of_attack_method": diagnostics.get("sonic_angle_of_attack_method", "") if diagnostics else "",
                "sonic_angle_of_attack_summary": json.dumps(diagnostics.get("sonic_angle_of_attack_summary", {}), ensure_ascii=False) if diagnostics and diagnostics.get("sonic_angle_of_attack_summary") else "",
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
                "clock_sync_quality_status": diagnostics.get("clock_sync_quality_status", "") if diagnostics else "",
                "clock_sync_quality_gate_status": diagnostics.get("clock_sync_quality_gate_status", "") if diagnostics else "",
                "clock_sync_quality_metric_s": diagnostics.get("clock_sync_quality_metric_s", "") if diagnostics else "",
                "clock_sync_quality_threshold_s": diagnostics.get("clock_sync_quality_threshold_s", "") if diagnostics else "",
                "clock_sync_max_event_step_s": diagnostics.get("clock_sync_max_event_step_s", "") if diagnostics else "",
                "clock_sync_offset_span_s": diagnostics.get("clock_sync_offset_span_s", "") if diagnostics else "",
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
                "target_host_validation_status": diagnostics.get("target_host_validation_status", "") if diagnostics else "",
                "target_host_validation_gate_status": diagnostics.get("target_host_validation_gate_status", "") if diagnostics else "",
                "target_host_validation_fixture_id": diagnostics.get("target_host_validation_fixture_id", "") if diagnostics else "",
                "target_host_validation_target_host_id": diagnostics.get("target_host_validation_target_host_id", "") if diagnostics else "",
                "target_host_validation_detail": json.dumps(diagnostics.get("target_host_validation_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("target_host_validation_detail") else "",
                "supervisor_state": diagnostics.get("supervisor_state", "") if diagnostics else "",
                "ptp_lock_status": diagnostics.get("ptp_lock_status", "") if diagnostics else "",
                "gps_pps_lock_status": diagnostics.get("gps_pps_lock_status", "") if diagnostics else "",
                "clock_discipline_status": diagnostics.get("clock_discipline_status", "") if diagnostics else "",
                "clock_discipline_offset_ns": diagnostics.get("clock_discipline_offset_ns", "") if diagnostics else "",
                "clock_discipline_frequency_ppm": diagnostics.get("clock_discipline_frequency_ppm", "") if diagnostics else "",
                "hardware_watchdog_status": diagnostics.get("hardware_watchdog_status", "") if diagnostics else "",
                "os_supervisor_status": diagnostics.get("os_supervisor_status", "") if diagnostics else "",
                "os_supervisor_state": diagnostics.get("os_supervisor_state", "") if diagnostics else "",
                "watchdog_provider_status": diagnostics.get("watchdog_provider_status", "") if diagnostics else "",
                "watchdog_provider_type": diagnostics.get("watchdog_provider_type", "") if diagnostics else "",
                "watchdog_kick_delivered": diagnostics.get("watchdog_kick_delivered", "") if diagnostics else "",
                "watchdog_reboot_recorded": diagnostics.get("watchdog_reboot_recorded", "") if diagnostics else "",
                "installable_runtime_status": diagnostics.get("installable_runtime_status", "") if diagnostics else "",
                "installable_runtime_profile_id": diagnostics.get("installable_runtime_profile_id", "") if diagnostics else "",
                "installable_runtime_targets": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
                if diagnostics and isinstance(diagnostics.get("installable_runtime_targets"), list)
                else (diagnostics.get("installable_runtime_targets", "") if diagnostics else ""),
                "runtime_deployment_status": diagnostics.get("runtime_deployment_status", "") if diagnostics else "",
                "runtime_deployment_execution_mode": diagnostics.get("runtime_deployment_execution_mode", "") if diagnostics else "",
                "runtime_deployment_feedback_status": diagnostics.get("runtime_deployment_feedback_status", "") if diagnostics else "",
                "runtime_deployment_feedback_detail": json.dumps(diagnostics.get("runtime_deployment_feedback_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("runtime_deployment_feedback_detail") else "",
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
                "li7700_diagnostics_status": diagnostics.get("li7700_diagnostics_status", "") if diagnostics else "",
                "li7700_rssi_mean_pct": diagnostics.get("li7700_rssi_mean_pct", "") if diagnostics else "",
                "li7700_rssi_min_pct": diagnostics.get("li7700_rssi_min_pct", "") if diagnostics else "",
                "li7700_signal_strength_mean_pct": diagnostics.get("li7700_signal_strength_mean_pct", "") if diagnostics else "",
                "li7700_mirror_dirty_fraction": diagnostics.get("li7700_mirror_dirty_fraction", "") if diagnostics else "",
                "li7700_diagnostic_fault_count": diagnostics.get("li7700_diagnostic_fault_count", "") if diagnostics else "",
                "li7700_diagnostic_flags": "|".join(diagnostics.get("li7700_diagnostic_flags", []) or [])
                if diagnostics and isinstance(diagnostics.get("li7700_diagnostic_flags"), list)
                else (diagnostics.get("li7700_diagnostic_flags", "") if diagnostics else ""),
                "li7700_status_diagnostics": json.dumps(diagnostics.get("li7700_status_diagnostics", {}), ensure_ascii=False)
                if diagnostics and diagnostics.get("li7700_status_diagnostics")
                else "",
                "li7700_wms_fit_quality_status": diagnostics.get("li7700_wms_fit_quality_status", "") if diagnostics else "",
                "li7700_wms_selected_fit_model": diagnostics.get("li7700_wms_selected_fit_model", "") if diagnostics else "",
                "li7700_wms_fit_normalized_rmse": diagnostics.get("li7700_wms_fit_normalized_rmse", "") if diagnostics else "",
                "li7700_wms_area_source": diagnostics.get("li7700_wms_area_source", "") if diagnostics else "",
                "li7700_wms_fit_diagnostics": json.dumps(diagnostics.get("li7700_wms_fit_diagnostics", {}), ensure_ascii=False)
                if diagnostics and diagnostics.get("li7700_wms_fit_diagnostics")
                else "",
                "ch4_provenance": diagnostics.get("ch4_provenance", "") if diagnostics else "",
                "ch4_limitations": json.dumps(diagnostics.get("ch4_limitations", []), ensure_ascii=False) if diagnostics and diagnostics.get("ch4_limitations") else "",
                "ch4_detail": json.dumps(diagnostics.get("ch4_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("ch4_detail") else "",
                "trace_gas_family": json.dumps(diagnostics.get("trace_gas_family", {}), ensure_ascii=False) if diagnostics and diagnostics.get("trace_gas_family") else "",
                "requested_rotation_mode": diagnostics.get("requested_rotation_mode", "") if diagnostics else "",
                "applied_rotation_impl": diagnostics.get("applied_rotation_impl", "") if diagnostics else "",
                "planar_fit_library_status": diagnostics.get("planar_fit_library_status", "") if diagnostics else "",
                "planar_fit_library_source": diagnostics.get("planar_fit_library_source", "") if diagnostics else "",
                "planar_fit_library_path": diagnostics.get("planar_fit_library_path", "") if diagnostics else "",
                "planar_fit_library_save_status": diagnostics.get("planar_fit_library_save_status", "") if diagnostics else "",
                "planar_fit_library_saved_path": diagnostics.get("planar_fit_library_saved_path", "") if diagnostics else "",
                "planar_fit_library_id": diagnostics.get("planar_fit_library_id", "") if diagnostics else "",
                "planar_fit_sector_count": diagnostics.get("planar_fit_sector_count", "") if diagnostics else "",
                "planar_fit_valid_sector_count": diagnostics.get("planar_fit_valid_sector_count", "") if diagnostics else "",
                "planar_fit_selected_sector": diagnostics.get("planar_fit_selected_sector", "") if diagnostics else "",
                "planar_fit_selected_sector_window_count": diagnostics.get("planar_fit_selected_sector_window_count", "") if diagnostics else "",
                "planar_fit_selected_sector_r_squared": diagnostics.get("planar_fit_selected_sector_r_squared", "") if diagnostics else "",
                "planar_fit_wind_direction_deg": diagnostics.get("planar_fit_wind_direction_deg", "") if diagnostics else "",
                "planar_fit_library_detail": json.dumps(diagnostics.get("planar_fit_library_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("planar_fit_library_detail") else "",
                "lag_fallback_reason": diagnostics.get("lag_fallback_reason", "") if diagnostics else "",
                "screening_summary": diagnostics.get("screening_summary", "") if diagnostics else "",
                "qc_details": json.dumps(diagnostics.get("qc_details", {}), ensure_ascii=False) if diagnostics and diagnostics.get("qc_details") else "",
                "metadata_summary": json.dumps(diagnostics.get("metadata_summary", {}), ensure_ascii=False) if diagnostics and diagnostics.get("metadata_summary") else "",
                "water_vapor_flux": rp_window.water_vapor_flux if rp_window else "",
                "sensible_heat_flux_w_m2": diagnostics.get("sensible_heat_flux_w_m2", "") if diagnostics else "",
                "latent_heat_flux_w_m2": diagnostics.get("latent_heat_flux_w_m2", "") if diagnostics else "",
                "evapotranspiration_rate_mm_h": diagnostics.get("evapotranspiration_rate_mm_h", "") if diagnostics else "",
                "evapotranspiration_window_mm": diagnostics.get("evapotranspiration_window_mm", "") if diagnostics else "",
                "momentum_flux_kg_m_s2": diagnostics.get("momentum_flux_kg_m_s2", "") if diagnostics else "",
                "momentum_flux_tau_pa": diagnostics.get("momentum_flux_tau_pa", "") if diagnostics else "",
                "air_density_kg_m3": diagnostics.get("air_density_kg_m3", "") if diagnostics else "",
                "latent_heat_vaporization_j_kg": diagnostics.get("latent_heat_vaporization_j_kg", "") if diagnostics else "",
                "energy_flux_detail": json.dumps(diagnostics.get("energy_flux_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("energy_flux_detail") else "",
                "wpl_water_vapor_term": diagnostics.get("wpl_water_vapor_term", "") if diagnostics else "",
                "wpl_sensible_heat_term": diagnostics.get("wpl_sensible_heat_term", "") if diagnostics else "",
                "wpl_sensible_heat_source": diagnostics.get("wpl_sensible_heat_source", "") if diagnostics else "",
                "cell_thermodynamics_status": diagnostics.get("cell_thermodynamics_status", "") if diagnostics else "",
                "cell_thermodynamics_source": diagnostics.get("cell_thermodynamics_source", "") if diagnostics else "",
                "cell_pressure_valid_ratio": diagnostics.get("cell_pressure_valid_ratio", "") if diagnostics else "",
                "cell_temp_valid_ratio": diagnostics.get("cell_temp_valid_ratio", "") if diagnostics else "",
                "cell_mean_pressure_kpa": diagnostics.get("cell_mean_pressure_kpa", "") if diagnostics else "",
                "cell_mean_temp_c": diagnostics.get("cell_mean_temp_c", "") if diagnostics else "",
                "cov_w_cell_pressure_kpa": diagnostics.get("cov_w_cell_pressure_kpa", "") if diagnostics else "",
                "cov_w_cell_temp_c": diagnostics.get("cov_w_cell_temp_c", "") if diagnostics else "",
                "closed_path_cell_temperature_term": diagnostics.get("closed_path_cell_temperature_term", "") if diagnostics else "",
                "closed_path_cell_pressure_term": diagnostics.get("closed_path_cell_pressure_term", "") if diagnostics else "",
                "closed_path_density_term": diagnostics.get("closed_path_density_term", "") if diagnostics else "",
                "closed_path_density_correction_applied": diagnostics.get("closed_path_density_correction_applied", False) if diagnostics else False,
                "closed_path_cell_detail": json.dumps(diagnostics.get("closed_path_cell_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("closed_path_cell_detail") else "",
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
                "footprint_z_m": diagnostics.get("footprint_z_m", "") if diagnostics else "",
                "footprint_z_m_source": diagnostics.get("footprint_z_m_source", "") if diagnostics else "",
                "footprint_canopy_height_m": diagnostics.get("footprint_canopy_height_m", "") if diagnostics else "",
                "footprint_canopy_height_source": diagnostics.get("footprint_canopy_height_source", "") if diagnostics else "",
                "dynamic_canopy_height_m": diagnostics.get("dynamic_canopy_height_m", "") if diagnostics else "",
                "dynamic_metadata_status": diagnostics.get("dynamic_metadata_status", "") if diagnostics else "",
                "dynamic_metadata_source_path": diagnostics.get("dynamic_metadata_source_path", "") if diagnostics else "",
                "dynamic_metadata_source_row": diagnostics.get("dynamic_metadata_source_row", "") if diagnostics else "",
                "dynamic_metadata_detail": json.dumps(diagnostics.get("dynamic_metadata_detail", {}), ensure_ascii=False) if diagnostics and diagnostics.get("dynamic_metadata_detail") else "",
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

    def _read_json_if_available(self, path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _copy_external_artifacts(self, artifacts: dict[str, Any], *, export_root: Path) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        files: dict[str, str] = {}
        payloads: dict[str, dict[str, Any]] = {}
        for raw_key, path_value in artifacts.items():
            if not path_value:
                continue
            key = str(raw_key)
            if not key.endswith("_artifact"):
                key = f"{key}_artifact"
            source = Path(str(path_value))
            if not source.exists() or not source.is_file():
                continue
            target = export_root / source.name
            try:
                if source.resolve() != target.resolve():
                    if target.exists():
                        target = export_root / f"{key.removesuffix('_artifact')}_{source.name}"
                    shutil.copy2(source, target)
            except OSError:
                continue
            files[key] = str(target)
            payloads[key] = self._read_json_if_available(target)
        return files, payloads

    def export_spectral_assessment_artifact(
        self,
        *,
        spectral_result: SpectralRunResult | None,
        export_root: Path,
    ) -> tuple[Path | None, dict[str, str]]:
        if spectral_result is None:
            return None, {}
        path = export_root / "spectral_assessment.json"
        companion_files = {
            "spectral_binned_ensemble_csv": str(export_root / "spectral_binned_ensemble.csv"),
            "spectral_full_windows_csv": str(export_root / "spectral_full_windows.csv"),
            "spectral_ogive_ensemble_csv": str(export_root / "spectral_ogive_ensemble.csv"),
        }
        payload = self._spectral_assessment_payload(
            spectral_result=spectral_result,
            companion_files=companion_files,
        )
        self._write_json(path, payload)
        self._write_csv(
            Path(companion_files["spectral_binned_ensemble_csv"]),
            list(payload.get("binned_ensemble", {}).get("rows", []) or []),
            _spectral_binned_headers(),
        )
        self._write_csv(
            Path(companion_files["spectral_full_windows_csv"]),
            list(payload.get("full_window_rows", []) or []),
            _spectral_full_headers(),
        )
        self._write_csv(
            Path(companion_files["spectral_ogive_ensemble_csv"]),
            list(payload.get("ogive_ensemble", {}).get("rows", []) or []),
            _spectral_ogive_headers(),
        )
        return path, companion_files

    def export_spectral_assessment_library_artifact(
        self,
        *,
        spectral_runs: list[SpectralRunResult],
        export_root: Path,
        dataset_id: str = "",
        target_bins: int = 24,
        group_by: list[str] | None = None,
        min_windows_per_group: int = 1,
    ) -> tuple[Path | None, dict[str, str]]:
        runs = [run for run in list(spectral_runs or []) if run is not None]
        if not runs:
            return None, {}
        from core.ec_fcc.analysis import build_spectral_assessment_library

        path = export_root / "spectral_assessment_library.json"
        companion_files = {
            "spectral_assessment_library_groups_csv": str(export_root / "spectral_assessment_library_groups.csv"),
            "spectral_assessment_library_bins_csv": str(export_root / "spectral_assessment_library_bins.csv"),
        }
        payload = build_spectral_assessment_library(
            runs,
            dataset_id=dataset_id,
            target_bins=target_bins,
            group_by=group_by,
            min_windows_per_group=min_windows_per_group,
        )
        payload["companion_files"] = companion_files
        self._write_json(path, payload)
        self._write_csv(
            Path(companion_files["spectral_assessment_library_groups_csv"]),
            _spectral_library_group_rows(payload),
            _spectral_library_group_headers(),
        )
        self._write_csv(
            Path(companion_files["spectral_assessment_library_bins_csv"]),
            _spectral_library_bin_rows(payload),
            _spectral_library_bin_headers(),
        )
        return path, companion_files

    def _spectral_assessment_payload(
        self,
        *,
        spectral_result: SpectralRunResult,
        companion_files: dict[str, str],
    ) -> dict[str, Any]:
        windows = list(spectral_result.windows or [])
        series_defs = [
            ("power_measured", "power_freq", "power_measured"),
            ("power_reference", "power_freq", "power_ref"),
            ("cospectrum", "cross_freq", "cross_value"),
            ("ogive", "ogive_freq", "ogive_value"),
            ("transfer_observed", "transfer_freq", "transfer_value"),
            ("total_transfer_model", "total_transfer_function_freq", "total_transfer_function_value"),
        ]
        window_series: list[dict[str, Any]] = []
        full_rows: list[dict[str, Any]] = []
        for window in windows:
            series_payload: dict[str, Any] = {
                "window_id": window.window_id,
                "start_time": window.start_time.isoformat(),
                "end_time": window.end_time.isoformat(),
                "qc_grade": window.qc_grade,
                "model_version": window.model_version,
                "series": {},
            }
            for series_name, freq_attr, value_attr in series_defs:
                pairs = _paired_numeric_series(getattr(window, freq_attr, []), getattr(window, value_attr, []))
                series_payload["series"][series_name] = pairs
                for freq, value in pairs:
                    full_rows.append(
                        {
                            "window_id": window.window_id,
                            "start_time": window.start_time.isoformat(),
                            "end_time": window.end_time.isoformat(),
                            "qc_grade": window.qc_grade,
                            "series": series_name,
                            "freq_hz": freq,
                            "value": value,
                            "model_version": window.model_version,
                        }
                    )
            window_series.append(series_payload)

        all_freqs = [
            freq
            for payload in window_series
            for pairs in dict(payload.get("series", {}) or {}).values()
            for freq, _value in list(pairs or [])
            if freq > 0.0
        ]
        edges = _log_frequency_edges(all_freqs, target_bins=24)
        binned_rows = _spectral_binned_rows(window_series, edges, [item[0] for item in series_defs])
        ogive_rows = [
            {
                "bin_index": row["bin_index"],
                "freq_center_hz": row["freq_center_hz"],
                "ogive_mean": row.get("ogive_mean", ""),
                "ogive_window_count": row.get("ogive_window_count", 0),
                "cospectrum_mean": row.get("cospectrum_mean", ""),
                "cospectrum_window_count": row.get("cospectrum_window_count", 0),
            }
            for row in binned_rows
        ]
        usable_window_ids = [
            str(payload.get("window_id", ""))
            for payload in window_series
            if any(list(pairs or []) for pairs in dict(payload.get("series", {}) or {}).values())
        ]
        model_versions = sorted(
            {
                str(getattr(window, "model_version", "")).strip()
                for window in windows
                if str(getattr(window, "model_version", "")).strip()
            }
        )
        return {
            "artifact_type": "spectral_assessment_export_v1",
            "status": "ok" if full_rows else "empty",
            "run_id": spectral_result.run_id,
            "created_at": spectral_result.created_at.isoformat(),
            "data_source": spectral_result.data_source,
            "time_range": spectral_result.time_range,
            "window_count": len(windows),
            "usable_window_count": len(usable_window_ids),
            "frequency_units": "Hz",
            "value_families": [item[0] for item in series_defs],
            "binned_ensemble": {
                "binning": "log_frequency",
                "bin_count": len(binned_rows),
                "rows": binned_rows,
            },
            "ogive_ensemble": {
                "binning": "log_frequency",
                "rows": ogive_rows,
            },
            "full_window_row_count": len(full_rows),
            "full_window_rows": full_rows,
            "summary": {
                "mean_correction_factor": _mean_or_zero([float(window.correction_factor) for window in windows]),
                "mean_lag_seconds": _mean_or_zero([float(window.lag_seconds) for window in windows]),
                "qc_grade_counts": dict(sorted(Counter(str(window.qc_grade) for window in windows).items())),
                "model_versions": model_versions,
                "source_window_ids": usable_window_ids,
            },
            "companion_files": companion_files,
            "provenance": {
                "source": "ECFCCPipeline WindowSpectralResult power/cross/ogive/transfer arrays",
                "ensemble_method": "log-frequency interpolation followed by arithmetic mean across windows",
                "model_versions": model_versions,
            },
            "known_limitations": [
                "This artifact exports measured spectra/cospectra/ogives from the current FCC run; it is not an official EddyPro spectral assessment dataset.",
                "Long-period ensemble assessment depends on the available run windows and should be expanded with month-scale field data.",
                "Frequency bins are log-spaced and interpolated for delivery consistency, so original full per-window rows are kept as a companion CSV.",
            ],
        }

    def export_synthetic_eddypro_parity_artifact(
        self,
        *,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
        report_key: str = "",
    ) -> Path | None:
        if not _synthetic_eddypro_parity_enabled(rp_config_snapshot=rp_config_snapshot, report_key=report_key):
            return None
        from core.comparison.synthetic_parity import run_synthetic_eddypro_parity_suite

        payload = run_synthetic_eddypro_parity_suite()
        path = export_root / "synthetic_eddypro_parity_artifact.json"
        self._write_json(path, payload)
        return path

    def export_raw_to_final_parity_artifact(
        self,
        *,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
        report_key: str = "",
    ) -> Path | None:
        if not _raw_to_final_parity_enabled(rp_config_snapshot=rp_config_snapshot, report_key=report_key):
            return None
        cfg = dict(rp_config_snapshot.get("raw_to_final_parity", {}) or {})
        raw_path = cfg.get("raw_path") or cfg.get("input_path")
        if not raw_path:
            return None
        payload = run_raw_to_final_parity_harness(
            raw_path=raw_path,
            metadata=cfg.get("metadata") or cfg.get("metadata_snapshot") or {},
            rp_config=rp_config_snapshot,
            reference_json_path=cfg.get("reference_json_path") or cfg.get("reference_json"),
            reference_windows=list(cfg.get("reference_windows", []) or []),
            fixture_id=str(cfg.get("fixture_id", "")),
            thresholds=dict(cfg.get("thresholds", {}) or {}),
            data_source=str(cfg.get("data_source", "raw_to_final_parity")),
            time_range=str(cfg.get("time_range", "")),
        )
        path = export_root / "raw_to_final_parity_artifact.json"
        self._write_json(path, payload)
        return path

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
                "li7700_diagnostics_status": "not_available",
                "li7700_status_diagnostics": {},
                "li7700_wms_fit_quality_status": "",
                "li7700_wms_selected_fit_model": "",
                "li7700_wms_fit_diagnostics": {},
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
            "li7700_diagnostics_status": first.get("li7700_diagnostics_status", "not_available"),
            "li7700_status_diagnostics": first.get("li7700_status_diagnostics", {}),
            "li7700_wms_fit_quality_status": first.get("li7700_wms_fit_quality_status", ""),
            "li7700_wms_selected_fit_model": first.get("li7700_wms_selected_fit_model", ""),
            "li7700_wms_fit_normalized_rmse": first.get("li7700_wms_fit_normalized_rmse"),
            "li7700_wms_area_source": first.get("li7700_wms_area_source", ""),
            "li7700_wms_fit_diagnostics": first.get("li7700_wms_fit_diagnostics", {}),
            "provenance": first.get("ch4_provenance", ""),
            "limitations": list(first.get("ch4_limitations", []) or []),
        }

    def _li7700_wms_fit_acceptance_thresholds(self, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        trace = rp_config_snapshot.get("trace_gas", {}) if isinstance(rp_config_snapshot.get("trace_gas", {}), dict) else {}
        ch4 = trace.get("ch4", {}) if isinstance(trace.get("ch4", {}), dict) else {}
        spectroscopic = ch4.get("spectroscopic_correction", {}) if isinstance(ch4.get("spectroscopic_correction", {}), dict) else {}
        fit_acceptance = spectroscopic.get("fit_acceptance", spectroscopic.get("wms_fit_acceptance", {}))
        fit_acceptance = fit_acceptance if isinstance(fit_acceptance, dict) else {}
        return {
            "normalized_rmse_pass_max": float(fit_acceptance.get("normalized_rmse_pass_max", 0.15) or 0.15),
            "normalized_rmse_warning_max": float(fit_acceptance.get("normalized_rmse_warning_max", 0.35) or 0.35),
            "area_ratio_min": float(fit_acceptance.get("area_ratio_min", 0.65) or 0.65),
            "area_ratio_max": float(fit_acceptance.get("area_ratio_max", 1.35) or 1.35),
        }

    def _li7700_wms_fit_acceptance_payload(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = self._li7700_wms_fit_acceptance_thresholds(rp_config_snapshot)
        if rp_result is None:
            return {
                "artifact_type": "li7700_wms_fit_acceptance_v1",
                "status": "missing",
                "thresholds": thresholds,
                "windows": [],
            }
        windows: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        for window in rp_result.windows:
            diagnostics = dict(window.diagnostics or {})
            fit = dict(diagnostics.get("li7700_wms_fit_diagnostics", {}) or {})
            if not fit:
                continue
            selected = dict(fit.get("selected_fit", {}) or {})
            normalized_rmse = _optional_number(selected.get("normalized_rmse", diagnostics.get("li7700_wms_fit_normalized_rmse")))
            area_ratio = _optional_number(fit.get("selected_to_integrated_area_ratio"))
            acceptance_status, reasons = _li7700_wms_acceptance_status(
                normalized_rmse=normalized_rmse,
                area_ratio=area_ratio,
                thresholds=thresholds,
                fit_status=str(fit.get("status", "")),
            )
            status_counts[acceptance_status] += 1
            windows.append(
                {
                    "window_id": window.window_id,
                    "start_time": window.start_time.isoformat(),
                    "end_time": window.end_time.isoformat(),
                    "qc_grade": window.qc_grade,
                    "ch4_status": diagnostics.get("ch4_status", ""),
                    "fit_status": fit.get("status", ""),
                    "fit_quality_status": diagnostics.get("li7700_wms_fit_quality_status", fit.get("quality_status", "")),
                    "acceptance_status": acceptance_status,
                    "acceptance_reasons": reasons,
                    "selected_model": diagnostics.get("li7700_wms_selected_fit_model", fit.get("selected_model", "")),
                    "normalized_rmse": normalized_rmse,
                    "area_ratio": area_ratio,
                    "area_source": diagnostics.get("li7700_wms_area_source", ""),
                    "integrated_area": fit.get("integrated_area"),
                    "selected_fit_area": selected.get("area"),
                    "candidate_models": [str(item.get("model", "")) for item in list(fit.get("candidate_fits", []) or []) if isinstance(item, dict)],
                    "method_deviation_notes": _build_method_deviation_notes(diagnostics, {}),
                    "fit_diagnostics": fit,
                }
            )
        evaluated = len(windows)
        if not evaluated:
            status = "not_available"
        elif status_counts.get("fail", 0):
            status = "fail"
        elif status_counts.get("warning", 0):
            status = "warning"
        else:
            status = "pass"
        return {
            "artifact_type": "li7700_wms_fit_acceptance_v1",
            "status": status,
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "thresholds": thresholds,
            "window_count": len(rp_result.windows),
            "evaluated_window_count": evaluated,
            "pass_count": int(status_counts.get("pass", 0)),
            "warning_count": int(status_counts.get("warning", 0)),
            "fail_count": int(status_counts.get("fail", 0)),
            "not_evaluable_count": int(status_counts.get("not_evaluable", 0)),
            "windows": windows,
            "eddypro_source_anchors": {
                "engine_modules": ["src/src_rp/m_li7700.f90", "src/src_rp/m_trace_gas.f90"],
                "public_repositories": {
                    "eddypro_engine": "https://github.com/LI-COR-Environmental/eddypro-engine",
                    "eddypro_gui": "https://github.com/LI-COR-Environmental/eddypro-gui",
                },
                "documentation": "https://www.licor.com/support/EddyPro/topics/calculate-flux-7200-and-7700.html",
            },
            "provenance": "LI-7700 WMS fit acceptance v1 is derived from per-window Gaussian/Lorentzian line-shape fit diagnostics exported by RP.",
            "limitations": [
                "Acceptance thresholds are open, auditable policy gates and are not a claim of LI-7700 firmware-equivalent WMS fitting.",
                "Public real LI-7700 WMS scans with matching EddyPro Full_Output are still required for numeric parity closure.",
            ],
        }

    def export_li7700_wms_fit_acceptance_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        payload = self._li7700_wms_fit_acceptance_payload(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
        )
        if payload.get("status") in {"missing", "not_available"}:
            return None
        path = export_root / "li7700_wms_fit_acceptance.json"
        self._write_json(path, payload)
        return path

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

    def _planar_fit_library_summary(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        if rp_result is None:
            return {}
        artifacts = dict(rp_result.artifacts or {})
        artifact_summary = artifacts.get("planar_fit_library")
        if isinstance(artifact_summary, dict) and artifact_summary:
            return dict(artifact_summary)
        summary = dict(rp_result.summary or {})
        summary_payload = summary.get("planar_fit_library")
        if isinstance(summary_payload, dict) and summary_payload:
            return dict(summary_payload)
        for window in rp_result.windows or []:
            diagnostics = dict(window.diagnostics or {})
            detail = diagnostics.get("planar_fit_library_detail")
            if isinstance(detail, dict) and detail:
                return dict(detail)
        return {}

    def export_planar_fit_library_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        summary = self._planar_fit_library_summary(rp_result=rp_result)
        if not summary or summary.get("status") in {"not_requested", ""}:
            return None
        path = export_root / "planar_fit_library.json"
        self._write_json(path, summary)
        return path

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

    def export_footprint_geojson_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        site: object,
        export_root: Path,
    ) -> Path | None:
        payload = self._footprint_geojson_payload(rp_result=rp_result, site=site)
        if payload.get("status") in {"missing_site_coordinates", "missing_footprint_grid", "missing"}:
            return None
        path = export_root / "footprint_geojson.json"
        self._write_json(path, payload)
        return path

    def _footprint_geojson_payload(self, *, rp_result: RPRunResult | None, site: object) -> dict[str, Any]:
        if rp_result is None:
            return {"type": "FeatureCollection", "artifact_type": "footprint_geojson_v1", "status": "missing", "features": []}
        latitude = _coerce_optional_float(_object_get(site, "latitude"))
        longitude = _coerce_optional_float(_object_get(site, "longitude"))
        if latitude is None or longitude is None:
            return {
                "type": "FeatureCollection",
                "artifact_type": "footprint_geojson_v1",
                "status": "missing_site_coordinates",
                "features": [],
                "limitations": ["Site latitude/longitude are required before exporting georeferenced footprint polygons."],
            }
        features: list[dict[str, Any]] = []
        for window in rp_result.windows:
            diagnostics = dict(window.diagnostics or {})
            grid = dict(diagnostics.get("footprint_2d_grid", {}) or {})
            if not grid:
                continue
            features.extend(
                _footprint_grid_geojson_features(
                    window=window,
                    diagnostics=diagnostics,
                    grid=grid,
                    latitude=float(latitude),
                    longitude=float(longitude),
                )
            )
        if not features:
            return {
                "type": "FeatureCollection",
                "artifact_type": "footprint_geojson_v1",
                "status": "missing_footprint_grid",
                "features": [],
                "site": {"latitude": latitude, "longitude": longitude},
            }
        return {
            "type": "FeatureCollection",
            "artifact_type": "footprint_geojson_v1",
            "status": "ok",
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "coordinate_reference_system": "EPSG:4326",
            "site": {
                "latitude": latitude,
                "longitude": longitude,
                "station_code": str(_object_get(site, "station_code", "")),
                "station_name": str(_object_get(site, "station_name", "")),
            },
            "feature_count": len(features),
            "summary": dict(rp_result.summary.get("footprint_2d_summary", {}) if isinstance(rp_result.summary, dict) else {}),
            "features": features,
            "limitations": [
                "GeoJSON uses the processed footprint bearing available in diagnostics; verify sonic north alignment for map-grade use.",
                "Polygons are diagnostic source-area grid cells, not a cadastral land-cover classification.",
            ],
        }

    def export_footprint_geotiff_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        site: object,
        export_root: Path,
    ) -> Path | None:
        record = _first_footprint_grid_record(rp_result)
        latitude = _coerce_optional_float(_object_get(site, "latitude"))
        longitude = _coerce_optional_float(_object_get(site, "longitude"))
        if record is None or latitude is None or longitude is None:
            return None
        window, diagnostics, grid = record
        path = export_root / "footprint_geotiff.tif"
        _write_footprint_geotiff(
            path=path,
            window=window,
            diagnostics=diagnostics,
            grid=grid,
            latitude=float(latitude),
            longitude=float(longitude),
        )
        return path

    def export_footprint_land_cover_overlay_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        site: object,
        export_root: Path,
    ) -> Path | None:
        payload = _footprint_land_cover_overlay_payload(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            site=site,
        )
        if payload.get("status") in {"missing", "missing_footprint_grid", "missing_land_cover"}:
            return None
        path = export_root / "footprint_land_cover_overlay.json"
        self._write_json(path, payload)
        return path

    def export_footprint_gis_validation_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        site: object,
        export_root: Path,
        footprint_geojson_path: Path | None,
        footprint_geotiff_path: Path | None,
        footprint_land_cover_overlay_path: Path | None,
    ) -> Path | None:
        payload = _footprint_gis_validation_payload(
            rp_result=rp_result,
            rp_config_snapshot=rp_config_snapshot,
            site=site,
            footprint_geojson_path=footprint_geojson_path,
            footprint_geotiff_path=footprint_geotiff_path,
            footprint_land_cover_overlay_path=footprint_land_cover_overlay_path,
        )
        if payload.get("status") in {"missing", "missing_footprint_grid"}:
            return None
        path = export_root / "footprint_gis_validation.json"
        self._write_json(path, payload)
        return path

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

    def _flux_correction_ledger_payload(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        if rp_result is None:
            return {"artifact_type": "flux_correction_ledger_run_v1", "status": "missing", "summary": {}, "windows": []}
        artifacts = dict(rp_result.artifacts or {})
        artifact_payload = dict(artifacts.get("flux_correction_ledger", {}) or {})
        if artifact_payload:
            return {
                **artifact_payload,
                "run_id": rp_result.run_id,
                "created_at": rp_result.created_at.isoformat(),
            }
        windows = [
            dict(window.diagnostics.get("flux_correction_ledger", {}) or {})
            for window in rp_result.windows
            if isinstance(window.diagnostics, dict) and window.diagnostics.get("flux_correction_ledger")
        ]
        return {
            "artifact_type": "flux_correction_ledger_run_v1",
            "status": "ok" if windows else "no_ledgers",
            "run_id": rp_result.run_id,
            "created_at": rp_result.created_at.isoformat(),
            "summary": dict(rp_result.summary.get("flux_correction_ledger_summary", {}) if isinstance(rp_result.summary, dict) else {}),
            "windows": windows,
        }

    def _flux_correction_ledger_summary(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        payload = self._flux_correction_ledger_payload(rp_result=rp_result)
        return dict(payload.get("summary", {}) or {})

    def _biomet_ambient_summary(self, *, rp_result: RPRunResult | None) -> dict[str, Any]:
        if rp_result is None:
            return {"status": "missing", "window_count": 0, "applied_window_count": 0, "applied_fields": []}
        applied_fields: Counter[str] = Counter()
        source_modes: Counter[str] = Counter()
        applied_window_count = 0
        for window in rp_result.windows:
            diagnostics = window.diagnostics or {}
            if diagnostics.get("biomet_ambient_status") != "applied":
                continue
            applied_window_count += 1
            for field in diagnostics.get("biomet_ambient_applied_fields", []) or []:
                applied_fields[str(field)] += 1
            mode = str(diagnostics.get("biomet_ambient_source_mode", "") or "unknown")
            source_modes[mode] += 1
        return {
            "artifact_type": "biomet_ambient_summary_v1",
            "status": "applied" if applied_window_count else "not_applied",
            "window_count": len(rp_result.windows),
            "applied_window_count": applied_window_count,
            "applied_fields": dict(sorted(applied_fields.items())),
            "source_modes": dict(sorted(source_modes.items())),
            "provenance": "Biomet ambient summary is derived from per-window RP diagnostics and exported manifest fields.",
        }

    def export_flux_correction_ledger_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        export_root: Path,
    ) -> Path | None:
        payload = self._flux_correction_ledger_payload(rp_result=rp_result)
        if payload.get("status") in {"missing", "no_ledgers"}:
            return None
        path = export_root / "flux_correction_ledger.json"
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

    def _runtime_deployment_feedback_summary(self, *, rp_result: RPRunResult | None, rp_config_snapshot: dict[str, Any]) -> dict[str, Any]:
        if rp_result is not None:
            artifacts = dict(rp_result.artifacts or {})
            if isinstance(artifacts.get("runtime_deployment_feedback"), dict) and artifacts["runtime_deployment_feedback"]:
                return dict(artifacts["runtime_deployment_feedback"])
        supervisor = self._supervisor_integration_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if isinstance(supervisor.get("runtime_deployment_feedback"), dict) and supervisor["runtime_deployment_feedback"]:
            return dict(supervisor["runtime_deployment_feedback"])
        if has_runtime_deployment_feedback_config(rp_config_snapshot):
            installable = self._installable_runtime_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
            deployment = self._runtime_deployment_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
            service_status = dict(supervisor.get("service_status", {}) or {})
            return build_runtime_deployment_feedback_artifact(
                config=rp_config_snapshot,
                runtime_root=self.runtime_root,
                installable_runtime_profile=installable,
                runtime_deployment=deployment,
                service_status=service_status,
            )
        return {}

    def export_runtime_deployment_feedback_artifact(
        self,
        *,
        rp_result: RPRunResult | None,
        rp_config_snapshot: dict[str, Any],
        export_root: Path,
    ) -> Path | None:
        summary = self._runtime_deployment_feedback_summary(rp_result=rp_result, rp_config_snapshot=rp_config_snapshot)
        if not summary:
            return None
        payload = {
            "artifact_type": "runtime_deployment_feedback",
            "run_id": rp_result.run_id if rp_result else "",
            "created_at": rp_result.created_at.isoformat() if rp_result else "",
            "summary": summary,
            "provenance": "Runtime deployment feedback artifact exported from target-host post-install status evidence.",
        }
        path = export_root / "runtime_deployment_feedback_artifact.json"
        self._write_json(path, payload)
        return path

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
                    "clock_sync_quality_status": diagnostics.get("clock_sync_quality_status", ""),
                    "clock_sync_quality_gate_status": diagnostics.get("clock_sync_quality_gate_status", ""),
                    "clock_sync_quality_metric_s": diagnostics.get("clock_sync_quality_metric_s"),
                    "clock_sync_quality_threshold_s": diagnostics.get("clock_sync_quality_threshold_s"),
                    "clock_sync_max_event_step_s": diagnostics.get("clock_sync_max_event_step_s"),
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
        elif schema_target == "GHG-Europe":
            artifact_path = self.export_ghg_europe_artifact(
                rp_result=rp_result,
                export_root=export_root,
                timezone_offset_hours=float(config["timezone_offset_hours"]),
                timestamp_refers_to=str(config["timestamp_refers_to"]),
                gap_fill_value=float(config["gap_fill_value"]),
                site_id=str(config["site_id"]),
            )
            if artifact_path is not None:
                metadata_path = artifact_path
                files["ghg_europe_artifact"] = str(artifact_path)
                csv_path = export_root / "ghg_europe_legacy_artifact.csv"
                if csv_path.exists():
                    files["ghg_europe_csv"] = str(csv_path)

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
                    "sensible_heat_flux_w_m2": "",
                    "latent_heat_flux_w_m2": "",
                    "evapotranspiration_rate_mm_h": "",
                    "evapotranspiration_window_mm": "",
                    "momentum_flux_kg_m_s2": "",
                    "momentum_flux_tau_pa": "",
                    "air_density_kg_m3": "",
                    "latent_heat_vaporization_j_kg": "",
                    "energy_flux_detail": "",
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
            entry["li7700_diagnostics_status"] = br.get("li7700_diagnostics_status", diagnostics.get("li7700_diagnostics_status", ""))
            entry["li7700_status_diagnostics"] = br.get("li7700_status_diagnostics", diagnostics.get("li7700_status_diagnostics", {}))
            entry["li7700_wms_fit_quality_status"] = br.get("li7700_wms_fit_quality_status", diagnostics.get("li7700_wms_fit_quality_status", ""))
            entry["li7700_wms_selected_fit_model"] = br.get("li7700_wms_selected_fit_model", diagnostics.get("li7700_wms_selected_fit_model", ""))
            entry["li7700_wms_fit_normalized_rmse"] = br.get("li7700_wms_fit_normalized_rmse", diagnostics.get("li7700_wms_fit_normalized_rmse"))
            entry["li7700_wms_area_source"] = br.get("li7700_wms_area_source", diagnostics.get("li7700_wms_area_source", ""))
            entry["li7700_wms_fit_diagnostics"] = br.get("li7700_wms_fit_diagnostics", diagnostics.get("li7700_wms_fit_diagnostics", {}))
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
        qc = window.qc_grade
        qc_num = {"A": 0, "B": 1, "C": 2}.get(qc, 2)
        diagnostics = dict(window.diagnostics or {})
        def _diag_number(name: str) -> float:
            value = diagnostics.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
            return float(gap_fill_value)
        le = _diag_number("latent_heat_flux_w_m2")
        h = _diag_number("sensible_heat_flux_w_m2")
        et = _diag_number("evapotranspiration_rate_mm_h")
        tau = _diag_number("momentum_flux_kg_m_s2")
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
            "H": h,
            "LE": le,
            "ET": et,
            "TAU": tau,
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
            "CLOCK_SYNC_QUALITY_STATUS": diagnostics.get("clock_sync_quality_status", ""),
            "CLOCK_SYNC_QUALITY_GATE_STATUS": diagnostics.get("clock_sync_quality_gate_status", ""),
            "CLOCK_SYNC_QUALITY_METRIC_S": diagnostics.get("clock_sync_quality_metric_s", ""),
            "CLOCK_SYNC_QUALITY_THRESHOLD_S": diagnostics.get("clock_sync_quality_threshold_s", ""),
            "CLOCK_SYNC_MAX_EVENT_STEP_S": diagnostics.get("clock_sync_max_event_step_s", ""),
            "RUNTIME_WATCHDOG_STATUS": diagnostics.get("runtime_watchdog_status", "not_run"),
            "RUNTIME_WATCHDOG_PROFILE": diagnostics.get("runtime_watchdog_profile", "not_configured"),
            "RUNTIME_WATCHDOG_FAIL_COUNT": diagnostics.get("runtime_watchdog_fail_count", 0),
            "RUNTIME_SERVICE_STATUS": diagnostics.get("runtime_service_status", "not_run"),
            "RUNTIME_SERVICE_DELIVERY_STATE": diagnostics.get("runtime_service_delivery_state", "not_run"),
            "RUNTIME_SERVICE_QUARANTINE_COUNT": diagnostics.get("runtime_service_quarantine_count", 0),
            "DAEMON_TELEMETRY_STATUS": diagnostics.get("daemon_telemetry_status", "not_run"),
            "TARGET_HOST_VALIDATION_STATUS": diagnostics.get("target_host_validation_status", "not_configured"),
            "TARGET_HOST_VALIDATION_GATE_STATUS": diagnostics.get("target_host_validation_gate_status", "not_configured"),
            "TARGET_HOST_VALIDATION_FIXTURE_ID": diagnostics.get("target_host_validation_fixture_id", ""),
            "TARGET_HOST_ID": diagnostics.get("target_host_validation_target_host_id", ""),
            "SUPERVISOR_STATE": diagnostics.get("supervisor_state", "not_configured"),
            "PTP_LOCK_STATUS": diagnostics.get("ptp_lock_status", "not_configured"),
            "GPS_PPS_LOCK_STATUS": diagnostics.get("gps_pps_lock_status", "not_configured"),
            "CLOCK_DISCIPLINE_STATUS": diagnostics.get("clock_discipline_status", "not_configured"),
            "CLOCK_DISCIPLINE_OFFSET_NS": diagnostics.get("clock_discipline_offset_ns", ""),
            "CLOCK_DISCIPLINE_FREQUENCY_PPM": diagnostics.get("clock_discipline_frequency_ppm", ""),
            "HARDWARE_WATCHDOG_STATUS": diagnostics.get("hardware_watchdog_status", "not_configured"),
            "OS_SUPERVISOR_STATUS": diagnostics.get("os_supervisor_status", "not_configured"),
            "OS_SUPERVISOR_STATE": diagnostics.get("os_supervisor_state", "not_configured"),
            "WATCHDOG_PROVIDER_STATUS": diagnostics.get("watchdog_provider_status", "not_configured"),
            "WATCHDOG_PROVIDER_TYPE": diagnostics.get("watchdog_provider_type", "not_configured"),
            "WATCHDOG_KICK_DELIVERED": diagnostics.get("watchdog_kick_delivered", False),
            "WATCHDOG_REBOOT_RECORDED": diagnostics.get("watchdog_reboot_recorded", False),
            "INSTALLABLE_RUNTIME_STATUS": diagnostics.get("installable_runtime_status", "not_configured"),
            "INSTALLABLE_RUNTIME_TARGETS": "|".join(diagnostics.get("installable_runtime_targets", []) or [])
            if isinstance(diagnostics.get("installable_runtime_targets"), list)
            else diagnostics.get("installable_runtime_targets", ""),
            "RUNTIME_DEPLOYMENT_STATUS": diagnostics.get("runtime_deployment_status", "not_configured"),
            "RUNTIME_DEPLOYMENT_FEEDBACK_STATUS": diagnostics.get("runtime_deployment_feedback_status", "not_configured"),
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
            "H": gap_fill_value,
            "LE": gap_fill_value,
            "ET": gap_fill_value,
            "TAU": gap_fill_value,
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
            "CLOCK_SYNC_QUALITY_STATUS": "not_configured",
            "CLOCK_SYNC_QUALITY_GATE_STATUS": "not_configured",
            "CLOCK_SYNC_QUALITY_METRIC_S": "",
            "CLOCK_SYNC_QUALITY_THRESHOLD_S": "",
            "CLOCK_SYNC_MAX_EVENT_STEP_S": "",
            "RUNTIME_WATCHDOG_STATUS": "gap_fill",
            "RUNTIME_WATCHDOG_PROFILE": "not_configured",
            "RUNTIME_WATCHDOG_FAIL_COUNT": 0,
            "RUNTIME_SERVICE_STATUS": "gap_fill",
            "RUNTIME_SERVICE_DELIVERY_STATE": "not_run",
            "RUNTIME_SERVICE_QUARANTINE_COUNT": 0,
            "DAEMON_TELEMETRY_STATUS": "gap_fill",
            "TARGET_HOST_VALIDATION_STATUS": "not_configured",
            "TARGET_HOST_VALIDATION_GATE_STATUS": "not_configured",
            "TARGET_HOST_VALIDATION_FIXTURE_ID": "",
            "TARGET_HOST_ID": "",
            "SUPERVISOR_STATE": "not_configured",
            "PTP_LOCK_STATUS": "not_configured",
            "GPS_PPS_LOCK_STATUS": "not_configured",
            "CLOCK_DISCIPLINE_STATUS": "not_configured",
            "CLOCK_DISCIPLINE_OFFSET_NS": "",
            "CLOCK_DISCIPLINE_FREQUENCY_PPM": "",
            "HARDWARE_WATCHDOG_STATUS": "not_configured",
            "OS_SUPERVISOR_STATUS": "not_configured",
            "OS_SUPERVISOR_STATE": "not_configured",
            "WATCHDOG_PROVIDER_STATUS": "not_configured",
            "WATCHDOG_PROVIDER_TYPE": "not_configured",
            "WATCHDOG_KICK_DELIVERED": False,
            "WATCHDOG_REBOOT_RECORDED": False,
            "INSTALLABLE_RUNTIME_STATUS": "not_configured",
            "INSTALLABLE_RUNTIME_TARGETS": "",
            "RUNTIME_DEPLOYMENT_STATUS": "not_configured",
            "RUNTIME_DEPLOYMENT_FEEDBACK_STATUS": "not_configured",
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

    def export_ghg_europe_artifact(
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
        from datetime import datetime as _dt, timedelta

        rows: list[dict[str, Any]] = []
        method_rows: list[dict[str, Any]] = []
        for window in rp_result.windows:
            internal_row = self._fluxnet_half_hourly_row(
                window=window,
                timezone_offset_hours=timezone_offset_hours,
                timestamp_refers_to=timestamp_refers_to,
                gap_fill_value=gap_fill_value,
            )
            ghg_row = self._remap_row(internal_row, GHG_EUROPE_FIELD_MAP)
            local_start = window.start_time + timedelta(hours=timezone_offset_hours)
            local_end = window.end_time + timedelta(hours=timezone_offset_hours)
            ghg_row["TIMESTAMP_START"] = local_start.strftime("%Y%m%d%H%M")
            ghg_row["TIMESTAMP_END"] = local_end.strftime("%Y%m%d%H%M")
            ghg_row["NEE_PI"] = ghg_row.get("FC", gap_fill_value)
            ghg_row.update(self._ghg_europe_footprint_fields(window=window, gap_fill_value=gap_fill_value))
            rows.append(ghg_row)
            diagnostics = dict(window.diagnostics or {})
            method_rows.append(
                {
                    "TIMESTAMP_START": ghg_row["TIMESTAMP_START"],
                    "TIMESTAMP_END": ghg_row["TIMESTAMP_END"],
                    "FOOTPRINT_METHOD": diagnostics.get("footprint_method", ""),
                    "UNCERTAINTY_METHOD": diagnostics.get("uncertainty_method", ""),
                    "SPECTRAL_CORRECTION_METHOD": diagnostics.get("spectral_correction_method", ""),
                    "METHOD_DEVIATION_NOTES": internal_row.get("METHOD_DEVIATION_NOTES", ""),
                }
            )
        continuous = self.generate_continuous_dataset(rp_result=rp_result, averaging_period_minutes=30.0)
        for cont_row in continuous:
            if cont_row.get("anomaly_type") != "gap":
                continue
            gap_internal = self._fluxnet_gap_row(
                cont_row=cont_row,
                timezone_offset_hours=timezone_offset_hours,
                timestamp_refers_to=timestamp_refers_to,
                gap_fill_value=gap_fill_value,
            )
            ghg_gap = self._remap_row(gap_internal, GHG_EUROPE_FIELD_MAP)
            try:
                start_utc = _dt.fromisoformat(str(cont_row.get("start_time", "")))
                end_utc = _dt.fromisoformat(str(cont_row.get("end_time", "")))
                ghg_gap["TIMESTAMP_START"] = (start_utc + timedelta(hours=timezone_offset_hours)).strftime("%Y%m%d%H%M")
                ghg_gap["TIMESTAMP_END"] = (end_utc + timedelta(hours=timezone_offset_hours)).strftime("%Y%m%d%H%M")
            except (TypeError, ValueError):
                pass
            ghg_gap["NEE_PI"] = gap_fill_value
            ghg_gap["FETCH_70"] = gap_fill_value
            ghg_gap["FETCH_90"] = gap_fill_value
            ghg_gap["FETCH_MAX"] = gap_fill_value
            ghg_gap["FETCH_FILTER"] = 0
            rows.append(ghg_gap)
        rows.sort(key=lambda r: r.get("TIMESTAMP_START", ""))
        all_errors: list[str] = []
        for row in rows:
            all_errors.extend(validate_fluxnet_row(row, schema_target="GHG-Europe"))
        missing_fields = self._detect_missing_fields(rows, GHG_EUROPE_FIELD_MAP)
        validation_status = "pass" if not all_errors else "errors_found"
        metadata = {
            "site_id": site_id,
            "schema_target": "GHG-Europe",
            "format_profile": "GHG-Europe legacy half-hourly flux table",
            "timezone_offset_hours": timezone_offset_hours,
            "timestamp_refers_to": "local_standard_start_end",
            "requested_timestamp_refers_to": timestamp_refers_to,
            "gap_fill_value": gap_fill_value,
            "record_count": len(rows),
            "validation_status": validation_status,
            "error_count": len(all_errors),
            "missing_fields": missing_fields,
            "method_provenance_row_count": len(method_rows),
            "method_provenance_fields": [
                "FOOTPRINT_METHOD",
                "UNCERTAINTY_METHOD",
                "SPECTRAL_CORRECTION_METHOD",
                "METHOD_DEVIATION_NOTES",
            ],
            "source_guidelines": [
                "https://www.europe-fluxdata.eu/home/guidelines/obtaining-data/variables-and-formats",
            ],
            "known_limitations": [
                "Legacy GHG-Europe-style exports are generated from the normalized RP result and do not certify upload acceptance by the original database operator.",
                "Method provenance is kept in JSON sidecar rows to preserve traceability without polluting the legacy data table.",
            ],
            "exported_at": datetime.now().isoformat(),
        }
        artifact = {"metadata": metadata, "rows": rows, "method_provenance_rows": method_rows}
        path = export_root / "ghg_europe_legacy_artifact.json"
        self._write_json(path, artifact)
        csv_path = export_root / "ghg_europe_legacy_artifact.csv"
        if rows:
            headers = list(rows[0].keys())
            self._write_csv(csv_path, rows, headers)
        return path

    def _ghg_europe_footprint_fields(self, *, window: WindowRPResult, gap_fill_value: float) -> dict[str, Any]:
        diagnostics = dict(window.diagnostics or {})
        distances = diagnostics.get("footprint_contribution_distances", {})
        if not isinstance(distances, dict):
            distances = {}

        def _distance(percent: int) -> float:
            for key in (percent, str(percent), f"{percent}%", f"p{percent}", f"{percent}_percent"):
                value = distances.get(key)
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    return float(value)
            return float(gap_fill_value)

        fetch70 = _distance(70)
        fetch90 = _distance(90)
        peak = diagnostics.get("footprint_peak_distance_m", gap_fill_value)
        try:
            fetch_max = max(float(fetch90), float(peak))
        except (TypeError, ValueError):
            fetch_max = float(gap_fill_value)
        fetch_filter = 1 if fetch70 != gap_fill_value or fetch90 != gap_fill_value else 0
        return {
            "FETCH_70": fetch70,
            "FETCH_90": fetch90,
            "FETCH_MAX": fetch_max,
            "FETCH_FILTER": fetch_filter,
        }

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
                    "wpl_sensible_heat_source": diag.get("wpl_sensible_heat_source", ""),
                    "cell_thermodynamics_status": diag.get("cell_thermodynamics_status", ""),
                    "cov_w_cell_pressure_kpa": diag.get("cov_w_cell_pressure_kpa"),
                    "cov_w_cell_temp_c": diag.get("cov_w_cell_temp_c"),
                    "closed_path_density_term": diag.get("closed_path_density_term"),
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
                "sonic_angle_of_attack_method": diag.get("sonic_angle_of_attack_method", ""),
                "sonic_angle_of_attack_status": diag.get("sonic_angle_of_attack_status", ""),
                "crosswind_correction_method": diag.get("crosswind_correction_method", ""),
                "crosswind_correction_status": diag.get("crosswind_correction_status", ""),
                "crosswind_correction_mean_delta_c": diag.get("crosswind_correction_mean_delta_c"),
                "clock_sync_status": diag.get("clock_sync_status", ""),
                "clock_sync_method": diag.get("clock_sync_method", ""),
                "clock_sync_source": diag.get("clock_sync_source", ""),
                "clock_sync_mean_offset_s": diag.get("clock_sync_mean_offset_s"),
                "clock_sync_quality_status": diag.get("clock_sync_quality_status", ""),
                "clock_sync_quality_gate_status": diag.get("clock_sync_quality_gate_status", ""),
                "clock_sync_quality_metric_s": diag.get("clock_sync_quality_metric_s"),
                "clock_sync_quality_threshold_s": diag.get("clock_sync_quality_threshold_s"),
                "clock_sync_max_event_step_s": diag.get("clock_sync_max_event_step_s"),
                "ch4_method": diag.get("ch4_method", ""),
                "ch4_flux_nmol_m2_s": diag.get("ch4_flux_nmol_m2_s"),
                "ch4_flux_level0_nmol_m2_s": diag.get("ch4_flux_level0_nmol_m2_s"),
                "ch4_correction_sequence": diag.get("ch4_correction_sequence", {}),
                "ch4_coefficient_profile_id": diag.get("ch4_coefficient_profile_id", ""),
                "ch4_coefficient_registry_status": diag.get("ch4_coefficient_registry_status", ""),
                "ch4_coefficient_profile_provenance": diag.get("ch4_coefficient_profile_provenance", ""),
                "li7700_diagnostics_status": diag.get("li7700_diagnostics_status", ""),
                "li7700_status_diagnostics": diag.get("li7700_status_diagnostics", {}),
                "li7700_wms_fit_quality_status": diag.get("li7700_wms_fit_quality_status", ""),
                "li7700_wms_selected_fit_model": diag.get("li7700_wms_selected_fit_model", ""),
                "li7700_wms_fit_normalized_rmse": diag.get("li7700_wms_fit_normalized_rmse"),
                "li7700_wms_area_source": diag.get("li7700_wms_area_source", ""),
                "li7700_wms_fit_diagnostics": diag.get("li7700_wms_fit_diagnostics", {}),
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
                "wpl_sensible_heat_source": diag.get("wpl_sensible_heat_source", ""),
                "cell_thermodynamics_status": diag.get("cell_thermodynamics_status", ""),
                "cov_w_cell_pressure_kpa": diag.get("cov_w_cell_pressure_kpa"),
                "cov_w_cell_temp_c": diag.get("cov_w_cell_temp_c"),
                "closed_path_density_term": diag.get("closed_path_density_term"),
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
                "sonic_angle_of_attack_method": diag.get("sonic_angle_of_attack_method", ""),
                "sonic_angle_of_attack_status": diag.get("sonic_angle_of_attack_status", ""),
                "crosswind_correction_method": diag.get("crosswind_correction_method", ""),
                "crosswind_correction_status": diag.get("crosswind_correction_status", ""),
                "crosswind_correction_mean_delta_c": diag.get("crosswind_correction_mean_delta_c"),
                "clock_sync_status": diag.get("clock_sync_status", ""),
                "clock_sync_method": diag.get("clock_sync_method", ""),
                "clock_sync_source": diag.get("clock_sync_source", ""),
                "clock_sync_mean_offset_s": diag.get("clock_sync_mean_offset_s"),
                "clock_sync_quality_status": diag.get("clock_sync_quality_status", ""),
                "clock_sync_quality_gate_status": diag.get("clock_sync_quality_gate_status", ""),
                "clock_sync_quality_metric_s": diag.get("clock_sync_quality_metric_s"),
                "clock_sync_quality_threshold_s": diag.get("clock_sync_quality_threshold_s"),
                "clock_sync_max_event_step_s": diag.get("clock_sync_max_event_step_s"),
                "ch4_method": diag.get("ch4_method", ""),
                "ch4_flux_nmol_m2_s": diag.get("ch4_flux_nmol_m2_s"),
                "ch4_flux_level0_nmol_m2_s": diag.get("ch4_flux_level0_nmol_m2_s"),
                "ch4_correction_sequence": diag.get("ch4_correction_sequence", {}),
                "ch4_coefficient_profile_id": diag.get("ch4_coefficient_profile_id", ""),
                "ch4_coefficient_registry_status": diag.get("ch4_coefficient_registry_status", ""),
                "ch4_coefficient_profile_provenance": diag.get("ch4_coefficient_profile_provenance", ""),
                "li7700_diagnostics_status": diag.get("li7700_diagnostics_status", ""),
                "li7700_status_diagnostics": diag.get("li7700_status_diagnostics", {}),
                "li7700_wms_fit_quality_status": diag.get("li7700_wms_fit_quality_status", ""),
                "li7700_wms_selected_fit_model": diag.get("li7700_wms_selected_fit_model", ""),
                "li7700_wms_fit_normalized_rmse": diag.get("li7700_wms_fit_normalized_rmse"),
                "li7700_wms_area_source": diag.get("li7700_wms_area_source", ""),
                "li7700_wms_fit_diagnostics": diag.get("li7700_wms_fit_diagnostics", {}),
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


def _object_get(obj: object, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coerce_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _footprint_grid_geojson_features(
    *,
    window: WindowRPResult,
    diagnostics: dict[str, Any],
    grid: dict[str, Any],
    latitude: float,
    longitude: float,
) -> list[dict[str, Any]]:
    x_coords = [_coerce_optional_float(value) for value in list(grid.get("x_coords_m", []) or [])]
    y_coords = [_coerce_optional_float(value) for value in list(grid.get("y_coords_m", []) or [])]
    x = [float(value) for value in x_coords if value is not None]
    y = [float(value) for value in y_coords if value is not None]
    values = [
        [float(item or 0.0) for item in row]
        for row in list(grid.get("contribution_grid", []) or [])
        if isinstance(row, list)
    ]
    if not x or not y or not values:
        return []
    dx = _coordinate_spacing_m(x)
    dy = _coordinate_spacing_m(y)
    bearing_deg = float(diagnostics.get("footprint_bearing_deg", grid.get("bearing_deg", 0.0)) or 0.0)
    features: list[dict[str, Any]] = []
    for y_index, row in enumerate(values):
        if y_index >= len(y):
            continue
        for x_index, contribution in enumerate(row):
            if x_index >= len(x):
                continue
            polygon = _local_cell_to_lonlat_polygon(
                latitude=latitude,
                longitude=longitude,
                center_x_m=x[x_index],
                center_y_m=y[y_index],
                dx_m=dx,
                dy_m=dy,
                bearing_deg=bearing_deg,
            )
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [polygon]},
                    "properties": {
                        "feature_type": "footprint_grid_cell",
                        "window_id": window.window_id,
                        "start_time": window.start_time.isoformat(),
                        "end_time": window.end_time.isoformat(),
                        "qc_grade": window.qc_grade,
                        "method": str(diagnostics.get("footprint_method", grid.get("method", ""))),
                        "x_m": x[x_index],
                        "y_m": y[y_index],
                        "contribution": contribution,
                        "bearing_deg": bearing_deg,
                    },
                }
            )
    peak_x = _coerce_optional_float(diagnostics.get("footprint_2d_peak_downwind_m"))
    peak_y = _coerce_optional_float(diagnostics.get("footprint_2d_peak_crosswind_m"))
    if peak_x is not None and peak_y is not None:
        peak_lon, peak_lat = _local_to_lonlat(
            latitude=latitude,
            longitude=longitude,
            x_m=peak_x,
            y_m=peak_y,
            bearing_deg=bearing_deg,
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [peak_lon, peak_lat]},
                "properties": {
                    "feature_type": "footprint_peak",
                    "window_id": window.window_id,
                    "method": str(diagnostics.get("footprint_method", grid.get("method", ""))),
                    "peak_downwind_m": peak_x,
                    "peak_crosswind_m": peak_y,
                    "bearing_deg": bearing_deg,
                },
            }
        )
    return features


def _coordinate_spacing_m(values: list[float]) -> float:
    if len(values) < 2:
        return max(abs(values[0]) * 0.15, 1.0) if values else 1.0
    diffs = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    positive = [value for value in diffs if value > 1e-9]
    return float(sorted(positive)[len(positive) // 2]) if positive else 1.0


def _local_cell_to_lonlat_polygon(
    *,
    latitude: float,
    longitude: float,
    center_x_m: float,
    center_y_m: float,
    dx_m: float,
    dy_m: float,
    bearing_deg: float,
) -> list[list[float]]:
    half_x = dx_m / 2.0
    half_y = dy_m / 2.0
    corners = [
        (center_x_m - half_x, center_y_m - half_y),
        (center_x_m + half_x, center_y_m - half_y),
        (center_x_m + half_x, center_y_m + half_y),
        (center_x_m - half_x, center_y_m + half_y),
        (center_x_m - half_x, center_y_m - half_y),
    ]
    return [
        list(_local_to_lonlat(latitude=latitude, longitude=longitude, x_m=x_m, y_m=y_m, bearing_deg=bearing_deg))
        for x_m, y_m in corners
    ]


def _local_to_lonlat(
    *,
    latitude: float,
    longitude: float,
    x_m: float,
    y_m: float,
    bearing_deg: float,
) -> tuple[float, float]:
    theta = math.radians(float(bearing_deg))
    east_m = x_m * math.sin(theta) + y_m * math.cos(theta)
    north_m = x_m * math.cos(theta) - y_m * math.sin(theta)
    lat = latitude + north_m / 111_320.0
    lon_scale = max(math.cos(math.radians(latitude)), 1e-6)
    lon = longitude + east_m / (111_320.0 * lon_scale)
    return round(lon, 8), round(lat, 8)


def _first_footprint_grid_record(
    rp_result: RPRunResult | None,
) -> tuple[WindowRPResult, dict[str, Any], dict[str, Any]] | None:
    if rp_result is None:
        return None
    for window in rp_result.windows:
        diagnostics = dict(window.diagnostics or {})
        grid = diagnostics.get("footprint_2d_grid")
        if isinstance(grid, dict) and grid.get("contribution_grid"):
            return window, diagnostics, dict(grid)
    return None


def _footprint_grid_arrays(grid: dict[str, Any]) -> tuple[list[float], list[float], list[list[float]]]:
    x_coords = [_coerce_optional_float(value) for value in list(grid.get("x_coords_m", []) or [])]
    y_coords = [_coerce_optional_float(value) for value in list(grid.get("y_coords_m", []) or [])]
    x = [float(value) for value in x_coords if value is not None]
    y = [float(value) for value in y_coords if value is not None]
    raw_values = list(grid.get("contribution_grid", []) or [])
    values: list[list[float]] = []
    for row in raw_values:
        if not isinstance(row, list):
            continue
        values.append([float(item or 0.0) for item in row])
    if values and x:
        values = [row[: len(x)] for row in values]
    if y and values:
        values = values[: len(y)]
    return x, y, values


def _write_footprint_geotiff(
    *,
    path: Path,
    window: WindowRPResult,
    diagnostics: dict[str, Any],
    grid: dict[str, Any],
    latitude: float,
    longitude: float,
) -> None:
    x, y, values = _footprint_grid_arrays(grid)
    if not x or not y or not values:
        path.write_bytes(b"")
        return
    row_widths = [len(row) for row in values if row]
    if not row_widths:
        path.write_bytes(b"")
        return
    width = min(len(x), min(row_widths))
    height = min(len(y), len(values))
    if width <= 0 or height <= 0:
        path.write_bytes(b"")
        return
    values = [row[:width] for row in values[:height]]
    x = x[:width]
    y = y[:height]
    dx = _coordinate_spacing_m(x)
    dy = _coordinate_spacing_m(y)
    bearing_deg = float(diagnostics.get("footprint_bearing_deg", grid.get("bearing_deg", 0.0)) or 0.0)
    lon_values: list[float] = []
    lat_values: list[float] = []
    for y_index, row in enumerate(values):
        for x_index, _ in enumerate(row):
            polygon = _local_cell_to_lonlat_polygon(
                latitude=latitude,
                longitude=longitude,
                center_x_m=x[x_index],
                center_y_m=y[y_index],
                dx_m=dx,
                dy_m=dy,
                bearing_deg=bearing_deg,
            )
            lon_values.extend(float(point[0]) for point in polygon)
            lat_values.extend(float(point[1]) for point in polygon)
    if not lon_values or not lat_values:
        path.write_bytes(b"")
        return
    min_lon = min(lon_values)
    max_lon = max(lon_values)
    min_lat = min(lat_values)
    max_lat = max(lat_values)
    pixel_scale_lon = max((max_lon - min_lon) / max(width, 1), 1e-12)
    pixel_scale_lat = max((max_lat - min_lat) / max(height, 1), 1e-12)
    description = (
        f"gas_ec_studio tiled footprint GeoTIFF v1; window={window.window_id}; "
        f"method={diagnostics.get('footprint_method', grid.get('method', ''))}; "
        f"bearing_deg={bearing_deg:.3f}; values=contribution_fraction"
    )
    _write_float32_geotiff(
        path=path,
        width=width,
        height=height,
        rows=values,
        min_lon=min_lon,
        max_lat=max_lat,
        pixel_scale_lon=pixel_scale_lon,
        pixel_scale_lat=pixel_scale_lat,
        description=description,
    )


def _write_float32_geotiff(
    *,
    path: Path,
    width: int,
    height: int,
    rows: list[list[float]],
    min_lon: float,
    max_lat: float,
    pixel_scale_lon: float,
    pixel_scale_lat: float,
    description: str,
) -> None:
    geo_key_directory = [
        1,
        1,
        0,
        3,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
    ]
    overview_rows = _float32_overview_rows(rows=rows, width=width, height=height)
    overview_height = len(overview_rows)
    overview_width = len(overview_rows[0]) if overview_rows else 1
    image_specs = [
        {
            "width": width,
            "height": height,
            "rows": rows,
            "tile_width": _geotiff_tile_size(width),
            "tile_length": _geotiff_tile_size(height),
            "pixel_scale_lon": float(pixel_scale_lon),
            "pixel_scale_lat": float(pixel_scale_lat),
            "description": description,
            "reduced": False,
        },
        {
            "width": overview_width,
            "height": overview_height,
            "rows": overview_rows,
            "tile_width": _geotiff_tile_size(overview_width),
            "tile_length": _geotiff_tile_size(overview_height),
            "pixel_scale_lon": float(pixel_scale_lon) * max(width / max(overview_width, 1), 1.0),
            "pixel_scale_lat": float(pixel_scale_lat) * max(height / max(overview_height, 1), 1.0),
            "description": f"{description}; overview=2x",
            "reduced": True,
        },
    ]
    for spec in image_specs:
        spec["tile_payloads"] = _float32_tile_payloads(
            rows=spec["rows"],
            width=int(spec["width"]),
            height=int(spec["height"]),
            tile_width=int(spec["tile_width"]),
            tile_length=int(spec["tile_length"]),
        )
        spec["tile_byte_counts"] = [len(payload) for payload in spec["tile_payloads"]]
        spec["ascii_payload"] = str(spec["description"]).encode("ascii", errors="replace") + b"\x00"
        spec["pixel_scale_payload"] = struct.pack(
            "<ddd",
            float(spec["pixel_scale_lon"]),
            float(spec["pixel_scale_lat"]),
            0.0,
        )
        spec["tiepoint_payload"] = struct.pack("<dddddd", 0.0, 0.0, 0.0, float(min_lon), float(max_lat), 0.0)
        spec["geo_key_payload"] = struct.pack("<" + "H" * len(geo_key_directory), *geo_key_directory)
        spec["tag_count"] = 17 if spec["reduced"] else 16
    main_tag_count = int(image_specs[0]["tag_count"])
    overview_tag_count = int(image_specs[1]["tag_count"])
    ifd_offset = 8
    main_ifd_size = 2 + main_tag_count * 12 + 4
    overview_ifd_offset = ifd_offset + main_ifd_size
    overview_ifd_size = 2 + overview_tag_count * 12 + 4
    cursor = overview_ifd_offset + overview_ifd_size
    for spec in image_specs:
        tile_count = len(spec["tile_payloads"])
        if tile_count > 1:
            spec["tile_offsets_array_offset"] = cursor
            cursor += tile_count * 4
        else:
            spec["tile_offsets_array_offset"] = 0
        if tile_count > 1:
            spec["tile_byte_counts_array_offset"] = cursor
            cursor += tile_count * 4
        else:
            spec["tile_byte_counts_array_offset"] = 0
        spec["pixel_scale_offset"] = cursor
        cursor += len(spec["pixel_scale_payload"])
        spec["tiepoint_offset"] = cursor
        cursor += len(spec["tiepoint_payload"])
        spec["geo_key_offset"] = cursor
        cursor += len(spec["geo_key_payload"])
        spec["ascii_offset"] = cursor
        cursor += len(spec["ascii_payload"])
    for spec in image_specs:
        tile_count = len(spec["tile_payloads"])
        tile_offsets: list[int] = []
        for payload in spec["tile_payloads"]:
            tile_offsets.append(cursor)
            cursor += len(payload)
        spec["tile_offsets"] = tile_offsets
        spec["tile_offsets_payload"] = struct.pack("<" + "I" * tile_count, *tile_offsets) if tile_count > 1 else b""
        spec["tile_byte_counts_payload"] = (
            struct.pack("<" + "I" * tile_count, *spec["tile_byte_counts"]) if tile_count > 1 else b""
        )
    metadata_parts: list[bytes] = []
    tile_data_parts: list[bytes] = []
    for spec in image_specs:
        metadata_parts.extend(
            [
                spec["tile_offsets_payload"],
                spec["tile_byte_counts_payload"],
                spec["pixel_scale_payload"],
                spec["tiepoint_payload"],
                spec["geo_key_payload"],
                spec["ascii_payload"],
            ]
        )
        tile_data_parts.append(b"".join(spec["tile_payloads"]))

    def _tag(tag: int, tag_type: int, count: int, value: int | bytes) -> bytes:
        if isinstance(value, bytes):
            raw = value[:4].ljust(4, b"\x00")
        else:
            raw = struct.pack("<I", int(value))
        return struct.pack("<HHI", tag, tag_type, count) + raw

    def _image_ifd(spec: dict[str, Any], *, next_ifd_offset: int) -> bytes:
        tile_count = len(spec["tile_payloads"])
        tags = []
        if spec["reduced"]:
            tags.append(_tag(254, 4, 1, 1))
        tags.extend(
            [
                _tag(256, 4, 1, int(spec["width"])),
                _tag(257, 4, 1, int(spec["height"])),
                _tag(258, 3, 1, struct.pack("<H", 32)),
                _tag(259, 3, 1, struct.pack("<H", 1)),
                _tag(262, 3, 1, struct.pack("<H", 1)),
                _tag(270, 2, len(spec["ascii_payload"]), int(spec["ascii_offset"])),
                _tag(277, 3, 1, struct.pack("<H", 1)),
                _tag(284, 3, 1, struct.pack("<H", 1)),
                _tag(322, 4, 1, int(spec["tile_width"])),
                _tag(323, 4, 1, int(spec["tile_length"])),
                _tag(
                    324,
                    4,
                    tile_count,
                    spec["tile_offsets"][0] if tile_count == 1 else int(spec["tile_offsets_array_offset"]),
                ),
                _tag(
                    325,
                    4,
                    tile_count,
                    spec["tile_byte_counts"][0] if tile_count == 1 else int(spec["tile_byte_counts_array_offset"]),
                ),
                _tag(33550, 12, 3, int(spec["pixel_scale_offset"])),
                _tag(33922, 12, 6, int(spec["tiepoint_offset"])),
                _tag(339, 3, 1, struct.pack("<H", 3)),
                _tag(34735, 3, len(geo_key_directory), int(spec["geo_key_offset"])),
            ]
        )
        return struct.pack("<H", len(tags)) + b"".join(tags) + struct.pack("<I", next_ifd_offset)

    header = b"II" + struct.pack("<H", 42) + struct.pack("<I", ifd_offset)
    main_ifd = _image_ifd(image_specs[0], next_ifd_offset=overview_ifd_offset)
    overview_ifd = _image_ifd(image_specs[1], next_ifd_offset=0)
    path.write_bytes(
        header
        + main_ifd
        + overview_ifd
        + b"".join(metadata_parts)
        + b"".join(tile_data_parts)
    )


def _geotiff_tile_size(length: int) -> int:
    if length <= 0:
        return 16
    return min(256, max(16, int(math.ceil(length / 16.0)) * 16))


def _float32_overview_rows(*, rows: list[list[float]], width: int, height: int) -> list[list[float]]:
    overview_width = max(1, int(math.ceil(width / 2.0)))
    overview_height = max(1, int(math.ceil(height / 2.0)))
    overview: list[list[float]] = []
    for overview_y in range(overview_height):
        output_row: list[float] = []
        for overview_x in range(overview_width):
            values: list[float] = []
            for src_y in range(overview_y * 2, min(overview_y * 2 + 2, height)):
                if src_y >= len(rows):
                    continue
                for src_x in range(overview_x * 2, min(overview_x * 2 + 2, width)):
                    if src_x < len(rows[src_y]):
                        values.append(float(rows[src_y][src_x]))
            output_row.append(sum(values) / len(values) if values else 0.0)
        overview.append(output_row)
    return overview


def _float32_tile_payloads(
    *,
    rows: list[list[float]],
    width: int,
    height: int,
    tile_width: int,
    tile_length: int,
) -> list[bytes]:
    payloads: list[bytes] = []
    for tile_y in range(0, height, tile_length):
        for tile_x in range(0, width, tile_width):
            values: list[float] = []
            for offset_y in range(tile_length):
                src_y = tile_y + offset_y
                for offset_x in range(tile_width):
                    src_x = tile_x + offset_x
                    if src_y < height and src_x < width and src_y < len(rows) and src_x < len(rows[src_y]):
                        values.append(float(rows[src_y][src_x]))
                    else:
                        values.append(0.0)
            payloads.append(struct.pack("<" + "f" * len(values), *values))
    return payloads or [struct.pack("<f", 0.0)]


def _footprint_land_cover_overlay_payload(
    *,
    rp_result: RPRunResult | None,
    rp_config_snapshot: dict[str, Any],
    site: object,
) -> dict[str, Any]:
    if rp_result is None:
        return {"artifact_type": "footprint_land_cover_overlay_v1", "status": "missing", "windows": [], "classes": []}
    footprint_config = dict(rp_config_snapshot.get("footprint", {}) if isinstance(rp_config_snapshot.get("footprint", {}), dict) else {})
    raw_land_cover_grid = footprint_config.get("land_cover_grid")
    legend = dict(footprint_config.get("land_cover_legend", {}) if isinstance(footprint_config.get("land_cover_legend", {}), dict) else {})
    raster = _load_land_cover_raster(footprint_config=footprint_config, rp_config_snapshot=rp_config_snapshot)
    latitude = _coerce_optional_float(_object_get(site, "latitude"))
    longitude = _coerce_optional_float(_object_get(site, "longitude"))
    default_land_cover = str(
        footprint_config.get("land_cover_default")
        or dict(rp_config_snapshot.get("project_context", {}) if isinstance(rp_config_snapshot.get("project_context", {}), dict) else {}).get("land_cover", "")
        or _object_get(site, "land_cover", "")
        or ""
    ).strip()
    windows: list[dict[str, Any]] = []
    aggregate: dict[str, float] = {}
    for window in rp_result.windows:
        diagnostics = dict(window.diagnostics or {})
        grid = dict(diagnostics.get("footprint_2d_grid", {}) or {})
        x, y, values = _footprint_grid_arrays(grid)
        if not values:
            continue
        rows = len(values)
        cols = min((len(row) for row in values if row), default=0)
        if rows <= 0 or cols <= 0:
            continue
        classification_source = "missing"
        class_totals: dict[str, float] = {}
        overlay_detail: dict[str, Any] = {}
        if raster and latitude is not None and longitude is not None:
            classification_source = "raster"
            class_totals, overlay_detail = _sample_land_cover_raster_for_footprint(
                raster=raster,
                x=x[:cols],
                y=y[:rows],
                values=[row[:cols] for row in values[:rows]],
                diagnostics=diagnostics,
                grid=grid,
                latitude=float(latitude),
                longitude=float(longitude),
                legend=legend,
            )
            if not class_totals:
                classification_source = "missing"
        if not class_totals:
            if _land_cover_grid_matches(raw_land_cover_grid, rows, cols):
                classification_source = "grid"
                for row_index, row in enumerate(values):
                    cover_row = raw_land_cover_grid[row_index]
                    for col_index, contribution in enumerate(row[:cols]):
                        cover_key = str(cover_row[col_index])
                        label = str(legend.get(cover_key, cover_key)).strip() or "unclassified"
                        class_totals[label] = class_totals.get(label, 0.0) + float(contribution)
            elif default_land_cover:
                classification_source = "site_default"
                label = str(legend.get(default_land_cover, default_land_cover)).strip() or "site_default"
                class_totals[label] = sum(float(value) for row in values for value in row[:cols])
            else:
                continue
        total = sum(max(value, 0.0) for value in class_totals.values())
        if total <= 0.0:
            continue
        normalized = [
            {
                "land_cover": label,
                "contribution": round(value, 10),
                "fraction": round(max(value, 0.0) / total, 10),
            }
            for label, value in sorted(class_totals.items(), key=lambda item: item[0])
        ]
        for row in normalized:
            aggregate[row["land_cover"]] = aggregate.get(row["land_cover"], 0.0) + float(row["contribution"])
        windows.append(
            {
                "window_id": window.window_id,
                "start_time": window.start_time.isoformat(),
                "end_time": window.end_time.isoformat(),
                "method": str(diagnostics.get("footprint_method", grid.get("method", ""))),
                "classification_source": classification_source,
                "class_count": len(normalized),
                "classes": normalized,
                "overlay_detail": overlay_detail,
            }
        )
    if not windows:
        has_footprint = any(
            isinstance(window.diagnostics, dict) and window.diagnostics.get("footprint_2d_grid")
            for window in rp_result.windows
        )
        return {
            "artifact_type": "footprint_land_cover_overlay_v1",
            "status": "missing_land_cover" if has_footprint else "missing_footprint_grid",
            "run_id": rp_result.run_id,
            "windows": [],
            "classes": [],
            "limitations": [
                "Provide footprint.land_cover_raster.path, footprint.land_cover_grid matching the 2D footprint grid shape, or a site/project land_cover default."
            ],
        }
    aggregate_total = sum(max(value, 0.0) for value in aggregate.values())
    classes = [
        {
            "land_cover": label,
            "contribution": round(value, 10),
            "fraction": round(max(value, 0.0) / aggregate_total, 10) if aggregate_total > 0 else 0.0,
        }
        for label, value in sorted(aggregate.items(), key=lambda item: item[0])
    ]
    dominant = max(classes, key=lambda item: float(item.get("fraction", 0.0))) if classes else {}
    classification_sources = sorted({str(window.get("classification_source", "")) for window in windows if window.get("classification_source")})
    return {
        "artifact_type": "footprint_land_cover_overlay_v1",
        "status": "ok",
        "run_id": rp_result.run_id,
        "created_at": rp_result.created_at.isoformat(),
        "classification_source": classification_sources[0] if len(classification_sources) == 1 else "mixed",
        "summary": {
            "window_count": len(windows),
            "class_count": len(classes),
            "dominant_class": str(dominant.get("land_cover", "")),
            "dominant_fraction": float(dominant.get("fraction", 0.0) or 0.0),
            "raster_source": raster.get("path", "") if raster else "",
            "raster_crs": raster.get("crs", "") if raster else "",
        },
        "classes": classes,
        "windows": windows,
        "provenance": (
            "Footprint contribution grid overlaid with configured land-cover raster, grid, or site default label."
        ),
        "limitations": [
            "Overlay summarizes footprint contribution by supplied classes; it is not a remote-sensing classifier.",
            "Raster sampling supports built-in EPSG:4326/EPSG:3857 lookup and optional rasterio/GDAL reprojection for other configured CRS values; validate cell alignment before publication-grade source-area attribution.",
        ],
    }


def _load_land_cover_raster(
    *,
    footprint_config: dict[str, Any],
    rp_config_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    raster_config = footprint_config.get("land_cover_raster") or footprint_config.get("land_cover_raster_path")
    if not raster_config:
        return None
    if isinstance(raster_config, dict):
        raw_path = str(raster_config.get("path") or raster_config.get("file") or "").strip()
        raster_crs = str(raster_config.get("crs", "EPSG:4326") or "EPSG:4326")
    else:
        raw_path = str(raster_config).strip()
        raster_crs = "EPSG:4326"
    if not raw_path:
        return None
    path = _resolve_config_path(raw_path, rp_config_snapshot)
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix in {".asc", ".txt"}:
        return _read_esri_ascii_land_cover(path=path, crs=raster_crs)
    if suffix == ".json":
        return _read_json_land_cover_raster(path=path, crs=raster_crs)
    if suffix in {".tif", ".tiff"}:
        return _read_geotiff_land_cover_metadata(path=path, fallback_crs=raster_crs)
    return None


def _resolve_config_path(raw_path: str, rp_config_snapshot: dict[str, Any]) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    project_context = dict(rp_config_snapshot.get("project_context", {}) if isinstance(rp_config_snapshot.get("project_context", {}), dict) else {})
    for base_key in ("workspace_root", "project_root", "data_root"):
        base = str(project_context.get(base_key, "") or "").strip()
        if base:
            candidate = Path(base) / path
            if candidate.exists():
                return candidate
    return path.resolve()


def _read_esri_ascii_land_cover(*, path: Path, crs: str) -> dict[str, Any] | None:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    header: dict[str, float] = {}
    data_start = 0
    for index, line in enumerate(lines[:12]):
        parts = line.split()
        if len(parts) < 2:
            break
        key = parts[0].lower()
        if key not in {"ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"}:
            data_start = index
            break
        try:
            header[key] = float(parts[1])
        except ValueError:
            return None
        data_start = index + 1
        if {"ncols", "nrows", "cellsize"}.issubset(header) and index >= 5:
            next_index = index + 1
            if next_index < len(lines):
                next_key = lines[next_index].split()[0].lower()
                if next_key not in {"nodata_value"}:
                    data_start = next_index
                    break
    try:
        ncols = int(header["ncols"])
        nrows = int(header["nrows"])
        cellsize = float(header["cellsize"])
    except (KeyError, ValueError):
        return None
    x_origin = float(header.get("xllcorner", header.get("xllcenter", 0.0) - cellsize / 2.0))
    y_origin = float(header.get("yllcorner", header.get("yllcenter", 0.0) - cellsize / 2.0))
    nodata = header.get("nodata_value")
    rows: list[list[str]] = []
    for line in lines[data_start : data_start + nrows]:
        values = line.split()
        if len(values) < ncols:
            return None
        rows.append([str(value) for value in values[:ncols]])
    if len(rows) != nrows:
        return None
    return {
        "format": "esri_ascii_grid",
        "path": str(path),
        "crs": crs,
        "ncols": ncols,
        "nrows": nrows,
        "xllcorner": x_origin,
        "yllcorner": y_origin,
        "cellsize": cellsize,
        "nodata_value": str(int(nodata)) if isinstance(nodata, float) and nodata.is_integer() else (str(nodata) if nodata is not None else ""),
        "rows": rows,
    }


def _read_json_land_cover_raster(*, path: Path, crs: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    rows = payload.get("rows") or payload.get("grid")
    if not isinstance(rows, list) or not rows:
        return None
    nrows = int(payload.get("nrows", len(rows)) or len(rows))
    ncols = int(payload.get("ncols", len(rows[0]) if isinstance(rows[0], list) else 0) or 0)
    if nrows <= 0 or ncols <= 0:
        return None
    normalized_rows: list[list[str]] = []
    for row in rows[:nrows]:
        if not isinstance(row, list) or len(row) < ncols:
            return None
        normalized_rows.append([str(value) for value in row[:ncols]])
    return {
        "format": "json_land_cover_grid",
        "path": str(path),
        "crs": str(payload.get("crs", crs) or crs),
        "ncols": ncols,
        "nrows": nrows,
        "xllcorner": float(payload.get("xllcorner", payload.get("west", 0.0)) or 0.0),
        "yllcorner": float(payload.get("yllcorner", payload.get("south", 0.0)) or 0.0),
        "cellsize": float(payload.get("cellsize", 0.0) or 0.0),
        "nodata_value": str(payload.get("nodata_value", "")),
        "rows": normalized_rows,
    }


def _read_geotiff_land_cover_metadata(*, path: Path, fallback_crs: str) -> dict[str, Any] | None:
    import subprocess
    import sys

    script = r'''
import json
import math
import os
import sys

path = sys.argv[1]
fallback_crs = sys.argv[2] if len(sys.argv) > 2 else "EPSG:4326"
try:
    import rasterio
except Exception as exc:
    print(json.dumps({
        "status": "not_available",
        "package": "rasterio",
        "error": str(exc),
        "message": "Install rasterio/GDAL to read GeoTIFF land-cover rasters.",
    }))
    sys.stdout.flush()
    os._exit(0)

try:
    with rasterio.open(path) as dataset:
        transform = dataset.transform
        bounds = dataset.bounds
        pixel_width = math.sqrt(float(transform.a) ** 2 + float(transform.d) ** 2)
        pixel_height = math.sqrt(float(transform.b) ** 2 + float(transform.e) ** 2)
        nodata = dataset.nodata
        crs = str(dataset.crs) if dataset.crs is not None else fallback_crs
        print(json.dumps({
            "status": "ok",
            "package": "rasterio",
            "rasterio_version": str(getattr(rasterio, "__version__", "")),
            "gdal_version": str(getattr(rasterio, "__gdal_version__", "")),
            "driver": str(dataset.driver),
            "crs": crs,
            "width": int(dataset.width),
            "height": int(dataset.height),
            "count": int(dataset.count),
            "dtype": str(dataset.dtypes[0]) if dataset.dtypes else "",
            "nodata_value": nodata,
            "transform": [
                float(transform.a),
                float(transform.b),
                float(transform.c),
                float(transform.d),
                float(transform.e),
                float(transform.f),
            ],
            "cellsize_x": pixel_width,
            "cellsize_y": pixel_height,
            "rotated_transform": bool(abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12),
            "native_extent": {
                "min_lon": float(bounds.left),
                "min_lat": float(bounds.bottom),
                "max_lon": float(bounds.right),
                "max_lat": float(bounds.top),
            },
        }))
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "package": "rasterio",
        "path": path,
        "error": str(exc),
    }))
sys.stdout.flush()
os._exit(0)
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path), str(fallback_crs or "EPSG:4326")],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "format": "geotiff_land_cover",
            "path": str(path),
            "crs": fallback_crs,
            "load_status": "error",
            "load_error": str(exc),
            "rows": [],
        }
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {
            "format": "geotiff_land_cover",
            "path": str(path),
            "crs": fallback_crs,
            "load_status": "error",
            "load_error": (completed.stderr or "").strip() or f"rasterio metadata reader exited {completed.returncode}",
            "rows": [],
        }
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return {
            "format": "geotiff_land_cover",
            "path": str(path),
            "crs": fallback_crs,
            "load_status": "error",
            "load_error": str(exc),
            "rows": [],
        }
    detail = dict(payload) if isinstance(payload, dict) else {"status": "error"}
    if detail.get("status") != "ok":
        return {
            "format": "geotiff_land_cover",
            "path": str(path),
            "crs": fallback_crs,
            "load_status": str(detail.get("status", "error")),
            "load_error": str(detail.get("error", detail.get("message", ""))),
            "metadata_reader": detail,
            "rows": [],
        }
    nodata = detail.get("nodata_value")
    return {
        "format": "geotiff_land_cover",
        "path": str(path),
        "crs": str(detail.get("crs") or fallback_crs or "EPSG:4326"),
        "ncols": int(detail.get("width", 0) or 0),
        "nrows": int(detail.get("height", 0) or 0),
        "xllcorner": float(dict(detail.get("native_extent", {}) or {}).get("min_lon", 0.0) or 0.0),
        "yllcorner": float(dict(detail.get("native_extent", {}) or {}).get("min_lat", 0.0) or 0.0),
        "cellsize": float(detail.get("cellsize_x", 0.0) or 0.0),
        "cellsize_x": float(detail.get("cellsize_x", 0.0) or 0.0),
        "cellsize_y": float(detail.get("cellsize_y", 0.0) or 0.0),
        "nodata_value": _format_raster_value(nodata) if nodata is not None else "",
        "rows": [],
        "load_status": "ok",
        "native_extent": dict(detail.get("native_extent", {}) or {}),
        "native_extent_source": "geotiff_bounds",
        "metadata_reader": {
            "package": "rasterio",
            "rasterio_version": str(detail.get("rasterio_version", "")),
            "gdal_version": str(detail.get("gdal_version", "")),
            "driver": str(detail.get("driver", "")),
            "count": int(detail.get("count", 0) or 0),
            "dtype": str(detail.get("dtype", "")),
            "transform": list(detail.get("transform", []) or []),
            "rotated_transform": bool(detail.get("rotated_transform", False)),
        },
    }


def _sample_land_cover_raster_for_footprint(
    *,
    raster: dict[str, Any],
    x: list[float],
    y: list[float],
    values: list[list[float]],
    diagnostics: dict[str, Any],
    grid: dict[str, Any],
    latitude: float,
    longitude: float,
    legend: dict[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    load_status = str(raster.get("load_status", "ok") or "ok")
    if load_status != "ok":
        return {}, {
            "status": load_status,
            "raster_path": str(raster.get("path", "")),
            "raster_format": str(raster.get("format", "")),
            "raster_crs": str(raster.get("crs", "")),
            "load_error": str(raster.get("load_error", "")),
        }
    rows = list(raster.get("rows", []) or [])
    ncols = int(raster.get("ncols", 0) or 0)
    nrows = int(raster.get("nrows", 0) or 0)
    cellsize_x = float(raster.get("cellsize_x", raster.get("cellsize", 0.0)) or 0.0)
    cellsize_y = float(raster.get("cellsize_y", raster.get("cellsize", 0.0)) or 0.0)
    xll = float(raster.get("xllcorner", 0.0) or 0.0)
    yll = float(raster.get("yllcorner", 0.0) or 0.0)
    nodata = str(raster.get("nodata_value", "") or "")
    raster_format = str(raster.get("format", ""))
    is_geotiff = raster_format == "geotiff_land_cover"
    if ncols <= 0 or nrows <= 0 or (not is_geotiff and (not rows or cellsize_x <= 0 or cellsize_y <= 0)):
        return {}, {"status": "invalid_raster_geometry", "raster_path": raster.get("path", "")}
    class_totals: dict[str, float] = {}
    sampled = 0
    unsampled = 0
    bearing_deg = float(diagnostics.get("footprint_bearing_deg", grid.get("bearing_deg", 0.0)) or 0.0)
    raster_crs = _normalize_raster_crs(str(raster.get("crs", "") or "EPSG:4326"))
    footprint_points: list[tuple[float, float, float]] = []
    for y_index, row in enumerate(values):
        if y_index >= len(y):
            continue
        for x_index, contribution in enumerate(row):
            if x_index >= len(x):
                continue
            lon, lat = _local_to_lonlat(
                latitude=latitude,
                longitude=longitude,
                x_m=float(x[x_index]),
                y_m=float(y[y_index]),
                bearing_deg=bearing_deg,
            )
            footprint_points.append((float(lon), float(lat), float(contribution)))
    raster_points, transform_detail = _transform_coordinates_between_crs(
        points=[(lon, lat) for lon, lat, _ in footprint_points],
        src_crs="EPSG:4326",
        dst_crs=raster_crs,
    )
    unsupported_crs = 0
    sampling_error_status = ""
    if transform_detail.get("status") != "ok" or len(raster_points) != len(footprint_points):
        unsupported_crs = len(footprint_points)
    elif is_geotiff:
        sampled_values, sampling_detail = _sample_geotiff_land_cover_values(
            path=Path(str(raster.get("path", ""))),
            points=raster_points,
        )
        if sampling_detail.get("status") != "ok" or len(sampled_values) != len(footprint_points):
            sampling_error_status = str(sampling_detail.get("status", "raster_sampling_error") or "raster_sampling_error")
            transform_detail = {
                **transform_detail,
                "raster_sampling_detail": sampling_detail,
            }
        else:
            for cover_key, (_, _, contribution) in zip(sampled_values, footprint_points):
                if cover_key is None:
                    unsampled += 1
                    continue
                normalized_key = str(cover_key)
                if nodata and normalized_key == nodata:
                    unsampled += 1
                    continue
                label = str(legend.get(normalized_key, normalized_key)).strip() or "unclassified"
                class_totals[label] = class_totals.get(label, 0.0) + float(contribution)
                sampled += 1
            transform_detail = {
                **transform_detail,
                "raster_sampling_detail": sampling_detail,
            }
    else:
        for (raster_x, raster_y), (_, _, contribution) in zip(raster_points, footprint_points):
            col = int(math.floor((float(raster_x) - xll) / cellsize_x))
            row_from_bottom = int(math.floor((float(raster_y) - yll) / cellsize_y))
            row_index = nrows - 1 - row_from_bottom
            if row_index < 0 or row_index >= nrows or col < 0 or col >= ncols:
                unsampled += 1
                continue
            cover_key = str(rows[row_index][col])
            if nodata and cover_key == nodata:
                unsampled += 1
                continue
            label = str(legend.get(cover_key, cover_key)).strip() or "unclassified"
            class_totals[label] = class_totals.get(label, 0.0) + float(contribution)
            sampled += 1
    status = "ok" if sampled else "no_overlap"
    if unsupported_crs:
        status = "unsupported_crs"
    if sampling_error_status:
        status = sampling_error_status
    return class_totals, {
        "status": status,
        "raster_path": str(raster.get("path", "")),
        "raster_format": raster_format,
        "raster_crs": str(raster.get("crs", "")),
        "coordinate_transform": str(transform_detail.get("transform", _raster_crs_transform_label(raster_crs))),
        "coordinate_transform_detail": transform_detail,
        "raster_sampling_engine": "rasterio" if is_geotiff else "in_memory_grid",
        "sampled_cell_count": sampled,
        "unsampled_cell_count": unsampled,
        "unsupported_crs_cell_count": unsupported_crs,
    }


def _sample_geotiff_land_cover_values(
    *,
    path: Path,
    points: list[tuple[float, float]],
) -> tuple[list[str | None], dict[str, Any]]:
    import subprocess
    import sys

    script = r'''
import json
import os
import sys

path = sys.argv[1]
payload = json.loads(sys.stdin.read() or "{}")
points = payload.get("points", [])
try:
    import rasterio
    from rasterio.windows import Window
except Exception as exc:
    print(json.dumps({
        "status": "not_available",
        "package": "rasterio",
        "error": str(exc),
        "message": "Install rasterio/GDAL to sample GeoTIFF land-cover rasters.",
    }))
    sys.stdout.flush()
    os._exit(0)

def format_value(value):
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)

try:
    with rasterio.open(path) as dataset:
        transform = dataset.transform
        nodata = dataset.nodata
        values = []
        for point in points:
            if not isinstance(point, list) or len(point) < 2:
                values.append(None)
                continue
            try:
                x = float(point[0])
                y = float(point[1])
                row, col = dataset.index(x, y)
            except Exception:
                values.append(None)
                continue
            if row < 0 or col < 0 or row >= dataset.height or col >= dataset.width:
                values.append(None)
                continue
            sample = dataset.read(1, window=Window(col, row, 1, 1), masked=True)
            value = sample[0, 0]
            if hasattr(value, "mask") and bool(value.mask):
                values.append(None)
                continue
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = None
            if nodata is not None and numeric_value is not None and numeric_value == float(nodata):
                values.append(None)
                continue
            values.append(format_value(value))
        print(json.dumps({
            "status": "ok",
            "package": "rasterio",
            "point_count": len(points),
            "sampled_value_count": sum(1 for value in values if value is not None),
            "unsampled_value_count": sum(1 for value in values if value is None),
            "rotated_transform": bool(abs(float(transform.b)) > 1e-12 or abs(float(transform.d)) > 1e-12),
            "values": values,
        }))
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "package": "rasterio",
        "path": path,
        "error": str(exc),
    }))
sys.stdout.flush()
os._exit(0)
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            input=json.dumps({"points": [[float(x_value), float(y_value)] for x_value, y_value in points]}),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "path": str(path),
            "point_count": len(points),
            "error": str(exc),
        }
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "path": str(path),
            "point_count": len(points),
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip(),
        }
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "path": str(path),
            "point_count": len(points),
            "error": str(exc),
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
        }
    detail = dict(payload) if isinstance(payload, dict) else {"status": "error"}
    values = detail.pop("values", [])
    detail.update({"engine": "rasterio", "path": str(path), "point_count": len(points)})
    if detail.get("status") != "ok" or not isinstance(values, list):
        return [], detail
    normalized: list[str | None] = []
    for value in values:
        normalized.append(None if value is None else _format_raster_value(value))
    return normalized, detail


def _format_raster_value(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def _footprint_gis_validation_payload(
    *,
    rp_result: RPRunResult | None,
    rp_config_snapshot: dict[str, Any],
    site: object,
    footprint_geojson_path: Path | None,
    footprint_geotiff_path: Path | None,
    footprint_land_cover_overlay_path: Path | None,
) -> dict[str, Any]:
    if rp_result is None:
        return {"artifact_type": "footprint_gis_validation_v1", "status": "missing", "checks": []}
    footprint_config = dict(rp_config_snapshot.get("footprint", {}) if isinstance(rp_config_snapshot.get("footprint", {}), dict) else {})
    raster = _load_land_cover_raster(footprint_config=footprint_config, rp_config_snapshot=rp_config_snapshot)
    if not any([footprint_geojson_path, footprint_geotiff_path, footprint_land_cover_overlay_path, raster]):
        return {"artifact_type": "footprint_gis_validation_v1", "status": "missing", "checks": []}
    bbox = _footprint_bbox_wgs84(rp_result=rp_result, site=site)
    if not bbox:
        has_footprint = any(
            isinstance(window.diagnostics, dict) and window.diagnostics.get("footprint_2d_grid")
            for window in rp_result.windows
        )
        return {
            "artifact_type": "footprint_gis_validation_v1",
            "status": "missing_site_coordinates" if has_footprint else "missing_footprint_grid",
            "run_id": rp_result.run_id,
            "checks": [],
            "limitations": ["Site latitude/longitude and footprint_2d_grid are required for map-grade validation."],
        }
    geojson_summary = _geojson_artifact_validation(footprint_geojson_path)
    geotiff_summary = _geotiff_artifact_validation(footprint_geotiff_path)
    overlay_summary = _overlay_artifact_validation(footprint_land_cover_overlay_path)
    raster_summary = _raster_artifact_validation(raster=raster, footprint_bbox=bbox)
    checks = [
        {
            "name": "footprint_extent_wgs84",
            "status": "ok",
            "detail": bbox,
        },
        {
            "name": "geojson_artifact",
            "status": geojson_summary.get("status", "missing"),
            "detail": geojson_summary,
        },
        {
            "name": "geotiff_artifact",
            "status": geotiff_summary.get("status", "missing"),
            "detail": geotiff_summary,
        },
        {
            "name": "geotiff_external_reader",
            "status": dict(geotiff_summary.get("external_reader_validation", {}) or {}).get("status", "not_available"),
            "detail": dict(geotiff_summary.get("external_reader_validation", {}) or {}),
        },
        {
            "name": "geotiff_cog_validator",
            "status": dict(geotiff_summary.get("cog_validator_validation", {}) or {}).get("status", "not_available"),
            "detail": dict(geotiff_summary.get("cog_validator_validation", {}) or {}),
        },
        {
            "name": "land_cover_overlay",
            "status": overlay_summary.get("status", "missing"),
            "detail": overlay_summary,
        },
        {
            "name": "land_cover_raster",
            "status": raster_summary.get("status", "not_configured"),
            "detail": raster_summary,
        },
        {
            "name": "cog_readiness",
            "status": geotiff_summary.get("cog_readiness", "not_available"),
            "detail": {
                "current_layout": geotiff_summary.get("layout", "not_available"),
                "required_for_cog": ["tiled GeoTIFF", "internal overviews", "HTTP range-friendly IFD ordering"],
            },
        },
    ]
    fatal_statuses = {"invalid_tiff", "missing_required_tags", "missing_file", "unsupported_crs", "no_overlap"}
    warning_statuses = {
        "not_cog_single_strip",
        "tiled_no_overviews",
        "candidate_with_layout_warnings",
        "missing",
        "invalid",
        "not_configured",
        "partial_overlap",
        "not_available",
    }
    fatal = any(str(check.get("status")) in fatal_statuses for check in checks)
    warning = any(str(check.get("status")) in warning_statuses for check in checks)
    status = "warning" if fatal else ("ok_with_limitations" if warning else "ok")
    return {
        "artifact_type": "footprint_gis_validation_v1",
        "status": status,
        "run_id": rp_result.run_id,
        "created_at": rp_result.created_at.isoformat(),
        "site": {
            "latitude": _coerce_optional_float(_object_get(site, "latitude")),
            "longitude": _coerce_optional_float(_object_get(site, "longitude")),
            "station_code": str(_object_get(site, "station_code", "")),
        },
        "footprint_extent_wgs84": bbox,
        "geojson": geojson_summary,
        "geotiff": geotiff_summary,
        "land_cover_overlay": overlay_summary,
        "land_cover_raster": raster_summary,
        "checks": checks,
        "provenance": "GIS validation is derived from exported footprint artifacts and configured land-cover raster metadata.",
        "limitations": [
            "GeoTIFF validation checks baseline tags and WGS84 georeferencing; it does not replace a full GDAL validation run.",
            "COG readiness is intentionally reported separately because the current diagnostic GeoTIFF is single-strip and not cloud optimized.",
            "Raster overlap uses built-in EPSG:4326/EPSG:3857 transforms and isolated rasterio/GDAL transforms for other configured CRS values.",
        ],
    }


def _footprint_bbox_wgs84(*, rp_result: RPRunResult, site: object) -> dict[str, Any]:
    latitude = _coerce_optional_float(_object_get(site, "latitude"))
    longitude = _coerce_optional_float(_object_get(site, "longitude"))
    if latitude is None or longitude is None:
        return {}
    lon_values: list[float] = []
    lat_values: list[float] = []
    window_count = 0
    for window in rp_result.windows:
        diagnostics = dict(window.diagnostics or {})
        grid = dict(diagnostics.get("footprint_2d_grid", {}) or {})
        x, y, values = _footprint_grid_arrays(grid)
        if not x or not y or not values:
            continue
        window_count += 1
        dx = _coordinate_spacing_m(x)
        dy = _coordinate_spacing_m(y)
        bearing_deg = float(diagnostics.get("footprint_bearing_deg", grid.get("bearing_deg", 0.0)) or 0.0)
        for y_index, row in enumerate(values):
            if y_index >= len(y):
                continue
            for x_index, _ in enumerate(row):
                if x_index >= len(x):
                    continue
                polygon = _local_cell_to_lonlat_polygon(
                    latitude=float(latitude),
                    longitude=float(longitude),
                    center_x_m=x[x_index],
                    center_y_m=y[y_index],
                    dx_m=dx,
                    dy_m=dy,
                    bearing_deg=bearing_deg,
                )
                lon_values.extend(float(point[0]) for point in polygon)
                lat_values.extend(float(point[1]) for point in polygon)
    if not lon_values or not lat_values:
        return {}
    return {
        "min_lon": min(lon_values),
        "min_lat": min(lat_values),
        "max_lon": max(lon_values),
        "max_lat": max(lat_values),
        "window_count": window_count,
        "crs": "EPSG:4326",
    }


def _geojson_artifact_validation(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "missing", "path": ""}
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "invalid_json", "path": str(path), "error": str(exc)}
    return {
        "status": str(payload.get("status", "unknown")),
        "path": str(path),
        "artifact_type": str(payload.get("artifact_type", "")),
        "coordinate_reference_system": str(payload.get("coordinate_reference_system", "")),
        "feature_count": int(payload.get("feature_count", 0) or 0),
    }


def _geotiff_artifact_validation(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "missing", "path": "", "cog_readiness": "not_available"}
    if not path.exists():
        return {"status": "missing_file", "path": str(path), "cog_readiness": "not_available"}
    try:
        tags = _parse_tiff_tag_ids(path)
    except (OSError, struct.error, ValueError) as exc:
        return {"status": "invalid_tiff", "path": str(path), "error": str(exc), "cog_readiness": "not_available"}
    ifds = list(tags.get("ifds", []) or [])
    first_ifd = dict(ifds[0] if ifds else {})
    entries = dict(first_ifd.get("entries", {}) or tags.get("entries", {}) or {})
    tag_ids = set(first_ifd.get("tag_ids", set()) or tags.get("tag_ids", set()))
    tiled = {322, 323, 324, 325}.issubset(tag_ids)
    base_required = {256, 257, 258, 259, 262, 33550, 33922, 34735}
    storage_required = {322, 323, 324, 325} if tiled else {273, 279}
    missing_tags = sorted(base_required.union(storage_required).difference(tag_ids))
    has_internal_overviews = len(ifds) > 1 or bool(tags.get("next_ifd_offset")) or 330 in tag_ids
    reduced_overview_count = sum(
        1
        for ifd in ifds[1:]
        if int(dict(dict(ifd).get("entries", {}) or {}).get(254, {}).get("value", 0) or 0) & 1
    )
    range_summary = _tiff_range_readiness(tags)
    if tiled and has_internal_overviews and range_summary.get("status") == "ok":
        cog_readiness = "candidate"
    elif tiled:
        cog_readiness = "candidate_with_layout_warnings" if has_internal_overviews else "tiled_no_overviews"
    else:
        cog_readiness = "not_cog_single_strip"
    external_reader_validation = _optional_rasterio_geotiff_validation(path)
    cog_validator_validation = _optional_cog_validator_validation(path)
    return {
        "status": "ok" if not missing_tags and tags.get("magic_ok") else "missing_required_tags",
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "magic_ok": bool(tags.get("magic_ok")),
        "tag_ids": sorted(tag_ids),
        "missing_required_tags": missing_tags,
        "has_model_pixel_scale": 33550 in tags.get("tag_ids", set()),
        "has_model_tiepoint": 33922 in tags.get("tag_ids", set()),
        "has_geo_key_directory": 34735 in tags.get("tag_ids", set()),
        "layout": "tiled" if tiled else "single_strip",
        "tile_width": dict(entries.get(322, {}) or {}).get("value", 0),
        "tile_length": dict(entries.get(323, {}) or {}).get("value", 0),
        "tile_count": dict(entries.get(324, {}) or {}).get("count", 0) if tiled else 0,
        "has_internal_overviews": has_internal_overviews,
        "overview_ifd_count": max(len(ifds) - 1, 0),
        "reduced_overview_count": reduced_overview_count,
        "cog_readiness": cog_readiness,
        "range_readiness": range_summary.get("status", "unknown"),
        "range_validation": range_summary,
        "external_reader_validation": external_reader_validation,
        "cog_validator_validation": cog_validator_validation,
    }


def _optional_cog_validator_validation(path: Path) -> dict[str, Any]:
    # rio-cogeo is optional and loaded only in a child process for the same
    # GDAL/Windows teardown-safety reason as rasterio smoke validation.
    import subprocess
    import sys

    script = r'''
import json
import os
import sys

path = sys.argv[1]
try:
    import rio_cogeo
    from rio_cogeo.cogeo import cog_validate
except Exception as exc:
    print(json.dumps({
        "status": "not_available",
        "package": "rio-cogeo",
        "error": str(exc),
        "message": "Install rio-cogeo to run full COG validator checks.",
    }))
    sys.stdout.flush()
    os._exit(0)

try:
    valid, errors, warnings = cog_validate(path, strict=True, quiet=True)
    print(json.dumps({
        "status": "valid" if bool(valid) else "invalid",
        "package": "rio-cogeo",
        "rio_cogeo_version": str(getattr(rio_cogeo, "__version__", "")),
        "strict": True,
        "valid": bool(valid),
        "errors": [str(error) for error in errors],
        "warnings": [str(warning) for warning in warnings],
    }))
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "package": "rio-cogeo",
        "path": path,
        "error": str(exc),
    }))
sys.stdout.flush()
os._exit(0)
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "error",
            "package": "rio-cogeo",
            "path": str(path),
            "error": str(exc),
        }
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {
            "status": "error",
            "package": "rio-cogeo",
            "path": str(path),
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip(),
        }
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "package": "rio-cogeo",
            "path": str(path),
            "error": str(exc),
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
        }
    return dict(payload) if isinstance(payload, dict) else {"status": "error", "package": "rio-cogeo", "path": str(path)}


def _optional_rasterio_geotiff_validation(path: Path) -> dict[str, Any]:
    # Run GDAL/rasterio in a short-lived child process. On Windows, importing GDAL
    # in the pytest/main process can trigger native cleanup faults at interpreter exit.
    import subprocess
    import sys

    script = r'''
import json
import os
import sys

path = sys.argv[1]
try:
    import rasterio
except Exception as exc:
    print(json.dumps({
        "status": "not_available",
        "package": "rasterio",
        "error": str(exc),
        "message": "Install rasterio/GDAL to run external GeoTIFF reader validation.",
    }))
    sys.stdout.flush()
    os._exit(0)

try:
    with rasterio.open(path) as dataset:
        overviews = list(dataset.overviews(1)) if dataset.count >= 1 else []
        block_shapes = [list(shape) for shape in list(dataset.block_shapes or [])]
        bounds = dataset.bounds
        checksum = int(dataset.checksum(1)) if dataset.count >= 1 else 0
        data_sum = None
        if dataset.count >= 1 and int(dataset.width) * int(dataset.height) <= 1_000_000:
            band = dataset.read(1)
            data_sum = float(band.sum())
        payload = {
            "status": "ok",
            "package": "rasterio",
            "rasterio_version": str(getattr(rasterio, "__version__", "")),
            "gdal_version": str(getattr(rasterio, "__gdal_version__", "")),
            "driver": str(dataset.driver),
            "crs": str(dataset.crs) if dataset.crs is not None else "",
            "width": int(dataset.width),
            "height": int(dataset.height),
            "count": int(dataset.count),
            "dtypes": [str(dtype) for dtype in dataset.dtypes],
            "block_shapes": block_shapes,
            "overviews_band1": overviews,
            "bounds": {
                "left": float(bounds.left),
                "bottom": float(bounds.bottom),
                "right": float(bounds.right),
                "top": float(bounds.top),
            },
            "checksum_band1": checksum,
            "data_sum_band1": data_sum,
            "read_status": "ok",
        }
except Exception as exc:
    payload = {
        "status": "error",
        "package": "rasterio",
        "path": path,
        "error": str(exc),
    }

print(json.dumps(payload))
sys.stdout.flush()
os._exit(0)
'''
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "error",
            "package": "rasterio",
            "path": str(path),
            "error": str(exc),
        }
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {
            "status": "error",
            "package": "rasterio",
            "path": str(path),
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip(),
        }
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "package": "rasterio",
            "path": str(path),
            "error": str(exc),
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
        }
    return dict(payload) if isinstance(payload, dict) else {"status": "error", "package": "rasterio", "path": str(path)}


def _parse_tiff_tag_ids(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 10:
        raise ValueError("TIFF file is too small")
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError("Unsupported TIFF byte order")
    magic = struct.unpack(endian + "H", data[2:4])[0]
    ifd_offset = struct.unpack(endian + "I", data[4:8])[0]
    if ifd_offset + 2 > len(data):
        raise ValueError("Invalid TIFF IFD offset")
    tag_ids: set[int] = set()
    ifds: list[dict[str, Any]] = []
    visited_offsets: set[int] = set()
    current_ifd_offset = ifd_offset
    while current_ifd_offset and current_ifd_offset not in visited_offsets:
        visited_offsets.add(current_ifd_offset)
        if current_ifd_offset + 2 > len(data):
            raise ValueError("Invalid TIFF IFD offset")
        tag_count = struct.unpack(endian + "H", data[current_ifd_offset : current_ifd_offset + 2])[0]
        local_tag_ids: set[int] = set()
        entries: dict[int, dict[str, Any]] = {}
        cursor = current_ifd_offset + 2
        for _ in range(tag_count):
            if cursor + 12 > len(data):
                raise ValueError("Truncated TIFF IFD entry")
            tag_id, tag_type, count = struct.unpack(endian + "HHI", data[cursor : cursor + 8])
            raw_value = data[cursor + 8 : cursor + 12]
            value_or_offset = struct.unpack(endian + "I", raw_value)[0]
            values, external_value_offset, byte_size = _read_tiff_entry_values(
                data=data,
                endian=endian,
                tag_type=tag_type,
                count=count,
                raw_value=raw_value,
            )
            value = values[0] if len(values) == 1 else None
            tag_ids.add(tag_id)
            local_tag_ids.add(tag_id)
            entries[tag_id] = {
                "type": tag_type,
                "count": count,
                "value": value,
                "values": values,
                "value_or_offset": value_or_offset,
                "external_value_offset": external_value_offset,
                "external_byte_size": byte_size if external_value_offset else 0,
            }
            cursor += 12
        next_ifd_offset = 0
        if cursor + 4 <= len(data):
            next_ifd_offset = struct.unpack(endian + "I", data[cursor : cursor + 4])[0]
        ifds.append(
            {
                "offset": current_ifd_offset,
                "tag_count": tag_count,
                "tag_ids": local_tag_ids,
                "entries": entries,
                "next_ifd_offset": next_ifd_offset,
                "ifd_end_offset": cursor + 4,
            }
        )
        current_ifd_offset = next_ifd_offset
    first_entries = dict(ifds[0].get("entries", {}) if ifds else {})
    return {
        "magic_ok": magic == 42,
        "tag_ids": tag_ids,
        "entries": first_entries,
        "next_ifd_offset": ifds[0].get("next_ifd_offset", 0) if ifds else 0,
        "ifds": ifds,
        "file_size": len(data),
    }


def _read_tiff_entry_values(
    *,
    data: bytes,
    endian: str,
    tag_type: int,
    count: int,
    raw_value: bytes,
) -> tuple[list[Any], int, int]:
    type_map = {
        1: ("B", 1),
        2: ("c", 1),
        3: ("H", 2),
        4: ("I", 4),
        12: ("d", 8),
    }
    if tag_type not in type_map or count <= 0:
        return [], 0, 0
    fmt_code, item_size = type_map[tag_type]
    byte_size = int(count) * item_size
    external_value_offset = 0
    if byte_size <= 4:
        payload = raw_value[:byte_size]
    else:
        external_value_offset = struct.unpack(endian + "I", raw_value)[0]
        if external_value_offset + byte_size > len(data):
            return [], external_value_offset, byte_size
        payload = data[external_value_offset : external_value_offset + byte_size]
    if tag_type == 2:
        return [payload.rstrip(b"\x00").decode("ascii", errors="replace")], external_value_offset, byte_size
    values = list(struct.unpack(endian + fmt_code * int(count), payload))
    return values, external_value_offset, byte_size


def _tiff_range_readiness(tags: dict[str, Any]) -> dict[str, Any]:
    ifds = list(tags.get("ifds", []) or [])
    if not ifds:
        return {"status": "missing_ifd_chain"}
    file_size = int(tags.get("file_size", 0) or 0)
    ifd_offsets = [int(ifd.get("offset", 0) or 0) for ifd in ifds]
    ifd_offsets_monotonic = all(ifd_offsets[index] > ifd_offsets[index - 1] for index in range(1, len(ifd_offsets)))
    metadata_end_offset = max(int(ifd.get("ifd_end_offset", 0) or 0) for ifd in ifds)
    tile_ranges: list[dict[str, Any]] = []
    reduced_image_count = 0
    for ifd_index, ifd in enumerate(ifds):
        entries = dict(ifd.get("entries", {}) or {})
        for entry in entries.values():
            external_offset = int(dict(entry).get("external_value_offset", 0) or 0)
            external_size = int(dict(entry).get("external_byte_size", 0) or 0)
            if external_offset and external_size:
                metadata_end_offset = max(metadata_end_offset, external_offset + external_size)
        if int(dict(entries.get(254, {}) or {}).get("value", 0) or 0) & 1:
            reduced_image_count += 1
        tile_offsets = [int(value) for value in list(dict(entries.get(324, {}) or {}).get("values", []) or [])]
        tile_byte_counts = [int(value) for value in list(dict(entries.get(325, {}) or {}).get("values", []) or [])]
        if not tile_offsets or len(tile_offsets) != len(tile_byte_counts):
            return {"status": "missing_tile_arrays", "ifd_count": len(ifds)}
        for tile_index, (offset, byte_count) in enumerate(zip(tile_offsets, tile_byte_counts)):
            tile_ranges.append(
                {
                    "ifd_index": ifd_index,
                    "tile_index": tile_index,
                    "offset": offset,
                    "byte_count": byte_count,
                    "end_offset": offset + byte_count,
                }
            )
    if not tile_ranges:
        return {"status": "missing_tile_data", "ifd_count": len(ifds)}
    first_tile_offset = min(int(item["offset"]) for item in tile_ranges)
    tile_data_after_metadata = first_tile_offset >= metadata_end_offset
    tile_offsets_monotonic = all(
        int(tile_ranges[index]["offset"]) >= int(tile_ranges[index - 1]["end_offset"])
        for index in range(1, len(tile_ranges))
    )
    tile_ranges_in_file = all(
        int(item["offset"]) >= 0 and int(item["end_offset"]) <= file_size and int(item["byte_count"]) > 0
        for item in tile_ranges
    )
    status = "ok"
    if not ifd_offsets_monotonic:
        status = "ifd_offsets_not_monotonic"
    elif not tile_data_after_metadata:
        status = "tile_data_before_metadata"
    elif not tile_offsets_monotonic:
        status = "tile_offsets_not_monotonic"
    elif not tile_ranges_in_file:
        status = "tile_ranges_out_of_file"
    elif len(ifds) > 1 and reduced_image_count < len(ifds) - 1:
        status = "overview_ifd_not_marked_reduced"
    return {
        "status": status,
        "ifd_count": len(ifds),
        "ifd_offsets": ifd_offsets,
        "ifd_offsets_monotonic": ifd_offsets_monotonic,
        "metadata_end_offset": metadata_end_offset,
        "first_tile_offset": first_tile_offset,
        "tile_data_after_metadata": tile_data_after_metadata,
        "tile_offsets_monotonic": tile_offsets_monotonic,
        "tile_ranges_in_file": tile_ranges_in_file,
        "tile_range_count": len(tile_ranges),
        "reduced_image_count": reduced_image_count,
    }


def _overlay_artifact_validation(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "missing", "path": ""}
    if not path.exists():
        return {"status": "missing_file", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "invalid_json", "path": str(path), "error": str(exc)}
    summary = dict(payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {})
    return {
        "status": str(payload.get("status", "unknown")),
        "path": str(path),
        "classification_source": str(payload.get("classification_source", "")),
        "class_count": int(summary.get("class_count", 0) or 0),
        "dominant_class": str(summary.get("dominant_class", "")),
    }


def _raster_artifact_validation(*, raster: dict[str, Any] | None, footprint_bbox: dict[str, Any]) -> dict[str, Any]:
    if not raster:
        return {"status": "not_configured"}
    load_status = str(raster.get("load_status", "ok") or "ok")
    if load_status != "ok":
        return {
            "status": load_status,
            "path": str(raster.get("path", "")),
            "format": str(raster.get("format", "")),
            "crs": _normalize_raster_crs(str(raster.get("crs", "") or "")),
            "message": str(raster.get("load_error", "")),
            "metadata_reader": dict(raster.get("metadata_reader", {}) if isinstance(raster.get("metadata_reader", {}), dict) else {}),
        }
    raster_native_bbox = _land_cover_raster_native_bbox(raster)
    crs = _normalize_raster_crs(str(raster.get("crs", "") or ""))
    raster_bbox, transform_detail = _land_cover_raster_bbox_wgs84_with_detail(raster)
    if not raster_bbox:
        return {
            "status": "unsupported_crs",
            "path": str(raster.get("path", "")),
            "crs": crs,
            "native_extent": raster_native_bbox,
            "coordinate_transform": _raster_crs_transform_label(crs),
            "coordinate_transform_detail": transform_detail,
            "message": "Install rasterio/GDAL or use EPSG:4326/EPSG:3857 to validate this land-cover raster CRS.",
        }
    overlap = _bbox_overlap_fraction(footprint_bbox, raster_bbox)
    if overlap <= 0.0:
        status = "no_overlap"
    elif overlap < 0.999:
        status = "partial_overlap"
    else:
        status = "ok"
    return {
        "status": status,
        "path": str(raster.get("path", "")),
        "format": str(raster.get("format", "")),
        "crs": crs,
        "native_extent": raster_native_bbox,
        "native_extent_source": str(raster.get("native_extent_source", "grid_geometry")),
        "metadata_reader": dict(raster.get("metadata_reader", {}) if isinstance(raster.get("metadata_reader", {}), dict) else {}),
        "extent_wgs84": raster_bbox,
        "coordinate_transform": _raster_crs_transform_label(crs),
        "coordinate_transform_detail": transform_detail,
        "footprint_overlap_fraction": round(overlap, 6),
    }


def _land_cover_raster_native_bbox(raster: dict[str, Any]) -> dict[str, float]:
    configured_extent = raster.get("native_extent")
    if isinstance(configured_extent, dict):
        try:
            return {
                "min_lon": float(configured_extent["min_lon"]),
                "min_lat": float(configured_extent["min_lat"]),
                "max_lon": float(configured_extent["max_lon"]),
                "max_lat": float(configured_extent["max_lat"]),
            }
        except (KeyError, TypeError, ValueError):
            pass
    xll = float(raster.get("xllcorner", 0.0) or 0.0)
    yll = float(raster.get("yllcorner", 0.0) or 0.0)
    ncols = int(raster.get("ncols", 0) or 0)
    nrows = int(raster.get("nrows", 0) or 0)
    cellsize_x = float(raster.get("cellsize_x", raster.get("cellsize", 0.0)) or 0.0)
    cellsize_y = float(raster.get("cellsize_y", raster.get("cellsize", 0.0)) or 0.0)
    return {
        "min_lon": xll,
        "min_lat": yll,
        "max_lon": xll + ncols * cellsize_x,
        "max_lat": yll + nrows * cellsize_y,
    }


def _land_cover_raster_bbox_wgs84(raster: dict[str, Any]) -> dict[str, float]:
    bbox, _ = _land_cover_raster_bbox_wgs84_with_detail(raster)
    return bbox


def _land_cover_raster_bbox_wgs84_with_detail(raster: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    native = _land_cover_raster_native_bbox(raster)
    crs = _normalize_raster_crs(str(raster.get("crs", "") or "EPSG:4326"))
    corners = [
        (native["min_lon"], native["min_lat"]),
        (native["max_lon"], native["min_lat"]),
        (native["max_lon"], native["max_lat"]),
        (native["min_lon"], native["max_lat"]),
    ]
    lonlat, transform_detail = _transform_coordinates_between_crs(
        points=corners,
        src_crs=crs,
        dst_crs="EPSG:4326",
    )
    if transform_detail.get("status") != "ok" or len(lonlat) != len(corners):
        return {}, transform_detail
    lon_values = [point[0] for point in lonlat]
    lat_values = [point[1] for point in lonlat]
    return (
        {
            "min_lon": min(lon_values),
            "min_lat": min(lat_values),
            "max_lon": max(lon_values),
            "max_lat": max(lat_values),
        },
        transform_detail,
    )


def _normalize_raster_crs(value: str) -> str:
    normalized = str(value or "EPSG:4326").strip().upper().replace(" ", "")
    if normalized in {"4326", "EPSG4326"}:
        return "EPSG:4326"
    if normalized in {"3857", "EPSG3857", "EPSG:900913", "900913", "WEBMERCATOR", "WEB_MERCATOR"}:
        return "EPSG:3857"
    return normalized or "EPSG:4326"


def _raster_crs_transform_label(crs: str) -> str:
    normalized = _normalize_raster_crs(crs)
    if normalized == "EPSG:4326":
        return "identity_epsg4326"
    if normalized == "EPSG:3857":
        return "builtin_epsg4326_to_epsg3857"
    return _coordinate_transform_label(src_crs="EPSG:4326", dst_crs=normalized, engine="rasterio")


def _coordinate_transform_label(*, src_crs: str, dst_crs: str, engine: str) -> str:
    src = _normalize_raster_crs(src_crs)
    dst = _normalize_raster_crs(dst_crs)
    if src == dst:
        return f"identity_{_crs_slug(src)}"
    return f"{engine}_{_crs_slug(src)}_to_{_crs_slug(dst)}"


def _crs_slug(crs: str) -> str:
    value = _normalize_raster_crs(crs).lower()
    return "".join(ch for ch in value if ch.isalnum()) or "unknown"


def _transform_coordinates_between_crs(
    *,
    points: list[tuple[float, float]],
    src_crs: str,
    dst_crs: str,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    src = _normalize_raster_crs(src_crs)
    dst = _normalize_raster_crs(dst_crs)
    normalized_points: list[tuple[float, float]] = []
    for x_value, y_value in points:
        try:
            x_float = float(x_value)
            y_float = float(y_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x_float) or not math.isfinite(y_float):
            continue
        normalized_points.append((x_float, y_float))
    if not normalized_points:
        return [], {
            "status": "ok",
            "engine": "none",
            "source_crs": src,
            "target_crs": dst,
            "transform": _coordinate_transform_label(src_crs=src, dst_crs=dst, engine="identity"),
            "point_count": 0,
        }
    if src == dst:
        return normalized_points, {
            "status": "ok",
            "engine": "identity",
            "source_crs": src,
            "target_crs": dst,
            "transform": _coordinate_transform_label(src_crs=src, dst_crs=dst, engine="identity"),
            "point_count": len(normalized_points),
        }
    if src == "EPSG:4326" and dst == "EPSG:3857":
        transformed = [_lonlat_to_raster_xy(lon=x_value, lat=y_value, crs=dst) for x_value, y_value in normalized_points]
        if all(point is not None for point in transformed):
            return [point for point in transformed if point is not None], {
                "status": "ok",
                "engine": "builtin",
                "source_crs": src,
                "target_crs": dst,
                "transform": _coordinate_transform_label(src_crs=src, dst_crs=dst, engine="builtin"),
                "point_count": len(normalized_points),
            }
    if src == "EPSG:3857" and dst == "EPSG:4326":
        transformed = [_raster_xy_to_lonlat(x=x_value, y=y_value, crs=src) for x_value, y_value in normalized_points]
        if all(point is not None for point in transformed):
            return [point for point in transformed if point is not None], {
                "status": "ok",
                "engine": "builtin",
                "source_crs": src,
                "target_crs": dst,
                "transform": _coordinate_transform_label(src_crs=src, dst_crs=dst, engine="builtin"),
                "point_count": len(normalized_points),
            }
    return _rasterio_coordinate_transform(points=normalized_points, src_crs=src, dst_crs=dst)


def _rasterio_coordinate_transform(
    *,
    points: list[tuple[float, float]],
    src_crs: str,
    dst_crs: str,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    import subprocess
    import sys

    src = _normalize_raster_crs(src_crs)
    dst = _normalize_raster_crs(dst_crs)
    payload = {
        "src_crs": src,
        "dst_crs": dst,
        "points": [[float(x_value), float(y_value)] for x_value, y_value in points],
    }
    script = r'''
import json
import os
import sys

payload = json.loads(sys.stdin.read() or "{}")
src_crs = payload.get("src_crs", "")
dst_crs = payload.get("dst_crs", "")
points = payload.get("points", [])
try:
    import rasterio
    from rasterio.warp import transform
except Exception as exc:
    print(json.dumps({
        "status": "not_available",
        "package": "rasterio",
        "error": str(exc),
        "message": "Install rasterio/GDAL to transform arbitrary land-cover raster CRS values.",
    }))
    sys.stdout.flush()
    os._exit(0)

try:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    out_xs, out_ys = transform(src_crs, dst_crs, xs, ys)
    print(json.dumps({
        "status": "ok",
        "package": "rasterio",
        "rasterio_version": str(getattr(rasterio, "__version__", "")),
        "gdal_version": str(getattr(rasterio, "__gdal_version__", "")),
        "points": [[float(x), float(y)] for x, y in zip(out_xs, out_ys)],
    }))
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "package": "rasterio",
        "source_crs": src_crs,
        "target_crs": dst_crs,
        "error": str(exc),
    }))
sys.stdout.flush()
os._exit(0)
'''
    transform_label = _coordinate_transform_label(src_crs=src, dst_crs=dst, engine="rasterio")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "source_crs": src,
            "target_crs": dst,
            "transform": transform_label,
            "point_count": len(points),
            "error": str(exc),
        }
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "source_crs": src,
            "target_crs": dst,
            "transform": transform_label,
            "point_count": len(points),
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip(),
        }
    try:
        child_payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return [], {
            "status": "error",
            "engine": "rasterio",
            "source_crs": src,
            "target_crs": dst,
            "transform": transform_label,
            "point_count": len(points),
            "error": str(exc),
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
        }
    detail = dict(child_payload) if isinstance(child_payload, dict) else {"status": "error"}
    status = str(detail.get("status", "error"))
    detail.update(
        {
            "engine": "rasterio",
            "source_crs": src,
            "target_crs": dst,
            "transform": transform_label,
            "point_count": len(points),
        }
    )
    if status != "ok":
        return [], detail
    transformed_points: list[tuple[float, float]] = []
    for point in detail.get("points", []):
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            transformed_points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if len(transformed_points) != len(points):
        detail["status"] = "error"
        detail["error"] = "Transformed point count does not match input point count."
        return [], detail
    detail.pop("points", None)
    return transformed_points, detail


def _lonlat_to_raster_xy(*, lon: float, lat: float, crs: str) -> tuple[float, float] | None:
    normalized = _normalize_raster_crs(crs)
    if normalized == "EPSG:4326":
        return float(lon), float(lat)
    if normalized == "EPSG:3857":
        radius_m = 6_378_137.0
        clamped_lat = max(min(float(lat), 85.05112878), -85.05112878)
        x = radius_m * math.radians(float(lon))
        y = radius_m * math.log(math.tan(math.pi / 4.0 + math.radians(clamped_lat) / 2.0))
        return x, y
    return None


def _raster_xy_to_lonlat(*, x: float, y: float, crs: str) -> tuple[float, float] | None:
    normalized = _normalize_raster_crs(crs)
    if normalized == "EPSG:4326":
        return float(x), float(y)
    if normalized == "EPSG:3857":
        radius_m = 6_378_137.0
        lon = math.degrees(float(x) / radius_m)
        lat = math.degrees(2.0 * math.atan(math.exp(float(y) / radius_m)) - math.pi / 2.0)
        return lon, lat
    return None


def _spectral_full_headers() -> list[str]:
    return ["window_id", "start_time", "end_time", "qc_grade", "series", "freq_hz", "value", "model_version"]


def _spectral_binned_headers() -> list[str]:
    base = ["bin_index", "freq_min_hz", "freq_max_hz", "freq_center_hz"]
    series = [
        "power_measured",
        "power_reference",
        "cospectrum",
        "ogive",
        "transfer_observed",
        "total_transfer_model",
    ]
    fields: list[str] = list(base)
    for name in series:
        fields.extend([f"{name}_mean", f"{name}_window_count"])
    return fields


def _spectral_ogive_headers() -> list[str]:
    return [
        "bin_index",
        "freq_center_hz",
        "ogive_mean",
        "ogive_window_count",
        "cospectrum_mean",
        "cospectrum_window_count",
    ]


def _spectral_library_group_headers() -> list[str]:
    return [
        "group_id",
        "group_label",
        "status",
        "run_count",
        "window_count",
        "period_start",
        "period_end",
        "mean_correction_factor",
        "mean_lag_seconds",
        "qc_grade_counts",
        "risk_counts",
    ]


def _spectral_library_bin_headers() -> list[str]:
    fields = ["group_id", "group_label", "bin_index", "freq_min_hz", "freq_max_hz", "freq_center_hz"]
    for name in (
        "power_measured",
        "power_reference",
        "cospectrum",
        "ogive",
        "transfer_observed",
        "total_transfer_model",
    ):
        fields.extend([f"{name}_mean", f"{name}_std", f"{name}_window_count"])
    return fields


def _spectral_library_group_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in list(payload.get("groups", []) or []):
        rows.append(
            {
                "group_id": group.get("group_id", ""),
                "group_label": group.get("group_label", ""),
                "status": group.get("status", ""),
                "run_count": group.get("run_count", 0),
                "window_count": group.get("window_count", 0),
                "period_start": group.get("period_start", ""),
                "period_end": group.get("period_end", ""),
                "mean_correction_factor": group.get("mean_correction_factor", ""),
                "mean_lag_seconds": group.get("mean_lag_seconds", ""),
                "qc_grade_counts": json.dumps(group.get("qc_grade_counts", {}), ensure_ascii=False),
                "risk_counts": json.dumps(group.get("risk_counts", {}), ensure_ascii=False),
            }
        )
    return rows


def _spectral_library_bin_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in list(payload.get("groups", []) or []):
        for row in list(dict(group.get("binned_ensemble", {}) or {}).get("rows", []) or []):
            merged = {
                "group_id": group.get("group_id", ""),
                "group_label": group.get("group_label", ""),
            }
            merged.update(dict(row))
            rows.append(merged)
    return rows


def _paired_numeric_series(freqs: Any, values: Any) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for raw_freq, raw_value in zip(list(freqs or []), list(values or []), strict=False):
        try:
            freq = float(raw_freq)
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(freq) or not math.isfinite(value):
            continue
        pairs.append((freq, value))
    pairs.sort(key=lambda item: item[0])
    return pairs


def _log_frequency_edges(freqs: list[float], *, target_bins: int) -> list[tuple[float, float, float]]:
    positive = [float(freq) for freq in freqs if freq > 0.0 and math.isfinite(freq)]
    if not positive:
        return []
    low = max(min(positive), 1e-9)
    high = max(max(positive), low * 1.001)
    bin_count = max(1, min(int(target_bins), len(set(round(freq, 12) for freq in positive))))
    if high <= low:
        return [(low, high, low)]
    log_low = math.log10(low)
    log_high = math.log10(high)
    edges = [10.0 ** (log_low + (log_high - log_low) * index / bin_count) for index in range(bin_count + 1)]
    bins: list[tuple[float, float, float]] = []
    for index in range(bin_count):
        left = float(edges[index])
        right = float(edges[index + 1])
        center = math.sqrt(max(left, 1e-12) * max(right, 1e-12))
        bins.append((left, right, center))
    return bins


def _spectral_binned_rows(
    window_series: list[dict[str, Any]],
    bins: list[tuple[float, float, float]],
    series_names: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (freq_min, freq_max, center) in enumerate(bins, start=1):
        row: dict[str, Any] = {
            "bin_index": index,
            "freq_min_hz": freq_min,
            "freq_max_hz": freq_max,
            "freq_center_hz": center,
        }
        for series_name in series_names:
            values: list[float] = []
            for payload in window_series:
                pairs = list(dict(payload.get("series", {}) or {}).get(series_name, []) or [])
                interpolated = _interpolate_series(pairs, center)
                if interpolated is not None:
                    values.append(interpolated)
            row[f"{series_name}_mean"] = _mean_or_blank(values)
            row[f"{series_name}_window_count"] = len(values)
        rows.append(row)
    return rows


def _interpolate_series(pairs: list[tuple[float, float]], x_value: float) -> float | None:
    if not pairs:
        return None
    if x_value < pairs[0][0] or x_value > pairs[-1][0]:
        return None
    if len(pairs) == 1:
        return float(pairs[0][1]) if abs(float(pairs[0][0]) - x_value) <= 1e-12 else None
    for (x0, y0), (x1, y1) in zip(pairs[:-1], pairs[1:], strict=False):
        if x0 == x1:
            continue
        if x0 <= x_value <= x1:
            weight = (x_value - x0) / (x1 - x0)
            return float(y0 + (y1 - y0) * weight)
    return None


def _mean_or_blank(values: list[float]) -> float | str:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return ""
    return float(sum(clean) / len(clean))


def _mean_or_zero(values: list[float]) -> float:
    mean = _mean_or_blank(values)
    return float(mean) if mean != "" else 0.0


def _synthetic_eddypro_parity_enabled(*, rp_config_snapshot: dict[str, Any], report_key: str = "") -> bool:
    candidates = (
        rp_config_snapshot.get("synthetic_eddypro_parity"),
        rp_config_snapshot.get("synthetic_parity"),
        dict(rp_config_snapshot.get("benchmark", {}) if isinstance(rp_config_snapshot.get("benchmark", {}), dict) else {}).get("synthetic_eddypro_parity"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and _truthy(candidate.get("enabled")):
            return True
        if isinstance(candidate, bool) and candidate:
            return True
    return str(report_key or "").strip().lower() in {
        "synthetic_eddypro_parity",
        "synthetic_parity",
        "eddypro_synthetic_parity",
    }


def _raw_to_final_parity_enabled(*, rp_config_snapshot: dict[str, Any], report_key: str = "") -> bool:
    candidates = (
        rp_config_snapshot.get("raw_to_final_parity"),
        dict(rp_config_snapshot.get("benchmark", {}) if isinstance(rp_config_snapshot.get("benchmark", {}), dict) else {}).get("raw_to_final_parity"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and _truthy(candidate.get("enabled")):
            return True
        if isinstance(candidate, bool) and candidate:
            return True
    return str(report_key or "").strip().lower() in {
        "raw_to_final_parity",
        "eddypro_raw_to_final_parity",
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _bbox_overlap_fraction(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        min_lon = max(float(a["min_lon"]), float(b["min_lon"]))
        max_lon = min(float(a["max_lon"]), float(b["max_lon"]))
        min_lat = max(float(a["min_lat"]), float(b["min_lat"]))
        max_lat = min(float(a["max_lat"]), float(b["max_lat"]))
        area_a = max(float(a["max_lon"]) - float(a["min_lon"]), 0.0) * max(float(a["max_lat"]) - float(a["min_lat"]), 0.0)
    except (KeyError, TypeError, ValueError):
        return 0.0
    if max_lon <= min_lon or max_lat <= min_lat or area_a <= 0.0:
        return 0.0
    return max((max_lon - min_lon) * (max_lat - min_lat), 0.0) / area_a


def _land_cover_grid_matches(value: Any, rows: int, cols: int) -> bool:
    if not isinstance(value, list) or len(value) != rows:
        return False
    for row in value:
        if not isinstance(row, list) or len(row) < cols:
            return False
    return True


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _li7700_wms_acceptance_status(
    *,
    normalized_rmse: float | None,
    area_ratio: float | None,
    thresholds: dict[str, Any],
    fit_status: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if str(fit_status or "").strip().lower() not in {"fit", "ok", "computed"}:
        return "not_evaluable", ["WMS line-shape fit was not available."]
    if normalized_rmse is None:
        return "not_evaluable", ["Selected WMS fit normalized RMSE was missing."]
    pass_max = float(thresholds.get("normalized_rmse_pass_max", 0.15) or 0.15)
    warning_max = float(thresholds.get("normalized_rmse_warning_max", 0.35) or 0.35)
    area_min = float(thresholds.get("area_ratio_min", 0.65) or 0.65)
    area_max = float(thresholds.get("area_ratio_max", 1.35) or 1.35)
    if normalized_rmse > warning_max:
        reasons.append(f"normalized_rmse {normalized_rmse:.6f} exceeds warning threshold {warning_max:.6f}.")
        return "fail", reasons
    if normalized_rmse > pass_max:
        reasons.append(f"normalized_rmse {normalized_rmse:.6f} exceeds pass threshold {pass_max:.6f}.")
    if area_ratio is not None and not (area_min <= area_ratio <= area_max):
        reasons.append(f"fit/integrated area ratio {area_ratio:.6f} is outside [{area_min:.6f}, {area_max:.6f}].")
    if reasons:
        return "warning", reasons
    return "pass", []


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
        quality_status = diag.get("clock_sync_quality_status", "")
        quality_text = f"; quality={quality_status}" if quality_status and quality_status != "not_configured" else ""
        notes.append(
            f"clock_sync: {diag.get('clock_sync_method', '')}; "
            f"source={diag.get('clock_sync_source', '')}; status={clock_status}{offset_text}{quality_text}"
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
    ("H", "W m-2", "Sensible heat flux"),
    ("LE", "W m-2", "Latent heat flux"),
    ("ET", "mm h-1", "Evapotranspiration rate derived from H2O flux"),
    ("TAU", "Pa", "Momentum flux / shear stress magnitude"),
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
    ("CLOCK_SYNC_QUALITY_STATUS", "text", "Post-acquisition clock correction quality status"),
    ("CLOCK_SYNC_QUALITY_GATE_STATUS", "text", "Clock correction quality gate status"),
    ("CLOCK_SYNC_QUALITY_METRIC_S", "seconds", "Clock correction quality metric"),
    ("CLOCK_SYNC_QUALITY_THRESHOLD_S", "seconds", "Configured clock correction quality threshold"),
    ("CLOCK_SYNC_MAX_EVENT_STEP_S", "seconds", "Maximum adjacent clock-event correction step"),
    ("RUNTIME_WATCHDOG_STATUS", "text", "Headless/SmartFlux-style runtime watchdog status"),
    ("RUNTIME_WATCHDOG_PROFILE", "text", "Runtime watchdog profile id"),
    ("RUNTIME_WATCHDOG_FAIL_COUNT", "count", "Failed runtime watchdog checks"),
    ("RUNTIME_SERVICE_STATUS", "text", "Headless runtime service status"),
    ("RUNTIME_SERVICE_DELIVERY_STATE", "text", "Runtime service delivery readiness state"),
    ("RUNTIME_SERVICE_QUARANTINE_COUNT", "count", "Inputs quarantined by runtime service"),
    ("DAEMON_TELEMETRY_STATUS", "text", "Daemon telemetry aggregate status"),
    ("TARGET_HOST_VALIDATION_STATUS", "text", "Target-host golden telemetry snapshot validation status"),
    ("TARGET_HOST_VALIDATION_GATE_STATUS", "text", "Target-host telemetry validation delivery gate status"),
    ("TARGET_HOST_VALIDATION_FIXTURE_ID", "text", "Target-host telemetry fixture identifier"),
    ("TARGET_HOST_ID", "text", "Target host identifier used for telemetry validation"),
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
    "H": "H",
    "LE": "LE",
    "ET": "ET",
    "TAU": "TAU",
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
    "CLOCK_SYNC_QUALITY_STATUS": "CLOCK_SYNC_QUALITY_STATUS",
    "CLOCK_SYNC_QUALITY_GATE_STATUS": "CLOCK_SYNC_QUALITY_GATE_STATUS",
    "CLOCK_SYNC_QUALITY_METRIC_S": "CLOCK_SYNC_QUALITY_METRIC_S",
    "CLOCK_SYNC_QUALITY_THRESHOLD_S": "CLOCK_SYNC_QUALITY_THRESHOLD_S",
    "CLOCK_SYNC_MAX_EVENT_STEP_S": "CLOCK_SYNC_MAX_EVENT_STEP_S",
    "RUNTIME_WATCHDOG_STATUS": "RUNTIME_WATCHDOG_STATUS",
    "RUNTIME_WATCHDOG_PROFILE": "RUNTIME_WATCHDOG_PROFILE",
    "RUNTIME_WATCHDOG_FAIL_COUNT": "RUNTIME_WATCHDOG_FAIL_COUNT",
    "RUNTIME_SERVICE_STATUS": "RUNTIME_SERVICE_STATUS",
    "RUNTIME_SERVICE_DELIVERY_STATE": "RUNTIME_SERVICE_DELIVERY_STATE",
    "RUNTIME_SERVICE_QUARANTINE_COUNT": "RUNTIME_SERVICE_QUARANTINE_COUNT",
    "DAEMON_TELEMETRY_STATUS": "DAEMON_TELEMETRY_STATUS",
    "TARGET_HOST_VALIDATION_STATUS": "TARGET_HOST_VALIDATION_STATUS",
    "TARGET_HOST_VALIDATION_GATE_STATUS": "TARGET_HOST_VALIDATION_GATE_STATUS",
    "TARGET_HOST_VALIDATION_FIXTURE_ID": "TARGET_HOST_VALIDATION_FIXTURE_ID",
    "TARGET_HOST_ID": "TARGET_HOST_ID",
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
    "H": "H",
    "LE": "LE",
    "ET": "ET",
    "TAU": "Tau",
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
    "CLOCK_SYNC_QUALITY_STATUS": "ClockSyncQualityStatus",
    "CLOCK_SYNC_QUALITY_GATE_STATUS": "ClockSyncQualityGateStatus",
    "CLOCK_SYNC_QUALITY_METRIC_S": "ClockSyncQualityMetricS",
    "CLOCK_SYNC_QUALITY_THRESHOLD_S": "ClockSyncQualityThresholdS",
    "CLOCK_SYNC_MAX_EVENT_STEP_S": "ClockSyncMaxEventStepS",
    "RUNTIME_WATCHDOG_STATUS": "RuntimeWatchdogStatus",
    "RUNTIME_WATCHDOG_PROFILE": "RuntimeWatchdogProfile",
    "RUNTIME_WATCHDOG_FAIL_COUNT": "RuntimeWatchdogFailCount",
    "RUNTIME_SERVICE_STATUS": "RuntimeServiceStatus",
    "RUNTIME_SERVICE_DELIVERY_STATE": "RuntimeServiceDeliveryState",
    "RUNTIME_SERVICE_QUARANTINE_COUNT": "RuntimeServiceQuarantineCount",
    "DAEMON_TELEMETRY_STATUS": "DaemonTelemetryStatus",
    "TARGET_HOST_VALIDATION_STATUS": "TargetHostValidationStatus",
    "TARGET_HOST_VALIDATION_GATE_STATUS": "TargetHostValidationGateStatus",
    "TARGET_HOST_VALIDATION_FIXTURE_ID": "TargetHostValidationFixtureId",
    "TARGET_HOST_ID": "TargetHostId",
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

GHG_EUROPE_FIELD_MAP = {
    "TIMESTAMP_START": "TIMESTAMP_START",
    "TIMESTAMP_END": "TIMESTAMP_END",
    "DOY": "DOY",
    "HOUR": "HOUR",
    "MINUTE": "MINUTE",
    "FC": "FC",
    "FC_QC": "FC_SSITC_TEST",
    "H": "H",
    "LE": "LE",
    "ET": "ET",
    "TAU": "TAU",
    "USTAR": "USTAR",
    "TA": "TA",
    "PA": "PA",
    "CO2": "CO2",
    "H2O": "H2O",
    "FCH4": "FCH4",
    "FCH4_QC": "FCH4_SSITC_TEST",
    "FETCH_70": "FETCH_70",
    "FETCH_90": "FETCH_90",
    "FETCH_MAX": "FETCH_MAX",
    "FETCH_FILTER": "FETCH_FILTER",
    "WIND_SPEED": "WS",
    "WIND_DIR": "WD",
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
    "GHG-Europe": {
        "field_map": GHG_EUROPE_FIELD_MAP,
        "timestamp_format": "YYYYMMDDHHmm local standard start/end",
        "gap_value": -9999,
        "qc_scale": "0-2 SSITC-style",
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
