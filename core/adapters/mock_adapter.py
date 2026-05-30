from __future__ import annotations

import math
import time
from random import Random

from core.adapters.base import BaseGasAnalyzerAdapter


class MockGasAnalyzerAdapter(BaseGasAnalyzerAdapter):
    def __init__(self, *, device_id: str, seed: int = 42) -> None:
        super().__init__(device_id=device_id)
        self.mode = 1
        self.active_send = True
        self.ftd_hz = 10
        self.average_co2 = 1
        self.average_h2o = 1
        self.filter_window = 49
        self.baudrate = 115200
        self.data_bits = 8
        self.parity = "N"
        self.stop_bits = 1
        self.lamp_power_mv = 2000
        self.reference_signal_mv = 3000
        self.timeout_compensation = 999
        self.calibration_temperatures = {1: 22.5, 2: 22.5}
        self.coefficients = {
            1: [0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            2: [0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            3: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            4: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            5: [0.0, 1.0],
            6: [0.0, 1.0],
            7: [0.0, 1.0, 0.0, 0.0],
            8: [0.0, 1.0, 0.0, 0.0],
            9: [0.0, 1.0, 0.0, 0.0],
        }
        self._random = Random(seed)
        self._tick = 0
        self._last_stream_at = 0.0

    def open(self) -> None:
        with self._lock:
            self._is_open = True

    def close(self) -> None:
        with self._lock:
            self._is_open = False

    def send_command(self, command_text: str, response_window_s: float = 0.3) -> str:
        del response_window_s
        with self._lock:
            self._require_open()
            parts = [part.strip() for part in command_text.strip().split(",") if part.strip()]
            if len(parts) < 3:
                return f"YGAS,{self.device_id},F,BAD_COMMAND"
            command = parts[0].upper()
            args = parts[3:]

            if command == "SETCOM":
                if args:
                    self.baudrate = int(float(args[0]))
                    self.data_bits = int(float(args[1])) if len(args) > 1 else self.data_bits
                    self.parity = str(args[2]).upper() if len(args) > 2 else self.parity
                    self.stop_bits = int(float(args[3])) if len(args) > 3 else self.stop_bits
                    return self._ack(True, "serial parameters updated; restart required")
                return self._param(self.baudrate, self.data_bits, self.parity, self.stop_bits)

            if command == "MODE":
                if args:
                    self.mode = max(1, min(3, int(float(args[0]))))
                    return self._ack(True, f"mode set to MODE{self.mode}")
                return self._param(self.mode)

            if command == "SETCOMWAY":
                if args:
                    self.active_send = str(args[0]).upper() in {"1", "TRUE", "ACTIVE"}
                    return self._ack(True, "communication mode updated")
                return self._param(1 if self.active_send else 0)

            if command == "FTD":
                if args:
                    self.ftd_hz = min(20, max(1, int(float(args[0]))))
                    return self._ack(True, f"frequency set to {self.ftd_hz} Hz")
                return self._param(self.ftd_hz)

            if command.startswith("AVERAGE"):
                if args:
                    value = max(1, min(399, int(float(args[0]))))
                    if command == "AVERAGE":
                        self.filter_window = value
                        return self._ack(True, f"filter window set to {self.filter_window}")
                    channel = 1 if command.endswith("1") else 2
                    if channel == 1:
                        self.average_co2 = value
                    else:
                        self.average_h2o = value
                    return self._ack(True, f"average channel {channel} set to {value}")
                if command == "AVERAGE":
                    return self._param(f"{self.filter_window:03d}")
                channel = 1 if command.endswith("1") else 2
                return self._param(f"{(self.average_co2 if channel == 1 else self.average_h2o):03d}")

            if command == "FILTER" and args:
                self.filter_window = max(1, min(399, int(float(args[0]))))
                return self._ack(True, f"filter window set to {self.filter_window}")

            if command == "GETCO" and args:
                index = int(float(args[0]))
                values = self.coefficients.get(index, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                return ",".join(f"C{i}:{value:.6g}" for i, value in enumerate(values))

            if command.startswith("SENCO"):
                index = int(command.replace("SENCO", "") or 0)
                self.coefficients[index] = [float(value) for value in args]
                return self._ack(True, f"coefficient group {index} written")

            if command.startswith("CLEARSENCO"):
                index = int(command.replace("CLEARSENCO", "") or 0)
                self.coefficients[index] = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
                return self._ack(True, f"coefficient group {index} cleared")

            if command == "ID":
                if args:
                    self.device_id = str(args[0]).upper()
                    return self._ack(True, f"device id set to {self.device_id}")
                return self._param(self.device_id)

            if command == "RESET":
                self._tick = 0
                return self._ack(True, "device restarted")

            if command == "SETPOW":
                if args:
                    self.lamp_power_mv = max(0, min(3000, int(float(args[0]))))
                    return self._ack(True, f"lamp power set to {self.lamp_power_mv} mV")
                return self._param(f"{self.lamp_power_mv:04d}")

            if command == "SETILLUM":
                self.reference_signal_mv = self.lamp_power_mv
                return self._ack(True, "current reference illumination captured")

            if command == "SETCO2":
                if args:
                    self.reference_signal_mv = max(100, min(4000, int(float(args[0]))))
                    return self._ack(True, f"reference signal set to {self.reference_signal_mv} mV")
                return self._param(f"{self.reference_signal_mv:04d}")

            if command == "TIMEOUT":
                if args:
                    self.timeout_compensation = max(900, min(1100, int(float(args[0]))))
                    return self._ack(True, f"timer compensation set to {self.timeout_compensation}")
                return self._param(self.timeout_compensation)

            if command.startswith("SENTEMP"):
                channel = 1 if command.endswith("1") else 2
                if args:
                    self.calibration_temperatures[channel] = float(args[0])
                    return self._ack(True, f"calibration temperature point {channel} updated")
                return self._param(f"{self.calibration_temperatures[channel]:.1f}")

            if command == "PING":
                return self._ack(True, "legacy ping response")
            if command == "READDATA":
                return self._generate_frame()
            return self._ack(False, "unsupported command")

    def request_frame(self, command_text: str, timeout_s: float = 0.3) -> str:
        del timeout_s
        return self.send_command(command_text)

    def read_stream(self, window_s: float = 0.25) -> str:
        del window_s
        with self._lock:
            self._require_open()
            if not self.active_send:
                return ""
            now = time.monotonic()
            min_interval = 1.0 / max(1, self.ftd_hz)
            if (now - self._last_stream_at) < min_interval:
                return ""
            self._last_stream_at = now
            frames = [self._generate_frame()]
            if self._random.random() < 0.18:
                frames.append(self._generate_frame())
            return "".join(frames)

    def _require_open(self) -> None:
        if not self._is_open:
            raise RuntimeError("Mock analyzer is not connected.")

    def _ack(self, success: bool, message: str) -> str:
        flag = "T" if success else "F"
        return f"YGAS,{self.device_id},{flag},{message}"

    def _param(self, *values: object) -> str:
        suffix = "," + ",".join(str(value) for value in values) if values else ""
        return f"YGAS,{self.device_id}{suffix}"

    def _generate_frame(self) -> str:
        self._tick += 1
        phase = self._tick / max(1.0, float(self.ftd_hz))
        co2 = 418.0 + math.sin(phase * 1.1) * 18.0 + self._random.uniform(-1.2, 1.2)
        h2o = 11.8 + math.cos(phase * 0.8) * 1.6 + self._random.uniform(-0.2, 0.2)
        pressure = 101.2 + math.sin(phase * 0.15) * 0.35
        chamber_temp = 24.8 + math.sin(phase * 0.4) * 0.9
        case_temp = 26.0 + math.cos(phase * 0.33) * 0.7
        co2_signal = 1030.0 + math.sin(phase) * 18.0
        h2o_signal = 870.0 + math.cos(phase) * 12.0
        if self.mode == 1:
            status_register = "0001"
            checksum = int((co2 * 10.0 + h2o * 100.0 + pressure * 100.0) % 10000)
            return (
                f"YGAS,{self.device_id},{co2:.3f},{h2o:.3f},"
                f"0.98,0.98,{chamber_temp:.2f},{pressure:.2f},{status_register},{checksum:04d}"
            )
        return (
            f"YGAS,{self.device_id},{co2:.3f},{h2o:.3f},"
            f"{co2 * 1.80:.3f},{h2o * 0.80:.3f},{co2 / 420.0:.6f},{co2 / 422.0:.6f},"
            f"{h2o / 8.2:.6f},{h2o / 8.4:.6f},{self.reference_signal_mv:d},{co2_signal:.3f},{h2o_signal:.3f},"
            f"{chamber_temp:.3f},{case_temp:.3f},{pressure:.3f},OK"
        )
