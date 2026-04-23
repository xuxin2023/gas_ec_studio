from __future__ import annotations

import math
import time
from random import Random

from core.adapters.base import BaseGasAnalyzerAdapter


class MockGasAnalyzerAdapter(BaseGasAnalyzerAdapter):
    def __init__(self, *, device_id: str, seed: int = 42) -> None:
        super().__init__(device_id=device_id)
        self.mode = 2
        self.active_send = True
        self.ftd_hz = 10
        self.average_co2 = 4
        self.average_h2o = 4
        self.filter_window = 49
        self.coefficients = {
            0: [0.998, 1.002, 0.004, 0.0, 0.0, 0.0],
            1: [1.012, 0.998, 0.006, 0.0, 0.0, 0.0],
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
            if command == "MODE" and args:
                self.mode = 1 if str(args[0]) == "1" else 2
                return self._ack(True, f"模式已切换为 MODE{self.mode}")
            if command == "SETCOMWAY" and args:
                self.active_send = str(args[0]) in {"1", "TRUE", "ACTIVE"}
                return self._ack(True, "通信方式已更新")
            if command == "FTD" and args:
                self.ftd_hz = max(1, int(float(args[0])))
                return self._ack(True, f"频率已设为 {self.ftd_hz} Hz")
            if command.startswith("AVERAGE") and args:
                channel = 1 if command.endswith("1") else 2
                value = max(1, int(float(args[0])))
                if channel == 1:
                    self.average_h2o = value
                else:
                    self.average_co2 = value
                return self._ack(True, f"平均参数已更新 ch={channel}")
            if command == "FILTER" and args:
                self.filter_window = max(1, int(float(args[0])))
                return self._ack(True, f"滤波窗口已设为 {self.filter_window}")
            if command == "GETCO" and args:
                index = int(args[0])
                values = self.coefficients.get(index, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                return ",".join(f"C{i}:{value:.6g}" for i, value in enumerate(values))
            if command.startswith("SENCO"):
                index = int(command.replace("SENCO", "") or 0)
                self.coefficients[index] = [float(value) for value in args]
                return self._ack(True, f"系数组 {index} 已写入")
            if command == "ID" and args:
                self.device_id = str(args[0]).upper()
                return self._ack(True, f"设备 ID 已写入 {self.device_id}")
            if command == "PING":
                return self._ack(True, "FFF 广播收到响应")
            if command == "READDATA":
                return self._generate_frame()
            return self._ack(False, "设备不支持该操作")

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
            raise RuntimeError("模拟设备尚未连接")

    def _ack(self, success: bool, message: str) -> str:
        flag = "T" if success else "F"
        return f"YGAS,{self.device_id},{flag},{message}"

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
            return (
                f"YGAS,{self.device_id},{co2:.3f},{h2o:.3f},"
                f"{co2_signal:.3f},{h2o_signal:.3f},{chamber_temp:.3f},{pressure:.3f},OK"
            )
        return (
            f"YGAS,{self.device_id},{co2:.3f},{h2o:.3f},"
            f"{co2 / 480.0:.6f},{h2o / 100.0:.6f},{co2 / 420.0:.6f},{co2 / 422.0:.6f},"
            f"{h2o / 8.2:.6f},{h2o / 8.4:.6f},{1015.0:.3f},{co2_signal:.3f},{h2o_signal:.3f},"
            f"{chamber_temp:.3f},{case_temp:.3f},{pressure:.3f},OK"
        )
