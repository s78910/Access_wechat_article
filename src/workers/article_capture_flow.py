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
DEFAULT_DETAIL_WINDOW_CLOSE_EVERY_ARTICLES = 5
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
    sleep: Callable[[float], None] = time.sleep


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
    home_window = deps.find_wechat_home_window()
    if bool(config.get("enable_home_article_click", True)) and home_window is None:
        deps.put_event(
            event_queue,
            "ERROR",
            "未找到可用的微信主页窗口，已停止本次文章采集；请先打开公众号/服务号主页后重新开始",
            source="article_capture",
        )
        put_collection_status_event(event_queue, "error", "未找到可用的微信主页窗口")
        return
    if bool(config.get("enable_home_article_click", True)):
        _cleanup_detail_windows(event_queue, config, deps, home_window=home_window, reason="start", processed_count=0)

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
                home_window=home_window,
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
                home_window=home_window,
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
    *,
    home_window: Any | None = None,
) -> tuple[int, int, int]:
    cursor = deps.home_article_cursor_cls(config=config, home_window=home_window)
    account_name = str(config.get("account_name") or "").strip()
    saved_count = 0
    failed_count = 0
    skipped_count = 0
    saw_candidate = False
    pending_failed_records: list[dict[str, Any]] = []
    processed_since_detail_cleanup = 0

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
                cursor = _wait_for_home_article_candidates(event_queue, config, deps, home_window=home_window)
                if cursor is not None:
                    home_window = getattr(cursor, "home_window", home_window)
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
        candidate = _refresh_current_visible_candidate_before_click(
            event_queue,
            config,
            store,
            deps,
            cursor=cursor,
            account_name=account_name,
            original_candidate=candidate,
        )
        if candidate is None:
            skipped_count += 1
            continue
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

        ok = _capture_one_article_with_retries(
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
            home_window=home_window,
            deps=deps,
        )
        if ok:
            saved_count += 1
        else:
            failed_count += 1
        processed_since_detail_cleanup += 1
        if _should_cleanup_detail_windows_for_batch(config, processed_since_detail_cleanup):
            _cleanup_detail_windows(
                event_queue,
                config,
                deps,
                home_window=home_window,
                reason="batch",
                processed_count=saved_count + failed_count,
            )
            processed_since_detail_cleanup = 0
        if hasattr(cursor, "invalidate"):
            cursor.invalidate()
        if saved_count + failed_count < target_total:
            _wait_before_next_article(event_queue, config, deps)

    if saved_count + failed_count > 0:
        _cleanup_detail_windows(
            event_queue,
            config,
            deps,
            home_window=home_window,
            reason="finish",
            processed_count=saved_count + failed_count,
        )
    return saved_count, failed_count, skipped_count


def _refresh_current_visible_candidate_before_click(
    event_queue,
    config: dict,
    store,
    deps: ArticleCaptureDependencies,
    *,
    cursor: Any,
    account_name: str,
    original_candidate: Any,
) -> Any | None:
    """点击前重新读取当前可见候选；主页自动刷新后，以最新可点击候选为准。"""
    if not bool(config.get("homepage_reselect_current_visible_before_click", True)):
        return original_candidate
    refresh_visible = getattr(cursor, "refresh_visible_candidates", None)
    if not callable(refresh_visible):
        return original_candidate
    refresh_visible()
    fresh_candidates = _get_cursor_visible_candidates(cursor)
    fresh_candidates = [item for item in fresh_candidates if _candidate_has_clickable_rect(item)]
    if not fresh_candidates:
        return original_candidate

    original_title = str(getattr(original_candidate, "title", "") or "").strip()
    selected = _select_first_unsaved_candidate(fresh_candidates, store, account_name)
    if selected is None:
        _skip_cursor_visible_candidates(cursor, fresh_candidates)
        deps.put_event(
            event_queue,
            "INFO",
            f"点击前当前可见 {len(fresh_candidates)} 篇文章均已保存，继续向下滚动查找未保存文章",
            source="article_capture",
        )
        return None

    selected_title = str(getattr(selected, "title", "") or "").strip()
    original_index = int(getattr(original_candidate, "article_index", 0) or 0)
    selected_index = int(getattr(selected, "article_index", 0) or 0)
    if selected_title != original_title or selected_index != original_index:
        deps.put_event(
            event_queue,
            "INFO",
            f"点击前主页候选已变化：原计划《{original_title or '未识别'}》，当前改为《{selected_title or '未识别'}》",
            source="article_capture",
        )
    return selected


def _get_cursor_visible_candidates(cursor: Any) -> list[Any]:
    value = getattr(cursor, "visible_candidates", None)
    if callable(value):
        value = value()
    if isinstance(value, list):
        return list(value)
    visible = getattr(cursor, "_visible", None)
    if isinstance(visible, list):
        return list(visible)
    return []


def _select_first_unsaved_candidate(candidates: list[Any], store, account_name: str) -> Any | None:
    for candidate in candidates:
        title = str(getattr(candidate, "title", "") or "").strip()
        if not title:
            continue
        if account_name and store.has_saved_public_article_title(account_name, title):
            continue
        return candidate
    return None


def _skip_cursor_visible_candidates(cursor: Any, candidates: list[Any]) -> None:
    skip_visible = getattr(cursor, "skip_visible_candidates", None)
    titles = [str(getattr(candidate, "title", "") or "").strip() for candidate in candidates]
    titles = [title for title in titles if title]
    if callable(skip_visible):
        skip_visible(titles=titles)
        return
    visible = getattr(cursor, "_visible", None)
    if isinstance(visible, list):
        try:
            cursor._position = len(visible)
        except Exception:
            pass


def _candidate_has_clickable_rect(candidate: Any) -> bool:
    try:
        left, top, right, bottom = tuple(getattr(candidate, "rect", ()) or ())
        return int(right) > int(left) and int(bottom) > int(top)
    except Exception:
        return False


def _should_wait_for_home_candidates(cursor: Any) -> bool:
    reason = str(getattr(cursor, "last_stop_reason", "") or "").strip()
    if reason:
        return reason == "no_visible_candidates"
    return not bool(getattr(cursor, "has_visible_candidates", False))


def _wait_for_home_article_candidates(
    event_queue,
    config: dict,
    deps: ArticleCaptureDependencies,
    *,
    home_window: Any | None = None,
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


def _resolve_homepage_hwnd(home_window: Any | None) -> int:
    try:
        return int(getattr(home_window, "NativeWindowHandle", 0) or 0)
    except Exception:
        return 0


def _cleanup_detail_windows(
    event_queue,
    config: dict,
    deps: ArticleCaptureDependencies,
    *,
    home_window: Any | None = None,
    reason: str = "manual",
    processed_count: int = 0,
) -> None:
    """按采集策略关闭微信文章详情窗口，保留公众号/服务号主页窗口。"""
    if not bool(config.get("enable_home_article_click", True)):
        return
    homepage_hwnd = _resolve_homepage_hwnd(home_window)
    if homepage_hwnd <= 0:
        deps.put_event(event_queue, "WARN", "未清理详情窗口：当前主页窗口句柄为空", source="article_capture")
        return
    try:
        result = deps.close_detail_windows(
            homepage_hwnd=homepage_hwnd,
            pause_seconds=float(config.get("wechat_detail_window_close_pause_seconds", 0.12) or 0.0),
            reason=reason,
        )
    except Exception as exc:
        deps.put_event(event_queue, "WARN", f"清理详情窗口失败：{exc}", source="article_capture")
        return
    closed_count = len(result.get("closed") or [])
    if closed_count:
        message = _build_detail_window_cleanup_message(reason, closed_count, processed_count)
        deps.put_event(event_queue, "INFO", message, source="article_capture")


def _should_cleanup_detail_windows_for_batch(config: dict, processed_since_cleanup: int) -> bool:
    interval = resolve_detail_window_close_every_articles(config)
    return interval > 0 and processed_since_cleanup >= interval


def _build_detail_window_cleanup_message(reason: str, closed_count: int, processed_count: int) -> str:
    if reason == "start":
        return f"任务开始前已关闭 {closed_count} 个历史微信文章详情窗口"
    if reason == "batch":
        return f"已处理 {processed_count} 篇文章，自动关闭 {closed_count} 个微信文章详情窗口"
    if reason == "finish":
        return f"任务结束前已关闭 {closed_count} 个微信文章详情窗口"
    return f"已关闭 {closed_count} 个微信文章详情窗口"


def _run_legacy_index_article_capture(
    event_queue,
    config: dict,
    capture_event_queue,
    store,
    selections: dict,
    run_id: str,
    target_total: int,
    deps: ArticleCaptureDependencies,
    *,
    home_window: Any | None = None,
) -> tuple[int, int, int]:
    saved_count = 0
    failed_count = 0
    processed_since_detail_cleanup = 0
    for article_index in resolve_target_article_indices({"recordLimit": target_total}):
        ok = _capture_one_article_with_retries(
            event_queue,
            config,
            capture_event_queue,
            store,
            selections,
            run_id,
            article_index,
            planned_articles=target_total,
            home_window=home_window,
            deps=deps,
        )
        if ok:
            saved_count += 1
        else:
            failed_count += 1
        processed_since_detail_cleanup += 1
        if _should_cleanup_detail_windows_for_batch(config, processed_since_detail_cleanup):
            _cleanup_detail_windows(
                event_queue,
                config,
                deps,
                home_window=home_window,
                reason="batch",
                processed_count=saved_count + failed_count,
            )
            processed_since_detail_cleanup = 0
        if saved_count + failed_count < target_total:
            _wait_before_next_article(event_queue, config, deps)
    if saved_count + failed_count > 0:
        _cleanup_detail_windows(
            event_queue,
            config,
            deps,
            home_window=home_window,
            reason="finish",
            processed_count=saved_count + failed_count,
        )
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
    home_window: Any | None = None,
    deps: ArticleCaptureDependencies,
    candidate: Any | None = None,
    known_account_name: str = "",
    on_account_confirmed: Callable[[str], Any] | None = None,
    on_failed_record_deferred: Callable[[dict[str, Any]], Any] | None = None,
    save_failed_record: bool = True,
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
        home_window=home_window,
        close_detail_windows=deps.close_detail_windows,
        click_home_article=deps.click_home_article,
        candidate=candidate,
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
        if save_failed_record:
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
        if save_failed_record:
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
        if save_failed_record:
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


def _capture_one_article_with_retries(
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
    home_window: Any | None = None,
) -> bool:
    retry_count = resolve_retry_count(config)
    for attempt_index in range(retry_count + 1):
        is_final_attempt = attempt_index >= retry_count
        ok = _capture_one_article(
            event_queue,
            config,
            capture_event_queue,
            store,
            selections,
            run_id,
            article_index,
            planned_articles=planned_articles,
            deps=deps,
            candidate=candidate,
            known_account_name=known_account_name,
            on_account_confirmed=on_account_confirmed,
            on_failed_record_deferred=on_failed_record_deferred if is_final_attempt else None,
            save_failed_record=is_final_attempt,
            home_window=home_window,
        )
        if ok:
            return True
        if is_final_attempt:
            return False
        _cleanup_detail_windows(
            event_queue,
            config,
            deps,
            home_window=home_window,
            reason="retry",
            processed_count=0,
        )
        deps.put_event(
            event_queue,
            "WARN",
            f"主页第 {article_index} 篇文章采集失败，准备第 {attempt_index + 1} 次重试",
            source="article_capture",
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


def resolve_request_interval_seconds(config: dict | None) -> float:
    data = config if isinstance(config, dict) else {}
    try:
        seconds = float(data.get("request_interval_seconds", data.get("requestIntervalSeconds", 0)))
    except (TypeError, ValueError):
        seconds = 0.0
    return max(0.0, seconds)


def resolve_retry_count(config: dict | None) -> int:
    data = config if isinstance(config, dict) else {}
    try:
        retry_count = int(data.get("retry_count", data.get("retryCount", 0)))
    except (TypeError, ValueError):
        retry_count = 0
    return max(0, retry_count)


def resolve_detail_window_close_every_articles(config: dict | None) -> int:
    data = config if isinstance(config, dict) else {}
    raw_value = data.get(
        "wechat_detail_window_close_every_articles",
        data.get("wechatDetailWindowCloseEveryArticles", DEFAULT_DETAIL_WINDOW_CLOSE_EVERY_ARTICLES),
    )
    try:
        interval = int(raw_value)
    except (TypeError, ValueError):
        interval = DEFAULT_DETAIL_WINDOW_CLOSE_EVERY_ARTICLES
    return max(0, interval)


def _wait_before_next_article(event_queue, config: dict, deps: ArticleCaptureDependencies) -> None:
    seconds = resolve_request_interval_seconds(config)
    if seconds <= 0:
        return
    deps.put_event(
        event_queue,
        "INFO",
        f"等待 {seconds:g} 秒后继续处理下一篇文章",
        source="article_capture",
    )
    deps.sleep(seconds)


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
