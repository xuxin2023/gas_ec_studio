from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from models.hf_models import FrameQuality


def test_parse_mode1_full_frame() -> None:
    parsed = parse_mode1_frame("YGAS,001,421.35,12.20,1020.0,860.0,24.5,101.3,OK")
    assert parsed is not None
    assert parsed["mode"] == 1
    assert parsed["device_id"] == "001"
    assert parsed["co2_ppm"] == 421.35
    assert parsed["h2o_mmol"] == 12.2
    assert parsed["pressure_kpa"] == 101.3
    assert parsed["frame_quality"] == FrameQuality.FULL


def test_parse_mode2_full_frame() -> None:
    parsed = parse_mode2_frame(
        "YGAS,002,420.1,11.9,0.91,0.11,1.01,0.99,1.90,1.87,1015,998,876,24.9,26.2,101.1,OK"
    )
    assert parsed is not None
    assert parsed["mode"] == 2
    assert parsed["device_id"] == "002"
    assert parsed["co2_ppm"] == 420.1
    assert parsed["h2o_mmol"] == 11.9
    assert parsed["pressure_kpa"] == 101.1
    assert parsed["frame_quality"] == FrameQuality.FULL


def test_parse_mode1_partial_frame() -> None:
    parsed = parse_mode1_frame("YGAS,003,419.9,11.7,999.0,830.0")
    assert parsed is not None
    assert parsed["frame_quality"] == FrameQuality.PARTIAL


def test_parse_mode2_rejects_bad_payload() -> None:
    assert parse_mode2_frame("YGAS,001,BAD,FRAME") is None
