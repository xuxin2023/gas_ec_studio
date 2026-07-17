from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCALES = (1.0, 1.25, 1.5)


def _safe_reset_workspace(path: Path, output_root: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(output_root.resolve())
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def _run_child(scale: float, output: Path, workspace: Path, screenshot: Path) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(PROJECT_ROOT))
    from app.main import _visible_text
    from app.main_window import StudioMainWindow
    from app.studio import INTERNAL_VALIDATION_REPORT_KEYS, StudioController
    from app.theme import apply_app_theme
    from core.exports.public_text import find_public_text_violations

    app = QApplication.instance() or QApplication([])
    apply_app_theme(app)
    controller = StudioController(workspace_root=workspace, expose_internal_validation=False)
    window = StudioMainWindow(controller)
    window.resize(1366, 768)
    window.show()
    app.processEvents()
    page_results: dict[str, object] = {}
    violations: set[str] = set()
    try:
        for page_key, page in window.pages.items():
            window._set_page(page_key)
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
            app.processEvents()
            page_violations = find_public_text_violations(_visible_text(page))
            violations.update(page_violations)
            page_results[page_key] = {
                "width": page.width(),
                "height": page.height(),
                "forbidden_tokens": page_violations,
            }

        window._set_page("report_center")
        window.report_center_page.refresh()
        app.processEvents()
        pixmap = window.grab()
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        screenshot_saved = pixmap.save(str(screenshot))
        image = pixmap.toImage()
        sample_colors = {
            image.pixelColor(x, y).rgba()
            for x in range(0, max(1, image.width()), max(1, image.width() // 24))
            for y in range(0, max(1, image.height()), max(1, image.height() // 16))
        }
        compact_checks = {
            "delivery_rail_hidden": not window.report_center_page.delivery_rail.isVisible(),
            "principle_footer_hidden": not window.navigation.principle_footer.isVisible(),
            "filter_title_hidden": not window.report_center_page.filter_title.isVisible(),
        }
        release_reports = set(controller.report_center_workspace.get("reports", {}))
        release_surface_checks = {
            "internal_reports_absent": release_reports.isdisjoint(INTERNAL_VALIDATION_REPORT_KEYS),
            "internal_tree_items_absent": set(window.report_center_page.report_items).isdisjoint(
                INTERNAL_VALIDATION_REPORT_KEYS
            ),
        }
        violations.update(find_public_text_violations(_visible_text(window)))
        passed = (
            screenshot_saved
            and len(sample_colors) >= 8
            and not violations
            and all(compact_checks.values())
            and all(release_surface_checks.values())
        )
        payload = {
            "status": "pass" if passed else "fail",
            "requested_scale": scale,
            "logical_window_size": [window.width(), window.height()],
            "captured_pixel_size": [pixmap.width(), pixmap.height()],
            "device_pixel_ratio": pixmap.devicePixelRatio(),
            "sample_color_count": len(sample_colors),
            "forbidden_tokens": sorted(violations),
            "compact_checks": compact_checks,
            "release_surface": {**release_surface_checks, "report_count": len(release_reports)},
            "pages": page_results,
            "screenshot": str(screenshot),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if passed else 2
    finally:
        window.close()
        controller.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate common Windows DPI scale factors in isolated Qt processes.")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "artifacts" / "windows_rc" / "dpi_validation")
    parser.add_argument("--child-scale", type=float)
    parser.add_argument("--child-output", type=Path)
    parser.add_argument("--child-workspace", type=Path)
    parser.add_argument("--child-screenshot", type=Path)
    args = parser.parse_args()

    if args.child_scale is not None:
        if not args.child_output or not args.child_workspace or not args.child_screenshot:
            parser.error("child mode requires output, workspace and screenshot paths")
        return _run_child(args.child_scale, args.child_output, args.child_workspace, args.child_screenshot)

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    for scale in DEFAULT_SCALES:
        label = str(scale).replace(".", "p")
        workspace = output_root / f"workspace-{label}"
        _safe_reset_workspace(workspace, output_root)
        report_path = output_root / f"dpi-{label}.json"
        screenshot_path = output_root / f"report-center-dpi-{label}.png"
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_SCALE_FACTOR"] = str(scale)
        env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child-scale",
                str(scale),
                "--child-output",
                str(report_path),
                "--child-workspace",
                str(workspace),
                "--child-screenshot",
                str(screenshot_path),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            timeout=180,
            check=False,
        )
        if result.returncode != 0 or not report_path.exists():
            raise RuntimeError(f"DPI validation failed for scale {scale}: exit={result.returncode}")
        reports.append(json.loads(report_path.read_text(encoding="utf-8")))

    passed = all(report.get("status") == "pass" for report in reports)
    summary = {"status": "pass" if passed else "fail", "reports": reports}
    summary_path = output_root / "dpi-validation-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), **summary}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
