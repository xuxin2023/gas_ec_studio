from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.comparison.synthetic_parity import (
    SYNTHETIC_PARITY_SUITE_ID,
    run_synthetic_eddypro_parity_suite,
)
from core.exports.result_exporter import ResultExporter
from core.headless_batch_runner import build_batch_manifest
from models.rp_models import RPRunResult
from models.spectral_models import SpectralRunResult
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def test_synthetic_eddypro_parity_suite_passes_core_oracles() -> None:
    suite = run_synthetic_eddypro_parity_suite()

    assert suite["artifact_type"] == "synthetic_eddypro_parity_suite"
    assert suite["suite_id"] == SYNTHETIC_PARITY_SUITE_ID
    assert suite["status"] == "pass"
    assert suite["case_count"] == 7
    assert suite["failed_case_count"] == 0
    assert "without claiming real-world EddyPro numeric parity" in suite["truthfulness_note"]


def test_synthetic_eddypro_parity_suite_covers_lag_flux_and_density_modes() -> None:
    suite = run_synthetic_eddypro_parity_suite()
    by_id = {case["case_id"]: case for case in suite["cases"]}

    assert set(by_id) == {
        "known_covariance_density_none",
        "known_lag_covariance_max",
        "density_correction_mode_semantics",
        "double_rotation_tilt_guardrail",
        "constant_signal_qc_guardrail",
        "spectral_correction_family_invariants",
        "footprint_geometry_family_invariants",
    }
    lag_case = by_id["known_lag_covariance_max"]
    assert lag_case["status"] == "pass"
    assert lag_case["expected"]["lag_seconds"] == 0.5
    assert abs(float(lag_case["actual"]["lag_seconds"]) - 0.5) < 0.11

    density_case = by_id["density_correction_mode_semantics"]
    assert density_case["status"] == "pass"
    assert set(density_case["actual"]) == {"none", "mixing_ratio", "wpl"}
    assert density_case["actual"]["none"]["primary_flux_source"] == "none"
    assert density_case["actual"]["mixing_ratio"]["primary_flux_source"] == "mixing_ratio"
    assert density_case["actual"]["wpl"]["primary_flux_source"] == "wpl"

    rotation_case = by_id["double_rotation_tilt_guardrail"]
    assert rotation_case["status"] == "pass"
    assert rotation_case["actual"]["applied_rotation_impl"] == "double"
    assert rotation_case["actual"]["rotation_applied"] is True

    qc_case = by_id["constant_signal_qc_guardrail"]
    assert qc_case["status"] == "pass"
    assert qc_case["actual"]["qc_grade"] == "C"
    assert qc_case["actual"]["anomaly_type"] == "constant_signal"
    assert {"co2_ppm_constant", "h2o_mmol_constant"}.issubset(set(qc_case["actual"]["issues"]))

    spectral_case = by_id["spectral_correction_family_invariants"]
    assert spectral_case["status"] == "pass"
    assert spectral_case["actual"]["fratini"]["components"]["uses_measured_cospectrum"] is True

    footprint_case = by_id["footprint_geometry_family_invariants"]
    assert footprint_case["status"] == "pass"
    assert abs(footprint_case["actual"]["kljun_2d_grid"]["grid_sum"] - 1.0) < 1e-6


def test_result_exporter_writes_synthetic_parity_artifact_when_enabled(tmp_path: Path) -> None:
    created_at = datetime(2026, 5, 25, 12, 0, 0)
    rp_result = RPRunResult(run_id="rp", created_at=created_at, data_source="test", time_range="", windows=[], summary={}, artifacts={})
    spectral_result = SpectralRunResult(run_id="sp", created_at=created_at, data_source="test", time_range="", qc_only=False, windows=[], summary={}, artifacts={})

    bundle = ResultExporter(tmp_path).export_minimal_bundle(
        rp_result=rp_result,
        spectral_result=spectral_result,
        rp_config_snapshot={"synthetic_eddypro_parity": {"enabled": True}},
        spectral_config_snapshot={},
        project=ProjectProfile(code="PRJ-SYN", name="synthetic"),
        site=SiteProfile(station_code="SYN", station_name="Synthetic"),
        report_payload={"title": "synthetic parity"},
        report_key="synthetic_eddypro_parity",
    )

    artifact_path = Path(bundle["files"]["synthetic_eddypro_parity_artifact"])
    manifest = json.loads(Path(bundle["files"]["export_manifest"]).read_text(encoding="utf-8"))
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_path.exists()
    assert payload["status"] == "pass"
    assert payload["suite_id"] == SYNTHETIC_PARITY_SUITE_ID
    assert manifest["synthetic_eddypro_parity"]["status"] == "pass"
    assert manifest["synthetic_eddypro_parity_artifact"] == str(artifact_path)


def test_headless_manifest_includes_synthetic_parity_when_enabled() -> None:
    created_at = datetime(2026, 5, 25, 12, 0, 0)
    metadata = MetadataBundle()
    rp_result = RPRunResult(run_id="rp", created_at=created_at, data_source="test", time_range="", windows=[], summary={}, artifacts={})
    spectral_result = SpectralRunResult(run_id="sp", created_at=created_at, data_source="test", time_range="", qc_only=False, windows=[], summary={}, artifacts={})

    manifest = build_batch_manifest(
        batch_id="synthetic-parity",
        metadata_bundle=metadata,
        config={"synthetic_eddypro_parity": {"enabled": True}},
        rows=[],
        rp_result=rp_result,
        spectral_result=spectral_result,
    )

    assert manifest["synthetic_eddypro_parity"]["status"] == "pass"
    assert manifest["synthetic_eddypro_parity"]["suite_id"] == SYNTHETIC_PARITY_SUITE_ID
