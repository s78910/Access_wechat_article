from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class FakeTaskManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def start_task(self, options=None) -> dict:
        self.calls.append(("start_task", options))
        return {"ok": True, "status": "running"}

    def stop_task(self) -> dict:
        self.calls.append(("stop_task", None))
        return {"ok": True, "status": "stopped"}

    def get_status(self, refresh_home: bool = True) -> dict:
        self.calls.append(("get_status", refresh_home))
        return {"ok": True, "status": "idle", "refreshHome": refresh_home}

    def get_logs(self, limit: int = 100) -> list[dict]:
        self.calls.append(("get_logs", limit))
        return [{"level": "INFO", "message": "ok"}]

    def start_mitm_proxy(self) -> dict:
        self.calls.append(("start_mitm_proxy", None))
        return {"ok": True, "status": "mitm-started"}

    def stop_mitm_proxy(self) -> dict:
        self.calls.append(("stop_mitm_proxy", None))
        return {"ok": True, "status": "mitm-stopped"}

    def enable_system_proxy(self) -> dict:
        self.calls.append(("enable_system_proxy", None))
        return {"ok": True, "status": "proxy-enabled"}

    def disable_system_proxy(self) -> dict:
        self.calls.append(("disable_system_proxy", None))
        return {"ok": True, "status": "proxy-disabled"}

    def update_config(self, config, config_path: str | None = None) -> dict:
        self.calls.append(("update_config", config_path))
        return {"ok": True, "status": "saved"}

    def shutdown(self) -> None:
        self.calls.append(("shutdown", None))

    def log_runtime_error(self, message: str, source: str = "runtime") -> None:
        self.calls.append(("log_runtime_error", (message, source)))


class SimpleArchitectureServicesTest(unittest.TestCase):
    def test_task_service_delegates_task_flow_to_manager(self) -> None:
        from src.services.task_service import TaskService

        manager = FakeTaskManager()
        service = TaskService(manager)

        self.assertEqual(service.start_task({"recordLimit": 1})["status"], "running")
        self.assertEqual(service.stop_task()["status"], "stopped")
        self.assertEqual(service.get_status(refresh_home=False)["refreshHome"], False)
        self.assertEqual(service.get_logs(10)[0]["message"], "ok")

        self.assertEqual(
            manager.calls[:4],
            [
                ("start_task", {"recordLimit": 1}),
                ("stop_task", None),
                ("get_status", False),
                ("get_logs", 10),
            ],
        )

    def test_proxy_service_delegates_proxy_operations_to_manager(self) -> None:
        from src.services.proxy_service import ProxyService

        manager = FakeTaskManager()
        service = ProxyService(manager)

        self.assertEqual(service.start_mitm_proxy()["status"], "mitm-started")
        self.assertEqual(service.stop_mitm_proxy()["status"], "mitm-stopped")
        self.assertEqual(service.enable_system_proxy()["status"], "proxy-enabled")
        self.assertEqual(service.disable_system_proxy()["status"], "proxy-disabled")

    def test_article_service_uses_injected_fetcher_and_writer(self) -> None:
        from src.services.article_service import ArticleService

        def fake_fetcher(keyed_url, *, request_headers=None, timeout_seconds=10.0, collect_time=None):
            return {
                "short_link": "https://mp.weixin.qq.com/s/demo",
                "article_title": "demo",
                "collect_time": collect_time,
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            service = ArticleService(fetch_detail=fake_fetcher)
            result = service.fetch_detail_to_archive(
                "https://mp.weixin.qq.com/s?__biz=demo&key=secret",
                Path(temp_dir),
                collect_time="2026-06-20 14:00:00",
            )

            self.assertEqual(result["detail"]["article_title"], "demo")
            self.assertTrue(Path(result["article_detail_path"]).exists())

    def test_comment_service_uses_injected_fetcher(self) -> None:
        from src.services.comment_service import CommentService

        def fake_fetcher(keyed_url, source_html, archive_dir, **kwargs):
            return {"ok": True, "comment_count": 2, "archiveDir": str(archive_dir)}

        service = CommentService(fetch_comments=fake_fetcher)
        result = service.fetch_comments_to_archive(
            "https://mp.weixin.qq.com/s?__biz=demo&key=secret",
            "<html></html>",
            Path("storages/demo"),
        )

        self.assertEqual(result["comment_count"], 2)

    def test_beginner_friendly_worker_and_utils_modules_are_importable(self) -> None:
        from src.modules.system.env_checker import get_system_status
        from src.modules.utils.file_utils import clean_path_part, ensure_directory
        from src.modules.utils.text_utils import normalize_text
        from src.modules.utils.time_utils import format_datetime_for_dir
        from src.workers.article_worker import run_article_capture_worker
        from src.workers.wechat_worker import detect_wechat_home_window

        self.assertTrue(callable(run_article_capture_worker))
        self.assertTrue(callable(detect_wechat_home_window))
        self.assertEqual(clean_path_part(' a<b>c '), "a_b_c")
        self.assertEqual(normalize_text("  hello  "), "hello")
        self.assertEqual(format_datetime_for_dir("2026-06-20 14:30:00"), "2026-06-20 14-30")
        self.assertIn("pythonVersion", get_system_status())

        with tempfile.TemporaryDirectory() as temp_dir:
            target = ensure_directory(Path(temp_dir) / "demo")
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
