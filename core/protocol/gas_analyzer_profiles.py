from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GasAnalyzerCommandSpec:
    name: str
    command: str
    mode: str
    range_text: str = ""
    notes: str = ""
    dangerous: bool = False


@dataclass(frozen=True, slots=True)
class GasAnalyzerProfile:
    profile_id: str
    label: str
    manufacturer: str
    instrument_family: str
    command_prefix: str
    default_baudrate: int
    default_mode: int
    default_active_send: bool
    supported_modes: tuple[int, ...]
    max_sample_hz: int
    measured_variables: tuple[str, ...]
    calibration_groups: tuple[str, ...] = ()
    command_specs: tuple[GasAnalyzerCommandSpec, ...] = ()
    raw_output_fields: tuple[str, ...] = ()
    eddypro_peer: bool = False
    primary_project_device: bool = False
    source_reference: dict[str, Any] = field(default_factory=dict)
    known_limitations: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, Any]:
        command_specs = [
            {
                "name": command.name,
                "command": command.command,
                "mode": command.mode,
                "range_text": command.range_text,
                "notes": command.notes,
                "dangerous": command.dangerous,
            }
            for command in self.command_specs
        ]
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "manufacturer": self.manufacturer,
            "instrument_family": self.instrument_family,
            "command_prefix": self.command_prefix,
            "default_baudrate": self.default_baudrate,
            "default_mode": self.default_mode,
            "default_active_send": self.default_active_send,
            "supported_modes": list(self.supported_modes),
            "max_sample_hz": self.max_sample_hz,
            "measured_variables": list(self.measured_variables),
            "calibration_groups": list(self.calibration_groups),
            "command_count": len(self.command_specs),
            "command_specs": command_specs,
            "raw_output_fields": list(self.raw_output_fields),
            "eddypro_peer": self.eddypro_peer,
            "primary_project_device": self.primary_project_device,
            "source_reference": dict(self.source_reference),
            "known_limitations": list(self.known_limitations),
        }


YGAS_COMMANDS: tuple[GasAnalyzerCommandSpec, ...] = (
    GasAnalyzerCommandSpec("serial parameters", "SETCOM", "read_write", "1200-115200 bps", "Baud/data/parity/stop bits; reboot required after write.", True),
    GasAnalyzerCommandSpec("active/passive output", "SETCOMWAY", "read_write", "0/1", "0 passive READDATA, 1 active high-frequency output."),
    GasAnalyzerCommandSpec("active output frequency", "FTD", "read_write", "1-20 Hz", "Manual examples use 10 and 20 Hz."),
    GasAnalyzerCommandSpec("read latest data", "READDATA", "read", "", "Returns latest MODE1/MODE2 high-frequency frame."),
    GasAnalyzerCommandSpec("restart device", "RESET", "write", "", "Device reboot.", True),
    GasAnalyzerCommandSpec("write calibration coefficients", "SENCO1-9", "write", "1-9 groups", "Calibration mode only.", True),
    GasAnalyzerCommandSpec("read calibration coefficients", "GETCO", "read", "1-9 groups", "Returns C0..C7 coefficient tokens."),
    GasAnalyzerCommandSpec("clear calibration coefficients", "CLEARSENCO1-9", "write", "1-9 groups", "Clears one coefficient group.", True),
    GasAnalyzerCommandSpec("device id", "ID", "read_write", "000-999/FFF", "FFF is broadcast discovery/write target.", True),
    GasAnalyzerCommandSpec("work mode", "MODE", "read_write", "1/2/3", "1 normal, 2 calibration, 3 factory."),
    GasAnalyzerCommandSpec("lamp power voltage", "SETPOW", "read_write", "0000-3000 mV", "Emitter power voltage."),
    GasAnalyzerCommandSpec("capture reference full-scale", "SETILLUM", "write", "", "Stores current reference signal as full-scale reference.", True),
    GasAnalyzerCommandSpec("reference signal full-scale", "SETCO2", "read_write", "0100-4000 mV", "Manual command name is SETCO2 although it stores reference signal full-scale."),
    GasAnalyzerCommandSpec("timer compensation", "TIMEOUT", "read_write", "900-1100", "Adjusts active-send interval compensation."),
    GasAnalyzerCommandSpec("calibration temperature point", "SENTEMP1-2", "read_write", "-20.0-40.0 C", "1 CO2, 2 H2O calibration environment temperature."),
    GasAnalyzerCommandSpec("CO2 smoothing/filter", "AVERAGE1", "read_write", "1-399", "1-40 moving average, 49/99/399 filter windows."),
    GasAnalyzerCommandSpec("H2O smoothing/filter", "AVERAGE2", "read_write", "1-399", "1-40 moving average, 49/99/399 filter windows."),
    GasAnalyzerCommandSpec("generic filter window", "AVERAGE", "read_write", "1-399", "Manual narrative uses AVERAGE for filter-style processing."),
)


YGAS_PROFILE = GasAnalyzerProfile(
    profile_id="ygas_irga",
    label="YGAS CO2/H2O infrared gas analyzer",
    manufacturer="Project YGAS",
    instrument_family="open_path_or_short_path_irga",
    command_prefix="YGAS",
    default_baudrate=115200,
    default_mode=1,
    default_active_send=True,
    supported_modes=(1, 2, 3),
    max_sample_hz=20,
    measured_variables=("co2_mol_fraction", "h2o_mol_fraction", "co2_density", "h2o_density", "pressure", "temperature", "signal_strength"),
    calibration_groups=(
        "SENCO1 CO2 density-ratio coefficients",
        "SENCO2 H2O density-ratio coefficients",
        "SENCO3 CO2 ratio-temperature compensation",
        "SENCO4 H2O ratio-temperature compensation",
        "SENCO5 CO2 density-temperature compensation",
        "SENCO6 H2O density-temperature compensation",
        "SENCO7 chamber temperature compensation",
        "SENCO8 case temperature compensation",
        "SENCO9 pressure calibration",
    ),
    command_specs=YGAS_COMMANDS,
    raw_output_fields=(
        "device_id",
        "co2_ppm",
        "h2o_mmol_mol",
        "co2_signal_strength",
        "h2o_signal_strength",
        "temperature_c",
        "pressure_kpa",
        "status_register",
        "checksum",
        "co2_density_mg_m3",
        "h2o_density_g_m3",
        "co2_ratio_filtered",
        "co2_ratio_raw",
        "h2o_ratio_filtered",
        "h2o_ratio_raw",
        "reference_signal",
        "co2_signal_raw",
        "h2o_signal_raw",
        "chamber_temperature_c",
        "case_temperature_c",
    ),
    primary_project_device=True,
    source_reference={
        "manual": "D:/手册/气体分析仪指令.docx",
        "manual_title": "气体分析仪指令表",
        "normalized_at": "2026-05-25",
        "normalization": "DOCX word/document.xml text extraction; commands mapped to CommandBuilder and parser tests.",
    },
    known_limitations=(
        "Manual describes CO2/H2O analyzer protocol only; sonic wind data must still come from a paired anemometer/logger stream.",
        "Checksum algorithm is documented as a field but not specified; parser preserves checksum without validating it.",
        "Factory MODE2 diagnostic fields are parsed for provenance and QC, not used as replacement for audited calibration certificates.",
    ),
)


LICOR_CO2H2O_COMMANDS: tuple[GasAnalyzerCommandSpec, ...] = (
    GasAnalyzerCommandSpec(
        "read latest data",
        "READDATA",
        "read",
        "",
        "Adapter-level request for one normalized LI-COR CO2/H2O diagnostic text record.",
    ),
    GasAnalyzerCommandSpec(
        "diagnostic record",
        "GETDIAG",
        "read",
        "",
        "Reads the diagnostic record parsed by Gas EC Studio's LI-7500/LI-7200 text decoder.",
    ),
    GasAnalyzerCommandSpec(
        "diagnostic alias",
        "DIAG",
        "read",
        "",
        "Alias accepted by supported acquisition adapters for LI-COR diagnostic telemetry.",
    ),
    GasAnalyzerCommandSpec(
        "data query alias",
        "DATA?",
        "read",
        "",
        "Passive query alias used by simulator and text-acquisition adapters.",
    ),
)


LICOR_LI7500_RAW_OUTPUT_FIELDS: tuple[str, ...] = (
    "co2_ppm",
    "h2o_mmol",
    "co2_signal_strength_pct",
    "h2o_signal_strength_pct",
    "reference_signal_pct",
    "diagnostic_word",
    "status_ok",
)


LICOR_LI7200_RAW_OUTPUT_FIELDS: tuple[str, ...] = (
    *LICOR_LI7500_RAW_OUTPUT_FIELDS,
    "cell_pressure_kpa",
    "cell_temperature_c",
)


LICOR_PEER_PROFILES: tuple[GasAnalyzerProfile, ...] = (
    GasAnalyzerProfile(
        profile_id="licor_li7500_family",
        label="LI-COR LI-7500/LI-7500A/LI-7500DS family",
        manufacturer="LI-COR",
        instrument_family="open_path_irga",
        command_prefix="",
        default_baudrate=9600,
        default_mode=1,
        default_active_send=True,
        supported_modes=(1,),
        max_sample_hz=20,
        measured_variables=("co2_mol_fraction", "h2o_mol_fraction", "diagnostics"),
        command_specs=LICOR_CO2H2O_COMMANDS,
        raw_output_fields=LICOR_LI7500_RAW_OUTPUT_FIELDS,
        eddypro_peer=True,
        source_reference={
            "eddypro_engine": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_gui": "https://github.com/LI-COR-Environmental/eddypro-gui",
            "normalized_at": "2026-06-06",
            "normalization": "LI-COR diagnostic text frames normalized through parse_licor_diag_frame.",
        },
        known_limitations=(
            "Diagnostic text parsing and adapter-level read commands are supported; native proprietary binary/RS control remains a separate parity track.",
        ),
    ),
    GasAnalyzerProfile(
        profile_id="licor_li7200_family",
        label="LI-COR LI-7200/LI-7200RS family",
        manufacturer="LI-COR",
        instrument_family="enclosed_path_irga",
        command_prefix="",
        default_baudrate=9600,
        default_mode=1,
        default_active_send=True,
        supported_modes=(1,),
        max_sample_hz=20,
        measured_variables=("co2_mol_fraction", "h2o_mol_fraction", "cell_temperature", "cell_pressure", "diagnostics"),
        command_specs=LICOR_CO2H2O_COMMANDS,
        raw_output_fields=LICOR_LI7200_RAW_OUTPUT_FIELDS,
        eddypro_peer=True,
        source_reference={
            "eddypro_engine": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_flux_docs": "https://www.licor.com/support/EddyPro/topics/calculate-flux-7200-and-7700.html",
            "normalized_at": "2026-06-06",
            "normalization": "LI-7200 diagnostic text frames normalized through parse_licor_diag_frame, including cell pressure and temperature.",
        },
        known_limitations=(
            "Diagnostic text parsing and adapter-level read commands are supported; native proprietary binary/RS control remains a separate parity track.",
            "Full closed-path cell thermodynamic parity is tracked in RP correction tests.",
        ),
    ),
    GasAnalyzerProfile(
        profile_id="licor_li7700_family",
        label="LI-COR LI-7700 methane analyzer",
        manufacturer="LI-COR",
        instrument_family="open_path_ch4",
        command_prefix="",
        default_baudrate=9600,
        default_mode=1,
        default_active_send=True,
        supported_modes=(1,),
        max_sample_hz=20,
        measured_variables=("ch4_mol_fraction", "rss_77", "diagnostics"),
        eddypro_peer=True,
        source_reference={
            "eddypro_engine": "https://github.com/LI-COR-Environmental/eddypro-engine",
            "eddypro_flux_docs": "https://www.licor.com/support/EddyPro/topics/calculate-flux-7200-and-7700.html",
        },
        known_limitations=("Raw WMS line-shape fitting is not fully implemented yet; correction-sequence parity remains tracked separately.",),
    ),
)


GAS_ANALYZER_PROFILES: dict[str, GasAnalyzerProfile] = {
    profile.profile_id: profile for profile in (YGAS_PROFILE, *LICOR_PEER_PROFILES)
}


def get_gas_analyzer_profile(profile_id: str | None) -> GasAnalyzerProfile:
    key = str(profile_id or "").strip().lower() or YGAS_PROFILE.profile_id
    aliases = {
        "standard": "ygas_irga",
        "ygas": "ygas_irga",
        "project_ygas": "ygas_irga",
        "li7500": "licor_li7500_family",
        "li7200": "licor_li7200_family",
        "li7700": "licor_li7700_family",
    }
    resolved = aliases.get(key, key)
    return GAS_ANALYZER_PROFILES.get(resolved, YGAS_PROFILE)


def list_gas_analyzer_profiles() -> list[GasAnalyzerProfile]:
    return list(GAS_ANALYZER_PROFILES.values())
