from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src.core.config import DEFAULT_DB_PATH
from src.modules.detail.account_identity import first_valid_account_name


AWA_SCHEMA_PATH = Path(__file__).with_name("awa_public_schema.sql")


class SQLiteStore:
    """AWA 公共文章索引的本地 SQLite 存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            if AWA_SCHEMA_PATH.exists():
                schema_sql = AWA_SCHEMA_PATH.read_text(encoding="utf-8")
                conn.executescript(schema_sql)

    def save_public_article(self, record: dict) -> int:
        """按 AWA 表结构保存文章索引；成功和失败记录使用不同业务键合并。"""
        account_name = self._normalize_public_account_name(record.get("account_name"))
        article_title = self._normalize_public_article_title(record.get("article_title"))
        record_type = self._normalize_record_type(record.get("record_type"))
        collect_status = self._normalize_public_collect_status(record.get("collect_status"))
        article_link = str(record.get("article_link") or "").strip()
        if collect_status == "saved":
            if not article_link:
                raise ValueError("saved public article requires a non-empty article_link")
            published_article_time = str(record.get("published_article_time") or datetime.now().strftime("%Y-%m-%d %H:%M")).strip()
        else:
            # 失败/超时记录不再写 failed:// 这类占位链接，避免污染最终文章去重键。
            article_link = ""
            published_article_time = str(record.get("published_article_time") or "").strip()

        collect_time = str(record.get("collect_time") or self._now()).strip()
        duration_seconds = max(0.0, float(record.get("duration_seconds") or 0.0))

        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            account_id = self._upsert_public_account(conn, account_name)
            if collect_status == "saved":
                return self._save_saved_public_article(
                    conn,
                    account_id=account_id,
                    article_title=article_title,
                    published_article_time=published_article_time,
                    article_link=article_link,
                    record_type=record_type,
                    collect_time=collect_time,
                    duration_seconds=duration_seconds,
                )
            return self._save_failed_public_article(
                conn,
                account_id=account_id,
                article_title=article_title,
                published_article_time=published_article_time,
                record_type=record_type,
                collect_time=collect_time,
                duration_seconds=duration_seconds,
            )

    def has_saved_public_article_title(self, account_name: str, article_title: str) -> bool:
        """判断同一公众号下是否已有保存成功的同标题文章。"""
        normalized_account = str(account_name or "").strip()
        normalized_title = self._normalize_article_title(article_title)
        if not normalized_account or not normalized_title:
            return False

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT article.article_title
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                WHERE account.account_name = ?
                  AND article.collect_status = 'saved'
                """,
                (normalized_account,),
            ).fetchall()
            return any(self._normalize_article_title(row[0]).lower() == normalized_title.lower() for row in rows)

    def count_public_accounts(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM awa_public_accounts").fetchone()[0])

    def count_public_articles(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM awa_public_articles").fetchone()[0])

    def count_saved_article_details(self) -> int:
        """统计已成功保存文章详情的记录数，用于首页和数据档案统一展示。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM awa_public_articles
                WHERE collect_status = 'saved'
                  AND record_type LIKE '%文章详情%'
                """
            ).fetchone()
            return int(row[0] or 0)

    def count_history_records(
        self,
        *,
        keyword: str = "",
        collect_type: str = "",
        collect_status: str = "",
        collect_date: str = "",
    ) -> int:
        """按采集历史页筛选条件统计文章记录数量。"""
        where_clause, params = self._build_history_filter_clause(
            keyword=keyword,
            collect_type=collect_type,
            collect_status=collect_status,
            collect_date=collect_date,
        )
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                {where_clause}
                """,
                tuple(params),
            ).fetchone()
            return int(row[0] or 0)

    def list_history_records(
        self,
        *,
        limit: int = 15,
        offset: int = 0,
        keyword: str = "",
        collect_type: str = "",
        collect_status: str = "",
        collect_date: str = "",
    ) -> list[dict[str, object]]:
        """读取采集历史页列表数据，保持页面和 SQLite 表结构低耦合。"""
        where_clause, params = self._build_history_filter_clause(
            keyword=keyword,
            collect_type=collect_type,
            collect_status=collect_status,
            collect_date=collect_date,
        )
        safe_limit = max(1, int(limit))
        safe_offset = max(0, int(offset))
        params.extend([safe_limit, safe_offset])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    article.id,
                    article.account_id,
                    account.account_name,
                    article.article_title,
                    article.published_article_time,
                    article.article_link,
                    article.record_type,
                    article.collect_time,
                    article.duration_seconds,
                    article.collect_status
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                {where_clause}
                ORDER BY article.collect_time DESC, article.id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()

        return [self._article_row_to_dict(row) for row in rows]

    def get_history_summary(self) -> dict[str, object]:
        """汇总采集历史页顶部卡片、右侧统计卡片和近日趋势所需数据。"""
        with self._connect() as conn:
            summary_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN collect_status = 'saved' THEN 1 ELSE 0 END) AS saved_count,
                    SUM(CASE WHEN collect_status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    AVG(duration_seconds) AS average_duration,
                    MAX(collect_time) AS latest_collect_time
                FROM awa_public_articles
                """
            ).fetchone()
            trend_rows = conn.execute(
                """
                SELECT substr(collect_time, 1, 10) AS collect_date, COUNT(*) AS record_count
                FROM awa_public_articles
                WHERE trim(collect_time) <> ''
                GROUP BY substr(collect_time, 1, 10)
                ORDER BY collect_date DESC
                LIMIT 7
                """
            ).fetchall()

        return {
            "total_count": int(summary_row[0] or 0),
            "saved_count": int(summary_row[1] or 0),
            "failed_count": int(summary_row[2] or 0),
            "average_duration": float(summary_row[3] or 0.0),
            "latest_collect_time": str(summary_row[4] or ""),
            "trend": [
                {
                    "date": str(row[0] or ""),
                    "count": int(row[1] or 0),
                }
                for row in reversed(trend_rows)
            ],
        }

    def list_history_suggestions(self, *, keyword: str = "", limit: int = 20) -> list[str]:
        """读取采集历史关键词候选，候选来自全库标题和公众号名，不受当前分页影响。"""
        normalized_keyword = str(keyword or "").strip()
        safe_limit = max(1, min(50, int(limit or 20)))
        like_keyword = f"%{normalized_keyword}%"

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT value
                FROM (
                    SELECT
                        account.account_name AS value,
                        MAX(article.collect_time) AS latest_collect_time,
                        0 AS source_order
                    FROM awa_public_articles AS article
                    JOIN awa_public_accounts AS account
                        ON account.id = article.account_id
                    WHERE trim(account.account_name) <> ''
                      AND (? = '' OR account.account_name LIKE ?)
                    GROUP BY account.account_name

                    UNION ALL

                    SELECT
                        article.article_title AS value,
                        MAX(article.collect_time) AS latest_collect_time,
                        1 AS source_order
                    FROM awa_public_articles AS article
                    WHERE trim(article.article_title) <> ''
                      AND (? = '' OR article.article_title LIKE ?)
                    GROUP BY article.article_title
                )
                ORDER BY source_order ASC, latest_collect_time DESC, value ASC
                LIMIT ?
                """,
                (
                    normalized_keyword,
                    like_keyword,
                    normalized_keyword,
                    like_keyword,
                    safe_limit,
                ),
            ).fetchall()

        suggestions: list[str] = []
        seen: set[str] = set()
        for row in rows:
            value = str(row[0] or "").strip()
            if value and value not in seen:
                seen.add(value)
                suggestions.append(value)
        return suggestions

    def list_public_accounts(self) -> list[dict[str, object]]:
        """按公众号汇总本地文章索引，供数据档案页展示真实数据库内容。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    account.id,
                    account.account_name,
                    account.created_time,
                    account.updated_time,
                    COUNT(article.id) AS article_count,
                    SUM(CASE WHEN article.collect_status = 'saved' THEN 1 ELSE 0 END) AS saved_count,
                    SUM(CASE WHEN article.collect_status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    MAX(article.collect_time) AS latest_collect_time
                FROM awa_public_accounts AS account
                LEFT JOIN awa_public_articles AS article
                    ON article.account_id = account.id
                GROUP BY
                    account.id,
                    account.account_name,
                    account.created_time,
                    account.updated_time
                ORDER BY
                    COALESCE(MAX(article.collect_time), account.updated_time) DESC,
                    account.id DESC
                """
            ).fetchall()

        return [
            {
                "id": int(row[0]),
                "account_name": str(row[1] or ""),
                "created_time": str(row[2] or ""),
                "updated_time": str(row[3] or ""),
                "article_count": int(row[4] or 0),
                "saved_count": int(row[5] or 0),
                "failed_count": int(row[6] or 0),
                "latest_collect_time": str(row[7] or row[3] or ""),
            }
            for row in rows
        ]

    def count_public_articles_by_account(self, account_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM awa_public_articles WHERE account_id = ?",
                (int(account_id),),
            ).fetchone()
            return int(row[0] or 0)

    def get_public_articles_by_ids(self, article_ids: list[int]) -> list[dict[str, object]]:
        """按文章主键读取文章索引，供删除本地归档前定位目录。"""
        safe_ids = _unique_positive_ids(article_ids)
        if not safe_ids:
            return []

        placeholders = ",".join("?" for _ in safe_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    article.id,
                    article.account_id,
                    account.account_name,
                    article.article_title,
                    article.published_article_time,
                    article.article_link,
                    article.record_type,
                    article.collect_time,
                    article.duration_seconds,
                    article.collect_status
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                WHERE article.id IN ({placeholders})
                ORDER BY article.id ASC
                """,
                tuple(safe_ids),
            ).fetchall()

        return [self._article_row_to_dict(row) for row in rows]

    def list_public_article_ids_by_account(self, account_id: int) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM awa_public_articles
                WHERE account_id = ?
                ORDER BY id ASC
                """,
                (int(account_id),),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def delete_public_articles_by_ids(self, article_ids: list[int]) -> int:
        """删除指定文章索引；本地目录删除由归档服务负责。"""
        safe_ids = _unique_positive_ids(article_ids)
        if not safe_ids:
            return 0

        placeholders = ",".join("?" for _ in safe_ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM awa_public_articles WHERE id IN ({placeholders})",
                tuple(safe_ids),
            )
            return int(cursor.rowcount or 0)

    def delete_public_account(self, account_id: int) -> int:
        """删除无文章引用的公众号行；调用前应先删除该公众号下所有文章。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM awa_public_accounts WHERE id = ?",
                (int(account_id),),
            )
            return int(cursor.rowcount or 0)

    def merge_public_account(self, source_account_name: str, target_account_name: str) -> dict[str, int]:
        """把误识别公众号的文章迁移到真实公众号，成功短链冲突时保留目标账号记录。"""
        source_name = str(source_account_name or "").strip()
        target_name = self._normalize_public_account_name(target_account_name)
        if not source_name or source_name == target_name:
            return {"moved": 0, "removed_duplicates": 0}

        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            source_row = conn.execute(
                "SELECT id FROM awa_public_accounts WHERE account_name = ?",
                (source_name,),
            ).fetchone()
            if not source_row:
                return {"moved": 0, "removed_duplicates": 0}

            source_id = int(source_row[0])
            target_id = self._upsert_public_account(conn, target_name)
            duplicate_rows = conn.execute(
                """
                SELECT source.id
                FROM awa_public_articles AS source
                JOIN awa_public_articles AS target
                    ON target.account_id = ?
                   AND target.collect_status = 'saved'
                   AND target.article_link = source.article_link
                WHERE source.account_id = ?
                  AND source.collect_status = 'saved'
                  AND source.article_link <> ''
                """,
                (target_id, source_id),
            ).fetchall()
            duplicate_ids = [int(row[0]) for row in duplicate_rows]
            removed_duplicates = 0
            if duplicate_ids:
                placeholders = ",".join("?" for _ in duplicate_ids)
                cursor = conn.execute(
                    f"DELETE FROM awa_public_articles WHERE id IN ({placeholders})",
                    tuple(duplicate_ids),
                )
                removed_duplicates = int(cursor.rowcount or 0)

            cursor = conn.execute(
                """
                UPDATE awa_public_articles
                SET account_id = ?
                WHERE account_id = ?
                """,
                (target_id, source_id),
            )
            moved = int(cursor.rowcount or 0)
            conn.execute("DELETE FROM awa_public_accounts WHERE id = ?", (source_id,))
            return {"moved": moved, "removed_duplicates": removed_duplicates}

    def list_public_articles_by_account(
        self,
        account_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """读取某个公众号下的文章索引，供数据档案页右侧记录详情展示。"""
        params: list[object] = [int(account_id)]
        page_clause = ""
        if limit is not None:
            safe_limit = max(1, int(limit))
            safe_offset = max(0, int(offset))
            page_clause = " LIMIT ? OFFSET ?"
            params.extend([safe_limit, safe_offset])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    article.id,
                    article.account_id,
                    account.account_name,
                    article.article_title,
                    article.published_article_time,
                    article.article_link,
                    article.record_type,
                    article.collect_time,
                    article.duration_seconds,
                    article.collect_status
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                WHERE article.account_id = ?
                ORDER BY
                    CASE WHEN trim(article.published_article_time) = '' THEN 1 ELSE 0 END ASC,
                    article.published_article_time DESC,
                    article.collect_time DESC,
                    article.id DESC
                {page_clause}
                """,
                tuple(params),
            ).fetchall()

        return [self._article_row_to_dict(row) for row in rows]

    def list_public_articles_for_export(self, account_id: int) -> list[dict[str, object]]:
        """按发布时间倒序读取公众号全部文章，供 Excel 导出使用。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    article.id,
                    article.account_id,
                    account.account_name,
                    article.article_title,
                    article.published_article_time,
                    article.article_link,
                    article.record_type,
                    article.collect_time,
                    article.duration_seconds,
                    article.collect_status
                FROM awa_public_articles AS article
                JOIN awa_public_accounts AS account
                    ON account.id = article.account_id
                WHERE article.account_id = ?
                ORDER BY
                    CASE WHEN trim(article.published_article_time) = '' THEN 1 ELSE 0 END ASC,
                    article.published_article_time DESC,
                    article.collect_time DESC,
                    article.id DESC
                """,
                (int(account_id),),
            ).fetchall()

        return [self._article_row_to_dict(row) for row in rows]

    def _build_history_filter_clause(
        self,
        *,
        keyword: str = "",
        collect_type: str = "",
        collect_status: str = "",
        collect_date: str = "",
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []

        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword:
            clauses.append(
                """
                (
                    article.article_title LIKE ?
                    OR account.account_name LIKE ?
                    OR article.record_type LIKE ?
                )
                """
            )
            like_keyword = f"%{normalized_keyword}%"
            params.extend([like_keyword, like_keyword, like_keyword])

        normalized_type = str(collect_type or "").strip()
        if normalized_type:
            clauses.append("article.record_type LIKE ?")
            params.append(f"%{normalized_type}%")

        normalized_status = str(collect_status or "").strip().lower()
        if normalized_status:
            clauses.append("article.collect_status = ?")
            params.append(self._normalize_public_collect_status(normalized_status))

        normalized_date = str(collect_date or "").strip()
        if normalized_date:
            clauses.append("article.collect_time LIKE ?")
            params.append(f"{normalized_date}%")

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses), params

    @staticmethod
    def _article_row_to_dict(row) -> dict[str, object]:
        return {
            "id": int(row[0]),
            "account_id": int(row[1]),
            "account_name": str(row[2] or ""),
            "article_title": str(row[3] or ""),
            "published_article_time": str(row[4] or ""),
            "article_link": str(row[5] or ""),
            "record_type": str(row[6] or ""),
            "collect_time": str(row[7] or ""),
            "duration_seconds": float(row[8] or 0),
            "collect_status": str(row[9] or ""),
        }

    def _save_saved_public_article(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: int,
        article_title: str,
        published_article_time: str,
        article_link: str,
        record_type: str,
        collect_time: str,
        duration_seconds: float,
    ) -> int:
        row = conn.execute(
            """
            SELECT id
            FROM awa_public_articles
            WHERE account_id = ? AND article_link = ? AND collect_status = 'saved'
            """,
            (account_id, article_link),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT id
                FROM awa_public_articles
                WHERE account_id = ?
                  AND article_title = ?
                  AND record_type = ?
                  AND collect_status = 'failed'
                """,
                (account_id, article_title, record_type),
            ).fetchone()

        if row is not None:
            article_id = int(row[0])
            conn.execute(
                """
                UPDATE awa_public_articles
                SET article_title = ?,
                    published_article_time = ?,
                    article_link = ?,
                    record_type = ?,
                    collect_time = ?,
                    duration_seconds = ?,
                    collect_status = 'saved'
                WHERE id = ?
                """,
                (
                    article_title,
                    published_article_time,
                    article_link,
                    record_type,
                    collect_time,
                    duration_seconds,
                    article_id,
                ),
            )
            return article_id

        cursor = conn.execute(
            """
            INSERT INTO awa_public_articles (
                account_id,
                article_title,
                published_article_time,
                article_link,
                record_type,
                collect_time,
                duration_seconds,
                collect_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'saved')
            """,
            (
                account_id,
                article_title,
                published_article_time,
                article_link,
                record_type,
                collect_time,
                duration_seconds,
            ),
        )
        return int(cursor.lastrowid)

    def _save_failed_public_article(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: int,
        article_title: str,
        published_article_time: str,
        record_type: str,
        collect_time: str,
        duration_seconds: float,
    ) -> int:
        row = conn.execute(
            """
            SELECT id
            FROM awa_public_articles
            WHERE account_id = ?
              AND article_title = ?
              AND record_type = ?
              AND collect_status = 'failed'
            """,
            (account_id, article_title, record_type),
        ).fetchone()
        if row is not None:
            article_id = int(row[0])
            conn.execute(
                """
                UPDATE awa_public_articles
                SET published_article_time = ?,
                    article_link = '',
                    collect_time = ?,
                    duration_seconds = ?,
                    collect_status = 'failed'
                WHERE id = ?
                """,
                (published_article_time, collect_time, duration_seconds, article_id),
            )
            return article_id

        cursor = conn.execute(
            """
            INSERT INTO awa_public_articles (
                account_id,
                article_title,
                published_article_time,
                article_link,
                record_type,
                collect_time,
                duration_seconds,
                collect_status
            )
            VALUES (?, ?, ?, '', ?, ?, ?, 'failed')
            """,
            (
                account_id,
                article_title,
                published_article_time,
                record_type,
                collect_time,
                duration_seconds,
            ),
        )
        return int(cursor.lastrowid)

    def _upsert_public_account(self, conn: sqlite3.Connection, account_name: str) -> int:
        now = self._now()
        conn.execute(
            """
            INSERT INTO awa_public_accounts (account_name, created_time, updated_time)
            VALUES (?, ?, ?)
            ON CONFLICT(account_name) DO UPDATE SET updated_time = excluded.updated_time
            """,
            (account_name, now, now),
        )
        row = conn.execute(
            "SELECT id FROM awa_public_accounts WHERE account_name = ?",
            (account_name,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _normalize_public_account_name(value: object) -> str:
        text = first_valid_account_name(value, default="")
        if not text:
            raise ValueError("account_name must be a recognized public account name")
        return text

    @staticmethod
    def _normalize_public_article_title(value: object) -> str:
        text = str(value or "").strip()
        if not text or text == "未识别标题":
            raise ValueError("article_title must be a recognized article title")
        return text

    @staticmethod
    def _normalize_record_type(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("record_type is required")
        return text

    @staticmethod
    def _normalize_article_title(value: object) -> str:
        return " ".join(str(value or "").split())

    @staticmethod
    def _normalize_public_collect_status(value: object) -> str:
        text = str(value or "").strip().lower()
        if text in {"saved", "已保存", "保存成功"}:
            return "saved"
        return "failed"

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _unique_positive_ids(values: list[int]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item <= 0 or item in seen:
            continue
        seen.add(item)
        ids.append(item)
    return ids

