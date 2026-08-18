from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from dev_server import (
    ArticleDetailDiagnosticPayload,
    DevBackendContext,
    _start_article_detail_diagnostic_job,
)


class ArticleDetailStartJobTests(unittest.TestCase):
    def test_reads_first_card_before_starting_huey_when_payload_has_no_card(self) -> None:
        with TemporaryDirectory() as temp_dir:
            probe = _FakeProbeService(_probe_result())
            huey = _FakeHueyService()
            backend = _backend(temp_dir, probe=probe, huey=huey)

            result = _start_article_detail_diagnostic_job(
                backend,
                ArticleDetailDiagnosticPayload(skipCollectedRecords=True),
            )

            self.assertEqual(probe.read_count, 1)
            self.assertEqual(huey.start_count, 1)
            self.assertEqual(huey.last_start_kwargs["account_name"], "汝城发布")
            self.assertEqual(huey.last_start_kwargs["card"]["rawTitle"], "第一篇测试文章")
            self.assertTrue(huey.last_start_kwargs["skip_collected_records"])
            self.assertEqual(result["status"], "running")

    def test_uses_payload_card_directly_when_already_provided(self) -> None:
        with TemporaryDirectory() as temp_dir:
            probe = _FakeProbeService(_probe_result())
            huey = _FakeHueyService()
            backend = _backend(temp_dir, probe=probe, huey=huey)
            card = {
                "index": 3,
                "dateText": "8月7日",
                "publishedDate": "2026-08-07",
                "rawTitle": "外部传入文章",
                "title": "外部传入文章",
                "visibleRect": [80, 100, 420, 180],
                "clickPoint": [250, 140],
            }

            _start_article_detail_diagnostic_job(
                backend,
                ArticleDetailDiagnosticPayload(
                    cardIndex=3,
                    accountName="外部公众号",
                    card=card,
                    skipCollectedRecords=False,
                ),
            )

            self.assertEqual(probe.read_count, 0)
            self.assertEqual(huey.start_count, 1)
            self.assertEqual(huey.last_start_kwargs["card_index"], 3)
            self.assertEqual(huey.last_start_kwargs["account_name"], "外部公众号")
            self.assertEqual(huey.last_start_kwargs["card"], card)

    def test_does_not_start_huey_when_first_card_probe_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            probe = _FakeProbeService(
                {
                    "ok": False,
                    "status": "no-visible-card",
                    "action": "single-article-detail",
                    "title": "详情获取结果",
                    "message": "当前主页可视区没有识别到文章卡片。",
                    "tone": "warning",
                    "items": [],
                    "records": [],
                    "accountName": "汝城发布",
                    "captureType": "none",
                }
            )
            huey = _FakeHueyService()
            backend = _backend(temp_dir, probe=probe, huey=huey)

            result = _start_article_detail_diagnostic_job(
                backend,
                ArticleDetailDiagnosticPayload(skipCollectedRecords=False),
            )

            self.assertEqual(probe.read_count, 1)
            self.assertEqual(huey.start_count, 0)
            self.assertEqual(result["status"], "no-visible-card")
            self.assertEqual(result["jobId"], "")


class _FakeProbeService:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.read_count = 0

    def read_first_visible_card(self) -> dict:
        self.read_count += 1
        return dict(self._result)


class _FakeHueyService:
    def __init__(self) -> None:
        self.start_count = 0
        self.last_start_kwargs: dict[str, object] = {}

    def start(self, **kwargs: object) -> dict:
        self.start_count += 1
        self.last_start_kwargs = dict(kwargs)
        return {
            "ok": False,
            "status": "running",
            "jobId": "article-detail-job001",
            "hueyTaskId": "task001",
            "action": "single-article-detail",
            "title": "详情获取结果",
            "message": "正在等待Huey执行单篇文章详情任务...",
            "tone": "info",
            "items": [],
            "records": [],
            "accountName": str(kwargs.get("account_name") or ""),
        }


def _backend(temp_dir: str, *, probe: object, huey: object) -> DevBackendContext:
    return DevBackendContext(
        project_root=Path(temp_dir),
        runtime=SimpleNamespace(config=SimpleNamespace(), window_factory=object()),
        db_path=Path(temp_dir) / "archive.sqlite3",
        task_manager=object(),
        article_detail_card_probe_service=probe,
        article_detail_huey_service=huey,
    )


def _probe_result() -> dict:
    card = {
        "index": 1,
        "dateText": "8月7日",
        "publishedDate": "2026-08-07",
        "rawTitle": "第一篇测试文章",
        "title": "第一篇测试文章",
        "visibleRect": [80, 100, 420, 180],
        "clickPoint": [250, 140],
    }
    return {
        "ok": True,
        "status": "completed",
        "action": "single-article-detail",
        "title": "详情获取结果",
        "message": "已识别可视区第一篇文章卡片。",
        "tone": "success",
        "items": [{"kind": "article", "label": "第1条文章", "value": "第一篇测试文章"}],
        "records": [card],
        "accountName": "汝城发布",
        "captureType": "none",
    }


if __name__ == "__main__":
    unittest.main()
