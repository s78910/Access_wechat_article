from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sqlite_connection(
    database_path: str | Path,
    *,
    write: bool = True,
) -> Iterator[sqlite3.Connection]:
    """创建 SQLite 连接，并在每个连接上显式开启外键。"""
    path = Path(database_path).resolve()
    if write:
        connection = sqlite3.connect(path, timeout=5)
    else:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()
