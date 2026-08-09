from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.domain.enums import TaskStage, TaskStatus


@dataclass(frozen=True, slots=True)
class TaskEvent:
    task_id: str
    stage: TaskStage
    status: TaskStatus
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
