from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from core.ec_fcc.analysis import build_spectral_assessment_library
from core.ec_fcc.pipeline import ECFCCPipeline
from core.exports.result_exporter import ResultExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _rows(sample_hz: float = 10.0, samples: int = 900, start: datetime | None = None) -> list[NormalizedHFFrame]:
    start = start or datetime(2026, 5, 27, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    vertical = 0.7 * np.sin(2.0 * np.pi * 0.16 * time_axis) + 0.2 * np.sin(2.0 * np.pi * 0.8 * time_axis)
    co2 = np.roll(vertical, 4) + 0.03 * np.sin(2.0 * np.pi * 1.3 * time_axis)
    h2o = 0.65 * np.roll(vertical, 3) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-fcc",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2[index]),
                h2o_mmol=float(12.0 + 1.1 * h2o[index]),
                pressure_kpa=float(101.3 + 0.08 * vertical[index]),
                chamber_temp_c=float(25.0 + 0.2 * np.sin(2.0 * np.pi * 0.02 * time_axis[index])),
                case_temp_c=float(24.8),
                raw_text=json.dumps({"w": float(vertical[index])}),
            )
        )
    return rows


def test_spectral_assessment_artifact_exports_binned_full_and_ogive_csv(tmp_path: Path) -> None:
    spectral = ECFCCPipeline().run(
        rows=_rows(),
        project=ProjectProfile(code="PRJ-SPEC", name="Spectral Assessment"),
        site=SiteProfile(station_code="SITE-SPEC", station_name="Spectral Site"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "lag_phase": {"search_window_s": 3.0, "expected_lag_s": 0.4},
            "correction_factor": {"factor_cap": 1.4},
        },
        data_source="unit-test",
        time_range="2026-05-27 09:00~09:02",
    )
    assert spectral.windows

    exporter = ResultExporter(runtime_root=tmp_path)
    export_root = tmp_path / "spectral_assessment"
    export_root.mkdir(parents=True)
    artifact_path, companion_files = exporter.export_spectral_assessment_artifact(
        spectral_result=spectral,
        export_root=export_root,
    )

    assert artifact_path is not None
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "spectral_assessment_export_v1"
    assert payload["status"] == "ok"
    assert payload["binned_ensemble"]["bin_count"] > 0
    assert payload["full_window_row_count"] > payload["usable_window_count"]
    assert "power_measured" in payload["value_families"]
    assert "cospectrum" in payload["value_families"]
    assert "ogive" in payload["value_families"]

    for path_value in companion_files.values():
        path = Path(path_value)
        assert path.exists()
        assert path.read_text(encoding="utf-8").splitlines()[0]


def test_spectral_assessment_library_stratifies_long_period_runs(tmp_path: Path) -> None:
    config = {
        "sample_hz": 10.0,
        "block_minutes": 0.5,
        "lag_phase": {"search_window_s": 3.0, "expected_lag_s": 0.4},
        "correction_factor": {"factor_cap": 1.4},
    }
    pipeline = ECFCCPipeline()
    may_run = pipeline.run(
        rows=_rows(start=datetime(2026, 5, 27, 9, 0, 0)),
        project=ProjectProfile(code="PRJ-SPEC", name="Spectral Assessment"),
        site=SiteProfile(station_code="SITE-SPEC", station_name="Spectral Site"),
        config=config,
        data_source="unit-test-may",
        time_range="2026-05",
    )
    june_run = pipeline.run(
        rows=_rows(start=datetime(2026, 6, 3, 9, 0, 0)),
        project=ProjectProfile(code="PRJ-SPEC", name="Spectral Assessment"),
        site=SiteProfile(station_code="SITE-SPEC", station_name="Spectral Site"),
        config=config,
        data_source="unit-test-june",
        time_range="2026-06",
    )

    library = build_spectral_assessment_library(
        [may_run, june_run],
        dataset_id="spec-library-test",
        target_bins=12,
        group_by=["month", "qc_grade"],
        min_windows_per_group=1,
    )

    assert library["artifact_type"] == "spectral_assessment_library_v1"
    assert library["status"] == "ok"
    assert library["run_count"] == 2
    assert library["window_count"] == len(may_run.windows) + len(june_run.windows)
    assert {"all", "month:2026-05", "month:2026-06"}.issubset({group["group_id"] for group in library["groups"]})
    all_group = next(group for group in library["groups"] if group["group_id"] == "all")
    assert all_group["binned_ensemble"]["bin_count"] > 0
    assert "power_measured_std" in all_group["binned_ensemble"]["rows"][0]

    exporter = ResultExporter(runtime_root=tmp_path)
    export_root = tmp_path / "spectral_library"
    export_root.mkdir(parents=True)
    artifact_path, companion_files = exporter.export_spectral_assessment_library_artifact(
        spectral_runs=[may_run, june_run],
        export_root=export_root,
        dataset_id="spec-library-test",
        target_bins=12,
        group_by=["month", "qc_grade"],
    )

    assert artifact_path is not None
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["library_id"] == "spec-library-test"
    assert payload["group_count"] >= 3
    assert Path(companion_files["spectral_assessment_library_groups_csv"]).exists()
    bins_header = Path(companion_files["spectral_assessment_library_bins_csv"]).read_text(encoding="utf-8").splitlines()[0]
    assert "power_measured_std" in bins_header
