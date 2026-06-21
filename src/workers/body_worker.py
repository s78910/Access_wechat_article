from __future__ import annotations

import time
from multiprocessing.queues import Queue

from src.workers.mitm_worker import put_event


def run_body_worker(event_queue: Queue, config: dict | None = None) -> None:
    """正文获取 worker 入口。

    当前先保留独立进程入口，后续接入正文 HTML、图片、CSS、JS 等资源下载时优先扩展这里。
    """
    _ = config or {}
    put_event(event_queue, "INFO", "Body worker 已就绪，等待接入正文采集逻辑", source="body")
    while True:
        time.sleep(1)
