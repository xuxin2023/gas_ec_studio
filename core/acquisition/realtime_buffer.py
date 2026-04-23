from __future__ import annotations

from collections import deque

from models.hf_models import NormalizedHFFrame


class RealtimeBuffer:
    def __init__(self, maxlen: int = 1800) -> None:
        self._frames: deque[NormalizedHFFrame] = deque(maxlen=maxlen)

    def append(self, frame: NormalizedHFFrame) -> None:
        self._frames.append(frame)

    def clear(self, *, device_uid: str | None = None) -> None:
        if device_uid is None:
            self._frames.clear()
            return
        self._frames = deque(
            [frame for frame in self._frames if frame.device_uid != device_uid],
            maxlen=self._frames.maxlen,
        )

    def snapshot(
        self,
        *,
        device_uid: str | None = None,
        seconds: float | None = None,
    ) -> list[NormalizedHFFrame]:
        rows = list(self._frames)
        if device_uid is None:
            filtered = rows
        else:
            filtered = [row for row in rows if row.device_uid == device_uid]
        if seconds is None or not filtered:
            return filtered
        end_time = filtered[-1].timestamp
        threshold = end_time.timestamp() - max(0.0, float(seconds))
        return [row for row in filtered if row.timestamp.timestamp() >= threshold]
