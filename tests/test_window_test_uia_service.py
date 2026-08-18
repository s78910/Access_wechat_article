from __future__ import annotations

from types import SimpleNamespace
import unittest

from src.modules.window.uia_window_test_reader import (
    UiaWindowTestArticleCard,
    UiaWindowTestDateGroup,
    UiaWindowTestDateGroupHeader,
    UiaWindowTestDateSnapshot,
    UiaWindowTestSnapshot,
)
from src.services.runtime.window_click_flow_diagnostic_service import (
    WindowClickFlowDiagnosticService,
)


class WindowTestUiaServiceTests(unittest.TestCase):
    def test_date_location_scales_wheel_steps_by_remaining_days(self) -> None:
        cases = (
            ("2026-07-01", 18),
            ("2026-08-05", 12),
            ("2026-08-10", 6),
            ("2026-08-13", 3),
        )
        for target_date, expected_steps in cases:
            with self.subTest(target_date=target_date):
                factory = _FakeWindowFactory(
                    [
                        _snapshot(
                            _card(
                                target_date[5:].replace("-", "月") + "日",
                                "目标文章",
                                published_date=target_date,
                            )
                        )
                    ],
                    date_snapshots=[
                        _date_snapshot("8月15日", "2026-08-15"),
                        _date_snapshot("目标日期", target_date),
                    ],
                )

                result = _service(factory).run(
                    max_records=1,
                    date_filter_mode="after",
                    start_date=target_date,
                )

                self.assertEqual(result["status"], "completed")
                self.assertEqual(
                    factory.scroller.actions,
                    [("down", expected_steps)],
                )

    def test_date_range_locates_end_date_before_reading_article_cards(self) -> None:
        factory = _FakeWindowFactory(
            [
                _snapshot(
                    _card(
                        "8月10日",
                        "范围内文章",
                        published_date="2026-08-10",
                    )
                )
            ],
            date_snapshots=[
                _date_snapshot("8月15日", "2026-08-15"),
                _date_snapshot("8月10日", "2026-08-10"),
            ],
        )

        result = _service(factory).run(
            max_records=1,
            date_filter_mode="range",
            start_date="2026-08-01",
            end_date="2026-08-10",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.snapshot_reader.date_read_count, 2)
        self.assertEqual(factory.snapshot_reader.read_count, 1)
        self.assertEqual(factory.scroller.actions, [("down", 6)])

    def test_date_location_waits_until_observed_loading_finishes(self) -> None:
        factory = _FakeWindowFactory(
            [
                _snapshot(
                    _card(
                        "8月5日",
                        "加载完成后的文章",
                        published_date="2026-08-05",
                    )
                )
            ],
            date_snapshots=[
                _date_snapshot("8月15日", "2026-08-15"),
                _date_snapshot("8月5日", "2026-08-05", loading=True),
                _date_snapshot("8月5日", "2026-08-05", loading=False),
            ],
        )

        result = _service(factory).run(
            max_records=1,
            date_filter_mode="after",
            start_date="2026-08-05",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.snapshot_reader.date_read_count, 3)

    def test_date_location_loading_timeout_uses_bounce_instead_of_next_fast_scroll(self) -> None:
        factory = _FakeWindowFactory(
            [_snapshot(_card("8月5日", "不应进入收录"))],
            date_snapshots=[
                _date_snapshot("8月15日", "2026-08-15"),
                _date_snapshot("8月5日", "2026-08-05", loading=True),
            ],
        )

        result = _service(
            factory,
            unchanged_before_bounce_seconds=0,
            lazy_load_timeout_seconds=0,
        ).run(
            max_records=1,
            date_filter_mode="after",
            start_date="2026-08-05",
        )

        self.assertEqual(result["status"], "date-not-found")
        self.assertEqual(
            factory.scroller.actions,
            [
                ("down", 12),
                ("up", 2),
                ("down", 6),
                ("up", 2),
                ("down", 6),
            ],
        )

    def test_normal_scroll_waits_until_observed_loading_finishes(self) -> None:
        first = _card("8月7日", "第一篇")
        second = _card("8月7日", "第二篇", top=200)
        factory = _FakeWindowFactory(
            [
                _snapshot(first),
                _snapshot(first, second, loading=True),
                _snapshot(first, second, loading=False),
            ]
        )

        result = _service(factory).run(max_records=2)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.snapshot_reader.read_count, 3)

    def test_start_date_uses_loaded_offscreen_group_without_extra_scroll(self) -> None:
        visible = _date_group_header("8月9日", "2026-08-09", top=100)
        loaded_below = _date_group_header(
            "8月8日",
            "2026-08-08",
            top=520,
            visible=False,
        )
        factory = _FakeWindowFactory(
            [
                _snapshot(
                    _card(
                        "8月8日",
                        "target article",
                        published_date="2026-08-08",
                    )
                )
            ],
            date_snapshots=[_date_snapshot_from_groups(visible, loaded_below)],
        )

        result = _service(factory, unchanged_before_bounce_seconds=0).run(
            max_records=1,
            date_filter_mode="after",
            start_date="2026-08-08",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.scroller.actions, [])

    def test_start_date_locates_first_older_group_before_reading_article_cards(self) -> None:
        factory = _FakeWindowFactory(
            [
                _snapshot(
                    _card(
                        "8月9日",
                        "目标日期缺失后第一篇",
                        published_date="2026-08-09",
                    )
                )
            ],
            date_snapshots=[
                _date_snapshot("8月12日", "2026-08-12"),
                _date_snapshot("8月9日", "2026-08-09"),
            ],
        )

        result = _service(factory).run(
            max_records=1,
            date_filter_mode="after",
            start_date="2026-08-10",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.snapshot_reader.date_read_count, 2)
        self.assertEqual(factory.snapshot_reader.read_count, 1)
        self.assertEqual(factory.scroller.actions, [("down", 3)])
        self.assertEqual(
            [record["rawTitle"] for record in result["records"]],
            ["目标日期缺失后第一篇"],
        )

    def test_cutoff_date_with_zero_limit_records_current_page_through_boundary(self) -> None:
        factory = _FakeWindowFactory(
            [
                _snapshot(
                    _card("8月12日", "当前页文章", published_date="2026-08-12"),
                    _card("8月10日", "截止日文章", top=200, published_date="2026-08-10"),
                    _card("8月9日", "边界外文章", top=300, published_date="2026-08-09"),
                )
            ]
        )

        result = _service(factory).run(
            max_records=0,
            date_filter_mode="before",
            end_date="2026-08-10",
        )

        self.assertEqual(result["status"], "date-boundary")
        self.assertEqual(result["maxRecords"], 0)
        self.assertEqual(
            [record["rawTitle"] for record in result["records"]],
            ["当前页文章", "截止日文章"],
        )

    def test_activates_home_and_records_first_snapshot_without_old_cursor(self) -> None:
        factory = _FakeWindowFactory([_snapshot(_card("8月7日", "第一篇"), _card("8月7日", "第二篇", top=200))])

        result = _service(factory).run(max_records=2)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.guard.activation_count, 1)
        self.assertEqual(factory.snapshot_reader.read_count, 1)
        self.assertEqual(
            [record["rawTitle"] for record in result["records"]],
            ["第一篇", "第二篇"],
        )
        self.assertFalse(factory.old_cursor_requested)

    def test_scroll_snapshot_appends_only_cards_after_last_date_title_marker(self) -> None:
        first = _card("8月7日", "第一篇")
        second = _card("8月7日", "第二篇", top=200)
        factory = _FakeWindowFactory(
            [
                _snapshot(first),
                _snapshot(first, second),
            ]
        )

        result = _service(factory).run(max_records=2)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(factory.scroller.actions, [("down", 3)])
        self.assertEqual(factory.snapshot_reader.read_count, 2)
        self.assertEqual(
            [record["rawTitle"] for record in result["records"]],
            ["第一篇", "第二篇"],
        )

    def test_no_new_card_triggers_bounce_then_reads_following_card(self) -> None:
        first = _card("8月7日", "第一篇")
        second = _card("8月7日", "第二篇", top=200)
        factory = _FakeWindowFactory(
            [
                _snapshot(first),
                _snapshot(first),
                _snapshot(first, second),
            ]
        )

        result = _service(factory, unchanged_before_bounce_seconds=0).run(max_records=2)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            factory.scroller.actions,
            [("down", 3), ("up", 2), ("down", 6)],
        )
        self.assertEqual(factory.snapshot_reader.read_count, 3)
        self.assertEqual(result["records"][-1]["rawTitle"], "第二篇")


class _FakeGuard:
    def __init__(self) -> None:
        self.activation_count = 0

    def activate(self, _home_window: object) -> None:
        self.activation_count += 1


class _FakeSnapshotReader:
    def __init__(
        self,
        snapshots: list[UiaWindowTestSnapshot],
        *,
        date_snapshots: list[object] | None = None,
    ) -> None:
        self._snapshots = list(snapshots)
        self._date_snapshots = list(date_snapshots or [])
        self.read_count = 0
        self.date_read_count = 0

    def read(self, _home_window: object) -> UiaWindowTestSnapshot:
        self.read_count += 1
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]

    def read_date_groups(self, _home_window: object) -> object:
        self.date_read_count += 1
        if not self._date_snapshots:
            raise AssertionError("当前测试没有提供日期组快照")
        if len(self._date_snapshots) > 1:
            return self._date_snapshots.pop(0)
        return self._date_snapshots[0]


class _FakeScroller:
    def __init__(self) -> None:
        self.actions: list[tuple[str, int]] = []

    def scroll_down(self, _home_window: object, *, visible_targets: list[object]) -> bool:
        del visible_targets
        self.actions.append(("down", 3))
        return True

    def scroll(
        self,
        _home_window: object,
        *,
        visible_targets: list[object],
        direction: str,
        wheel_steps: int,
    ) -> bool:
        del visible_targets
        self.actions.append((direction, wheel_steps))
        return True


class _FakeWindowFactory:
    def __init__(
        self,
        snapshots: list[UiaWindowTestSnapshot],
        *,
        date_snapshots: list[object] | None = None,
    ) -> None:
        self.guard = _FakeGuard()
        self.snapshot_reader = _FakeSnapshotReader(
            snapshots,
            date_snapshots=date_snapshots,
        )
        self.scroller = _FakeScroller()
        self.old_cursor_requested = False

    def create_reader(self) -> object:
        return object()

    def find_home_window(self, **_kwargs: object) -> object:
        return SimpleNamespace(handle=100)

    def create_home_guard(self) -> _FakeGuard:
        return self.guard

    def create_home_reader(self) -> object:
        return SimpleNamespace(
            read=lambda _window: SimpleNamespace(account_name="测试公众号")
        )

    def create_window_test_reader(self) -> _FakeSnapshotReader:
        return self.snapshot_reader

    def create_scroller(self) -> _FakeScroller:
        return self.scroller

    def create_cursor(self, **_kwargs: object) -> object:
        self.old_cursor_requested = True
        raise AssertionError("窗口测试不应再创建 HomeArticleCursor")


def _service(
    factory: _FakeWindowFactory,
    *,
    unchanged_before_bounce_seconds: float = 0.6,
    lazy_load_timeout_seconds: float = 3.0,
) -> WindowClickFlowDiagnosticService:
    window = SimpleNamespace(
        home_find_timeout_seconds=1.0,
        scroll_wheel_steps=3,
        date_seek_max_steps=18,
        scroll_initial_delay_seconds=0.0,
        scroll_probe_interval_seconds=0.0,
        scroll_probe_max_interval_seconds=0.0,
        lazy_load_timeout_seconds=lazy_load_timeout_seconds,
        unchanged_before_bounce_seconds=unchanged_before_bounce_seconds,
        bounce_enabled=True,
        bounce_attempts=2,
        bounce_up_steps=2,
        bounce_down_steps=6,
        bounce_pause_seconds=0.0,
    )
    return WindowClickFlowDiagnosticService(
        config=SimpleNamespace(window=window),
        window_factory=factory,
    )


def _card(
    date_text: str,
    title: str,
    *,
    top: int = 100,
    published_date: str = "2026-08-07",
) -> UiaWindowTestArticleCard:
    visible_rect = (80, top, 420, top + 80)
    return UiaWindowTestArticleCard(
        date_text=date_text,
        published_date=published_date,
        raw_title=title,
        title=title,
        date_rect=(80, 70, 140, 90),
        title_rect=(100, top + 10, 320, top + 40),
        card_rect=visible_rect,
        visible_rect=visible_rect,
        visible_height=80,
        click_point=(250, top + 40),
    )


def _snapshot(
    *cards: UiaWindowTestArticleCard,
    loading: bool = False,
) -> UiaWindowTestSnapshot:
    group = UiaWindowTestDateGroup(
        date_text="8月7日",
        published_date="2026-08-07",
        date_rect=(80, 70, 140, 90),
        group_rect=(60, 65, 440, 500),
        cards=tuple(cards),
    )
    return UiaWindowTestSnapshot(
        groups=(group,),
        all_cards=tuple(cards),
        visible_cards=tuple(cards),
        content_viewport=(0, 60, 500, 500),
        node_count=20,
        loading=loading,
    )


def _date_snapshot(
    date_text: str,
    published_date: str,
    *,
    loading: bool = False,
) -> object:
    group = _date_group_header(date_text, published_date)
    return _date_snapshot_from_groups(group, loading=loading)


def _date_group_header(
    date_text: str,
    published_date: str,
    *,
    top: int = 70,
    visible: bool = True,
) -> UiaWindowTestDateGroupHeader:
    group_rect = (60, top, 440, top + 80)
    return UiaWindowTestDateGroupHeader(
        date_text=date_text,
        published_date=published_date,
        date_rect=(80, top + 5, 140, top + 25),
        group_rect=group_rect,
        visible_rect=group_rect if visible else None,
    )


def _date_snapshot_from_groups(
    *groups: UiaWindowTestDateGroupHeader,
    loading: bool = False,
) -> UiaWindowTestDateSnapshot:
    return UiaWindowTestDateSnapshot(
        groups=tuple(groups),
        visible_groups=tuple(group for group in groups if group.visible_rect is not None),
        content_viewport=(0, 60, 500, 500),
        node_count=10,
        loading=loading,
    )


if __name__ == "__main__":
    unittest.main()
