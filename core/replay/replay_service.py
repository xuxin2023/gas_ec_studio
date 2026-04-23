from __future__ import annotations

import json
from pathlib import Path


class ReplayService:
    def __init__(self, source_path: Path) -> None:
        self.source_path = Path(source_path)

    def iter_raw_frames(self) -> list[dict]:
        if not self.source_path.exists():
            return []
        rows: list[dict] = []
        for line in self.source_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows
