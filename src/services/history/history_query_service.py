from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.storage.repositories.fetch_history_repository import FetchHistoryRepository
from src.storage.sqlite.connection import sqlite_connection


_TASK_TYPE_LABELS = {
    "article_capture": "文章详情",
    "comment_fetch": "评论信息",
    "offline_cache": "离线缓存",
}

_RESOURCE_TYPE_LABELS = {
    "article_detail": "文章详情",
    "origin_html": "原始 HTML",
    "comment_detail": "评论信息",
    "offline_html": "离线页面",
}

_ERROR_STAGE_LABELS = {
    "window_detection": "窗口检测",
    "mitm_capture": "MITM 捕获",
    "reference_request": "引用请求",
    "article_parse": "文章解析",
    "article_save": "文章保存",
    "comment_fetch": "评论采集",
    "offline_cache": "离线缓存",
}


class HistoryQueryService:
    """将采集历史仓储结果转换为前端需要的只读视图。"""

    def __init__(
        self,
        database_path: str | Path,
        *,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self._today_provider = today_provider

    def list_records(
        self,
        *,
        page: int = 1,
        page_size: int = 15,
        keyword: str = "",
        collect_type: str = "",
        status: str = "",
        collect_date: str = "",
        collect_start_date: str = "",
        collect_end_date: str = "",
    ) -> dict[str, Any]:
        with sqlite_connection(self.database_path, write=False) as connection:
            result = FetchHistoryRepository(connection).list_page(
                page=page,
                page_size=page_size,
                keyword=keyword,
                task_type=self._task_type_value(collect_type),
                status=self._status_value(status),
                collect_date=collect_date,
                collect_start_date=collect_start_date,
                collect_end_date=collect_end_date,
            )
            items = [self._record_item(row) for row in result.rows]
        return {
            "ok": True,
            "status": "ok",
            "page": result.page,
            "pageSize": result.page_size,
            "items": items,
            "total": result.total,
            "dbPath": str(self.database_path),
        }

    def get_summary(self) -> dict[str, Any]:
        end_date = self._today_provider()
        start_date = end_date - timedelta(days=6)
        with sqlite_connection(self.database_path, write=False) as connection:
            repository = FetchHistoryRepository(connection)
            row = repository.read_summary()
            daily_counts = repository.read_daily_counts(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

        total = int(row["total_count"] or 0)
        successful = int(row["success_count"] or 0)
        failed = int(row["failed_count"] or 0)
        trend = []
        for offset in range(7):
            current_date = start_date + timedelta(days=offset)
            value = current_date.isoformat()
            trend.append(
                {
                    "date": value,
                    "label": value,
                    "count": int(daily_counts.get(value, 0)),
                }
            )

        latest_collect_date = str(row["latest_collect_time"] or "").strip()[:10]
        return {
            "ok": True,
            "status": "ok",
            "totalRecords": total,
            "successfulRecords": successful,
            # 保留旧字段，避免尚未更新的调用方读取失败。
            "savedRecords": successful,
            "failedRecords": failed,
            "successRate": round(successful / total * 100, 1) if total else 0.0,
            "latestCollectDate": latest_collect_date,
            "collectedArticleCount": int(row["collected_article_count"] or 0),
            "averageDuration": self._format_duration(row["average_duration"] or 0),
            "trend": trend,
            "dbPath": str(self.database_path),
        }

    def list_suggestions(self, *, keyword: str = "", limit: int = 20) -> dict[str, Any]:
        with sqlite_connection(self.database_path, write=False) as connection:
            items = FetchHistoryRepository(connection).list_suggestions(
                keyword=keyword,
                limit=limit,
            )
        return {
            "ok": True,
            "status": "ok",
            "items": items,
            "total": len(items),
            "dbPath": str(self.database_path),
        }

    def _record_item(self, row: Any) -> dict[str, Any]:
        task_type = str(row["task_type"] or "")
        raw_status = str(row["status"] or "")
        title = str(row["target_title"] or row["article_title"] or "")
        account = str(row["target_account_name"] or row["account_name"] or "")
        link = str(row["target_link"] or row["article_link"] or "")
        resource_types = self._parse_resource_types(row["resource_types_json"])
        resource_labels = [self._resource_type_label(item) for item in resource_types]
        error_stage = str(row["error_stage"] or "")
        error_message = str(row["error_message"] or "")
        status_label = "成功" if raw_status == "success" else "失败"

        if raw_status == "failed":
            summary_items = []
            if error_stage:
                summary_items.append(
                    {
                        "key": "error_stage",
                        "label": "失败阶段",
                        "value": self._error_stage_label(error_stage),
                    }
                )
            summary_message = error_message or "采集失败，未记录具体原因。"
            summary_kind = "status"
        else:
            summary_items = [
                {"key": item, "label": "资源类型", "value": label}
                for item, label in zip(resource_types, resource_labels, strict=True)
            ]
            summary_message = "本次采集已成功完成。"
            summary_kind = "metrics"

        started_time = str(row["started_time"] or "")
        published_time = str(row["published_article_time"] or "")
        return {
            "id": int(row["id"]),
            "articleId": int(row["article_id"] or 0),
            "accountId": int(row["account_id"] or 0),
            "name": title,
            "account": account,
            "collectType": self._task_type_label(task_type),
            "collectTime": started_time,
            "recordTime": published_time,
            "startedTime": started_time,
            "finishedTime": str(row["finished_time"] or ""),
            "duration": self._format_duration(row["duration_seconds"] or 0),
            "durationSeconds": float(row["duration_seconds"] or 0),
            "collectStatus": raw_status,
            "status": status_label,
            "articleLink": link,
            "publishedArticleTime": published_time,
            "resourceTypes": resource_types,
            "resourceTypeLabels": resource_labels,
            "errorStage": error_stage,
            "errorStageLabel": self._error_stage_label(error_stage),
            "errorMessage": error_message,
            "outputDir": str(row["output_dir"] or ""),
            "recordSummary": {
                "kind": summary_kind,
                "items": summary_items,
                "message": summary_message,
            },
        }

    def _parse_resource_types(self, value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    def _task_type_label(self, value: str) -> str:
        return _TASK_TYPE_LABELS.get(value, value or "未知任务")

    def _task_type_value(self, value: str) -> str:
        normalized = value.strip()
        labels = {label: raw for raw, label in _TASK_TYPE_LABELS.items()}
        return labels.get(normalized, normalized)

    def _status_value(self, value: str) -> str:
        normalized = value.strip()
        return {
            "saved": "success",
            "成功": "success",
            "失败": "failed",
        }.get(normalized, normalized)

    def _resource_type_label(self, value: str) -> str:
        return _RESOURCE_TYPE_LABELS.get(value, value)

    def _error_stage_label(self, value: str) -> str:
        return _ERROR_STAGE_LABELS.get(value, value or "-")

    def _format_duration(self, seconds: Any) -> str:
        value = max(0, int(float(seconds or 0)))
        minutes, second = divmod(value, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02d}:{minute:02d}:{second:02d}"
