from __future__ import annotations

import time
from typing import Any

from core.adapters.base import BaseGasAnalyzerAdapter

try:
    import serial
except Exception:  # pragma: no cover - optional at test time
    serial = None


class SerialGasAnalyzerAdapter(BaseGasAnalyzerAdapter):
    def __init__(self, *, port: str, baudrate: int, device_id: str, timeout: float = 0.08) -> None:
        super().__init__(device_id=device_id)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Any = None

    def open(self) -> None:
        if serial is None:
            raise RuntimeError("当前环境缺少 pyserial，无法连接真实串口设备")
        with self._lock:
            if self._serial and self._serial.is_open:
                self._is_open = True
                return
            self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self._is_open = True

    def close(self) -> None:
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._is_open = False

    def send_command(self, command_text: str, response_window_s: float = 0.3) -> str:
        with self._lock:
            self._require_open()
            self._serial.reset_input_buffer()
            self._serial.write(command_text.encode("utf-8"))
            self._serial.flush()
            return self._collect_window(response_window_s)

    def request_frame(self, command_text: str, timeout_s: float = 0.3) -> str:
        return self.send_command(command_text, response_window_s=timeout_s)

    def read_stream(self, window_s: float = 0.25) -> str:
        with self._lock:
            self._require_open()
            return self._collect_window(window_s)

    def _collect_window(self, window_s: float) -> str:
        end_at = time.monotonic() + max(0.02, float(window_s))
        chunks: list[str] = []
        while time.monotonic() < end_at:
            waiting = int(getattr(self._serial, "in_waiting", 0) or 0)
            if waiting > 0:
                chunks.append(self._serial.read(waiting).decode("utf-8", errors="ignore"))
                continue
            line = self._serial.readline().decode("utf-8", errors="ignore")
            if line:
                chunks.append(line)
                continue
            time.sleep(0.01)
        return "".join(chunks).strip()

    def _require_open(self) -> None:
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("串口尚未连接，请先检查 COM 口和波特率")
