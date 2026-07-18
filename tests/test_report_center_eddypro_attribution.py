from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.main_window import StudioMainWindow
from app.pages.report_center_page import ReportCenterPage
from app.studio import StudioController
from app.widgets.context_inspector import ContextInspector


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _prepare_reference_dir(reference_dir: Path, current_export_dir: Path | None = None) -> None:
    reference_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        "window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade",
        "ep-1,2026-04-18T09:00:00,2026-04-18T09:05:00,0.70,0.010,1.08,A",
        "ep-2,2026-04-18T09:05:00,2026-04-18T09:10:00,0.95,0.016,1.12,B",
    ]
    if current_export_dir is not None:
        spectral_lines = (current_export_dir / "spectral_qc_results.csv").read_text(encoding="utf-8").splitlines()
        header = spectral_lines[0].split(",")
        records = [dict(zip(header, line.split(","), strict=False)) for line in spectral_lines[1:3] if line.strip()]
        rows = ["window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade"]
        for index, record in enumerate(records, start=1):
            start_time = datetime.fromisoformat(str(record.get("start_time", ""))) + timedelta(seconds=1)
            end_time = datetime.fromisoformat(str(record.get("end_time", ""))) + timedelta(seconds=1)
            lag_seconds = float(record.get("lag_seconds", "0") or 0.0) + 0.65
            flux = float(record.get("corrected_flux_after", "0") or 0.0) * 0.86
            correction_factor = float(record.get("correction_factor", "1") or 1.0) * 1.12
            rows.append(
                ",".join(
                    [
                        f"ep-{index}",
                        start_time.isoformat(),
                        end_time.isoformat(),
                        f"{lag_seconds:.3f}",
                        f"{flux:.6f}",
                        f"{correction_factor:.4f}",
                        "B",
                    ]
                )
            )
    (reference_dir / "eddypro_windows.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (reference_dir / "eddypro_summary.json").write_text(
        json.dumps({"software": "EddyPro", "mapping_incomplete": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prepare_current_compare_export(controller: StudioController) -> Path:
    export_dir = controller.runtime_root / "exports" / "results" / "report_center_attribution_fixture"
    export_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 4, 18, 9, 0, 0)
    records = []
    for index, (lag, flux, correction, qc) in enumerate(
        (
            (0.30, 0.0200, 1.000, "A"),
            (0.40, 0.0185, 1.010, "A"),
            (0.50, 0.0192, 1.020, "B"),
        ),
        start=1,
    ):
        window_start = start + timedelta(minutes=5 * (index - 1))
        window_end = window_start + timedelta(minutes=5)
        records.append(
            {
                "window_key": f"cur-{index}",
                "start_time": window_start.isoformat(),
                "end_time": window_end.isoformat(),
                "lag_seconds": f"{lag:.3f}",
                "flux": f"{flux:.6f}",
                "corrected_flux_after": f"{flux:.6f}",
                "correction_factor": f"{correction:.4f}",
                "qc_grade": qc,
            }
        )
    header = "window_key,start_time,end_time,lag_seconds,flux,corrected_flux_after,correction_factor,qc_grade"
    lines = [
        header,
        *[
            ",".join(str(row[column]) for column in header.split(","))
            for row in records
        ],
    ]
    payload = "\n".join(lines) + "\n"
    (export_dir / "rp_results.csv").write_text(payload, encoding="utf-8")
    (export_dir / "spectral_qc_results.csv").write_text(payload, encoding="utf-8")
    (export_dir / "summary.json").write_text(
        json.dumps({"run_id": "attribution-fixture", "window_count": len(records)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (export_dir / "config_snapshot.json").write_text(
        json.dumps({"processing": "attribution-fixture"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (export_dir / "project_site_snapshot.json").write_text(
        json.dumps({"project": "attribution-fixture", "site": "synthetic"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return export_dir


def test_report_center_redirects_internal_attribution_empty_state(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path, expose_internal_validation=False)
    try:
        controller.set_report_nav_section("eddypro_compare")
        assert controller.report_center_workspace["selected_report"] == "method_provenance"
        page = ReportCenterPage(controller)
        page.refresh()

        assert "EddyPro" not in page.preview_title_label.text()
        assert page.preview_table.rowCount() >= 1
        assert all(
            "EddyPro" not in page.preview_table.item(row, column).text()
            for row in range(page.preview_table.rowCount())
            for column in range(page.preview_table.columnCount())
            if page.preview_table.item(row, column)
        )
    finally:
        controller.shutdown()


def test_report_center_keeps_internal_attribution_off_public_surface(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path, expose_internal_validation=False)
    try:
        current_export_dir = _prepare_current_compare_export(controller)
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)

        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )
        controller.set_report_nav_section("eddypro_compare")
        assert controller.latest_eddypro_attribution_result is not None
        assert controller.report_center_workspace["selected_report"] == "method_provenance"

        page = ReportCenterPage(controller)
        page.refresh()

        assert "EddyPro" not in page.preview_title_label.text()
        assert all(
            "EddyPro" not in page.preview_table.item(row, column).text()
            for row in range(page.preview_table.rowCount())
            for column in range(page.preview_table.columnCount())
            if page.preview_table.item(row, column)
        )
    finally:
        controller.shutdown()


def test_context_inspector_returns_eddypro_attribution_inspector(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        current_export_dir = _prepare_current_compare_export(controller)
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

        assert "eddypro_attribution_inspector" in context
        assert context["eddypro_attribution_inspector"]["dominant_causes"]
        assert context["eddypro_attribution_inspector"]["summary_text"]
    finally:
        controller.shutdown()


def test_compare_with_eddypro_updates_attribution_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        current_export_dir = _prepare_current_compare_export(controller)
        reference_dir = tmp_path / "reference"
        _prepare_reference_dir(reference_dir, current_export_dir)

        hits: list[str] = []
        controller.report_changed.connect(lambda: hits.append("changed"))
        controller.compare_with_eddypro(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        )

        attribution = controller.report_center_workspace["eddypro_attribution"]
        assert hits
        assert attribution["status"] == "ready"
        assert controller.current_eddypro_attribution_result() is not None
        assert attribution["dominant_causes"]
    finally:
        controller.shutdown()


def test_main_window_report_center_page_smoke_with_attribution(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        current_export_dir = _prepare_current_compare_export(controller)
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
        assert controller.report_center_workspace["eddypro_attribution"]["status"] == "ready"
        window.close()
    finally:
        controller.shutdown()
