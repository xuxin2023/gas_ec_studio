from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from core.exports.result_exporter import ResultExporter


def _load_normalizer():
    path = Path("references/eddypro/normalize_reference.py")
    spec = importlib.util.spec_from_file_location("eddypro_reference_normalizer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalizer_extracts_method_metadata_from_sidecar(tmp_path: Path) -> None:
    normalizer = _load_normalizer()
    csv_path = tmp_path / "eddypro_full_output.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Filename,start_time,end_time,Fc,Fc_QC_Flag,co2_lag,rotation_method,WPL_water_vapor_term,total_density_correction",
                "w001,2026-01-01T00:00:00,2026-01-01T00:30:00,-3.2,0,2.4,double,0.01,0.02",
            ]
        ),
        encoding="utf-8",
    )
    metadata_path = tmp_path / "eddypro_project_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "processing_settings": {
                    "detrend_method": "block_average",
                    "frequency_correction": "analytical",
                    "footprint_method": "kljun",
                    "uncertainty_method": "finkelstein_sims",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    normalized = normalizer.normalize_csv(csv_path, metadata_path=metadata_path)
    window = normalized["windows"][0]
    assert window["window_id"] == "w001"
    assert window["primary_flux"] == -3.2
    assert window["qc_grade"] == "A"

    methods = normalized["method_metadata"]
    assert methods["rotation"]["availability"] == "reported"
    assert methods["density_correction"]["raw_method"] == "WPL"
    assert methods["footprint"]["raw_method"] == "kljun"
    assert methods["uncertainty"]["normalized_method"] == "finkelstein_sims"
    assert normalized["method_metadata_coverage"]["reported_count"] == 7

    provenance = normalizer.generate_provenance(normalized, csv_path)
    assert provenance["method_metadata"]["footprint"]["evidence_source"] in {"processing_settings", "metadata_sidecar"}
    assert provenance["method_metadata_coverage"]["total_count"] == 7


def test_result_exporter_uses_reference_method_metadata_payload(tmp_path: Path) -> None:
    reference_path = tmp_path / "ref_with_methods.json"
    reference_path.write_text(
        json.dumps(
            {
                "reference_id": "ref_with_methods",
                "source": "unit test",
                "processing_settings": {"rotation_mode": "double"},
                "method_metadata": {
                    "footprint": {
                        "reference_field": "footprint_method",
                        "raw_method": "kljun",
                        "normalized_method": "kljun",
                        "availability": "reported",
                        "evidence_source": "project_metadata",
                    },
                    "uncertainty": {
                        "reference_field": "uncertainty_method",
                        "raw_method": "finkelstein_sims",
                        "normalized_method": "finkelstein_sims",
                        "availability": "reported",
                        "evidence_source": "project_metadata",
                    },
                },
                "method_metadata_coverage": {
                    "reported_families": ["footprint", "uncertainty"],
                    "not_reported_families": [],
                    "reported_count": 2,
                    "total_count": 7,
                },
                "windows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    exporter = ResultExporter(runtime_root=tmp_path)
    exporter._reference_json_path = lambda _reference_id: reference_path  # type: ignore[method-assign]

    profile = exporter._reference_method_profile("ref_with_methods")
    assert profile["method_metadata"]["footprint"]["raw_method"] == "kljun"
    assert profile["method_metadata"]["footprint"]["evidence_source"] == "project_metadata"
    assert profile["method_metadata"]["uncertainty"]["availability"] == "reported"


def test_normalizer_accepts_target_to_source_custom_mapping(tmp_path: Path) -> None:
    normalizer = _load_normalizer()
    csv_path = tmp_path / "custom_full_output.csv"
    csv_path.write_text(
        "File,Start,End,CO2_flux\n"
        "w-1,2026-05-22T00:00:00,2026-05-22T00:30:00,-4.2\n",
        encoding="utf-8",
    )

    normalized = normalizer.normalize_csv(
        csv_path,
        field_mapping={
            "window_id": "File",
            "start_time": "Start",
            "end_time": "End",
            "primary_flux": "CO2_flux",
        },
    )

    assert normalized["windows"][0]["window_id"] == "w-1"
    assert normalized["windows"][0]["primary_flux"] == -4.2
    assert normalized["field_mapping"]["CO2_flux"] == "primary_flux"
