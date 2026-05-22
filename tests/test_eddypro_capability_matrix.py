from __future__ import annotations

import json
from pathlib import Path


def test_capability_matrix_is_truthful_about_full_eddypro_parity() -> None:
    matrix = json.loads(Path("docs/benchmark/eddypro_capability_matrix.json").read_text(encoding="utf-8"))

    assert matrix["overall_status"] == "not_full_eddypro_parity_yet"
    assert "does not yet implement every EddyPro" in matrix["truthfulness_note"]
    statuses = {item["gas_ec_status"] for item in matrix["capabilities"]}
    assert {"covered", "partial", "missing", "beyond_eddypro"}.issubset(statuses)
    assert any(item["id"] == "ch4_trace_gas_fluxes" and item["gas_ec_status"] == "missing" for item in matrix["capabilities"])
    assert any(item["id"] == "raw_ghg_bundle" and item["gas_ec_status"] == "covered" for item in matrix["capabilities"])
    assert any(item["id"] == "raw_ascii_csv" and item["gas_ec_status"] == "covered" for item in matrix["capabilities"])
    assert any(
        item["id"] == "raw_ghg_real_world_fixture_breadth" and item["gas_ec_status"] == "partial"
        for item in matrix["capabilities"]
    )


def test_capability_matrix_schema_and_counts_are_consistent() -> None:
    matrix = json.loads(Path("docs/benchmark/eddypro_capability_matrix.json").read_text(encoding="utf-8"))
    capabilities = matrix["capabilities"]
    ids = [item["id"] for item in capabilities]
    counts = matrix["coverage_summary"]

    assert len(ids) == len(set(ids))
    for item in capabilities:
        assert item["family"]
        assert item["eddypro_requirement"] or item["gas_ec_status"] == "beyond_eddypro"
        assert item["gas_ec_status"] in {"covered", "partial", "missing", "beyond_eddypro"}
        assert "evidence" in item
        assert "gap" in item
        assert "next_action" in item

    assert counts["covered"] == sum(1 for item in capabilities if item["gas_ec_status"] == "covered")
    assert counts["partial"] == sum(1 for item in capabilities if item["gas_ec_status"] == "partial")
    assert counts["missing"] == sum(1 for item in capabilities if item["gas_ec_status"] == "missing")
    assert counts["beyond_eddypro"] == sum(1 for item in capabilities if item["gas_ec_status"] == "beyond_eddypro")


def test_capability_matrix_sources_are_official_licor_urls() -> None:
    matrix = json.loads(Path("docs/benchmark/eddypro_capability_matrix.json").read_text(encoding="utf-8"))

    assert matrix["official_sources"]
    for source in matrix["official_sources"]:
        assert source["url"].startswith("https://")
        assert "licor.com" in source["url"]
        assert source["used_for"]
