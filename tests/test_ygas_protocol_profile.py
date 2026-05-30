from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.studio import StudioController
from core.adapters.mock_adapter import MockGasAnalyzerAdapter
from core.protocol.command_builder import CommandBuilder
from core.protocol.frame_splitter import classify_frame_text
from core.protocol.gas_analyzer_profiles import get_gas_analyzer_profile, list_gas_analyzer_profiles
from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from core.protocol.parameter_parser import parse_parameter_response
from core.protocol.software_profile import SoftwareProfile
from core.storage.raw_importer import load_raw_text_frames
from models.hf_models import FrameQuality
from models.station_models import MetadataBundle, RawFileDescriptionMetadata, RawFileSettingsMetadata


def test_ygas_profile_is_first_class_next_to_eddypro_peer_analyzers() -> None:
    profiles = {profile.profile_id: profile for profile in list_gas_analyzer_profiles()}

    assert "ygas_irga" in profiles
    assert "licor_li7500_family" in profiles
    assert "licor_li7200_family" in profiles
    assert "licor_li7700_family" in profiles
    assert profiles["ygas_irga"].primary_project_device is True
    assert profiles["ygas_irga"].source_reference["manual"].endswith("气体分析仪指令.docx")
    assert any(command.command == "SETCOM" for command in profiles["ygas_irga"].command_specs)
    assert get_gas_analyzer_profile("standard").profile_id == "ygas_irga"


def test_command_builder_covers_manual_command_set_and_validates_ranges() -> None:
    builder = CommandBuilder(SoftwareProfile.for_analyzer_profile("ygas_irga"))

    assert builder.set_comm_params(target_id="0", baudrate=115200, data_bits=8, parity="N", stop_bits=1) == "SETCOM,YGAS,000,115200,8,N,1\r\n"
    assert builder.query_comm_params(target_id="000") == "SETCOM,YGAS,000\r\n"
    assert builder.set_comm_way(True, target_id="000") == "SETCOMWAY,YGAS,000,1\r\n"
    assert builder.set_ftd_frequency(20, target_id="000") == "FTD,YGAS,000,20\r\n"
    assert builder.set_mode(3, target_id="000") == "MODE,YGAS,000,3\r\n"
    assert builder.set_average(1, 49, target_id="000") == "AVERAGE1,YGAS,000,49\r\n"
    assert builder.set_filter(99, target_id="000") == "AVERAGE,YGAS,000,99\r\n"
    assert builder.clear_coefficients(9, target_id="000") == "CLEARSENCO9,YGAS,000\r\n"
    assert builder.set_lamp_power_mv(2000, target_id="000") == "SETPOW,YGAS,000,2000\r\n"
    assert builder.capture_illumination_reference(target_id="FFF") == "SETILLUM,YGAS,FFF\r\n"
    assert builder.set_reference_signal_mv(3000, target_id="000") == "SETCO2,YGAS,000,3000\r\n"
    assert builder.set_timeout_compensation(999, target_id="000") == "TIMEOUT,YGAS,000,999\r\n"
    assert builder.set_calibration_temperature(2, 22.5, target_id="000") == "SENTEMP2,YGAS,000,22.5\r\n"
    assert builder.broadcast_probe() == "ID,YGAS,FFF\r\n"

    with pytest.raises(ValueError):
        builder.set_ftd_frequency(50, target_id="000")
    with pytest.raises(ValueError):
        builder.set_reference_signal_mv(50, target_id="000")


def test_mode_parsers_preserve_ygas_status_register_checksum_and_mode2_layout() -> None:
    parsed = parse_mode1_frame("YGAS,001,0488.879,00.528,0.98,0.98,026.10,101.14,0001,2771")

    assert parsed is not None
    assert parsed["frame_quality"] == FrameQuality.FULL
    assert parsed["status_register"] == "0001"
    assert parsed["status_ok"] is True
    assert parsed["active_faults"] == []
    assert parsed["checksum"] == "2771"
    assert parsed["status_text"] == "OK"

    fault = parse_mode1_frame("YGAS,001,0488.879,00.528,0.98,0.98,026.10,101.14,0003,2771")
    assert fault is not None
    assert fault["status_ok"] is False
    assert "data_abnormal" in fault["active_faults"]
    assert fault["status_text"].startswith("FAULT:")

    mode2 = parse_mode2_frame(
        "YGAS,087,0479.572,05.198,0958.423,04.249,1.3030,1.3033,0.7888,0.7888,03322,04356,02631,002.18,002.31,103.97"
    )
    assert mode2 is not None
    assert mode2["frame_quality"] == FrameQuality.FULL
    assert mode2["co2_density"] == 958.423
    assert mode2["pressure_kpa"] == 103.97


def test_parameter_responses_are_valid_transaction_frames() -> None:
    parsed = parse_parameter_response("<YGAS,000,115200,8,N,1>")

    assert parsed == {
        "response_type": "parameter",
        "device_id": "000",
        "values": ["115200", "8", "N", "1"],
        "value_count": 4,
        "raw": "YGAS,000,115200,8,N,1",
    }
    assert classify_frame_text("YGAS,000,115200,8,N,1") == FrameQuality.FULL
    assert classify_frame_text("YGAS,000,10") == FrameQuality.FULL


def test_mock_adapter_executes_full_ygas_command_family() -> None:
    adapter = MockGasAnalyzerAdapter(device_id="000")
    adapter.open()
    try:
        assert adapter.send_command("SETCOM,YGAS,000").startswith("YGAS,000,115200")
        assert adapter.send_command("SETCOM,YGAS,000,57600,8,N,1").startswith("YGAS,000,T")
        assert adapter.send_command("FTD,YGAS,000,20").startswith("YGAS,000,T")
        assert adapter.send_command("AVERAGE1,YGAS,000,49").startswith("YGAS,000,T")
        assert adapter.send_command("AVERAGE2,YGAS,000,99").startswith("YGAS,000,T")
        assert adapter.send_command("AVERAGE,YGAS,000,399").startswith("YGAS,000,T")
        assert adapter.send_command("SETPOW,YGAS,000,2000").startswith("YGAS,000,T")
        assert adapter.send_command("SETILLUM,YGAS,FFF").startswith("YGAS,000,T")
        assert adapter.send_command("SETCO2,YGAS,000,3000").startswith("YGAS,000,T")
        assert adapter.send_command("TIMEOUT,YGAS,000,999").startswith("YGAS,000,T")
        assert adapter.send_command("SENTEMP1,YGAS,000,22.5").startswith("YGAS,000,T")
        assert adapter.send_command("SENCO1,YGAS,000,1,2,3,4,5,6").startswith("YGAS,000,T")
        assert adapter.send_command("GETCO,YGAS,000,1").startswith("C0:1")
        assert adapter.send_command("CLEARSENCO1,YGAS,000").startswith("YGAS,000,T")
        assert adapter.send_command("RESET,YGAS,000").startswith("YGAS,000,T")
        assert parse_mode1_frame(adapter.send_command("READDATA,YGAS,000")) is not None
    finally:
        adapter.close()


def test_ygas_protocol_log_imports_to_normalized_frames(tmp_path: Path) -> None:
    source = tmp_path / "ygas.log"
    source.write_text(
        "\n".join(
            [
                "YGAS,001,0488.879,00.528,0.98,0.98,026.10,101.14,0001,2771",
                "YGAS,001,0479.572,05.198,0958.423,04.249,1.3030,1.3033,0.7888,0.7888,03322,04356,02631,002.18,002.31,103.97",
            ]
        ),
        encoding="utf-8",
    )
    metadata = MetadataBundle(
        raw_file_description=RawFileDescriptionMetadata(source_type="ygas_protocol"),
        raw_file_settings=RawFileSettingsMetadata(sample_hz=10.0, extra={"start_time": "2026-05-25T08:00:00"}),
    )

    rows = load_raw_text_frames(source, metadata=metadata, device_uid="dev-ygas")

    assert len(rows) == 2
    assert rows[0].timestamp == datetime(2026, 5, 25, 8, 0, 0)
    assert rows[1].timestamp == datetime(2026, 5, 25, 8, 0, 0, 100000)
    assert rows[0].device_uid == "dev-ygas"
    assert rows[0].device_id == "001"
    assert rows[0].co2_ppm == 488.879
    assert rows[1].mode == 2
    assert "ygas_protocol_import" in rows[0].raw_text


def test_studio_controller_exposes_ygas_profile_and_manual_commands(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(StudioController, "bootstrap_demo_device", lambda self: None)
    controller = StudioController(workspace_root=tmp_path)
    try:
        uid = controller.add_device(
            label="Field YGAS",
            port="SIM1",
            baudrate=115200,
            device_id="001",
            analyzer_profile="ygas_irga",
        )
        controller.connect_device(uid)

        assert controller.device_cards()[0]["analyzer_profile"] == "ygas_irga"
        assert controller.set_ftd_frequency(uid, 20).status.value == "SUCCEEDED"
        assert controller.set_average_params(uid, avg_co2=49, avg_h2o=99)[0].status.value == "SUCCEEDED"
        assert controller.set_filter_params(uid, window_n=399)[0].status.value == "SUCCEEDED"
        assert controller.configure_serial_params(uid, baudrate=115200).status.value == "SUCCEEDED"
        assert controller.set_lamp_power(uid, value_mv=2000).status.value == "SUCCEEDED"
        assert controller.capture_illumination_reference(uid).status.value == "SUCCEEDED"
        assert controller.set_reference_signal(uid, value_mv=3000).status.value == "SUCCEEDED"
        assert controller.set_timeout_compensation(uid, value=999).status.value == "SUCCEEDED"
        assert controller.set_calibration_temperature(uid, channel=1, temp_c=22.5).status.value == "SUCCEEDED"
        assert controller.clear_coefficients(uid, group_index=1).status.value == "SUCCEEDED"
        assert controller.broadcast_probe(uid).status.value == "SUCCEEDED"

        snapshot = controller.device_detail_snapshot(uid)
        assert snapshot["gas_analyzer_profile"]["profile_id"] == "ygas_irga"
    finally:
        controller.shutdown()
