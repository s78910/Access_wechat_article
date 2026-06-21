from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.core.config import DEFAULT_DB_PATH, LOG_DIR, PROJECT_ROOT
from src.core.progress_logger import ProgressLogger


DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storages"
CURRENT_MITM_TARGET_PROBE_PATH = LOG_DIR / "article_capture" / "current_target.json"
DEFAULT_MITM_RESPONSE_INSPECT_SECONDS = 5.0
DEFAULT_HOME_CANDIDATE_WAIT_TIMEOUT_SECONDS = 300.0
DEFAULT_HOME_CANDIDATE_WAIT_INTERVAL_SECONDS = 2.0
CLICK_FAILURE_REASONS_WITHOUT_REQUEST = {
    "wechat_home_window_not_found",
    "article_click_target_not_found",
    "article_index_out_of_range",
    "article_click_failed",
}


@dataclass(frozen=True)
class ArticleCaptureDependencies:
    put_event: Callable[..., Any]
    create_public_article_store: Callable[[Path], Any]
    find_wechat_home_window: Callable[[], Any]
    home_article_cursor_cls: type
    open_home_article_for_capture: Callable[..., dict[str, Any]]
    close_detail_windows: Callable[..., dict[str, Any]]
    click_home_article: Callable[..., dict[str, Any]]
    write_probe: Callable[..., Any]
    drain_capture_events: Callable[..., int]
    collect_report: Callable[..., dict[str, Any]]
    resolve_timeout: Callable[[dict], float]
    is_report_ready: Callable[[dict[str, Any]], bool]
    resolve_failure_reason: Callable[[dict[str, Any]], str]
    resolve_failure_title: Callable[[dict[str, Any], str, int], str]
    build_ready_message: Callable[[dict[str, Any]], str]
    get_capture_source: Callable[[dict[str, Any]], str]
    build_archive: Callable[..., dict[str, Any]]
    build_record: Callable[[dict[str, Any]], dict[str, Any]]
    build_failed_record: Callable[..., dict[str, Any]]


def run_article_capture_flow(
    event_queue,
    config: dict | None,
    capture_event_queue,
    deps: ArticleCaptureDependencies,
) -> None:
    """按主服务任务参数抓取公众号主页文章，并把归档索引写入当前项目数据库。"""
    config = config or {}
    run_options = config.get("run_options") if isinstance(config.get("run_options"), dict) else {}
    selections = run_options.get("selections") if isinstance(run_options.get("selections"), dict) else {}
    store = deps.create_public_article_store(Path(config.get("db_path") or DEFAULT_DB_PATH))
    target_total = resolve_record_limit(run_options)
    run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

    deps.put_event(
        event_queue,
        "INFO",
        f"文章抓取任务已启动，本次计划获取 {target_total} 篇新文章",
        source="article_capture",
    )

    try:
        if bool(config.get("enable_home_article_click", True)):
            saved_count, failed_count, skipped_count = _run_cursor_article_capture(
                event_queue,
                config,
                capture_event_queue,
                store,
                selections,
                run_id,
                target_total,
                deps,
            )
        else:
            saved_count, failed_count, skipped_count = _run_legacy_index_article_capture(
                event_queue,
                config,
                capture_event_queue,
                store,
                selections,
                run_id,
                target_total,
                deps,
            )

        summary_level = "ERROR" if failed_count > 0 else "SUCCESS"
        put_collection_status_event(
            event_queue,
            "stopped",
            f"文章抓取任务已完成，本次保存 {saved_count}/{target_total} 篇，跳过 {skipped_count} 篇，失败 {failed_count} 篇",
            level=summary_level,
        )
    except Exception as exc:
        deps.put_event(event_queue, "ERROR", f"文章抓取任务失败：{exc}", source="article_capture")
        put_collection_status_event(event_queue, "error", f"文章抓取任务失败：{exc}")


def _run_cursor_article_capture(
    event_queue,
    config: dict,
    capture_event_queue,
    store,
    selections: dict,
    run_id: str,
    target_total: int,
    deps: ArticleCaptureDependencies,
) -> tuple[int, int, int]:
    home_window = deps.find_wechat_home_window()
    cursor = deps.home_article_cursor_cls(config=config, home_window=home_window)
    account_name = str(config.get("account_name") or "").strip()
    saved_count = 0
    failed_count = 0
    skipped_count = 0
    saw_candidate = False
    pending_failed_records: list[dict[str, Any]] = []

    def defer_failed_record(payload: dict[str, Any]) -> None:
        pending_failed_records.append(payload)

    def flush_pending_failed_records() -> None:
        if not account_name:
            return
        while pending_failed_records:
            payload = pending_failed_records.pop(0)
            _save_failed_article_record(
                event_queue,
                store,
                deps,
                payload["report"],
                article_index=int(payload["article_index"]),
                account_name=account_name,
                target_title=str(payload["target_title"]),
                failure_reason=str(payload["failure_reason"]),
                duration_seconds=float(payload["duration_seconds"]),
                selections=payload.get("selections") if isinstance(payload.get("selections"), dict) else None,
            )

    def remember_confirmed_account_name(value: str) -> None:
        """同一轮采集中，详情页确认过的公众号名可作为后续滚动页的可信兜底。"""
        nonlocal account_name
        text = str(value or "").strip()
        if text:
            account_name = text
            flush_pending_failed_records()

    while saved_count + failed_count < target_total:
        candidate = cursor.next_candidate()
        if candidate is None:
            if _should_wait_for_home_candidates(cursor):
                cursor = _wait_for_home_article_candidates(event_queue, config, deps)
                if cursor is not None:
                    continue
                message = (
                    "主页窗口当前不可读，已停止本次文章采集；请解锁屏幕并保持公众号主页可见后重新开始"
                    if not saw_candidate
                    else "主页窗口中途变为不可读，已停止本次文章采集；请解锁屏幕并保持公众号主页可见后重新开始"
                )
                deps.put_event(
                    event_queue,
                    "WARN",
                    message,
                    source="article_capture",
                )
            else:
                deps.put_event(event_queue, "WARN", "主页可识别文章已处理完，未继续发现新的文章候选", source="article_capture")
            break

        saw_candidate = True
        title = str(getattr(candidate, "title", "") or "").strip()
        article_index = int(getattr(candidate, "article_index", 1) or 1)
        if account_name and title and store.has_saved_public_article_title(account_name, title):
            skipped_count += 1
            deps.put_event(
                event_queue,
                "INFO",
                f"主页第 {article_index} 篇文章已存在，跳过：{title}",
                source="article_capture",
            )
            if hasattr(cursor, "invalidate"):
                cursor.invalidate()
            continue

        ok = _capture_one_article(
            event_queue,
            config,
            capture_event_queue,
            store,
            selections,
            run_id,
            article_index,
            planned_articles=target_total,
            candidate=candidate,
            known_account_name=account_name,
            on_account_confirmed=remember_confirmed_account_name,
            on_failed_record_deferred=defer_failed_record,
            deps=deps,
        )
        if ok:
            saved_count += 1
        else:
            failed_count += 1
        _cleanup_detail_windows_after_article(event_queue, config, deps)
        if hasattr(cursor, "invalidate"):
            cursor.invalidate()

    return saved_count, failed_count, skipped_count


def _should_wait_for_home_candidates(cursor: Any) -> bool:
    reason = str(getattr(cursor, "last_stop_reason", "") or "").strip()
    if reason:
        return reason == "no_visible_candidates"
    return not bool(getattr(cursor, "has_visible_candidates", False))


def _wait_for_home_article_candidates(
    event_queue,
    config: dict,
    deps: ArticleCaptureDependencies,
):
    """锁屏或窗口遮挡时等待主页恢复可读；恢复后返回新的游标，超时返回 None。"""
    timeout_seconds = resolve_home_candidate_wait_timeout_seconds(config)
    interval_seconds = resolve_home_candidate_wait_interval_seconds(config)
    deadline = time.time() + timeout_seconds
    deps.put_event(
        event_queue,
        "WARN",
        f"未读取到主页文章候选，等待主页窗口恢复可读，最长等待 {timeout_seconds:g} 秒",
        source="article_capture",
    )

    while True:
        if interval_seconds > 0:
            time.sleep(interval_seconds)
        home_window = deps.find_wechat_home_window()
        cursor = deps.home_article_cursor_cls(config=config, home_window=home_window)
        if _cursor_has_visible_candidates(cursor):
            deps.put_event(event_queue, "INFO", "主页窗口已恢复可读，继续按文章标题候选采集", source="article_capture")
            return cursor
        if time.time() >= deadline:
            return None


def _cursor_has_visible_candidates(cursor: Any) -> bool:
    refresh_visible = getattr(cursor, "refresh_visible_candidates", None)
    if callable(refresh_visible):
        return bool(refresh_visible())
    has_visible = getattr(cursor, "has_visible_candidates", None)
    if isinstance(has_visible, bool):
        if has_visible:
            return True
        loaded = bool(getattr(cursor, "_loaded", False))
        if loaded:
            return False
    candidate = cursor.next_candidate()
    if candidate is None:
        return False
    visible = getattr(cursor, "_visible", None)
    position = getattr(cursor, "_position", None)
    if isinstance(visible, list) and isinstance(position, int):
        visible.insert(max(0, position - 1), candidate)
        cursor._position = max(0, position - 1)
    return True


def _cleanup_detail_windows_after_article(event_queue, config: dict, deps: ArticleCaptureDependencies) -> None:
    """单篇结束后先关详情窗口，避免下一次主页游标滚动被详情页遮挡。"""
    if not bool(config.get("enable_home_article_click", True)):
        return
    try:
        result = deps.close_detail_windows(
            homepage_hwnd=int(config.get("wechat_home_hwnd") or 0),
            pause_seconds=float(config.get("wechat_detail_window_close_pause_seconds", 0.12) or 0.0),
        )
    except Exception as exc:
        deps.put_event(event_queue, "WARN", f"单篇结束后清理详情窗口失败：{exc}", source="article_capture")
        return
    closed_count = len(result.get("closed") or [])
    if closed_count:
        deps.put_event(event_queue, "INFO", f"单篇结束后已关闭 {closed_count} 个文章详情窗口，准备继续读取主页", source="article_capture")


def _run_legacy_index_article_capture(
    event_queue,
    config: dict,
    capture_event_queue,
    store,
    selections: dict,
    run_id: str,
    target_total: int,
    deps: ArticleCaptureDependencies,
) -> tuple[int, int, int]:
    saved_count = 0
    failed_count = 0
    for article_index in resolve_target_article_indices({"recordLimit": target_total}):
        ok = _capture_one_article(
            event_queue,
            config,
            capture_event_queue,
            store,
            selections,
            run_id,
            article_index,
            planned_articles=target_total,
            deps=deps,
        )
        if ok:
            saved_count += 1
        else:
            failed_count += 1
    return saved_count, failed_count, 0


def _capture_one_article(
    event_queue,
    config: dict,
    capture_event_queue,
    store,
    selections: dict,
    run_id: str,
    article_index: int,
    *,
    planned_articles: int,
    deps: ArticleCaptureDependencies,
    candidate: Any | None = None,
    known_account_name: str = "",
    on_account_confirmed: Callable[[str], Any] | None = None,
    on_failed_record_deferred: Callable[[dict[str, Any]], Any] | None = None,
) -> bool:
    progress_logger = ProgressLogger(event_queue, run_id=run_id, article_index=article_index)
    display_title = str(getattr(candidate, "title", "") or "").strip()
    progress_logger.info(
        "task",
        f"开始处理主页第 {article_index} 篇文章" + (f"：{display_title}" if display_title else ""),
        substep="article_start",
        progress=1,
        meta={"plannedArticles": planned_articles, "candidateTitle": display_title},
    )
    deps.put_event(event_queue, "INFO", f"开始抓取主页第 {article_index} 篇文章", source="article_capture")
    stale_event_count = deps.drain_capture_events(capture_event_queue)
    if stale_event_count:
        deps.put_event(
            event_queue,
            "INFO",
            f"已清理历史 MITM 捕获事件 {stale_event_count} 条，避免误用旧文章",
            source="article_capture",
        )

    window_flow = deps.open_home_article_for_capture(
        event_queue=event_queue,
        config=config,
        article_index=article_index,
        progress_logger=progress_logger,
        target_probe_path=Path(config.get("mitm_target_probe_path") or CURRENT_MITM_TARGET_PROBE_PATH),
        inspect_duration_seconds=DEFAULT_MITM_RESPONSE_INSPECT_SECONDS,
        close_detail_windows=deps.close_detail_windows,
        click_home_article=deps.click_home_article,
        write_probe=deps.write_probe,
        emit_event=deps.put_event,
    )
    target_title = str(window_flow.get("target_title") or display_title or "")
    click_started_at = float(window_flow.get("click_started_at") or time.time())
    selections_payload = {
        "articleDetail": True,
        "commentInfo": bool(selections.get("commentInfo", False)),
    }
    failure_account_name = str(known_account_name or config.get("account_name") or "").strip()
    if should_fast_fail_without_mitm_wait(window_flow):
        failure_reason = build_click_failure_reason(window_flow)
        failed_report = build_click_failed_report(
            config,
            article_index=article_index,
            target_title=target_title,
            failure_reason=failure_reason,
            click_result=window_flow.get("click_result") if isinstance(window_flow.get("click_result"), dict) else {},
        )
        failed_title = deps.resolve_failure_title(failed_report, target_title, article_index)
        progress_logger.error(
            "click",
            "点击阶段未找到可打开的主页文章，已跳过 MITM 空等待",
            substep="click_failed_no_request",
            progress=20,
            meta={
                "displayTitle": failed_title,
                "reason": failure_reason,
                "clickResult": failed_report.get("click_result") or {},
            },
        )
        deps.put_event(
            event_queue,
            "ERROR",
            f"主页第 {article_index} 篇文章保存失败：{failed_title}；原因：{failure_reason}",
            source="article_capture",
        )
        _save_or_defer_failed_article_record(
            event_queue,
            store,
            deps,
            failed_report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=failure_reason,
            duration_seconds=time.time() - click_started_at,
            selections=selections_payload,
            on_failed_record_deferred=on_failed_record_deferred,
        )
        return False

    mitm_capture_timeout_seconds = deps.resolve_timeout(config)
    progress_logger.info(
        "mitm",
        f"开始等待 MITM 捕获文章主 HTML，最长等待 {mitm_capture_timeout_seconds:g} 秒",
        substep="wait_main_html",
        progress=15,
        meta={"timeoutSeconds": mitm_capture_timeout_seconds, "singleClickCapture": True},
    )
    report = deps.collect_report(
        capture_event_queue,
        config,
        article_index=article_index,
        timeout_seconds=mitm_capture_timeout_seconds,
        min_event_timestamp=max(0.0, click_started_at - 0.25),
        target_title=target_title,
    )
    if not deps.is_report_ready(report):
        failure_reason = deps.resolve_failure_reason(report)
        failed_title = deps.resolve_failure_title(report, target_title, article_index)
        progress_logger.error(
            "mitm",
            "MITM 未返回可归档的文章主 HTML",
            substep="wait_failed",
            progress=20,
            meta={"displayTitle": failed_title, "reason": failure_reason},
        )
        deps.put_event(
            event_queue,
            "ERROR",
            f"主页第 {article_index} 篇文章保存失败：{failed_title}；原因：{failure_reason}",
            source="article_capture",
        )
        _save_or_defer_failed_article_record(
            event_queue,
            store,
            deps,
            report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=failure_reason,
            duration_seconds=time.time() - click_started_at,
            selections=selections_payload,
            on_failed_record_deferred=on_failed_record_deferred,
        )
        return False

    progress_logger.success(
        "mitm",
        deps.build_ready_message(report),
        substep="capture_ready",
        progress=25,
        meta={
            "title": deps.resolve_failure_title(report, target_title, article_index),
            "captureSource": deps.get_capture_source(report),
        },
    )
    try:
        archive = deps.build_archive(
            report,
            article_index=article_index,
            selections=selections_payload,
            storage_root=Path(config.get("storage_root") or DEFAULT_STORAGE_ROOT),
            progress_logger=progress_logger,
        )
        record = deps.build_record(archive)
        record["duration_seconds"] = max(0.0, time.time() - click_started_at)
        progress_logger.info(
            "sqlite",
            "开始写入 awa_public_accounts / awa_public_articles",
            substep="upsert_start",
            progress=94,
            meta={"dedupeKey": "account_id + article_link", "articleLink": record["article_link"]},
        )
        record["duration_seconds"] = max(0.0, time.time() - click_started_at)
        store.save_public_article(record)
        confirmed_account_name = str(record.get("account_name") or "").strip()
        if confirmed_account_name and callable(on_account_confirmed):
            on_account_confirmed(confirmed_account_name)
        progress_logger.success("sqlite", "SQLite 索引写入完成", substep="upsert_done", progress=97)
        deps.put_event(
            event_queue,
            "SUCCESS",
            f"主页第 {article_index} 篇文章已保存：{record['article_title']}",
            source="article_capture",
        )
        return True
    except Exception as exc:
        failed_title = deps.resolve_failure_title(report, target_title, article_index)
        error_message = f"主页第 {article_index} 篇文章保存失败：{failed_title}；原因：{exc}"
        progress_logger.error(
            "local_archive",
            str(exc),
            substep="archive_failed",
            progress=90,
            meta={
                "displayTitle": failed_title,
                "errorType": type(exc).__name__,
                "traceback": traceback.format_exc(limit=8),
            },
        )
        deps.put_event(event_queue, "ERROR", error_message, source="article_capture")
        _save_or_defer_failed_article_record(
            event_queue,
            store,
            deps,
            report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=str(exc),
            duration_seconds=time.time() - click_started_at,
            selections=selections_payload,
            on_failed_record_deferred=on_failed_record_deferred,
        )
        return False


def _save_failed_article_record(
    event_queue,
    store,
    deps: ArticleCaptureDependencies,
    report: dict[str, Any],
    *,
    article_index: int,
    account_name: str,
    target_title: str,
    failure_reason: str,
    duration_seconds: float,
    selections: dict[str, bool] | None = None,
) -> None:
    try:
        record = deps.build_failed_record(
            report,
            article_index=article_index,
            selections=selections,
            account_name=account_name,
            target_title=target_title,
            failure_reason=failure_reason,
            duration_seconds=duration_seconds,
        )
        store.save_public_article(record)
    except Exception as exc:
        deps.put_event(event_queue, "WARN", f"失败文章记录写入 SQLite 失败：{exc}", source="article_capture")


def _save_or_defer_failed_article_record(
    event_queue,
    store,
    deps: ArticleCaptureDependencies,
    report: dict[str, Any],
    *,
    article_index: int,
    account_name: str,
    target_title: str,
    failure_reason: str,
    duration_seconds: float,
    selections: dict[str, bool] | None = None,
    on_failed_record_deferred: Callable[[dict[str, Any]], Any] | None = None,
) -> None:
    if str(account_name or "").strip():
        _save_failed_article_record(
            event_queue,
            store,
            deps,
            report,
            article_index=article_index,
            account_name=account_name,
            target_title=target_title,
            failure_reason=failure_reason,
            duration_seconds=duration_seconds,
            selections=selections,
        )
        return

    if callable(on_failed_record_deferred):
        on_failed_record_deferred(
            {
                "report": report,
                "article_index": article_index,
                "target_title": target_title,
                "failure_reason": failure_reason,
                "duration_seconds": duration_seconds,
                "selections": dict(selections or {}),
            }
        )
        deps.put_event(
            event_queue,
            "INFO",
            f"失败文章已暂存，等待同轮后续文章确认公众号名称后再写入 SQLite：{target_title}",
            source="article_capture",
        )
        return

    _save_failed_article_record(
        event_queue,
        store,
        deps,
        report,
        article_index=article_index,
        account_name=account_name,
        target_title=target_title,
        failure_reason=failure_reason,
        duration_seconds=duration_seconds,
        selections=selections,
    )


def should_fast_fail_without_mitm_wait(window_flow: dict[str, Any]) -> bool:
    """点击阶段明确没有发出文章打开动作时，直接失败，避免每篇再空等 MITM。"""
    click_result = window_flow.get("click_result") if isinstance(window_flow.get("click_result"), dict) else {}
    if click_result.get("ok") is not False:
        return False
    reason = str(click_result.get("reason") or "").strip()
    return reason in CLICK_FAILURE_REASONS_WITHOUT_REQUEST


def build_click_failure_reason(window_flow: dict[str, Any]) -> str:
    click_result = window_flow.get("click_result") if isinstance(window_flow.get("click_result"), dict) else {}
    reason = str(click_result.get("reason") or "article_click_failed").strip()
    if reason == "article_click_target_not_found":
        return "点击阶段未找到可打开的主页文章；当前主页窗口未向 UI Automation 暴露文章标题或坐标兜底不可用"
    if reason == "article_index_out_of_range":
        visible_count = click_result.get("visible_count")
        return f"点击阶段文章序号超出当前可见范围；visible_count={visible_count}"
    if reason == "wechat_home_window_not_found":
        return "点击阶段未找到微信公众号主页窗口"
    if reason == "article_click_failed":
        return f"点击阶段发送点击失败：{click_result.get('error') or 'unknown'}"
    return f"点击阶段失败：{reason}"


def build_click_failed_report(
    config: dict,
    *,
    article_index: int,
    target_title: str,
    failure_reason: str,
    click_result: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    display_title = str(target_title or "").strip() or "未识别标题"
    return {
        "created_at": now,
        "target_article": {"title": display_title},
        "main_html_capture": {},
        "storage": {
            "account_name": str(config.get("account_name") or ""),
            "title": display_title,
        },
        "article_detail": {},
        "comment_fetch": {},
        "click_result": dict(click_result or {}),
        "automation_error": failure_reason,
        "conclusion": failure_reason,
    }


def resolve_record_limit(run_options: dict | None) -> int:
    data = run_options if isinstance(run_options, dict) else {}
    try:
        record_limit = int(data.get("recordLimit", data.get("record_limit", 1)))
    except (TypeError, ValueError):
        record_limit = 1
    return max(1, record_limit)


def resolve_home_candidate_wait_timeout_seconds(config: dict | None) -> float:
    data = config if isinstance(config, dict) else {}
    try:
        seconds = float(data.get("homepage_candidate_wait_timeout_seconds", DEFAULT_HOME_CANDIDATE_WAIT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        seconds = DEFAULT_HOME_CANDIDATE_WAIT_TIMEOUT_SECONDS
    return max(0.0, seconds)


def resolve_home_candidate_wait_interval_seconds(config: dict | None) -> float:
    data = config if isinstance(config, dict) else {}
    try:
        seconds = float(data.get("homepage_candidate_wait_interval_seconds", DEFAULT_HOME_CANDIDATE_WAIT_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        seconds = DEFAULT_HOME_CANDIDATE_WAIT_INTERVAL_SECONDS
    return max(0.0, seconds)


def resolve_target_article_indices(run_options: dict | None) -> list[int]:
    """把 01 指定记录总量转换成主页文章序号；当前阶段至少抓取第一篇。"""
    record_limit = resolve_record_limit(run_options)
    return list(range(1, record_limit + 1))


def put_collection_status_event(event_queue, status: str, message: str, level: str | None = None) -> None:
    event_queue.put(
        {
            "type": "collection_status",
            "level": level or ("SUCCESS" if status == "stopped" else "ERROR"),
            "status": status,
            "message": message,
            "source": "article_capture",
            "createdAt": datetime.now().isoformat(timespec="seconds"),
            "timestamp": time.time(),
        }
    )
