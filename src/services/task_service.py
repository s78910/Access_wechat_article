from __future__ import annotations

from typing import Any

from src.core.task_manager import TaskManager


class TaskService:
    """主服务页任务流程入口。

    页面上的“开始运行、停止、读取状态、读取日志”都先到这里，再交给 TaskManager。
    这样后续 TaskManager 继续拆分时，FastAPI 和 pywebview 不需要跟着大改。
    """

    def __init__(self, task_manager: TaskManager | Any | None = None) -> None:
        self.task_manager = task_manager or TaskManager()

    def start_task(self, options: dict | None = None) -> dict:
        return self.task_manager.start_task(options)

    def stop_task(self) -> dict:
        return self.task_manager.stop_task()

    def get_status(self, refresh_home: bool = True) -> dict:
        return self.task_manager.get_status(refresh_home=refresh_home)

    def get_logs(self, limit: int = 100) -> list[dict]:
        return self.task_manager.get_logs(limit)

    def update_config(self, config, config_path: str | None = None) -> dict:
        return self.task_manager.update_config(config, config_path)

    def shutdown(self) -> None:
        self.task_manager.shutdown()

    def log_runtime_error(self, message: str, source: str = "runtime") -> None:
        self.task_manager.log_runtime_error(message, source=source)
