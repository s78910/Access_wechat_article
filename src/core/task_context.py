from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskContext:
    """一次采集任务的上下文。

    TaskManager 负责任务编排时，可以把这些稳定字段传给 worker，避免各子进程到处读取全局配置。
    """

    run_id: str
    record_limit: int = 1
    selections: dict[str, bool] = field(default_factory=lambda: {"articleDetail": True, "commentInfo": True})
    account_name: str = ""
    storage_root: str = "storages"
    db_path: str = ""

    def to_worker_payload(self) -> dict[str, Any]:
        """转换为 multiprocessing worker 易于接收的普通 dict。"""
        return {
            "run_id": self.run_id,
            "record_limit": max(0, int(self.record_limit or 0)),
            "selections": dict(self.selections),
            "account_name": self.account_name,
            "storage_root": self.storage_root,
            "db_path": self.db_path,
        }
