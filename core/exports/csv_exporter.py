from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_rows_to_csv(rows: list[dict], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(target, index=False)
    return target
