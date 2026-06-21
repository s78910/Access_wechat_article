from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.app.pywebview_app.webview_api import WebviewApi
from src.config.runtime_config import load_runtime_config
from src.core.config import AppRuntimeConfig
from src.modules.storage.archive_delete_service import ArchiveDeleteService
from src.modules.storage.archive_storage_info import (
    ArchiveStorageInfoResolver,
    default_storage_root_for_db,
    directory_size_bytes,
    format_size_label,
)
from src.modules.storage.sqlite_store import SQLiteStore


def create_app(api: WebviewApi | None = None, runtime_config: AppRuntimeConfig | None = None) -> FastAPI:
    """创建 FastAPI 应用，路由层复用现有 WebviewApi 业务能力。"""
    app_config = runtime_config or load_runtime_config()
    webview_api = api or WebviewApi(runtime_config=app_config, auto_start=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            webview_api.shutdown()

    app = FastAPI(title="Access WeChat Article API", version="2.0.0", lifespan=lifespan)
    app.state.webview_api = webview_api

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status")
    def get_status():
        return parse_api_payload(webview_api.get_status())

    @app.get("/api/task/status")
    def get_task_status():
        return parse_api_payload(webview_api.get_task_status())

    @app.get("/api/task/logs")
    def get_task_logs(limit: int = 100):
        return parse_api_payload(webview_api.get_task_logs(limit))

    @app.get("/api/archive/accounts")
    def list_archive_accounts():
        store = SQLiteStore(app_config.storage.db_path)
        items = [_format_archive_account_item(row) for row in store.list_public_accounts()]
        return {
            "ok": True,
            "status": "ok",
            "items": items,
            "total": len(items),
            "dbPath": str(app_config.storage.db_path),
        }

    @app.get("/api/archive/summary")
    def get_archive_summary():
        store = SQLiteStore(app_config.storage.db_path)
        storage_root = default_storage_root_for_db(app_config.storage.db_path)
        storage_size_bytes = directory_size_bytes(storage_root)
        return {
            "ok": True,
            "status": "ok",
            "accountCount": store.count_public_accounts(),
            "articleCount": store.count_public_articles(),
            "dataType": "JSON",
            "storageSizeBytes": storage_size_bytes,
            "storageSizeLabel": format_size_label(storage_size_bytes),
            "storageRoot": str(storage_root),
            "dbPath": str(app_config.storage.db_path),
        }

    @app.get("/api/history/records")
    def list_history_records(
        page: int = 1,
        pageSize: int = 15,
        keyword: str = "",
        collectType: str = "",
        status: str = "",
        collectDate: str = "",
    ):
        store = SQLiteStore(app_config.storage.db_path)
        safe_page_size = max(1, min(100, int(pageSize)))
        total = store.count_history_records(
            keyword=keyword,
            collect_type=collectType,
            collect_status=status,
            collect_date=collectDate,
        )
        total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(int(page), total_pages))
        offset = (safe_page - 1) * safe_page_size
        rows = store.list_history_records(
            limit=safe_page_size,
            offset=offset,
            keyword=keyword,
            collect_type=collectType,
            collect_status=status,
            collect_date=collectDate,
        )
        archive_info_resolver = ArchiveStorageInfoResolver(default_storage_root_for_db(app_config.storage.db_path))
        return {
            "ok": True,
            "status": "ok",
            "page": safe_page,
            "pageSize": safe_page_size,
            "items": [_format_history_record_item(row, archive_info_resolver) for row in rows],
            "total": total,
            "dbPath": str(app_config.storage.db_path),
        }

    @app.get("/api/history/summary")
    def get_history_summary():
        store = SQLiteStore(app_config.storage.db_path)
        summary = store.get_history_summary()
        total_records = int(summary["total_count"])
        saved_records = int(summary["saved_count"])
        failed_records = int(summary["failed_count"])
        success_rate = round((saved_records / total_records) * 100, 1) if total_records else 0.0
        return {
            "ok": True,
            "status": "ok",
            "totalRecords": total_records,
            "savedRecords": saved_records,
            "failedRecords": failed_records,
            "successRate": success_rate,
            "latestCollectDate": _format_collect_date(summary["latest_collect_time"]),
            "averageDuration": _format_duration_seconds(summary["average_duration"]),
            "trend": [
                {
                    "date": item["date"],
                    "label": _format_trend_label(item["date"]),
                    "count": item["count"],
                }
                for item in summary["trend"]
            ],
            "dbPath": str(app_config.storage.db_path),
        }

    @app.get("/api/archive/accounts/{account_id}/articles")
    def list_archive_account_articles(account_id: int, page: int = 1, pageSize: int = 10):
        store = SQLiteStore(app_config.storage.db_path)
        archive_info_resolver = ArchiveStorageInfoResolver(default_storage_root_for_db(app_config.storage.db_path))
        safe_page_size = max(1, min(100, int(pageSize)))
        total = store.count_public_articles_by_account(account_id)
        total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        safe_page = max(1, min(int(page), total_pages))
        offset = (safe_page - 1) * safe_page_size
        items = [
            _format_archive_article_item(row, archive_info_resolver)
            for row in store.list_public_articles_by_account(account_id, limit=safe_page_size, offset=offset)
        ]
        return {
            "ok": True,
            "status": "ok",
            "accountId": account_id,
            "page": safe_page,
            "pageSize": safe_page_size,
            "items": items,
            "total": total,
            "dbPath": str(app_config.storage.db_path),
        }

    @app.delete("/api/archive/articles")
    def delete_archive_articles(payload: ArchiveArticleDeletePayload):
        delete_service = _create_archive_delete_service(app_config)
        result = delete_service.delete_articles(payload.articleIds)
        response = result.to_dict()
        response["status"] = "ok" if result.ok else "partial-failed"
        return response

    @app.delete("/api/archive/accounts/{account_id}")
    def delete_archive_account(account_id: int):
        delete_service = _create_archive_delete_service(app_config)
        result = delete_service.delete_account(account_id)
        response = result.to_dict()
        response["status"] = "ok" if result.ok else "partial-failed"
        return response

    @app.delete("/api/archive")
    def delete_archive_all():
        delete_service = _create_archive_delete_service(app_config)
        result = delete_service.delete_all()
        response = result.to_dict()
        response["status"] = "ok" if result.ok else "partial-failed"
        return response

    @app.post("/api/task/start")
    def start_task(payload: dict[str, Any] | None = None):
        return parse_api_payload(webview_api.start_task(json.dumps(payload or {}, ensure_ascii=False)))

    @app.post("/api/task/stop")
    def stop_task():
        return parse_api_payload(webview_api.stop_task())

    @app.post("/api/proxy/mitm/start")
    def start_mitm_proxy():
        return parse_api_payload(webview_api.start_mitm_proxy())

    @app.post("/api/proxy/mitm/stop")
    def stop_mitm_proxy():
        return parse_api_payload(webview_api.stop_mitm_proxy())

    @app.post("/api/proxy/system/enable")
    def enable_system_proxy():
        return parse_api_payload(webview_api.enable_system_proxy())

    @app.post("/api/proxy/system/disable")
    def disable_system_proxy():
        return parse_api_payload(webview_api.disable_system_proxy())

    @app.post("/api/config/save")
    def save_runtime_config(payload: dict[str, Any] | None = None):
        return parse_api_payload(webview_api.save_runtime_config(json.dumps(payload or {}, ensure_ascii=False)))

    @app.get("/api/log/current/open")
    def open_current_runtime_log():
        return parse_api_payload(webview_api.open_current_runtime_log())

    @app.get("/api/ca/status")
    def check_ca_certificate():
        return parse_api_payload(webview_api.check_ca_certificate())

    @app.post("/api/ca/install/open")
    def open_ca_install_page():
        return parse_api_payload(webview_api.open_ca_install_page())

    @app.get("/api/ca/mitm/list")
    def list_mitm_ca_certificates():
        return parse_api_payload(webview_api.list_mitm_ca_certificates())

    @app.post("/api/ca/mitm/delete")
    def delete_mitm_ca_certificates(payload: CertificateDeletePayload):
        return parse_api_payload(
            webview_api.delete_mitm_ca_certificates(
                json.dumps({"thumbprints": payload.thumbprints}, ensure_ascii=False)
            )
        )

    @app.post("/api/cache/runtime/clear")
    def clear_runtime_cache():
        return parse_api_payload(webview_api.clear_runtime_cache())

    @app.post("/api/proxy/test")
    def test_proxy_connection():
        return parse_api_payload(webview_api.test_proxy_connection())

    return app


class CertificateDeletePayload(BaseModel):
    thumbprints: list[str] = []


class ArchiveArticleDeletePayload(BaseModel):
    articleIds: list[int] = []


def _create_archive_delete_service(app_config: AppRuntimeConfig) -> ArchiveDeleteService:
    store = SQLiteStore(app_config.storage.db_path)
    return ArchiveDeleteService(
        store=store,
        storage_root=default_storage_root_for_db(app_config.storage.db_path),
    )


def parse_api_payload(raw_payload: str | dict[str, Any]) -> JSONResponse:
    """把 WebviewApi 的 JSON 字符串结果转换成 FastAPI 响应。"""
    if isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        try:
            loaded = json.loads(raw_payload)
            payload = loaded if isinstance(loaded, dict) else {"ok": True, "data": loaded}
        except json.JSONDecodeError:
            payload = {"ok": False, "status": "invalid-json", "message": raw_payload}

    status_code = 200 if payload.get("ok", True) is not False else 400
    if payload.get("status") in {"not-found"}:
        status_code = 404
    return JSONResponse(payload, status_code=status_code)


def _format_archive_account_item(row: dict[str, Any]) -> dict[str, Any]:
    """把 SQLite 下划线字段转成前端页面使用的驼峰字段。"""
    article_count = int(row.get("article_count") or 0)
    return {
        "id": int(row.get("id") or 0),
        "accountName": str(row.get("account_name") or ""),
        "createdTime": str(row.get("created_time") or ""),
        "updatedTime": str(row.get("updated_time") or ""),
        "latestCollectTime": str(row.get("latest_collect_time") or ""),
        "articleCount": article_count,
        "savedCount": int(row.get("saved_count") or 0),
        "failedCount": int(row.get("failed_count") or 0),
        "sizeLabel": f"{article_count} 条",
    }


def _format_archive_article_item(
    row: dict[str, Any],
    archive_info_resolver: ArchiveStorageInfoResolver,
) -> dict[str, Any]:
    """把文章索引字段转成数据档案右侧记录详情使用的结构。"""
    status = str(row.get("collect_status") or "")
    archive_info = archive_info_resolver.resolve_for_row(row)
    return {
        "id": int(row.get("id") or 0),
        "accountId": int(row.get("account_id") or 0),
        "title": str(row.get("article_title") or "未命名文章"),
        "publishedArticleTime": str(row.get("published_article_time") or ""),
        "articleLink": str(row.get("article_link") or ""),
        "recordType": str(row.get("record_type") or ""),
        "collectTime": str(row.get("collect_time") or ""),
        "durationSeconds": float(row.get("duration_seconds") or 0),
        "collectStatus": status,
        "statusLabel": "已保存" if status == "saved" else "失败",
        "archiveDir": str(archive_info.archive_dir) if archive_info.archive_dir else "",
        "archiveDirs": [str(path) for path in archive_info.archive_dirs],
        "sizeBytes": archive_info.size_bytes,
        "sizeLabel": archive_info.size_label,
    }


def _format_history_record_item(
    row: dict[str, Any],
    archive_info_resolver: ArchiveStorageInfoResolver | None = None,
) -> dict[str, Any]:
    """把文章采集索引转成采集历史页面的列表行。"""
    collect_status = str(row.get("collect_status") or "")
    return {
        "id": int(row.get("id") or 0),
        "accountId": int(row.get("account_id") or 0),
        "name": str(row.get("article_title") or ""),
        "account": str(row.get("account_name") or ""),
        "collectType": str(row.get("record_type") or ""),
        "collectTime": str(row.get("collect_time") or ""),
        "recordTime": str(row.get("published_article_time") or ""),
        "duration": _format_duration_seconds(row.get("duration_seconds") or 0),
        "durationSeconds": float(row.get("duration_seconds") or 0),
        "collectStatus": collect_status,
        "status": "成功" if collect_status == "saved" else "失败",
        "articleLink": str(row.get("article_link") or ""),
        "publishedArticleTime": str(row.get("published_article_time") or ""),
        "recordSummary": _build_history_record_summary(row, archive_info_resolver),
    }


def _build_history_record_summary(
    row: dict[str, Any],
    archive_info_resolver: ArchiveStorageInfoResolver | None,
) -> dict[str, Any]:
    """为历史详情卡片生成短摘要；前端不直接读取本地归档路径。"""
    collect_status = str(row.get("collect_status") or "")
    if collect_status != "saved":
        return {
            "kind": "status",
            "items": [],
            "message": f"本次采集未成功保存，当前状态为 {collect_status or 'unknown'}。",
        }

    if archive_info_resolver is None:
        return {"kind": "missing", "items": [], "message": "未配置本地归档解析器，无法读取详情摘要。"}

    archive_info = archive_info_resolver.resolve_for_row(row)
    detail_path = (archive_info.archive_dir / "article_detail.json") if archive_info.archive_dir else None
    if detail_path is None or not detail_path.exists():
        return {"kind": "missing", "items": [], "message": "未找到对应的 article_detail.json。"}

    detail = _read_json_object(detail_path)
    if not detail:
        return {"kind": "missing", "items": [], "message": "article_detail.json 无法读取或格式异常。"}

    items = [
        {"key": key, "label": label, "value": _format_optional_count(detail.get(key))}
        for key, label in (
            ("read_count", "阅读数"),
            ("like_count", "点赞数"),
            ("share_count", "转发数"),
            ("recommend_count", "推荐数"),
            ("comment_count", "留言数"),
            ("audience_count", "听众数"),
        )
        if detail.get(key) is not None
    ]
    if not items:
        return {"kind": "missing", "items": [], "message": "article_detail.json 中暂无可展示的统计指标。"}

    return {"kind": "metrics", "items": items, "message": ""}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _format_optional_count(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value or "")


def _format_duration_seconds(value: Any) -> str:
    """把秒数格式化为 mm:ss.hh，方便列表中紧凑展示采集耗时。"""
    try:
        duration_seconds = max(0.0, float(value or 0))
    except (TypeError, ValueError):
        duration_seconds = 0.0
    minutes = int(duration_seconds // 60)
    seconds = int(duration_seconds % 60)
    hundredths = int((duration_seconds - int(duration_seconds)) * 100)
    return f"{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def _format_collect_date(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _format_trend_label(value: Any) -> str:
    text = str(value or "").strip()
    return text[5:10] if len(text) >= 10 else text
