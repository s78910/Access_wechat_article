from __future__ import annotations

import time
from typing import Any, Mapping, Protocol

from src.domain.enums import ProcessMessageType
from src.domain.models import MitmCaptureResult, ProcessMessage
from src.modules.processes.process_launcher import LaunchedProcess
from src.modules.proxy.proxy_state import ProxySnapshot, proxy_points_to


class ProcessLauncher(Protocol):
    def launch(
        self,
        *,
        task_id: str,
        attempt_id: str,
        proxy_lease_id: str,
    ) -> LaunchedProcess: ...


class FallbackSystemProxy(Protocol):
    def current(self) -> ProxySnapshot: ...

    def restore(self, snapshot: ProxySnapshot) -> None: ...


class MitmProcessError(RuntimeError):
    """一次 MITM 捕获子进程未按协议完成。"""

    def __init__(self, message: str, *, result: MitmCaptureResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class MitmProcessControlService:
    """创建一次性 MITM 子进程，不在服务内复用旧进程。"""

    def __init__(
        self,
        *,
        launcher: ProcessLauncher,
        fallback_system_proxy: FallbackSystemProxy,
        cancel_grace_seconds: float = 1.0,
        terminate_grace_seconds: float = 1.0,
    ) -> None:
        self._launcher = launcher
        self._fallback_system_proxy = fallback_system_proxy
        self._cancel_grace_seconds = max(0.0, float(cancel_grace_seconds))
        self._terminate_grace_seconds = max(0.0, float(terminate_grace_seconds))

    def start_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        proxy_lease_id: str,
        proxy_address: str,
        capture_config: Mapping[str, Any],
    ) -> MitmAttemptProcess:
        launched = self._launcher.launch(
            task_id=task_id,
            attempt_id=attempt_id,
            proxy_lease_id=proxy_lease_id,
        )
        attempt = MitmAttemptProcess(
            launched=launched,
            proxy_address=proxy_address,
            fallback_system_proxy=self._fallback_system_proxy,
            cancel_grace_seconds=self._cancel_grace_seconds,
            terminate_grace_seconds=self._terminate_grace_seconds,
        )
        payload = dict(capture_config)
        payload["proxy_lease_id"] = proxy_lease_id
        try:
            attempt.channel.send(ProcessMessageType.START_CAPTURE, payload)
        except Exception:
            attempt.force_cleanup()
            raise
        return attempt


class MitmAttemptProcess:
    """父进程持有的一次采集尝试句柄。"""

    def __init__(
        self,
        *,
        launched: LaunchedProcess,
        proxy_address: str,
        fallback_system_proxy: FallbackSystemProxy,
        cancel_grace_seconds: float,
        terminate_grace_seconds: float,
    ) -> None:
        self.process = launched.process
        self.channel = launched.channel
        self._proxy_address = proxy_address
        self._fallback_system_proxy = fallback_system_proxy
        self._cancel_grace_seconds = cancel_grace_seconds
        self._terminate_grace_seconds = terminate_grace_seconds
        self._proxy_snapshot: ProxySnapshot | None = None
        self._ready = False
        self._closed = False

    def wait_ready(self, *, timeout_seconds: float) -> dict[str, Any]:
        message = self._wait_for(
            {ProcessMessageType.READY, ProcessMessageType.FAILED},
            timeout_seconds=timeout_seconds,
        )
        if message is None:
            self.force_cleanup()
            raise MitmProcessError("等待 MITM 子进程 READY 超时")
        if message.message_type is ProcessMessageType.FAILED:
            result = self._read_capture_result(message)
            self._join_after_terminal_message()
            raise MitmProcessError(result.error_message or "MITM 子进程启动失败", result=result)
        self._ready = True
        return dict(message.payload)

    def stop_capture(self, *, timeout_seconds: float) -> MitmCaptureResult:
        if not self._ready:
            raise MitmProcessError("MITM 子进程尚未 READY，不能发送 STOP_CAPTURE")
        if self._closed:
            raise MitmProcessError("MITM 子进程已结束")
        self.channel.send(ProcessMessageType.STOP_CAPTURE)
        message = self._wait_for(
            {ProcessMessageType.RESULT, ProcessMessageType.FAILED},
            timeout_seconds=timeout_seconds,
        )
        if message is None:
            self.force_cleanup()
            raise MitmProcessError("等待 MITM 子进程 RESULT 超时")

        result = self._read_capture_result(message)
        self._join_after_terminal_message()
        if message.message_type is ProcessMessageType.FAILED:
            raise MitmProcessError(result.error_message or "MITM 子进程失败", result=result)
        return result

    def cancel(self) -> None:
        if self._closed:
            return
        try:
            self.channel.send(ProcessMessageType.CANCEL)
            message = self._wait_for(
                {ProcessMessageType.FAILED, ProcessMessageType.RESULT},
                timeout_seconds=self._cancel_grace_seconds,
            )
            if message is not None:
                self._join_after_terminal_message()
                return
        except Exception:
            pass
        self.force_cleanup(send_cancel=False)

    def force_cleanup(self, *, send_cancel: bool = True) -> None:
        if self._closed:
            return
        if self.process.is_alive() and send_cancel:
            try:
                self.channel.send(ProcessMessageType.CANCEL)
            except Exception:
                pass
            self.process.join(self._cancel_grace_seconds)

        # 没有收到终态消息就属于异常收尾；即使子进程已经崩溃，也要按已发布
        # 的快照检查并恢复仍由本任务占用的系统代理。
        self._restore_proxy_fallback()

        if self.process.is_alive():
            self.process.terminate()
            self.process.join(self._terminate_grace_seconds)

        if self.process.is_alive():
            kill = getattr(self.process, "kill", None)
            if callable(kill):
                kill()
                self.process.join(self._terminate_grace_seconds)
        self._close_channel()

    def _wait_for(
        self,
        accepted_types: set[ProcessMessageType],
        *,
        timeout_seconds: float,
    ) -> ProcessMessage | None:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            message = self.channel.receive(timeout=remaining)
            if message is None:
                return None
            if message.message_type is ProcessMessageType.PROXY_SNAPSHOT:
                raw_snapshot = message.payload.get("snapshot", {})
                if not isinstance(raw_snapshot, Mapping):
                    raise MitmProcessError("MITM 子进程返回的代理快照格式无效")
                self._proxy_snapshot = ProxySnapshot.from_dict(raw_snapshot)
                if time.monotonic() >= deadline:
                    return None
                continue
            if message.message_type in accepted_types:
                return message
            raise MitmProcessError(f"MITM 子进程返回了非预期消息：{message.message_type.value}")

    @staticmethod
    def _read_capture_result(message: ProcessMessage) -> MitmCaptureResult:
        raw_result = message.payload.get("capture_result", {})
        if not isinstance(raw_result, Mapping):
            raise MitmProcessError("MITM 捕获结果格式无效")
        try:
            return MitmCaptureResult.from_dict(raw_result)
        except (TypeError, ValueError) as exc:
            raise MitmProcessError(f"MITM 捕获结果格式无效：{exc}") from exc

    def _join_after_terminal_message(self) -> None:
        self.process.join(self._cancel_grace_seconds)
        if self.process.is_alive():
            self.force_cleanup()
            return
        self._close_channel()

    def _restore_proxy_fallback(self) -> None:
        if self._proxy_snapshot is None:
            return
        try:
            current = self._fallback_system_proxy.current()
            if proxy_points_to(current, self._proxy_address):
                self._fallback_system_proxy.restore(self._proxy_snapshot)
        except Exception:
            # 父进程清理仍需继续 terminate；具体恢复错误由上层日志记录。
            return

    def _close_channel(self) -> None:
        close = getattr(self.channel, "close", None)
        if callable(close):
            close()
        self._closed = True
