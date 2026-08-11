from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from src.domain.models import ResourceManifest


@dataclass(frozen=True, slots=True)
class ArticleIndexWrite:
    account_id: int
    article_title: str
    published_article_time: str
    article_link: str
    archive_dir: str
    resource_manifest: ResourceManifest
    collected_time: str


@dataclass(frozen=True, slots=True)
class ArticleRecord:
    id: int
    account_id: int
    article_title: str
    published_article_time: str
    article_link: str
    archive_dir: str
    resource_types_json: str
    first_collected_time: str
    last_collected_time: str
    created_time: str
    updated_time: str


@dataclass(frozen=True, slots=True)
class OfflineCacheArticleRecord:
    id: int
    account_id: int
    account_name: str
    article_title: str
    published_article_time: str
    article_link: str
    archive_dir: str
    resource_types_json: str


class ArticleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert(self, article: ArticleIndexWrite) -> int:
        title = article.article_title.strip()
        link = article.article_link.strip()
        if not title:
            raise ValueError("article_title 不能为空")
        if not link:
            raise ValueError("article_link 不能为空")

        resource_types_json = json.dumps(
            article.resource_manifest.to_json_values(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.connection.execute(
            """
            INSERT INTO awa_public_articles(
                account_id,
                article_title,
                published_article_time,
                article_link,
                archive_dir,
                resource_types_json,
                first_collected_time,
                last_collected_time,
                created_time,
                updated_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, article_link) DO UPDATE SET
                article_title = excluded.article_title,
                published_article_time = excluded.published_article_time,
                archive_dir = CASE
                    WHEN trim(awa_public_articles.archive_dir) <> ''
                    THEN awa_public_articles.archive_dir
                    ELSE excluded.archive_dir
                END,
                resource_types_json = excluded.resource_types_json,
                last_collected_time = excluded.last_collected_time,
                updated_time = excluded.updated_time
            """,
            (
                article.account_id,
                title,
                article.published_article_time.strip(),
                link,
                article.archive_dir.strip(),
                resource_types_json,
                article.collected_time,
                article.collected_time,
                article.collected_time,
                article.collected_time,
            ),
        )
        row = self.connection.execute(
            """
            SELECT id FROM awa_public_articles
            WHERE account_id = ? AND article_link = ?
            """,
            (article.account_id, link),
        ).fetchone()
        return int(row["id"])

    def get_by_id(self, article_id: int) -> ArticleRecord | None:
        row = self.connection.execute(
            "SELECT * FROM awa_public_articles WHERE id = ?",
            (article_id,),
        ).fetchone()
        return _to_record(row)

    def update_resource_manifest(
        self,
        article_id: int,
        resource_manifest: ResourceManifest,
        *,
        collected_time: str,
    ) -> None:
        resource_types_json = json.dumps(
            resource_manifest.to_json_values(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cursor = self.connection.execute(
            """
            UPDATE awa_public_articles
            SET resource_types_json = ?,
                last_collected_time = ?,
                updated_time = ?
            WHERE id = ?
            """,
            (resource_types_json, collected_time, collected_time, article_id),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"文章索引不存在：{article_id}")

    def get_by_account_and_link(self, account_id: int, article_link: str) -> ArticleRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM awa_public_articles
            WHERE account_id = ? AND article_link = ?
            """,
            (account_id, article_link.strip()),
        ).fetchone()
        return _to_record(row)

    def exists_by_account_and_title(self, account_id: int, article_title: str) -> bool:
        """按公众号 ID 和完整标题精确判断文章索引是否存在。"""
        row = self.connection.execute(
            """
            SELECT 1
            FROM awa_public_articles
            WHERE account_id = ? AND article_title = ?
            LIMIT 1
            """,
            (account_id, article_title),
        ).fetchone()
        return row is not None

    def list_offline_cache_records_by_ids(
        self,
        article_ids,
    ) -> tuple[OfflineCacheArticleRecord, ...]:
        """按用户勾选顺序读取离线缓存目标，并去除重复或无效 ID。"""
        ordered_ids: list[int] = []
        seen: set[int] = set()
        for value in article_ids:
            try:
                article_id = int(value)
            except (TypeError, ValueError):
                continue
            if article_id <= 0 or article_id in seen:
                continue
            seen.add(article_id)
            ordered_ids.append(article_id)
        if not ordered_ids:
            return ()

        placeholders = ",".join("?" for _ in ordered_ids)
        rows = self.connection.execute(
            f"""
            SELECT article.*, account.account_name
            FROM awa_public_articles AS article
            JOIN awa_public_accounts AS account ON account.id = article.account_id
            WHERE article.id IN ({placeholders})
            """,
            tuple(ordered_ids),
        ).fetchall()
        records = {int(row["id"]): _to_offline_cache_record(row) for row in rows}
        return tuple(records[article_id] for article_id in ordered_ids if article_id in records)

    def list_offline_cache_records_by_account(
        self,
        account_id: int,
    ) -> tuple[OfflineCacheArticleRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT article.*, account.account_name
            FROM awa_public_articles AS article
            JOIN awa_public_accounts AS account ON account.id = article.account_id
            WHERE article.account_id = ?
            ORDER BY article.published_article_time DESC, article.id DESC
            """,
            (int(account_id),),
        ).fetchall()
        return tuple(_to_offline_cache_record(row) for row in rows)


def _to_record(row: sqlite3.Row | None) -> ArticleRecord | None:
    if row is None:
        return None
    return ArticleRecord(
        id=int(row["id"]),
        account_id=int(row["account_id"]),
        article_title=str(row["article_title"]),
        published_article_time=str(row["published_article_time"]),
        article_link=str(row["article_link"]),
        archive_dir=str(row["archive_dir"]),
        resource_types_json=str(row["resource_types_json"]),
        first_collected_time=str(row["first_collected_time"]),
        last_collected_time=str(row["last_collected_time"]),
        created_time=str(row["created_time"]),
        updated_time=str(row["updated_time"]),
    )


def _to_offline_cache_record(row: sqlite3.Row) -> OfflineCacheArticleRecord:
    return OfflineCacheArticleRecord(
        id=int(row["id"]),
        account_id=int(row["account_id"]),
        account_name=str(row["account_name"]),
        article_title=str(row["article_title"]),
        published_article_time=str(row["published_article_time"]),
        article_link=str(row["article_link"]),
        archive_dir=str(row["archive_dir"]),
        resource_types_json=str(row["resource_types_json"]),
    )
