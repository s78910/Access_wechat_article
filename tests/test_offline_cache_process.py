from __future__ import annotations

import json
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

    def test_stateful_payload_builds_navigation_from_origin_request_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_directory = root / "article"
            request_json = article_directory / "origin" / "request.json"
            request_json.parent.mkdir(parents=True)
            reference_url = (
                "https://mp.weixin.qq.com/s?__biz=test&mid=1&idx=1&sn=abc"
                "&key=secret&pass_ticket=ticket&exportkey=encoded%2Bexport"
                "&fasttmpl_fullversion=8394604-zh_CN-html&fasttmpl_type=0"
            )
            request_json.write_text(
                json.dumps(
                    {
                        "reference": {
                            "url": reference_url,
                            "request_headers": {
                                "User-Agent": "Wechat UserAgent",
                                "Accept": "image/avif,image/webp,*/*",
                                "Accept-Language": "zh-CN,zh;q=0.9",
                                "Cookie": "wxuin=123; pass_ticket=abc",
                                "Referer": reference_url,
                                "If-Modified-Since": "Tue, 18 Aug 2026 15:51:22 +0800",
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            connection = _RecordingConnection()
            received = {}

            def fake_archive(request, *, on_event):
                received["request"] = request
                return OfflineArchiveResult(
                    ok=True,
                    stage_dir=request.stage_dir,
                    index_html_path=request.stage_dir / "index.html",
                    assets_dir=request.stage_dir / "assets",
                    resource_count=0,
                    message="离线缓存完成",
                )

            payload = self._payload(root / "stage")
            payload["article_directory"] = str(article_directory)
            payload["request_json_path"] = str(request_json)
            payload["stateful_offline_cache"] = True

            run_offline_cache_process(
                connection=connection,
                task_id="cache-job",
                attempt_id="article-7",
                payload=payload,
                archive_func=fake_archive,
            )

            request = received["request"]
            self.assertEqual(request.navigation_mode, "stateful")
            self.assertEqual(request.navigation_url, reference_url)
            self.assertEqual(request.navigation_user_agent, "Wechat UserAgent")
            self.assertIn("Accept-Language", request.navigation_headers)
            self.assertNotIn("Cookie", request.navigation_headers)
            self.assertIn("text/html", request.navigation_headers["Accept"])
            self.assertNotIn("If-Modified-Since", request.navigation_headers)
            self.assertEqual(request.navigation_headers["Sec-Fetch-Dest"], "document")
            self.assertEqual(request.navigation_headers["Sec-Fetch-Mode"], "navigate")
            self.assertEqual(request.navigation_headers["Sec-Fetch-Site"], "same-origin")
            self.assertEqual(request.navigation_headers["exportkey"], "encoded%2Bexport")
            self.assertEqual(
                request.navigation_headers["Referer"],
                (
                    "https://mp.weixin.qq.com/s/index.html?data_version=8394604"
                    "&fasttmpl_fullversion=8394604-zh_CN-html&fasttmpl_type=0"
                ),
            )
            self.assertEqual(request.navigation_cookies[0]["name"], "wxuin")
            self.assertEqual(
                connection.messages[-1]["payload"]["offline_cache_result"]["navigation_mode"],
                "stateful",
            )

    @staticmethod
    def _payload(stage_dir: Path) -> dict[str, object]:
        return {
            "article_id": 7,
            "article_title": "测试文章",
            "article_link": "https://mp.weixin.qq.com/s/test",
            "stage_dir": str(stage_dir),
            "browser_cache_dir": str(stage_dir.parent / ".playwright-browsers"),
            "max_scroll_seconds": 30.0,
            "resource_timeout_seconds": 10.0,
        }


if __name__ == "__main__":
    unittest.main()
