from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config import LOG_DIR


class SessionFileLogger:
    """Write all logs from one app startup into one data/logs/yyyy-mm-dd/*.log file."""

    def __init__(self, root_dir: str | Path = LOG_DIR, started_at: str | datetime | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.started_at = self._parse_datetime(started_at) if started_at else datetime.now()
        self.path = self._build_log_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: dict[str, Any]) -> Path:
        created_at = self._parse_datetime(str(event.get("createdAt", "")))
        line = self._format_line(event, created_at)
        payload = json.dumps(event, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n{payload}\n")
        return self.path

    def _build_log_path(self) -> Path:
        date_text = self.started_at.strftime("%Y-%m-%d")
        timestamp = self.started_at.strftime("%Y-%m-%d %H%M%S%f")
        return self.root_dir / date_text / f"{timestamp}.log"

    def _format_line(self, event: dict[str, Any], created_at: datetime) -> str:
        level = str(event.get("level", "INFO"))
        source = str(event.get("source", "app"))
        message = str(event.get("message", ""))
        return f"[{created_at.isoformat(timespec='seconds')}] [{level}] [{source}] {message}"

    def _parse_datetime(self, value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            return value
        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()


# Backward-compatible name for older imports.
DailyFileLogger = SessionFileLogger
