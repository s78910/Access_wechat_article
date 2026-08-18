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
from src.services.task.article_detail_comments_huey_service import (
    ArticleDetailCommentsHueyService,
)


_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "skipped",
    "skipped-collected",
    "ready-to-continue",
}


class ArticleDetailCommentsHueyServiceTests(unittest.TestCase):
    def test_capture_save_then_runs_comment_process(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            comment_control = _FakeCommentProcessControl(events)
            html_save = _FakeHtmlSave(events, temp_dir)
            service = ArticleDetailCommentsHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=Path(temp_dir) / "awa_public.sqlite3",
                html_save=html_save,
                comment_process_control=comment_control,
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
                    store_comment_info=True,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertEqual(initial["action"], "article-detail-comments")
                self.assertEqual(final["status"], "completed")
                self.assertTrue(final["ok"])
                self.assertEqual(final["captureType"], "html")
                self.assertEqual(final["htmlSource"], "mitm_response")
                self.assertEqual(final["articleId"], 101)
                self.assertEqual(final["accountId"], 201)
                self.assertEqual(final["commentCount"], 5)
                self.assertEqual(final["replyCount"], 2)
                self.assertEqual(final["commentPath"], "comments/final.json")
                self.assertEqual(
                    final["options"],
                    {
                        "skipCollectedRecords": False,
                        "storeArticleDetail": True,
                        "storeCommentInfo": True,
                    },
                )
                self.assertEqual(html_save.save_count, 1)
                self.assertEqual(comment_control.start_count, 1)
                self.assertLess(
                    events.index("html_save.save"),
                    events.index("comment.start"),
                )
                self.assertEqual(comment_control.last_payload["article_id"], 101)
                self.assertEqual(comment_control.last_payload["account_id"], 201)
                self.assertEqual(comment_control.last_payload["archive_dir"], "汝城发布/2026-08-07 测试文章__abc")
                self.assertEqual(comment_control.last_payload["article_directory"], str(html_save.article_directory))
                self.assertIn("comment.wait_ready", events)
                self.assertIn("comment.wait_result", events)
            finally:
                service.shutdown()

    def test_comment_storage_is_locked_enabled_even_when_false_is_passed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            events: list[str] = []
            service = ArticleDetailCommentsHueyService(
                temp_root=Path(temp_dir),
                config=_config(temp_dir),
                window_factory=_FakeWindowFactory(events),
                capture_factory=_FakeCaptureFactory(events),
                database_path=Path(temp_dir) / "awa_public.sqlite3",
                html_save=_FakeHtmlSave(events, temp_dir),
                comment_process_control=_FakeCommentProcessControl(events),
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
                    store_comment_info=False,
                )
                final = _wait_for_terminal(service, initial["jobId"])

                self.assertTrue(initial["options"]["storeArticleDetail"])
                self.assertTrue(initial["options"]["storeCommentInfo"])
                self.assertTrue(final["options"]["storeArticleDetail"])
                self.assertTrue(final["options"]["storeCommentInfo"])
                self.assertEqual(final["status"], "completed")
            finally:
                service.shutdown()


class _FakeHtmlSave:
    def __init__(self, events: list[str], temp_dir: str) -> None:
        self._events = events
        self.save_count = 0
        self.article_directory = Path(temp_dir) / "storages" / "汝城发布" / "2026-08-07 测试文章__abc"

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
        comment=SimpleNamespace(
            request_timeout_seconds=10.0,
            page_interval_seconds=0.5,
            max_pages=50,
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
            task_id="detail-comments-job001",
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


class _FakeCommentProcessControl:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.start_count = 0
        self.last_payload: dict[str, object] = {}

    def start(self, **kwargs: object) -> object:
        self.start_count += 1
        self._events.append("comment.start")
        self.last_payload = dict(kwargs["payload"])
        return _FakeCommentAttempt(self._events)


class _FakeCommentAttempt:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def wait_ready(self, *, timeout_seconds: float) -> dict:
        self._events.append("comment.wait_ready")
        return {"article_id": 101, "archive_dir": "汝城发布/2026-08-07 测试文章__abc"}

    def wait_result(self, *, timeout_seconds: float, on_progress=None) -> dict:
        self._events.append("comment.wait_result")
        if on_progress is not None:
            on_progress(
                {
                    "name": "请求评论分页与回复",
                    "elapsed_seconds": 0.3,
                    "result": "已完成评论接口请求",
                    "details": {"comment_count": 5, "reply_count": 2},
                }
            )
        return {
            "status": "success",
            "message": "评论采集完成",
            "html_comment_count": 7,
            "comment_count": 5,
            "reply_count": 2,
            "page_count": 1,
            "stop_reason": "completed",
            "comment_path": "comments/final.json",
            "asset_count": 0,
            "asset_dir": "",
            "resource_manifest": ["article_detail", "origin_html", "origin_request", "comment_detail"],
        }

    def cancel(self) -> None:
        self._events.append("comment.cancel")


def _wait_for_terminal(
    service: ArticleDetailCommentsHueyService,
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
    raise AssertionError(f"详情评论 Huey 任务未在{timeout_seconds:g}秒内结束")


if __name__ == "__main__":
    unittest.main()
