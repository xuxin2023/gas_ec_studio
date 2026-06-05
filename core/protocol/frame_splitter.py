from __future__ import annotations

import re
from dataclasses import dataclass

from core.protocol.ack_parser import parse_ack
from core.protocol.coefficient_codec import parse_coefficient_line
from core.protocol.licor_diag_parser import parse_licor_diag_frame
from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from core.protocol.parameter_parser import parse_parameter_response
from models.hf_models import FrameQuality


FRAME_START_RE = re.compile(r"(?:YGAS\s*,|LICOR\s*,|LI-?7(?:200|500)(?:A|DS|RS)?\s*[,;\s])", re.IGNORECASE)


@dataclass(slots=True)
class FrameChunk:
    text: str
    quality: FrameQuality


def classify_frame_text(text: str) -> FrameQuality:
    candidate = str(text or "").strip()
    if not candidate:
        return FrameQuality.UNKNOWN
    if parse_ack(candidate):
        return FrameQuality.ACK_ONLY
    if parse_mode2_frame(candidate):
        return parse_mode2_frame(candidate)["frame_quality"]
    if parse_mode1_frame(candidate):
        return parse_mode1_frame(candidate)["frame_quality"]
    licor = parse_licor_diag_frame(candidate)
    if licor:
        return licor["frame_quality"]
    if parse_coefficient_line(candidate):
        return FrameQuality.FULL
    if parse_parameter_response(candidate):
        return FrameQuality.FULL
    if any(token in candidate.upper() for token in ("YGAS", "LICOR", "LI7200", "LI-7200", "LI7500", "LI-7500")):
        return FrameQuality.CORRUPTED
    return FrameQuality.UNKNOWN


class FrameSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[FrameChunk]:
        self._buffer += str(chunk or "")
        return self._extract(finalize=False)

    def flush(self) -> list[FrameChunk]:
        return self._extract(finalize=True)

    def _extract(self, *, finalize: bool) -> list[FrameChunk]:
        buffer = self._buffer.replace("\r", "\n")
        starts = [match.start() for match in FRAME_START_RE.finditer(buffer)]
        frames: list[FrameChunk] = []
        if not starts:
            if finalize and buffer.strip():
                self._buffer = ""
                return [FrameChunk(buffer.strip(), FrameQuality.CORRUPTED)]
            self._buffer = buffer
            return frames

        last_consumed = 0
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else None
            if start > last_consumed:
                prefix = buffer[last_consumed:start].strip()
                if prefix:
                    frames.append(FrameChunk(prefix, FrameQuality.CORRUPTED))
            if end is None:
                tail = buffer[start:]
                if finalize:
                    frames.append(FrameChunk(tail.strip(), self._final_quality(tail)))
                    last_consumed = len(buffer)
                else:
                    if "\n" in tail or self._looks_complete(tail):
                        candidate = tail.strip()
                        if candidate:
                            frames.append(FrameChunk(candidate, classify_frame_text(candidate)))
                            last_consumed = len(buffer)
                        else:
                            last_consumed = start
                    else:
                        last_consumed = start
                break
            candidate = buffer[start:end].strip()
            if candidate:
                frames.append(FrameChunk(candidate, classify_frame_text(candidate)))
            last_consumed = end

        self._buffer = "" if last_consumed >= len(buffer) else buffer[last_consumed:]
        return frames

    def _looks_complete(self, text: str) -> bool:
        quality = classify_frame_text(text)
        return quality in {FrameQuality.FULL, FrameQuality.ACK_ONLY}

    def _final_quality(self, text: str) -> FrameQuality:
        quality = classify_frame_text(text)
        if quality in {FrameQuality.FULL, FrameQuality.ACK_ONLY}:
            return quality
        if quality == FrameQuality.PARTIAL:
            return FrameQuality.TRUNCATED
        if any(token in text.upper() for token in ("YGAS", "LICOR", "LI7200", "LI-7200", "LI7500", "LI-7500")):
            return FrameQuality.TRUNCATED
        return FrameQuality.CORRUPTED
