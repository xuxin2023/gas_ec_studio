from __future__ import annotations

from pathlib import Path

import pandas as pd

from models.hf_models import NormalizedHFFrame


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

    def append_parquet_placeholder(self, frame: NormalizedHFFrame) -> Path:
        device_dir = self.root / frame.device_uid
        device_dir.mkdir(parents=True, exist_ok=True)
        return device_dir / f"{frame.timestamp:%Y%m%d}_hf.parquet"
