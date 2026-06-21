from __future__ import annotations

import time
from multiprocessing.queues import Queue

from src.workers.mitm_worker import put_event


def run_winui_worker(event_queue: Queue, config: dict | None = None) -> None:
    """Windows UI 自动化 worker 占位，后续用于控制已打开的微信窗口。"""
    put_event(event_queue, "INFO", "WinUI worker 已就绪，等待接入窗口自动化逻辑", source="winui")
    while True:
        time.sleep(1)
