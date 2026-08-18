from __future__ import annotations

from pathlib import Path
from typing import Any

from src.storage.repositories.fetch_history_repository import FetchHistoryRepository
from src.storage.sqlite.connection import sqlite_connection


class HistoryClearService:
    """清空采集历史流水，不触碰数据档案和本地归档文件。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()

    def clear_all(self) -> dict[str, Any]:
        with sqlite_connection(self.database_path) as connection:
            deleted_count = FetchHistoryRepository(connection).delete_all()

        return {
            "ok": True,
            "status": "deleted",
            "deletedCount": deleted_count,
            "dbPath": str(self.database_path),
            "message": f"已清空 {deleted_count} 条采集历史记录。",
        }
