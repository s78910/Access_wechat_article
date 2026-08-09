from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from typing import Any

from src.modules.window.wechat_home_window_finder import (
    WechatHomeWindowFindTimeout,
    WechatHomeWindowMinimized,
)


WINDOW_DIAGNOSTIC_ACTIONS = frozenset(
    {
        "read-home",
        "activate-home",
        "first-article-click",
        "scroll-page",
        "bounce-scroll",
        "close-tab",
    }
)


class WindowDiagnosticService:
    """执行设置页里的窗口诊断动作，不启动 MITM，也不保存采集数据。"""

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

    def run(self, action: str) -> dict[str, Any]:
        normalized_action = str(action).strip()
        try:
            if normalized_action == "read-home":
                return self._read_home()
            if normalized_action == "activate-home":
                return self._activate_home()
            if normalized_action == "first-article-click":
                return self._first_article_click()
            if normalized_action == "scroll-page":
                return self._scroll_page()
            if normalized_action == "bounce-scroll":
                return self._bounce_scroll()
            if normalized_action == "close-tab":
                return self._close_one_tab()
        except _DiagnosticHomeMinimized as exc:
            return _home_minimized_result(
                action=normalized_action,
                title=_diagnostic_title(normalized_action),
                window=exc.window,
                find_seconds=exc.find_seconds,
                config=self._config,
            )
        except WechatHomeWindowMinimized as exc:
            return _home_minimized_result(
                action=normalized_action,
                title=_diagnostic_title(normalized_action),
                window=exc.window,
            )
        raise ValueError(f"不支持的窗口诊断动作：{action}")

    def _read_home(self) -> dict[str, Any]:
        reader = self._window_factory.create_reader()
        started_at = self._monotonic()
        try:
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
                use_article_probe=self._config.window.home_find_use_article_probe,
            )
        except WechatHomeWindowFindTimeout:
            return _result(
                action="read-home",
                ok=False,
                status="home-find-timeout",
                title="读取主页结果",
                message="定位微信主页窗口超时，请先确认公众号主页已经打开。",
                tone="warning",
            )
        except WechatHomeWindowMinimized as exc:
            return _home_minimized_result(
                action="read-home",
                title="读取主页结果",
                window=exc.window,
            )

        if home_window is None:
            return _result(
                action="read-home",
                ok=False,
                status="home-not-found",
                title="读取主页结果",
                message="未找到目标窗口，请先打开公众号主页窗口。",
                tone="warning",
            )

        home_reader = self._window_factory.create_home_reader()
        home_info = home_reader.read(home_window)
        return _result(
            action="read-home",
            ok=True,
            status="home-read",
            title="读取主页结果",
            message="已读取公众号主页名称。",
            items=[
                _item("公众号名称", _safe_attr(home_info, "account_name", "")),
            ],
        )

    def _activate_home(self) -> dict[str, Any]:
        action_started_at = self._monotonic()
        reader = self._window_factory.create_reader()

        started_at = self._monotonic()
        try:
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
                use_article_probe=self._config.window.home_find_use_article_probe,
            )
        except WechatHomeWindowFindTimeout:
            find_seconds = _elapsed(self._monotonic, started_at)
            return _result(
                action="activate-home",
                ok=False,
                status="home-find-timeout",
                title="激活主页结果",
                message="定位微信主页窗口超时，请先确认公众号主页已经打开。",
                tone="warning",
                items=[
                    _timing_config_item(
                        "主页窗口定位",
                        find_seconds,
                        "home_find_timeout_seconds",
                        self._config.window.home_find_timeout_seconds,
                        extra_setting_key="home_find_use_article_probe",
                        extra_setting_value=(
                            self._config.window.home_find_use_article_probe
                        ),
                    ),
                ],
            )
        except WechatHomeWindowMinimized as exc:
            find_seconds = _elapsed(self._monotonic, started_at)
            return _home_minimized_result(
                action="activate-home",
                title="激活主页结果",
                window=exc.window,
                find_seconds=find_seconds,
                config=self._config,
            )
        find_seconds = _elapsed(self._monotonic, started_at)
        if home_window is None:
            return _result(
                action="activate-home",
                ok=False,
                status="home-not-found",
                title="激活主页结果",
                message="未找到可操作的微信公众号主页窗口，请先打开公众号主页窗口。",
                tone="warning",
                items=[
                    _timing_config_item(
                        "主页窗口定位",
                        find_seconds,
                        "home_find_timeout_seconds",
                        self._config.window.home_find_timeout_seconds,
                        extra_setting_key="home_find_use_article_probe",
                        extra_setting_value=(
                            self._config.window.home_find_use_article_probe
                        ),
                    ),
                ],
            )

        started_at = self._monotonic()
        guard = self._window_factory.create_home_guard()
        guard.activate(home_window)
        activation_seconds = _elapsed(self._monotonic, started_at)

        started_at = self._monotonic()
        home_reader = self._window_factory.create_home_reader()
        home_info = home_reader.read(home_window)
        read_home_seconds = _elapsed(self._monotonic, started_at)

        total_seconds = _elapsed(self._monotonic, action_started_at)
        return _result(
            action="activate-home",
            ok=True,
            status="activated",
            title="激活主页结果",
            message="已聚焦微信主页窗口。",
            items=[
                _item("公众号", _safe_attr(home_info, "account_name", "")),
                _item("主页标题", _safe_attr(home_window, "title", "")),
                _item("主页窗口句柄", _safe_attr(home_window, "handle", "")),
                _timing_config_item(
                    "主页窗口定位",
                    find_seconds,
                    "home_find_timeout_seconds",
                    self._config.window.home_find_timeout_seconds,
                    extra_setting_key="home_find_use_article_probe",
                    extra_setting_value=self._config.window.home_find_use_article_probe,
                ),
                _timing_config_item(
                    "激活主页窗口",
                    activation_seconds,
                    "activation_wait_seconds",
                    self._config.window.activation_wait_seconds,
                ),
                _timing_config_item(
                    "公众号信息读取",
                    read_home_seconds,
                    "无",
                    "无直接等待配置",
                ),
                _timing_config_item(
                    "总耗时",
                    total_seconds,
                    "综合耗时",
                    (
                        "主页窗口定位 + 公众号信息读取 + 激活主页窗口"
                    ),
                ),
            ],
        )

    def _first_article_click(self) -> dict[str, Any]:
        action_started_at = self._monotonic()
        reader, home_window, home_info, activation_seconds = self._home_context(
            activate=True
        )
        cursor = self._create_cursor(reader, home_info)
        clicker = self._window_factory.create_clicker()

        step_items: list[dict[str, str]] = [
            _split_item(
                "激活主页",
                _seconds(activation_seconds),
                "对应设置",
                f"activation_wait_seconds={self._config.window.activation_wait_seconds}",
            )
        ]

        started_at = self._monotonic()
        visible_targets = cursor.refresh_visible(home_window)
        target = cursor.next_candidate(home_window)
        if target is None:
            return _result(
                action="first-article-click",
                ok=False,
                status="no-candidate",
                title="首篇点击结果",
                message="当前主页没有可点击的候选文章。",
                tone="warning",
                items=[
                    _item("公众号", _safe_attr(home_info, "account_name", "")),
                    _item("当前可见文章数", len(visible_targets)),
                ],
            )

        refreshed_target = cursor.refresh_target(home_window, target)
        guard = self._window_factory.create_home_guard()
        guard.ensure_target_clickable(home_window, refreshed_target)
        candidate_seconds = _elapsed(self._monotonic, started_at)
        step_items.append(
            _split_item(
                "候选准备",
                _seconds(candidate_seconds),
                "候选文章",
                refreshed_target.title,
            )
        )

        started_at = self._monotonic()
        click_result = clicker.click(refreshed_target)
        click_seconds = _elapsed(self._monotonic, started_at)
        step_items.append(
            _split_item(
                "点击派发",
                _seconds(click_seconds),
                "点击方式",
                _safe_attr(click_result, "method", ""),
            )
        )
        step_items.append(
            _item(
                "点击坐标",
                f"({_safe_attr(click_result, 'click_x', 0)}, {_safe_attr(click_result, 'click_y', 0)})",
            )
        )

        total_seconds = _elapsed(self._monotonic, action_started_at)
        step_items.extend(
            [
                _item("公众号", _safe_attr(home_info, "account_name", "")),
                _item("目标文章", refreshed_target.title),
                _item("点击方式", _safe_attr(click_result, "method", "")),
                _item("总耗时", _seconds(total_seconds)),
            ]
        )
        return _result(
            action="first-article-click",
            ok=True,
            status="clicked",
            title="首篇点击结果",
            message="已点击首篇候选文章，未执行标题确认和标签关闭。",
            items=step_items,
        )

    def _scroll_page(self) -> dict[str, Any]:
        reader, home_window, home_info, activation_seconds = self._home_context(
            activate=True
        )
        cursor = self._create_cursor(reader, home_info)
        visible_before = cursor.refresh_visible(home_window)

        before = dict(cursor.diagnostics)
        started_at = self._monotonic()
        scroll_ok = bool(
            cursor._send_scroll(
                home_window,
                direction="down",
                wheel_steps=self._config.window.scroll_wheel_steps,
            )
        )
        if scroll_ok:
            cursor._wait(self._config.window.scroll_initial_delay_seconds)
        visible_after = cursor.refresh_visible(home_window) if scroll_ok else visible_before
        elapsed = _elapsed(self._monotonic, started_at)
        after = dict(cursor.diagnostics)

        return _result(
            action="scroll-page",
            ok=scroll_ok,
            status="completed" if scroll_ok else "scroll-failed",
            title="滚动页面结果",
            message=(
                "已聚焦主页窗口并执行一次普通向下滚动。"
                if scroll_ok
                else "普通向下滚动消息发送失败。"
            ),
            tone="success" if scroll_ok else "error",
            items=[
                _item("公众号", _safe_attr(home_info, "account_name", "")),
                _split_item(
                    "激活主页",
                    _seconds(activation_seconds),
                    "对应设置",
                    f"activation_wait_seconds={self._config.window.activation_wait_seconds}",
                ),
                _item("滚动派发", "成功" if scroll_ok else "失败"),
                _item("滚动方向", "down"),
                _item("滚动前可见文章数", len(visible_before)),
                _item("滚动后可见文章数", len(visible_after)),
                _item("实际耗时", _seconds(elapsed)),
                _item("向下滚动次数", 1 if scroll_ok else 0),
                _item("页面变化轮询次数", _delta(after, before, "scroll_probe_count")),
                _item("懒加载等待次数", _delta(after, before, "loading_wait_count")),
                _item(
                    "对应设置",
                    (
                        f"scroll_wheel_steps={self._config.window.scroll_wheel_steps}; "
                        "scroll_initial_delay_seconds="
                        f"{self._config.window.scroll_initial_delay_seconds}; "
                        "scroll_probe_interval_seconds="
                        f"{self._config.window.scroll_probe_interval_seconds}; "
                        "lazy_load_timeout_seconds="
                        f"{self._config.window.lazy_load_timeout_seconds}"
                    ),
                ),
            ],
        )

    def _bounce_scroll(self) -> dict[str, Any]:
        reader, home_window, home_info, activation_seconds = self._home_context(
            activate=True
        )
        cursor = self._create_cursor(reader, home_info)
        visible_targets = cursor.refresh_visible(home_window)

        started_at = self._monotonic()
        up_ok = cursor._send_scroll(
            home_window,
            direction="up",
            wheel_steps=self._config.window.bounce_up_steps,
        )
        cursor._wait(self._config.window.bounce_pause_seconds)
        down_ok = cursor._send_scroll(
            home_window,
            direction="down",
            wheel_steps=self._config.window.bounce_down_steps,
        )
        elapsed = _elapsed(self._monotonic, started_at)

        return _result(
            action="bounce-scroll",
            ok=bool(up_ok and down_ok),
            status="completed" if up_ok and down_ok else "scroll-failed",
            title="回弹滚动结果",
            message="已执行一次先上滚后下滚的回弹滚动。" if up_ok and down_ok else "回弹滚动消息发送失败。",
            tone="success" if up_ok and down_ok else "error",
            items=[
                _item("公众号", _safe_attr(home_info, "account_name", "")),
                _split_item(
                    "激活主页",
                    _seconds(activation_seconds),
                    "对应设置",
                    f"activation_wait_seconds={self._config.window.activation_wait_seconds}",
                ),
                _item("当前可见文章数", len(visible_targets)),
                _item("向上滚动", "成功" if up_ok else "失败"),
                _item("向上滚动步数", self._config.window.bounce_up_steps),
                _item("向下滚动", "成功" if down_ok else "失败"),
                _item("向下滚动步数", self._config.window.bounce_down_steps),
                _item("实际耗时", _seconds(elapsed)),
                _item(
                    "对应设置",
                    (
                        f"bounce_up_steps={self._config.window.bounce_up_steps}; "
                        f"bounce_pause_seconds={self._config.window.bounce_pause_seconds}; "
                        f"bounce_down_steps={self._config.window.bounce_down_steps}"
                    ),
                ),
            ],
        )

    def _close_one_tab(self) -> dict[str, Any]:
        tabs = self._window_factory.create_tab_service()
        article_tabs = _article_tabs(tabs)
        if not article_tabs:
            return _result(
                action="close-tab",
                ok=False,
                status="no-article-tab",
                title="关闭标签结果",
                message="未找到可关闭的文章标签，请先打开微信文章详情页。",
                tone="warning",
                items=[_item("检测到文章标签数", 0)],
            )
        selected = article_tabs[0]
        started_at = self._monotonic()
        tabs.close_article_tab(selected, home_window_handle=0)
        elapsed = _elapsed(self._monotonic, started_at)
        return _result(
            action="close-tab",
            ok=True,
            status="closed",
            title="关闭标签结果",
            message="已关闭第一个文章标签。",
            items=[
                _item("标签名", selected.title),
                _item("标签 ID", selected.tab_id),
                _item("窗口句柄", selected.owner_handle),
                _item("关闭方式", "Ctrl+W"),
                _item("关闭耗时", _seconds(elapsed)),
                _item(
                    "对应设置",
                    (
                        "article_close_confirm_timeout_seconds="
                        f"{self._config.window.article_close_confirm_timeout_seconds}"
                    ),
                ),
            ],
        )

    def _home_context(
        self,
        *,
        required: bool = True,
        activate: bool = False,
    ) -> tuple[Any, Any, Any, float]:
        reader = self._window_factory.create_reader()
        started_at = self._monotonic()
        try:
            home_window = self._window_factory.find_home_window(
                reader=reader,
                timeout_seconds=self._config.window.home_find_timeout_seconds,
                use_article_probe=self._config.window.home_find_use_article_probe,
            )
        except WechatHomeWindowMinimized as exc:
            find_seconds = _elapsed(self._monotonic, started_at)
            if required:
                raise _DiagnosticHomeMinimized(exc.window, find_seconds) from exc
            home_window = _MissingHomeWindow()
        if home_window is None:
            if required:
                raise RuntimeError("未找到可操作的微信公众号主页窗口，请先打开公众号主页窗口。")
            home_window = _MissingHomeWindow()

        activation_seconds = 0.0
        if activate and home_window.handle:
            guard = self._window_factory.create_home_guard()
            started_at = self._monotonic()
            guard.activate(home_window)
            activation_seconds = _elapsed(self._monotonic, started_at)
        home_reader = self._window_factory.create_home_reader()
        home_info = home_reader.read(home_window) if home_window.handle else _MissingHomeInfo()
        return reader, home_window, home_info, activation_seconds

    def _create_cursor(self, reader: Any, home_info: Any) -> Any:
        return self._window_factory.create_cursor(
            reader=reader,
            account_name=_safe_attr(home_info, "account_name", ""),
        )


class _MissingHomeWindow:
    handle = 0
    title = ""
    rect = (0, 0, 0, 0)


class _MissingHomeInfo:
    account_name = ""


class _DiagnosticHomeMinimized(RuntimeError):
    def __init__(self, window: Any, find_seconds: float) -> None:
        self.window = window
        self.find_seconds = find_seconds
        super().__init__("微信主页窗口处于最小化状态")


def _article_tabs(tabs: Any) -> list[Any]:
    list_article_tabs = getattr(tabs, "list_article_tabs", None)
    raw_tabs = list_article_tabs() if callable(list_article_tabs) else []
    return [
        item
        for item in raw_tabs
        if str(getattr(item, "title", "") or "").strip()
        and str(getattr(item, "tab_id", "") or "").strip()
    ]


def _looks_like_home_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in {"公众号", "服务号", "订阅号", "微信", "wechat", "weixin"}


def _result(
    *,
    action: str,
    ok: bool,
    status: str,
    title: str,
    message: str,
    items: list[dict[str, Any]] | None = None,
    tone: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "status": status,
        "action": action,
        "title": title,
        "message": message,
        "tone": tone or ("success" if ok else "error"),
        "items": items or [],
    }


def _home_minimized_result(
    *,
    action: str,
    title: str,
    window: Any,
    find_seconds: float | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    items = [
        _item("主页标题", _safe_attr(window, "title", "")),
        _item("主页窗口句柄", _safe_attr(window, "handle", "")),
        _item("窗口状态", "最小化"),
        _item(
            "处理方式",
            "请先打开微信任务栏图标，让公众号主页窗口显示出来，再重新执行窗口诊断。",
        ),
    ]
    if find_seconds is not None and config is not None:
        items.append(
            _timing_config_item(
                "主页窗口定位",
                find_seconds,
                "home_find_timeout_seconds",
                config.window.home_find_timeout_seconds,
                extra_setting_key="home_find_use_article_probe",
                extra_setting_value=config.window.home_find_use_article_probe,
            )
        )
    return _result(
        action=action,
        ok=False,
        status="home-minimized",
        title=title,
        message="检测到微信主页窗口处于最小化状态，请先打开公众号主页窗口。",
        tone="warning",
        items=items,
    )


def _diagnostic_title(action: str) -> str:
    return {
        "read-home": "读取主页结果",
        "activate-home": "激活主页结果",
        "first-article-click": "首篇点击结果",
        "scroll-page": "滚动页面结果",
        "bounce-scroll": "回弹滚动结果",
        "close-tab": "关闭标签结果",
    }.get(action, "窗口诊断结果")


def _item(label: str, value: Any) -> dict[str, str]:
    return {"label": str(label), "value": str(value)}


def _split_item(label: str, value: Any, right_label: str, right_value: Any) -> dict[str, Any]:
    return {
        "label": str(label),
        "value": str(value),
        "cells": [
            {"label": str(label), "value": str(value)},
            {"label": str(right_label), "value": str(right_value)},
        ],
    }


def _timing_config_item(
    stage: str,
    seconds: float,
    setting_key: str,
    setting_value: Any,
    *,
    extra_setting_key: str | None = None,
    extra_setting_value: Any | None = None,
) -> dict[str, Any]:
    cells = [
        {"label": "阶段", "value": str(stage)},
        {"label": "耗时", "value": _seconds(seconds)},
        {"label": "相关设置", "value": str(setting_key)},
        {"label": "当前值", "value": str(setting_value)},
    ]
    if extra_setting_key is not None:
        cells.extend(
            [
                {"label": "辅助设置", "value": str(extra_setting_key)},
                {"label": "辅助值", "value": str(extra_setting_value)},
            ]
        )
    return {
        "label": str(stage),
        "value": _seconds(seconds),
        "cells": cells,
    }


def _elapsed(monotonic: Callable[[], float], started_at: float) -> float:
    return round(max(0.0, monotonic() - started_at), 3)


def _seconds(value: float) -> str:
    return f"{float(value):.3f} 秒"


def _delta(after: Mapping[str, Any], before: Mapping[str, Any], key: str) -> int | float:
    return after.get(key, 0) - before.get(key, 0)


def _safe_attr(value: Any, name: str, fallback: Any) -> Any:
    try:
        return getattr(value, name)
    except Exception:
        return fallback


__all__ = ["WINDOW_DIAGNOSTIC_ACTIONS", "WindowDiagnosticService"]
