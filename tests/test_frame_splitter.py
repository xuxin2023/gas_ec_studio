from core.protocol.frame_splitter import FrameSplitter
from models.hf_models import FrameQuality


def test_splitter_handles_glued_frames_and_ack() -> None:
    splitter = FrameSplitter()
    payload = (
        "YGAS,001,T"
        "YGAS,001,420.0,11.8,0.9,0.1,1.0,1.0,1.8,1.8,1015,1000,870,25.0,26.0,101.2,OK"
    )
    frames = splitter.feed(payload)
    assert len(frames) == 2
    assert frames[0].quality == FrameQuality.ACK_ONLY
    assert frames[1].quality == FrameQuality.FULL


def test_splitter_marks_truncated_frame_on_flush() -> None:
    splitter = FrameSplitter()
    frames = splitter.feed("YGAS,001,420.0,11.8,0.9")
    assert frames == []
    tail = splitter.flush()
    assert len(tail) == 1
    assert tail[0].quality == FrameQuality.TRUNCATED


def test_splitter_marks_corrupted_prefix() -> None:
    splitter = FrameSplitter()
    frames = splitter.feed("noise noise\nYGAS,001,T")
    assert len(frames) == 2
    assert frames[0].quality == FrameQuality.CORRUPTED
    assert frames[1].quality == FrameQuality.ACK_ONLY
