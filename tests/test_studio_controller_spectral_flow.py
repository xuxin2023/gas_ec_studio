from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from app.studio import StudioController
from models.hf_models import FrameQuality, NormalizedHFFrame


def _make_rows(sample_hz: float = 10.0, samples: int = 512) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    vertical = np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.35 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    co2_signal = np.roll(vertical, 6) + 0.05 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, 4) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)
    pressure = 101.3 + 0.12 * vertical
    chamber = 25.0 + 0.3 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    case = 24.7 + 0.2 * np.cos(2.0 * np.pi * 0.03 * time_axis)

    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_signal[index]),
                h2o_mmol=float(12.0 + 1.2 * h2o_signal[index]),
                pressure_kpa=float(pressure[index]),
                chamber_temp_c=float(chamber[index]),
                case_temp_c=float(case[index]),
                raw_text=json.dumps({"w": float(vertical[index])}),
            )
        )
    return rows


def test_studio_controller_starts_with_empty_real_workspaces(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        assert controller.spectral_qc_workspace["windows"] == []
        assert controller.spectral_qc_workspace["active_run_id"] is None
        assert controller.spectral_qc_workspace["selected_window_id"] is None
        assert controller.report_center_workspace["active_run_id"] is None
        assert controller.report_center_workspace["summary"]["exportable_reports"] == 0
        assert controller.report_center_workspace["batch_compare"]["changed_windows"] == []
    finally:
        controller.shutdown()


def test_studio_controller_run_and_export_real_results(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
        controller.project_workspace["timing"]["block_minutes"] = 0.5
        for row in _make_rows():
            controller.realtime_buffer.append(row)

        result = controller.run_spectral_qc()

        assert "message" in result
        assert controller.spectral_runs
        assert controller.spectral_qc_workspace["active_run_id"] is not None
        assert controller.spectral_qc_workspace["windows"]
        assert controller.report_center_workspace["summary"]["exportable_reports"] > 0
        assert controller.current_spectral_run() is not None

        export_result = controller.export_spectral_evidence()
        manifest = controller.latest_evidence_manifest

        assert "message" in export_result
        assert manifest is not None
        bundle_root = tmp_path / "runtime_data" / "exports" / "evidence"
        assert bundle_root.exists()
        exported = next(bundle_root.iterdir())
        assert (exported / "manifest.json").exists()
        assert (exported / "summary.json").exists()
        assert (exported / "qc_windows.csv").exists()
    finally:
        controller.shutdown()
