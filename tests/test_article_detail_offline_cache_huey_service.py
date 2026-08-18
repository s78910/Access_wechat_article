from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest

from src.domain.enums import CaptureType, TaskStatus
from src.domain.models import MitmCaptureResult, ResourceManifest
from src.domain.results import ServiceResult
from src.services.capture.html_parse_save_service import ArticleSaveData
from src.services.task.article_detail_offline_cache_huey_service import (
    ArticleDetailOfflineCacheHueyService,
)


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "skipped-collected",
    "ready-to-continue",
}


class ArticleDetailOfflineCacheHueyServiceTests(unittest.TestCase):
    def test_capture_save_then_runs_offline_cache_process(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            database_path = Path(temp_dir) / "awa_public.sqlite3"
            _create_article_database(database_path, article_link="https://mp.weixin.qq.com/s/abc123")
            html_save = _FakeHtmlSave(events, temp_dir)
            offline_control = _FakeOfflineCacheProcessControl(events)
            service = ArticleDetailOfflineCacheHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=database_path,
                html_save=html_save,
                offline_cache_process_control=offline_control,
                session_id="session001",
                job_id_factory=lambda: "job001",
            )
            try:
                initial = service.start(
                    card_index=1,
                    account_name="汝城发布",
                    card=_first_card_record(),
                    skip_collected_records=False,
                    store_article_detail=True,
                    archive_offline_content=True,
                    stateful_offline_cache=True,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(initial["action"], "article-detail-offline-cache")
                self.assertEqual(final["status"], "completed")
                self.assertTrue(final["ok"])
                self.assertEqual(final["articleId"], 101)
                self.assertEqual(final["offlineResourceCount"], 3)
                self.assertEqual(final["offlineIndexPath"], str(html_save.article_directory / "index.html"))
                self.assertEqual(
                    final["options"],
                    {
                        "skipCollectedRecords": False,
                        "storeArticleDetail": True,
                        "archiveOfflineContent": True,
                        "statefulOfflineCache": True,
                    },
                )
                self.assertEqual(html_save.save_count, 1)
                self.assertEqual(offline_control.start_count, 1)
                self.assertLess(events.index("html_save.save"), events.index("offline.start"))
                self.assertEqual(
                    offline_control.last_payload["article_directory"],
                    str(html_save.article_directory),
                )
                self.assertEqual(
                    offline_control.last_payload["article_short_link"],
                    "https://mp.weixin.qq.com/s/abc123",
                )
                self.assertTrue(offline_control.last_payload["stateful_offline_cache"])
                self.assertEqual(
                    offline_control.last_payload["request_json_path"],
                    str(html_save.article_directory / "origin" / "request.json"),
                )
                self.assertIn("offline.wait_ready", events)
                self.assertIn("offline.wait_result", events)
            finally:
                service.shutdown()

    def test_fails_when_saved_article_has_no_short_link_in_database(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            database_path = Path(temp_dir) / "awa_public.sqlite3"
            _create_article_database(database_path, article_link="")
            offline_control = _FakeOfflineCacheProcessControl(events)
            service = ArticleDetailOfflineCacheHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=database_path,
                html_save=_FakeHtmlSave(events, temp_dir),
                offline_cache_process_control=offline_control,
                session_id="session001",
                job_id_factory=lambda: "job001",
            )
            try:
                initial = service.start(
                    card_index=1,
                    account_name="汝城发布",
                    card=_first_card_record(),
                    skip_collected_records=False,
                    store_article_detail=True,
                    archive_offline_content=True,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(final["status"], "failed")
                self.assertFalse(final["ok"])
                self.assertIn("数据库中缺少文章短链", final["message"])
                self.assertEqual(offline_control.start_count, 0)
            finally:
                service.shutdown()

    def test_offline_archive_option_is_locked_enabled_even_when_false_is_passed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            database_path = Path(temp_dir) / "awa_public.sqlite3"
            _create_article_database(database_path, article_link="https://mp.weixin.qq.com/s/abc123")
            service = ArticleDetailOfflineCacheHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=database_path,
                html_save=_FakeHtmlSave(events, temp_dir),
                offline_cache_process_control=_FakeOfflineCacheProcessControl(events),
                session_id="session001",
                job_id_factory=lambda: "job001",
            )
            try:
                initial = service.start(
                    card_index=1,
                    account_name="汝城发布",
                    card=_first_card_record(),
                    skip_collected_records=False,
                    store_article_detail=False,
                    archive_offline_content=False,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertTrue(initial["options"]["storeArticleDetail"])
                self.assertTrue(initial["options"]["archiveOfflineContent"])
                self.assertTrue(final["options"]["storeArticleDetail"])
                self.assertTrue(final["options"]["archiveOfflineContent"])
                self.assertEqual(final["status"], "completed")
            finally:
                service.shutdown()


class _FakeHtmlSave:
    def __init__(self, events: list[str], temp_dir: str) -> None:
        self._events = events
        self.save_count = 0
        self.article_directory = Path(temp_dir) / "storages" / "汝城发布" / "2026-08-07 测试文章__abc"
        self.article_directory.mkdir(parents=True, exist_ok=True)

    def save(self, **kwargs: object) -> ServiceResult[ArticleSaveData]:
        self.save_count += 1
        self._events.append("html_save.save")
        capture_result = kwargs["capture_result"]
        return ServiceResult.success(
            ArticleSaveData(
                article_id=101,
                account_id=201,
                history_id=301,
                article_directory=self.article_directory,
                archive_dir="汝城发布/2026-08-07 测试文章__abc",
                detail_path=self.article_directory / "article_detail.json",
                resource_manifest=ResourceManifest.from_types(()),
                html_source="mitm_response",
                attempt_id=capture_result.attempt_id,
            ),
            duration_seconds=0.4,
        )


def _first_card_record() -> dict:
    return {
        "index": 1,
        "dateText": "8月7日",
        "publishedDate": "2026-08-07",
        "rawTitle": "测试文章",
        "title": "测试文章",
        "visibleRect": [80, 100, 420, 180],
        "clickPoint": [250, 140],
        "homeWindowHandle": 100,
        "accountName": "汝城发布",
    }


def _config(temp_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        storage=SimpleNamespace(
            article_storage_root=Path(temp_dir) / "storages",
            temp_dir=Path(temp_dir) / "tmp",
        ),
        request=SimpleNamespace(request_timeout_seconds=10.0),
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
        offline_cache=SimpleNamespace(
            max_scroll_seconds=30.0,
            resource_timeout_seconds=10.0,
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

    def stop_capture(self, *, timeout_seconds: float) -> MitmCaptureResult:
        self._events.append("mitm.stop_capture")
        return MitmCaptureResult(
            task_id="detail-offline-cache-job001",
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


class _FakeOfflineCacheProcessControl:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.start_count = 0
        self.last_payload: dict[str, object] = {}

    def start(self, **kwargs: object) -> object:
        self.start_count += 1
        self._events.append("offline.start")
        self.last_payload = dict(kwargs["payload"])
        return _FakeOfflineCacheAttempt(self._events, self.last_payload)


class _FakeOfflineCacheAttempt:
    def __init__(self, events: list[str], payload: dict[str, object]) -> None:
        self._events = events
        self._payload = payload

    def wait_ready(self, *, timeout_seconds: float) -> dict:
        self._events.append("offline.wait_ready")
        return {
            "article_directory": self._payload.get("article_directory"),
            "article_short_link": self._payload.get("article_short_link"),
        }

    def wait_result(self, *, timeout_seconds: float, on_progress=None) -> dict:
        self._events.append("offline.wait_result")
        article_directory = Path(str(self._payload["article_directory"]))
        stage_dir = Path(str(self._payload["stage_dir"]))
        (stage_dir / "assets").mkdir(parents=True, exist_ok=True)
        (stage_dir / "index.html").write_text("<html>offline</html>", encoding="utf-8")
        if on_progress is not None:
            on_progress({"name": "打开文章", "elapsed_seconds": 0.1, "status": "running"})
            on_progress({"name": "整理离线页面", "elapsed_seconds": 0.2, "status": "running"})
        return {
            "ok": True,
            "article_id": 101,
            "stage_dir": str(stage_dir),
            "index_html_path": str(stage_dir / "index.html"),
            "assets_dir": str(stage_dir / "assets"),
            "resource_count": 3,
            "message": "离线缓存完成",
            "warning": "",
            "elapsed_seconds": 0.3,
            "article_directory": str(article_directory),
        }

    def cancel(self) -> None:
        self._events.append("offline.cancel")


def _create_article_database(database_path: Path, *, article_link: str) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE awa_public_articles(
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL,
                article_title TEXT NOT NULL,
                published_article_time TEXT NOT NULL,
                article_link TEXT NOT NULL,
                archive_dir TEXT NOT NULL,
                resource_types_json TEXT NOT NULL,
                first_collected_time TEXT NOT NULL,
                last_collected_time TEXT NOT NULL,
                created_time TEXT NOT NULL,
                updated_time TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE awa_fetch_history(
                id INTEGER PRIMARY KEY,
                article_id INTEGER,
                account_id INTEGER,
                target_account_name TEXT NOT NULL,
                target_title TEXT NOT NULL,
                target_link TEXT NOT NULL,
                task_type TEXT NOT NULL,
                resource_types_json TEXT NOT NULL,
                status TEXT NOT NULL,
                started_time TEXT NOT NULL,
                finished_time TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                error_stage TEXT NOT NULL,
                error_message TEXT NOT NULL,
                output_dir TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO awa_public_articles(
                id, account_id, article_title, published_article_time, article_link,
                archive_dir, resource_types_json, first_collected_time, last_collected_time,
                created_time, updated_time
            ) VALUES(101, 201, '测试文章', '2026-08-07 12:00', ?, '汝城发布/2026-08-07 测试文章__abc', '[]', '', '', '', '')
            """,
            (article_link,),
        )
        connection.commit()
    finally:
        connection.close()


def _wait_for_terminal(
    service: ArticleDetailOfflineCacheHueyService,
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
    raise AssertionError(f"单篇离线缓存 Huey 任务未在{timeout_seconds:g}秒内结束")


if __name__ == "__main__":
    unittest.main()
