from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from src.domain.enums import ErrorCode
from src.domain.errors import DomainError
from src.storage.sqlite.connection import sqlite_connection


REQUIRED_TABLES = (
    "awa_fetch_history",
    "awa_public_accounts",
    "awa_public_articles",
)


class DatabaseInitializationError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.DB_INIT_FAILED, message)


class DatabaseValidationError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.DB_UNAVAILABLE, message)


def read_required_tables(database_path: str | Path) -> tuple[str, ...]:
    """读取当前库中属于 v2.1 契约的必要表。"""
    with sqlite_connection(database_path, write=False) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name IN (?, ?, ?)
            ORDER BY name
            """,
            REQUIRED_TABLES,
        ).fetchall()
    return tuple(str(row["name"]) for row in rows)


def validate_database(database_path: str | Path) -> Path:
    """验证正式库可打开、完整且包含 v2.1 必要表。"""
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseValidationError(f"数据库文件不存在：{path}")
    try:
        with sqlite_connection(path, write=False) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise DatabaseValidationError(f"数据库完整性检查失败：{integrity}")
        existing_tables = read_required_tables(path)
    except DatabaseValidationError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseValidationError(f"数据库无法打开：{path}；{exc}") from exc

    missing = sorted(set(REQUIRED_TABLES) - set(existing_tables))
    if missing:
        raise DatabaseValidationError(f"数据库缺少必要表：{', '.join(missing)}")
    return path


class DatabaseInitializer:
    """只执行现有 SQL，并通过临时库原子生成正式数据库。"""

    def initialize(self, database_path: str | Path, schema_sql: str) -> Path:
        target = Path(database_path).resolve()
        if target.exists():
            return validate_database(target)
        if not schema_sql.strip():
            raise DatabaseInitializationError("建表 SQL 不能为空")

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(str(target) + ".tmp")
        if temporary.exists():
            temporary.unlink()

        try:
            with sqlite_connection(temporary) as connection:
                connection.executescript(schema_sql)
            validate_database(temporary)
            os.replace(temporary, target)
            return validate_database(target)
        except Exception as exc:
            if temporary.exists():
                temporary.unlink()
            if isinstance(exc, DatabaseInitializationError):
                raise
            raise DatabaseInitializationError(f"数据库初始化失败：{exc}") from exc
