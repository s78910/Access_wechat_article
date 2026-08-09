from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

_TASK_METHOD_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TASK_METHOD_DIR.parents[1]
for _candidate in (_PROJECT_ROOT, _TASK_METHOD_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from worker_protocol import (
    PROJECT_ROOT,
    describe_result,
    failure_result,
    payload_bool,
    payload_int,
    run_main,
    skipped_result,
    success_result,
)


STAGE = "window_control"


def run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id", ""))
    attempt_id = str(payload.get("attempt_id", ""))
    action = str(payload.get("action", "describe"))
    if action == "describe":
        return describe_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            summary="识别微信公众号主页窗口，点击目标文章标签，并在确认详情页后关闭文章标签�?,
            actions=["describe", "open_and_close_article"],
            safety="除非 execute_click=true，否则不会点击微信窗口�?,
        )
    if action != "open_and_close_article":
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="unknown_action",
            message=f"未知窗口控制动作：{action}",
        )
    if not payload_bool(payload, "execute_click", False):
        return skipped_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            reason="execute_click_not_enabled",
            data={"action": action},
        )
    try:
        return _open_and_close_article(payload, task_id=task_id, attempt_id=attempt_id)
    except Exception as exc:
        return failure_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            code="window_control_failed",
            message=f"{type(exc).__name__}: {exc}",
        )


def _open_and_close_article(
    payload: dict[str, Any],
    *,
    task_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    from src.app.main_orchestrator import load_application_runtime
    from src.modules.window.wechat_browser_tabs import match_article_tab_title

    runtime = load_application_runtime(project_root=PROJECT_ROOT)
    factory = runtime.window_factory
    reader = factory.create_reader()
    home_window = factory.find_home_window(
        reader=reader,
        timeout_seconds=payload.get("home_find_timeout_seconds"),
        use_article_probe=True,
    )
    if home_window is None:
        raise RuntimeError("未找到可操作的微信公众号主页窗口")

    home_info = factory.create_home_reader().read(home_window)
    cursor = factory.create_cursor(reader=reader, account_name=home_info.account_name)
    visible_targets = cursor.refresh_visible(home_window)
    record_index = payload_int(payload, "record_index", 1)
    target = None
    for _ in range(max(1, record_index)):
        target = cursor.next_candidate(home_window)
    if target is None:
        raise RuntimeError("当前主页没有更多未处理文�?)

    guard = factory.create_home_guard()
    clicker = factory.create_clicker()
    tabs = factory.create_tab_service()
    article_tab = None
    tab_closed = False
    try:
        guard.activate(home_window)
        refreshed_target = cursor.refresh_target(home_window, target)
        guard.ensure_target_clickable(home_window, refreshed_target)
        baseline = tabs.capture_baseline()
        click_result = clicker.click(refreshed_target)
        article_tab = tabs.wait_for_article_tab(
            target_title=refreshed_target.title,
            baseline=baseline,
            timeout_seconds=runtime.single_capture_settings.title_timeout_seconds,
            poll_interval_seconds=runtime.single_capture_settings.title_poll_interval_seconds,
            stable_delay_seconds=runtime.single_capture_settings.title_stable_delay_seconds,
        )
        tabs.close_article_tab(article_tab, home_window_handle=home_window.handle)
        tab_closed = True
        cursor.mark_processed(refreshed_target)
        return success_result(
            task_id=task_id,
            attempt_id=attempt_id,
            stage=STAGE,
            data={
                "account_name": home_info.account_name,
                "home_window_handle": home_window.handle,
                "visible_candidate_count": len(visible_targets),
                "target": _target_to_payload(refreshed_target),
                "article_tab": {
                    "title": article_tab.title,
                    "handle": article_tab.handle,
                },
                "title_match_level": match_article_tab_title(
                    refreshed_target.title,
                    article_tab.title,
                )
                or "unknown",
                "click_result": {
                    "x": getattr(click_result, "x", refreshed_target.click_x),
                    "y": getattr(click_result, "y", refreshed_target.click_y),
                },
            },
        )
    finally:
        if article_tab is not None and not tab_closed:
            try:
                tabs.close_article_tab(article_tab, home_window_handle=home_window.handle)
            except Exception:
                pass


def _target_to_payload(target: Any) -> dict[str, Any]:
    return {
        "account_name": target.account_name,
        "title": target.title,
        "click_x": target.click_x,
        "click_y": target.click_y,
        "home_window_handle": target.home_window_handle,
        "fingerprint": target.fingerprint,
    }


def main() -> int:
    return run_main(run_worker)


if __name__ == "__main__":
    raise SystemExit(main())
