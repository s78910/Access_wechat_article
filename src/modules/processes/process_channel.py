from __future__ import annotations

import time
from typing import Any, Mapping

from src.domain.enums import ProcessMessageType
from src.domain.models import ProcessMessage


class ProcessChannelError(RuntimeError):
    """进程通道收到非法消息或底层连接异常。"""


class ProcessChannel:
    """绑定一次 task/attempt 身份的类型化双向通信通道。"""

    def __init__(self, connection: Any, *, task_id: str, attempt_id: str) -> None:
        if not task_id.strip() or not attempt_id.strip():
            raise ValueError("task_id 和 attempt_id 不能为空")
        self._connection = connection
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.ignored_message_count = 0

    def send(
        self,
        message_type: ProcessMessageType,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.send_message(
            ProcessMessage(
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                message_type=message_type,
                payload=dict(payload or {}),
            )
        )

    def send_message(self, message: ProcessMessage) -> None:
        if message.task_id != self.task_id or message.attempt_id != self.attempt_id:
            raise ProcessChannelError("不能通过本次通道发送其他 task_id 或 attempt_id 的消息")
        try:
            self._connection.send(message.to_dict())
        except (BrokenPipeError, EOFError, OSError) as exc:
            raise ProcessChannelError(f"进程消息发送失败：{exc}") from exc

    def receive(self, *, timeout: float | None = None) -> ProcessMessage | None:
        """接收下一条当前尝试消息；迟到的其他尝试消息直接忽略。"""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout 不能小于 0")
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                if remaining is None:
                    raw = self._connection.recv()
                else:
                    if not self._connection.poll(remaining):
                        return None
                    raw = self._connection.recv()
            except (EOFError, OSError) as exc:
                raise ProcessChannelError(f"进程消息接收失败：{exc}") from exc

            message = self._decode(raw)
            if message.task_id == self.task_id and message.attempt_id == self.attempt_id:
                return message

            self.ignored_message_count += 1
            if deadline is not None and time.monotonic() >= deadline:
                return None

    def close(self) -> None:
        """关闭当前进程持有的 Pipe 端点。"""
        try:
            self._connection.close()
        except OSError as exc:
            raise ProcessChannelError(f"进程通道关闭失败：{exc}") from exc

    @staticmethod
    def _decode(raw: Any) -> ProcessMessage:
        if isinstance(raw, ProcessMessage):
            return raw
        if not isinstance(raw, Mapping):
            raise ProcessChannelError("进程消息必须是可映射数据")
        try:
            return ProcessMessage.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessChannelError(f"进程消息格式无效：{exc}") from exc
