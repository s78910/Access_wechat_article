from __future__ import annotations

import time
from typing import Any

from src.workers.mitm_worker import put_event


class ProgressLogger:
    """把任务拆成前端可展示的步骤日志，便于定位采集流程卡在哪一步。"""

    def __init__(
        self,
        event_queue=None,
        source: str = "article_capture",
        sink=None,
        *,
        run_id: str | None = None,
        article_index: int | None = None,
    ) -> None:
        self.event_queue = event_queue
        self.source = source
        self.sink = sink
        self.run_id = run_id
        self.article_index = article_index
        self._started_at = time.perf_counter()

    def info(
        self,
        phase: str,
        message: str,
        *,
        substep: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._emit("INFO", phase, message, substep=substep, status=status, progress=progress, meta=meta)

    def warn(
        self,
        phase: str,
        message: str,
        *,
        substep: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._emit("WARN", phase, message, substep=substep, status=status, progress=progress, meta=meta)

    def success(
        self,
        phase: str,
        message: str,
        *,
        substep: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._emit("SUCCESS", phase, message, substep=substep, status=status, progress=progress, meta=meta)

    def error(
        self,
        phase: str,
        message: str,
        *,
        substep: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._emit("ERROR", phase, message, substep=substep, status=status, progress=progress, meta=meta)

    def _emit(
        self,
        level: str,
        phase: str,
        message: str,
        *,
        substep: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        phase_text = str(phase or "unknown")
        substep_text = str(substep or "").strip()
        body = f"步骤[{phase_text}] {message}"
        duration_ms = max(0, int((time.perf_counter() - self._started_at) * 1000))
        extra = {
            "type": "progress",
            "eventType": "progress",
            "phase": phase_text,
            "substep": substep_text,
            "status": str(status or "").strip() or ("done" if level in {"SUCCESS", "ERROR"} else "running"),
            "progress": self._safe_progress(progress),
            "durationMs": duration_ms,
            "runId": self.run_id,
            "articleIndex": self.article_index,
            "meta": dict(meta or {}),
        }
        if callable(self.sink):
            try:
                self.sink(level, body, **extra)
            except TypeError as exc:
                if "unexpected keyword" not in str(exc):
                    raise
                self.sink(level, body)
            return
        if self.event_queue is None:
            return
        put_event(self.event_queue, level, body, source=self.source, **extra)

    @staticmethod
    def _safe_progress(value: int | None) -> int | None:
        if value is None:
            return None
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return None


__all__ = ["ProgressLogger"]
