from __future__ import annotations

from collections import Counter
from pathlib import Path

from app import studio as studio_module
from app.studio import StudioController
from core.comparison import fixture_pack as fixture_pack_module
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


def test_fixture_pack_summary_builder_cache_reuses_file_signature(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()

    def fake_validate(asset: dict, **_kwargs) -> dict:
        calls["validate"] += 1
        return {
            "fixture_id": asset.get("fixture_id", ""),
            "tier": asset.get("tier", ""),
            "status": "pass",
            "errors": [],
            "raw_to_final_parity": {"status": "pass"},
        }

    def public_summary(**_kwargs) -> dict:
        return {"status": "pass", "fixture_count": 0, "valid_fixture_count": 0, "errors": []}

    monkeypatch.setattr(fixture_pack_module, "validate_fixture_asset", fake_validate)
    monkeypatch.setattr(
        fixture_pack_module,
        "build_eddypro_source_inventory",
        lambda: {"feature_count": 0, "present_feature_count": 0, "missing_feature_count": 0, "repositories": {}},
    )
    monkeypatch.setattr(fixture_pack_module, "build_public_spectral_fixture_summary", public_summary)
    monkeypatch.setattr(fixture_pack_module, "build_public_full_output_fixture_summary", public_summary)
    monkeypatch.setattr(fixture_pack_module, "build_public_official_raw_fixture_summary", public_summary)
    monkeypatch.setattr(fixture_pack_module, "build_public_raw_search_summary", public_summary)
    monkeypatch.setattr(
        fixture_pack_module,
        "build_public_eddypro_fixture_catalog",
        lambda **_kwargs: {"status": "pass", "fixture_count": 0, "valid_fixture_count": 0, "errors": []},
    )

    pack_path = tmp_path / "fixture_pack.json"
    pack_path.write_text(
        '{"fixture_pack_id":"unit","version":"1","assets":[{"fixture_id":"cache_fixture","tier":"raw_to_final_parity"}]}',
        encoding="utf-8",
    )

    first = fixture_pack_module.build_fixture_pack_summary(pack_path, workspace_root=tmp_path, use_cache=False)
    first["assets"][0]["fixture_id"] = "mutated"
    second = fixture_pack_module.build_fixture_pack_summary(pack_path, workspace_root=tmp_path)

    assert calls["validate"] == 1
    assert second["assets"][0]["fixture_id"] == "cache_fixture"

    pack_path.write_text(
        (
            '{"fixture_pack_id":"unit","version":"2",'
            '"assets":[{"fixture_id":"cache_fixture","tier":"raw_to_final_parity"}]}'
        ),
        encoding="utf-8",
    )
    fixture_pack_module.build_fixture_pack_summary(pack_path, workspace_root=tmp_path)

    assert calls["validate"] == 2


def test_raw_to_final_asset_validation_reuses_harness_cache(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()
    cache_dir = tmp_path / "raw_to_final_cache"
    raw_path = tmp_path / "raw.csv"
    reference_path = tmp_path / "reference.json"
    raw_path.write_text("timestamp,co2\n2026-01-01T00:00:00,410\n", encoding="utf-8")
    reference_path.write_text('{"reference_id":"ref","windows":[]}', encoding="utf-8")
    asset = {
        "fixture_id": "cache_raw_to_final",
        "tier": "raw_to_final_parity",
        "raw_file": str(raw_path),
        "reference_json": str(reference_path),
    }

    def fake_harness(**_kwargs) -> dict:
        calls["harness"] += 1
        return {
            "artifact_type": "eddypro_raw_to_final_parity_v1",
            "fixture_id": "cache_raw_to_final",
            "status": "pass",
            "raw_input": {"row_count": 1, "import_summary": {"format": "csv"}},
            "pipeline": {"window_count": 0},
            "reference": {"reference_window_count": 0},
            "benchmark_summary": {"status": "pass", "pass_rate": 1.0, "failed_fields": []},
            "trace_gas_parity": {},
            "trace_gas_provenance_summary": {},
            "li7700_level_parity": {},
            "parity_diagnostics": {"artifact_type": "raw_to_final_parity_diagnostics_v1", "status": "ok"},
            "known_limitations": [],
            "truthfulness_note": "cache unit test",
        }

    monkeypatch.setenv("GAS_EC_RAW_TO_FINAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(fixture_pack_module, "run_raw_to_final_parity_harness", fake_harness)

    first = fixture_pack_module.validate_fixture_asset(asset, workspace_root=tmp_path)
    second = fixture_pack_module.validate_fixture_asset(asset, workspace_root=tmp_path)

    assert first["status"] == "pass"
    assert second["status"] == "pass"
    assert second["raw_to_final_cache"]["status"] == "hit"
    assert calls["harness"] == 1


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


def test_result_exporter_eddypro_artifact_persistent_cache_reuses_across_instances(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()
    cache_dir = tmp_path / "persistent_eddypro_artifact_cache"
    pack_path = tmp_path / "fixture_pack.json"
    pack_path.write_text('{"assets": []}', encoding="utf-8")
    monkeypatch.setenv("GAS_EC_EDDYPRO_ARTIFACT_CACHE_DIR", str(cache_dir))
    ResultExporter._shared_eddypro_artifact_cache.clear()

    def build_artifact() -> dict:
        calls["stress_suite"] += 1
        return {"artifact_type": "eddypro_computation_stress_suite_v1", "call_count": calls["stress_suite"]}

    first_exporter = ResultExporter(tmp_path / "runtime_one")
    first_key = first_exporter._fixture_pack_cache_key(pack_path, tmp_path)
    first, first_cache = first_exporter._cached_eddypro_export_artifact(
        "eddypro_computation_stress_suite",
        first_key,
        build_artifact,
    )

    ResultExporter._shared_eddypro_artifact_cache.clear()
    second_exporter = ResultExporter(tmp_path / "runtime_two")
    second_key = second_exporter._fixture_pack_cache_key(pack_path, tmp_path)
    second, second_cache = second_exporter._cached_eddypro_export_artifact(
        "eddypro_computation_stress_suite",
        second_key,
        build_artifact,
    )

    assert first["call_count"] == 1
    assert second["call_count"] == 1
    assert first_cache["status"] == "miss"
    assert second_cache["status"] == "persistent_hit"
    assert calls["stress_suite"] == 1
