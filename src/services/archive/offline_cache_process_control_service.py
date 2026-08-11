from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Protocol

from src.domain.enums import ProcessMessageType
from src.domain.models import ProcessMessage
from src.modules.processes.offline_cache_process_launcher import (
    MultiprocessingOfflineCacheProcessLauncher,
)
from src.modules.processes.process_launcher import LaunchedProcess


class OfflineCacheProcessLauncher(Protocol):
    def launch(
        self,
        *,
        task_id: str,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> LaunchedProcess: ...


class OfflineCacheProcessError(RuntimeError):
    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result


class OfflineCacheProcessControlService:
    """启动并回收一次性 Playwright 离线缓存子进程。"""

    def __init__(
        self,
        *,
        launcher: OfflineCacheProcessLauncher | None = None,
        join_timeout_seconds: float = 1.0,
        terminate_timeout_seconds: float = 1.0,
    ) -> None:
        self._launcher = launcher or MultiprocessingOfflineCacheProcessLauncher()
        self._join_timeout_seconds = max(0.0, float(join_timeout_seconds))
        self._terminate_timeout_seconds = max(0.0, float(terminate_timeout_seconds))

    def start(
        self,
        *,
        task_id: str,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> "OfflineCacheAttemptProcess":
        launched = self._launcher.launch(
            task_id=task_id,
            attempt_id=attempt_id,
            payload=dict(payload),
        )
        return OfflineCacheAttemptProcess(
            launched=launched,
            join_timeout_seconds=self._join_timeout_seconds,
            terminate_timeout_seconds=self._terminate_timeout_seconds,
        )


class OfflineCacheAttemptProcess:
    def __init__(
        self,
        *,
        launched: LaunchedProcess,
        join_timeout_seconds: float,
        terminate_timeout_seconds: float,
    ) -> None:
        self.process = launched.process
        self.channel = launched.channel
        self._join_timeout_seconds = join_timeout_seconds
        self._terminate_timeout_seconds = terminate_timeout_seconds
        self._closed = False

    def wait_ready(self, *, timeout_seconds: float) -> dict[str, Any]:
        message = self._wait_for(
            {ProcessMessageType.READY, ProcessMessageType.FAILED},
            timeout_seconds=timeout_seconds,
        )
        if message is None:
            self.force_cleanup()
            raise OfflineCacheProcessError("等待离线缓存子进程 READY 超时")
        if message.message_type is ProcessMessageType.FAILED:
            result = self._read_result(message)
            self._join_after_terminal_message()
            raise OfflineCacheProcessError(result.get("message") or "离线缓存子进程启动失败", result=result)
        return dict(message.payload)

    def wait_result(
        self,
        *,
        timeout_seconds: float,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        message = self._wait_for(
            {ProcessMessageType.RESULT, ProcessMessageType.FAILED},
            timeout_seconds=timeout_seconds,
            on_progress=on_progress,
        )
        if message is None:
            self.force_cleanup()
            raise OfflineCacheProcessError("等待离线缓存子进程 RESULT 超时")
        result = self._read_result(message)
        self._join_after_terminal_message()
        if message.message_type is ProcessMessageType.FAILED:
            raise OfflineCacheProcessError(result.get("message") or "离线缓存子进程失败", result=result)
        return result

    def cancel(self) -> None:
        self.force_cleanup()

    def force_cleanup(self) -> None:
        if self._closed:
            return
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(self._terminate_timeout_seconds)
        if self.process.is_alive():
            kill = getattr(self.process, "kill", None)
            if callable(kill):
                kill()
                self.process.join(self._terminate_timeout_seconds)
        self._close_channel()

    def _wait_for(
        self,
        accepted_types: set[ProcessMessageType],
        *,
        timeout_seconds: float,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ProcessMessage | None:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            message = self.channel.receive(timeout=max(0.0, deadline - time.monotonic()))
            if message is None:
                return None
            if message.message_type is ProcessMessageType.PROGRESS:
                event = message.payload.get("event")
                if isinstance(event, Mapping) and on_progress is not None:
                    on_progress(dict(event))
                continue
            if message.message_type in accepted_types:
                return message
            raise OfflineCacheProcessError(
                f"离线缓存子进程返回了非预期消息：{message.message_type.value}"
            )

    @staticmethod
    def _read_result(message: ProcessMessage) -> dict[str, Any]:
        result = message.payload.get("offline_cache_result")
        if not isinstance(result, Mapping):
            raise OfflineCacheProcessError("离线缓存子进程结果格式无效")
        return dict(result)

    def _join_after_terminal_message(self) -> None:
        self.process.join(self._join_timeout_seconds)
        if self.process.is_alive():
            self.force_cleanup()
        else:
            self._close_channel()

    def _close_channel(self) -> None:
        close = getattr(self.channel, "close", None)
        if callable(close):
            close()
        self._closed = True


__all__ = [
    "OfflineCacheAttemptProcess",
    "OfflineCacheProcessControlService",
    "OfflineCacheProcessError",
]
