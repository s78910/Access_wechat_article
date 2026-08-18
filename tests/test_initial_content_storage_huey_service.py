from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest

from src.domain.enums import CaptureType, TaskStatus
from src.domain.models import MitmCaptureResult, ResourceManifest
from src.domain.results import ServiceResult
from src.services.capture.html_parse_save_service import ArticleSaveData
from src.services.task.initial_content_storage_huey_service import (
    InitialContentStorageHueyService,
)


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "save-failed",
    "skipped-collected",
    "ready-to-continue",
}


class InitialContentStorageHueyServiceTests(unittest.TestCase):
    def test_capture_success_parses_and_saves_initial_article_content(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            html_save = _FakeHtmlSave(events)
            service = InitialContentStorageHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=Path(temp_dir) / "awa_public.sqlite3",
                html_save=html_save,
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
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(initial["action"], "initial-content-storage")
                self.assertEqual(final["status"], "completed")
                self.assertTrue(final["ok"])
                self.assertEqual(final["captureType"], "html")
                self.assertEqual(final["htmlSource"], "mitm_response")
                self.assertEqual(final["articleId"], 101)
                self.assertEqual(final["accountId"], 201)
                self.assertEqual(final["archiveDir"], "汝城发布/2026-08-07 测试文章__abc")
                self.assertEqual(
                    final["options"],
                    {"skipCollectedRecords": False, "storeArticleDetail": True},
                )
                self.assertEqual(html_save.save_count, 1)
                self.assertIn("html_save.save", events)
                self.assertEqual(
                    events[:7],
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

    def test_store_article_detail_is_locked_enabled_even_when_false_is_passed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            service = InitialContentStorageHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=Path(temp_dir) / "awa_public.sqlite3",
                html_save=_FakeHtmlSave(events),
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
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertTrue(initial["options"]["storeArticleDetail"])
                self.assertTrue(final["options"]["storeArticleDetail"])
                self.assertEqual(final["status"], "completed")
            finally:
                service.shutdown()


class _FakeHtmlSave:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.save_count = 0

    def save(self, **kwargs: object) -> ServiceResult[ArticleSaveData]:
        self.save_count += 1
        self._events.append("html_save.save")
        capture_result = kwargs["capture_result"]
        self.capture_result = capture_result
        self.request_timeout_seconds = kwargs["request_timeout_seconds"]
        return ServiceResult.success(
            ArticleSaveData(
                article_id=101,
                account_id=201,
                history_id=301,
                article_directory=Path("storages/汝城发布/2026-08-07 测试文章__abc"),
                archive_dir="汝城发布/2026-08-07 测试文章__abc",
                detail_path=Path("storages/汝城发布/2026-08-07 测试文章__abc/article_detail.json"),
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
            task_id="initial-storage-job001",
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
    service: InitialContentStorageHueyService,
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
    raise AssertionError(f"Huey初始内容存储任务未在{timeout_seconds:g}秒内结束")


if __name__ == "__main__":
    unittest.main()
