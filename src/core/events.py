from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RuntimeLog:
    level: str
    message: str
    source: str = "task"
    created_at: str = ""

    def to_dict(self) -> dict:
        created_at = self.created_at or datetime.now().isoformat(timespec="seconds")
        return {
            "level": self.level,
            "message": self.message,
            "source": self.source,
            "createdAt": created_at,
        }
