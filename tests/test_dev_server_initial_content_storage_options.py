from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from dev_server import (
    DevBackendContext,
    InitialContentStorageDiagnosticPayload,
    _initial_content_storage_diagnostic_job_payload,
    _start_initial_content_storage_diagnostic_job,
)


class InitialContentStorageOptionsTests(unittest.TestCase):
    def test_payload_locks_article_detail_storage_enabled(self) -> None:
        payload = InitialContentStorageDiagnosticPayload(
            skipCollectedRecords=True,
            storeArticleDetail=False,
        )

        self.assertTrue(payload.skipCollectedRecords)
        self.assertTrue(payload.storeArticleDetail)

    def test_start_reads_first_card_and_dispatches_to_huey_service(self) -> None:
        with TemporaryDirectory() as temp_dir:
            probe = _FakeProbeService(_probe_result())
            huey = _FakeInitialStorageHueyService()
            backend = _backend(temp_dir, probe=probe, huey=huey)
            payload = InitialContentStorageDiagnosticPayload(
                skipCollectedRecords=True,
                storeArticleDetail=False,
            )

            initial = _start_initial_content_storage_diagnostic_job(backend, payload)

            self.assertEqual(probe.read_count, 1)
            self.assertEqual(huey.start_count, 1)
            self.assertEqual(huey.last_start_kwargs["account_name"], "汝城发布")
            self.assertEqual(huey.last_start_kwargs["card"]["rawTitle"], "第一篇测试文章")
            self.assertTrue(huey.last_start_kwargs["skip_collected_records"])
            self.assertTrue(huey.last_start_kwargs["store_article_detail"])
            self.assertEqual(initial["action"], "initial-content-storage")
            self.assertEqual(initial["status"], "running")
            self.assertEqual(
                initial["options"],
                {"skipCollectedRecords": True, "storeArticleDetail": True},
            )

            fetched = _initial_content_storage_diagnostic_job_payload(
                backend,
                initial["jobId"],
            )
            self.assertEqual(fetched["jobId"], initial["jobId"])

    def test_does_not_start_huey_when_first_card_probe_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            probe = _FakeProbeService(
                {
                    "ok": False,
                    "status": "no-visible-card",
                    "message": "当前主页可视区没有识别到文章卡片。",
                    "tone": "warning",
                    "items": [],
                    "records": [],
                    "accountName": "汝城发布",
                    "captureType": "none",
                }
            )
            huey = _FakeInitialStorageHueyService()
            backend = _backend(temp_dir, probe=probe, huey=huey)

            result = _start_initial_content_storage_diagnostic_job(
                backend,
                InitialContentStorageDiagnosticPayload(),
            )

            self.assertEqual(probe.read_count, 1)
            self.assertEqual(huey.start_count, 0)
            self.assertEqual(result["action"], "initial-content-storage")
            self.assertEqual(result["status"], "no-visible-card")
            self.assertEqual(result["jobId"], "")


class _FakeProbeService:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.read_count = 0

    def read_first_visible_card(self) -> dict:
        self.read_count += 1
        return dict(self._result)


class _FakeInitialStorageHueyService:
    def __init__(self) -> None:
        self.start_count = 0
        self.last_start_kwargs: dict[str, object] = {}
        self.jobs: dict[str, dict[str, object]] = {}

    def start(self, **kwargs: object) -> dict[str, object]:
        self.start_count += 1
        self.last_start_kwargs = dict(kwargs)
        job = {
            "ok": False,
            "status": "running",
            "jobId": "initial-storage-job001",
            "hueyTaskId": "task001",
            "action": "initial-content-storage",
            "title": "初始内容存储结果",
            "message": "正在等待Huey执行初始内容存储任务...",
            "tone": "info",
            "items": [],
            "records": [],
            "accountName": str(kwargs.get("account_name") or ""),
            "options": {
                "skipCollectedRecords": bool(kwargs.get("skip_collected_records")),
                "storeArticleDetail": bool(kwargs.get("store_article_detail")),
            },
        }
        self.jobs[str(job["jobId"])] = job
        return dict(job)

    def get(self, job_id: str) -> dict[str, object]:
        return dict(self.jobs[job_id])


def _backend(
    temp_dir: str,
    *,
    probe: object,
    huey: object,
) -> DevBackendContext:
    return DevBackendContext(
        project_root=Path(temp_dir),
        runtime=SimpleNamespace(config=SimpleNamespace()),
        db_path=Path(temp_dir) / "archive.sqlite3",
        task_manager=object(),
        article_detail_card_probe_service=probe,
        initial_content_storage_huey_service=huey,
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
        "homeWindowHandle": 100,
    }
    return {
        "ok": True,
        "status": "completed",
        "message": "已识别可视区第一篇文章卡片。",
        "tone": "success",
        "items": [{"kind": "article", "label": "第1条文章", "value": "第一篇测试文章"}],
        "records": [card],
        "accountName": "汝城发布",
        "captureType": "none",
    }


if __name__ == "__main__":
    unittest.main()
