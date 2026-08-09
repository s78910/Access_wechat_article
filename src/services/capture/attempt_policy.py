from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import uuid4


class AttemptBudgetExhausted(RuntimeError):
    """全局预算或当前目标重试预算已经耗尽。"""


@dataclass(frozen=True, slots=True)
class AttemptTicket:
    attempt_id: str
    target_fingerprint: str
    global_attempt_number: int
    target_attempt_number: int
    started_at: datetime


class AttemptPolicy:
    """ArticleCaptureService 唯一的真实尝试计数入口。"""

    def __init__(
        self,
        *,
        max_attempts: int,
        article_retry_count: int,
        attempt_id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts 必须大于 0")
        if article_retry_count < 0:
            raise ValueError("article_retry_count 不能小于 0")
        self.max_attempts = int(max_attempts)
        self.max_target_attempts = 1 + int(article_retry_count)
        self._attempt_id_factory = attempt_id_factory or (lambda: uuid4().hex)
        self._now = now
        self._total_attempts = 0
        self._target_attempts: dict[str, int] = {}
        self._issued_ids: set[str] = set()

    @property
    def total_attempts(self) -> int:
        return self._total_attempts

    @property
    def global_exhausted(self) -> bool:
        return self._total_attempts >= self.max_attempts

    def attempts_for(self, target_fingerprint: str) -> int:
        return self._target_attempts.get(target_fingerprint, 0)

    def can_attempt(self, target_fingerprint: str) -> bool:
        fingerprint = str(target_fingerprint or "").strip()
        if not fingerprint:
            return False
        return (
            not self.global_exhausted
            and self.attempts_for(fingerprint) < self.max_target_attempts
        )

    def begin(self, target_fingerprint: str) -> AttemptTicket:
        fingerprint = str(target_fingerprint or "").strip()
        if not self.can_attempt(fingerprint):
            if self.global_exhausted:
                raise AttemptBudgetExhausted("已达到全局最大尝试次数")
            raise AttemptBudgetExhausted("当前文章的首次尝试和额外重试次数已耗尽")

        attempt_id = str(self._attempt_id_factory() or "").strip()
        if not attempt_id or attempt_id in self._issued_ids:
            raise RuntimeError("attempt_id 生成器返回了空值或重复值")
        self._issued_ids.add(attempt_id)
        self._total_attempts += 1
        target_count = self.attempts_for(fingerprint) + 1
        self._target_attempts[fingerprint] = target_count
        return AttemptTicket(
            attempt_id=attempt_id,
            target_fingerprint=fingerprint,
            global_attempt_number=self._total_attempts,
            target_attempt_number=target_count,
            started_at=self._now(),
        )
