from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from app.studio import StudioController
from core.adapters.mock_adapter import MockGasAnalyzerAdapter
from core.ec_rp.analysis import compute_primary_analyzer_diagnostics, compute_ygas_primary_analyzer_diagnostics
from core.ec_rp.pipeline import ECRPPipeline
from core.exports.result_exporter import ResultExporter
from core.protocol.command_builder import CommandBuilder
from core.protocol.frame_splitter import classify_frame_text
from core.protocol.gas_analyzer_profiles import get_gas_analyzer_profile, list_gas_analyzer_profiles
from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from core.protocol.parameter_parser import parse_parameter_response
from core.protocol.software_profile import SoftwareProfile
from core.storage.raw_importer import load_raw_text_frames
from models.hf_models import FrameQuality, NormalizedHFFrame
from models.station_models import MetadataBundle, ProjectProfile, RawFileDescriptionMetadata, RawFileSettingsMetadata, SiteProfile


def _make_ygas_rp_rows(*, samples: int = 600, sample_hz: float = 10.0, status_register: str = "0001") -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 25, 8, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.2 + 0.18 * np.sin(2.0 * np.pi * 0.03 * time_axis)
    v = 0.25 * np.cos(2.0 * np.pi * 0.05 * time_axis)
    w = 0.48 * np.sin(2.0 * np.pi * 0.18 * time_axis) + 0.10 * np.cos(2.0 * np.pi * 0.63 * time_axis)
    co2_scalar = np.roll(w, 4) + 0.03 * np.sin(2.0 * np.pi * 1.0 * time_axis)
    h2o_scalar = 0.7 * np.roll(w, 2) + 0.02 * np.cos(2.0 * np.pi * 0.7 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        raw_payload = {
            "u": float(u[index]),
            "v": float(v[index]),
            "w": float(w[index]),
            "ygas_protocol_import": {
                "status": "decoded",
                "format": "ygas_protocol",
                "source_file": "D:/manuals/ygas_mode_samples.log",
            },
            "profile_id": "ygas_irga",
            "co2_signal": 0.96 + 0.01 * float(np.sin(time_axis[index])),
            "h2o_signal": 0.94 + 0.01 * float(np.cos(time_axis[index])),
            "ref_signal": 2630.0 + float(index % 5),
            "co2_ratio_f": 1.303,
            "h2o_ratio_f": 0.789,
            "co2_density": 958.0,
            "h2o_density": 4.25,
            "status_register": status_register,
            "status_ok": status_register == "0001",
            "active_faults": [] if status_register == "0001" else ["data_abnormal"],
        }
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-ygas-rp",
                device_id="001",
                mode=2,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(410.0 + 8.0 * co2_scalar[index]),
                h2o_mmol=float(12.0 + 1.1 * h2o_scalar[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.5,
                case_temp_c=24.3,
                status_text=json.dumps({"status_register": status_register, "status_ok": status_register == "0001"}),
                raw_text=json.dumps(raw_payload),
            )
        )
    return rows


def _make_licor_rp_rows(
    *,
    profile_id: str = "licor_li7200_family",
    samples: int = 600,
    sample_hz: float = 10.0,
    diagnostic_word: int = 0,
    include_cell: bool = True,
) -> list[NormalizedHFFrame]:
    start = datetime(2026, 5, 25, 9, 0, 0)
    time_axis = np.arange(samples, dtype=float) / sample_hz
    u = 2.4 + 0.14 * np.sin(2.0 * np.pi * 0.04 * time_axis)
    v = 0.20 * np.cos(2.0 * np.pi * 0.06 * time_axis)
    w = 0.42 * np.sin(2.0 * np.pi * 0.16 * time_axis) + 0.08 * np.cos(2.0 * np.pi * 0.55 * time_axis)
    co2_scalar = np.roll(w, 3) + 0.02 * np.sin(2.0 * np.pi * 0.9 * time_axis)
    h2o_scalar = 0.65 * np.roll(w, 2) + 0.02 * np.cos(2.0 * np.pi * 0.8 * time_axis)
    rows: list[NormalizedHFFrame] = []
    for index in range(samples):
        raw_payload = {
            "u": float(u[index]),
            "v": float(v[index]),
            "w": float(w[index]),
            "licor_primary_analyzer_import": {
                "status": "decoded",
                "format": "licor_diagnostic_json",
                "source_file": "D:/fixtures/licor_primary_analyzer.log",
            },
            "profile_id": profile_id,
            "co2_signal_strength_pct": 86.0 + 0.5 * float(np.sin(time_axis[index])),
            "h2o_signal_strength_pct": 88.0 + 0.5 * float(np.cos(time_axis[index])),
            "reference_signal_pct": 91.0,
            "diagnostic_word": diagnostic_word,
            "status_ok": diagnostic_word == 0,
        }
        if include_cell:
            raw_payload["cell_pressure_kpa"] = 101.2 + 0.01 * float(np.sin(time_axis[index]))
            raw_payload["cell_temperature_c"] = 24.8 + 0.02 * float(np.cos(time_axis[index]))
        rows.append(
            NormalizedHFFrame(
                timestamp=start + timedelta(seconds=float(time_axis[index])),
                device_uid="dev-licor-rp",
                device_id="li7200",
                mode=1,
                frame_quality=FrameQuality.FULL,
                co2_ppm=float(412.0 + 7.0 * co2_scalar[index]),
                h2o_mmol=float(13.0 + 1.0 * h2o_scalar[index]),
                pressure_kpa=101.3,
                chamber_temp_c=24.5,
                case_temp_c=24.3,
                status_text=json.dumps({"diagnostic_word": diagnostic_word, "status_ok": diagnostic_word == 0}),
                raw_text=json.dumps(raw_payload),
            )
        )
    return rows


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


def test_ygas_primary_analyzer_diagnostics_decode_status_register_faults() -> None:
    detail = compute_ygas_primary_analyzer_diagnostics(
        rows=_make_ygas_rp_rows(samples=30, status_register="0003"),
        config={"profile_id": "ygas_irga", "calibration_profile_id": "ygas_lab_fault_check"},
    )

    assert detail["artifact_type"] == "ygas_primary_analyzer_diagnostics_v1"
    assert detail["status"] == "fail"
    assert detail["profile_id"] == "ygas_irga"
    assert "data_abnormal" in detail["active_faults"]
    assert detail["status_register_status"] == "fail"
    assert detail["calibration_profile_id"] == "ygas_lab_fault_check"


def test_licor_primary_analyzer_diagnostics_decode_diagnostic_word_faults() -> None:
    detail = compute_primary_analyzer_diagnostics(
        rows=_make_licor_rp_rows(profile_id="licor_li7500_family", samples=30, diagnostic_word=4, include_cell=False),
        config={
            "profile_id": "licor_li7500_family",
            "calibration_profile_id": "li7500_site_zero_span",
            "diagnostic_bit_map": {"2": "pll_or_chopper_fault"},
        },
    )

    assert detail["artifact_type"] == "licor_co2h2o_primary_analyzer_diagnostics_v1"
    assert detail["status"] == "fail"
    assert detail["profile_id"] == "licor_li7500_family"
    assert detail["diagnostic_word_status"] == "fail"
    assert any("pll_or_chopper_fault" in item for item in detail["active_faults"])
    assert detail["calibration_profile_id"] == "li7500_site_zero_span"


def test_ygas_primary_analyzer_reaches_rp_ledger_and_result_exporter(tmp_path: Path) -> None:
    result = ECRPPipeline().run(
        rows=_make_ygas_rp_rows(),
        project=ProjectProfile(code="YGAS"),
        site=SiteProfile(station_code="YGS"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "primary_analyzer": {
                "profile_id": "ygas_irga",
                "calibration_profile_id": "ygas_lab_2026",
                "source_file": "D:/manuals/ygas_calibration_2026.json",
                "normalization_command": "gas_ec_studio normalize-ygas --profile ygas_lab_2026",
                "min_signal_warning": 0.10,
                "require_status_ok": True,
            },
        },
    )

    assert result.windows
    first = result.windows[0]
    diagnostics = first.diagnostics
    assert diagnostics["primary_analyzer_status"] == "pass"
    assert diagnostics["ygas_status"] == "pass"
    assert diagnostics["ygas_profile_id"] == "ygas_irga"
    assert diagnostics["ygas_calibration_profile_id"] == "ygas_lab_2026"
    assert diagnostics["primary_analyzer_detail"]["telemetry_detected"] is True
    ledger_stages = {stage["stage"] for stage in diagnostics["flux_correction_ledger"]["stages"]}
    assert "ygas_primary_analyzer_qc_profile" in ledger_stages
    assert result.summary["primary_analyzer_summary"]["status"] == "pass"
    assert result.summary["flux_correction_ledger_summary"]["ygas_primary_analyzer_window_count"] == len(result.windows)
    assert result.artifacts["primary_analyzer"]["summary"]["telemetry_window_count"] == len(result.windows)

    exporter = ResultExporter(runtime_root=tmp_path / "runtime_data")
    export = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot={"primary_analyzer": {"profile_id": "ygas_irga"}},
        spectral_config_snapshot={},
        project={"code": "YGAS"},
        site={"station_code": "YGS"},
        report_payload={"status": "ok"},
        report_key="ygas-primary-analyzer",
    )
    manifest = json.loads(Path(export["files"]["export_manifest"]).read_text(encoding="utf-8"))
    full_output = Path(export["files"]["full_output"]).read_text(encoding="utf-8")
    primary_artifact = json.loads(Path(export["files"]["primary_analyzer_artifact"]).read_text(encoding="utf-8"))

    assert "ygas_status" in full_output
    assert "ygas_lab_2026" in full_output
    assert manifest["primary_analyzer_summary"]["status"] == "pass"
    assert "ygas_status" in manifest["primary_analyzer_fields"]
    assert manifest["primary_analyzer_artifact"].endswith("primary_analyzer_diagnostics.json")
    assert primary_artifact["summary"]["status"] == "pass"
    assert primary_artifact["windows"][0]["diagnostics"]["calibration_normalization_command"].endswith("ygas_lab_2026")


def test_licor_li7200_primary_analyzer_reaches_rp_ledger_and_result_exporter(tmp_path: Path) -> None:
    result = ECRPPipeline().run(
        rows=_make_licor_rp_rows(profile_id="licor_li7200_family"),
        project=ProjectProfile(code="LICOR"),
        site=SiteProfile(station_code="L7200"),
        config={
            "sample_hz": 10.0,
            "block_minutes": 0.5,
            "primary_analyzer": {
                "profile_id": "licor_li7200_family",
                "calibration_profile_id": "li7200_factory_site_profile",
                "source_file": "D:/fixtures/li7200_factory_site_profile.json",
                "normalization_command": "gas_ec_studio normalize-licor --profile li7200_factory_site_profile",
                "min_signal_warning_pct": 50.0,
                "require_cell_thermodynamics": True,
                "require_status_ok": True,
            },
        },
    )

    assert result.windows
    first = result.windows[0]
    diagnostics = first.diagnostics
    assert diagnostics["primary_analyzer_status"] == "pass"
    assert diagnostics["primary_analyzer_profile_id"] == "licor_li7200_family"
    assert diagnostics["licor_status"] == "pass"
    assert diagnostics["ygas_status"] == "not_available"
    assert diagnostics["licor_cell_pressure_mean_kpa"] is not None
    assert diagnostics["licor_cell_temp_mean_c"] is not None
    assert diagnostics["primary_analyzer_detail"]["telemetry_detected"] is True
    ledger_stages = {stage["stage"] for stage in diagnostics["flux_correction_ledger"]["stages"]}
    assert "licor_primary_analyzer_qc_profile" in ledger_stages
    assert result.summary["primary_analyzer_summary"]["status"] == "pass"
    assert result.summary["primary_analyzer_summary"]["profile_counts"]["licor_li7200_family"] == len(result.windows)
    assert result.summary["flux_correction_ledger_summary"]["licor_primary_analyzer_window_count"] == len(result.windows)
    assert result.artifacts["primary_analyzer"]["summary"]["telemetry_window_count"] == len(result.windows)

    exporter = ResultExporter(runtime_root=tmp_path / "runtime_data")
    export = exporter.export_minimal_bundle(
        rp_result=result,
        spectral_result=None,
        rp_config_snapshot={"primary_analyzer": {"profile_id": "licor_li7200_family"}},
        spectral_config_snapshot={},
        project={"code": "LICOR"},
        site={"station_code": "L7200"},
        report_payload={"status": "ok"},
        report_key="licor-primary-analyzer",
    )
    manifest = json.loads(Path(export["files"]["export_manifest"]).read_text(encoding="utf-8"))
    full_output = Path(export["files"]["full_output"]).read_text(encoding="utf-8")
    primary_artifact = json.loads(Path(export["files"]["primary_analyzer_artifact"]).read_text(encoding="utf-8"))

    assert "licor_status" in full_output
    assert "li7200_factory_site_profile" in full_output
    assert manifest["primary_analyzer_summary"]["status"] == "pass"
    assert "licor_status" in manifest["primary_analyzer_fields"]
    assert manifest["primary_analyzer_artifact"].endswith("primary_analyzer_diagnostics.json")
    assert primary_artifact["summary"]["status"] == "pass"
    assert primary_artifact["windows"][0]["diagnostics"]["profile_id"] == "licor_li7200_family"
    assert primary_artifact["windows"][0]["diagnostics"]["cell_pressure_mean_kpa"] is not None
