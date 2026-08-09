from __future__ import annotations

from pathlib import Path

from src.storage.repositories.account_repository import AccountRepository
from src.storage.repositories.article_repository import ArticleRepository
from src.storage.sqlite.connection import sqlite_connection


class CollectedArticleLookupService:
    """通过公众号 ID 和完整标题检查文章是否已进入本地索引。"""

    def is_collected(
        self,
        *,
        database_path: str | Path,
        account_name: str,
        article_title: str,
    ) -> bool:
        with sqlite_connection(database_path, write=False) as connection:
            account = AccountRepository(connection).get_by_name(account_name)
            if account is None:
                return False
            return ArticleRepository(connection).exists_by_account_and_title(
                account.id,
                article_title,
            )


__all__ = ["CollectedArticleLookupService"]
