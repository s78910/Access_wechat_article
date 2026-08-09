from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from src.domain.enums import TaskStatus
from src.domain.models import ResourceManifest


@dataclass(frozen=True, slots=True)
class FetchHistoryWrite:
    task_type: str
    status: TaskStatus
    started_time: str
    article_id: int | None = None
    account_id: int | None = None
    target_account_name: str = ""
    target_title: str = ""
    target_link: str = ""
    resource_manifest: ResourceManifest = field(default_factory=ResourceManifest)
    finished_time: str = ""
    duration_seconds: float = 0
    error_stage: str = ""
    error_message: str = ""
    output_dir: str = ""

    @classmethod
    def failed(
        cls,
        *,
        target_account_name: str,
        target_title: str,
        task_type: str,
        started_time: str,
        finished_time: str,
        duration_seconds: float,
        error_stage: str,
        error_message: str,
        target_link: str = "",
        article_id: int | None = None,
        account_id: int | None = None,
    ) -> FetchHistoryWrite:
        return cls(
            article_id=article_id,
            account_id=account_id,
            target_account_name=target_account_name,
            target_title=target_title,
            target_link=target_link,
            task_type=task_type,
            status=TaskStatus.FAILED,
            started_time=started_time,
            finished_time=finished_time,
            duration_seconds=duration_seconds,
            error_stage=error_stage,
            error_message=error_message,
        )


@dataclass(frozen=True, slots=True)
class FetchHistoryPage:
    """采集历史分页查询结果。"""

    page: int
    page_size: int
    total: int
    rows: tuple[sqlite3.Row, ...]


class FetchHistoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append(self, history: FetchHistoryWrite) -> int:
        if history.status not in {TaskStatus.SUCCESS, TaskStatus.FAILED}:
            raise ValueError("获取历史状态只允许 success 或 failed")
        if not history.task_type.strip():
            raise ValueError("task_type 不能为空")
        if history.duration_seconds < 0:
            raise ValueError("duration_seconds 不能小于 0")

        resource_types_json = json.dumps(
            history.resource_manifest.to_json_values(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cursor = self.connection.execute(
            """
            INSERT INTO awa_fetch_history(
                article_id,
                account_id,
                target_account_name,
                target_title,
                target_link,
                task_type,
                resource_types_json,
                status,
                started_time,
                finished_time,
                duration_seconds,
                error_stage,
                error_message,
                output_dir
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history.article_id,
                history.account_id,
                history.target_account_name,
                history.target_title,
                history.target_link,
                history.task_type.strip(),
                resource_types_json,
                history.status.value,
                history.started_time,
                history.finished_time,
                history.duration_seconds,
                history.error_stage,
                history.error_message,
                history.output_dir,
            ),
        )
        return int(cursor.lastrowid)

    def list_page(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str = "",
        task_type: str = "",
        status: str = "",
        collect_date: str = "",
        collect_start_date: str = "",
        collect_end_date: str = "",
    ) -> FetchHistoryPage:
        """按开始时间倒序读取历史记录，关联数据只用于补充缺失快照。"""

        safe_page_size = max(1, min(int(page_size), 100))
        where_sql, params = self._build_filters(
            keyword=keyword,
            task_type=task_type,
            status=status,
            collect_date=collect_date,
            collect_start_date=collect_start_date,
            collect_end_date=collect_end_date,
        )
        from_sql = """
            FROM awa_fetch_history h
            LEFT JOIN awa_public_accounts a ON a.id = h.account_id
            LEFT JOIN awa_public_articles ar ON ar.id = h.article_id
        """
        total = int(
            self.connection.execute(
                f"SELECT COUNT(*) {from_sql} {where_sql}",
                params,
            ).fetchone()[0]
        )
        total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(int(page), total_pages))
        rows = self.connection.execute(
            f"""
            SELECT
                h.*,
                a.account_name,
                ar.article_title,
                ar.published_article_time,
                ar.article_link
            {from_sql}
            {where_sql}
            ORDER BY h.started_time DESC, h.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_page_size, (safe_page - 1) * safe_page_size),
        ).fetchall()
        return FetchHistoryPage(
            page=safe_page,
            page_size=safe_page_size,
            total=total,
            rows=tuple(rows),
        )

    def read_summary(self) -> sqlite3.Row:
        """读取历史任务总量、状态、最近时间、耗时和成功文章数。"""

        return self.connection.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                MAX(started_time) AS latest_collect_time,
                AVG(duration_seconds) AS average_duration,
                COUNT(DISTINCT CASE
                    WHEN status = 'success'
                         AND task_type = 'article_capture'
                         AND article_id IS NOT NULL
                    THEN article_id
                END) AS collected_article_count
            FROM awa_fetch_history
            """
        ).fetchone()

    def read_daily_counts(self, *, start_date: str, end_date: str) -> dict[str, int]:
        """读取指定自然日区间内每天的历史任务数。"""

        rows = self.connection.execute(
            """
            SELECT substr(started_time, 1, 10) AS collect_date, COUNT(*) AS record_count
            FROM awa_fetch_history
            WHERE substr(started_time, 1, 10) BETWEEN ? AND ?
            GROUP BY substr(started_time, 1, 10)
            """,
            (start_date, end_date),
        ).fetchall()
        return {
            str(row["collect_date"]): int(row["record_count"] or 0)
            for row in rows
            if str(row["collect_date"] or "").strip()
        }

    def list_suggestions(self, *, keyword: str, limit: int) -> list[str]:
        """分别查询标题和公众号快照，再合并去重为搜索候选。"""

        pattern = f"%{keyword.strip()}%" if keyword.strip() else "%"
        rows = self.connection.execute(
            """
            SELECT suggestion
            FROM (
                SELECT target_title AS suggestion
                FROM awa_fetch_history
                UNION
                SELECT target_account_name AS suggestion
                FROM awa_fetch_history
            )
            WHERE trim(suggestion) <> '' AND suggestion LIKE ?
            ORDER BY suggestion
            LIMIT ?
            """,
            (pattern, max(1, min(int(limit), 50))),
        ).fetchall()
        return [str(row["suggestion"]) for row in rows]

    def _build_filters(
        self,
        *,
        keyword: str,
        task_type: str,
        status: str,
        collect_date: str,
        collect_start_date: str,
        collect_end_date: str,
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        if keyword.strip():
            clauses.append(
                """(
                    h.target_title LIKE ?
                    OR h.target_account_name LIKE ?
                    OR h.target_link LIKE ?
                    OR ar.article_title LIKE ?
                    OR a.account_name LIKE ?
                    OR ar.article_link LIKE ?
                )"""
            )
            pattern = f"%{keyword.strip()}%"
            params.extend([pattern] * 6)
        if task_type:
            clauses.append("h.task_type = ?")
            params.append(task_type)
        if status:
            clauses.append("h.status = ?")
            params.append(status)
        if collect_date.strip():
            clauses.append("substr(h.started_time, 1, 10) = ?")
            params.append(collect_date.strip())
        else:
            if collect_start_date.strip():
                clauses.append("substr(h.started_time, 1, 10) >= ?")
                params.append(collect_start_date.strip())
            if collect_end_date.strip():
                clauses.append("substr(h.started_time, 1, 10) <= ?")
                params.append(collect_end_date.strip())
        return ("" if not clauses else "WHERE " + " AND ".join(clauses), tuple(params))
