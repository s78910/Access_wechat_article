from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from src.modules.html_archive.article_html_archiver import archive_article_html
from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveResult, ArticleHtmlArchiveTask
from src.modules.html_archive.url_guard import normalize_plain_wechat_short_link
from src.modules.storage.sqlite_store import SQLiteStore


ArchiveFunc = Callable[[ArticleHtmlArchiveTask, ArticleHtmlArchiveConfig], ArticleHtmlArchiveResult]


@dataclass
class ArchiveCacheResultItem:
    """单篇文章缓存结果；字段保持和前端展示所需信息一致。"""

    article_id: int
    article_title: str
    ok: bool
    status: str
    message: str = ""
    archive_dir: str = ""
    index_html_path: str = ""
    resource_count: int = 0
    warning: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "articleId": self.article_id,
            "articleTitle": self.article_title,
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "archiveDir": self.archive_dir,
            "indexHtmlPath": self.index_html_path,
            "resourceCount": self.resource_count,
            "warning": self.warning,
            "elapsedSeconds": round(self.elapsed_seconds, 3),
        }


@dataclass
class ArchiveCacheJob:
    """后台缓存任务快照；tasks 只在服务内部使用，不返回给前端。"""

    job_id: str
    tasks: list[ArticleHtmlArchiveTask]
    concurrency: int
    status: str = "pending"
    finished: int = 0
    running: int = 0
    message: str = ""
    results: list[ArchiveCacheResultItem] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.status not in {"failed", "missing"},
            "jobId": self.job_id,
            "status": self.status,
            "total": self.total,
            "finished": self.finished,
            "running": self.running,
            "concurrency": self.concurrency,
            "results": [item.to_dict() for item in self.results],
            "message": self.message,
        }


class ArchiveCacheJobRunner:
    """低耦合的 HTML 缓存任务运行器；FastAPI 只负责创建和查询 job。"""

    def __init__(
        self,
        *,
        concurrency: int = 3,
        archive_func: ArchiveFunc = archive_article_html,
        executor_factory=ProcessPoolExecutor,
        archive_config: ArticleHtmlArchiveConfig | None = None,
    ) -> None:
        self.concurrency = max(1, int(concurrency or 1))
        self.archive_func = archive_func
        self.executor_factory = executor_factory
        base_config = archive_config or ArticleHtmlArchiveConfig()
        self.archive_config = replace(base_config, concurrency=self.concurrency)
        self._jobs: dict[str, ArchiveCacheJob] = {}
        self._lock = threading.RLock()

    def create_job(self, tasks: Iterable[ArticleHtmlArchiveTask]) -> ArchiveCacheJob:
        task_list = list(tasks)
        job = ArchiveCacheJob(
            job_id=uuid.uuid4().hex,
            tasks=task_list,
            concurrency=self.concurrency,
            status="pending" if task_list else "done",
            message="" if task_list else "没有可缓存的文章。",
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def start_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None or job.status != "pending":
            return
        thread = threading.Thread(target=self.run_job, args=(job_id,), name=f"archive-cache-{job_id[:8]}", daemon=True)
        thread.start()

    def run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return
        if not job.tasks:
            self._update_job(job, status="done", finished=0, running=0, message="没有可缓存的文章。")
            return

        max_workers = max(1, min(self.concurrency, len(job.tasks)))
        self._update_job(job, status="running", running=max_workers, message="")
        try:
            with self.executor_factory(max_workers=max_workers) as executor:
                future_context = {
                    executor.submit(self.archive_func, task, self.archive_config): (task, time.perf_counter())
                    for task in job.tasks
                }
                for future in as_completed(future_context):
                    task, started_at = future_context[future]
                    result_item = self._resolve_future(task, started_at, future)
                    with self._lock:
                        job.results.append(result_item)
                        job.finished += 1
                        remaining = job.total - job.finished
                        job.running = min(max_workers, remaining)
                        job.updated_at = time.time()
        except Exception as exc:  # pragma: no cover - 这里兜住进程池创建等系统级异常。
            self._update_job(job, status="failed", running=0, message=f"缓存任务执行失败：{exc}")
            return

        with self._lock:
            failed_count = sum(1 for item in job.results if not item.ok)
            job.status = "done" if failed_count == 0 else "partial_failed"
            job.running = 0
            job.message = "" if failed_count == 0 else f"{failed_count} 篇文章缓存失败。"
            job.updated_at = time.time()

    def get_job(self, job_id: str) -> ArchiveCacheJob | None:
        with self._lock:
            return self._jobs.get(str(job_id or ""))

    def _resolve_future(self, task: ArticleHtmlArchiveTask, started_at: float, future: Any) -> ArchiveCacheResultItem:
        try:
            result = future.result()
        except Exception as exc:
            return ArchiveCacheResultItem(
                article_id=task.article_id,
                article_title=task.article_title,
                ok=False,
                status="failed",
                message=str(exc),
                elapsed_seconds=time.perf_counter() - started_at,
            )

        return _archive_result_to_item(task, result, elapsed_seconds=time.perf_counter() - started_at)

    def _update_job(self, job: ArchiveCacheJob, **updates: object) -> None:
        with self._lock:
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = time.time()


def build_cache_tasks_for_articles(
    store: SQLiteStore,
    article_ids: Iterable[int],
    *,
    storage_root: str | Path,
) -> list[ArticleHtmlArchiveTask]:
    """按用户勾选顺序构建缓存任务；无效 ID、失败记录和带参数链接会被跳过。"""
    ordered_ids = _unique_positive_ids(article_ids)
    if not ordered_ids:
        return []
    rows = store.get_public_articles_by_ids(ordered_ids)
    row_by_id = {int(row.get("id") or 0): row for row in rows}
    return [
        task
        for article_id in ordered_ids
        if (task := _row_to_cache_task(row_by_id.get(article_id), storage_root=storage_root)) is not None
    ]


def build_cache_tasks_for_account(
    store: SQLiteStore,
    account_id: int,
    *,
    storage_root: str | Path,
) -> list[ArticleHtmlArchiveTask]:
    """构建某个公众号下全部可缓存文章任务；排序沿用 SQLiteStore 的文章列表排序。"""
    rows = store.list_public_articles_by_account(int(account_id), limit=None)
    return [
        task
        for row in rows
        if (task := _row_to_cache_task(row, storage_root=storage_root)) is not None
    ]


def _row_to_cache_task(row: dict[str, object] | None, *, storage_root: str | Path) -> ArticleHtmlArchiveTask | None:
    if not row or str(row.get("collect_status") or "").strip().lower() != "saved":
        return None
    short_link = normalize_plain_wechat_short_link(row.get("article_link"))
    if not short_link:
        return None
    return ArticleHtmlArchiveTask(
        article_id=int(row.get("id") or 0),
        short_link=short_link,
        account_name=str(row.get("account_name") or ""),
        published_article_time=str(row.get("published_article_time") or ""),
        article_title=str(row.get("article_title") or ""),
        storage_root=Path(storage_root),
    )


def _archive_result_to_item(
    task: ArticleHtmlArchiveTask,
    result: ArticleHtmlArchiveResult,
    *,
    elapsed_seconds: float,
) -> ArchiveCacheResultItem:
    return ArchiveCacheResultItem(
        article_id=task.article_id,
        article_title=task.article_title,
        ok=bool(result.ok),
        status="done" if result.ok else "failed",
        message=result.message,
        archive_dir=str(result.archive_dir or ""),
        index_html_path=str(result.index_html_path or ""),
        resource_count=int(result.resource_count or 0),
        warning=result.warning,
        elapsed_seconds=elapsed_seconds,
    )


def _unique_positive_ids(values: Iterable[int]) -> list[int]:
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


__all__ = [
    "ArchiveCacheJob",
    "ArchiveCacheJobRunner",
    "ArchiveCacheResultItem",
    "build_cache_tasks_for_account",
    "build_cache_tasks_for_articles",
]
