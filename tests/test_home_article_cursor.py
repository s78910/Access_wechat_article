from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from src.domain.models import ArticleTarget
from src.modules.window.home_article_cursor import HomeArticleCursor
from src.modules.window.window_models import WindowInfo
from src.services.capture.window_runtime_factory import WindowRuntimeFactory


class HomeArticleCursorScrollAnchorTests(unittest.TestCase):
    def test_loading_candidate_is_accepted_after_two_matching_snapshots(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        following = _target(
            "懒加载后新文章",
            "following",
            metric_text="阅读 18",
            click_y=260,
        )
        reader = _SequenceViewportReader(
            [
                ([anchor], False),
                ([following], True),
                ([following], True),
            ]
        )
        clock = _FakeClock()
        events: list[dict[str, object]] = []
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            scroller=_FakeScroller(),
            max_scroll_attempts=1,
            scroll_wait_seconds=0,
            scroll_probe_interval_seconds=0.01,
            scroll_probe_max_interval_seconds=0.02,
            scroll_settle_timeout_seconds=0.2,
            lazy_load_timeout_seconds=0.2,
            unchanged_before_bounce_seconds=0.2,
            bounce_enabled=False,
            trace=events.append,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), following)
        self.assertEqual(reader.read_count, 3)
        probe_event = next(item for item in events if item["event"] == "scroll-probe")
        self.assertTrue(probe_event["details"]["loadingObserved"])

    def test_loading_timeout_uses_bounce_and_continues_reading(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        following = _target(
            "回弹后新文章",
            "following",
            metric_text="阅读 28",
            click_y=260,
        )
        reader = _SequenceViewportReader(
            [
                ([anchor], False),
                ([anchor], True),
                ([following], False),
                ([following], False),
            ]
        )
        clock = _FakeClock()
        scroller = _FakeScroller()
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            scroller=scroller,
            max_scroll_attempts=2,
            scroll_wait_seconds=0,
            scroll_probe_interval_seconds=0.01,
            scroll_probe_max_interval_seconds=0.02,
            scroll_settle_timeout_seconds=0,
            lazy_load_timeout_seconds=0,
            unchanged_before_bounce_seconds=0,
            bounce_enabled=True,
            bounce_attempts=2,
            bounce_up_steps=2,
            bounce_down_steps=6,
            bounce_pause_seconds=0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), following)
        self.assertEqual(
            scroller.requests,
            [("down", None), ("up", 2), ("down", 6)],
        )
        self.assertEqual(cursor.diagnostics["bounce_count"], 1)

    def test_loading_timeout_stops_only_after_all_bounces_are_exhausted(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        reader = _SequenceViewportReader(
            [
                ([anchor], False),
                ([anchor], True),
            ]
        )
        clock = _FakeClock()
        scroller = _FakeScroller()
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            scroller=scroller,
            max_scroll_attempts=2,
            scroll_wait_seconds=0,
            scroll_probe_interval_seconds=0.01,
            scroll_probe_max_interval_seconds=0.02,
            scroll_settle_timeout_seconds=0,
            lazy_load_timeout_seconds=0,
            unchanged_before_bounce_seconds=0,
            bounce_enabled=True,
            bounce_attempts=2,
            bounce_up_steps=2,
            bounce_down_steps=6,
            bounce_pause_seconds=0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertIsNone(cursor.next_candidate(_HOME_WINDOW))
        self.assertEqual(
            scroller.requests,
            [
                ("down", None),
                ("up", 2),
                ("down", 6),
                ("up", 2),
                ("down", 6),
            ],
        )
        self.assertEqual(cursor.diagnostics["bounce_count"], 2)

    def test_scroll_waits_through_empty_transition_snapshot(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        following = _target(
            "滚动后真正的新文章",
            "following",
            metric_text="阅读 18",
            click_y=260,
        )
        reader = _SequenceReader([[anchor], [], [following], [following]])
        clock = _FakeClock()
        scroller = _FakeScroller()
        cursor = _cursor(reader=reader, scroller=scroller, clock=clock)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), following)
        self.assertEqual(scroller.calls, 1)

    def test_scroll_skips_truncated_copy_of_previous_viewport_anchor(self) -> None:
        first = _target("第一篇文章", "first", metric_text="阅读 11", click_y=100)
        anchor = _target(
            "这是上一视口最后一篇完整文章标题",
            "anchor-full",
            metric_text="阅读 42 赞 3",
            click_y=300,
        )
        truncated_anchor = _target(
            "最后一篇完整文章标题",
            "anchor-truncated",
            metric_text="阅读 42 赞 3",
            click_y=80,
        )
        following = _target(
            "滚动后真正的新文章",
            "following",
            metric_text="阅读 18",
            click_y=260,
        )
        reader = _SequenceReader(
            [
                [first, anchor],
                [truncated_anchor, following],
                [truncated_anchor, following],
            ]
        )
        clock = _FakeClock()
        scroller = _FakeScroller()
        cursor = _cursor(reader=reader, scroller=scroller, clock=clock)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), first)
        cursor.mark_processed(first)
        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), following)
        self.assertEqual(scroller.calls, 1)

    def test_scroll_waits_for_two_matching_snapshots_before_accepting_candidate(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        transient = _target(
            "新文章标题残片",
            "new-transient",
            metric_text="阅读 20",
            click_y=180,
        )
        stable = _target(
            "这是滚动后完整的新文章标题",
            "new-stable",
            metric_text="阅读 20",
            click_y=180,
        )
        reader = _SequenceReader([[anchor], [transient], [stable], [stable]])
        clock = _FakeClock()
        cursor = _cursor(
            reader=reader,
            scroller=_FakeScroller(),
            clock=clock,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), stable)
        self.assertEqual(reader.read_count, 4)

    def test_scroll_accepts_stable_article_identity_while_coordinates_change(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        moving = _target(
            "滚动后新文章",
            "moving-first",
            metric_text="阅读 20",
            click_y=220,
        )
        latest = replace(
            moving,
            fingerprint="moving-latest",
            click_y=180,
            title_rect=(50, 120, 250, 160),
            metric_rect=(70, 170, 160, 190),
        )
        reader = _SequenceReader([[anchor], [moving], [latest]])
        clock = _FakeClock()
        cursor = _cursor(
            reader=reader,
            scroller=_FakeScroller(),
            clock=clock,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), latest)
        self.assertEqual(reader.read_count, 3)


class HomeArticleCursorSemanticSignatureTests(unittest.TestCase):
    def test_same_date_containing_titles_are_distinct_articles(self) -> None:
        first = _target(
            "大喜男生35岁之后可以继续申请国自然",
            "first",
            metric_text="阅读 10",
            click_y=200,
        )
        second = _target(
            "男生35岁之后可以继续申请国自然",
            "second",
            metric_text="阅读 20",
            click_y=400,
        )
        reader = _SequenceReader([[first, second]])
        clock = _FakeClock()
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            scroller=None,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), first)
        cursor.mark_processed(first)

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), second)

    def test_same_article_ignores_metric_text_fingerprint_and_coordinates(self) -> None:
        first = _target("同一篇文章", "first", metric_text="阅读 10", click_y=200)
        latest = replace(
            first,
            fingerprint="latest",
            metric_text="阅读 11 赞 1",
            click_y=120,
            title_rect=(50, 60, 250, 100),
            metric_rect=(70, 110, 160, 130),
        )

        self.assertTrue(HomeArticleCursor._same_article(first, latest))

    def test_same_title_on_different_dates_is_not_the_same_article(self) -> None:
        first = _target("同名文章", "first", metric_text="阅读 10", click_y=200)
        another_day = replace(
            first,
            fingerprint="another-day",
            date_text="8月5日",
            published_date="2026-08-05",
        )

        self.assertFalse(HomeArticleCursor._same_article(first, another_day))

    def test_content_signature_uses_raw_title_and_date_only(self) -> None:
        first = _target("同一篇文章", "first", metric_text="阅读 10", click_y=200)
        latest = replace(
            first,
            fingerprint="latest",
            metric_text="阅读 11",
            click_y=120,
            title_rect=(50, 60, 250, 100),
            metric_rect=(70, 110, 160, 130),
        )

        self.assertEqual(
            HomeArticleCursor._content_signature([first]),
            HomeArticleCursor._content_signature([latest]),
        )

    def test_refresh_target_reads_latest_coordinates_before_returning(self) -> None:
        first = _target("待点击文章", "first", metric_text="阅读 10", click_y=200)
        latest = replace(
            first,
            fingerprint="latest",
            click_y=120,
            title_rect=(50, 60, 250, 100),
            metric_rect=(70, 110, 160, 130),
        )
        reader = _SequenceReader([[first], [latest]])
        clock = _FakeClock()
        cursor = _cursor(
            reader=reader,
            scroller=_FakeScroller(),
            clock=clock,
        )

        cursor.refresh_visible(_HOME_WINDOW)

        self.assertEqual(cursor.refresh_target(_HOME_WINDOW, first), latest)
        self.assertEqual(reader.read_count, 2)


class HomeArticleCursorTraceTests(unittest.TestCase):
    def test_reports_viewport_read_and_discarded_candidate_once_per_snapshot(self) -> None:
        target = _target("完整文章", "first", metric_text="阅读 10", click_y=200)
        discarded = {
            "status": "discarded",
            "titleFragment": "被裁切的标题片段",
            "dateText": "8月6日",
            "metricText": "阅读 8",
            "reason": "阅读指标没有完整位于主页可视区",
        }
        reader = _TraceViewportReader(
            [
                ([target], False, 7, [discarded]),
                ([target], False, 7, [discarded]),
            ]
        )
        events: list[dict[str, object]] = []
        clock = _FakeClock()
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            trace=events.append,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        cursor.refresh_visible(_HOME_WINDOW)
        cursor.refresh_visible(_HOME_WINDOW)

        read_events = [item for item in events if item["event"] == "viewport-read"]
        self.assertEqual(len(read_events), 1)
        self.assertEqual(read_events[0]["details"]["rangeCount"], 7)
        self.assertEqual(read_events[0]["details"]["targetCount"], 1)
        self.assertEqual(read_events[0]["details"]["discardedCount"], 1)
        self.assertEqual(read_events[0]["decisions"], [discarded])

    def test_reports_scroll_steps_and_probe_result_in_execution_order(self) -> None:
        anchor = _target("上一视口文章", "anchor", metric_text="阅读 8", click_y=280)
        following = _target("滚动后文章", "following", metric_text="阅读 18", click_y=260)
        reader = _TraceViewportReader(
            [
                ([anchor], False, 3, []),
                ([following], False, 3, []),
                ([following], False, 3, []),
            ]
        )
        events: list[dict[str, object]] = []
        clock = _FakeClock()
        cursor = HomeArticleCursor(
            reader=reader,
            account_name="测试公众号",
            scroller=_FakeScroller(wheel_steps=5),
            trace=events.append,
            max_scroll_attempts=1,
            scroll_wait_seconds=0,
            scroll_probe_interval_seconds=0.01,
            scroll_probe_max_interval_seconds=0.02,
            scroll_settle_timeout_seconds=0.2,
            lazy_load_timeout_seconds=0.2,
            unchanged_before_bounce_seconds=0.2,
            bounce_enabled=False,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), anchor)
        cursor.mark_processed(anchor)
        self.assertEqual(cursor.next_candidate(_HOME_WINDOW), following)

        event_names = [item["event"] for item in events]
        self.assertEqual(
            event_names,
            ["viewport-read", "scroll-dispatch", "viewport-read", "scroll-probe"],
        )
        scroll_event = events[1]
        self.assertEqual(scroll_event["details"]["direction"], "down")
        self.assertEqual(scroll_event["details"]["wheelSteps"], 5)
        self.assertTrue(scroll_event["details"]["succeeded"])
        probe_event = events[-1]
        self.assertEqual(probe_event["details"]["result"], "candidate")
        self.assertEqual(probe_event["details"]["probeCount"], 2)


class WindowRuntimeFactoryTraceTests(unittest.TestCase):
    def test_create_cursor_passes_optional_trace_callback(self) -> None:
        trace = lambda _event: None
        window = SimpleNamespace(
            scroll_wheel_steps=5,
            activation_wait_seconds=0.05,
            max_scroll_attempts=6,
            scroll_initial_delay_seconds=0.05,
            scroll_probe_interval_seconds=0.1,
            scroll_probe_max_interval_seconds=0.3,
            scroll_settle_timeout_seconds=0.6,
            lazy_load_timeout_seconds=3.0,
            unchanged_before_bounce_seconds=0.6,
            visible_snapshot_max_age_seconds=60.0,
            bounce_enabled=True,
            bounce_attempts=2,
            bounce_up_steps=2,
            bounce_down_steps=6,
            bounce_pause_seconds=0.2,
            restore_focus_after_close=True,
        )
        factory = WindowRuntimeFactory(
            SimpleNamespace(window=window),
            scroller_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            cursor_factory=lambda **kwargs: kwargs,
        )

        cursor_options = factory.create_cursor(
            reader=object(),
            account_name="测试公众号",
            trace=trace,
        )

        self.assertIs(cursor_options["trace"], trace)


class _SequenceReader:
    def __init__(self, viewports: list[list[ArticleTarget]]) -> None:
        self._viewports = viewports
        self.read_count = 0

    def read(
        self,
        _home_window: WindowInfo,
        *,
        account_name: str = "",
    ) -> list[ArticleTarget]:
        del account_name
        index = min(self.read_count, len(self._viewports) - 1)
        self.read_count += 1
        return list(self._viewports[index])


class _SequenceViewportReader:
    def __init__(
        self,
        viewports: list[tuple[list[ArticleTarget], bool]],
    ) -> None:
        self._viewports = viewports
        self.read_count = 0

    def read_viewport(
        self,
        _home_window: WindowInfo,
        *,
        account_name: str = "",
    ) -> object:
        del account_name
        index = min(self.read_count, len(self._viewports) - 1)
        self.read_count += 1
        targets, loading = self._viewports[index]
        signature = tuple(
            f"{target.raw_title}\n{target.published_date}"
            for target in targets
        )
        return SimpleNamespace(
            targets=tuple(targets),
            visible_signature=signature,
            loading=loading,
        )


class _TraceViewportReader:
    def __init__(
        self,
        viewports: list[
            tuple[list[ArticleTarget], bool, int, list[dict[str, object]]]
        ],
    ) -> None:
        self._viewports = viewports
        self.read_count = 0

    def read_viewport(
        self,
        _home_window: WindowInfo,
        *,
        account_name: str = "",
    ) -> object:
        del account_name
        index = min(self.read_count, len(self._viewports) - 1)
        self.read_count += 1
        targets, loading, range_count, decisions = self._viewports[index]
        signature = tuple(
            f"{target.raw_title}\n{target.published_date}"
            for target in targets
        )
        return SimpleNamespace(
            targets=tuple(targets),
            visible_signature=signature,
            loading=loading,
            range_count=range_count,
            decisions=tuple(decisions),
        )


class _FakeScroller:
    def __init__(self, *, wheel_steps: int = 5) -> None:
        self.calls = 0
        self.wheel_steps = wheel_steps
        self.requests: list[tuple[str, int | None]] = []

    def scroll(
        self,
        _home_window: WindowInfo,
        *,
        visible_targets: list[ArticleTarget],
        direction: str,
        wheel_steps: int | None = None,
    ) -> bool:
        del visible_targets
        self.calls += 1
        self.requests.append((direction, wheel_steps))
        return True


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, seconds)


def _cursor(
    *,
    reader: _SequenceReader,
    scroller: _FakeScroller,
    clock: _FakeClock,
) -> HomeArticleCursor:
    return HomeArticleCursor(
        reader=reader,
        account_name="测试公众号",
        scroller=scroller,
        max_scroll_attempts=1,
        scroll_wait_seconds=0,
        scroll_probe_interval_seconds=0.01,
        scroll_probe_max_interval_seconds=0.02,
        scroll_settle_timeout_seconds=0.2,
        lazy_load_timeout_seconds=0.2,
        unchanged_before_bounce_seconds=0.2,
        bounce_enabled=False,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def _target(
    title: str,
    fingerprint: str,
    *,
    metric_text: str,
    click_y: int,
) -> ArticleTarget:
    return ArticleTarget(
        account_name="测试公众号",
        title=title,
        raw_title=title,
        click_x=100,
        click_y=click_y,
        home_window_handle=_HOME_WINDOW.handle,
        fingerprint=fingerprint,
        date_text="8月6日",
        published_date="2026-08-06",
        title_rect=(50, click_y - 60, 250, click_y - 20),
        metric_text=metric_text,
        metric_rect=(70, click_y - 10, 160, click_y + 10),
    )


_HOME_WINDOW = WindowInfo(
    handle=100,
    title="测试公众号",
    class_name="Chrome_WidgetWin_0",
    process_name="WeChatAppEx.exe",
    rect=(0, 0, 600, 800),
)


if __name__ == "__main__":
    unittest.main()
