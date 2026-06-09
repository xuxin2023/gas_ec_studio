from __future__ import annotations

from collections import Counter
from pathlib import Path

from app import studio as studio_module
from app.studio import StudioController
from core.exports import result_exporter as result_exporter_module
from core.exports.result_exporter import ResultExporter


def _summary() -> dict:
    return {
        "artifact_type": "fixture_pack_summary_v1",
        "status": "pass",
        "asset_count": 1,
        "assets": [{"fixture_id": "cache_fixture", "tier": "raw_to_final_parity", "status": "pass"}],
        "public_eddypro_fixture_catalog": {"status": "pass", "fixture_count": 1, "valid_fixture_count": 1},
        "truthfulness_note": "cache test fixture",
    }


def _manifest() -> dict:
    return {
        "artifact_type": "official_raw_fixture_pack_manifest_v2",
        "status": "needs_official_raw_fixtures",
        "assets": [{"fixture_id": "cache_fixture", "readiness_level": "synthetic_guardrail"}],
        "evidence_matrix": {"rows": [{"fixture_id": "cache_fixture", "tier": "raw_to_final_parity"}]},
    }


def test_studio_fixture_pack_cache_reuses_summary_manifest_and_detail(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()

    def fake_summary(*_args, **_kwargs) -> dict:
        calls["summary"] += 1
        return _summary()

    def fake_manifest(*_args, **_kwargs) -> dict:
        calls["manifest"] += 1
        return _manifest()

    def fake_detail(*_args, fixture_id: str = "", **_kwargs) -> dict:
        calls["detail"] += 1
        return {
            "artifact_type": "official_raw_fixture_detail_v1",
            "fixture_id": fixture_id,
            "status": "pass",
            "readiness_level": "synthetic_guardrail",
        }

    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    monkeypatch.setattr(studio_module, "build_fixture_pack_summary", fake_summary)
    monkeypatch.setattr(studio_module, "build_official_raw_fixture_manifest", fake_manifest)
    monkeypatch.setattr(studio_module, "build_official_raw_fixture_detail", fake_detail)
    pack_path = tmp_path / "fixture_pack.json"
    pack_path.write_text('{"assets": []}', encoding="utf-8")

    controller = StudioController(workspace_root=tmp_path)
    try:
        assert controller._cached_fixture_pack_summary(pack_path, workspace_root=tmp_path)["status"] == "pass"
        assert controller._cached_fixture_pack_summary(pack_path, workspace_root=tmp_path)["status"] == "pass"
        assert calls["summary"] == 1

        assert controller._cached_official_raw_fixture_manifest(pack_path, workspace_root=tmp_path)["artifact_type"].endswith("_v2")
        assert controller._cached_official_raw_fixture_manifest(pack_path, workspace_root=tmp_path)["artifact_type"].endswith("_v2")
        assert calls["manifest"] == 1

        assert controller._cached_official_raw_fixture_detail("cache_fixture", pack_path=pack_path, workspace_root=tmp_path)["fixture_id"] == "cache_fixture"
        assert controller._cached_official_raw_fixture_detail("cache_fixture", pack_path=pack_path, workspace_root=tmp_path)["fixture_id"] == "cache_fixture"
        assert calls["detail"] == 1
        assert controller.report_center_workspace["fixture_pack_cache"]["status"] == "hit"

        controller._invalidate_fixture_pack_cache("unit_test")
        assert controller.report_center_workspace["fixture_pack_cache"]["status"] == "invalidated"
        controller._cached_fixture_pack_summary(pack_path, workspace_root=tmp_path)
        assert calls["summary"] == 2
    finally:
        controller.shutdown()


def test_result_exporter_fixture_pack_cache_tracks_hit_and_file_signature(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()

    def fake_summary(*_args, **_kwargs) -> dict:
        calls["summary"] += 1
        return _summary()

    def fake_catalog(*_args, **_kwargs) -> dict:
        calls["catalog"] += 1
        return {"status": "pass", "fixture_count": 1, "valid_fixture_count": 1}

    def fake_manifest(*_args, **_kwargs) -> dict:
        calls["manifest"] += 1
        return _manifest()

    monkeypatch.setattr(result_exporter_module, "build_fixture_pack_summary", fake_summary)
    monkeypatch.setattr(result_exporter_module, "build_public_eddypro_fixture_catalog", fake_catalog)
    monkeypatch.setattr(result_exporter_module, "build_official_raw_fixture_manifest", fake_manifest)
    pack_path = tmp_path / "fixture_pack.json"
    pack_path.write_text('{"assets": []}', encoding="utf-8")
    exporter = ResultExporter(tmp_path)

    first = exporter._cached_fixture_pack_artifacts(fixture_pack_path=str(pack_path), workspace_root=str(tmp_path))
    second = exporter._cached_fixture_pack_artifacts(fixture_pack_path=str(pack_path), workspace_root=str(tmp_path))

    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert calls["summary"] == 1
    assert calls["manifest"] == 1
    assert calls["catalog"] == 0

    pack_path.write_text('{"assets": [], "changed": true}', encoding="utf-8")
    third = exporter._cached_fixture_pack_artifacts(fixture_pack_path=str(pack_path), workspace_root=str(tmp_path))

    assert third["cache"]["status"] == "miss"
    assert calls["summary"] == 2


def test_result_exporter_eddypro_artifact_cache_reuses_until_pack_signature_changes(tmp_path: Path) -> None:
    calls: Counter[str] = Counter()
    pack_path = tmp_path / "fixture_pack.json"
    pack_path.write_text('{"assets": []}', encoding="utf-8")
    exporter = ResultExporter(tmp_path)

    def build_artifact() -> dict:
        calls["stress_suite"] += 1
        return {"artifact_type": "unit_artifact_v1", "call_count": calls["stress_suite"]}

    first_key = exporter._fixture_pack_cache_key(pack_path, tmp_path)
    first, first_cache = exporter._cached_eddypro_export_artifact("stress_suite", first_key, build_artifact)
    second, second_cache = exporter._cached_eddypro_export_artifact("stress_suite", first_key, build_artifact)

    assert first["call_count"] == 1
    assert second["call_count"] == 1
    assert first_cache["status"] == "miss"
    assert second_cache["status"] == "hit"
    assert second_cache["hit_count"] == 1
    assert calls["stress_suite"] == 1

    pack_path.write_text('{"assets": [], "changed": true}', encoding="utf-8")
    changed_key = exporter._fixture_pack_cache_key(pack_path, tmp_path)
    third, third_cache = exporter._cached_eddypro_export_artifact("stress_suite", changed_key, build_artifact)

    assert third["call_count"] == 2
    assert third_cache["status"] == "miss"
    assert calls["stress_suite"] == 2
