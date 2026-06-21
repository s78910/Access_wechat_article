from __future__ import annotations

import time
from multiprocessing.queues import Queue

from src.workers.mitm_worker import put_event


def run_comment_worker(event_queue: Queue, config: dict | None = None) -> None:
    """评论采集 worker 占位，后续用于 appmsg_comment 数据处理。"""
    put_event(event_queue, "INFO", "Comment worker 已就绪，等待接入评论采集逻辑", source="comment")
    while True:
        time.sleep(1)
