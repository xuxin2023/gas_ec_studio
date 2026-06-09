from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication, QLabel

from app.main_window import StudioMainWindow
from app.pages.report_center_page import ReportCenterPage, _ui_safe_text
from app.studio import StudioController
from app.widgets.context_inspector import ContextInspector
from models.hf_models import FrameQuality, NormalizedHFFrame


def _assert_no_forbidden_ui_text(widget) -> None:
    visible_texts: list[str] = [label.text() for label in widget.findChildren(QLabel)]
    table = getattr(widget, "preview_table", None)
    if table is not None:
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    visible_texts.append(item.text())
    forbidden = ("EddyPro", "EDDYPRO", "eddypro", "industry_reference")
    assert not any(fragment in text for text in visible_texts for fragment in forbidden)


def test_report_center_ui_safe_text_maps_reference_internal_keys() -> None:
    text = (
        "public_eddypro_fixture_catalog "
        "official_eddypro_executable_run "
        "eddypro_computation_stress_suite "
        "references/eddypro/official_raw/site_001"
    )

    safe = _ui_safe_text(text)

    assert "public_reference_fixture_catalog" in safe
    assert "official_reference_run" in safe
    assert "reference_computation_stress_suite" in safe
    assert "references/reference/official_raw/site_001" in safe
    assert "eddypro" not in safe
    assert "industry_reference" not in safe


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _make_rows(sample_hz: float = 10.0, samples: int = 600) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    vertical = np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.25 * np.sin(2.0 * np.pi * 0.72 * time_axis)
    co2_signal = np.roll(vertical, 6) + 0.04 * np.sin(2.0 * np.pi * 1.1 * time_axis)
    h2o_signal = 0.7 * np.roll(vertical, 4) + 0.03 * np.cos(2.0 * np.pi * 0.9 * time_axis)

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
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps({"w": float(vertical[index])}),
            )
        )
    return rows


def _prepare_reference_dir(reference_dir: Path, current_export_dir: Path | None = None) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        "window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade",
        "ep-1,2026-04-18T09:00:00,2026-04-18T09:05:00,0.70,0.010,1.02,A",
        "ep-2,2026-04-18T09:05:00,2026-04-18T09:10:00,0.80,0.012,1.03,B",
    ]
    if current_export_dir is not None:
        spectral_lines = (current_export_dir / "spectral_qc_results.csv").read_text(encoding="utf-8").splitlines()
        header = spectral_lines[0].split(",")
        records = [dict(zip(header, line.split(","), strict=False)) for line in spectral_lines[1:3] if line.strip()]
        rows = ["window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade"]
        for index, record in enumerate(records, start=1):
            start_time = datetime.fromisoformat(str(record.get("start_time", ""))) + timedelta(seconds=1)
            end_time = datetime.fromisoformat(str(record.get("end_time", ""))) + timedelta(seconds=1)
            lag_seconds = float(record.get("lag_seconds", "0") or 0.0) + 0.05
            flux = float(record.get("corrected_flux_after", "0") or 0.0) * 0.98
            correction_factor = float(record.get("correction_factor", "1") or 1.0) * 0.99
            rows.append(
                ",".join(
                    [
                        f"ep-{index}",
                        start_time.isoformat(),
                        end_time.isoformat(),
                        f"{lag_seconds:.3f}",
                        f"{flux:.6f}",
                        f"{correction_factor:.4f}",
                        str(record.get("qc_grade", "A")),
                    ]
                )
            )
    (reference_dir / "eddypro_windows.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (reference_dir / "eddypro_summary.json").write_text(
        json.dumps({"software": "EddyPro"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_and_export_real_results(controller: StudioController) -> None:
    controller.project_workspace.setdefault("timing", {})["sample_hz"] = 10.0
    controller.project_workspace["timing"]["block_minutes"] = 5 / 60
    controller.ec_processing["steps"]["window_sampling"]["sample_hz"] = 10.0
    controller.ec_processing["steps"]["window_sampling"]["window_minutes"] = 5 / 60
    for row in _make_rows():
        controller.realtime_buffer.append(row)
    controller.run_ec_processing()
    controller.run_spectral_qc()
    controller.export_current_report()


def test_report_center_empty_state_without_compare_result(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.set_report_nav_section("eddypro_compare")
        page = ReportCenterPage(controller)
        page.refresh()

        assert "EddyPro" not in page.preview_title_label.text()
        _assert_no_forbidden_ui_text(page)
        assert page.preview_table.rowCount() >= 1
        found = False
        for row in range(page.preview_table.rowCount()):
            item = page.preview_table.item(row, 2)
            if item and "当前还没有" in item.text() and "EddyPro" not in item.text():
                found = True
                break
        assert found, "Expected neutral empty compare message in table"
    finally:
        controller.shutdown()


def test_report_center_displays_real_compare_summary(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_and_export_real_results(controller)
        current_export_dir = controller._latest_result_export_dir()
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)

        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )
        controller.set_report_nav_section("eddypro_compare")

        page = ReportCenterPage(controller)
        page.refresh()

        assert "EddyPro" not in page.preview_title_label.text()
        _assert_no_forbidden_ui_text(page)
        assert page.preview_metric_values[0].text() != "0"
        assert page.preview_table.rowCount() > 5
        assert any(page.preview_table.item(row, 0).text() == "compare_id" for row in range(page.preview_table.rowCount()))
    finally:
        controller.shutdown()


def test_context_inspector_returns_eddypro_compare_inspector(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_and_export_real_results(controller)
        current_export_dir = controller._latest_result_export_dir()
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)

        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )
        controller.set_report_nav_section("eddypro_compare")
        controller.set_selected_page("report_center")

        context = controller.context_snapshot()
        inspector = ContextInspector()
        inspector.refresh(context)

        assert "eddypro_compare_inspector" in context
        assert context["eddypro_compare_inspector"]["compare_id"]
        assert context["eddypro_compare_inspector"]["actions"]
        _assert_no_forbidden_ui_text(inspector)
    finally:
        controller.shutdown()


def test_compare_result_updates_report_changed_signal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_and_export_real_results(controller)
        current_export_dir = controller._latest_result_export_dir()
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)

        hits: list[str] = []
        controller.report_changed.connect(lambda: hits.append("changed"))
        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )

        assert hits
        assert controller.report_center_workspace["eddypro_compare"]["status"] == "ready"
    finally:
        controller.shutdown()


def test_main_window_report_center_page_smoke_with_eddypro_compare(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        _run_and_export_real_results(controller)
        current_export_dir = controller._latest_result_export_dir()
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)
        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )

        window = StudioMainWindow(controller)
        window._set_page("report_center")
        controller.set_report_nav_section("eddypro_compare")
        window._refresh_shell()

        assert window.stack.currentWidget() is window.report_center_page
        assert "EddyPro" not in window.report_center_page.preview_title_label.text()
        _assert_no_forbidden_ui_text(window.report_center_page)
        window.close()
    finally:
        controller.shutdown()
