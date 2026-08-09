from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.app_config import AppConfig
from src.modules.window.article_card_reader import UiaArticleCardReader
from src.modules.window.article_clicker import ArticleClicker
from src.modules.window.home_article_cursor import HomeArticleCursor
from src.modules.window.home_window_activation import WindowsHomeWindowGuard
from src.modules.window.wechat_browser_tabs import (
    UiaWechatBrowserTabAdapter,
    WechatBrowserTabService,
)
from src.modules.window.wechat_home_reader import WechatHomeReader
from src.modules.window.wechat_home_scroller import WechatHomeScroller
from src.modules.window.wechat_home_window_finder import find_wechat_home_window


class WindowRuntimeFactory:
    """只使用内存 AppConfig，统一装配文章窗口操作组件。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        reader_factory: Callable[..., Any] = UiaArticleCardReader,
        scroller_factory: Callable[..., Any] = WechatHomeScroller,
        cursor_factory: Callable[..., Any] = HomeArticleCursor,
        home_finder: Callable[..., Any] = find_wechat_home_window,
        home_reader_factory: Callable[..., Any] = WechatHomeReader,
        guard_factory: Callable[..., Any] = WindowsHomeWindowGuard,
        clicker_factory: Callable[..., Any] = ArticleClicker,
        tab_adapter_factory: Callable[..., Any] = UiaWechatBrowserTabAdapter,
        tab_service_factory: Callable[..., Any] = WechatBrowserTabService,
    ) -> None:
        self._window = config.window
        self._reader_factory = reader_factory
        self._scroller_factory = scroller_factory
        self._cursor_factory = cursor_factory
        self._home_finder = home_finder
        self._home_reader_factory = home_reader_factory
        self._guard_factory = guard_factory
        self._clicker_factory = clicker_factory
        self._tab_adapter_factory = tab_adapter_factory
        self._tab_service_factory = tab_service_factory

    @property
    def restore_focus_after_close(self) -> bool:
        return self._window.restore_focus_after_close

    def create_reader(self) -> Any:
        return self._reader_factory()

    def find_home_window(
        self,
        *,
        reader: Any,
        timeout_seconds: float | None = None,
        use_article_probe: bool = True,
    ) -> Any:
        return self._home_finder(
            article_counter=(
                (lambda window: len(reader.read(window))) if use_article_probe else None
            ),
            timeout_seconds=timeout_seconds,
            use_article_probe=use_article_probe,
        )

    def create_home_reader(self) -> Any:
        return self._home_reader_factory()

    def create_cursor(self, *, reader: Any, account_name: str) -> Any:
        scroller = self._scroller_factory(
            wheel_steps=self._window.scroll_wheel_steps,
        )
        return self._cursor_factory(
            reader=reader,
            account_name=account_name,
            scroller=scroller,
            max_scroll_attempts=self._window.max_scroll_attempts,
            scroll_wait_seconds=self._window.scroll_initial_delay_seconds,
            scroll_probe_interval_seconds=self._window.scroll_probe_interval_seconds,
            scroll_probe_max_interval_seconds=(
                self._window.scroll_probe_max_interval_seconds
            ),
            scroll_settle_timeout_seconds=self._window.scroll_settle_timeout_seconds,
            lazy_load_timeout_seconds=self._window.lazy_load_timeout_seconds,
            unchanged_before_bounce_seconds=(
                self._window.unchanged_before_bounce_seconds
            ),
            snapshot_max_age_seconds=self._window.visible_snapshot_max_age_seconds,
            bounce_enabled=self._window.bounce_enabled,
            bounce_attempts=self._window.bounce_attempts,
            bounce_up_steps=self._window.bounce_up_steps,
            bounce_down_steps=self._window.bounce_down_steps,
            bounce_pause_seconds=self._window.bounce_pause_seconds,
        )

    def create_home_guard(self) -> Any:
        return self._guard_factory(
            activation_wait_seconds=self._window.activation_wait_seconds,
        )

    def create_clicker(self) -> Any:
        return self._clicker_factory(
            screen_click_wait_seconds=self._window.screen_click_wait_seconds,
        )

    def create_tab_service(self) -> Any:
        adapter = self._tab_adapter_factory(
            document_return_timeout_seconds=(
                self._window.article_close_confirm_timeout_seconds
            ),
        )
        return self._tab_service_factory(adapter=adapter)


__all__ = ["WindowRuntimeFactory"]
