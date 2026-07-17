from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from app.main_window import StudioMainWindow
from app.pages.report_center_page import INTERNAL_VALIDATION_REPORT_KEYS, ReportCenterPage, _ui_safe_text
from app.studio import StudioController
from app.widgets.context_inspector import ContextInspector


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

    assert "public_validation_fixture_catalog" in safe
    assert "official_validation_run" in safe
    assert "validation_computation_stress_suite" in safe
    assert "references/validation/official_raw/site_001" in safe
    assert "eddypro" not in safe
    assert "industry_reference" not in safe


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


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


def _prepare_current_compare_export(controller: StudioController) -> Path:
    export_dir = controller.runtime_root / "exports" / "results" / "report_center_compare_fixture"
    export_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 4, 18, 9, 0, 0)
    records = []
    for index, (lag, flux, correction, qc) in enumerate(
        (
            (0.65, 0.0102, 1.010, "A"),
            (0.75, 0.0121, 1.025, "B"),
            (0.85, 0.0116, 1.018, "A"),
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
        json.dumps({"run_id": "compare-fixture", "window_count": len(records)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (export_dir / "config_snapshot.json").write_text(
        json.dumps({"processing": "compare-fixture"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (export_dir / "project_site_snapshot.json").write_text(
        json.dumps({"project": "compare-fixture", "site": "synthetic"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return export_dir


def test_report_center_empty_state_without_compare_result(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        controller.set_report_nav_section("eddypro_compare")
        page = ReportCenterPage(controller)
        page.refresh()

        assert page.filter_bar.property("cardRole") == "command"
        assert page.tree_card.property("cardRole") == "rail"
        assert page.delivery_rail.property("cardRole") == "rail"
        assert page.batch_card.property("cardRole") == "panel"
        assert page.report_tree.objectName() == "workflowTree"
        assert controller.report_center_workspace["selected_report"] == "run_summary"
        assert INTERNAL_VALIDATION_REPORT_KEYS.isdisjoint(page.report_items)
        _assert_no_forbidden_ui_text(page)
    finally:
        controller.shutdown()


def test_report_center_keeps_real_compare_summary_internal(monkeypatch, tmp_path: Path) -> None:
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

        page = ReportCenterPage(controller)
        page.refresh()

        assert controller.report_center_workspace["eddypro_compare"]["status"] == "ready"
        assert controller.report_center_workspace["selected_report"] == "run_summary"
        assert INTERNAL_VALIDATION_REPORT_KEYS.isdisjoint(page.report_items)
        _assert_no_forbidden_ui_text(page)
    finally:
        controller.shutdown()


def test_context_inspector_uses_public_report_after_internal_compare_selection(monkeypatch, tmp_path: Path) -> None:
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
        page = ReportCenterPage(controller)
        page.refresh()

        context = controller.context_snapshot()
        inspector = ContextInspector()
        inspector.refresh(context)

        assert "report_inspector" in context
        assert "eddypro_compare_inspector" not in context
        _assert_no_forbidden_ui_text(inspector)
    finally:
        controller.shutdown()


def test_compare_result_updates_report_changed_signal(monkeypatch, tmp_path: Path) -> None:
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

        assert hits
        assert controller.report_center_workspace["eddypro_compare"]["status"] == "ready"
    finally:
        controller.shutdown()


def test_main_window_report_center_page_smoke_with_eddypro_compare(monkeypatch, tmp_path: Path) -> None:
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
        assert controller.report_center_workspace["selected_report"] == "run_summary"
        assert INTERNAL_VALIDATION_REPORT_KEYS.isdisjoint(window.report_center_page.report_items)
        _assert_no_forbidden_ui_text(window.report_center_page)
        window.close()
    finally:
        controller.shutdown()
