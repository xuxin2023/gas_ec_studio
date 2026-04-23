from __future__ import annotations

import json
from pathlib import Path

from models.hf_models import ProtocolFrame


class RawStreamStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "raw_stream.jsonl"

    def append(self, frame: ProtocolFrame) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(frame.to_json_dict(), ensure_ascii=False) + "\n")
