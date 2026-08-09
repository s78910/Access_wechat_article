from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from threading import RLock

from src.domain.models import ArticleTarget
from src.services.runtime.database_write_coordinator import DatabaseWriteCoordinator
from src.storage.repositories.fetch_history_repository import (
    FetchHistoryRepository,
    FetchHistoryWrite,
)
from src.storage.sqlite.connection import sqlite_connection


SENSITIVE_PARAMETER_PATTERN = re.compile(
    r"(?i)([?&](?:key|pass_ticket|appmsg_token|uin|wxtoken|poc_token|exportkey|sessionid)=)[^&\s]+"
)


class AttemptHistoryService:
    """守护任务内 attempt 终态，避免成功/失败路径重复追加历史。"""

    def __init__(
        self,
        *,
        database_path: str | Path,
        write_coordinator: DatabaseWriteCoordinator | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._write_coordinator = write_coordinator or DatabaseWriteCoordinator()
        self._recorded: dict[str, tuple[str, int]] = {}
        self._lock = RLock()

    def is_recorded(self, attempt_id: str) -> bool:
        with self._lock:
            return attempt_id in self._recorded

    def mark_success(self, attempt_id: str, *, history_id: int) -> bool:
        identity = _normalize_attempt_id(attempt_id)
        if history_id <= 0:
            raise ValueError("history_id 必须大于 0")
        with self._lock:
            if identity in self._recorded:
                return False
            self._recorded[identity] = ("success", int(history_id))
            return True

    def record_failure(
        self,
        *,
        attempt_id: str,
        target: ArticleTarget,
        started_at: datetime,
        duration_seconds: float,
        error_stage: str,
        error_message: str,
        target_link: str = "",
        article_id: int | None = None,
        account_id: int | None = None,
    ) -> bool:
        identity = _normalize_attempt_id(attempt_id)
        with self._lock:
            if identity in self._recorded:
                return False
            finished_at = datetime.now()
            history = FetchHistoryWrite.failed(
                target_account_name=target.account_name,
                target_title=target.title,
                task_type="article_capture",
                started_time=_format_time(started_at),
                finished_time=_format_time(finished_at),
                duration_seconds=max(0.0, float(duration_seconds)),
                error_stage=str(error_stage or "unknown"),
                error_message=redact_sensitive_text(error_message),
                target_link=_safe_target_link(target_link),
                article_id=article_id,
                account_id=account_id,
            )
            # 只有连接上下文正常提交后才把 attempt 标记为已记录；数据库失败时
            # 上层仍可发布事件并明确说明历史未落库。
            with self._write_coordinator.hold():
                with sqlite_connection(self._database_path) as connection:
                    history_id = FetchHistoryRepository(connection).append(history)
            self._recorded[identity] = ("failed", history_id)
            return True


def redact_sensitive_text(value: object) -> str:
    return SENSITIVE_PARAMETER_PATTERN.sub(r"\1***", str(value or ""))


def _safe_target_link(value: str) -> str:
    return redact_sensitive_text(value)


def _normalize_attempt_id(value: str) -> str:
    identity = str(value or "").strip()
    if not identity:
        raise ValueError("attempt_id 不能为空")
    return identity


def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")
