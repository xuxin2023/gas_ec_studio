from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

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
        rows.append(
            ",".join(
                [
                    f"ep-{index}",
                    start_time.isoformat(),
                    end_time.isoformat(),
                    f"{float(record.get('lag_seconds', '0') or 0.0) + 0.3:.3f}",
                    f"{float(record.get('corrected_flux_after', '0') or 0.0) * 0.95:.6f}",
                    f"{float(record.get('correction_factor', '1') or 1.0) * 1.03:.4f}",
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


def _latest_delivery_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_data" / "exports" / "delivery"
    return max((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)


def _latest_delivery_zip(tmp_path: Path) -> Path:
    root = tmp_path / "runtime_data" / "exports" / "delivery"
    return max((path for path in root.iterdir() if path.suffix == ".zip"), key=lambda path: path.stat().st_mtime)


def test_delivery_package_exports_minimal_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _prepare_real_results(controller)
        result = controller.export_current_report()

        assert "交付包已导出" in result["message"]
        assert "交付包已导出" in controller.report_center_workspace["export_status"]

        delivery_dir = _latest_delivery_dir(tmp_path)
        manifest_path = delivery_dir / "package_manifest.json"
        audit_path = delivery_dir / "delivery_audit.json"
        readme_path = delivery_dir / "README.txt"
        zip_path = _latest_delivery_zip(tmp_path)

        assert delivery_dir.exists()
        assert manifest_path.exists()
        assert audit_path.exists()
        assert readme_path.exists()
        assert zip_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        readme = readme_path.read_text(encoding="utf-8")

        assert manifest["export_status"] == "ready"
        assert manifest["delivery_audit"]["validation_status"] == "ok"
        assert audit["validation_status"] == "ok"
        assert manifest["result_manifest_summary"]["schema_target"]
        assert "network_validation_summary" in manifest
        assert manifest["artifact_index"]["export_manifest"]["packaged"] is True
        assert manifest["artifact_index"]["network_validation_summary"]["packaged"] is True
        assert manifest["artifact_index"]["method_rollup_artifact"]["packaged"] is True
        assert manifest["artifact_index"]["method_parity_matrix_artifact"]["packaged"] is True
        assert audit["missing_declared_files"] == []
        assert audit["missing_manifest_files"] == []
        assert manifest["file_list"]
        assert any("缺少 compare" in note or "缺少 attribution" in note for note in manifest["notes"])
        assert "formal_report.html" in readme
        assert "fallback_html_only" in readme
        assert (delivery_dir / "formal_report.html").exists()
        assert (delivery_dir / "rp_results.csv").exists()
        assert (delivery_dir / "spectral_qc_results.csv").exists()
        with ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
        assert any(name.endswith("package_manifest.json") for name in names)
        assert any(name.endswith("delivery_audit.json") for name in names)
        assert any(name.endswith("network_validation_summary.json") for name in names)
    finally:
        controller.shutdown()


def test_delivery_package_includes_compare_and_attribution(monkeypatch, tmp_path: Path) -> None:
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
        controller.export_current_report()

        delivery_dir = _latest_delivery_dir(tmp_path)
        manifest = json.loads((delivery_dir / "package_manifest.json").read_text(encoding="utf-8"))

        assert (delivery_dir / "compare_summary.json").exists()
        assert (delivery_dir / "compare_windows.csv").exists()
        assert (delivery_dir / "compare_manifest.json").exists()
        assert (delivery_dir / "attribution_summary.json").exists()
        assert manifest["compare_id"]
        assert manifest["attribution_id"]

        zip_path = _latest_delivery_zip(tmp_path)
        with ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
        assert any(name.endswith("compare_summary.json") for name in names)
        assert any(name.endswith("attribution_summary.json") for name in names)
    finally:
        controller.shutdown()
