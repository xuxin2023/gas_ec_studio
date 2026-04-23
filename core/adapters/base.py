from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock


class BaseGasAnalyzerAdapter(ABC):
    def __init__(self, *, device_id: str) -> None:
        self.device_id = device_id
        self._is_open = False
        self._lock = Lock()

    @property
    def is_open(self) -> bool:
        return self._is_open

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command_text: str, response_window_s: float = 0.3) -> str:
        raise NotImplementedError

    @abstractmethod
    def request_frame(self, command_text: str, timeout_s: float = 0.3) -> str:
        raise NotImplementedError

    @abstractmethod
    def read_stream(self, window_s: float = 0.25) -> str:
        raise NotImplementedError
