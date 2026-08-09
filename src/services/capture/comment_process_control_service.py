from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Protocol

from src.domain.enums import ProcessMessageType
from src.domain.models import ProcessMessage
from src.modules.processes.comment_process_launcher import MultiprocessingCommentProcessLauncher
from src.modules.processes.process_launcher import LaunchedProcess


class CommentProcessLauncher(Protocol):
    def launch(
        self,
        *,
        task_id: str,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> LaunchedProcess: ...


class CommentProcessError(RuntimeError):
    """评论采集子进程未按协议完成。"""

    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result


class CommentProcessControlService:
    """启动并回收一次性评论采集子进程。"""

    def __init__(
        self,
        *,
        launcher: CommentProcessLauncher | None = None,
        cancel_grace_seconds: float = 1.0,
        terminate_grace_seconds: float = 1.0,
    ) -> None:
        self._launcher = launcher or MultiprocessingCommentProcessLauncher()
        self._cancel_grace_seconds = max(0.0, float(cancel_grace_seconds))
        self._terminate_grace_seconds = max(0.0, float(terminate_grace_seconds))

    def start(
        self,
        *,
        task_id: str,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> CommentAttemptProcess:
        launched = self._launcher.launch(
            task_id=task_id,
            attempt_id=attempt_id,
            payload=dict(payload),
        )
        return CommentAttemptProcess(
            launched=launched,
            cancel_grace_seconds=self._cancel_grace_seconds,
            terminate_grace_seconds=self._terminate_grace_seconds,
        )


class CommentAttemptProcess:
    """父进程持有的评论子进程句柄。"""

    def __init__(
        self,
        *,
        launched: LaunchedProcess,
        cancel_grace_seconds: float,
        terminate_grace_seconds: float,
    ) -> None:
        self.process = launched.process
        self.channel = launched.channel
        self._cancel_grace_seconds = cancel_grace_seconds
        self._terminate_grace_seconds = terminate_grace_seconds
        self._closed = False

    def wait_ready(self, *, timeout_seconds: float) -> dict[str, Any]:
        message = self._wait_for(
            {ProcessMessageType.READY, ProcessMessageType.FAILED},
            timeout_seconds=timeout_seconds,
            on_progress=None,
        )
        if message is None:
            self.force_cleanup()
            raise CommentProcessError("等待评论采集子进程 READY 超时")
        if message.message_type is ProcessMessageType.FAILED:
            result = self._read_comment_result(message)
            self._join_after_terminal_message()
            raise CommentProcessError(result.get("message") or "评论采集子进程启动失败", result=result)
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
            raise CommentProcessError("等待评论采集子进程 RESULT 超时")
        result = self._read_comment_result(message)
        self._join_after_terminal_message()
        if message.message_type is ProcessMessageType.FAILED:
            raise CommentProcessError(result.get("message") or "评论采集子进程失败", result=result)
        return result

    def cancel(self) -> None:
        self.force_cleanup()

    def force_cleanup(self) -> None:
        if self._closed:
            return
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
        on_progress: Callable[[dict[str, Any]], None] | None,
    ) -> ProcessMessage | None:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            message = self.channel.receive(timeout=remaining)
            if message is None:
                return None
            if message.message_type is ProcessMessageType.PROGRESS:
                event = message.payload.get("event", {})
                if isinstance(event, Mapping) and on_progress is not None:
                    on_progress(dict(event))
                if time.monotonic() >= deadline:
                    return None
                continue
            if message.message_type in accepted_types:
                return message
            raise CommentProcessError(f"评论采集子进程返回了非预期消息：{message.message_type.value}")

    @staticmethod
    def _read_comment_result(message: ProcessMessage) -> dict[str, Any]:
        raw_result = message.payload.get("comment_result", {})
        if not isinstance(raw_result, Mapping):
            raise CommentProcessError("评论采集结果格式无效")
        return dict(raw_result)

    def _join_after_terminal_message(self) -> None:
        self.process.join(self._cancel_grace_seconds)
        if self.process.is_alive():
            self.force_cleanup()
            return
        self._close_channel()

    def _close_channel(self) -> None:
        close = getattr(self.channel, "close", None)
        if callable(close):
            close()
        self._closed = True


__all__ = ["CommentProcessControlService", "CommentProcessError"]
