from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import Process
from typing import Any, Callable


@dataclass
class ManagedProcess:
    name: str
    process: Any


class ProcessManager:
    """统一管理后台 worker 进程，避免页面多次点击后重复拉起同名任务。"""

    def __init__(self, process_factory: Callable[..., Any] = Process) -> None:
        self._process_factory = process_factory
        self._processes: dict[str, ManagedProcess] = {}

    def start_worker(
        self,
        name: str,
        target: Callable[..., Any],
        args: tuple = (),
        kwargs: dict | None = None,
    ) -> ManagedProcess:
        if self.is_running(name):
            raise RuntimeError(f"worker {name} is already running")

        process = self._process_factory(
            target=target,
            args=args,
            kwargs=kwargs or {},
            daemon=True,
        )
        process.start()

        managed = ManagedProcess(name=name, process=process)
        self._processes[name] = managed
        return managed

    def is_running(self, name: str) -> bool:
        managed = self._processes.get(name)
        return bool(managed and managed.process.is_alive())

    def running_workers(self) -> list[str]:
        return [
            name
            for name, managed in self._processes.items()
            if managed.process.is_alive()
        ]

    def stop_worker(self, name: str, timeout: float = 3) -> bool:
        managed = self._processes.pop(name, None)
        if not managed:
            return False

        process = managed.process
        if process.is_alive():
            process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():
            kill = getattr(process, "kill", None)
            if callable(kill):
                kill()
                process.join(timeout=timeout)
        return True

    def stop_all(self, timeout: float = 3) -> None:
        for name in list(self._processes):
            self.stop_worker(name, timeout=timeout)
