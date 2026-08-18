from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_METHOD_DIR = Path(__file__).resolve().parent
for candidate in (PROJECT_ROOT, TASK_METHOD_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from b_test_single_mitm_capture import (
    MitmTaskOutputStore,
    SingleArticleMitmTask,
    create_attempt_identity,
)
from src.app.main_orchestrator import load_application_runtime
from src.domain.enums import TaskStatus
from src.modules.window.article_card_reader import UiaArticleCardReader
from src.modules.window.article_clicker import ArticleClicker
from src.modules.window.home_article_cursor import HomeArticleCursor
from src.modules.window.home_window_activation import WindowsHomeWindowGuard
from src.modules.window.wechat_browser_tabs import (
    UiaWechatBrowserTabAdapter,
    WechatBrowserTabService,
    match_article_tab_title,
)
from src.modules.window.wechat_home_reader import WechatHomeReader
from src.modules.window.wechat_home_scroller import WechatHomeScroller
from src.modules.window.wechat_home_window_finder import find_wechat_home_window


CONFIG: dict[str, Any] = {
    # 手动真实测试时改�?True；默认关闭，避免误运行后直接点击微信文章�?    "execute_click": True,
    # 每篇文章点击前新建一�?MITM 子进程，关闭文章标签后立即结束该子进程�?    "enable_mitm": True,
    "target_count": 1,
    "title_timeout_seconds": 12.0,
    "title_poll_interval_seconds": 0.15,
    "title_stable_delay_seconds": 0.1,
    "scroll_initial_delay_seconds": 0.05,
    "scroll_probe_interval_seconds": 0.1,
    "scroll_probe_max_interval_seconds": 0.4,
    "scroll_settle_timeout_seconds": 1.2,
    "lazy_load_timeout_seconds": 3.0,
    "unchanged_before_bounce_seconds": 0.6,
    "max_scroll_attempts": 6,
    "scroll_wheel_steps": 5,
    "snapshot_max_age_seconds": 60.0,
    "bounce_enabled": True,
    "bounce_attempts": 2,
    "bounce_up_steps": 2,
    "bounce_down_steps": 6,
    "bounce_pause_seconds": 0.2,
    # 结果固定覆盖同一个文件，不生�?_1、_2 后缀�?    "output_path": PROJECT_ROOT / "tests" / "output" / "window_click_records.json",
    "mitm_output_root": PROJECT_ROOT / "tests" / "output",
}


def main() -> int:
    _configure_stdout()
    task_started_at = time.monotonic()
    mitm_enabled = bool(CONFIG["execute_click"] and CONFIG["enable_mitm"])
    task_id = f"window-click-{datetime.now().astimezone():%Y%m%d-%H%M%S}"
    report: dict[str, Any] = {
        "ok": False,
        "execute_click": bool(CONFIG["execute_click"]),
        "mitm_enabled": mitm_enabled,
        "task_id": task_id,
        "target_count": int(CONFIG["target_count"]),
        "completed_count": 0,
        "mitm_success_count": 0,
        "records": [],
        "started_time": _current_iso_time(),
        "error_stage": "",
        "error_message": "",
    }

    reader = UiaArticleCardReader()
    cursor: HomeArticleCursor | None = None
    try:
        report["error_stage"] = "find_home_window"
        home_window = find_wechat_home_window()
        if home_window is None:
            raise RuntimeError("未找到可操作的微信公众号主页窗口")

        report["error_stage"] = "read_home_info"
        home_info = WechatHomeReader().read(home_window)
        report["account_name"] = home_info.account_name
        report["home_window_handle"] = home_window.handle

        cursor = HomeArticleCursor(
            reader=reader,
            account_name=home_info.account_name,
            scroller=WechatHomeScroller(
                wheel_steps=int(CONFIG["scroll_wheel_steps"])
            ),
            max_scroll_attempts=int(CONFIG["max_scroll_attempts"]),
            scroll_wait_seconds=float(CONFIG["scroll_initial_delay_seconds"]),
            scroll_probe_interval_seconds=float(CONFIG["scroll_probe_interval_seconds"]),
            scroll_probe_max_interval_seconds=float(
                CONFIG["scroll_probe_max_interval_seconds"]
            ),
            scroll_settle_timeout_seconds=float(
                CONFIG["scroll_settle_timeout_seconds"]
            ),
            lazy_load_timeout_seconds=float(CONFIG["lazy_load_timeout_seconds"]),
            unchanged_before_bounce_seconds=float(
                CONFIG["unchanged_before_bounce_seconds"]
            ),
            snapshot_max_age_seconds=float(CONFIG["snapshot_max_age_seconds"]),
            bounce_enabled=bool(CONFIG["bounce_enabled"]),
            bounce_attempts=int(CONFIG["bounce_attempts"]),
            bounce_up_steps=int(CONFIG["bounce_up_steps"]),
            bounce_down_steps=int(CONFIG["bounce_down_steps"]),
            bounce_pause_seconds=float(CONFIG["bounce_pause_seconds"]),
        )
        visible_targets = cursor.refresh_visible(home_window)
        report["visible_candidate_count"] = len(visible_targets)
        if not bool(CONFIG["execute_click"]):
            report.update(
                {
                    "ok": True,
                    "error_stage": "",
                    "error_message": "",
                    "reason": "dry_run_completed",
                    "cursor_diagnostics": cursor.diagnostics,
                }
            )
            return _finish(report, task_started_at, 0)

        home_guard = WindowsHomeWindowGuard()
        clicker = ArticleClicker()
        tabs = WechatBrowserTabService(adapter=UiaWechatBrowserTabAdapter())
        mitm_output_store: MitmTaskOutputStore | None = None
        mitm_process_control = None
        mitm_settings = None
        if mitm_enabled:
            report["error_stage"] = "load_mitm_runtime"
            runtime = load_application_runtime(project_root=PROJECT_ROOT)
            if not runtime.config.proxy.enable_system_proxy:
                raise RuntimeError(
                    "custom.yaml 已关�?enable_system_proxy，无法运�?MITM 点击流程"
                )
            mitm_output_store = MitmTaskOutputStore(CONFIG["mitm_output_root"])
            mitm_output_store.reset(task_id=task_id)
            mitm_process_control = runtime.capture_factory.create_process_control()
            mitm_settings = runtime.single_capture_settings
            report["mitm_output_path"] = str(mitm_output_store.manifest_path)

        for record_index in range(1, int(CONFIG["target_count"]) + 1):
            iteration_started_at = time.monotonic()
            mitm_task: SingleArticleMitmTask | None = None
            article_tab = None
            tab_closed = False
            try:
                report["error_stage"] = "activate_home_window"
                stage_started_at = time.monotonic()
                home_guard.activate(home_window)
                activation_seconds = _elapsed(stage_started_at)

                report["error_stage"] = "read_candidate"
                stage_started_at = time.monotonic()
                target = cursor.next_candidate(home_window)
                if target is None:
                    raise RuntimeError("当前主页没有更多未处理文�?)

                report["error_stage"] = "refresh_target"
                refreshed_target = cursor.refresh_target(home_window, target)

                report["error_stage"] = "validate_click_point"
                home_guard.ensure_target_clickable(home_window, refreshed_target)
                candidate_prepare_seconds = _elapsed(stage_started_at)

                report["error_stage"] = "capture_tab_baseline"
                stage_started_at = time.monotonic()
                baseline = tabs.capture_baseline()
                baseline_seconds = _elapsed(stage_started_at)

                mitm_ready_seconds = 0.0
                mitm_stop_seconds = 0.0
                mitm_record: dict[str, Any] = {
                    "status": "disabled",
                    "capture_type": "none",
                }
                if mitm_enabled:
                    if (
                        mitm_output_store is None
                        or mitm_process_control is None
                        or mitm_settings is None
                    ):
                        raise RuntimeError("MITM 运行组件未初始化")
                    report["error_stage"] = "start_mitm_attempt"
                    stage_started_at = time.monotonic()
                    attempt_id, proxy_lease_id = create_attempt_identity(record_index)
                    mitm_task = SingleArticleMitmTask(
                        process_control=mitm_process_control,
                        settings=mitm_settings,
                        output_store=mitm_output_store,
                        task_id=task_id,
                        proxy_lease_id=proxy_lease_id,
                        attempt_id=attempt_id,
                        record_index=record_index,
                        article_title=refreshed_target.title,
                    )
                    # 只有收到 READY，确�?MITM 与系统代理均已生效后才允许点击�?                    mitm_task.start()
                    mitm_ready_seconds = _elapsed(stage_started_at)

                # 持续时长从真正开始点击计算，到确认详情页关闭完成为止�?                report["error_stage"] = "click_article"
                click_started_at = time.monotonic()
                clicker.click(refreshed_target)
                click_dispatch_seconds = _elapsed(click_started_at)

                report["error_stage"] = "confirm_article_title"
                stage_started_at = time.monotonic()
                article_tab = tabs.wait_for_article_tab(
                    target_title=refreshed_target.title,
                    baseline=baseline,
                    timeout_seconds=float(CONFIG["title_timeout_seconds"]),
                    poll_interval_seconds=float(CONFIG["title_poll_interval_seconds"]),
                    stable_delay_seconds=float(CONFIG["title_stable_delay_seconds"]),
                )
                open_confirm_seconds = _elapsed(stage_started_at)

                report["error_stage"] = "close_article_tab"
                stage_started_at = time.monotonic()
                tabs.close_article_tab(
                    article_tab,
                    home_window_handle=home_window.handle,
                )
                tab_closed = True
                close_confirm_seconds = _elapsed(stage_started_at)
                duration_seconds = _elapsed(click_started_at)

                if mitm_task is not None:
                    report["error_stage"] = "stop_mitm_attempt"
                    stage_started_at = time.monotonic()
                    # 标签已关闭就是本次截止点，不�?MITM 结果额外等待文章网络事件�?                    mitm_record = mitm_task.stop()
                    mitm_stop_seconds = _elapsed(stage_started_at)

                # 本人工流程每个候选只点击一次；MITM 成败单独记录，避免反复点击同篇�?                cursor.mark_processed(refreshed_target)
                report["records"].append(
                    _build_record(
                        record_index,
                        refreshed_target.title,
                        _current_collect_time(),
                        duration_seconds,
                        observed_tab_title=article_tab.title,
                        title_match_level=(
                            match_article_tab_title(
                                refreshed_target.title,
                                article_tab.title,
                            )
                            or "unknown"
                        ),
                        activation_seconds=activation_seconds,
                        candidate_prepare_seconds=candidate_prepare_seconds,
                        baseline_seconds=baseline_seconds,
                        click_dispatch_seconds=click_dispatch_seconds,
                        open_confirm_seconds=open_confirm_seconds,
                        close_confirm_seconds=close_confirm_seconds,
                        mitm_ready_seconds=mitm_ready_seconds,
                        mitm_stop_seconds=mitm_stop_seconds,
                        mitm_record=mitm_record,
                        iteration_duration_seconds=_elapsed(iteration_started_at),
                    )
                )
                report["completed_count"] = len(report["records"])
                report["mitm_success_count"] = sum(
                    1
                    for item in report["records"]
                    if item.get("mitm_status") == TaskStatus.SUCCESS.value
                )
            finally:
                # 窗口异常时优先关闭已确认的详情页，再取消本次代理子进程�?                if article_tab is not None and not tab_closed:
                    try:
                        tabs.close_article_tab(
                            article_tab,
                            home_window_handle=home_window.handle,
                        )
                    except Exception:
                        pass
                if mitm_task is not None and not mitm_task.terminal:
                    mitm_task.cancel(
                        f"窗口主流程在 {report['error_stage']} 阶段提前结束"
                    )

        mitm_failure_count = (
            int(report["completed_count"]) - int(report["mitm_success_count"])
            if mitm_enabled
            else 0
        )
        report.update(
            {
                "ok": mitm_failure_count == 0,
                "error_stage": "" if mitm_failure_count == 0 else "mitm_capture",
                "error_message": (
                    ""
                    if mitm_failure_count == 0
                    else f"{mitm_failure_count} 篇未捕获�?HTML �?reference"
                ),
                "reason": (
                    "target_count_completed"
                    if mitm_failure_count == 0
                    else "target_count_completed_with_mitm_failures"
                ),
                "mitm_failure_count": mitm_failure_count,
                "cursor_diagnostics": cursor.diagnostics,
            }
        )
        return _finish(report, task_started_at, 0 if mitm_failure_count == 0 else 4)
    except Exception as exc:
        report["error_message"] = str(exc)
        if cursor is not None:
            report["cursor_diagnostics"] = cursor.diagnostics
        return _finish(report, task_started_at, 3)


def _finish(report: dict[str, Any], task_started_at: float, exit_code: int) -> int:
    report["finished_time"] = _current_iso_time()
    report["task_duration_seconds"] = round(
        time.monotonic() - task_started_at,
        3,
    )
    report["timing_summary"] = _build_timing_summary(report.get("records", []))
    output_path = Path(CONFIG["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


def _current_collect_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _build_record(
    record_index: int,
    article_title: str,
    collect_time: str,
    duration_seconds: float,
    *,
    observed_tab_title: str,
    title_match_level: str,
    activation_seconds: float,
    candidate_prepare_seconds: float,
    baseline_seconds: float,
    click_dispatch_seconds: float,
    open_confirm_seconds: float,
    close_confirm_seconds: float,
    mitm_ready_seconds: float,
    mitm_stop_seconds: float,
    mitm_record: dict[str, Any],
    iteration_duration_seconds: float,
) -> dict[str, Any]:
    return {
        "record_index": int(record_index),
        "article_title": str(article_title),
        "collect_time": str(collect_time),
        "duration_seconds": float(duration_seconds),
        "observed_tab_title": str(observed_tab_title),
        "title_match_level": str(title_match_level),
        "activation_seconds": float(activation_seconds),
        "candidate_prepare_seconds": float(candidate_prepare_seconds),
        "baseline_seconds": float(baseline_seconds),
        "click_dispatch_seconds": float(click_dispatch_seconds),
        "open_confirm_seconds": float(open_confirm_seconds),
        "close_confirm_seconds": float(close_confirm_seconds),
        "mitm_ready_seconds": float(mitm_ready_seconds),
        "mitm_stop_seconds": float(mitm_stop_seconds),
        "mitm_status": str(mitm_record.get("status", "unknown")),
        "mitm_capture_type": str(mitm_record.get("capture_type", "none")),
        "mitm_request_summary": dict(mitm_record.get("request_summary", {})),
        "mitm_output_dir": str(mitm_record.get("output_dir", "")),
        "mitm_error_stage": str(mitm_record.get("error_stage", "")),
        "mitm_error_message": str(mitm_record.get("error_message", "")),
        "iteration_duration_seconds": float(iteration_duration_seconds),
    }


def _build_timing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "duration_seconds",
        "activation_seconds",
        "candidate_prepare_seconds",
        "baseline_seconds",
        "click_dispatch_seconds",
        "open_confirm_seconds",
        "close_confirm_seconds",
        "mitm_ready_seconds",
        "mitm_stop_seconds",
        "iteration_duration_seconds",
    )
    result: dict[str, Any] = {"sample_count": len(records)}
    for field in fields:
        values = [float(item[field]) for item in records if field in item]
        if not values:
            continue
        result[field] = {
            "total": round(sum(values), 3),
            "average": round(sum(values) / len(values), 3),
            "minimum": round(min(values), 3),
            "maximum": round(max(values), 3),
        }
    return result


def _elapsed(started_at: float) -> float:
    return round(time.monotonic() - started_at, 3)


def _current_iso_time() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
