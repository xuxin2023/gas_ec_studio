from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from core.storage.hf_data_store import HFDataStore
from models.hf_models import FrameQuality, NormalizedHFFrame


pytest.importorskip("pyarrow")


def _frame(index: int) -> NormalizedHFFrame:
    return NormalizedHFFrame(
        timestamp=datetime(2026, 5, 22, 10, 0, 0) + timedelta(seconds=index),
        device_uid="tower-a",
        device_id="analyzer-1",
        mode=2,
        frame_quality=FrameQuality.FULL,
        co2_ppm=410.0 + index,
        h2o_mmol=12.0 + index * 0.1,
        pressure_kpa=101.3,
        chamber_temp_c=24.0,
        case_temp_c=23.8,
        raw_text='{"u": 2.0, "v": 0.1, "w": 0.2}',
    )


def test_append_parquet_persists_daily_device_file(tmp_path) -> None:
    store = HFDataStore(tmp_path)

    path = store.append_parquet(_frame(0))
    second_path = store.append_parquet(_frame(1))

    assert second_path == path
    assert path.name == "20260522_hf.parquet"
    assert path.parent.name == "tower-a"
    table = pd.read_parquet(path)
    assert len(table) == 2
    assert list(table["co2_ppm"]) == [410.0, 411.0]
    assert list(table["frame_quality"]) == ["FULL", "FULL"]


def test_export_buffer_to_parquet_writes_requested_target(tmp_path) -> None:
    store = HFDataStore(tmp_path)
    target = tmp_path / "exports" / "buffer.parquet"
    rows = [_frame(0).to_record(), _frame(1).to_record()]

    path = store.export_buffer_to_parquet(rows, target)

    assert path == target
    table = pd.read_parquet(path)
    assert len(table) == 2
    assert table.iloc[1]["device_uid"] == "tower-a"
