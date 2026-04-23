from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from app.pages.project_site_page import ProjectSitePage
from app.studio import StudioController
from core.headless_batch_runner import run_cli
from models.hf_models import FrameQuality, NormalizedHFFrame


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    return app or QApplication([])


def _make_rows(sample_hz: float = 10.0, samples: int = 240) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.35 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.55 * np.sin(2.0 * np.pi * 0.19 * time_axis) + 0.12 * np.cos(2.0 * np.pi * 0.67 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-1",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 9.0 * np.roll(w, 5)[index]),
                h2o_mmol=float(12.0 + 1.3 * np.roll(w, 3)[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.8,
                case_temp_c=24.7,
                raw_text=json.dumps({"u": float(u[index]), "v": float(v[index]), "w": float(w[index])}),
            )
        )
    return rows


def test_project_site_page_metadata_persists_to_store(monkeypatch, tmp_path: Path) -> None:
    _app()
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        page = ProjectSitePage(controller)
        page.station_latitude_spin.setValue(30.123456)
        page.station_longitude_spin.setValue(120.654321)
        page.sonic_model_meta_edit.setText("CSAT3B")
        page.analyzer_model_meta_edit.setText("LI-7500DS")
        page.raw_column_mappings_edit.setPlainText(
            json.dumps(
                [
                    {
                        "column_name": "co2_ppm",
                        "ignore": False,
                        "numeric": True,
                        "variable": "co2",
                        "instrument": "gas-main",
                        "measurement_type": "mole_fraction",
                        "input_unit": "ppm",
                        "output_unit": "ppm",
                        "scaling": 1.0,
                        "nominal_lag": 2.0,
                        "min_lag": 0.5,
                        "max_lag": 6.0,
                    }
                ],
                ensure_ascii=False,
            )
        )
        page.metadata_profile_combo.setEditText("field-a")

        assert page._save(show_message=False)
        controller.save_metadata_profile("field-a")

        bundle = controller.metadata_bundle()
        active_doc = controller.metadata_store.load_metadata_document("active_metadata")
        assert bundle.site.latitude == 30.123456
        assert bundle.site.longitude == 120.654321
        assert bundle.instruments.sonic_model == "CSAT3B"
        assert bundle.raw_file_description.column_mappings[0].column_name == "co2_ppm"
        assert active_doc is not None
        assert active_doc["site"]["latitude"] == 30.123456
        assert "field-a" in controller.metadata_profile_names()
    finally:
        controller.shutdown()


def test_headless_cli_writes_deterministic_manifest(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    metadata_path = tmp_path / "metadata.json"
    input_path = tmp_path / "rows.json"
    output_path = tmp_path / "manifest.json"

    config_path.write_text(
        json.dumps(
            {
                "sample_hz": 10.0,
                "block_minutes": 0.4,
                "rotation_mode": "triple",
                "detrend_mode": "linear",
                "lag_phase": {"search_window_s": 1.5, "expected_lag_s": 0.5},
                "output": {"full_output_mode": "standard_schema"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "project": {"name": "CLI", "code": "CLI-001", "principal": "test", "archive_root": str(tmp_path), "notes": ""},
                "site": {
                    "station_name": "CLI Site",
                    "station_code": "CLI-S",
                    "location": "test",
                    "canopy_height_m": 1.0,
                    "altitude_m": 10.0,
                    "timezone": "Asia/Shanghai",
                    "latitude": 31.2,
                    "longitude": 121.4,
                    "timestamp_refers_to": "end_of_averaging_period",
                    "file_duration": 30.0,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    input_path.write_text(json.dumps([row.to_record() for row in _make_rows()], ensure_ascii=False, indent=2), encoding="utf-8")

    exit_code = run_cli(
        [
            "--config",
            str(config_path),
            "--metadata",
            str(metadata_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--time-range",
            "demo",
        ]
    )
    manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert manifest["batch_id"]
    assert manifest["rp_run"]["run_id"].startswith("rp_det_")
    assert manifest["spectral_run"]["run_id"].startswith("spectral_det_")
    assert manifest["site_snapshot"]["latitude"] == 31.2
