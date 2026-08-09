from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from src.modules.window.wechat_home_window_finder import (
    WechatHomeWindowFindTimeout,
    WechatHomeWindowMinimized,
)


class WindowClickFlowDiagnosticService:
    """连续执行主页文章窗口点击，不启动 MITM，也不做数据保存。"""

    def __init__(
        self,
        *,
        config: Any,
        window_factory: Any,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._window_factory = window_factory
        self._monotonic = monotonic

    def run(
        self,
        *,
        max_records: int = 20,
        stop_requested: Callable[[], bool] | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        limit = max(1, int(max_records))
        should_stop = stop_requested or (lambda: False)
        records: list[dict[str, Any]] = []
        counters = {"clicked": 0, "opened": 0, "closed": 0}
        started_at = self._monotonic()
        account_name = ""

        def publish(message: str, *, status: str = "running", tone: str = "info") -> None:
            if on_update is None:
                return
            on_update(
                _payload(
                    ok=False,
                    status=status,
                    message=message,
                    tone=tone,
                    items=_items(
                        limit=limit,
                        account_name=account_name,
                        records=records,
                        counters=counters,
                        current_status=message,
                    ),
                    clicked_count=counters["clicked"],
                    opened_count=counters["opened"],
                    closed_count=counters["closed"],
                    stopped_by_user=False,
                    total_seconds=_elapsed(self._monotonic, started_at),
                )
            )

        try:
            publish("正在定位微信主页窗口...")
            reader = self._window_factory.create_reader()
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
                use_article_probe=self._config.window.home_find_use_article_probe,
            )
            if home_window is None:
                return _payload(
                    ok=False,
                    status="home-not-found",
                    message="未找到可操作的微信公众号主页窗口，请先打开公众号主页。",
                    tone="warning",
                    items=_items(
                        limit=limit,
                        account_name=account_name,
                        records=records,
                        counters=counters,
                        current_status="主页窗口未找到",
                    ),
                    clicked_count=0,
                    opened_count=0,
                    closed_count=0,
                    stopped_by_user=False,
                    total_seconds=_elapsed(self._monotonic, started_at),
                )

            guard = self._window_factory.create_home_guard()
            step_started = self._monotonic()
            guard.activate(home_window)
            activation_seconds = _elapsed(self._monotonic, step_started)

            home_info = self._window_factory.create_home_reader().read(home_window)
            account_name = str(getattr(home_info, "account_name", "") or "")
            cursor = self._window_factory.create_cursor(
                reader=reader,
                account_name=account_name,
            )
            clicker = self._window_factory.create_clicker()
            tabs = self._window_factory.create_tab_service()

            visible_targets = cursor.refresh_visible(home_window)
            publish(f"主页激活完成，已识别 {len(visible_targets)} 个可见候选，正在准备第 1 条...")

            for index in range(1, limit + 1):
                if should_stop():
                    return _payload(
                        ok=True,
                        status="stopped",
                        message="已按用户要求停止窗口点击流程。",
                        tone="warning",
                        items=_items(
                            limit=limit,
                            account_name=account_name,
                            records=records,
                            counters=counters,
                            current_status="用户手动停止",
                        ),
                        clicked_count=counters["clicked"],
                        opened_count=counters["opened"],
                        closed_count=counters["closed"],
                        stopped_by_user=True,
                        total_seconds=_elapsed(self._monotonic, started_at),
                    )

                publish(f"正在选择第 {index} 条候选文章...")
                record = _new_record(index=index, status="准备中")
                try:
                    target, candidate_seconds = self._prepare_target(
                        cursor=cursor,
                        home_window=home_window,
                        guard=guard,
                    )
                    if target is None:
                        status = "no-candidate" if counters["clicked"] == 0 else "completed"
                        return _payload(
                            ok=counters["clicked"] > 0,
                            status=status,
                            message=(
                                "当前主页没有可点击的候选文章。"
                                if counters["clicked"] == 0
                                else "已点击当前可识别的候选文章，后续没有新的候选。"
                            ),
                            tone="warning" if counters["clicked"] == 0 else "success",
                            items=_items(
                                limit=limit,
                                account_name=account_name,
                                records=records,
                                counters=counters,
                                current_status="没有新的候选文章",
                            ),
                            clicked_count=counters["clicked"],
                            opened_count=counters["opened"],
                            closed_count=counters["closed"],
                            stopped_by_user=False,
                            total_seconds=_elapsed(self._monotonic, started_at),
                        )

                    record["title"] = str(getattr(target, "title", "") or "")
                    record["candidateSeconds"] = candidate_seconds
                    publish(f"已选择第 {index} 条，正在点击并等待详情页打开...")

                    self._run_one_record(
                        home_window=home_window,
                        target=target,
                        clicker=clicker,
                        tabs=tabs,
                        guard=guard,
                        cursor=cursor,
                        record=record,
                        counters=counters,
                    )
                    records.append(record)
                    publish(f"第 {index} 条完成，正在准备下一条...")
                except Exception as exc:
                    record["status"] = "失败"
                    record["error"] = str(exc)
                    records.append(record)
                    return _payload(
                        ok=False,
                        status="failed",
                        message=f"窗口点击流程在第 {index} 条失败：{exc}",
                        tone="error",
                        items=_items(
                            limit=limit,
                            account_name=account_name,
                            records=records,
                            counters=counters,
                            current_status="执行失败",
                        ),
                        clicked_count=counters["clicked"],
                        opened_count=counters["opened"],
                        closed_count=counters["closed"],
                        stopped_by_user=False,
                        total_seconds=_elapsed(self._monotonic, started_at),
                    )

            return _payload(
                ok=True,
                status="completed",
                message=f"窗口点击流程已达到测试上限 {limit} 条。",
                tone="success",
                items=_items(
                    limit=limit,
                    account_name=account_name,
                    records=records,
                    counters=counters,
                    current_status="达到测试上限",
                ),
                clicked_count=counters["clicked"],
                opened_count=counters["opened"],
                closed_count=counters["closed"],
                stopped_by_user=False,
                total_seconds=_elapsed(self._monotonic, started_at),
            )
        except WechatHomeWindowFindTimeout:
            return _payload(
                ok=False,
                status="home-find-timeout",
                message="定位微信主页窗口超时，请确认公众号主页已打开。",
                tone="warning",
                items=_items(
                    limit=limit,
                    account_name=account_name,
                    records=records,
                    counters=counters,
                    current_status="主页窗口定位超时",
                ),
                clicked_count=counters["clicked"],
                opened_count=counters["opened"],
                closed_count=counters["closed"],
                stopped_by_user=False,
                total_seconds=_elapsed(self._monotonic, started_at),
            )
        except WechatHomeWindowMinimized:
            return _payload(
                ok=False,
                status="home-minimized",
                message="检测到微信主页窗口处于最小化状态，请先从任务栏打开公众号主页窗口。",
                tone="warning",
                items=_items(
                    limit=limit,
                    account_name=account_name,
                    records=records,
                    counters=counters,
                    current_status="主页窗口最小化",
                ),
                clicked_count=counters["clicked"],
                opened_count=counters["opened"],
                closed_count=counters["closed"],
                stopped_by_user=False,
                total_seconds=_elapsed(self._monotonic, started_at),
            )

    def _prepare_target(
        self,
        *,
        cursor: Any,
        home_window: Any,
        guard: Any,
    ) -> tuple[Any | None, float]:
        started_at = self._monotonic()
        target = cursor.next_candidate(home_window)
        if target is None:
            return None, _elapsed(self._monotonic, started_at)
        refreshed_target = cursor.refresh_target(home_window, target)
        ensure_target_clickable = getattr(guard, "ensure_target_clickable", None)
        if callable(ensure_target_clickable):
            ensure_target_clickable(home_window, refreshed_target)
        return refreshed_target, _elapsed(self._monotonic, started_at)

    def _run_one_record(
        self,
        *,
        home_window: Any,
        target: Any,
        clicker: Any,
        tabs: Any,
        guard: Any,
        cursor: Any,
        record: dict[str, Any],
        counters: dict[str, int],
    ) -> None:
        article_tab = None
        tab_closed = False

        baseline_started = self._monotonic()
        baseline = tabs.capture_baseline()
        record["baselineSeconds"] = _elapsed(self._monotonic, baseline_started)

        click_started = self._monotonic()
        click_result = clicker.click(target)
        counters["clicked"] += 1
        record["clickSeconds"] = _elapsed(self._monotonic, click_started)
        record["clickMethod"] = str(getattr(click_result, "method", "") or "")
        record["clickX"] = int(getattr(click_result, "click_x", 0) or 0)
        record["clickY"] = int(getattr(click_result, "click_y", 0) or 0)

        try:
            open_started = self._monotonic()
            article_tab = tabs.wait_for_opened_article_tab(
                baseline=baseline,
                timeout_seconds=self._config.window.article_open_timeout_seconds,
                poll_interval_seconds=(
                    self._config.window.article_title_poll_interval_seconds
                ),
                stable_delay_seconds=(
                    self._config.window.article_title_stable_delay_seconds
                ),
            )
            counters["opened"] += 1
            record["openSeconds"] = _elapsed(self._monotonic, open_started)
            record["tabTitle"] = str(getattr(article_tab, "title", "") or "")

            close_started = self._monotonic()
            tabs.close_article_tab(article_tab, home_window_handle=home_window.handle)
            tab_closed = True
            counters["closed"] += 1
            record["closeSeconds"] = _elapsed(self._monotonic, close_started)

            mark_processed = getattr(cursor, "mark_processed", None)
            if callable(mark_processed):
                mark_processed(target)

            if bool(getattr(self._window_factory, "restore_focus_after_close", True)):
                restore_started = self._monotonic()
                guard.activate(home_window)
                record["restoreSeconds"] = _elapsed(self._monotonic, restore_started)
            else:
                record["restoreSeconds"] = 0.0

            record["status"] = "成功"
        finally:
            if article_tab is not None and not tab_closed:
                try:
                    tabs.close_article_tab(
                        article_tab,
                        home_window_handle=home_window.handle,
                    )
                except Exception:
                    pass


def _new_record(*, index: int, status: str) -> dict[str, Any]:
    return {
        "index": index,
        "status": status,
        "title": "",
        "candidateSeconds": 0.0,
        "baselineSeconds": 0.0,
        "clickSeconds": 0.0,
        "clickX": 0,
        "clickY": 0,
        "openSeconds": 0.0,
        "closeSeconds": 0.0,
        "restoreSeconds": 0.0,
        "clickMethod": "",
        "tabTitle": "",
        "error": "",
    }


def _payload(
    *,
    ok: bool,
    status: str,
    message: str,
    tone: str,
    items: list[dict[str, Any]],
    clicked_count: int,
    opened_count: int,
    closed_count: int,
    stopped_by_user: bool,
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "status": status,
        "action": "window-click-flow",
        "title": "窗口点击流程结果",
        "message": message,
        "tone": tone,
        "items": items,
        "clickedCount": int(clicked_count),
        "openedCount": int(opened_count),
        "closedCount": int(closed_count),
        "stoppedByUser": bool(stopped_by_user),
        "totalSeconds": total_seconds,
    }


def _items(
    *,
    limit: int,
    account_name: str,
    records: list[dict[str, Any]],
    counters: dict[str, int],
    current_status: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        _item("流程", "窗口点击流程"),
        _item("测试上限", f"{limit} 条"),
        _item("公众号", account_name or "未读取"),
        _item("当前状态", current_status),
        _item(
            "统计",
            f"点击 {counters['clicked']} / 打开 {counters['opened']} / 关闭 {counters['closed']}",
        ),
    ]
    items.extend(_record_item(record) for record in records[-20:])
    return items


def _record_item(record: dict[str, Any]) -> dict[str, Any]:
    index = int(record.get("index", 0) or 0)
    status = str(record.get("status", "") or "")
    cells = [
        {"label": "记录", "value": f"{index:02d}"},
        {"label": "状态", "value": status},
        {"label": "候选文章", "value": str(record.get("title", "") or "")},
        {"label": "点击方式", "value": str(record.get("clickMethod", "") or "")},
        {
            "label": "点击坐标",
            "value": (
                f"({record.get('clickX', 0)}, {record.get('clickY', 0)})"
            ),
        },
        {"label": "检测标签", "value": str(record.get("tabTitle", "") or "")},
        {"label": "候选耗时", "value": _seconds(record.get("candidateSeconds", 0.0))},
        {"label": "基线耗时", "value": _seconds(record.get("baselineSeconds", 0.0))},
        {"label": "点击耗时", "value": _seconds(record.get("clickSeconds", 0.0))},
        {"label": "打开耗时", "value": _seconds(record.get("openSeconds", 0.0))},
        {"label": "关闭耗时", "value": _seconds(record.get("closeSeconds", 0.0))},
        {"label": "恢复主页", "value": _seconds(record.get("restoreSeconds", 0.0))},
    ]
    error = str(record.get("error", "") or "")
    if error:
        cells.append({"label": "失败原因", "value": error})
    return {
        "label": f"记录 {index:02d}",
        "value": status,
        "cells": cells,
    }


def _item(label: str, value: Any) -> dict[str, str]:
    return {"label": str(label), "value": str(value)}


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return round(max(0.0, monotonic() - started_at), 3)


def _seconds(value: Any) -> str:
    return f"{float(value or 0.0):.3f} 秒"


__all__ = ["WindowClickFlowDiagnosticService"]
