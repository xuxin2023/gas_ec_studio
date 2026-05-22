from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from models.hf_models import NormalizedHFFrame


PARQUET_ENGINE_MESSAGE = (
    "Parquet storage requires a pandas parquet engine. Install pyarrow or fastparquet; "
    "project dependencies use pyarrow for the supported path."
)


class HFDataStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append_csv(self, frame: NormalizedHFFrame) -> Path:
        device_dir = self.root / frame.device_uid
        device_dir.mkdir(parents=True, exist_ok=True)
        csv_path = device_dir / f"{frame.timestamp:%Y%m%d}_hf.csv"
        row = pd.DataFrame([frame.to_record()])
        header = not csv_path.exists()
        row.to_csv(csv_path, mode="a", header=header, index=False)
        return csv_path

    def export_buffer_to_csv(self, rows: list[dict], target_path: Path) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(target, index=False)
        return target

    def append_parquet(self, frame: NormalizedHFFrame) -> Path:
        device_dir = self.root / frame.device_uid
        device_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = device_dir / f"{frame.timestamp:%Y%m%d}_hf.parquet"
        self._write_parquet_records([frame.to_record()], parquet_path, append=True)
        return parquet_path

    def export_buffer_to_parquet(self, rows: list[dict[str, Any]], target_path: Path) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_parquet_records(rows, target, append=False)
        return target

    def append_parquet_placeholder(self, frame: NormalizedHFFrame) -> Path:
        return self.append_parquet(frame)

    def _write_parquet_records(self, records: list[dict[str, Any]], target_path: Path, *, append: bool) -> None:
        frame = pd.DataFrame(records)
        if append and target_path.exists():
            try:
                existing = pd.read_parquet(target_path)
            except (ImportError, ValueError) as exc:
                raise RuntimeError(PARQUET_ENGINE_MESSAGE) from exc
            frame = pd.concat([existing, frame], ignore_index=True, sort=False)
        try:
            frame.to_parquet(target_path, index=False)
        except (ImportError, ValueError) as exc:
            raise RuntimeError(PARQUET_ENGINE_MESSAGE) from exc
