from __future__ import annotations

from typing import Any

from src.core.task_manager import TaskManager


class ProxyService:
    """代理相关操作入口。

    MITM 监听和系统代理属于高影响系统操作，单独放在这里，方便后续统一加日志、
    权限检查、状态提示或安全确认。
    """

    def __init__(self, task_manager: TaskManager | Any | None = None) -> None:
        self.task_manager = task_manager or TaskManager()

    def start_mitm_proxy(self) -> dict:
        return self.task_manager.start_mitm_proxy()

    def stop_mitm_proxy(self) -> dict:
        return self.task_manager.stop_mitm_proxy()

    def enable_system_proxy(self) -> dict:
        return self.task_manager.enable_system_proxy()

    def disable_system_proxy(self) -> dict:
        return self.task_manager.disable_system_proxy()
