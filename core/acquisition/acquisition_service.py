from __future__ import annotations

import atexit
import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock, Thread, current_thread
from typing import Callable
import weakref

from core.adapters.base import BaseGasAnalyzerAdapter
from core.protocol.ack_parser import parse_ack
from core.protocol.command_builder import CommandBuilder
from core.protocol.frame_splitter import FrameChunk, FrameSplitter
from core.protocol.licor_diag_parser import parse_licor_diag_frame
from core.protocol.mode1_parser import parse_mode1_frame
from core.protocol.mode2_parser import parse_mode2_frame
from core.protocol.parameter_parser import parse_parameter_response
from core.protocol.software_profile import SoftwareProfile
from models.hf_models import FrameQuality, ProtocolFrame


_REGISTERED_SERVICES: weakref.WeakSet["AcquisitionService"] = weakref.WeakSet()
_REGISTERED_SERVICES_LOCK = Lock()


def shutdown_all_acquisition_services() -> None:
    with _REGISTERED_SERVICES_LOCK:
        services = list(_REGISTERED_SERVICES)
    for service in services:
        try:
            service.shutdown()
        except Exception:
            continue


atexit.register(shutdown_all_acquisition_services)


@dataclass(slots=True)
class AcquisitionSession:
    device_uid: str
    device_id: str
    adapter: BaseGasAnalyzerAdapter
    builder: CommandBuilder
    profile: SoftwareProfile
    active_send: bool
    ftd_hz: int
    splitter: FrameSplitter = field(default_factory=FrameSplitter)
    task: asyncio.Task | None = None
    connected: bool = False


class AcquisitionService:
    def __init__(
        self,
        *,
        frame_callback: Callable[[str, ProtocolFrame], None],
        log_callback: Callable[[str, str], None],
    ) -> None:
        self._frame_callback = frame_callback
        self._log_callback = log_callback
        self._sessions: dict[str, AcquisitionSession] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, name="gas-ec-acquisition", daemon=True)
        self._thread_lock = Lock()
        self._closed = False
        with _REGISTERED_SERVICES_LOCK:
            _REGISTERED_SERVICES.add(self)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_loop_thread(self) -> None:
        if self._closed or self._loop.is_closed():
            raise RuntimeError("Acquisition service has been shut down.")
        if self._thread.is_alive():
            return
        with self._thread_lock:
            if not self._thread.is_alive():
                self._thread.start()

    def shutdown(self) -> None:
        if self._closed:
            return
        for device_uid in list(self._sessions.keys()):
            try:
                self.disconnect_session(device_uid)
            except Exception:
                continue
        self._closed = True
        thread_started = self._thread.ident is not None
        if thread_started and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if thread_started and self._thread.is_alive() and current_thread() is not self._thread:
            self._thread.join(timeout=3.0)
        if not self._loop.is_closed():
            try:
                pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.run_until_complete(self._loop.shutdown_default_executor())
            finally:
                self._loop.close()
        with _REGISTERED_SERVICES_LOCK:
            _REGISTERED_SERVICES.discard(self)

    def connect_session(
        self,
        *,
        device_uid: str,
        device_id: str,
        adapter: BaseGasAnalyzerAdapter,
        builder: CommandBuilder,
        profile: SoftwareProfile,
        active_send: bool,
        ftd_hz: int,
    ) -> None:
        self._call(
            self._async_connect(
                device_uid=device_uid,
                device_id=device_id,
                adapter=adapter,
                builder=builder,
                profile=profile,
                active_send=active_send,
                ftd_hz=ftd_hz,
            )
        )

    def disconnect_session(self, device_uid: str) -> None:
        self._call(self._async_disconnect(device_uid))

    def update_session(self, device_uid: str, **changes: object) -> None:
        self._call(self._async_update(device_uid, **changes))

    def execute_command(self, device_uid: str, command_text: str, *, timeout_s: float = 0.35) -> str:
        return self._call(self._async_execute_command(device_uid, command_text, timeout_s=timeout_s))

    def decode_payload(self, raw_text: str, *, source: str, fallback_device_id: str) -> list[ProtocolFrame]:
        splitter = FrameSplitter()
        frames = splitter.feed(raw_text)
        frames.extend(splitter.flush())
        if not frames and str(raw_text or "").strip():
            frames.append(FrameChunk(str(raw_text).strip(), FrameQuality.UNKNOWN))
        return [self._build_protocol_frame(chunk, source=source, fallback_device_id=fallback_device_id) for chunk in frames]

    async def _async_connect(
        self,
        *,
        device_uid: str,
        device_id: str,
        adapter: BaseGasAnalyzerAdapter,
        builder: CommandBuilder,
        profile: SoftwareProfile,
        active_send: bool,
        ftd_hz: int,
    ) -> None:
        if device_uid in self._sessions and self._sessions[device_uid].connected:
            return
        await asyncio.to_thread(adapter.open)
        session = AcquisitionSession(
            device_uid=device_uid,
            device_id=device_id,
            adapter=adapter,
            builder=builder,
            profile=profile,
            active_send=active_send,
            ftd_hz=max(1, int(ftd_hz)),
            connected=True,
        )
        session.task = asyncio.create_task(self._run_session(session))
        self._sessions[device_uid] = session
        self._log_callback("info", f"设备 {device_id} 已建立采集会话")

    async def _async_disconnect(self, device_uid: str) -> None:
        session = self._sessions.get(device_uid)
        if session is None:
            return
        session.connected = False
        if session.task:
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass
        trailing = session.splitter.flush()
        for chunk in trailing:
            frame = self._build_protocol_frame(chunk, source="disconnect_flush", fallback_device_id=session.device_id)
            self._frame_callback(device_uid, frame)
        await asyncio.to_thread(session.adapter.close)
        self._sessions.pop(device_uid, None)
        self._log_callback("info", f"设备 {session.device_id} 已断开采集会话")

    async def _async_update(self, device_uid: str, **changes: object) -> None:
        session = self._sessions.get(device_uid)
        if session is None:
            return
        if "device_id" in changes:
            session.device_id = str(changes["device_id"])
            session.adapter.device_id = session.device_id
        if "active_send" in changes:
            session.active_send = bool(changes["active_send"])
        if "ftd_hz" in changes:
            session.ftd_hz = max(1, int(changes["ftd_hz"]))

    async def _async_execute_command(self, device_uid: str, command_text: str, *, timeout_s: float) -> str:
        session = self._sessions.get(device_uid)
        if session is None:
            raise RuntimeError("设备尚未连接，请先在设备中心建立连接")
        return await asyncio.to_thread(session.adapter.send_command, command_text, timeout_s)

    async def _run_session(self, session: AcquisitionSession) -> None:
        while session.connected:
            try:
                if session.active_send:
                    raw_text = await asyncio.to_thread(
                        session.adapter.read_stream,
                        session.profile.active_read_window_s,
                    )
                    source = "active"
                else:
                    command_text = session.builder.read_frame(target_id=session.device_id)
                    raw_text = await asyncio.to_thread(
                        session.adapter.request_frame,
                        command_text,
                        session.profile.passive_read_window_s,
                    )
                    source = "passive"
                if raw_text:
                    for chunk in session.splitter.feed(raw_text):
                        frame = self._build_protocol_frame(chunk, source=source, fallback_device_id=session.device_id)
                        self._frame_callback(session.device_uid, frame)
                await asyncio.sleep(max(0.02, 1.0 / max(1, session.ftd_hz)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_callback("error", f"采集会话中断：{exc}")
                await asyncio.sleep(0.2)

    def _build_protocol_frame(
        self,
        chunk: FrameChunk,
        *,
        source: str,
        fallback_device_id: str,
    ) -> ProtocolFrame:
        raw_text = chunk.text.strip()
        ack = parse_ack(raw_text)
        parsed = (
            parse_mode2_frame(raw_text)
            or parse_mode1_frame(raw_text)
            or parse_licor_diag_frame(raw_text)
            or parse_parameter_response(raw_text)
            or {}
        )
        quality = chunk.quality
        if parsed and "frame_quality" in parsed:
            quality = parsed["frame_quality"]
        device_id = None
        mode = None
        status_text = None
        is_ack = False
        if ack:
            device_id = ack.device_id
            status_text = ack.message
            is_ack = True
        elif parsed:
            device_id = str(parsed.get("device_id") or fallback_device_id)
            mode = parsed.get("mode")
            status_text = parsed.get("status_text")
        else:
            device_id = fallback_device_id
        return ProtocolFrame(
            received_at=datetime.now(),
            raw_text=raw_text,
            source=source,
            quality=quality,
            device_id=device_id,
            mode=mode,
            parsed=parsed,
            status_text=status_text,
            is_ack=is_ack,
        )

    def _call(self, coro: asyncio.Future | asyncio.Task | asyncio.coroutines) -> object:
        if self._closed or self._loop.is_closed():
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise RuntimeError("Acquisition service has been shut down.")
        self._ensure_loop_thread()
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()
