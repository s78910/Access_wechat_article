from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: int
    account_name: str
    created_time: str
    updated_time: str


class AccountRepository:
    """只按公众号名称保存和查询公众号索引。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert(self, account_name: str, *, now: str) -> int:
        normalized_name = account_name.strip()
        if not normalized_name:
            raise ValueError("account_name 不能为空")
        self.connection.execute(
            """
            INSERT INTO awa_public_accounts(account_name, created_time, updated_time)
            VALUES (?, ?, ?)
            ON CONFLICT(account_name) DO UPDATE SET
                updated_time = excluded.updated_time
            """,
            (normalized_name, now, now),
        )
        row = self.connection.execute(
            "SELECT id FROM awa_public_accounts WHERE account_name = ?",
            (normalized_name,),
        ).fetchone()
        return int(row["id"])

    def get_by_name(self, account_name: str) -> AccountRecord | None:
        row = self.connection.execute(
            "SELECT * FROM awa_public_accounts WHERE account_name = ?",
            (account_name.strip(),),
        ).fetchone()
        return _to_record(row)

    def get_by_id(self, account_id: int) -> AccountRecord | None:
        row = self.connection.execute(
            "SELECT * FROM awa_public_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        return _to_record(row)


def _to_record(row: sqlite3.Row | None) -> AccountRecord | None:
    if row is None:
        return None
    return AccountRecord(
        id=int(row["id"]),
        account_name=str(row["account_name"]),
        created_time=str(row["created_time"]),
        updated_time=str(row["updated_time"]),
    )
