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
MIN_HOME_CANDIDATE_WAIT_INTERVAL_SECONDS = 0.05
DEFAULT_FAILED_ARTICLE_SKIP_COOLDOWN_MINUTES = 30.0
DEFAULT_CURSOR_LOOP_LIMIT_EXTRA = 50
DEFAULT_CURSOR_LOOP_LIMIT_MULTIPLIER = 8
DEFAULT_CAPTURE_ATTEMPT_LIMIT_MULTIPLIER = 3
DEFAULT_NO_PROGRESS_LIMIT_EXTRA = 30
DEFAULT_NO_PROGRESS_LIMIT_MULTIPLIER = 5
CLICK_FAILURE_REASONS_WITHOUT_REQUEST = {
    "wechat_home_window_not_found",
    "article_click_target_not_found",
    "article_index_out_of_range",
    "article_click_failed",
}
RECOVERABLE_HOME_CANDIDATE_STOP_REASONS = {
    "no_visible_candidates",
    "scroll_failed",
    "unchanged_after_scroll",
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

        summary_level = "SUCCESS" if saved_count >= target_total else ("ERROR" if failed_count > 0 else "WARN")
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
    run_failed_titles: set[str] = set()
    failed_cooldown_minutes = resolve_failed_article_skip_cooldown_minutes(config)
    max_cursor_iterations = resolve_homepage_max_cursor_iterations(config, target_total)
    max_capture_attempts = resolve_homepage_max_capture_attempts(config, target_total)
    max_no_progress_iterations = resolve_homepage_max_no_progress_iterations(config, target_total)
    skip_collected_records = should_skip_collected_records(selections)
    cursor_iterations = 0
    capture_attempts = 0
    no_progress_iterations = 0

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

    while saved_count < target_total:
        cursor_iterations += 1
        if cursor_iterations > max_cursor_iterations:
            deps.put_event(
                event_queue,
                "WARN",
                (
                    f"主页候选循环达到安全上限 {max_cursor_iterations} 次，已停止本次采集；"
                    f"本次保存 {saved_count}/{target_total} 篇，跳过 {skipped_count} 篇，失败 {failed_count} 篇"
                ),
                source="article_capture",
            )
            break
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
            run_failed_titles=run_failed_titles,
            failed_cooldown_minutes=failed_cooldown_minutes,
            skip_collected_records=skip_collected_records,
        )
        if candidate is None:
            skipped_count += 1
            no_progress_iterations += 1
            if _should_stop_for_no_progress(
                event_queue,
                deps,
                no_progress_iterations=no_progress_iterations,
                max_no_progress_iterations=max_no_progress_iterations,
                saved_count=saved_count,
                target_total=target_total,
                skipped_count=skipped_count,
                failed_count=failed_count,
            ):
                break
            continue
        title = str(getattr(candidate, "title", "") or "").strip()
        article_index = int(getattr(candidate, "article_index", 1) or 1)
        skip_reason = _candidate_skip_reason(
            store,
            account_name,
            title,
            run_failed_titles=run_failed_titles,
            failed_cooldown_minutes=failed_cooldown_minutes,
            skip_collected_records=skip_collected_records,
        )
        if skip_reason:
            skipped_count += 1
            no_progress_iterations += 1
            _skip_cursor_visible_candidates(cursor, [candidate])
            deps.put_event(
                event_queue,
                "INFO",
                _format_candidate_skip_message(article_index, title, skip_reason),
                source="article_capture",
            )
            if hasattr(cursor, "invalidate"):
                cursor.invalidate()
            if _should_stop_for_no_progress(
                event_queue,
                deps,
                no_progress_iterations=no_progress_iterations,
                max_no_progress_iterations=max_no_progress_iterations,
                saved_count=saved_count,
                target_total=target_total,
                skipped_count=skipped_count,
                failed_count=failed_count,
            ):
                break
            continue

        final_failure: dict[str, Any] = {}

        def remember_final_failure(payload: dict[str, Any]) -> None:
            final_failure.clear()
            final_failure.update(payload)

        capture_attempts += 1
        if capture_attempts > max_capture_attempts:
            deps.put_event(
                event_queue,
                "WARN",
                (
                    f"实际点击采集达到安全上限 {max_capture_attempts} 次，已停止本次采集；"
                    f"本次保存 {saved_count}/{target_total} 篇，跳过 {skipped_count} 篇，失败 {failed_count} 篇"
                ),
                source="article_capture",
            )
            break
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
            on_final_failed=remember_final_failure,
            home_window=home_window,
            deps=deps,
        )
        if ok:
            saved_count += 1
            no_progress_iterations = 0
        else:
            failed_count += 1
            no_progress_iterations += 1
            failure_reason = str(final_failure.get("failure_reason") or "")
            failed_title = str(final_failure.get("target_title") or title).strip()
            if failed_title and not should_retry_article_capture(config, failure_reason):
                _remember_failed_title(run_failed_titles, failed_title)
                deps.put_event(
                    event_queue,
                    "WARN",
                    f"文章《{failed_title}》已加入本轮跳过列表，继续查找下一篇可采集文章",
                    source="article_capture",
                )
            if _should_stop_for_no_progress(
                event_queue,
                deps,
                no_progress_iterations=no_progress_iterations,
                max_no_progress_iterations=max_no_progress_iterations,
                saved_count=saved_count,
                target_total=target_total,
                skipped_count=skipped_count,
                failed_count=failed_count,
            ):
                break
        _cleanup_detail_windows(
            event_queue,
            config,
            deps,
            home_window=home_window,
            reason="article_done",
            processed_count=saved_count + failed_count,
        )
        if hasattr(cursor, "invalidate"):
            cursor.invalidate()
        if saved_count < target_total:
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
    run_failed_titles: set[str] | None = None,
    failed_cooldown_minutes: float = 0.0,
    skip_collected_records: bool = True,
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
    selected = _select_first_unsaved_candidate(
        fresh_candidates,
        store,
        account_name,
        run_failed_titles=run_failed_titles,
        failed_cooldown_minutes=failed_cooldown_minutes,
        skip_collected_records=skip_collected_records,
    )
    if selected is None:
        _skip_cursor_visible_candidates(cursor, fresh_candidates)
        deps.put_event(
            event_queue,
            "INFO",
            f"点击前当前可见 {len(fresh_candidates)} 篇文章均不可采集或处于失败冷却，继续向下滚动查找可采集文章",
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


def _select_first_unsaved_candidate(
    candidates: list[Any],
    store,
    account_name: str,
    *,
    run_failed_titles: set[str] | None = None,
    failed_cooldown_minutes: float = 0.0,
    skip_collected_records: bool = True,
) -> Any | None:
    for candidate in candidates:
        title = str(getattr(candidate, "title", "") or "").strip()
        if not title:
            continue
        if _candidate_is_current_account_name(title, account_name):
            continue
        if _candidate_skip_reason(
            store,
            account_name,
            title,
            run_failed_titles=run_failed_titles,
            failed_cooldown_minutes=failed_cooldown_minutes,
            skip_collected_records=skip_collected_records,
        ):
            continue
        return candidate
    return None


def _candidate_is_current_account_name(title: str, account_name: str) -> bool:
    return bool(account_name) and _normalize_skip_title(title) == _normalize_skip_title(account_name)


def _candidate_skip_reason(
    store,
    account_name: str,
    title: str,
    *,
    run_failed_titles: set[str] | None = None,
    failed_cooldown_minutes: float = 0.0,
    skip_collected_records: bool = True,
) -> str:
    normalized_title = _normalize_skip_title(title)
    if not normalized_title:
        return ""
    if normalized_title in (run_failed_titles or set()):
        return "run_failed"
    if skip_collected_records and account_name and _store_has_saved_title(store, account_name, title):
        return "saved"
    if account_name and _store_has_recent_failed_title(store, account_name, title, failed_cooldown_minutes):
        return "recent_failed"
    return ""


def _format_candidate_skip_message(article_index: int, title: str, reason: str) -> str:
    if reason == "saved":
        return f"主页第 {article_index} 篇文章已存在，跳过：{title}"
    if reason == "run_failed":
        return f"主页第 {article_index} 篇文章本轮刚失败，跳过：{title}"
    if reason == "recent_failed":
        return f"主页第 {article_index} 篇文章最近失败仍在冷却期，跳过：{title}"
    return f"主页第 {article_index} 篇文章已跳过：{title}"


def should_skip_collected_records(selections: dict | None) -> bool:
    """是否跳过数据库中已经成功采集过的文章。默认开启，保持旧版本主流程行为。"""
    data = selections if isinstance(selections, dict) else {}
    return bool(data.get("skipCollectedRecords", True))


def _remember_failed_title(run_failed_titles: set[str], title: str) -> None:
    normalized_title = _normalize_skip_title(title)
    if normalized_title:
        run_failed_titles.add(normalized_title)


def _store_has_saved_title(store, account_name: str, title: str) -> bool:
    checker = getattr(store, "has_saved_public_article_title", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(account_name, title))
    except Exception:
        return False


def _store_has_recent_failed_title(store, account_name: str, title: str, cooldown_minutes: float) -> bool:
    try:
        minutes = float(cooldown_minutes)
    except (TypeError, ValueError):
        minutes = 0.0
    if minutes <= 0:
        return False
    checker = getattr(store, "has_recent_failed_public_article_title", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(account_name, title, cooldown_minutes=minutes))
    except Exception:
        return False


def _normalize_skip_title(value: object) -> str:
    return " ".join(str(value or "").split()).lower()


def _should_stop_for_no_progress(
    event_queue,
    deps: ArticleCaptureDependencies,
    *,
    no_progress_iterations: int,
    max_no_progress_iterations: int,
    saved_count: int,
    target_total: int,
    skipped_count: int,
    failed_count: int,
) -> bool:
    if no_progress_iterations < max_no_progress_iterations:
        return False
    deps.put_event(
        event_queue,
        "WARN",
        (
            f"主页采集连续 {no_progress_iterations} 次未产生新的保存结果，已停止本次采集；"
            f"本次保存 {saved_count}/{target_total} 篇，跳过 {skipped_count} 篇，失败 {failed_count} 篇"
        ),
        source="article_capture",
    )
    return True


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
        return reason in RECOVERABLE_HOME_CANDIDATE_STOP_REASONS
    has_visible = getattr(cursor, "has_visible_candidates", None)
    if isinstance(has_visible, bool):
        return not has_visible
    # 没有明确不可读原因时，认为游标已正常耗尽，避免重复创建新游标从头处理。
    return False


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
    latest_home_window = home_window
    deps.put_event(
        event_queue,
        "WARN",
        f"未读取到主页文章候选，正在重新定位并激活微信主页，最长等待 {timeout_seconds:g} 秒",
        source="article_capture",
    )

    while True:
        found_home_window = _find_home_window_safely(deps)
        if found_home_window is not None:
            latest_home_window = found_home_window
        cursor = deps.home_article_cursor_cls(config=config, home_window=latest_home_window)
        if _cursor_has_visible_candidates(cursor):
            deps.put_event(event_queue, "INFO", "主页窗口已恢复可读，继续按文章标题候选采集", source="article_capture")
            return cursor
        if time.time() >= deadline:
            return None
        if interval_seconds > 0:
            time.sleep(interval_seconds)


def _find_home_window_safely(deps: ArticleCaptureDependencies) -> Any | None:
    try:
        return deps.find_wechat_home_window()
    except Exception:
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


def _build_detail_window_cleanup_message(reason: str, closed_count: int, processed_count: int) -> str:
    if reason == "start":
        return f"任务开始前已关闭 {closed_count} 个历史微信文章详情窗口"
    if reason == "article_done":
        return f"已处理 {processed_count} 篇文章，已关闭 {closed_count} 个微信文章详情窗口"
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
        _cleanup_detail_windows(
            event_queue,
            config,
            deps,
            home_window=home_window,
            reason="article_done",
            processed_count=saved_count + failed_count,
        )
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
    on_attempt_failed: Callable[[dict[str, Any]], Any] | None = None,
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
        duration_seconds = time.time() - click_started_at
        _notify_attempt_failed(
            on_attempt_failed,
            report=failed_report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=failure_reason,
            duration_seconds=duration_seconds,
            selections=selections_payload,
            saved=save_failed_record,
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
                duration_seconds=duration_seconds,
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
        duration_seconds = time.time() - click_started_at
        _notify_attempt_failed(
            on_attempt_failed,
            report=report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=failure_reason,
            duration_seconds=duration_seconds,
            selections=selections_payload,
            saved=save_failed_record,
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
                duration_seconds=duration_seconds,
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
        duration_seconds = time.time() - click_started_at
        _notify_attempt_failed(
            on_attempt_failed,
            report=report,
            article_index=article_index,
            account_name=failure_account_name,
            target_title=failed_title,
            failure_reason=str(exc),
            duration_seconds=duration_seconds,
            selections=selections_payload,
            saved=save_failed_record,
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
                failure_reason=str(exc),
                duration_seconds=duration_seconds,
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
    on_final_failed: Callable[[dict[str, Any]], Any] | None = None,
    home_window: Any | None = None,
) -> bool:
    retry_count = resolve_retry_count(config)
    for attempt_index in range(retry_count + 1):
        is_final_attempt = attempt_index >= retry_count
        attempt_failure: dict[str, Any] = {}

        def remember_attempt_failure(payload: dict[str, Any]) -> None:
            attempt_failure.clear()
            attempt_failure.update(payload)

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
            on_attempt_failed=remember_attempt_failure,
            save_failed_record=is_final_attempt,
            home_window=home_window,
        )
        if ok:
            return True
        if is_final_attempt:
            _notify_attempt_failed(on_final_failed, **attempt_failure)
            return False
        failure_reason = str(attempt_failure.get("failure_reason") or "")
        if not should_retry_article_capture(config, failure_reason):
            if not bool(attempt_failure.get("saved")):
                _save_or_defer_failed_article_record(
                    event_queue,
                    store,
                    deps,
                    attempt_failure.get("report") if isinstance(attempt_failure.get("report"), dict) else {},
                    article_index=int(attempt_failure.get("article_index") or article_index),
                    account_name=str(attempt_failure.get("account_name") or known_account_name or config.get("account_name") or ""),
                    target_title=str(attempt_failure.get("target_title") or getattr(candidate, "title", "") or ""),
                    failure_reason=failure_reason,
                    duration_seconds=float(attempt_failure.get("duration_seconds") or 0.0),
                    selections=attempt_failure.get("selections") if isinstance(attempt_failure.get("selections"), dict) else None,
                    on_failed_record_deferred=on_failed_record_deferred,
                )
            deps.put_event(
                event_queue,
                "WARN",
                f"主页第 {article_index} 篇文章失败原因属于无效重试类型，已跳过重复重试",
                source="article_capture",
            )
            _notify_attempt_failed(on_final_failed, **attempt_failure)
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


def _notify_attempt_failed(callback: Callable[[dict[str, Any]], Any] | None, **payload: Any) -> None:
    if not callable(callback):
        return
    try:
        callback(dict(payload))
    except Exception:
        return


def should_retry_article_capture(config: dict | None, failure_reason: str) -> bool:
    """判断单篇失败是否值得重试；缓存命中导致无主请求时，重复点击通常只会继续超时。"""
    if not bool((config or {}).get("retry_non_retriable_mitm_failures", False)):
        reason = str(failure_reason or "")
        non_retriable_markers = (
            "MITM 未看到文章主页面请求",
            "未看到文章主页面请求",
            "未触发网络请求",
            "本地缓存",
            "复用了缓存",
        )
        if any(marker in reason for marker in non_retriable_markers):
            return False
    return True


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


def resolve_failed_article_skip_cooldown_minutes(config: dict | None) -> float:
    data = config if isinstance(config, dict) else {}
    value = data.get(
        "failed_article_skip_cooldown_minutes",
        data.get("failedArticleSkipCooldownMinutes", DEFAULT_FAILED_ARTICLE_SKIP_COOLDOWN_MINUTES),
    )
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        minutes = DEFAULT_FAILED_ARTICLE_SKIP_COOLDOWN_MINUTES
    return max(0.0, minutes)


def resolve_homepage_max_cursor_iterations(config: dict | None, target_total: int) -> int:
    default_value = max(
        1,
        int(target_total) * DEFAULT_CURSOR_LOOP_LIMIT_MULTIPLIER + DEFAULT_CURSOR_LOOP_LIMIT_EXTRA,
    )
    return _resolve_positive_int_config(
        config,
        "homepage_max_cursor_iterations",
        "homepageMaxCursorIterations",
        default_value,
    )


def resolve_homepage_max_capture_attempts(config: dict | None, target_total: int) -> int:
    default_value = max(1, int(target_total) * DEFAULT_CAPTURE_ATTEMPT_LIMIT_MULTIPLIER)
    return _resolve_positive_int_config(
        config,
        "homepage_max_capture_attempts",
        "homepageMaxCaptureAttempts",
        default_value,
    )


def resolve_homepage_max_no_progress_iterations(config: dict | None, target_total: int) -> int:
    default_value = max(
        1,
        int(target_total) * DEFAULT_NO_PROGRESS_LIMIT_MULTIPLIER + DEFAULT_NO_PROGRESS_LIMIT_EXTRA,
    )
    return _resolve_positive_int_config(
        config,
        "homepage_max_no_progress_iterations",
        "homepageMaxNoProgressIterations",
        default_value,
    )


def _resolve_positive_int_config(config: dict | None, snake_key: str, camel_key: str, default_value: int) -> int:
    data = config if isinstance(config, dict) else {}
    try:
        value = int(data.get(snake_key, data.get(camel_key, default_value)))
    except (TypeError, ValueError):
        value = default_value
    return max(1, value)


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
    return max(MIN_HOME_CANDIDATE_WAIT_INTERVAL_SECONDS, seconds)


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
