from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from models.hf_models import FrameQuality


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


@dataclass(slots=True)
class TransactionRecord:
    transaction_id: str
    created_at: datetime
    label: str
    command_text: str
    device_uid: str
    device_id: str
    dangerous: bool = False
    status: TransactionStatus = TransactionStatus.PENDING
    response_text: str = ""
    response_quality: FrameQuality = FrameQuality.UNKNOWN
    response_summary: str = ""
    finished_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "label": self.label,
            "command_text": self.command_text,
            "device_uid": self.device_uid,
            "device_id": self.device_id,
            "dangerous": int(self.dangerous),
            "status": self.status.value,
            "response_text": self.response_text,
            "response_quality": self.response_quality.value,
            "response_summary": self.response_summary,
            "metadata_json": self.metadata,
        }


@dataclass(slots=True)
class PipelineResult:
    pipeline_name: str
    created_at: datetime
    status: str
    message: str
    artifacts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExportArtifact:
    created_at: datetime
    kind: str
    path: str
    summary: str


@dataclass(slots=True)
class EventRecord:
    event_id: str
    created_at: datetime
    device_uid: str
    device_id: str
    severity: str
    title: str
    message: str
    category: str
    related_timestamp: datetime | None = None
    raw_text: str = ""
    parsed_snapshot: dict[str, Any] = field(default_factory=dict)
