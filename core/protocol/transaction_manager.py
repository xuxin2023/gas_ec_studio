from __future__ import annotations

from collections import deque
from datetime import datetime
from uuid import uuid4

from core.protocol.ack_parser import parse_ack
from core.protocol.frame_splitter import classify_frame_text
from models.hf_models import FrameQuality
from models.result_models import TransactionRecord, TransactionStatus


class TransactionManager:
    def __init__(self, max_records: int = 200) -> None:
        self._records: deque[TransactionRecord] = deque(maxlen=max_records)
        self._index: dict[str, TransactionRecord] = {}

    def begin(
        self,
        *,
        label: str,
        command_text: str,
        device_uid: str,
        device_id: str,
        dangerous: bool = False,
        metadata: dict | None = None,
    ) -> TransactionRecord:
        record = TransactionRecord(
            transaction_id=uuid4().hex[:12],
            created_at=datetime.now(),
            label=label,
            command_text=command_text.strip(),
            device_uid=device_uid,
            device_id=device_id,
            dangerous=dangerous,
            metadata=dict(metadata or {}),
        )
        self._records.appendleft(record)
        self._index[record.transaction_id] = record
        return record

    def finish(
        self,
        transaction_id: str,
        *,
        response_text: str,
        timeout: bool = False,
    ) -> TransactionRecord:
        record = self._index[transaction_id]
        response_text = str(response_text or "").strip()
        quality = classify_frame_text(response_text)
        record.response_text = response_text
        record.response_quality = quality
        record.finished_at = datetime.now()
        if timeout:
            record.status = TransactionStatus.TIMEOUT
            record.response_summary = "命令执行超时"
            return record
        ack = parse_ack(response_text)
        if ack:
            record.status = TransactionStatus.SUCCEEDED if ack.success else TransactionStatus.FAILED
            record.response_quality = FrameQuality.ACK_ONLY
            record.response_summary = "设备确认成功" if ack.success else "设备返回失败确认"
            return record
        if quality in {FrameQuality.FULL, FrameQuality.PARTIAL}:
            record.status = TransactionStatus.SUCCEEDED
            record.response_summary = "已收到有效数据帧"
        elif quality == FrameQuality.TRUNCATED:
            record.status = TransactionStatus.FAILED
            record.response_summary = "响应帧被截断，请检查线路或设备输出频率"
        elif quality == FrameQuality.CORRUPTED:
            record.status = TransactionStatus.FAILED
            record.response_summary = "响应内容损坏，可能存在粘连或波特率配置异常"
        else:
            record.status = TransactionStatus.FAILED
            record.response_summary = "未识别的响应内容"
        return record

    def recent(self) -> list[TransactionRecord]:
        return list(self._records)
