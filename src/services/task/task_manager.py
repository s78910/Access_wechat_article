from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
from uuid import uuid4

from src.domain.enums import ErrorCode, TaskStatus
from src.domain.models import TaskCommand, TaskContext
from src.domain.results import TaskResult
from src.services.runtime.task_runtime_state import TaskRuntimeTracker


class TaskConflictError(RuntimeError):
    def __init__(self, owner_task_id: str) -> None:
        super().__init__(f"文章采集代理正在被任务 {owner_task_id} 占用")
        self.owner_task_id = owner_task_id


@dataclass(frozen=True, slots=True)
class CaptureTaskSnapshot:
    task_id: str
    proxy_lease_id: str
    status: TaskStatus
    result: TaskResult[Any] | None = None
    runtime_state: dict[str, Any] | None = None

    @property
    def message(self) -> str:
        return "" if self.result is None else self.result.message


@dataclass(slots=True)
class _ManagedTask:
    context: TaskContext
    status: TaskStatus
    runtime_state: TaskRuntimeTracker
    result: TaskResult[Any] | None = None
    thread: Thread | None = None


class CaptureTaskManager:
    """管理文章采集后台线程、取消令牌和进程内唯一代理租约。"""

    def __init__(
        self,
        *,
        capture_service: Any,
        db_path: str | Path,
        storage_root: str | Path,
        temp_root: str | Path,
        single_capture_settings: Any,
        request_timeout_seconds: float,
        comment_timeout_seconds: float | None = None,
        comment_page_interval_seconds: float = 0,
        comment_max_pages: int = 5,
        runtime_logger: Any | None = None,
        id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._capture_service = capture_service
        self._db_path = Path(db_path)
        self._storage_root = Path(storage_root)
        self._temp_root = Path(temp_root)
        self._single_capture_settings = single_capture_settings
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._comment_timeout_seconds = (
            self._request_timeout_seconds
            if comment_timeout_seconds is None
            else float(comment_timeout_seconds)
        )
        self._comment_page_interval_seconds = max(0.0, float(comment_page_interval_seconds))
        self._comment_max_pages = max(1, int(comment_max_pages))
        self._runtime_logger = runtime_logger
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._now = now
        self._tasks: dict[str, _ManagedTask] = {}
        self._capture_owner_task_id: str | None = None
        self._lock = RLock()

    @property
    def capture_owner_task_id(self) -> str | None:
        with self._lock:
            return self._capture_owner_task_id

    def start_capture(self, command: TaskCommand) -> CaptureTaskSnapshot:
        with self._lock:
            if self._capture_owner_task_id is not None:
                raise TaskConflictError(self._capture_owner_task_id)
            task_id = self._new_id("task")
            lease_id = self._new_id("lease")
            context = TaskContext(
                task_id=task_id,
                proxy_lease_id=lease_id,
                db_path=self._db_path,
                storage_root=self._storage_root,
                temp_dir=self._temp_root / task_id,
                started_at=self._now(),
                cancel_token=Event(),
            )
            runtime_state = TaskRuntimeTracker(
                progress_total_label=self._progress_total_label(command),
                runtime_logger=self._runtime_logger,
            )
            runtime_state.set_action("准备采集任务")
            managed = _ManagedTask(
                context=context,
                status=TaskStatus.PENDING,
                runtime_state=runtime_state,
            )
            self._tasks[task_id] = managed
            self._capture_owner_task_id = task_id
            thread = Thread(
                target=self._run_capture,
                args=(task_id, command),
                name=f"awa-capture-{task_id}",
                daemon=False,
            )
            managed.thread = thread
            self._write_summary(
                "INFO",
                self._task_started_message(command),
                context={
                    "task_id": task_id,
                    "target_success_count": command.target_success_count,
                    "collect_comments": command.collect_comments,
                },
            )
            thread.start()
            return self._snapshot(managed)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            managed = self._tasks.get(task_id)
            if managed is None or managed.status in {
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return False
            managed.context.cancel_token.set()
            managed.runtime_state.set_action("停止采集任务")
            self._write_summary(
                "INFO",
                "已请求停止采集任务",
                context={"task_id": task_id},
            )
            return True

    def get(self, task_id: str) -> CaptureTaskSnapshot:
        with self._lock:
            managed = self._tasks.get(task_id)
            if managed is None:
                raise KeyError(f"任务不存在：{task_id}")
            return self._snapshot(managed)

    def wait(self, task_id: str, *, timeout_seconds: float | None = None) -> CaptureTaskSnapshot:
        with self._lock:
            managed = self._tasks.get(task_id)
            if managed is None:
                raise KeyError(f"任务不存在：{task_id}")
            thread = managed.thread
        if thread is not None:
            thread.join(timeout_seconds)
        return self.get(task_id)

    def _run_capture(self, task_id: str, command: TaskCommand) -> None:
        caught_exception: BaseException | None = None
        with self._lock:
            managed = self._tasks[task_id]
            managed.status = TaskStatus.RUNNING
            managed.runtime_state.set_action("准备采集任务")
        try:
            result = self._capture_service.run(
                command,
                managed.context,
                single_capture_settings=self._single_capture_settings,
                request_timeout_seconds=self._request_timeout_seconds,
                comment_timeout_seconds=self._comment_timeout_seconds,
                comment_page_interval_seconds=self._comment_page_interval_seconds,
                comment_max_pages=self._comment_max_pages,
                runtime_state=managed.runtime_state,
            )
        except Exception as exc:
            caught_exception = exc
            managed.runtime_state.record_error(f"{type(exc).__name__}: {exc}")
            result = TaskResult(
                status=TaskStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                message=f"采集任务异常：{type(exc).__name__}: {exc}",
            )
        with self._lock:
            managed.runtime_state.set_terminal_action(result.status)
            managed.result = result
            managed.status = result.status
            if self._capture_owner_task_id == task_id:
                self._capture_owner_task_id = None
            runtime_snapshot = managed.runtime_state.snapshot()
        self._write_terminal_summary(
            task_id=task_id,
            result=result,
            runtime_snapshot=runtime_snapshot,
            exception=caught_exception,
        )

    def _new_id(self, prefix: str) -> str:
        value = str(self._id_factory() or "").strip()
        if not value:
            raise RuntimeError("任务 ID 生成器返回空值")
        return f"{prefix}-{value}"

    @staticmethod
    def _progress_total_label(command: TaskCommand) -> str:
        return "全部" if command.target_success_count == 0 else str(command.target_success_count)

    @staticmethod
    def _task_started_message(command: TaskCommand) -> str:
        target = (
            "全部文章"
            if command.target_success_count == 0
            else f"目标 {command.target_success_count} 篇"
        )
        comment = "，评论采集已开启" if command.collect_comments else ""
        return f"采集任务已启动：{target}{comment}"

    def _write_terminal_summary(
        self,
        *,
        task_id: str,
        result: TaskResult[Any],
        runtime_snapshot: dict[str, Any],
        exception: BaseException | None,
    ) -> None:
        progress_done = int(runtime_snapshot.get("progressDone") or 0)
        error_count = int(runtime_snapshot.get("errorCount") or 0)
        context = {
            "task_id": task_id,
            "status": result.status.value,
            "progress_done": progress_done,
            "error_count": error_count,
        }
        if result.status is TaskStatus.SUCCESS:
            self._write_summary(
                "SUCCESS",
                f"采集任务完成：处理 {progress_done} 篇，异常 {error_count} 篇",
                context=context,
            )
            return
        if result.status is TaskStatus.CANCELLED:
            self._write_summary("INFO", "采集任务已停止", context=context)
            return
        self._write_error(
            result.message or "采集任务异常",
            context=context,
            exception=exception,
        )

    def _write_summary(
        self,
        level: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        method = getattr(self._runtime_logger, "write_summary", None)
        if callable(method):
            try:
                method(level, message, source="task-manager", context=context)
            except Exception:
                pass

    def _write_error(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        method = getattr(self._runtime_logger, "write_error", None)
        if callable(method):
            try:
                method(
                    message,
                    source="task-manager",
                    context=context,
                    exception=exception,
                )
            except Exception:
                pass

    @staticmethod
    def _snapshot(managed: _ManagedTask) -> CaptureTaskSnapshot:
        return CaptureTaskSnapshot(
            task_id=managed.context.task_id,
            proxy_lease_id=managed.context.proxy_lease_id,
            status=managed.status,
            result=managed.result,
            runtime_state=managed.runtime_state.snapshot(),
        )
