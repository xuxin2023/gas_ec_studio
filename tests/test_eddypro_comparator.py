from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from core.comparison.eddypro_comparator import EddyProComparator
from models.comparison_models import EddyProCompareResult


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_current_export(export_dir: Path) -> None:
    _write_text(
        export_dir / "rp_results.csv",
        "\n".join(
            [
                "window_id,start_time,end_time,lag_seconds,density_corrected_flux,qc_grade",
                "w1,2026-04-18T09:00:00,2026-04-18T09:30:00,2.4,0.52,A",
                "w2,2026-04-18T09:30:00,2026-04-18T10:00:00,2.8,0.61,B",
            ]
        )
        + "\n",
    )
    _write_text(
        export_dir / "spectral_qc_results.csv",
        "\n".join(
            [
                "window_id,start_time,end_time,lag_seconds,correction_factor,corrected_flux_after,qc_grade",
                "w1,2026-04-18T09:00:00,2026-04-18T09:30:00,2.5,1.08,0.53,A",
                "w2,2026-04-18T09:30:00,2026-04-18T10:00:00,2.9,1.11,0.60,B",
            ]
        )
        + "\n",
    )
    _write_text(
        export_dir / "summary.json",
        json.dumps({"rp_run": {"status": "ok"}, "spectral_run": {"status": "ok"}}, ensure_ascii=False, indent=2),
    )
    _write_text(
        export_dir / "config_snapshot.json",
        json.dumps({"rp_config_snapshot": {"sample_hz": 10}, "spectral_config_snapshot": {"block_minutes": 30}}, ensure_ascii=False, indent=2),
    )
    _write_text(
        export_dir / "project_site_snapshot.json",
        json.dumps({"project": {"name": "P1"}, "site": {"station_code": "S1"}}, ensure_ascii=False, indent=2),
    )


def _prepare_reference_export(reference_dir: Path) -> None:
    _write_text(
        reference_dir / "eddypro_windows.csv",
        "\n".join(
            [
                "window_key,start_time,end_time,lag_seconds,flux,correction_factor,qc_grade",
                "r1,2026-04-18T09:00:20,2026-04-18T09:30:20,2.6,0.50,1.05,A",
                "r2,2026-04-18T09:30:00,2026-04-18T10:00:00,2.7,0.58,1.09,C",
            ]
        )
        + "\n",
    )
    _write_text(
        reference_dir / "eddypro_summary.json",
        json.dumps({"software": "EddyPro", "version": "minimal"}, ensure_ascii=False, indent=2),
    )


def test_current_results_load_successfully(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    _prepare_current_export(export_dir)

    comparator = EddyProComparator(tmp_path)
    current = comparator.load_current_results(export_dir)

    assert len(current["windows"]) == 2
    assert current["summary"]["rp_run"]["status"] == "ok"
    assert current["windows"][0].flux == 0.52
    assert current["windows"][0].correction_factor == 1.08


def test_reference_results_load_successfully(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference_bundle"
    _prepare_reference_export(reference_dir)

    comparator = EddyProComparator(tmp_path)
    reference = comparator.load_reference_results(
        reference_dir,
        mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
    )

    assert len(reference["windows"]) == 2
    assert reference["summary"]["software"] == "EddyPro"
    assert reference["windows"][0].lag_seconds == 2.6


def test_time_window_matching_succeeds_with_tolerance(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    reference_dir = tmp_path / "reference_bundle"
    _prepare_current_export(export_dir)
    _prepare_reference_export(reference_dir)

    comparator = EddyProComparator(tmp_path, match_tolerance_seconds=30.0)
    current = comparator.load_current_results(export_dir)
    reference = comparator.load_reference_results(
        reference_dir,
        mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
    )
    result = comparator.compare(current, reference)

    matched_notes = [window.notes for window in result.window_results if "matched within time tolerance" in window.notes]
    assert matched_notes
    assert result.summary_metrics["matched_window_count"] == 2


def test_compare_generates_non_empty_result(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    reference_dir = tmp_path / "reference_bundle"
    _prepare_current_export(export_dir)
    _prepare_reference_export(reference_dir)

    comparator = EddyProComparator(tmp_path, match_tolerance_seconds=30.0)
    result = comparator.compare(
        comparator.load_current_results(export_dir),
        comparator.load_reference_results(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        ),
    )

    assert isinstance(result, EddyProCompareResult)
    assert result.window_results
    assert result.summary_metrics["avg_lag_delta"] is not None


def test_compare_summary_json_is_written(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    reference_dir = tmp_path / "reference_bundle"
    _prepare_current_export(export_dir)
    _prepare_reference_export(reference_dir)

    comparator = EddyProComparator(tmp_path, match_tolerance_seconds=30.0)
    result = comparator.compare(
        comparator.load_current_results(export_dir),
        comparator.load_reference_results(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        ),
    )
    manifest = comparator.export(result, comparator.default_export_root())

    summary_path = Path(manifest["files"]["compare_summary"])
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary_path.exists()
    assert payload["matched_window_count"] == 2
    assert "risk_summary" in payload


def test_compare_windows_csv_is_written(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    reference_dir = tmp_path / "reference_bundle"
    _prepare_current_export(export_dir)
    _prepare_reference_export(reference_dir)

    comparator = EddyProComparator(tmp_path, match_tolerance_seconds=30.0)
    result = comparator.compare(
        comparator.load_current_results(export_dir),
        comparator.load_reference_results(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        ),
    )
    manifest = comparator.export(result, comparator.default_export_root())

    windows_path = Path(manifest["files"]["compare_windows"])
    content = windows_path.read_text(encoding="utf-8")

    assert windows_path.exists()
    assert "window_key" in content
    assert "current_lag_seconds" in content


def test_missing_fields_fall_back_without_unhandled_exception(tmp_path: Path) -> None:
    export_dir = tmp_path / "current_bundle"
    reference_dir = tmp_path / "reference_bundle"
    _prepare_current_export(export_dir)

    _write_text(
        reference_dir / "eddypro_windows.csv",
        "\n".join(
            [
                "start_time,end_time,lag_seconds",
                "2026-04-18T09:00:00,2026-04-18T09:30:00,2.6",
                "2026-04-18T09:30:00,2026-04-18T10:00:00,2.7",
            ]
        )
        + "\n",
    )
    _write_text(reference_dir / "eddypro_summary.json", "{}")

    comparator = EddyProComparator(tmp_path)
    result = comparator.compare(
        comparator.load_current_results(export_dir),
        comparator.load_reference_results(
            reference_dir,
            mapping={"window_csv": "eddypro_windows.csv", "summary_json": "eddypro_summary.json"},
        ),
    )

    assert result.window_results
    assert any("flux field missing" in note for window in result.window_results for note in window.notes)
