from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any, Protocol

from src.domain.enums import ProcessMessageType
from src.domain.models import MitmCaptureResult, ProcessMessage
from src.modules.proxy.capture_buffer import CaptureBuffer
from src.modules.proxy.proxy_lifecycle import ProxyLifecycle


class SessionChannel(Protocol):
    def receive(self, *, timeout: float | None = None) -> ProcessMessage | None: ...

    def send(self, message_type: ProcessMessageType, payload: dict | None = None) -> None: ...


LifecycleFactory = Callable[[str, dict[str, Any]], ProxyLifecycle]


class _CaptureCancelled(RuntimeError):
    pass


class MitmCaptureSession:
    """MITM 子进程中的一次性捕获协议，不处理下一次尝试。"""

    def __init__(
        self,
        *,
        channel: SessionChannel,
        buffer: CaptureBuffer,
        expected_proxy_lease_id: str,
        lifecycle_factory: LifecycleFactory,
        capture_timeout_seconds: float,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if not expected_proxy_lease_id.strip():
            raise ValueError("expected_proxy_lease_id 不能为空")
        if capture_timeout_seconds <= 0:
            raise ValueError("capture_timeout_seconds 必须大于 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        self._channel = channel
        self._buffer = buffer
        self._expected_proxy_lease_id = expected_proxy_lease_id
        self._lifecycle_factory = lifecycle_factory
        self._capture_timeout_seconds = float(capture_timeout_seconds)
        self._poll_interval_seconds = float(poll_interval_seconds)

    def run(self, *, start_timeout_seconds: float) -> MitmCaptureResult:
        lifecycle: ProxyLifecycle | None = None
        lifecycle_started = False
        try:
            start_message = self._channel.receive(timeout=start_timeout_seconds)
            if start_message is None:
                raise RuntimeError("等待 START_CAPTURE 超时")
            if start_message.message_type is not ProcessMessageType.START_CAPTURE:
                raise RuntimeError("子进程首条消息必须是 START_CAPTURE")

            lease_id = str(start_message.payload.get("proxy_lease_id", "")).strip()
            if lease_id != self._expected_proxy_lease_id:
                raise RuntimeError("proxy_lease_id 与本次子进程身份不匹配")

            lifecycle = self._lifecycle_factory(lease_id, dict(start_message.payload))
            session_state = lifecycle.start()
            lifecycle_started = True
            self._channel.send(
                ProcessMessageType.READY,
                {
                    "listen_started_at": session_state.listen_started_at,
                    "proxy_address": session_state.proxy_address,
                    "proxy_lease_id": session_state.proxy_lease_id,
                },
            )

            capture_timeout = float(
                start_message.payload.get(
                    "capture_timeout_seconds",
                    self._capture_timeout_seconds,
                )
            )
            if capture_timeout <= 0:
                raise RuntimeError("capture_timeout_seconds 必须大于 0")
            deadline = time.monotonic() + capture_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("等待 STOP_CAPTURE 超时")
                command = self._channel.receive(
                    timeout=min(self._poll_interval_seconds, remaining)
                )
                if command is None:
                    continue
                if command.message_type is ProcessMessageType.CANCEL:
                    raise _CaptureCancelled("主流程取消本次 MITM 捕获")
                if command.message_type is not ProcessMessageType.STOP_CAPTURE:
                    raise RuntimeError(f"捕获期间收到不支持的消息：{command.message_type.value}")

                # 先冻结变量，再关闭代理；关闭完成后才能把结果交回主流程。
                result = self._buffer.freeze()
                lifecycle.stop()
                lifecycle_started = False
                self._channel.send(
                    ProcessMessageType.RESULT,
                    {"capture_result": result.to_dict()},
                )
                return result
        except _CaptureCancelled as exc:
            cleanup_error = self._stop_lifecycle(lifecycle, lifecycle_started)
            message = str(exc) if not cleanup_error else f"{exc}；{cleanup_error}"
            result = self._failed_result(error_stage="cancelled", error_message=message)
            self._safe_send_failed(result)
            return result
        except Exception as exc:
            cleanup_error = self._stop_lifecycle(lifecycle, lifecycle_started)
            message = str(exc) if not cleanup_error else f"{exc}；{cleanup_error}"
            result = self._failed_result(error_stage="mitm_capture", error_message=message)
            self._safe_send_failed(result)
            return result

    def _failed_result(self, *, error_stage: str, error_message: str) -> MitmCaptureResult:
        return MitmCaptureResult.failed(
            task_id=self._buffer.task_id,
            attempt_id=self._buffer.attempt_id,
            error_stage=error_stage,
            error_message=error_message,
            capture_events=self._buffer.capture_events,
        )

    def _safe_send_failed(self, result: MitmCaptureResult) -> None:
        try:
            self._channel.send(
                ProcessMessageType.FAILED,
                {"capture_result": result.to_dict()},
            )
        except Exception:
            # 通道已经断开时只能退出子进程，父进程会按快照执行兜底收尾。
            return

    @staticmethod
    def _stop_lifecycle(lifecycle: ProxyLifecycle | None, started: bool) -> str:
        if lifecycle is None or not started:
            return ""
        try:
            lifecycle.stop()
            return ""
        except Exception as exc:
            return f"代理会话清理失败：{exc}"
