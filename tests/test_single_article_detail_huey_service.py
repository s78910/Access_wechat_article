from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest

from src.services.task.single_article_detail_huey_service import (
    SingleArticleDetailHueyService,
)


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "home-not-found",
    "no-visible-card",
    "skipped-collected",
    "ready-to-continue",
}


class SingleArticleDetailHueyServiceTests(unittest.TestCase):
    def test_skip_disabled_reads_first_card_and_allows_continue(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            service = _service(
                temp_dir,
                db_path,
                runner=lambda **_kwargs: _first_card_result(),
            )
            try:
                initial = service.start(skip_collected_records=False)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(initial["status"], "running")
                self.assertTrue(initial["hueyTaskId"])
                self.assertEqual(final["status"], "ready-to-continue")
                self.assertTrue(final["ok"])
                self.assertEqual(final["accountName"], "汝城发布")
                self.assertEqual(final["records"][0]["rawTitle"], "第一篇测试文章")
                self.assertIn("可以继续", final["message"])
            finally:
                service.shutdown()

    def test_skip_enabled_stops_when_same_account_date_and_title_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            _insert_article(
                db_path,
                account_name="汝城发布",
                title="第一篇测试文章的完整标题",
                published_time="2026-08-07 21:08:00",
            )
            service = _service(
                temp_dir,
                db_path,
                runner=lambda **_kwargs: _first_card_result(raw_title="第一篇测试文章"),
            )
            try:
                initial = service.start(skip_collected_records=True)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "skipped-collected")
                self.assertTrue(final["ok"])
                self.assertEqual(final["collectedLookup"]["matchedTitle"], "第一篇测试文章的完整标题")
                self.assertIn("已采集", final["message"])
            finally:
                service.shutdown()

    def test_skip_enabled_normalizes_home_and_database_titles_before_matching(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            _insert_article(
                db_path,
                account_name="创青春",
                title="新时代青年先锋丨王兴平：将青春投入海南自贸港火热实践",
                published_time="2026-08-06 10:16:00",
            )
            service = _service(
                temp_dir,
                db_path,
                runner=lambda **_kwargs: _first_card_result(
                    raw_title="新时代青年先锋丨王兴平:将青春投入海南自贸港火热实践",
                    account_name="创青春",
                    published_date="2026-08-06",
                ),
            )
            try:
                initial = service.start(skip_collected_records=True)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "skipped-collected")
                self.assertTrue(final["ok"])
                self.assertEqual(
                    final["collectedLookup"]["matchedTitle"],
                    "新时代青年先锋丨王兴平：将青春投入海南自贸港火热实践",
                )
            finally:
                service.shutdown()

    def test_skip_enabled_allows_continue_when_account_or_title_not_found(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            _insert_article(
                db_path,
                account_name="其他公众号",
                title="第一篇测试文章",
                published_time="2026-08-07 21:08:00",
            )
            service = _service(
                temp_dir,
                db_path,
                runner=lambda **_kwargs: _first_card_result(),
            )
            try:
                initial = service.start(skip_collected_records=True)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "ready-to-continue")
                self.assertTrue(final["ok"])
                self.assertEqual(final["collectedLookup"]["matched"], False)
                self.assertIn("可以继续", final["message"])
            finally:
                service.shutdown()

    def test_skip_enabled_shows_account_name_and_lookup_inputs_when_not_matched(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            _insert_article(
                db_path,
                account_name="人民日报",
                title="21岁小伙瞒着父母去泰国找女朋友，在机场被民警劝下",
                published_time="2026-08-17 08:33",
            )
            service = _service(
                temp_dir,
                db_path,
                runner=lambda **_kwargs: _first_card_result(
                    account_name="错误公众号名",
                    raw_title="21岁小伙瞒着父母去泰国找女朋友，在机场被民警劝下",
                    published_date="2026-08-17",
                ),
            )
            try:
                initial = service.start(skip_collected_records=True)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "ready-to-continue")
                self.assertEqual(final["accountName"], "错误公众号名")
                self.assertEqual(final["collectedLookup"]["reason"], "account-not-found")
                self.assertEqual(final["collectedLookup"]["accountName"], "错误公众号名")
                self.assertTrue(
                    any(
                        item.get("label") == "公众号名称"
                        and item.get("value") == "错误公众号名"
                        for item in final["items"]
                    )
                )
                lookup_item = next(
                    item
                    for item in final["items"]
                    if item.get("label") == "已采集记录校验"
                )
                self.assertIn("公众号索引不存在", lookup_item["value"])
                self.assertIn(
                    {"label": "校验公众号", "value": "错误公众号名"},
                    lookup_item["cells"],
                )
                self.assertIn(
                    {"label": "校验日期", "value": "2026-08-17"},
                    lookup_item["cells"],
                )
            finally:
                service.shutdown()

    def test_missing_card_input_fails_without_reading_window_in_huey_worker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            service = _service(temp_dir, db_path, runner=None)
            try:
                initial = service.start(skip_collected_records=False)
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "failed")
                self.assertFalse(final["ok"])
                self.assertIn("缺少文章卡片输入", final["message"])
                self.assertEqual(final["records"], [])
            finally:
                service.shutdown()

    def test_ready_to_continue_runs_in_process_capture_flow(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            db_path = _create_archive_db(Path(temp_dir) / "archive.sqlite3")
            service = _service(
                temp_dir,
                db_path,
                runner=None,
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                config=_config(),
            )
            try:
                initial = service.start(
                    card_index=1,
                    account_name="汝城发布",
                    card=_first_card_record(),
                    skip_collected_records=False,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "completed")
                self.assertTrue(final["ok"])
                self.assertEqual(final["captureType"], "html")
                self.assertEqual(final["records"][0]["rawTitle"], "第一篇测试文章")
                self.assertEqual(
                    events,
                    [
                        "tabs.capture_baseline",
                        "mitm.start_attempt",
                        "mitm.wait_ready",
                        "click:250,140",
                        "tabs.wait_for_opened_article_tab",
                        "tabs.close_article_tab:文章标签",
                        "mitm.stop_capture",
                    ],
                )
            finally:
                service.shutdown()


def _service(
    temp_dir: str,
    db_path: Path,
    *,
    runner,
    window_factory=object(),
    capture_factory=object(),
    config=object(),
) -> SingleArticleDetailHueyService:
    return SingleArticleDetailHueyService(
        temp_root=Path(temp_dir),
        config=config,
        window_factory=window_factory,
        capture_factory=capture_factory,
        database_path=db_path,
        runner=runner,
        session_id="session001",
        job_id_factory=lambda: "job001",
    )


def _first_card_result(
    *,
    raw_title: str = "第一篇测试文章",
    account_name: str = "汝城发布",
    published_date: str = "2026-08-07",
) -> dict:
    record = {
        "index": 1,
        "dateText": "8月7日",
        "publishedDate": published_date,
        "rawTitle": raw_title,
        "title": raw_title,
        "visibleRect": [80, 100, 420, 180],
        "clickPoint": [250, 140],
    }
    return {
        "ok": True,
        "status": "completed",
        "message": "已识别可视区第一篇文章卡片。",
        "tone": "success",
        "items": [{"kind": "article", "label": "第1条文章", "value": raw_title}],
        "records": [record],
        "accountName": account_name,
        "captureType": "none",
        "totalSeconds": 0.01,
    }


def _first_card_record(
    *,
    raw_title: str = "第一篇测试文章",
    account_name: str = "汝城发布",
    published_date: str = "2026-08-07",
) -> dict:
    return {
        "index": 1,
        "dateText": "8月7日",
        "publishedDate": published_date,
        "rawTitle": raw_title,
        "title": raw_title,
        "visibleRect": [80, 100, 420, 180],
        "clickPoint": [250, 140],
        "homeWindowHandle": 100,
        "accountName": account_name,
    }


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        proxy=SimpleNamespace(host="127.0.0.1", port=18000, confdir=Path(".mitmproxy"), ssl_insecure=True),
        mitm_capture=SimpleNamespace(
            ready_timeout_seconds=10.0,
            capture_timeout_seconds=20.0,
            result_timeout_seconds=11.0,
            listener_shutdown_timeout_seconds=3.0,
        ),
        window=SimpleNamespace(
            article_open_timeout_seconds=12.0,
            article_title_poll_interval_seconds=0.15,
            article_title_stable_delay_seconds=0.1,
        ),
    )


class _FakeWindowFactory:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def create_clicker(self) -> object:
        return _FakeClicker(self._events)

    def create_tab_service(self) -> object:
        return _FakeTabs(self._events)


class _FakeCaptureFactory:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def create_in_process_control(self) -> object:
        return _FakeInProcessControl(self._events)


class _FakeClicker:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def click(self, target) -> SimpleNamespace:
        self._events.append(f"click:{target.click_x},{target.click_y}")
        return SimpleNamespace(method="win32_post_message")


class _FakeTabs:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def capture_baseline(self) -> dict[str, str]:
        self._events.append("tabs.capture_baseline")
        return {"home": "主页"}

    def wait_for_opened_article_tab(self, **_kwargs: object) -> SimpleNamespace:
        self._events.append("tabs.wait_for_opened_article_tab")
        return SimpleNamespace(title="文章标签", owner_handle=200)

    def close_article_tab(self, selected, *, home_window_handle: int) -> None:
        self._events.append(f"tabs.close_article_tab:{selected.title}")
        self.home_window_handle = home_window_handle


class _FakeInProcessControl:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def start_attempt(self, **_kwargs: object) -> object:
        self._events.append("mitm.start_attempt")
        return _FakeAttempt(self._events)


class _FakeAttempt:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def wait_ready(self, *, timeout_seconds: float) -> dict:
        self._events.append("mitm.wait_ready")
        return {"timeout_seconds": timeout_seconds}

    def stop_capture(self, *, timeout_seconds: float):
        from src.domain.enums import CaptureType, TaskStatus
        from src.domain.models import MitmCaptureResult

        self._events.append("mitm.stop_capture")
        return MitmCaptureResult(
            task_id="task001",
            attempt_id="attempt001",
            status=TaskStatus.SUCCESS,
            capture_type=CaptureType.HTML,
            html="<html>ok</html>",
            capture_events=(
                {"name": "捕获 HTML", "elapsed_seconds": 0.2, "capture_type_after_event": "html"},
            ),
        )

    def cancel(self) -> None:
        self._events.append("mitm.cancel")


def _wait_for_terminal(
    service: SingleArticleDetailHueyService,
    job_id: str,
    *,
    timeout_seconds: float = 3.0,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = service.get(job_id)
        if payload.get("status") in _TERMINAL_STATUSES:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Huey单篇详情任务未在{timeout_seconds:g}秒内结束")


def _create_archive_db(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE awa_public_accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT NOT NULL UNIQUE,
                created_time TEXT NOT NULL,
                updated_time TEXT NOT NULL
            );
            CREATE TABLE awa_public_articles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                article_title TEXT NOT NULL,
                published_article_time TEXT NOT NULL,
                article_link TEXT NOT NULL,
                archive_dir TEXT NOT NULL DEFAULT '',
                resource_types_json TEXT NOT NULL DEFAULT '[]',
                first_collected_time TEXT NOT NULL,
                last_collected_time TEXT NOT NULL,
                created_time TEXT NOT NULL,
                updated_time TEXT NOT NULL,
                UNIQUE(account_id, article_link)
            );
            """
        )
        connection.commit()
    return path


def _insert_article(
    db_path: Path,
    *,
    account_name: str,
    title: str,
    published_time: str,
) -> None:
    now = "2026-08-16 12:00:00"
    with closing(sqlite3.connect(db_path)) as connection:
        account_row = connection.execute(
            "SELECT id FROM awa_public_accounts WHERE account_name = ?",
            (account_name,),
        ).fetchone()
        if account_row is None:
            cursor = connection.execute(
                """
                INSERT INTO awa_public_accounts(account_name, created_time, updated_time)
                VALUES (?, ?, ?)
                """,
                (account_name, now, now),
            )
            account_id = int(cursor.lastrowid)
        else:
            account_id = int(account_row[0])
        connection.execute(
            """
            INSERT INTO awa_public_articles(
                account_id,
                article_title,
                published_article_time,
                article_link,
                archive_dir,
                resource_types_json,
                first_collected_time,
                last_collected_time,
                created_time,
                updated_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                title,
                published_time,
                f"https://mp.weixin.qq.com/s/{account_id}-{title}",
                "storages/test",
                "[]",
                now,
                now,
                now,
                now,
            ),
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
