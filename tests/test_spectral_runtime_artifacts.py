from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta

from core.exports.evidence_exporter import EvidenceExporter
from core.storage.run_result_store import RunResultStore
from models.spectral_models import EvidenceBundleManifest, SpectralRunResult, WindowSpectralResult
from models.station_models import ProjectProfile, SiteProfile


def _sample_window(window_id: str = "w-001") -> WindowSpectralResult:
    return WindowSpectralResult(
        window_id=window_id,
        start_time=datetime(2026, 4, 18, 8, 0, 0),
        end_time=datetime(2026, 4, 18, 8, 30, 0),
        qc_grade="A",
        anomaly_type="none",
        lag_seconds=1.2,
        lag_confidence=0.93,
        correction_factor=1.08,
        high_freq_loss_risk="low",
        reason="baseline skeleton",
        lag_curve_x=[0.0, 1.0],
        lag_curve_y=[0.1, 0.2],
        power_freq=[0.1, 0.2],
        power_measured=[1.0, 0.9],
        power_ref=[1.1, 1.0],
        cross_freq=[0.1],
        cross_value=[0.8],
        ogive_freq=[0.1],
        ogive_value=[0.6],
        qc_band_value=0.75,
    )


def _sample_run(run_id: str = "run-001", created_at: datetime | None = None) -> SpectralRunResult:
    return SpectralRunResult(
        run_id=run_id,
        created_at=created_at or datetime(2026, 4, 18, 9, 0, 0),
        data_source="hf_buffer",
        time_range="2026-04-18 08:00~08:30",
        qc_only=True,
        summary={"window_count": 1, "note": "skeleton"},
        windows=[_sample_window()],
        artifacts={"version": 1},
    )


def test_spectral_models_roundtrip() -> None:
    run = _sample_run()
    restored = SpectralRunResult.from_dict(run.to_dict())

    assert restored.run_id == run.run_id
    assert restored.created_at == run.created_at
    assert restored.summary == run.summary
    assert restored.windows[0].window_id == run.windows[0].window_id
    assert restored.windows[0].power_measured == run.windows[0].power_measured

    manifest = EvidenceBundleManifest(
        bundle_id="bundle-001",
        export_time=datetime(2026, 4, 18, 10, 0, 0),
        root_dir="D:/tmp/evidence",
        included_files=["manifest.json", "summary.json"],
        summary_text="ok",
    )
    assert EvidenceBundleManifest.from_dict(manifest.to_dict()) == manifest


def test_run_result_store_save_load_and_list_recent(tmp_path) -> None:
    store = RunResultStore(tmp_path / "run_results")
    newest = _sample_run("run-new", datetime(2026, 4, 18, 11, 0, 0))
    older = _sample_run("run-old", datetime(2026, 4, 18, 10, 0, 0))

    store.save_spectral_run(older)
    store.save_spectral_run(newest)

    loaded = store.load_spectral_run("run-new")
    recent = store.list_recent_runs(limit=2)
    previous = store.get_previous_batch("run-new")

    assert loaded is not None
    assert loaded.run_id == "run-new"
    assert [item.run_id for item in recent] == ["run-new", "run-old"]
    assert previous is not None
    assert previous.run_id == "run-old"

    index_payload = json.loads((tmp_path / "run_results" / "spectral_runs_index.json").read_text(encoding="utf-8"))
    assert [item["run_id"] for item in index_payload] == ["run-new", "run-old"]


def test_run_result_store_builds_and_persists_spectral_library(tmp_path) -> None:
    store = RunResultStore(tmp_path / "run_results")
    store.save_spectral_run(_sample_run("run-2026-04", datetime(2026, 4, 18, 10, 0, 0)))
    store.save_spectral_run(_sample_run("run-2026-05", datetime(2026, 5, 18, 10, 0, 0)))

    library = store.build_spectral_assessment_library(
        dataset_id="stored-library",
        target_bins=4,
        group_by=["month", "qc_grade"],
        min_windows_per_group=1,
    )
    path = store.save_spectral_assessment_library(library)
    loaded = store.latest_spectral_assessment_library()

    assert path.exists()
    assert library["artifact_type"] == "spectral_assessment_library_v1"
    assert library["library_id"] == "stored-library"
    assert library["status"] == "ok"
    assert loaded is not None
    assert loaded["library_id"] == "stored-library"


def test_evidence_exporter_writes_bundle_to_disk(tmp_path) -> None:
    exporter = EvidenceExporter(tmp_path)
    run = _sample_run("run-export", datetime.now() - timedelta(minutes=5))

    manifest = exporter.export_spectral_qc_evidence(
        run_result=run,
        config_snapshot={"lag_phase": {"expected_lag_s": 1.5}},
        project=ProjectProfile(name="Test Project", code="TP-001"),
        site=SiteProfile(station_name="Test Site", station_code="TS-001"),
    )

    export_root = tmp_path / "exports" / "evidence"
    bundle_root = next(export_root.iterdir())

    assert bundle_root.name.startswith("spectral_qc_")
    assert manifest.root_dir == str(bundle_root)

    expected_files = {
        "manifest.json",
        "summary.json",
        "qc_windows.csv",
        "current_config_snapshot.json",
        "project_site_snapshot.json",
    }
    assert expected_files.issubset({path.name for path in bundle_root.iterdir()})

    summary_payload = json.loads((bundle_root / "summary.json").read_text(encoding="utf-8"))
    assert summary_payload["run_id"] == "run-export"

    with (bundle_root / "qc_windows.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["window_id"] == "w-001"
