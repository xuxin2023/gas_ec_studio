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


def _prepare_reference_dir(reference_dir: Path, current_export_dir: Path) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)
    spectral_lines = (current_export_dir / "spectral_qc_results.csv").read_text(encoding="utf-8").splitlines()
    header = spectral_lines[0].split(",")
    records = [dict(zip(header, line.split(","), strict=False)) for line in spectral_lines[1:3] if line.strip()]
    rows = ["window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade"]
    for index, record in enumerate(records, start=1):
        start_time = datetime.fromisoformat(str(record.get("start_time", ""))) + timedelta(seconds=1)
        end_time = datetime.fromisoformat(str(record.get("end_time", ""))) + timedelta(seconds=1)
        lag_seconds = float(record.get("lag_seconds", "0") or 0.0) + 0.35
        flux = float(record.get("corrected_flux_after", "0") or 0.0) * 0.92
        correction_factor = float(record.get("correction_factor", "1") or 1.0) * 1.04
        rows.append(
            ",".join(
                [
                    f"ep-{index}",
                    start_time.isoformat(),
                    end_time.isoformat(),
                    f"{lag_seconds:.3f}",
                    f"{flux:.6f}",
                    f"{correction_factor:.4f}",
                    str(record.get("qc_grade", "B")),
                ]
            )
        )
    (reference_dir / "eddypro_windows.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (reference_dir / "eddypro_summary.json").write_text(
        json.dumps({"software": "EddyPro", "mapping_incomplete": False}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prepare_real_results(controller: StudioController) -> None:
    controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
    controller.project_workspace["timing"]["block_minutes"] = 0.5
    controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
    controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 0.5
    for row in _make_rows():
        controller.realtime_buffer.append(row)
    controller.run_ec_processing()
    controller.run_spectral_qc()


def _latest_formal_report_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_data" / "exports" / "formal_reports"
    return max(root.iterdir(), key=lambda path: path.stat().st_mtime)


def test_formal_report_exports_files_without_compare(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        result = controller.export_current_report()

        assert "导出" in result["message"]
        assert "正式报告" in controller.report_center_workspace["export_status"] or "交付包" in controller.report_center_workspace["export_status"]

        export_dir = _latest_formal_report_dir(tmp_path)
        html_path = export_dir / "formal_report.html"
        snapshot_path = export_dir / "formal_report_snapshot.json"
        manifest_path = export_dir / "report_manifest.json"

        assert html_path.exists()
        assert snapshot_path.exists()
        assert manifest_path.exists()

        html = html_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        assert "Gas EC Studio 正式结果报告" in html
        assert "当前无对标结果" in html
        assert "当前无归因结果" in html
        assert manifest["pdf_status"] == "fallback_html_only"
        assert snapshot["header"]["current_batch_id"]
    finally:
        controller.shutdown()


def test_formal_report_contains_compare_and_attribution_sections(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        controller.export_current_report()
        current_export_dir = controller._latest_result_export_dir()
        assert current_export_dir is not None

        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)
        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )
        controller.set_report_nav_section("eddypro_compare")
        controller.export_current_report()

        export_dir = _latest_formal_report_dir(tmp_path)
        html = (export_dir / "formal_report.html").read_text(encoding="utf-8")
        manifest = json.loads((export_dir / "report_manifest.json").read_text(encoding="utf-8"))

        assert "EddyPro 对标摘要" in html
        assert "差异自动归因" in html
        assert "matched_window_count" in html
        assert "dominant_causes" in html
        assert manifest["compare_id"]
        assert manifest["attribution_id"]
    finally:
        controller.shutdown()


def test_formal_report_export_state_is_stable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        controller.export_current_report()

        file_info = controller.report_center_workspace["reports"][controller.report_center_workspace["selected_report"]]["file_info"]
        assert file_info["正式报告HTML"].endswith("formal_report.html")
        assert file_info["正式报告Manifest"].endswith("report_manifest.json")

        export_dir = _latest_formal_report_dir(tmp_path)
        snapshot = json.loads((export_dir / "formal_report_snapshot.json").read_text(encoding="utf-8"))
        assert snapshot["data_sources"]["spectral_run_id"]
        assert snapshot["report_version"] == "formal_report_v1"
    finally:
        controller.shutdown()
