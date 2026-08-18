from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from src.domain.models import MitmCaptureResult
from src.modules.proxy.capture_buffer import CaptureBuffer
from src.modules.proxy.mitmproxy_listener import MitmproxyListener
from src.modules.proxy.proxy_lifecycle import ProxyLifecycle
from src.modules.proxy.proxy_state import ProxySessionState
from src.modules.system.windows_system_proxy import WindowsSystemProxy


class InProcessMitmCaptureError(RuntimeError):
    """进程内 MITM 捕获生命周期失败。"""


class MitmListenerFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


class SystemProxyFactory(Protocol):
    def __call__(self) -> Any: ...


class InProcessMitmCaptureService:
    """在当前 Huey 任务线程内执行一次 MITM 捕获，不再额外创建子进程。"""

    def __init__(
        self,
        *,
        listener_factory: MitmListenerFactory = MitmproxyListener,
        system_proxy_factory: SystemProxyFactory = WindowsSystemProxy,
        lifecycle_factory: Any = ProxyLifecycle,
        buffer_factory: Any = CaptureBuffer,
    ) -> None:
        self._listener_factory = listener_factory
        self._system_proxy_factory = system_proxy_factory
        self._lifecycle_factory = lifecycle_factory
        self._buffer_factory = buffer_factory

    def start_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        proxy_lease_id: str,
        proxy_address: str,
        capture_config: Mapping[str, Any],
    ) -> InProcessMitmAttempt:
        """同步启动 MITM listener 和系统代理，并返回本次捕获句柄。"""

        buffer = self._buffer_factory(task_id=task_id, attempt_id=attempt_id)
        listener = self._listener_factory(
            host=str(capture_config.get("host") or "127.0.0.1"),
            port=int(capture_config.get("port") or 18000),
            confdir=Path(str(capture_config.get("confdir") or ".mitmproxy")),
            ssl_insecure=bool(capture_config.get("ssl_insecure", True)),
            buffer=buffer,
            ready_timeout_seconds=float(capture_config.get("ready_timeout_seconds") or 10.0),
            shutdown_timeout_seconds=float(
                capture_config.get("shutdown_timeout_seconds") or 3.0
            ),
        )
        lifecycle = self._lifecycle_factory(
            listener=listener,
            system_proxy=self._system_proxy_factory(),
            proxy_address=proxy_address,
            proxy_lease_id=proxy_lease_id,
            publish_snapshot=lambda _snapshot: None,
        )
        try:
            session_state = lifecycle.start()
        except Exception as exc:
            raise InProcessMitmCaptureError(f"进程内 MITM 启动失败：{exc}") from exc
        return InProcessMitmAttempt(
            buffer=buffer,
            lifecycle=lifecycle,
            session_state=session_state,
        )


class InProcessMitmAttempt:
    """当前进程内的一次 MITM 捕获尝试。"""

    def __init__(
        self,
        *,
        buffer: CaptureBuffer,
        lifecycle: Any,
        session_state: ProxySessionState,
    ) -> None:
        self._buffer = buffer
        self._lifecycle = lifecycle
        self._session_state = session_state
        self._closed = False

    def wait_ready(self, *, timeout_seconds: float) -> dict[str, Any]:
        """兼容原子进程句柄接口；start_attempt 返回时已经 READY。"""

        del timeout_seconds
        return {
            "proxy_lease_id": self._session_state.proxy_lease_id,
            "proxy_address": self._session_state.proxy_address,
            "listen_started_at": self._session_state.listen_started_at,
        }

    def stop_capture(self, *, timeout_seconds: float) -> MitmCaptureResult:
        """冻结捕获结果，并按系统代理优先、MITM 随后的顺序关闭。"""

        del timeout_seconds
        if self._closed:
            raise InProcessMitmCaptureError("进程内 MITM 捕获已经结束")
        result: MitmCaptureResult | None = None
        close_error: Exception | None = None
        try:
            result = self._buffer.freeze()
        finally:
            try:
                self._lifecycle.stop()
            except Exception as exc:
                close_error = exc
            self._closed = True
        if close_error is not None:
            raise InProcessMitmCaptureError(f"进程内 MITM 关闭失败：{close_error}") from close_error
        return result

    def cancel(self) -> None:
        if self._closed:
            return
        try:
            self._lifecycle.stop()
        finally:
            self._closed = True


__all__ = [
    "InProcessMitmAttempt",
    "InProcessMitmCaptureError",
    "InProcessMitmCaptureService",
]
