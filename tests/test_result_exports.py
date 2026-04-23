from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    co2_signal = np.roll(w, 5) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.75 * np.roll(w, 3) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.08 * np.sin(2.0 * np.pi * 0.02 * time_axis)
    temp = 24.8 + 0.25 * np.cos(2.0 * np.pi * 0.02 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.3 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(temp[index]),
                case_temp_c=float(temp[index] - 0.1),
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def test_result_export_bundle_writes_real_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
        controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
        controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
        controller.project_workspace["timing"]["block_minutes"] = 0.5
        for row in _make_rows():
            controller.realtime_buffer.append(row)
        controller.run_ec_processing()
        controller.run_spectral_qc()
        result = controller.export_current_report()
        assert "交付包已导出" in result["message"]
        assert "导出" in controller.report_center_workspace["export_status"]

        export_root = tmp_path / "runtime_data" / "exports" / "results"
        bundle_root = next(export_root.iterdir())
        expected_files = {
            "rp_results.csv",
            "spectral_qc_results.csv",
            "full_output.csv",
            "summary.json",
            "config_snapshot.json",
            "project_site_snapshot.json",
            "report_snapshot.json",
            "export_manifest.json",
            "network_validation_summary.json",
            "fluxnet_half_hourly_foundation.json",
            "fluxnet_full_submission.json",
        }
        actual_files = {path.name for path in bundle_root.iterdir()}
        assert expected_files.issubset(actual_files)
        for name in expected_files:
            path = bundle_root / name
            assert path.exists()
            assert path.read_text(encoding="utf-8").strip() != ""

        rp_csv = (bundle_root / "rp_results.csv").read_text(encoding="utf-8")
        spectral_csv = (bundle_root / "spectral_qc_results.csv").read_text(encoding="utf-8")
        full_output_csv = (bundle_root / "full_output.csv").read_text(encoding="utf-8")
        assert "window_id" in rp_csv
        assert "window_id" in spectral_csv
        assert "relative_uncertainty" in full_output_csv
        assert "diagnostics_flags" in full_output_csv
        assert "turbulence_intermediate" in full_output_csv

        summary_payload = json.loads((bundle_root / "summary.json").read_text(encoding="utf-8"))
        assert summary_payload["rp_run"]["status"] == "ok"
        assert summary_payload["spectral_run"]["status"] == "ok"

        config_payload = json.loads((bundle_root / "config_snapshot.json").read_text(encoding="utf-8"))
        assert "rp_config_snapshot" in config_payload
        assert "spectral_config_snapshot" in config_payload

        manifest_payload = json.loads((bundle_root / "export_manifest.json").read_text(encoding="utf-8"))
        assert manifest_payload["full_output_mode"] == "only_available"
        assert manifest_payload["field_schema"]
        assert any(field["name"] == "diagnostics_flags" for field in manifest_payload["field_schema"])
        assert manifest_payload["schema_target"] == "FLUXNET"
        assert "network_validation_status" in manifest_payload
        assert "network_missing_fields" in manifest_payload

        project_site_payload = json.loads((bundle_root / "project_site_snapshot.json").read_text(encoding="utf-8"))
        assert "project" in project_site_payload
        assert "site" in project_site_payload
    finally:
        controller.shutdown()
