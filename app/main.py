from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QTreeWidget,
    QWidget,
)

from app.main_window import StudioMainWindow
from app.studio import INTERNAL_VALIDATION_REPORT_KEYS, StudioController
from app.theme import apply_app_theme
from app.version import APP_VERSION
from core.exports.public_text import find_public_text_violations


RC_RUNTIME_MODULES = (
    "PySide6",
    "pyqtgraph",
    "serial",
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "h5py",
    "rasterio",
    "pyproj",
    "morecantile",
    "rio_cogeo",
)


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--smoke-report")
    parser.add_argument("--smoke-screenshot")
    return parser.parse_known_args(argv)


def _default_workspace_root(configured: str | Path | None = None) -> Path:
    if configured:
        return Path(configured).expanduser()
    env_root = str(os.environ.get("GAS_EC_WORKSPACE_ROOT", "") or "").strip()
    if env_root:
        return Path(env_root).expanduser()
    if getattr(sys, "frozen", False):
        local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "GasECStudio"
    return Path.cwd()


def _tree_text(item) -> list[str]:
    rows = [item.text(0), item.toolTip(0)]
    for index in range(item.childCount()):
        rows.extend(_tree_text(item.child(index)))
    return rows


def _visible_text(root: QWidget) -> list[str]:
    rows: list[str] = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisibleTo(root):
            continue
        if widget.toolTip():
            rows.append(widget.toolTip())
        if isinstance(widget, QLabel):
            rows.append(widget.text())
        elif isinstance(widget, QAbstractButton):
            rows.append(widget.text())
        elif isinstance(widget, QComboBox):
            rows.extend(widget.itemText(index) for index in range(widget.count()))
        elif isinstance(widget, QPlainTextEdit):
            rows.append(widget.toPlainText())
        elif isinstance(widget, QTextEdit):
            rows.append(widget.toPlainText())
        elif isinstance(widget, QTreeWidget):
            for index in range(widget.topLevelItemCount()):
                rows.extend(_tree_text(widget.topLevelItem(index)))
    return [row for row in rows if row]


def _probe_runtime_modules() -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for module_name in RC_RUNTIME_MODULES:
        try:
            module = importlib.import_module(module_name)
            results[module_name] = {
                "status": "pass",
                "version": str(getattr(module, "__version__", "")),
            }
        except Exception as exc:  # pragma: no cover - package composition is environment-specific
            results[module_name] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    return results


def _navigation_guard_summary(results: dict[str, bool]) -> dict[str, int | bool]:
    blocked_count = sum(1 for blocked in results.values() if blocked)
    return {
        "checked_route_count": len(results),
        "blocked_route_count": blocked_count,
        "all_blocked": blocked_count == len(results),
    }


def _write_smoke_report(
    *,
    app: QApplication,
    window: StudioMainWindow,
    report_path: Path,
    screenshot_path: Path | None,
) -> int:
    payload: dict[str, object]
    try:
        page_results: dict[str, object] = {}
        violations: set[str] = set()
        for page_key, page in window.pages.items():
            window._set_page(page_key)
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
            app.processEvents()
            page_violations = find_public_text_violations(_visible_text(page))
            violations.update(page_violations)
            page_results[page_key] = {
                "visible": page.isVisible(),
                "width": page.width(),
                "height": page.height(),
                "forbidden_tokens": page_violations,
            }

        window._set_page("report_center")
        window.report_center_page.refresh()
        app.processEvents()
        pixmap = window.grab()
        screenshot_saved = True
        if screenshot_path is not None:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_saved = pixmap.save(str(screenshot_path))
        global_violations = find_public_text_violations(_visible_text(window))
        violations.update(global_violations)
        compact_checks = {
            "delivery_rail_hidden": not window.report_center_page.delivery_rail.isVisible(),
            "principle_footer_hidden": not window.navigation.principle_footer.isVisible(),
        }
        release_reports = set(window.controller.report_center_workspace.get("reports", {}))
        internal_reports = sorted(release_reports & INTERNAL_VALIDATION_REPORT_KEYS)
        navigation_guard: dict[str, bool] = {}
        selected_report = str(window.controller.report_center_workspace.get("selected_report", "run_summary"))
        signals_were_blocked = window.controller.blockSignals(True)
        try:
            for report_key in sorted(INTERNAL_VALIDATION_REPORT_KEYS):
                window.controller.set_report_nav_section(report_key)
                active_report = str(window.controller.report_center_workspace.get("selected_report", ""))
                navigation_guard[report_key] = active_report not in INTERNAL_VALIDATION_REPORT_KEYS
            window.controller.set_report_nav_section(selected_report)
        finally:
            window.controller.blockSignals(signals_were_blocked)
        report_tree_keys = set(window.report_center_page.report_items)
        internal_tree_items = sorted(report_tree_keys & INTERNAL_VALIDATION_REPORT_KEYS)
        release_surface_checks = {
            "internal_reports_absent": not internal_reports,
            "internal_tree_items_absent": not internal_tree_items,
            "internal_navigation_blocked": all(navigation_guard.values()),
        }
        module_probes = _probe_runtime_modules()
        modules_ready = all(probe.get("status") == "pass" for probe in module_probes.values())
        passed = (
            not violations
            and screenshot_saved
            and all(compact_checks.values())
            and all(release_surface_checks.values())
            and modules_ready
        )
        payload = {
            "status": "pass" if passed else "fail",
            "app_version": APP_VERSION,
            "workspace_root": str(window.controller.workspace_root),
            "logical_window_size": [window.width(), window.height()],
            "captured_pixel_size": [pixmap.width(), pixmap.height()],
            "device_pixel_ratio": pixmap.devicePixelRatio(),
            "forbidden_tokens": sorted(violations),
            "compact_checks": compact_checks,
            "release_surface": {
                **release_surface_checks,
                "report_count": len(release_reports),
                "internal_reports": internal_reports,
                "internal_tree_items": internal_tree_items,
                "navigation_guard": _navigation_guard_summary(navigation_guard),
            },
            "runtime_modules": module_probes,
            "pages": page_results,
            "screenshot": str(screenshot_path or ""),
        }
    except Exception as exc:  # pragma: no cover - exercised by packaged smoke runs
        passed = False
        payload = {"status": "fail", "app_version": APP_VERSION, "error": f"{type(exc).__name__}: {exc}"}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 2


def main() -> int:
    args, qt_args = _parse_args(sys.argv[1:])
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Gas EC Studio")
    app.setApplicationDisplayName("Gas EC Studio")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Gas EC Studio")
    apply_app_theme(app)
    controller = StudioController(
        workspace_root=_default_workspace_root(args.workspace_root),
        expose_internal_validation=False,
    )
    window = StudioMainWindow(controller)
    if args.smoke_report or args.smoke_screenshot:
        window.resize(1366, 768)
    window.show()
    if args.smoke_report:
        report_path = Path(args.smoke_report)
        screenshot_path = Path(args.smoke_screenshot) if args.smoke_screenshot else None
        QTimer.singleShot(
            250,
            lambda: app.exit(
                _write_smoke_report(
                    app=app,
                    window=window,
                    report_path=report_path,
                    screenshot_path=screenshot_path,
                )
            ),
        )
    try:
        return app.exec()
    finally:
        controller.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
