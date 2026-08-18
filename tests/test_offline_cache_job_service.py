from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.services.archive.offline_cache_job_service import OfflineCacheJobService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeAttempt:
    def __init__(self, payload: dict[str, object], tracker: "_ProcessTracker") -> None:
        self.payload = payload
        self.tracker = tracker

    def wait_ready(self, *, timeout_seconds: float):
        return {"article_id": self.payload["article_id"]}

    def wait_result(self, *, timeout_seconds: float, on_progress=None):
        with self.tracker.lock:
            self.tracker.active += 1
            self.tracker.maximum = max(self.tracker.maximum, self.tracker.active)
        try:
            stage_dir = Path(str(self.payload["stage_dir"]))
            assets_dir = stage_dir / "assets"
            assets_dir.mkdir(parents=True)
            (stage_dir / "index.html").write_text(
                f"new-{self.payload['article_id']}",
                encoding="utf-8",
            )
            (assets_dir / "image.jpg").write_bytes(b"new-image")
            time.sleep(0.02)
            return {
                "ok": True,
                "article_id": int(self.payload["article_id"]),
                "stage_dir": str(stage_dir),
                "index_html_path": str(stage_dir / "index.html"),
                "assets_dir": str(assets_dir),
                "resource_count": 1,
                "message": "离线缓存完成",
                "warning": "",
                "elapsed_seconds": 0.02,
            }
        finally:
            with self.tracker.lock:
                self.tracker.active -= 1

    def cancel(self) -> None:
        return None


class _FakeProcessControl:
    def __init__(self, tracker: "_ProcessTracker") -> None:
        self.tracker = tracker

    def start(self, *, task_id: str, attempt_id: str, payload: dict[str, object]):
        self.tracker.payloads.append(dict(payload))
        return _FakeAttempt(dict(payload), self.tracker)


class _ProcessTracker:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.active = 0
        self.maximum = 0
        self.lock = threading.Lock()


class _BlockingAttempt:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def wait_ready(self, *, timeout_seconds: float):
        return {"article_id": self.payload["article_id"]}

    def wait_result(self, *, timeout_seconds: float, on_progress=None):
        stage_dir = Path(str(self.payload["stage_dir"]))
        stage_dir.mkdir(parents=True)
        (stage_dir / "working.tmp").write_text("running", encoding="utf-8")
        if on_progress is not None:
            on_progress({"name": "页面滚动 2/30", "elapsed_seconds": 0.25})
        self.started.set()
        if not self.cancelled.wait(2.0):
            raise RuntimeError("测试子进程未收到取消")
        time.sleep(0.05)
        raise RuntimeError("测试子进程已取消")

    def cancel(self) -> None:
        self.cancelled.set()


class _BlockingProcessControl:
    def __init__(self) -> None:
        self.attempt: _BlockingAttempt | None = None

    def start(self, *, task_id: str, attempt_id: str, payload: dict[str, object]):
        self.attempt = _BlockingAttempt(dict(payload))
        return self.attempt


class OfflineCacheJobServiceTest(unittest.TestCase):
    def test_selected_article_refreshes_and_atomically_replaces_existing_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_id = self._insert_article(db_path, storage_root, title="文章一", slug="one")
            article_dir = storage_root / "测试公众号" / "文章一"
            (article_dir / "assets").mkdir(parents=True)
            (article_dir / "index.html").write_text("old", encoding="utf-8")
            (article_dir / "assets" / "old.jpg").write_bytes(b"old-image")
            tracker = _ProcessTracker()
            service = self._service(db_path, storage_root, temp_root, root, tracker)

            job = service.create_articles_job([article_id], start=False)
            service.run_job(job.job_id)
            snapshot = service.get_job(job.job_id)

            self.assertEqual((article_dir / "index.html").read_text(encoding="utf-8"), f"new-{article_id}")
            self.assertFalse((article_dir / "assets" / "old.jpg").exists())
            self.assertEqual(snapshot.status, "done")
            self.assertEqual(snapshot.skipped, 0)
            self.assertEqual(len(tracker.payloads), 1)
            self._assert_offline_manifest_and_history(db_path, article_id)

    def test_account_job_skips_existing_cache_and_runs_only_missing_articles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            existing_id = self._insert_article(db_path, storage_root, title="已有缓存", slug="existing")
            missing_id = self._insert_article(db_path, storage_root, title="缺少缓存", slug="missing")
            existing_dir = storage_root / "测试公众号" / "已有缓存"
            (existing_dir / "assets").mkdir(parents=True)
            (existing_dir / "index.html").write_text("cached", encoding="utf-8")
            tracker = _ProcessTracker()
            service = self._service(db_path, storage_root, temp_root, root, tracker)

            job = service.create_account_job(1, start=False)
            service.run_job(job.job_id)
            snapshot = service.get_job(job.job_id)

            self.assertEqual(snapshot.total, 1)
            self.assertEqual(snapshot.skipped, 1)
            self.assertEqual([payload["article_id"] for payload in tracker.payloads], [missing_id])
            self.assertEqual(existing_id, 1)
            payload = snapshot.to_payload()
            self.assertEqual(payload["requestedTotal"], 2)
            self.assertEqual(payload["processed"], 2)
            self.assertEqual(payload["queued"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["activeProcesses"], [])
            self._assert_offline_manifest_and_history(db_path, missing_id)

    def test_batch_job_limits_simultaneous_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_ids = [
                self._insert_article(db_path, storage_root, title=f"文章{index}", slug=f"item-{index}")
                for index in range(5)
            ]
            tracker = _ProcessTracker()
            service = self._service(db_path, storage_root, temp_root, root, tracker)

            job = service.create_articles_job(article_ids, start=False)
            service.run_job(job.job_id)

            self.assertEqual(service.get_job(job.job_id).status, "done")
            self.assertEqual(tracker.maximum, 3)

    def test_shutdown_prevents_pending_job_from_starting_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_id = self._insert_article(db_path, storage_root, title="待停止文章", slug="pending")
            tracker = _ProcessTracker()
            service = self._service(db_path, storage_root, temp_root, root, tracker)

            job = service.create_articles_job([article_id], start=False)
            service.shutdown()
            service.run_job(job.job_id)

            self.assertEqual(tracker.payloads, [])
            self.assertEqual(service.get_job(job.job_id).status, "failed")

    def test_invalid_wechat_short_link_is_rejected_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_id = self._insert_article(db_path, storage_root, title="无效链接文章", slug="invalid")
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "UPDATE awa_public_articles SET article_link = ? WHERE id = ?",
                    ("https://example.com/s/invalid", article_id),
                )
                connection.commit()
            finally:
                connection.close()
            tracker = _ProcessTracker()
            service = self._service(db_path, storage_root, temp_root, root, tracker)

            job = service.create_articles_job([article_id], start=False)
            service.run_job(job.job_id)
            snapshot = service.get_job(job.job_id)

            self.assertEqual(tracker.payloads, [])
            self.assertEqual(snapshot.status, "partial_failed")
            self.assertIn("微信文章短链", snapshot.results[0].message)
            self.assertEqual(snapshot.to_payload()["failed"], 1)

    def test_running_job_exposes_active_process_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_id = self._insert_article(db_path, storage_root, title="进度文章", slug="progress")
            process_control = _BlockingProcessControl()
            service = OfflineCacheJobService(
                database_path=db_path,
                storage_root=storage_root,
                temp_root=temp_root,
                browser_cache_dir=root / ".playwright-browsers",
                max_concurrent_processes=3,
                max_scroll_seconds=30,
                resource_timeout_seconds=10,
                process_control=process_control,
            )

            job = service.create_articles_job([article_id])
            deadline = time.monotonic() + 1.0
            while process_control.attempt is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(process_control.attempt)
            assert process_control.attempt is not None
            self.assertTrue(process_control.attempt.started.wait(1.0))

            payload = service.get_job(job.job_id).to_payload()

            self.assertEqual(payload["requestedTotal"], 1)
            self.assertEqual(payload["processed"], 0)
            self.assertEqual(payload["running"], 1)
            self.assertEqual(payload["queued"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(len(payload["activeProcesses"]), 1)
            self.assertEqual(payload["activeProcesses"][0]["articleId"], article_id)
            self.assertEqual(payload["activeProcesses"][0]["status"], "running")
            self.assertEqual(payload["activeProcesses"][0]["step"], "页面滚动 2/30")
            self.assertGreaterEqual(payload["activeProcesses"][0]["elapsedSeconds"], 0.25)
            service.shutdown()

    def test_shutdown_waits_for_running_job_and_cleans_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, db_path, storage_root, temp_root = self._prepare_environment(Path(directory))
            article_id = self._insert_article(db_path, storage_root, title="运行中文章", slug="running")
            process_control = _BlockingProcessControl()
            service = OfflineCacheJobService(
                database_path=db_path,
                storage_root=storage_root,
                temp_root=temp_root,
                browser_cache_dir=root / ".playwright-browsers",
                max_concurrent_processes=3,
                max_scroll_seconds=30,
                resource_timeout_seconds=10,
                process_control=process_control,
            )

            job = service.create_articles_job([article_id])
            deadline = time.monotonic() + 1.0
            while process_control.attempt is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(process_control.attempt)
            assert process_control.attempt is not None
            self.assertTrue(process_control.attempt.started.wait(1.0))

            service.shutdown()

            self.assertTrue(process_control.attempt.cancelled.is_set())
            self.assertFalse(service.is_busy())
            self.assertFalse((temp_root / "offline-cache" / job.job_id).exists())

    @staticmethod
    def _service(db_path: Path, storage_root: Path, temp_root: Path, root: Path, tracker: _ProcessTracker):
        return OfflineCacheJobService(
            database_path=db_path,
            storage_root=storage_root,
            temp_root=temp_root,
            browser_cache_dir=root / ".playwright-browsers",
            max_concurrent_processes=3,
            max_scroll_seconds=30,
            resource_timeout_seconds=10,
            process_control=_FakeProcessControl(tracker),
        )

    @staticmethod
    def _prepare_environment(root: Path) -> tuple[Path, Path, Path, Path]:
        db_path = root / "awa.sqlite3"
        storage_root = root / "storages"
        temp_root = root / "tmp"
        storage_root.mkdir()
        temp_root.mkdir()
        script = (PROJECT_ROOT / "data" / "sql" / "create_script" / "create_awa_v2_1.sql").read_text(
            encoding="utf-8"
        )
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(script)
            connection.execute("INSERT INTO awa_public_accounts(account_name) VALUES ('测试公众号')")
            connection.commit()
        finally:
            connection.close()
        return root, db_path, storage_root, temp_root

    @staticmethod
    def _insert_article(db_path: Path, storage_root: Path, *, title: str, slug: str) -> int:
        relative_dir = f"测试公众号/{title}"
        (storage_root / relative_dir).mkdir(parents=True)
        connection = sqlite3.connect(db_path)
        try:
            cursor = connection.execute(
                """
                INSERT INTO awa_public_articles(
                    account_id,
                    article_title,
                    published_article_time,
                    article_link,
                    archive_dir,
                    resource_types_json
                ) VALUES (1, ?, '2026-08-10 12:00', ?, ?, '[]')
                """,
                (title, f"https://mp.weixin.qq.com/s/{slug}", relative_dir),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def _assert_offline_manifest_and_history(self, db_path: Path, article_id: int) -> None:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            article = connection.execute(
                "SELECT resource_types_json FROM awa_public_articles WHERE id = ?",
                (article_id,),
            ).fetchone()
            history = connection.execute(
                "SELECT task_type, status FROM awa_fetch_history WHERE article_id = ?",
                (article_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(article)
        self.assertIsNotNone(history)
        resources = json.loads(article["resource_types_json"])
        self.assertIn("offline_html", resources)
        self.assertIn("offline_assets", resources)
        self.assertEqual(history["task_type"], "offline_cache")
        self.assertEqual(history["status"], "success")


if __name__ == "__main__":
    unittest.main()
