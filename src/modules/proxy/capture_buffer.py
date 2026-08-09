from __future__ import annotations

from threading import Lock
import time
from typing import Any, Mapping

from src.domain.models import MitmCaptureResult


class CaptureBuffer:
    """保存一次采集尝试的 MITM 回调结果。

    该对象只在当前 MITM 子进程内使用。reference 是兜底证据，不能让捕获
    提前结束；只有主进程发出 STOP_CAPTURE 后，调用 ``freeze`` 才确定结果。
    """

    def __init__(self, *, task_id: str, attempt_id: str) -> None:
        if not task_id.strip() or not attempt_id.strip():
            raise ValueError("task_id 和 attempt_id 不能为空")
        self._task_id = task_id
        self._attempt_id = attempt_id
        self._reference: dict[str, Any] | None = None
        self._html: str | None = None
        self._reference_summary: dict[str, Any] = {}
        self._html_summary: dict[str, Any] = {}
        self._started_at = time.monotonic()
        self._capture_events: list[dict[str, Any]] = []
        self._frozen_result: MitmCaptureResult | None = None
        self._lock = Lock()

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @property
    def frozen(self) -> bool:
        with self._lock:
            return self._frozen_result is not None

    @property
    def has_reference(self) -> bool:
        with self._lock:
            return self._reference is not None

    @property
    def has_html(self) -> bool:
        with self._lock:
            return self._html is not None

    @property
    def capture_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(event) for event in self._capture_events)

    def record_reference(
        self,
        reference: Mapping[str, Any],
        *,
        request_summary: Mapping[str, Any] | None = None,
    ) -> bool:
        """记录第一次有效 reference；已冻结或已有值时不覆盖。"""
        data = dict(reference)
        if not str(data.get("url", "")).strip():
            return False
        with self._lock:
            if self._frozen_result is not None or self._reference is not None:
                return False
            self._reference = data
            self._reference_summary = dict(request_summary or {})
            self._capture_events.append(
                {
                    "name": "捕获 reference",
                    "elapsed_seconds": _elapsed_since(self._started_at),
                    "result": "已得到 reference，继续等待 HTML",
                    "capture_type_after_event": "reference",
                }
            )
            return True

    def record_html(
        self,
        html: str,
        *,
        request_summary: Mapping[str, Any] | None = None,
    ) -> bool:
        """记录第一次有效 HTML；HTML 会在最终结果中覆盖 capture_type。"""
        content = str(html or "")
        if not content.strip():
            return False
        with self._lock:
            if self._frozen_result is not None or self._html is not None:
                return False
            had_reference = self._reference is not None
            self._html = content
            self._html_summary = dict(request_summary or {})
            self._capture_events.append(
                {
                    "name": "捕获 HTML",
                    "elapsed_seconds": _elapsed_since(self._started_at),
                    "result": "已得到 HTML，最终捕获类型升级为 html" if had_reference else "已得到 HTML",
                    "capture_type_after_event": "html",
                }
            )
            return True

    def freeze(self) -> MitmCaptureResult:
        """冻结本次捕获并返回稳定结果；重复调用返回同一个对象。"""
        with self._lock:
            if self._frozen_result is not None:
                return self._frozen_result

            if self._html is not None or self._reference is not None:
                summary = self._html_summary if self._html is not None else self._reference_summary
                self._frozen_result = MitmCaptureResult.success(
                    task_id=self._task_id,
                    attempt_id=self._attempt_id,
                    html=self._html,
                    reference=self._reference,
                    request_summary=summary,
                    capture_events=tuple(self._capture_events),
                )
            else:
                self._frozen_result = MitmCaptureResult.failed(
                    task_id=self._task_id,
                    attempt_id=self._attempt_id,
                    error_stage="mitm_capture",
                    error_message="文章窗口已关闭，但未捕获到 HTML 或 reference",
                    capture_events=tuple(self._capture_events),
                )
            return self._frozen_result


def _elapsed_since(started_at: float) -> float:
    return round(max(0.0, time.monotonic() - started_at), 3)
