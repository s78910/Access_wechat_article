from __future__ import annotations

import unittest
from unittest.mock import patch

from src.modules.window import home_article_cursor
from src.modules.window.home_window_focus_guard import ensure_home_window_readable
from src.modules.window.home_article_cursor import HomeArticleCursor, scroll_wechat_home_articles
from src.workers.home_article_clicker import ArticleClickTarget


def make_target(title: str, top: int) -> ArticleClickTarget:
    return ArticleClickTarget(title=title, rect=(100, top, 500, top + 40), hwnd=200)


def make_invalid_target(title: str) -> ArticleClickTarget:
    return ArticleClickTarget(title=title, rect=(0, 0, 0, 0), hwnd=200)


class HomeArticleCursorTest(unittest.TestCase):
    def test_focus_guard_activates_home_window_with_configured_delay(self) -> None:
        calls: list[tuple[object, float]] = []
        home_window = object()

        def activate(window, *, delay_seconds=0):
            calls.append((window, float(delay_seconds)))
            return {"ok": True, "reason": "activated"}

        result = ensure_home_window_readable(
            home_window,
            {"homepage_focus_recover_delay_seconds": 0.2},
            activate_window=activate,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [(home_window, 0.2)])

    def test_focus_guard_can_be_disabled_without_activating_window(self) -> None:
        calls: list[str] = []

        def activate(_window, *, delay_seconds=0):
            calls.append("activate")
            return {"ok": True, "reason": "activated"}

        result = ensure_home_window_readable(
            object(),
            {"homepage_focus_recover_enabled": False},
            activate_window=activate,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(calls, [])

    def test_refresh_visible_candidates_reactivates_home_window_when_first_read_is_empty(self) -> None:
        calls: list[str] = []
        state = {"attempt": 0}

        def collect_targets(_window, **_kwargs):
            state["attempt"] += 1
            calls.append(f"collect_{state['attempt']}")
            if state["attempt"] == 1:
                return []
            return [make_target("focused article", 100)]

        def ensure_readable(_window, _config):
            calls.append("focus_guard")
            return {"ok": True, "reason": "activated"}

        cursor = HomeArticleCursor(
            config={"homepage_focus_recover_attempts": 1},
            home_window=object(),
            collect_targets=collect_targets,
            ensure_home_window_readable=ensure_readable,
        )

        self.assertTrue(cursor.refresh_visible_candidates())
        self.assertEqual(cursor.next_candidate().title, "focused article")
        self.assertEqual(calls, ["collect_1", "focus_guard", "collect_2"])

    def test_next_candidate_scrolls_after_current_screen_is_exhausted(self) -> None:
        pages = [
            [make_target("first", 100), make_target("second", 160)],
            [make_target("third", 100)],
        ]
        state = {"page": 0, "scrolls": 0}

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, _config, **_kwargs):
            state["scrolls"] += 1
            state["page"] = 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={"homepage_scroll_unchanged_limit": 1},
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "first")
        self.assertEqual(cursor.next_candidate().title, "second")
        self.assertEqual(cursor.next_candidate().title, "third")
        self.assertEqual(state["scrolls"], 1)

    def test_next_candidate_ignores_title_targets_without_clickable_rect(self) -> None:
        targets = [
            make_invalid_target("title without rect"),
            make_target("clickable second", 180),
            make_target("clickable first", 100),
        ]

        def collect_targets(_window, **_kwargs):
            return targets

        cursor = HomeArticleCursor(
            home_window=object(),
            collect_targets=collect_targets,
        )

        self.assertEqual(cursor.next_candidate().title, "clickable first")
        self.assertEqual(cursor.next_candidate().title, "clickable second")

    def test_next_candidate_scrolls_when_current_screens_have_no_clickable_titles(self) -> None:
        pages = [
            [make_invalid_target("unclickable first screen")],
            [make_invalid_target("unclickable second screen")],
            [make_target("visible article after scroll", 120)],
        ]
        state = {"page": 0, "scrolls": 0}

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, _config, **_kwargs):
            state["scrolls"] += 1
            state["page"] = min(state["page"] + 1, len(pages) - 1)
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={
                "homepage_scroll_load_timeout_seconds": 0,
                "homepage_scroll_poll_interval_seconds": 0,
                "homepage_scroll_pause_seconds": 0,
                "homepage_scroll_bounce_attempts": 0,
                "homepage_scroll_bounce_pause_seconds": 0,
                "homepage_scroll_empty_limit": 3,
            },
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "visible article after scroll")
        self.assertEqual(state["scrolls"], 2)

    def test_skip_visible_candidates_marks_current_screen_done_before_scrolling(self) -> None:
        pages = [
            [make_target("saved first", 100), make_target("saved second", 160)],
            [make_target("fresh third", 100)],
        ]
        state = {"page": 0, "scrolls": 0}

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, _config, **_kwargs):
            state["scrolls"] += 1
            state["page"] = 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={"homepage_scroll_unchanged_limit": 1},
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertTrue(cursor.refresh_visible_candidates())
        cursor.skip_visible_candidates(titles=["saved first", "saved second"])

        self.assertEqual(cursor.next_candidate().title, "fresh third")
        self.assertEqual(state["scrolls"], 1)

    def test_skip_visible_candidates_uses_fast_scroll_profile_once(self) -> None:
        pages = [
            [make_target("saved first", 100), make_target("saved second", 160)],
            [make_target("fresh third", 100)],
        ]
        state = {"page": 0}
        scroll_configs: list[dict] = []

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, config, **_kwargs):
            scroll_configs.append(dict(config))
            state["page"] = 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={
                "homepage_scroll_unchanged_limit": 1,
                "homepage_scroll_pause_seconds": 0,
                "homepage_fast_skip_scroll_pause_seconds": 0,
                "homepage_fast_skip_load_timeout_seconds": 0,
                "homepage_fast_skip_scroll_delta_ratio": 1.4,
            },
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertTrue(cursor.refresh_visible_candidates())
        cursor.skip_visible_candidates(titles=["saved first", "saved second"])

        self.assertEqual(cursor.next_candidate().title, "fresh third")
        self.assertEqual(scroll_configs[0]["homepage_scroll_delta_ratio"], 1.4)

    def test_next_candidate_stops_when_scroll_does_not_reveal_new_titles(self) -> None:
        targets = [make_target("first", 100)]
        state = {"scrolls": 0}

        def collect_targets(_window, **_kwargs):
            return targets

        def scroll_home(_window, _config, **_kwargs):
            state["scrolls"] += 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={
                "homepage_scroll_unchanged_limit": 1,
                "homepage_scroll_load_timeout_seconds": 0,
                "homepage_scroll_poll_interval_seconds": 0,
                "homepage_scroll_pause_seconds": 0,
                "homepage_scroll_bounce_pause_seconds": 0,
            },
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "first")
        self.assertIsNone(cursor.next_candidate())
        self.assertEqual(state["scrolls"], 3)

    def test_scroll_receives_visible_candidates_for_precise_wheel_target(self) -> None:
        pages = [
            [make_target("first", 100), make_target("second", 160)],
            [make_target("third", 100)],
        ]
        state = {"page": 0}
        received_screens: list[list[str]] = []

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, _config, *, visible_candidates=None):
            received_screens.append([candidate.title for candidate in visible_candidates or []])
            state["page"] = 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={"homepage_scroll_unchanged_limit": 1},
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "first")
        self.assertEqual(cursor.next_candidate().title, "second")
        self.assertEqual(cursor.next_candidate().title, "third")
        self.assertEqual(received_screens, [["first", "second"]])

    def test_next_candidate_keeps_scrolling_through_temporarily_unchanged_screen(self) -> None:
        pages = [
            [make_target("first", 100), make_target("second", 160)],
            [make_target("second", 100), make_target("third", 160)],
            [make_target("second", 100), make_target("third", 160)],
            [make_target("second", 100), make_target("third", 160)],
            [make_target("fourth", 100)],
        ]
        state = {"page": 0, "scrolls": 0}

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, _config, **_kwargs):
            state["scrolls"] += 1
            state["page"] = min(state["page"] + 1, len(pages) - 1)
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={"homepage_scroll_pause_seconds": 0},
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "first")
        self.assertEqual(cursor.next_candidate().title, "second")
        self.assertEqual(cursor.next_candidate().title, "third")
        self.assertEqual(cursor.next_candidate().title, "fourth")
        self.assertEqual(state["scrolls"], 4)

    def test_next_candidate_bounces_scroll_when_new_candidates_do_not_load_in_time(self) -> None:
        pages = [
            [make_target("first", 100)],
            [make_target("first", 100)],
            [make_target("second", 100)],
        ]
        state = {"page": 0, "down_scrolls": 0}
        scroll_calls: list[tuple[str, float]] = []

        def collect_targets(_window, **_kwargs):
            return pages[state["page"]]

        def scroll_home(_window, config, **_kwargs):
            direction = str(config.get("homepage_scroll_direction", "down"))
            ratio = float(config.get("homepage_scroll_delta_ratio", 1.0))
            scroll_calls.append((direction, ratio))
            if direction == "down":
                state["down_scrolls"] += 1
                if state["down_scrolls"] >= 2:
                    state["page"] = 2
            else:
                state["page"] = 1
            return {"ok": True}

        cursor = HomeArticleCursor(
            config={
                "homepage_scroll_load_timeout_seconds": 0,
                "homepage_scroll_poll_interval_seconds": 0,
                "homepage_scroll_pause_seconds": 0,
                "homepage_scroll_bounce_attempts": 1,
                "homepage_scroll_bounce_ratio": 0.5,
                "homepage_scroll_unchanged_limit": 1,
            },
            home_window=object(),
            collect_targets=collect_targets,
            scroll_home=scroll_home,
        )

        self.assertEqual(cursor.next_candidate().title, "first")
        self.assertEqual(cursor.next_candidate().title, "second")
        self.assertEqual(scroll_calls, [("down", 1.0), ("up", 0.5), ("down", 1.0)])

    def test_scroll_supports_upward_half_delta_for_bounce(self) -> None:
        calls: list[tuple[str, int, int]] = []

        class FakeWindow:
            NativeWindowHandle = 123
            BoundingRectangle = (50, 50, 650, 650)

        class FakeUser32:
            def EnumChildWindows(self, _hwnd, _callback, _lparam):
                return True

            def ScreenToClient(self, hwnd, point_ref):
                point_ref._obj.x = 11
                point_ref._obj.y = 22
                calls.append(("screen_to_client", int(hwnd), home_article_cursor._make_lparam(11, 22)))
                return True

            def PostMessageW(self, hwnd, message, wparam, lparam):
                calls.append(("post_message", int(hwnd), int(wparam), int(lparam)))
                return True

        with (
            patch.object(home_article_cursor.platform, "system", return_value="Windows"),
            patch.object(home_article_cursor.ctypes, "windll", create=True) as windll,
        ):
            windll.user32 = FakeUser32()
            result = scroll_wechat_home_articles(
                FakeWindow(),
                {
                    "homepage_scroll_delta": 600,
                    "homepage_scroll_delta_ratio": 0.5,
                    "homepage_scroll_direction": "up",
                    "homepage_scroll_repeat": 1,
                },
                visible_candidates=[make_target("first", 100)],
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["wheel_delta"], 300)
        self.assertIn(
            ("post_message", 123, home_article_cursor._make_wparam(300), home_article_cursor._make_lparam(300, 120)),
            calls,
        )

    def test_mousewheel_message_uses_screen_point_lparam(self) -> None:
        calls: list[tuple[str, int, int]] = []

        class FakeWindow:
            NativeWindowHandle = 123
            BoundingRectangle = (50, 50, 650, 650)

        class FakeUser32:
            def EnumChildWindows(self, _hwnd, _callback, _lparam):
                return True

            def ScreenToClient(self, hwnd, point_ref):
                point_ref._obj.x = 11
                point_ref._obj.y = 22
                calls.append(("screen_to_client", int(hwnd), home_article_cursor._make_lparam(11, 22)))
                return True

            def PostMessageW(self, hwnd, message, _wparam, lparam):
                calls.append(("post_message", int(hwnd), int(lparam)))
                return True

        with (
            patch.object(home_article_cursor.platform, "system", return_value="Windows"),
            patch.object(home_article_cursor.ctypes, "windll", create=True) as windll,
        ):
            windll.user32 = FakeUser32()
            result = scroll_wechat_home_articles(
                FakeWindow(),
                {"homepage_scroll_repeat": 1},
                visible_candidates=[make_target("first", 100)],
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["screen_point"], [300, 120])
        self.assertEqual(result["client_point"], [11, 22])
        self.assertIn(("post_message", 123, home_article_cursor._make_lparam(300, 120)), calls)


if __name__ == "__main__":
    unittest.main()
