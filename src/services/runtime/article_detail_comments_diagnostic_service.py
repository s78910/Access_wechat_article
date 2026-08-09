from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from src.services.capture.comment_process_control_service import (
    CommentProcessControlService,
    CommentProcessError,
)
from src.services.runtime.article_detail_diagnostic_service import DiagnosticUpdate
from src.services.runtime.initial_content_storage_diagnostic_service import (
    InitialContentStorageDiagnosticService,
)


class ArticleDetailCommentsDiagnosticService:
    """执行“详情获取 -> 初始内容存储 -> 评论子进程采集”的诊断流程。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        capture_factory: Any,
        db_path: str | Path,
        comment_process_control: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._capture_factory = capture_factory
        self._db_path = Path(db_path)
        self._comment_process_control = comment_process_control or CommentProcessControlService()
        self._monotonic = monotonic
        self._now = now

    def run(self, *, on_update: DiagnosticUpdate | None = None) -> dict[str, Any]:
        started_at = self._monotonic()

        def update(payload: dict[str, Any]) -> None:
            if on_update is not None:
                on_update(
                    {
                        **payload,
                        "action": "article-detail-comments",
                        "title": "详情评论结果",
                    }
                )

        initial = InitialContentStorageDiagnosticService(
            config=self._config,
            window_factory=self._window_factory,
            capture_factory=self._capture_factory,
            db_path=self._db_path,
            monotonic=self._monotonic,
            now=self._now,
        ).run(on_update=update)

        items = _normalize_initial_items(initial.get("items", []))
        if not bool(initial.get("ok")):
            result = _result(
                ok=False,
                status=str(initial.get("status") or "initial-storage-failed"),
                message=str(initial.get("message") or "初始内容存储失败，未启动评论采集。"),
                tone=str(initial.get("tone") or "error"),
                items=items,
                total_seconds=_elapsed(self._monotonic, started_at),
            )
            update(result)
            return result

        task_id = f"diagnostic-comments-{uuid4().hex[:12]}"
        attempt_id = f"{task_id}-attempt-001"
        article_directory = Path(self._config.storage.article_storage_root) / str(initial["archiveDir"])
        payload = {
            "proxy_lease_id": f"{task_id}-comment",
            "db_path": str(self._db_path),
            "storage_root": str(self._config.storage.article_storage_root),
            "temp_dir": str(Path(self._config.storage.temp_dir) / task_id),
            "started_at": self._now().isoformat(),
            "article_id": int(initial["articleId"]),
            "account_id": int(initial["accountId"]),
            "history_id": int(initial.get("historyId") or 0),
            "archive_dir": str(initial["archiveDir"]),
            "article_directory": str(article_directory),
            "html_source": str(initial.get("htmlSource") or ""),
            "resource_manifest": list(initial.get("resourceManifest") or []),
            "timeout_seconds": float(self._config.comment.request_timeout_seconds),
            "page_interval_seconds": float(self._config.comment.page_interval_seconds),
            "max_pages": int(self._config.comment.max_pages),
        }

        attempt = None
        try:
            step_started = self._monotonic()
            attempt = self._comment_process_control.start(
                task_id=task_id,
                attempt_id=attempt_id,
                payload=payload,
            )
            items.append(
                {
                    "label": "启动评论采集子进程",
                    "value": _seconds(_elapsed(self._monotonic, step_started)),
                    "cells": [
                        _cell("结果", "已创建评论采集子进程"),
                        _cell("评论文件", "comments/final.json"),
                    ],
                }
            )
            update(
                _result(
                    ok=False,
                    status="running",
                    message="评论采集子进程已启动，正在等待 READY...",
                    tone="info",
                    items=items,
                    total_seconds=_elapsed(self._monotonic, started_at),
                )
            )

            step_started = self._monotonic()
            ready_payload = attempt.wait_ready(timeout_seconds=5.0)
            items.append(
                {
                    "label": "评论子进程 READY",
                    "value": _seconds(_elapsed(self._monotonic, step_started)),
                    "cells": [
                        _cell("结果", "评论子进程已就绪"),
                        _cell("文章ID", ready_payload.get("article_id")),
                        _cell("归档目录", ready_payload.get("archive_dir")),
                    ],
                }
            )
            update(
                _result(
                    ok=False,
                    status="running",
                    message="评论子进程正在读取 origin 并采集评论...",
                    tone="info",
                    items=items,
                    total_seconds=_elapsed(self._monotonic, started_at),
                )
            )

            def on_progress(event: dict[str, Any]) -> None:
                items.append(_event_item(event))
                update(
                    _result(
                        ok=False,
                        status="running",
                        message=str(event.get("result") or "评论子进程正在执行..."),
                        tone="info",
                        items=items,
                        total_seconds=_elapsed(self._monotonic, started_at),
                    )
                )

            step_started = self._monotonic()
            comment_result = attempt.wait_result(
                timeout_seconds=_comment_result_timeout_seconds(self._config),
                on_progress=on_progress,
            )
            status = str(comment_result.get("status") or "")
            ok = status == "success"
            skipped = status == "skipped"
            items.append(
                {
                    "label": "评论子进程返回结果",
                    "value": _seconds(_elapsed(self._monotonic, step_started)),
                    "cells": [
                        _cell("结果", status or "unknown"),
                        _cell("HTML 评论数", comment_result.get("html_comment_count")),
                        _cell("评论数", comment_result.get("comment_count")),
                        _cell("回复数", comment_result.get("reply_count")),
                        _cell("页数", comment_result.get("page_count")),
                        _cell("停止原因", comment_result.get("stop_reason")),
                    ],
                }
            )
            total_seconds = _elapsed(self._monotonic, started_at)
            items.append(
                {
                    "label": "总耗时",
                    "value": _seconds(total_seconds),
                    "cells": [
                        _cell(
                            "结果",
                            "详情评论流程完成"
                            if ok
                            else ("无评论参数，已跳过采集" if skipped else "详情评论流程未成功"),
                        )
                    ],
                }
            )
            result = _result(
                ok=ok,
                status="completed" if ok else ("skipped" if skipped else "failed"),
                message=_final_message(comment_result, ok=ok, skipped=skipped),
                tone="success" if ok else ("warning" if skipped else "error"),
                items=items,
                total_seconds=total_seconds,
                comment_result=comment_result,
            )
            update(result)
            return result
        except Exception as exc:
            if attempt is not None:
                try:
                    attempt.cancel()
                except Exception:
                    pass
            comment_result = exc.result if isinstance(exc, CommentProcessError) else None
            items.append(
                {
                    "label": "评论采集失败",
                    "value": str(exc),
                    "cells": [
                        _cell("失败原因", str(exc)),
                        _cell("子进程状态", _safe_mapping_value(comment_result, "status")),
                    ],
                }
            )
            result = _result(
                ok=False,
                status="failed",
                message=f"详情评论流程失败：{exc}",
                tone="error",
                items=items,
                total_seconds=_elapsed(self._monotonic, started_at),
                comment_result=comment_result if isinstance(comment_result, dict) else None,
            )
            update(result)
            return result


def _result(
    *,
    ok: bool,
    status: str,
    message: str,
    tone: str,
    items: list[dict[str, Any]],
    total_seconds: float | None = None,
    comment_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "action": "article-detail-comments",
        "title": "详情评论结果",
        "message": message,
        "tone": tone,
        "items": list(items),
    }
    if total_seconds is not None:
        result["totalSeconds"] = round(float(total_seconds), 3)
    if comment_result:
        result["htmlCommentCount"] = _safe_int(comment_result.get("html_comment_count"))
        result["commentCount"] = _safe_int(comment_result.get("comment_count"))
        result["replyCount"] = _safe_int(comment_result.get("reply_count"))
        result["commentPageCount"] = _safe_int(comment_result.get("page_count"))
        result["commentPath"] = str(comment_result.get("comment_path") or "")
        result["commentAssetCount"] = _safe_int(comment_result.get("asset_count"))
        result["commentAssetDir"] = str(comment_result.get("asset_dir") or "")
    return result


def _normalize_initial_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, Mapping):
            continue
        copied = dict(item)
        if copied.get("label") == "总耗时":
            copied["label"] = "初始内容存储总耗时"
        normalized.append(copied)
    return normalized


def _event_item(event: Mapping[str, Any]) -> dict[str, Any]:
    details = event.get("details")
    cells = [_cell("结果", event.get("result"))]
    if isinstance(details, Mapping):
        for key, value in details.items():
            cells.append(_cell(_detail_label(str(key)), value))
    return {
        "label": str(event.get("name") or "评论子进程步骤"),
        "value": _seconds(float(event.get("elapsed_seconds") or 0)),
        "cells": cells,
    }


def _comment_result_timeout_seconds(config: Any) -> float:
    timeout = max(1.0, float(config.comment.request_timeout_seconds))
    pages = max(1, int(config.comment.max_pages))
    interval = max(0.0, float(config.comment.page_interval_seconds))
    # 评论分页和回复都可能发起网络请求，这里给诊断子进程留出可回收的硬上限。
    return max(30.0, timeout * (pages + 2) + interval * pages + 15.0)


def _final_message(comment_result: Mapping[str, Any], *, ok: bool, skipped: bool) -> str:
    if ok:
        if str(comment_result.get("stop_reason") or "").startswith("html_comment_count_"):
            return "详情评论完成：HTML 未发现可采集评论，未发起评论接口请求。"
        return (
            "详情评论完成："
            f"评论 {comment_result.get('comment_count', 0)} 条，"
            f"回复 {comment_result.get('reply_count', 0)} 条。"
        )
    if skipped:
        return str(comment_result.get("message") or "评论参数不足，已跳过评论采集。")
    return str(comment_result.get("message") or "评论采集失败。")


def _detail_label(key: str) -> str:
    return {
        "required_parameter_count": "必要参数数",
        "html_comment_count": "HTML 评论数",
        "comment_count": "评论数",
        "reply_count": "回复数",
        "page_count": "页数",
        "stop_reason": "停止原因",
        "comment_path": "评论文件",
        "history_id": "历史ID",
    }.get(key, key)


def _safe_mapping_value(value: Any, key: str) -> str:
    return str(value.get(key) or "") if isinstance(value, Mapping) else ""


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cell(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": _format_value(value)}


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "无"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return max(0.0, monotonic() - started_at)


def _seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f} 秒"


__all__ = ["ArticleDetailCommentsDiagnosticService"]
