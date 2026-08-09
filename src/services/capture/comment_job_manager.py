from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
import time
from typing import Any, Callable, Mapping

from src.domain.enums import TaskStatus
from src.domain.models import TaskContext
from src.services.capture.comment_process_control_service import (
    CommentProcessControlService,
    CommentProcessError,
)
from src.services.capture.html_parse_save_service import ArticleSaveData
from src.services.runtime.database_write_coordinator import DatabaseWriteCoordinator


@dataclass(frozen=True, slots=True)
class CommentJobOutcome:
    article_id: int
    article_key: str
    article_title: str
    status: TaskStatus
    message: str
    comment_count: int = 0
    reply_count: int = 0
    page_count: int = 0
    duration_seconds: float = 0.0


class CommentJobManager:
    """以固定线程池监控一次性评论子进程，主文章线程只负责提交任务。"""

    def __init__(
        self,
        *,
        process_control: Any | None = None,
        write_coordinator: DatabaseWriteCoordinator | None = None,
        max_concurrent_processes: int = 3,
        ready_timeout_seconds: float = 5.0,
        result_timeout_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        concurrency = int(max_concurrent_processes)
        if concurrency <= 0:
            raise ValueError("评论子进程最大并发数必须大于 0")
        self._process_control = process_control or CommentProcessControlService()
        self._write_coordinator = write_coordinator or DatabaseWriteCoordinator()
        self._ready_timeout_seconds = max(0.1, float(ready_timeout_seconds))
        self._result_timeout_seconds = max(0.1, float(result_timeout_seconds))
        self._monotonic = monotonic
        self._now = now
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="awa-comment-monitor",
        )
        self._futures: list[Future[CommentJobOutcome]] = []
        self._active_attempts: set[Any] = set()
        self._cancelled = False
        self._closed = False
        self._lock = RLock()

    def submit(
        self,
        *,
        context: TaskContext,
        article: ArticleSaveData,
        article_key: str,
        article_title: str,
        article_started_monotonic: float,
        timeout_seconds: float,
        page_interval_seconds: float,
        max_pages: int,
        runtime_state: Any | None = None,
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("评论任务管理器已经关闭")
            if self._cancelled:
                raise RuntimeError("评论任务管理器已经取消")
            future = self._executor.submit(
                self._run_job,
                context=context,
                article=article,
                article_key=str(article_key),
                article_title=str(article_title),
                article_started_monotonic=float(article_started_monotonic),
                timeout_seconds=float(timeout_seconds),
                page_interval_seconds=float(page_interval_seconds),
                max_pages=int(max_pages),
                runtime_state=runtime_state,
            )
            self._futures.append(future)
        _runtime_call(
            runtime_state,
            "record_article_stage",
            article_key=str(article_key),
            stage="comment",
            label="评论采集",
            status="queued",
            duration_seconds=0.0,
            message="等待评论子进程",
        )

    def drain(self) -> tuple[CommentJobOutcome, ...]:
        with self._lock:
            futures = tuple(self._futures)
            self._closed = True
        outcomes: list[CommentJobOutcome] = []
        for future in futures:
            if future.cancelled():
                continue
            try:
                outcomes.append(future.result())
            except Exception as exc:
                # 工作线程内部会把业务异常转换成 CommentJobOutcome；这里只兜底线程本身异常。
                outcomes.append(
                    CommentJobOutcome(
                        article_id=0,
                        article_key="",
                        article_title="",
                        status=TaskStatus.FAILED,
                        message=f"评论监控线程异常：{type(exc).__name__}: {exc}",
                    )
                )
        self._executor.shutdown(wait=True, cancel_futures=self._cancelled)
        return tuple(outcomes)

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            futures = tuple(self._futures)
            attempts = tuple(self._active_attempts)
        for future in futures:
            future.cancel()
        for attempt in attempts:
            try:
                attempt.cancel()
            except Exception:
                pass

    def _run_job(
        self,
        *,
        context: TaskContext,
        article: ArticleSaveData,
        article_key: str,
        article_title: str,
        article_started_monotonic: float,
        timeout_seconds: float,
        page_interval_seconds: float,
        max_pages: int,
        runtime_state: Any | None,
    ) -> CommentJobOutcome:
        comment_started = self._monotonic()
        attempt = None
        worker_tracked = False
        try:
            with self._lock:
                if self._cancelled:
                    raise RuntimeError("评论任务已取消")
            comment_attempt_id = f"{article.attempt_id}-comment"
            attempt = self._process_control.start(
                task_id=context.task_id,
                attempt_id=comment_attempt_id,
                payload=self._build_payload(
                    context=context,
                    article=article,
                    timeout_seconds=timeout_seconds,
                    page_interval_seconds=page_interval_seconds,
                    max_pages=max_pages,
                ),
            )
            with self._lock:
                self._active_attempts.add(attempt)
                cancelled_after_start = self._cancelled
            _runtime_call(runtime_state, "worker_started")
            worker_tracked = True
            if cancelled_after_start:
                attempt.cancel()
                raise RuntimeError("评论任务已取消")
            attempt.wait_ready(timeout_seconds=self._ready_timeout_seconds)
            _runtime_call(
                runtime_state,
                "record_article_stage",
                article_key=article_key,
                stage="comment",
                label="评论采集",
                status="running",
                duration_seconds=self._monotonic() - comment_started,
                message="评论子进程已就绪",
            )
            raw_result = attempt.wait_result(
                timeout_seconds=self._result_timeout_seconds,
                on_progress=lambda event: self._record_progress(
                    runtime_state=runtime_state,
                    article_key=article_key,
                    event=event,
                ),
            )
            outcome = _outcome_from_result(
                article=article,
                article_key=article_key,
                article_title=article_title,
                result=raw_result,
                duration_seconds=self._monotonic() - comment_started,
            )
        except Exception as exc:
            raw_result = exc.result if isinstance(exc, CommentProcessError) else None
            outcome = _outcome_from_failure(
                article=article,
                article_key=article_key,
                article_title=article_title,
                message=(
                    str(raw_result.get("message") or exc)
                    if isinstance(raw_result, Mapping)
                    else str(exc)
                ),
                duration_seconds=self._monotonic() - comment_started,
            )
        finally:
            if attempt is not None:
                with self._lock:
                    self._active_attempts.discard(attempt)
            if worker_tracked:
                _runtime_call(runtime_state, "worker_finished")

        successful = outcome.status is TaskStatus.SUCCESS
        _runtime_call(
            runtime_state,
            "record_article_stage",
            article_key=article_key,
            stage="comment",
            label="评论采集",
            status="success" if successful else "failed",
            duration_seconds=outcome.duration_seconds,
            message=outcome.message,
        )
        if not successful:
            _runtime_call(runtime_state, "record_article_error", article_key, outcome.message)
        _runtime_call(
            runtime_state,
            "finish_article",
            article_key=article_key,
            duration_seconds=max(0.0, self._monotonic() - article_started_monotonic),
            count_for_average=True,
            status="success" if successful else "failed",
        )
        return outcome

    def _build_payload(
        self,
        *,
        context: TaskContext,
        article: ArticleSaveData,
        timeout_seconds: float,
        page_interval_seconds: float,
        max_pages: int,
    ) -> dict[str, Any]:
        return {
            "proxy_lease_id": f"{context.proxy_lease_id}-comment",
            "db_path": str(context.db_path),
            "storage_root": str(context.storage_root),
            "temp_dir": str(context.temp_dir),
            "started_at": self._now().isoformat(),
            "article_id": article.article_id,
            "account_id": article.account_id,
            "history_id": article.history_id,
            "archive_dir": article.archive_dir,
            "article_directory": str(article.article_directory),
            "html_source": article.html_source,
            "resource_manifest": article.resource_manifest.to_json_values(),
            "timeout_seconds": timeout_seconds,
            "page_interval_seconds": page_interval_seconds,
            "max_pages": max_pages,
            "database_write_coordinator": self._write_coordinator,
        }

    def _record_progress(
        self,
        *,
        runtime_state: Any | None,
        article_key: str,
        event: Mapping[str, Any],
    ) -> None:
        _runtime_call(
            runtime_state,
            "record_article_stage",
            article_key=article_key,
            stage="comment_progress",
            label=str(event.get("name") or "评论采集"),
            status=str(event.get("status") or "running"),
            duration_seconds=float(event.get("elapsed_seconds") or 0.0),
            message=str(event.get("result") or "评论子进程正在执行"),
        )


def _outcome_from_result(
    *,
    article: ArticleSaveData,
    article_key: str,
    article_title: str,
    result: Mapping[str, Any],
    duration_seconds: float,
) -> CommentJobOutcome:
    raw_status = str(result.get("status") or TaskStatus.FAILED.value)
    try:
        status = TaskStatus(raw_status)
    except ValueError:
        status = TaskStatus.FAILED
    return CommentJobOutcome(
        article_id=article.article_id,
        article_key=article_key,
        article_title=article_title,
        status=status,
        message=str(result.get("message") or "评论采集完成"),
        comment_count=_safe_int(result.get("comment_count")),
        reply_count=_safe_int(result.get("reply_count")),
        page_count=_safe_int(result.get("page_count")),
        duration_seconds=max(0.0, float(duration_seconds)),
    )


def _outcome_from_failure(
    *,
    article: ArticleSaveData,
    article_key: str,
    article_title: str,
    message: str,
    duration_seconds: float,
) -> CommentJobOutcome:
    return CommentJobOutcome(
        article_id=article.article_id,
        article_key=article_key,
        article_title=article_title,
        status=TaskStatus.FAILED,
        message=message or "评论采集失败",
        duration_seconds=max(0.0, float(duration_seconds)),
    )


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _runtime_call(runtime_state: Any | None, method_name: str, *args: Any, **kwargs: Any) -> None:
    method = getattr(runtime_state, method_name, None)
    if callable(method):
        try:
            method(*args, **kwargs)
        except Exception:
            pass


__all__ = ["CommentJobManager", "CommentJobOutcome"]
