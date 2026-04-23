from __future__ import annotations

import re
from typing import Iterable


TOKEN_RE = re.compile(
    r"C(?P<index>\d+)\s*:\s*(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
    re.IGNORECASE,
)


def encode_coefficients(values: Iterable[float]) -> list[str]:
    return [f"{float(value):.6g}" for value in values]


def parse_coefficient_line(text: str) -> dict[str, float] | None:
    candidate = str(text or "").strip().strip("<>")
    if not candidate:
        return None
    matches = list(TOKEN_RE.finditer(candidate))
    if not matches:
        return None
    parsed: dict[str, float] = {}
    for match in matches:
        parsed[f"C{int(match.group('index'))}"] = float(match.group("value"))
    return parsed
