from __future__ import annotations

from contextlib import contextmanager
import multiprocessing
from typing import Any, Iterator


class DatabaseWriteCoordinator:
    """在主进程和评论子进程之间串行化最终文件与 SQLite 提交。"""

    def __init__(self, *, lock: Any | None = None, context: Any | None = None) -> None:
        process_context = context or multiprocessing.get_context("spawn")
        self._lock = lock or process_context.RLock()

    @contextmanager
    def hold(self) -> Iterator[None]:
        """持有完整提交锁；必须覆盖文件替换、事务和补偿清理。"""
        with self._lock:
            yield


__all__ = ["DatabaseWriteCoordinator"]
