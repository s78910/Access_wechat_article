from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
from uuid import uuid4

from .main_flow_models import (
    MainFlowCommand,
    MainFlowContext,
    MainFlowSnapshot,
)
from .main_flow_state import MainFlowState


class MainFlowConflictError(RuntimeError):
    """同一时间已有一个主流程接管任务。"""

    def __init__(self, owner_task_id: str) -> None:
        super().__init__(f"主流程任务正在运行：{owner_task_id}")
        self.owner_task_id = owner_task_id


@dataclass(slots=True)
class _ManagedMainFlow:
    context: MainFlowContext
    command: MainFlowCommand
    state: MainFlowState
    thread: Thread | None = None
    finished_at: datetime | None = None


class MainFlowService:
    """主服务生命周期入口；具体主页扫描和单篇分发通过 runner 注入。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        config: Any,
        db_path: str | Path,
        storage_root: str | Path,
        temp_root: str | Path,
        runtime_logger: Any | None = None,
        runner: Callable[[MainFlowContext, MainFlowCommand], None] | None = None,
        now: Callable[[], datetime] = datetime.now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        self._config = config
        self._db_path = Path(db_path)
        self._storage_root = Path(storage_root)
        self._temp_root = Path(temp_root)
        self._runtime_logger = runtime_logger
        self._runner = runner
        self._now = now
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._lock = RLock()
        self._tasks: dict[str, _ManagedMainFlow] = {}
        self._active_task_id: str | None = None

    @property
    def active_task_id(self) -> str | None:
        with self._lock:
            return self._active_task_id

    def start(self, command: MainFlowCommand) -> MainFlowSnapshot:
        with self._lock:
            if self._active_task_id is not None:
                active = self._tasks.get(self._active_task_id)
                if active is not None and active.state.snapshot()["status"] in {
                    "starting",
                    "running",
                    "stopping",
                }:
                    raise MainFlowConflictError(self._active_task_id)
            task_id = f"main-{self._id_factory()}"
            state = MainFlowState(task_id=task_id, target_count=command.target_count, now=self._now)
            cancel_token = Event()
            context = MainFlowContext(
                task_id=task_id,
                db_path=self._db_path,
                storage_root=self._storage_root,
                temp_dir=self._temp_root / task_id,
                config_snapshot=self._config,
                cancel_token=cancel_token,
                started_at=self._now(),
                state=state,
            )
            managed = _ManagedMainFlow(context=context, command=command, state=state)
            self._tasks[task_id] = managed
            self._active_task_id = task_id
            thread = Thread(
                target=self._run,
                args=(managed,),
                name=f"awa-main-flow-{task_id}",
                daemon=True,
            )
            managed.thread = thread
            state.set_starting()
            initial_snapshot = self._snapshot(managed)
            thread.start()
            return initial_snapshot

    def stop(self, task_id: str | None = None) -> bool:
        with self._lock:
            selected_id = task_id or self._active_task_id
            managed = self._tasks.get(selected_id or "")
            if managed is None:
                return False
            status = managed.state.snapshot()["status"]
            if status in {"completed", "failed", "cancelled"}:
                return False
            managed.context.cancel_token.set()
            managed.state.request_stop()
            return True

    def get(self, task_id: str) -> MainFlowSnapshot:
        with self._lock:
            managed = self._tasks.get(task_id)
            if managed is None:
                raise KeyError(f"主流程任务不存在：{task_id}")
            return self._snapshot(managed)

    def current(self) -> MainFlowSnapshot | None:
        with self._lock:
            if self._active_task_id is None:
                return None
            managed = self._tasks.get(self._active_task_id)
            return None if managed is None else self._snapshot(managed)

    def wait(self, task_id: str, timeout_seconds: float | None = None) -> MainFlowSnapshot:
        with self._lock:
            managed = self._tasks.get(task_id)
            if managed is None:
                raise KeyError(f"主流程任务不存在：{task_id}")
            thread = managed.thread
        if thread is not None:
            thread.join(timeout_seconds)
        return self.get(task_id)

    def _run(self, managed: _ManagedMainFlow) -> None:
        managed.state.start()
        try:
            if self._runner is None:
                # 阶段一只验证生命周期，真实主页扫描器在后续阶段注入。
                managed.state.set_action("等待主页扫描模块接入")
                if managed.context.cancel_token.is_set():
                    managed.state.cancel()
                else:
                    managed.state.complete("主流程骨架已运行；主页扫描模块待接入")
            else:
                self._runner(managed.context, managed.command)
                if managed.context.cancel_token.is_set():
                    managed.state.cancel()
                elif managed.state.snapshot()["status"] not in {"failed", "cancelled"}:
                    managed.state.complete()
        except Exception as exc:
            message = f"主流程异常：{type(exc).__name__}: {exc}"
            managed.state.fail(message)
            self._write_error(message, exc)
        finally:
            managed.finished_at = self._now()
            with self._lock:
                if self._active_task_id == managed.context.task_id:
                    self._active_task_id = None

    def _snapshot(self, managed: _ManagedMainFlow) -> MainFlowSnapshot:
        state = managed.state.snapshot()
        return MainFlowSnapshot(
            task_id=managed.context.task_id,
            status=str(state["status"]),
            message=str(state.get("message") or ""),
            runtime_state=state,
            traffic=dict(state.get("traffic") or {}),
            started_at=managed.context.started_at.isoformat(timespec="seconds"),
            finished_at=(
                managed.finished_at.isoformat(timespec="seconds")
                if managed.finished_at is not None
                else None
            ),
        )

    def _write_error(self, message: str, exception: BaseException) -> None:
        method = getattr(self._runtime_logger, "write_error", None)
        if not callable(method):
            return
        try:
            method(message, source="main-flow", exception=exception, summary=True)
        except Exception:
            return
