from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.domain.enums import ProcessMessageType
from src.modules.archive.offline_archiver import OfflineArchiveResult
from src.modules.processes.offline_cache_process import run_offline_cache_process


class _RecordingConnection:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, message: dict) -> None:
        self.messages.append(message)


class OfflineCacheProcessTest(unittest.TestCase):
    def test_child_reports_ready_progress_and_result_for_one_article(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage_dir = Path(directory) / "stage"
            connection = _RecordingConnection()

            def fake_archive(request, *, on_event):
                on_event({"name": "页面滚动", "status": "running", "elapsed_seconds": 0.2})
                (request.stage_dir / "assets").mkdir(parents=True)
                (request.stage_dir / "index.html").write_text("<html></html>", encoding="utf-8")
                return OfflineArchiveResult(
                    ok=True,
                    stage_dir=request.stage_dir,
                    index_html_path=request.stage_dir / "index.html",
                    assets_dir=request.stage_dir / "assets",
                    resource_count=4,
                    message="离线缓存完成",
                )

            run_offline_cache_process(
                connection=connection,
                task_id="cache-job",
                attempt_id="article-7",
                payload=self._payload(stage_dir),
                archive_func=fake_archive,
            )

            message_types = [item["message_type"] for item in connection.messages]
            self.assertEqual(
                message_types,
                [
                    ProcessMessageType.READY.value,
                    ProcessMessageType.PROGRESS.value,
                    ProcessMessageType.RESULT.value,
                ],
            )
            result = connection.messages[-1]["payload"]["offline_cache_result"]
            self.assertTrue(result["ok"])
            self.assertEqual(result["article_id"], 7)
            self.assertEqual(result["resource_count"], 4)
            self.assertEqual(result["stage_dir"], str(stage_dir))

    def test_child_reports_failed_when_archiver_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = _RecordingConnection()

            def failing_archive(_request, *, on_event):
                raise RuntimeError("browser unavailable")

            run_offline_cache_process(
                connection=connection,
                task_id="cache-job",
                attempt_id="article-7",
                payload=self._payload(Path(directory) / "stage"),
                archive_func=failing_archive,
            )

            self.assertEqual(connection.messages[-1]["message_type"], ProcessMessageType.FAILED.value)
            result = connection.messages[-1]["payload"]["offline_cache_result"]
            self.assertFalse(result["ok"])
            self.assertIn("browser unavailable", result["message"])

    @staticmethod
    def _payload(stage_dir: Path) -> dict[str, object]:
        return {
            "article_id": 7,
            "article_title": "测试文章",
            "article_link": "https://mp.weixin.qq.com/s/test",
            "stage_dir": str(stage_dir),
            "browser_cache_dir": str(stage_dir.parent / ".playwright-browsers"),
            "max_scroll_seconds": 30.0,
            "max_scroll_count": 30,
            "resource_timeout_seconds": 10.0,
        }


if __name__ == "__main__":
    unittest.main()
