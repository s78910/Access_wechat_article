from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time
from typing import Any

from src.domain.enums import TaskStatus
from src.services.capture.html_parse_save_service import HtmlParseSaveService
from src.services.runtime.article_detail_diagnostic_service import (
    ArticleDetailDiagnosticService,
    DiagnosticUpdate,
)


class InitialContentStorageDiagnosticService:
    """执行一次“详情捕获 -> 初始 HTML 解析保存”的诊断流程。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        capture_factory: Any,
        db_path: str | Path,
        html_save: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._capture_factory = capture_factory
        self._db_path = Path(db_path)
        self._html_save = html_save or HtmlParseSaveService(now=now)
        self._monotonic = monotonic
        self._now = now

    def run(
        self,
        *,
        on_update: DiagnosticUpdate | None = None,
        skip_collected_records: bool = False,
        store_article_detail: bool = True,
    ) -> dict[str, Any]:
        # “初始内容存储”的业务目标就是写入文章详情，界面只允许锁定开启。
        store_article_detail = True
        started_at = self._monotonic()

        def update(payload: dict[str, Any]) -> None:
            if on_update is not None:
                payload = _with_option_context(
                    payload,
                    skip_collected_records=skip_collected_records,
                    store_article_detail=store_article_detail,
                )
                payload = {
                    "action": "initial-content-storage",
                    "title": "初始内容存储结果",
                    **payload,
                }
                on_update(payload)

        detail = ArticleDetailDiagnosticService(
            config=self._config,
            window_factory=self._window_factory,
            capture_factory=self._capture_factory,
            db_path=self._db_path,
            monotonic=self._monotonic,
            now=self._now,
        ).capture_detail(
            on_update=update,
            action="initial-content-storage",
            title="初始内容存储结果",
            running_message="初始内容存储测试正在执行...",
            failed_prefix="初始内容存储测试失败",
            skip_collected_records=skip_collected_records,
        )

        items = _prepend_option_items(
            _normalize_detail_items(detail.items),
            skip_collected_records=skip_collected_records,
            store_article_detail=store_article_detail,
        )
        if detail.status == "skipped-collected":
            result = _with_option_context(
                _result(
                    ok=True,
                    status=detail.status,
                    message=detail.message,
                    tone=detail.tone,
                    items=items,
                    capture_type=detail.capture_type,
                    total_seconds=_elapsed(self._monotonic, started_at),
                ),
                skip_collected_records=skip_collected_records,
                store_article_detail=store_article_detail,
            )
            update(result)
            return result
        if detail.data is None or not detail.ok:
            result = _with_option_context(
                _result(
                    ok=False,
                    status=detail.status,
                    message=detail.message,
                    tone=detail.tone,
                    items=items,
                    capture_type=detail.capture_type,
                    total_seconds=_elapsed(self._monotonic, started_at),
                ),
                skip_collected_records=skip_collected_records,
                store_article_detail=store_article_detail,
            )
            update(result)
            return result

        items.append(
            {
                "label": "解析 HTML 并存储初始内容",
                "value": "执行中",
                "cells": [
                    _cell("结果", "正在准备 HTML、解析文章详情并写入本地归档"),
                    _cell("捕获类型", detail.capture_type),
                ],
            }
        )
        update(
            _result(
                ok=False,
                status="running",
                message="正在解析 HTML 并存储初始内容...",
                tone="info",
                items=items,
                capture_type=detail.capture_type,
                total_seconds=_elapsed(self._monotonic, started_at),
            )
        )

        step_started = self._monotonic()
        save = self._html_save.save(
            context=detail.data.context,
            target=detail.data.target,
            capture_result=detail.data.capture_result,
            attempt_started_at=detail.data.attempt_started_at,
            duration_seconds=detail.data.capture_duration_seconds,
            request_timeout_seconds=self._config.request.request_timeout_seconds,
        )
        save_elapsed = _elapsed(self._monotonic, step_started)

        if save.status is TaskStatus.SUCCESS and save.data is not None:
            saved = save.data
            items[-1] = {
                "label": "解析 HTML 并存储初始内容",
                "value": _seconds(save_elapsed),
                "cells": [
                    _cell("结果", "已解析并保存初始内容"),
                    _cell("HTML 来源", saved.html_source),
                    _cell("文章ID", saved.article_id),
                    _cell("公众号ID", saved.account_id),
                    _cell("历史ID", saved.history_id),
                    _cell("归档目录", saved.archive_dir),
                    _cell("详情文件", saved.detail_path),
                    _cell(
                        "资源清单",
                        "，".join(str(value) for value in saved.resource_manifest.to_json_values()),
                    ),
                ],
            }
            total_seconds = _elapsed(self._monotonic, started_at)
            items.append(
                {
                    "label": "总耗时",
                    "value": _seconds(total_seconds),
                    "cells": [
                        _cell(
                            "结果",
                            f"初始内容存储完成，capture_type={detail.capture_type}",
                        )
                    ],
                }
            )
            result = _with_option_context(
                _result(
                    ok=True,
                    status="completed",
                    message=f"初始内容存储完成，HTML 来源：{saved.html_source}。",
                    tone="success",
                    items=items,
                    capture_type=detail.capture_type,
                    total_seconds=total_seconds,
                    html_source=saved.html_source,
                    archive_dir=saved.archive_dir,
                    article_id=saved.article_id,
                    account_id=saved.account_id,
                    history_id=saved.history_id,
                    attempt_id=saved.attempt_id,
                    resource_manifest=saved.resource_manifest.to_json_values(),
                ),
                skip_collected_records=skip_collected_records,
                store_article_detail=store_article_detail,
            )
            update(result)
            return result

        error_code = "" if save.error_code is None else str(save.error_code.value)
        items[-1] = {
            "label": "解析 HTML 并存储初始内容",
            "value": _seconds(save_elapsed),
            "cells": [
                _cell("结果", "解析或保存失败"),
                _cell("失败阶段", error_code or "html_save"),
                _cell("失败原因", save.message),
            ],
        }
        result = _with_option_context(
            _result(
                ok=False,
                status="save-failed",
                message=save.message or "初始内容解析保存失败。",
                tone="error",
                items=items,
                capture_type=detail.capture_type,
                total_seconds=_elapsed(self._monotonic, started_at),
            ),
            skip_collected_records=skip_collected_records,
            store_article_detail=store_article_detail,
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
    capture_type: str | None = None,
    total_seconds: float | None = None,
    html_source: str | None = None,
    archive_dir: str | None = None,
    article_id: int | None = None,
    account_id: int | None = None,
    history_id: int | None = None,
    attempt_id: str | None = None,
    resource_manifest: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "action": "initial-content-storage",
        "title": "初始内容存储结果",
        "message": message,
        "tone": tone,
        "items": list(items),
    }
    if capture_type is not None:
        result["captureType"] = capture_type
    if total_seconds is not None:
        result["totalSeconds"] = round(float(total_seconds), 3)
    if html_source is not None:
        result["htmlSource"] = html_source
    if archive_dir is not None:
        result["archiveDir"] = archive_dir
    if article_id is not None:
        result["articleId"] = article_id
    if account_id is not None:
        result["accountId"] = account_id
    if history_id is not None:
        result["historyId"] = history_id
    if attempt_id is not None:
        result["attemptId"] = attempt_id
    if resource_manifest is not None:
        result["resourceManifest"] = list(resource_manifest)
    return result


def _normalize_detail_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        if copied.get("label") == "整理耗时":
            copied["label"] = "详情获取整理耗时"
        normalized.append(copied)
    return normalized


def _with_option_context(
    payload: dict[str, Any],
    *,
    skip_collected_records: bool,
    store_article_detail: bool,
) -> dict[str, Any]:
    result = dict(payload)
    result["items"] = _prepend_option_items(
        list(result.get("items") or []),
        skip_collected_records=skip_collected_records,
        store_article_detail=store_article_detail,
    )
    result["options"] = {
        "skipCollectedRecords": bool(skip_collected_records),
        "storeArticleDetail": bool(store_article_detail),
    }
    return result


def _prepend_option_items(
    items: list[dict[str, Any]],
    *,
    skip_collected_records: bool,
    store_article_detail: bool,
) -> list[dict[str, Any]]:
    option_labels = {"跳过已采集记录", "存储文章详情"}
    remaining = [
        dict(item)
        for item in items
        if str(item.get("label") or "") not in option_labels
    ]
    return [
        {
            "label": "跳过已采集记录",
            "value": "开启" if skip_collected_records else "关闭",
        },
        {
            "label": "存储文章详情",
            "value": "开启（锁定）" if store_article_detail else "关闭",
        },
        *remaining,
    ]


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


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return max(0.0, monotonic() - started_at)


def _seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f} 秒"


__all__ = ["InitialContentStorageDiagnosticService"]
