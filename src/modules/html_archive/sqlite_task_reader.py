from __future__ import annotations

import sqlite3
from pathlib import Path

from src.modules.html_archive.models import ArticleHtmlArchiveTask
from src.modules.html_archive.url_guard import normalize_plain_wechat_short_link


def load_saved_article_html_archive_tasks(
    db_path: str | Path,
    *,
    storage_root: str | Path,
    limit: int = 1,
) -> list[ArticleHtmlArchiveTask]:
    """从 SQLite 中读取已保存文章短链接，默认只取 1 条用于小步测试。"""
    safe_limit = max(1, int(limit or 1))
    fetch_limit = max(safe_limit * 10, 50)
    rows = _load_candidate_rows(Path(db_path), fetch_limit)
    tasks: list[ArticleHtmlArchiveTask] = []
    for row in rows:
        short_link = normalize_plain_wechat_short_link(row["article_link"])
        if not short_link:
            continue
        tasks.append(
            ArticleHtmlArchiveTask(
                article_id=int(row["id"]),
                short_link=short_link,
                account_name=str(row["account_name"] or ""),
                published_article_time=str(row["published_article_time"] or ""),
                article_title=str(row["article_title"] or ""),
                storage_root=Path(storage_root),
            )
        )
        if len(tasks) >= safe_limit:
            break
    return tasks


def _load_candidate_rows(db_path: Path, limit: int) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                """
                SELECT
                    article.id,
                    account.account_name,
                    article.article_title,
                    article.published_article_time,
                    article.article_link,
                    article.collect_time
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                WHERE article.collect_status = 'saved'
                  AND trim(coalesce(article.article_link, '')) <> ''
                ORDER BY article.collect_time DESC, article.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        )
    finally:
        conn.close()


__all__ = ["load_saved_article_html_archive_tasks"]
