from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from core.exports.eddypro_bridge import EddyProBridgeExporter
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import ProjectProfile, SiteProfile


def _make_rows(samples: int = 8) -> list[NormalizedHFFrame]:
    start = datetime(2026, 4, 18, 9, 0, 0)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(milliseconds=index * 100),
                device_uid="dev-bridge",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=410.0 + index * 0.2,
                h2o_mmol=12.0 + index * 0.05,
                pressure_kpa=101.3,
                chamber_temp_c=25.0,
                case_temp_c=24.8,
                raw_text=json.dumps({"u": 2.1 + index * 0.01, "v": 0.4, "w": 0.2 - index * 0.005}),
            )
        )
    return rows


def test_eddypro_bridge_exports_paired_ascii_and_metadata(tmp_path: Path) -> None:
    exporter = EddyProBridgeExporter(tmp_path)
    result = exporter.export_bridge_bundle(
        rows=_make_rows(),
        project=ProjectProfile(name="Bridge Project", code="BR-001"),
        site=SiteProfile(station_name="Bridge Site", station_code="SITE-B"),
        config_snapshot={"sample_hz": 10.0, "block_minutes": 30.0},
        data_source_label="runtime_buffer:selected_device",
    )

    ascii_path = Path(result["ascii_path"])
    metadata_path = Path(result["metadata_path"])

    assert ascii_path.exists()
    assert metadata_path.exists()
    assert ascii_path.read_text(encoding="utf-8").strip() != ""
    assert metadata_path.read_text(encoding="utf-8").strip() != ""

    lines = ascii_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 1
    assert "TIMESTAMP" in lines[0]
    assert "CO2_PPM" in lines[0]

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["data_source"]["row_count"] == 8
    assert metadata["metadata_snapshot"]["project"]["code"] == "BR-001"
    assert metadata["metadata_snapshot"]["site"]["station_code"] == "SITE-B"
    assert metadata["field_mapping"]
    assert metadata["paired_files"]["ascii_data_file"].endswith("hf_ascii.txt")
