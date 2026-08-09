from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
from typing import Any

from src.modules.processes.process_channel import ProcessChannel


@dataclass(slots=True)
class LaunchedProcess:
    process: Any
    channel: Any


class MultiprocessingProcessLauncher:
    """为每次采集尝试创建全新的 spawn 子进程和双向 Pipe。"""

    def __init__(self, context: Any | None = None) -> None:
        self._context = context or multiprocessing.get_context("spawn")

    def launch(
        self,
        *,
        task_id: str,
        attempt_id: str,
        proxy_lease_id: str,
    ) -> LaunchedProcess:
        parent_connection, child_connection = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=_run_mitm_child,
            args=(child_connection, task_id, attempt_id, proxy_lease_id),
            name=f"awa-mitm-{attempt_id}",
            daemon=False,
        )
        try:
            process.start()
        except Exception:
            parent_connection.close()
            child_connection.close()
            raise
        child_connection.close()
        return LaunchedProcess(
            process=process,
            channel=ProcessChannel(
                parent_connection,
                task_id=task_id,
                attempt_id=attempt_id,
            ),
        )


def _run_mitm_child(
    connection: Any,
    task_id: str,
    attempt_id: str,
    proxy_lease_id: str,
) -> None:
    """保持为顶层函数，确保 Windows spawn 可以导入。"""
    try:
        from src.modules.processes.mitm_capture_process import run_mitm_capture_process

        run_mitm_capture_process(
            connection=connection,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_proxy_lease_id=proxy_lease_id,
        )
    finally:
        connection.close()
