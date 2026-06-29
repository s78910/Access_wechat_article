from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from src.core.config import LOG_DIR
from src.core.progress_logger import ProgressLogger
from src.modules.storage.mitm_probe_store import write_current_mitm_target_probe
from src.modules.window.article_clicker import trigger_home_article_open
from src.modules.window.detail_window_manager import close_wechat_article_detail_windows
from src.workers.mitm_worker import put_event


CURRENT_MITM_TARGET_PROBE_PATH = LOG_DIR / "article_capture" / "current_target.json"
DEFAULT_MITM_RESPONSE_INSPECT_SECONDS = 5.0


def open_home_article_for_capture(
    *,
    event_queue,
    config: dict[str, Any],
    article_index: int,
    progress_logger: ProgressLogger,
    target_probe_path: Path | None = None,
    inspect_duration_seconds: float = DEFAULT_MITM_RESPONSE_INSPECT_SECONDS,
    home_window: Any | None = None,
    close_detail_windows: Callable[..., dict[str, Any]] = close_wechat_article_detail_windows,
    click_home_article: Callable[..., dict[str, Any]] = trigger_home_article_open,
    candidate: Any | None = None,
    write_probe: Callable[..., Any] = write_current_mitm_target_probe,
    emit_event: Callable[..., Any] = put_event,
) -> dict[str, Any]:
    """完成单篇文章点击操作，返回后续 MITM 等待需要的标题和点击时间。"""
    target_title = str(getattr(candidate, "title", "") or "").strip()
    click_started_at = time.time()
    _ = close_detail_windows  # 兼容旧依赖注入签名，详情窗口清理由主流程统一调度。
    if not bool(config.get("enable_home_article_click", True)):
        return {"target_title": target_title, "click_started_at": click_started_at, "click_result": {"ok": False}}

    homepage_hwnd = _resolve_homepage_hwnd(home_window)
    if homepage_hwnd <= 0:
        return {
            "target_title": target_title,
            "click_started_at": click_started_at,
            "click_result": {"ok": False, "reason": "wechat_home_window_not_found"},
        }
    progress_logger.info(
        "click",
        f"准备调用主页点击工具打开第 {article_index} 篇文章",
        substep="trigger_home_article_open",
        progress=6,
    )
    probe_path = Path(target_probe_path or config.get("mitm_target_probe_path") or CURRENT_MITM_TARGET_PROBE_PATH)

    def before_article_click(target) -> None:
        nonlocal target_title, click_started_at
        target_title = str(getattr(target, "title", "") or "").strip()
        click_started_at = time.time()
        write_probe(
            probe_path,
            article_index=article_index,
            target_title=target_title,
            inspect_duration_seconds=inspect_duration_seconds,
        )
        progress_logger.info(
            "mitm",
            f"已在点击前写入 MITM 5 秒实时探针，目标标题：{target_title or '未识别'}",
            substep="target_probe_ready",
            progress=8,
            meta={
                "targetTitle": target_title,
                "inspectDurationSeconds": inspect_duration_seconds,
            },
        )

    click_started_at = time.time()
    click_result = click_home_article(
        config,
        article_index,
        home_window=home_window,
        candidate=candidate,
        before_click=before_article_click,
    )
    if click_result.get("ok"):
        target_title = str(click_result.get("target_title") or "")
        click_method = str((click_result.get("click_result") or {}).get("method") or "unknown")
        visible_targets = click_result.get("visible_targets") if isinstance(click_result.get("visible_targets"), list) else []
        progress_logger.success(
            "click",
            "主页点击工具调用完成",
            substep="click_sent",
            progress=12,
            meta={"targetTitle": target_title, "method": click_method, "visibleTargets": visible_targets},
        )
        emit_event(
            event_queue,
            "INFO",
            f"已触发主页第 {article_index} 篇文章点击：{click_result.get('target_title', '')}；method={click_method}",
            source="article_capture",
        )
        if visible_targets:
            target_summary = "；".join(
                f"{item.get('index')}. {item.get('title') or '未识别标题'}"
                for item in visible_targets[:5]
            )
            emit_event(
                event_queue,
                "INFO",
                f"本次点击前 UIA 实际检测到的文章候选：{target_summary}",
                source="article_capture",
            )
        if target_title:
            write_probe(
                probe_path,
                article_index=article_index,
                target_title=target_title,
                inspect_duration_seconds=inspect_duration_seconds,
            )
    else:
        progress_logger.warn(
            "click",
            "主页点击工具未确认完成，继续等待 MITM",
            substep="click_warning",
            progress=12,
            meta={
                "reason": click_result.get("reason", "unknown"),
                "visibleTargets": click_result.get("visible_targets") or [],
            },
        )
        emit_event(
            event_queue,
            "WARN",
            f"主页第 {article_index} 篇文章点击未完成，继续等待 MITM 捕获：{click_result.get('reason', 'unknown')}",
            source="article_capture",
        )

    return {"target_title": target_title, "click_started_at": click_started_at, "click_result": click_result}


def _resolve_homepage_hwnd(home_window: Any | None) -> int:
    try:
        return int(getattr(home_window, "NativeWindowHandle", 0) or 0)
    except Exception:
        return 0


__all__ = [
    "close_wechat_article_detail_windows",
    "open_home_article_for_capture",
    "trigger_home_article_open",
]
