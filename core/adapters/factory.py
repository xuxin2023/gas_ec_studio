from __future__ import annotations

from core.adapters.base import BaseGasAnalyzerAdapter
from core.adapters.mock_adapter import MockGasAnalyzerAdapter
from core.adapters.serial_adapter import SerialGasAnalyzerAdapter


def build_adapter(
    *,
    port: str,
    baudrate: int,
    device_id: str,
    analyzer_profile: str = "ygas_irga",
) -> BaseGasAnalyzerAdapter:
    normalized_port = str(port or "").strip().upper()
    if normalized_port.startswith("SIM"):
        return MockGasAnalyzerAdapter(device_id=device_id, analyzer_profile=analyzer_profile)
    return SerialGasAnalyzerAdapter(port=port, baudrate=baudrate, device_id=device_id)
