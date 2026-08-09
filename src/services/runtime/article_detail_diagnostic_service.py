from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from src.domain.enums import CaptureType, TaskStatus
from src.domain.models import ArticleTarget, MitmCaptureResult, TaskContext
from src.modules.window.window_models import BrowserTabInfo
from src.services.capture.single_article_capture_service import SingleCaptureSettings


DiagnosticUpdate = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class ArticleDetailCaptureData:
    context: TaskContext
    target: ArticleTarget
    capture_result: MitmCaptureResult
    attempt_started_at: datetime
    capture_duration_seconds: float
    total_seconds: float
    items: list[dict[str, Any]]


@dataclass(slots=True)
class ArticleDetailCaptureRun:
    ok: bool
    status: str
    message: str
    tone: str
    items: list[dict[str, Any]]
    capture_type: str
    total_seconds: float
    data: ArticleDetailCaptureData | None = None


class ArticleDetailDiagnosticService:
    """执行一次单篇详情获取诊断，只验证窗口 + MITM 捕获，不解析保存文章。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        capture_factory: Any,
        db_path: str | Path,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._capture_factory = capture_factory
        self._db_path = Path(db_path)
        self._monotonic = monotonic
        self._now = now

    def run(self, *, on_update: DiagnosticUpdate | None = None) -> dict[str, Any]:
        capture = self.capture_detail(on_update=on_update)
        result = _result(
            ok=capture.ok,
            status=capture.status,
            message=capture.message,
            tone=capture.tone,
            items=capture.items,
            capture_type=capture.capture_type,
            total_seconds=capture.total_seconds,
        )
        if on_update is not None:
            on_update(result)
        return result

    def capture_detail(
        self,
        *,
        on_update: DiagnosticUpdate | None = None,
        action: str = "single-article-detail",
        title: str = "详情获取结果",
        running_message: str = "单篇文章详情获取正在执行...",
        failed_prefix: str = "单篇文章详情获取失败",
    ) -> ArticleDetailCaptureRun:
        started_at = self._monotonic()
        items: list[dict[str, Any]] = []

        def emit(label: str, value: Any, cells: list[dict[str, str]] | None = None) -> None:
            item: dict[str, Any] = {"label": str(label), "value": str(value)}
            if cells:
                item["cells"] = cells
            items.append(item)
            if on_update is not None:
                on_update(
                    _result(
                        ok=False,
                        status="running",
                        message=running_message,
                        tone="info",
                        items=items,
                        action=action,
                        title=title,
                    )
                )

        attempt = None
        tabs = None
        home_window = None
        article_tab: BrowserTabInfo | Any | None = None
        tab_closed = False
        attempt_finished = False
        capture_started_at: datetime | None = None
        capture_started_monotonic: float | None = None
        settings = SingleCaptureSettings.from_app_config(self._config)
        task_id = f"diagnostic-detail-{uuid4().hex[:12]}"
        attempt_id = f"{task_id}-attempt-001"
        context = TaskContext(
            task_id=task_id,
            proxy_lease_id=f"{task_id}-lease",
            db_path=self._db_path,
            storage_root=Path(self._config.storage.article_storage_root),
            temp_dir=Path(self._config.storage.temp_dir) / task_id,
            started_at=self._now(),
        )

        try:
            step_started = self._monotonic()
            reader = self._window_factory.create_reader()
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
                use_article_probe=self._config.window.home_find_use_article_probe,
            )
            guard = self._window_factory.create_home_guard()
            guard.activate(home_window)
            home_info = self._window_factory.create_home_reader().read(home_window)
            cursor = self._window_factory.create_cursor(
                reader=reader,
                account_name=_safe_attr(home_info, "account_name", ""),
            )
            visible_targets = cursor.refresh_visible(home_window)
            target = cursor.next_candidate(home_window)
            if target is None:
                emit(
                    "窗口定位与首篇候选选择",
                    f"失败，当前可见文章数：{len(visible_targets)}",
                )
                return ArticleDetailCaptureRun(
                    ok=False,
                    status="no-candidate",
                    message="当前主页没有可点击的候选文章。",
                    tone="warning",
                    items=items,
                    capture_type=CaptureType.NONE.value,
                    total_seconds=_elapsed(self._monotonic, started_at),
                )
            refreshed_target = cursor.refresh_target(home_window, target)
            guard.ensure_target_clickable(home_window, refreshed_target)
            emit(
                "窗口定位与首篇候选选择",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", "已定位主页并选中首篇候选文章"),
                    _cell("公众号", _safe_attr(home_info, "account_name", "")),
                    _cell("候选文章", refreshed_target.title),
                ],
            )

            tabs = self._window_factory.create_tab_service()
            clicker = self._window_factory.create_clicker()
            baseline = tabs.capture_baseline()

            step_started = self._monotonic()
            capture_started_at = self._now()
            capture_started_monotonic = step_started
            process_control = self._capture_factory.create_process_control()
            attempt = process_control.start_attempt(
                task_id=context.task_id,
                attempt_id=attempt_id,
                proxy_lease_id=context.proxy_lease_id,
                proxy_address=settings.proxy_address,
                capture_config=settings.capture_config,
            )
            emit(
                "启动单篇 MITM 捕获",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", "已创建 MITM 子进程并发送 START_CAPTURE"),
                ],
            )

            step_started = self._monotonic()
            attempt.wait_ready(timeout_seconds=settings.ready_timeout_seconds)
            emit(
                "MITM 子进程 READY",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", "MITM 已进入 READY，可以点击文章"),
                ],
            )

            step_started = self._monotonic()
            click_result = clicker.click(refreshed_target)
            article_tab = tabs.wait_for_opened_article_tab(
                baseline=baseline,
                timeout_seconds=settings.title_timeout_seconds,
                poll_interval_seconds=settings.title_poll_interval_seconds,
                stable_delay_seconds=settings.title_stable_delay_seconds,
            )
            emit(
                "点击文章并确认详情页打开",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", "已检测到非临时文章标签"),
                    _cell("检测方式", "opened_non_placeholder_tab"),
                    _cell("点击方式", _safe_attr(click_result, "method", "")),
                    _cell("检测到的标签名", _safe_attr(article_tab, "title", "")),
                ],
            )

            step_started = self._monotonic()
            tabs.close_article_tab(
                article_tab,
                home_window_handle=home_window.handle,
            )
            tab_closed = True
            emit(
                "关闭文章标签",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", "文章标签已关闭并尝试恢复主页焦点"),
                ],
            )

            step_started = self._monotonic()
            capture_result = attempt.stop_capture(timeout_seconds=settings.result_timeout_seconds)
            attempt_finished = True
            capture_type = _capture_type_value(capture_result)
            _append_capture_event_items(
                items,
                capture_result,
            )
            emit(
                "MITM 子进程返回结果",
                _seconds(_elapsed(self._monotonic, step_started)),
                [
                    _cell("结果", f"status={_enum_value(capture_result.status)}，capture_type={capture_type}"),
                ],
            )

            total_seconds = _elapsed(self._monotonic, started_at)
            capture_duration_seconds = (
                _elapsed(self._monotonic, capture_started_monotonic)
                if capture_started_monotonic is not None
                else total_seconds
            )
            items.append(
                {
                    "label": "整理耗时",
                    "value": _seconds(total_seconds),
                    "cells": [_cell("结果", f"详情获取完成，capture_type={capture_type}")],
                }
            )
            ok = (
                capture_result.status is TaskStatus.SUCCESS
                and capture_result.capture_type is not CaptureType.NONE
            )
            return ArticleDetailCaptureRun(
                ok=ok,
                status="completed" if ok else "capture-empty",
                message=(
                    f"单篇文章详情获取完成，捕获类型：{capture_type}。"
                    if ok
                    else capture_result.error_message or "未捕获到 HTML 或 reference。"
                ),
                tone="success" if ok else "error",
                items=items,
                capture_type=capture_type,
                total_seconds=total_seconds,
                data=(
                    ArticleDetailCaptureData(
                        context=context,
                        target=refreshed_target,
                        capture_result=capture_result,
                        attempt_started_at=capture_started_at or context.started_at,
                        capture_duration_seconds=capture_duration_seconds,
                        total_seconds=total_seconds,
                        items=list(items),
                    )
                    if ok
                    else None
                ),
            )
        except Exception as exc:
            if attempt is not None and not attempt_finished:
                try:
                    attempt.cancel()
                except Exception:
                    pass
            failed_items = [*items, {"label": "失败原因", "value": str(exc)}]
            capture_result = getattr(exc, "result", None)
            if isinstance(capture_result, MitmCaptureResult):
                _append_capture_event_items(
                    failed_items,
                    capture_result,
                )
                failed_items.append(
                    {
                        "label": "MITM 子进程返回结果",
                        "value": "失败",
                        "cells": [
                            _cell("结果", f"status={_enum_value(capture_result.status)}，capture_type={_capture_type_value(capture_result)}"),
                            _cell("失败阶段", capture_result.error_stage),
                            _cell("失败原因", capture_result.error_message),
                        ],
                    }
                )
            return ArticleDetailCaptureRun(
                ok=False,
                status="failed",
                message=f"{failed_prefix}：{exc}",
                tone="error",
                items=failed_items,
                capture_type=(
                    _capture_type_value(capture_result)
                    if isinstance(capture_result, MitmCaptureResult)
                    else CaptureType.NONE.value
                ),
                total_seconds=_elapsed(self._monotonic, started_at),
            )
        finally:
            if tabs is not None and home_window is not None and article_tab is not None and not tab_closed:
                try:
                    tabs.close_article_tab(article_tab, home_window_handle=home_window.handle)
                except Exception:
                    pass


def _append_capture_event_items(
    items: list[dict[str, Any]],
    capture_result: MitmCaptureResult,
) -> None:
    for event in capture_result.capture_events:
        label = str(event.get("name") or "MITM 数据获取")
        elapsed_seconds = _coerce_float(event.get("elapsed_seconds"))
        capture_type = str(event.get("capture_type_after_event") or "").strip()
        cells = [
            _cell("结果", event.get("result", "已记录 MITM 数据获取事件")),
        ]
        if capture_type:
            cells.insert(1, _cell("阶段捕获类型", capture_type))
        items.append(
            {
                "label": f"MITM 数据获取：{label}",
                "value": _seconds(elapsed_seconds) if elapsed_seconds is not None else "已记录",
                "cells": cells,
            }
        )


def _cell(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": _format_value(value)}


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "无"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return "，".join(_format_value(item) for item in value) if value else "无"
    return str(value)


def _enum_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def _coerce_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result(
    *,
    ok: bool,
    status: str,
    message: str,
    tone: str,
    items: list[dict[str, Any]],
    action: str = "single-article-detail",
    title: str = "详情获取结果",
    capture_type: str | None = None,
    total_seconds: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "action": action,
        "title": title,
        "message": message,
        "tone": tone,
        "items": list(items),
    }
    if capture_type is not None:
        result["captureType"] = capture_type
    if total_seconds is not None:
        result["totalSeconds"] = round(float(total_seconds), 3)
    return result


def _capture_type_value(capture_result: MitmCaptureResult) -> str:
    value = capture_result.capture_type
    return value.value if hasattr(value, "value") else str(value)


def _safe_attr(value: Any, name: str, fallback: Any = "") -> Any:
    try:
        result = getattr(value, name)
    except Exception:
        return fallback
    return fallback if result is None else result


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return max(0.0, monotonic() - started_at)


def _seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f} 秒"


__all__ = ["ArticleDetailDiagnosticService"]
