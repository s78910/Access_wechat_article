from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from src.modules.window.uia_window_test_reader import (
    UiaWindowTestArticleCard,
    UiaWindowTestDateGroup,
    UiaWindowTestSnapshot,
)
from src.services.runtime.article_detail_diagnostic_service import (
    ArticleDetailDiagnosticService,
)
from src.services.runtime.window_click_flow_diagnostic_service import (
    _card_record,
    _record_item,
)


class ArticleDetailDiagnosticServiceTests(unittest.TestCase):
    def test_run_reads_first_visible_article_card_without_old_capture_flow(self) -> None:
        card = _card("8月7日", "第一篇文章", published_date="2026-08-07")
        factory = _FakeWindowFactory(_snapshot(card))
        updates: list[dict[str, object]] = []

        result = _service(factory).run(on_update=updates.append)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["ok"])
        self.assertEqual(result["captureType"], "none")
        self.assertEqual(result["items"], [_record_item(_card_record(card, index=1))])
        self.assertEqual(result["accountName"], "汝城发布")
        expected_record = _card_record(card, index=1)
        actual_record = dict(result["records"][0])
        self.assertEqual(
            {key: actual_record[key] for key in expected_record},
            expected_record,
        )
        self.assertEqual(actual_record["homeWindowHandle"], 100)
        self.assertEqual(actual_record["accountName"], "汝城发布")
        self.assertGreaterEqual(len(updates), 2)
        self.assertEqual(factory.guard.activation_count, 1)
        self.assertEqual(factory.snapshot_reader.read_count, 1)
        self.assertFalse(factory.old_cursor_requested)

    def test_run_returns_warning_when_no_visible_article_card(self) -> None:
        factory = _FakeWindowFactory(_snapshot())

        result = _service(factory).run()

        self.assertEqual(result["status"], "no-visible-card")
        self.assertFalse(result["ok"])
        self.assertEqual(result["captureType"], "none")
        self.assertEqual(result["items"], [])


class _FakeGuard:
    def __init__(self) -> None:
        self.activation_count = 0

    def activate(self, _home_window: object) -> None:
        self.activation_count += 1


class _FakeSnapshotReader:
    def __init__(self, snapshot: UiaWindowTestSnapshot) -> None:
        self._snapshot = snapshot
        self.read_count = 0

    def read(self, _home_window: object) -> UiaWindowTestSnapshot:
        self.read_count += 1
        return self._snapshot


class _FakeHomeReader:
    def read(self, _home_window: object) -> SimpleNamespace:
        return SimpleNamespace(account_name="汝城发布")


class _FakeWindowFactory:
    def __init__(self, snapshot: UiaWindowTestSnapshot) -> None:
        self.guard = _FakeGuard()
        self.snapshot_reader = _FakeSnapshotReader(snapshot)
        self.old_cursor_requested = False

    def create_reader(self) -> object:
        return object()

    def find_home_window(self, **_kwargs: object) -> object:
        return SimpleNamespace(handle=100)

    def create_home_guard(self) -> _FakeGuard:
        return self.guard

    def create_window_test_reader(self) -> _FakeSnapshotReader:
        return self.snapshot_reader

    def create_cursor(self, **_kwargs: object) -> object:
        self.old_cursor_requested = True
        raise AssertionError("详情获取不应再创建旧 HomeArticleCursor")

    def create_home_reader(self) -> object:
        return _FakeHomeReader()

    def create_tab_service(self) -> object:
        raise AssertionError("详情获取不应操作浏览器标签")

    def create_clicker(self) -> object:
        raise AssertionError("详情获取不应点击文章")


class _ForbiddenCaptureFactory:
    def create_process_control(self) -> object:
        raise AssertionError("详情获取当前不应启动 MITM")


def _service(factory: _FakeWindowFactory) -> ArticleDetailDiagnosticService:
    window = SimpleNamespace(home_find_timeout_seconds=1.0)
    storage = SimpleNamespace(
        article_storage_root=Path("storages"),
        temp_dir=Path("data/tmp"),
    )
    return ArticleDetailDiagnosticService(
        config=SimpleNamespace(window=window, storage=storage),
        window_factory=factory,
        capture_factory=_ForbiddenCaptureFactory(),
        db_path=Path("data/sql/test.sqlite3"),
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


def _snapshot(*cards: UiaWindowTestArticleCard) -> UiaWindowTestSnapshot:
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
        loading=False,
    )


if __name__ == "__main__":
    unittest.main()
