from __future__ import annotations

import unittest

from src.domain.models import ArticleTarget
from src.modules.window.wechat_home_scroller import WechatHomeScroller, _scroll_point
from src.modules.window.window_models import WindowInfo


class WechatHomeScrollerTests(unittest.TestCase):
    def test_exposes_configured_default_wheel_steps(self) -> None:
        scroller = WechatHomeScroller(
            wheel_steps=7,
            platform_name="Windows",
        )

        self.assertEqual(scroller.wheel_steps, 7)

    def test_scroll_point_uses_stable_home_viewport_position(self) -> None:
        target = _target()
        target = ArticleTarget(
            account_name=target.account_name,
            title=target.title,
            click_x=750,
            click_y=1150,
            home_window_handle=target.home_window_handle,
            fingerprint=target.fingerprint,
            metric_text=target.metric_text,
            metric_rect=(700, 1130, 790, 1170),
        )

        self.assertEqual(_scroll_point(_home_window(), [target]), (400, 800))

    def test_scroll_temporarily_activates_home_and_restores_previous_window(self) -> None:
        user32 = _FakeUser32(
            render_handle=220,
            home_handle=100,
            foreground_handle=900,
        )
        sleeps: list[tuple[float, int]] = []
        scroller = WechatHomeScroller(
            wheel_steps=5,
            user32=user32,
            platform_name="Windows",
            activation_wait_seconds=0.05,
            wheel_message_interval_seconds=0.02,
            wheel_dispatch_settle_seconds=0.05,
            sleep=lambda seconds: sleeps.append(
                (seconds, user32.foreground_handle)
            ),
        )

        result = scroller.scroll_down(
            _home_window(),
            visible_targets=[_target()],
        )

        self.assertTrue(result)
        self.assertEqual(user32.set_foreground_calls, [100, 900])
        self.assertEqual(user32.foreground_handle, 900)
        self.assertEqual(len(user32.posted_messages), 5)
        self.assertTrue(
            all(item[0] == 220 for item in user32.posted_messages)
        )
        self.assertEqual(
            [_signed_wheel_delta(item[2]) for item in user32.posted_messages],
            [-120, -120, -120, -120, -120],
        )
        self.assertEqual(user32.foregrounds_during_posts, [100] * 5)
        self.assertTrue(sleeps)
        self.assertTrue(all(foreground == 100 for _, foreground in sleeps))

    def test_scroll_up_sends_positive_standard_wheel_steps(self) -> None:
        user32 = _FakeUser32(
            render_handle=220,
            home_handle=100,
            foreground_handle=900,
        )
        scroller = WechatHomeScroller(
            user32=user32,
            platform_name="Windows",
            activation_wait_seconds=0,
            wheel_message_interval_seconds=0,
            wheel_dispatch_settle_seconds=0,
            sleep=lambda _seconds: None,
        )

        result = scroller.scroll(
            _home_window(),
            visible_targets=[],
            direction="up",
            wheel_steps=2,
        )

        self.assertTrue(result)
        self.assertEqual(
            [_signed_wheel_delta(item[2]) for item in user32.posted_messages],
            [120, 120],
        )
        self.assertEqual(user32.foreground_handle, 900)

    def test_scroll_restores_previous_window_when_wheel_dispatch_raises(self) -> None:
        user32 = _FakeUser32(
            render_handle=220,
            home_handle=100,
            foreground_handle=900,
            fail_post_at=2,
        )
        scroller = WechatHomeScroller(
            user32=user32,
            platform_name="Windows",
            activation_wait_seconds=0,
            wheel_message_interval_seconds=0,
            wheel_dispatch_settle_seconds=0,
            sleep=lambda _seconds: None,
        )

        with self.assertRaisesRegex(RuntimeError, "wheel dispatch failed"):
            scroller.scroll_down(_home_window(), visible_targets=[])

        self.assertEqual(user32.set_foreground_calls, [100, 900])
        self.assertEqual(user32.foreground_handle, 900)

    def test_scroll_stops_when_home_cannot_become_foreground(self) -> None:
        user32 = _FakeUser32(
            render_handle=220,
            home_handle=100,
            foreground_handle=900,
            allow_home_activation=False,
        )
        scroller = WechatHomeScroller(
            user32=user32,
            platform_name="Windows",
            activation_wait_seconds=0,
            wheel_message_interval_seconds=0,
            wheel_dispatch_settle_seconds=0,
            sleep=lambda _seconds: None,
        )

        result = scroller.scroll_down(_home_window(), visible_targets=[])

        self.assertFalse(result)
        self.assertEqual(user32.posted_messages, [])
        self.assertEqual(user32.foreground_handle, 900)

    def test_scroll_does_not_override_a_window_selected_during_dispatch(self) -> None:
        user32 = _FakeUser32(
            render_handle=220,
            home_handle=100,
            foreground_handle=900,
            switch_foreground_at_post=2,
            switched_foreground_handle=901,
        )
        scroller = WechatHomeScroller(
            wheel_steps=3,
            user32=user32,
            platform_name="Windows",
            activation_wait_seconds=0,
            wheel_message_interval_seconds=0,
            wheel_dispatch_settle_seconds=0,
            sleep=lambda _seconds: None,
        )

        result = scroller.scroll_down(_home_window(), visible_targets=[])

        self.assertTrue(result)
        self.assertEqual(user32.set_foreground_calls, [100])
        self.assertEqual(user32.foreground_handle, 901)


def _home_window() -> WindowInfo:
    return WindowInfo(
        handle=100,
        title="WeChat",
        class_name="Chrome_WidgetWin_0",
        process_name="WeChatAppEx.exe",
        rect=(0, 0, 800, 1200),
    )


def _target() -> ArticleTarget:
    return ArticleTarget(
        account_name="account",
        title="article",
        click_x=400,
        click_y=600,
        home_window_handle=100,
        fingerprint="article-1",
        metric_text="read 10",
        metric_rect=(350, 580, 450, 620),
    )


def _signed_wheel_delta(wparam: int) -> int:
    value = (int(wparam) >> 16) & 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class _FakeUser32:
    def __init__(
        self,
        *,
        render_handle: int,
        home_handle: int,
        foreground_handle: int,
        fail_post_at: int | None = None,
        allow_home_activation: bool = True,
        switch_foreground_at_post: int | None = None,
        switched_foreground_handle: int = 0,
    ) -> None:
        self.render_handle = render_handle
        self.home_handle = home_handle
        self.foreground_handle = foreground_handle
        self.fail_post_at = fail_post_at
        self.allow_home_activation = allow_home_activation
        self.switch_foreground_at_post = switch_foreground_at_post
        self.switched_foreground_handle = switched_foreground_handle
        self.set_foreground_calls: list[int] = []
        self.posted_messages: list[tuple[int, int, int, int]] = []
        self.foregrounds_during_posts: list[int] = []

    def SetThreadDpiAwarenessContext(self, _context: object) -> None:
        return None

    def IsWindow(self, handle: int) -> int:
        return int(handle > 0)

    def IsIconic(self, _handle: int) -> int:
        return 0

    def ShowWindow(self, _handle: int, _command: int) -> int:
        return 1

    def BringWindowToTop(self, _handle: int) -> int:
        return 1

    def SetForegroundWindow(self, handle: int) -> int:
        self.set_foreground_calls.append(handle)
        if handle != self.home_handle or self.allow_home_activation:
            self.foreground_handle = handle
        return 1

    def GetForegroundWindow(self) -> int:
        return self.foreground_handle

    def SetFocus(self, _handle: int) -> int:
        return 1

    def GetWindowThreadProcessId(self, handle: int, _process_id: object) -> int:
        return handle + 1000

    def AttachThreadInput(
        self,
        _current_thread: int,
        _target_thread: int,
        _attach: bool,
    ) -> int:
        return 1

    def FindWindowExW(
        self,
        parent: int,
        _child_after: int,
        class_name: str,
        _window_name: object,
    ) -> int:
        if parent == self.home_handle and class_name == "Chrome_RenderWidgetHostHWND":
            return self.render_handle
        return 0

    def GetAncestor(self, handle: int, _flag: int) -> int:
        return self.home_handle if handle == self.render_handle else handle

    def IsChild(self, parent: int, child: int) -> int:
        return int(parent == self.home_handle and child == self.render_handle)

    def PostMessageW(
        self,
        handle: int,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        post_number = len(self.posted_messages) + 1
        if self.fail_post_at == post_number:
            raise RuntimeError("wheel dispatch failed")
        self.posted_messages.append((handle, message, wparam, lparam))
        self.foregrounds_during_posts.append(self.foreground_handle)
        if self.switch_foreground_at_post == post_number:
            self.foreground_handle = self.switched_foreground_handle
        return 1


if __name__ == "__main__":
    unittest.main()
