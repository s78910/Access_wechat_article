from __future__ import annotations

import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config import DEFAULT_DB_PATH, LOG_DIR, PROJECT_ROOT
from src.core.progress_logger import ProgressLogger
# 这些函数是真实实现模块的兼容导出，旧测试和旧调用仍可从 article_capture 导入。
from src.modules.proxy.mitm_capture_waiter import (
    build_capture_ready_message,
    build_mitm_timeout_reason,
    collect_article_capture_report_from_mitm,
    drain_capture_event_queue,
    get_main_html_capture_source,
    is_report_ready_for_article_storage,
    resolve_capture_failure_reason,
    resolve_failure_article_title,
    resolve_mitm_capture_timeout_seconds,
)
# 这些函数是真实实现模块的兼容导出，主流程只直接使用归档和入库记录构造。
from src.modules.storage.article_archive_store import (
    ArticleArchiveError,
    ArticleDetailFetchError,
    build_failed_public_article_record,
    build_local_article_archive,
    build_public_article_record,
    build_sqlite_capture_record,
    CommentFetchError,
    extract_article_detail_stats_from_html,
    extract_article_ip_from_html,
    fetch_article_detail_from_keyed_url,
)
from src.modules.storage.mitm_probe_store import write_current_mitm_target_probe
from src.modules.storage.public_article_store import create_public_article_store
from src.modules.window.article_clicker import find_wechat_home_window
from src.modules.window.home_article_cursor import HomeArticleCandidate, HomeArticleCursor
from src.modules.window.article_window_flow import (
    close_wechat_article_detail_windows,
    open_home_article_for_capture,
    trigger_home_article_open,
)
from src.workers.mitm_worker import put_event


DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storages"
CURRENT_MITM_TARGET_PROBE_PATH = LOG_DIR / "article_capture" / "current_target.json"
DEFAULT_MITM_RESPONSE_INSPECT_SECONDS = 5.0


def run_article_capture_worker(event_queue, config: dict | None = None, capture_event_queue=None) -> None:
    """按主服务任务参数抓取公众号主页文章，并把归档索引写入当前项目数据库。"""
    from src.workers.article_capture_flow import ArticleCaptureDependencies, run_article_capture_flow

    deps = ArticleCaptureDependencies(
        put_event=put_event,
        create_public_article_store=create_public_article_store,
        find_wechat_home_window=find_wechat_home_window,
        home_article_cursor_cls=HomeArticleCursor,
        open_home_article_for_capture=open_home_article_for_capture,
        close_detail_windows=close_wechat_article_detail_windows,
        click_home_article=trigger_home_article_open,
        write_probe=write_current_mitm_target_probe,
        drain_capture_events=drain_capture_event_queue,
        collect_report=collect_article_capture_report_from_mitm,
        resolve_timeout=resolve_mitm_capture_timeout_seconds,
        is_report_ready=is_report_ready_for_article_storage,
        resolve_failure_reason=resolve_capture_failure_reason,
        resolve_failure_title=resolve_failure_article_title,
        build_ready_message=build_capture_ready_message,
        get_capture_source=get_main_html_capture_source,
        build_archive=build_local_article_archive,
        build_record=build_public_article_record,
        build_failed_record=build_failed_public_article_record,
    )
    run_article_capture_flow(event_queue, config, capture_event_queue, deps)


def resolve_target_article_indices(run_options: dict | None) -> list[int]:
    """把 01 指定记录总量转换成主页文章序号；当前阶段至少抓取第一篇。"""
    from src.workers.article_capture_flow import resolve_target_article_indices as _resolve

    return _resolve(run_options)


def put_collection_status_event(event_queue, status: str, message: str, level: str | None = None) -> None:
    from src.workers.article_capture_flow import put_collection_status_event as _put_collection_status_event

    _put_collection_status_event(event_queue, status, message, level)

