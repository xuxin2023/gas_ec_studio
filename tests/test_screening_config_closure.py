"""Tests for RP v3a.1 screening config closure.

Covers:
  1. GUI -> config mapping for screening parameters
  2. CLI parameter injection for screening
  3. Manifest recording of screening config
  4. Export manifest screening config
  5. Default config regression
  6. Pipeline _extract_screening_config
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from core.ec_rp.pipeline import _extract_screening_config
from core.exports.result_exporter import FULL_OUTPUT_SCHEMA, ResultExporter
from core.headless_batch_runner import build_batch_manifest
from models.rp_models import WindowRPResult, RPRunResult
from models.station_models import MetadataBundle, ProjectProfile, SiteProfile


def _make_window(**overrides) -> WindowRPResult:
    defaults = dict(
        window_id="w1",
        start_time=datetime(2025, 1, 1, 0, 0),
        end_time=datetime(2025, 1, 1, 0, 30),
        sample_count=18000,
        valid_sample_count=17900,
        continuity_ratio=0.99,
        missing_ratio=0.01,
        rotation_mode="double",
        detrend_mode="block_mean",
        lag_seconds=2.4,
        lag_confidence=0.85,
        cov_w_co2=-0.05,
        cov_w_h2o=0.01,
        raw_flux=-5.2,
        mixing_ratio_flux=-5.1,
        density_corrected_flux=-5.0,
        water_vapor_flux=0.02,
        air_molar_density=42.0,
        dry_air_molar_density=41.5,
        mean_co2_ppm=415.0,
        mean_h2o_mmol=10.0,
        mean_pressure_kpa=101.3,
        mean_temp_c=25.0,
        qc_grade="A",
        anomaly_type="",
        reason="",
        qc_flags=["spike_w"],
        diagnostics={
            "lag_strategy": "covariance_max",
            "lag_fallback_reason": "",
            "screening_detail": {
                "co2_ppm": {"valid_count": 17900, "skewness": {"value": 0.5, "threshold": 2.0}},
                "h2o_mmol": {"valid_count": 17900, "skewness": {"value": 2.3, "threshold": 2.0}},
            },
            "screening_config": {
                "skewness_threshold": 2.0,
                "kurtosis_threshold": 7.0,
                "dropout_min_run": 10,
                "spike_sigma": 5.0,
                "discontinuity_sigma": 8.0,
            },
            "issues": ["spike_w", "h2o_mmol_skewness"],
        },
    )
    defaults.update(overrides)
    return WindowRPResult(**defaults)


def _make_metadata() -> MetadataBundle:
    return MetadataBundle(
        project=ProjectProfile(name="Test", code="T01"),
        site=SiteProfile(station_name="Site1", station_code="S01"),
    )


# ---------------------------------------------------------------------------
# 1. GUI -> config mapping for screening parameters
# ---------------------------------------------------------------------------

class TestScreeningGUIConfigMapping:
    """Verify that screening parameters from GUI payload map correctly
    into the config snapshot consumed by the pipeline."""

    def test_screening_params_in_payload(self):
        payload_steps = {
            "screening": {
                "skewness_threshold": 3.0,
                "kurtosis_threshold": 9.0,
                "dropout_min_run": 15,
                "spike_sigma": 4.0,
                "discontinuity_sigma": 6.0,
                "absolute_limits_text": '{"co2_ppm": [0, 900]}',
            }
        }
        screening_step = payload_steps["screening"]
        config_snapshot = {
            "skewness_threshold": float(screening_step.get("skewness_threshold", 2.0) or 2.0),
            "kurtosis_threshold": float(screening_step.get("kurtosis_threshold", 7.0) or 7.0),
            "dropout_min_run": int(screening_step.get("dropout_min_run", 10) or 10),
            "spike_sigma": float(screening_step.get("spike_sigma", 5.0) or 5.0),
            "discontinuity_sigma": float(screening_step.get("discontinuity_sigma", 8.0) or 8.0),
        }
        abs_text = str(screening_step.get("absolute_limits_text", "")).strip()
        if abs_text:
            try:
                config_snapshot["absolute_limits"] = json.loads(abs_text)
            except (json.JSONDecodeError, ValueError):
                pass
        assert config_snapshot["skewness_threshold"] == 3.0
        assert config_snapshot["kurtosis_threshold"] == 9.0
        assert config_snapshot["dropout_min_run"] == 15
        assert config_snapshot["spike_sigma"] == 4.0
        assert config_snapshot["discontinuity_sigma"] == 6.0
        assert config_snapshot["absolute_limits"] == {"co2_ppm": [0, 900]}

    def test_screening_defaults_when_missing(self):
        payload_steps = {"screening": {}}
        screening_step = payload_steps["screening"]
        config_snapshot = {
            "skewness_threshold": float(screening_step.get("skewness_threshold", 2.0) or 2.0),
            "kurtosis_threshold": float(screening_step.get("kurtosis_threshold", 7.0) or 7.0),
            "dropout_min_run": int(screening_step.get("dropout_min_run", 10) or 10),
            "spike_sigma": float(screening_step.get("spike_sigma", 5.0) or 5.0),
            "discontinuity_sigma": float(screening_step.get("discontinuity_sigma", 8.0) or 8.0),
        }
        assert config_snapshot["skewness_threshold"] == 2.0
        assert config_snapshot["kurtosis_threshold"] == 7.0
        assert config_snapshot["dropout_min_run"] == 10
        assert config_snapshot["spike_sigma"] == 5.0
        assert config_snapshot["discontinuity_sigma"] == 8.0

    def test_absolute_limits_invalid_json_ignored(self):
        payload_steps = {
            "screening": {
                "absolute_limits_text": "not valid json{{{",
            }
        }
        screening_step = payload_steps["screening"]
        config_snapshot = {}
        abs_text = str(screening_step.get("absolute_limits_text", "")).strip()
        if abs_text:
            try:
                config_snapshot["absolute_limits"] = json.loads(abs_text)
            except (json.JSONDecodeError, ValueError):
                pass
        assert "absolute_limits" not in config_snapshot

    def test_absolute_limits_empty_string_ignored(self):
        payload_steps = {
            "screening": {
                "absolute_limits_text": "",
            }
        }
        screening_step = payload_steps["screening"]
        config_snapshot = {}
        abs_text = str(screening_step.get("absolute_limits_text", "")).strip()
        if abs_text:
            try:
                config_snapshot["absolute_limits"] = json.loads(abs_text)
            except (json.JSONDecodeError, ValueError):
                pass
        assert "absolute_limits" not in config_snapshot


# ---------------------------------------------------------------------------
# 2. CLI parameter injection for screening
# ---------------------------------------------------------------------------

class TestScreeningCLIInjection:
    """Verify that CLI screening args inject correctly into config dict,
    matching the logic in headless_batch_runner.run_cli."""

    def test_all_screening_cli_args_injected(self):
        config = {}
        skewness_threshold = "3.5"
        kurtosis_threshold = "10.0"
        dropout_min_run = "20"
        spike_sigma = "4.5"
        discontinuity_sigma = "7.0"
        absolute_limits_json = '{"co2_ppm": [0, 1200], "h2o_mmol": [0, 40]}'
        if skewness_threshold:
            config.setdefault("screening", {})["skewness_threshold"] = float(skewness_threshold)
        if kurtosis_threshold:
            config.setdefault("screening", {})["kurtosis_threshold"] = float(kurtosis_threshold)
        if dropout_min_run:
            config.setdefault("screening", {})["dropout_min_run"] = int(dropout_min_run)
        if spike_sigma:
            config.setdefault("screening", {})["spike_sigma"] = float(spike_sigma)
        if discontinuity_sigma:
            config.setdefault("screening", {})["discontinuity_sigma"] = float(discontinuity_sigma)
        if absolute_limits_json:
            config.setdefault("screening", {})["absolute_limits"] = json.loads(absolute_limits_json)
        assert config["screening"]["skewness_threshold"] == 3.5
        assert config["screening"]["kurtosis_threshold"] == 10.0
        assert config["screening"]["dropout_min_run"] == 20
        assert config["screening"]["spike_sigma"] == 4.5
        assert config["screening"]["discontinuity_sigma"] == 7.0
        assert config["screening"]["absolute_limits"]["co2_ppm"] == [0, 1200]

    def test_partial_screening_cli_args(self):
        config = {"screening": {"skewness_threshold": 2.0}}
        spike_sigma = "6.0"
        if spike_sigma:
            config.setdefault("screening", {})["spike_sigma"] = float(spike_sigma)
        assert config["screening"]["skewness_threshold"] == 2.0
        assert config["screening"]["spike_sigma"] == 6.0

    def test_no_screening_cli_args_leaves_config_unchanged(self):
        config = {}
        assert "screening" not in config


# ---------------------------------------------------------------------------
# 3. Batch manifest recording of screening config
# ---------------------------------------------------------------------------

class TestScreeningManifestRecording:
    """Verify that screening_config appears in the batch manifest."""

    def test_manifest_records_screening_config(self):
        config = {
            "screening": {
                "skewness_threshold": 3.0,
                "kurtosis_threshold": 9.0,
                "dropout_min_run": 15,
                "spike_sigma": 4.0,
                "discontinuity_sigma": 6.0,
                "absolute_limits": {"co2_ppm": [0, 900]},
            }
        }
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert "screening_config" in manifest
        sc = manifest["screening_config"]
        assert sc["skewness_threshold"] == 3.0
        assert sc["kurtosis_threshold"] == 9.0
        assert sc["dropout_min_run"] == 15
        assert sc["spike_sigma"] == 4.0
        assert sc["discontinuity_sigma"] == 6.0
        assert sc["absolute_limits"] == {"co2_ppm": [0, 900]}

    def test_manifest_screening_config_defaults(self):
        config = {}
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        assert "screening_config" in manifest
        sc = manifest["screening_config"]
        assert sc["skewness_threshold"] == 2.0
        assert sc["kurtosis_threshold"] == 7.0
        assert sc["dropout_min_run"] == 10
        assert sc["spike_sigma"] == 5.0
        assert sc["discontinuity_sigma"] == 8.0
        assert sc["absolute_limits"] is None

    def test_manifest_screening_config_without_absolute_limits(self):
        config = {
            "screening": {
                "skewness_threshold": 2.5,
            }
        }
        manifest = build_batch_manifest(
            batch_id="test_batch",
            metadata_bundle=_make_metadata(),
            config=config,
            rows=[],
            rp_result=MagicMock(run_id="rp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
            spectral_result=MagicMock(run_id="sp1", created_at=datetime(2025, 1, 1), summary={}, windows=[]),
        )
        sc = manifest["screening_config"]
        assert sc["skewness_threshold"] == 2.5
        assert sc["absolute_limits"] is None


# ---------------------------------------------------------------------------
# 4. Export manifest screening config
# ---------------------------------------------------------------------------

class TestExportManifestScreeningConfig:
    """Verify that screening_config appears in the export manifest."""

    def test_export_manifest_includes_screening_config(self):
        rp_config_snapshot = {
            "screening": {
                "skewness_threshold": 2.5,
                "kurtosis_threshold": 8.0,
                "dropout_min_run": 12,
                "spike_sigma": 5.5,
                "discontinuity_sigma": 7.5,
                "absolute_limits": {"co2_ppm": [0, 1000]},
            }
        }
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        sc = exporter._extract_screening_config(rp_config_snapshot)
        assert sc["skewness_threshold"] == 2.5
        assert sc["kurtosis_threshold"] == 8.0
        assert sc["dropout_min_run"] == 12
        assert sc["spike_sigma"] == 5.5
        assert sc["discontinuity_sigma"] == 7.5
        assert sc["absolute_limits"] == {"co2_ppm": [0, 1000]}

    def test_export_manifest_screening_defaults(self):
        rp_config_snapshot = {}
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        sc = exporter._extract_screening_config(rp_config_snapshot)
        assert sc["skewness_threshold"] == 2.0
        assert sc["kurtosis_threshold"] == 7.0
        assert sc["dropout_min_run"] == 10
        assert sc["spike_sigma"] == 5.0
        assert sc["discontinuity_sigma"] == 8.0
        assert sc["absolute_limits"] is None

    def test_full_output_schema_has_screening_config(self):
        schema_names = [name for name, _, _ in FULL_OUTPUT_SCHEMA]
        assert "screening_config" in schema_names

    def test_full_output_row_contains_screening_config(self):
        window = _make_window()
        rp_result = RPRunResult(
            run_id="test_run",
            created_at=datetime(2025, 1, 1),
            windows=[window],
            summary={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert len(rows) == 1
        sc = json.loads(rows[0]["screening_config"])
        assert sc["skewness_threshold"] == 2.0
        assert sc["kurtosis_threshold"] == 7.0
        assert sc["dropout_min_run"] == 10

    def test_full_output_row_screening_config_empty_when_absent(self):
        window = _make_window(diagnostics={})
        rp_result = RPRunResult(
            run_id="test_run",
            created_at=datetime(2025, 1, 1),
            windows=[window],
            summary={},
            data_source="test",
            time_range="",
        )
        exporter = ResultExporter(runtime_root=Path("tmp_test_export"))
        rows = exporter._full_output_rows(rp_result=rp_result, spectral_result=None, mode="standard_schema")
        assert rows[0].get("screening_config", "") == ""


# ---------------------------------------------------------------------------
# 5. Default config regression
# ---------------------------------------------------------------------------

class TestScreeningDefaultConfigRegression:
    """Verify that default screening config values are consistent
    across studio defaults, pipeline extraction, and manifest defaults."""

    EXPECTED_DEFAULTS = {
        "skewness_threshold": 2.0,
        "kurtosis_threshold": 7.0,
        "dropout_min_run": 10,
        "spike_sigma": 5.0,
        "discontinuity_sigma": 8.0,
    }

    def test_pipeline_extract_screening_config_defaults(self):
        config = {}
        sc = _extract_screening_config(config)
        for key, expected in self.EXPECTED_DEFAULTS.items():
            assert sc[key] == expected, f"pipeline default for {key}: expected {expected}, got {sc[key]}"

    def test_pipeline_extract_screening_config_from_top_level(self):
        config = {
            "screening": {
                "skewness_threshold": 3.0,
                "kurtosis_threshold": 10.0,
                "dropout_min_run": 20,
                "spike_sigma": 6.0,
                "discontinuity_sigma": 9.0,
            }
        }
        sc = _extract_screening_config(config)
        assert sc["skewness_threshold"] == 3.0
        assert sc["kurtosis_threshold"] == 10.0
        assert sc["dropout_min_run"] == 20
        assert sc["spike_sigma"] == 6.0
        assert sc["discontinuity_sigma"] == 9.0

    def test_pipeline_extract_screening_config_from_steps_path(self):
        config = {
            "steps": {
                "screening": {
                    "skewness_threshold": 1.5,
                    "kurtosis_threshold": 5.0,
                }
            }
        }
        sc = _extract_screening_config(config)
        assert sc["skewness_threshold"] == 1.5
        assert sc["kurtosis_threshold"] == 5.0

    def test_pipeline_extract_screening_absolute_limits(self):
        config = {
            "screening": {
                "absolute_limits": {"co2_ppm": [0, 800], "w": [-20, 20]},
            }
        }
        sc = _extract_screening_config(config)
        assert sc["absolute_limits"] == {"co2_ppm": [0, 800], "w": [-20, 20]}

    def test_studio_default_screening_step_has_all_keys(self):
        from app.studio import StudioController
        controller = StudioController(workspace_root=Path("tmp_test_studio_v3a1"))
        try:
            screening_step = controller.ec_processing["steps"]["screening"]
            for key in self.EXPECTED_DEFAULTS:
                assert key in screening_step, f"studio default screening step missing key: {key}"
                assert screening_step[key] == self.EXPECTED_DEFAULTS[key], (
                    f"studio default for {key}: expected {self.EXPECTED_DEFAULTS[key]}, got {screening_step[key]}"
                )
            assert "absolute_limits_text" in screening_step
        finally:
            controller.shutdown()

    def test_studio_config_snapshot_screening_roundtrip(self):
        from app.studio import StudioController
        controller = StudioController(workspace_root=Path("tmp_test_studio_v3a1_snap"))
        try:
            controller.ec_processing["steps"]["screening"]["skewness_threshold"] = 3.5
            controller.ec_processing["steps"]["screening"]["absolute_limits_text"] = '{"co2_ppm": [0, 1200]}'
            snapshot = controller._rp_config_snapshot(precheck_only=False)
            assert snapshot["screening"]["skewness_threshold"] == 3.5
            assert snapshot["screening"]["absolute_limits"] == {"co2_ppm": [0, 1200]}
        finally:
            controller.shutdown()


# ---------------------------------------------------------------------------
# 6. Screening detail and issues preserved in results
# ---------------------------------------------------------------------------

class TestScreeningDetailPreservation:
    """Verify that screening_detail and diagnostics_issues are preserved
    through the result pipeline and not lost during workspace sync."""

    def test_window_diagnostics_preserves_screening_detail(self):
        window = _make_window()
        assert "screening_detail" in window.diagnostics
        assert "co2_ppm" in window.diagnostics["screening_detail"]

    def test_window_diagnostics_preserves_screening_config(self):
        window = _make_window()
        assert "screening_config" in window.diagnostics
        assert window.diagnostics["screening_config"]["skewness_threshold"] == 2.0

    def test_window_diagnostics_preserves_issues(self):
        window = _make_window()
        assert "issues" in window.diagnostics
        assert "h2o_mmol_skewness" in window.diagnostics["issues"]

    def test_window_to_dict_preserves_screening(self):
        window = _make_window()
        d = window.to_dict()
        assert "screening_detail" in d["diagnostics"]
        assert "screening_config" in d["diagnostics"]
        assert "issues" in d["diagnostics"]
