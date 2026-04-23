from core.protocol.transaction_manager import TransactionManager
from models.hf_models import FrameQuality
from models.result_models import TransactionStatus


def test_transaction_manager_ack_success_flow() -> None:
    manager = TransactionManager()
    record = manager.begin(
        label="切换模式",
        command_text="MODE,YGAS,001,2",
        device_uid="dev1",
        device_id="001",
    )
    done = manager.finish(record.transaction_id, response_text="YGAS,001,T")
    assert done.status == TransactionStatus.SUCCEEDED
    assert done.response_quality == FrameQuality.ACK_ONLY
    assert "确认成功" in done.response_summary


def test_transaction_manager_detects_corrupted_response() -> None:
    manager = TransactionManager()
    record = manager.begin(
        label="读取单帧",
        command_text="READDATA,YGAS,001",
        device_uid="dev1",
        device_id="001",
    )
    done = manager.finish(record.transaction_id, response_text="YGAS,001,BAD,FRAME")
    assert done.status == TransactionStatus.FAILED
    assert done.response_quality == FrameQuality.CORRUPTED
    assert "损坏" in done.response_summary


def test_transaction_manager_marks_timeout() -> None:
    manager = TransactionManager()
    record = manager.begin(
        label="读取系数",
        command_text="GETCO,YGAS,001,0",
        device_uid="dev1",
        device_id="001",
    )
    done = manager.finish(record.transaction_id, response_text="", timeout=True)
    assert done.status == TransactionStatus.TIMEOUT
