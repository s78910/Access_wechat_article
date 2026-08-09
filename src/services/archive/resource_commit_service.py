from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

from src.modules.archive.article_file_store import ArticleFileStore
from src.services.runtime.database_write_coordinator import DatabaseWriteCoordinator
from src.storage.sqlite.connection import sqlite_connection


T = TypeVar("T")


class ResourceCommitService:
    """协调本地资源替换与 SQLite 事务，数据库失败时补偿文件。"""

    def __init__(
        self,
        file_store: ArticleFileStore | None = None,
        *,
        write_coordinator: DatabaseWriteCoordinator | None = None,
    ) -> None:
        self.file_store = file_store or ArticleFileStore()
        self._write_coordinator = write_coordinator or DatabaseWriteCoordinator()

    def commit(
        self,
        *,
        database_path: str | Path,
        stage_root: str | Path,
        target_root: str | Path,
        backup_root: str | Path,
        resource_paths: Iterable[str | Path],
        database_operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        with self._write_coordinator.hold():
            replacement = self.file_store.replace_resources(
                stage_root=stage_root,
                target_root=target_root,
                backup_root=backup_root,
                resource_paths=resource_paths,
            )
            try:
                with sqlite_connection(database_path) as connection:
                    result = database_operation(connection)
            except Exception:
                replacement.rollback()
                raise

            replacement.commit()
            return result
