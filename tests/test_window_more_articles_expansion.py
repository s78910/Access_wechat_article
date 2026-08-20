from __future__ import annotations

from types import SimpleNamespace
import unittest

from src.modules.window.article_clicker import ArticleClicker
from src.modules.window.uia_window_test_reader import (
    UiaWindowTestArticleCard,
    UiaWindowTestSnapshot,
)
from src.services.runtime.window_click_flow_diagnostic_service import (
    WindowClickFlowDiagnosticService,
)


def _card(*, raw_title: str, click_point: tuple[int, int]) -> UiaWindowTestArticleCard:
    return UiaWindowTestArticleCard(
        date_text="2024年4月25日",
        published_date="2024-04-25",
        raw_title=raw_title,
        title=raw_title,
        date_rect=(10, 10, 100, 30),
        title_rect=(20, 40, 200, 70),
        card_rect=(10, 30, 300, 100),
        visible_rect=(10, 30, 300, 100),
        visible_height=70,
        click_point=click_point,
    )


def _snapshot(*cards: UiaWindowTestArticleCard) -> UiaWindowTestSnapshot:
    return UiaWindowTestSnapshot(
        groups=(),
        all_cards=cards,
        visible_cards=cards,
        content_viewport=(0, 0, 500, 800),
    )


class _SnapshotReader:
    def __init__(self, *snapshots: UiaWindowTestSnapshot) -> None:
        self._snapshots = list(snapshots)
        self.read_count = 0

    def read(self, _home_window: object) -> UiaWindowTestSnapshot:
        index = min(self.read_count, len(self._snapshots) - 1)
        self.read_count += 1
        return self._snapshots[index]


class _Clicker:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    def click_point(self, home_window_handle: int, click_x: int, click_y: int) -> None:
        self.calls.append((home_window_handle, click_x, click_y))


class _Factory:
    def __init__(self, reader: _SnapshotReader, clicker: _Clicker) -> None:
        self.reader = reader
        self.clicker = clicker

    def create_reader(self) -> object:
        return object()

    def find_home_window(self, **_kwargs: object) -> object:
        return SimpleNamespace(handle=99)

    def create_home_guard(self) -> object:
        return SimpleNamespace(activate=lambda _window: None)

    def create_home_reader(self) -> object:
        return SimpleNamespace(
            read=lambda _window: SimpleNamespace(account_name="测试公众号")
        )

    def create_window_test_reader(self) -> _SnapshotReader:
        return self.reader

    def create_scroller(self) -> object:
        return SimpleNamespace(scroll_down=lambda *_args, **_kwargs: False)

    def create_clicker(self) -> _Clicker:
        return self.clicker


class WindowMoreArticlesExpansionTest(unittest.TestCase):
    def test_more_articles_card_is_identified(self) -> None:
        more = _card(raw_title="余下 3 篇", click_point=(150, 80))

        self.assertTrue(more.is_more_trigger)
        self.assertEqual(3, more.remaining_count)

    def test_article_clicker_can_click_an_explicit_point(self) -> None:
        calls: list[tuple[int, int, int]] = []
        clicker = ArticleClicker(native_click=lambda hwnd, x, y: calls.append((hwnd, x, y)))

        result = clicker.click_point(99, 150, 80)

        self.assertEqual([(99, 150, 80)], calls)
        self.assertEqual("win32_post_message", result.method)

    def test_diagnostic_clicks_more_card_then_rereads_visible_cards(self) -> None:
        more = _card(raw_title="余下 3 篇", click_point=(150, 80))
        article = _card(raw_title="展开后出现的文章", click_point=(160, 180))
        reader = _SnapshotReader(_snapshot(more), _snapshot(article))
        clicker = _Clicker()
        factory = _Factory(reader, clicker)
        config = SimpleNamespace(
            window=SimpleNamespace(
                home_find_timeout_seconds=0.1,
                scroll_initial_delay_seconds=0.0,
            )
        )
        service = WindowClickFlowDiagnosticService(
            config=config,
            window_factory=factory,
            sleep=lambda _seconds: None,
        )

        result = service.run(max_records=1)

        self.assertTrue(result["ok"])
        self.assertEqual(["展开后出现的文章"], [item["rawTitle"] for item in result["records"]])
        self.assertEqual([(99, 150, 80)], clicker.calls)
        self.assertEqual(2, reader.read_count)
        self.assertIn("more-trigger-clicked", [item["event"] for item in result["events"]])

    def test_same_date_group_more_entry_is_clicked_only_once(self) -> None:
        more_three = _card(raw_title="余下 3 篇", click_point=(150, 80))
        more_one = _card(raw_title="余下 1 篇", click_point=(150, 80))
        reader = _SnapshotReader(_snapshot(more_three), _snapshot(more_one))
        clicker = _Clicker()
        factory = _Factory(reader, clicker)
        config = SimpleNamespace(
            window=SimpleNamespace(
                home_find_timeout_seconds=0.1,
                scroll_initial_delay_seconds=0.0,
                scroll_wheel_steps=5,
            )
        )
        service = WindowClickFlowDiagnosticService(
            config=config,
            window_factory=factory,
            sleep=lambda _seconds: None,
        )

        result = service.run(max_records=1)

        self.assertEqual([(99, 150, 80)], clicker.calls)
        self.assertEqual(
            1,
            sum(
                item["event"] == "more-trigger-clicked"
                for item in result["events"]
            ),
        )


if __name__ == "__main__":
    unittest.main()
