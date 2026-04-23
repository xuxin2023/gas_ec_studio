from __future__ import annotations

import re
from dataclasses import dataclass


ACK_RE = re.compile(
    r"(?P<head>YGAS)\s*,\s*(?P<device_id>[0-9A-F]{3})\s*,\s*(?P<flag>[TF])(?:\s*,\s*(?P<message>.*))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AckFrame:
    device_id: str
    success: bool
    message: str = ""


def parse_ack(text: str) -> AckFrame | None:
    candidate = str(text or "").strip().strip("<>")
    if not candidate:
        return None
    match = ACK_RE.search(candidate)
    if not match:
        return None
    return AckFrame(
        device_id=match.group("device_id").upper(),
        success=match.group("flag").upper() == "T",
        message=(match.group("message") or "").strip(),
    )
