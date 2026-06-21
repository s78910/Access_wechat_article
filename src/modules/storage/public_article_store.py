from __future__ import annotations

from pathlib import Path

from src.modules.storage.sqlite_store import SQLiteStore


def create_public_article_store(db_path: str | Path) -> SQLiteStore:
    """创建公众号文章索引库访问对象，避免任务 worker 直接依赖 SQLite 具体实现。"""
    return SQLiteStore(Path(db_path))


__all__ = ["SQLiteStore", "create_public_article_store"]
