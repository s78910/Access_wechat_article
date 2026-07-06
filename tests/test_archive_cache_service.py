from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from src.modules.html_archive.models import ArticleHtmlArchiveConfig, ArticleHtmlArchiveResult, ArticleHtmlArchiveTask
from src.modules.storage.sqlite_store import SQLiteStore


class ArchiveCacheServiceTest(unittest.TestCase):
    def test_build_cache_tasks_from_article_ids_and_account_id(self) -> None:
        from src.modules.html_archive.archive_cache_service import build_cache_tasks_for_account, build_cache_tasks_for_articles

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            first_id = store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "第一篇",
                    "published_article_time": "2026-06-20 10:30",
                    "article_link": "https://mp.weixin.qq.com/s/first",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 10:31:00",
                    "collect_status": "saved",
                }
            )
            second_id = store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "第二篇",
                    "published_article_time": "2026-06-20 11:30",
                    "article_link": "https://mp.weixin.qq.com/s/second",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 11:31:00",
                    "collect_status": "saved",
                }
            )
            other_id = store.save_public_article(
                {
                    "account_name": "其他公众号",
                    "article_title": "其他篇",
                    "published_article_time": "2026-06-20 12:30",
                    "article_link": "https://mp.weixin.qq.com/s/other",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 12:31:00",
                    "collect_status": "saved",
                }
            )
            account_id = int(next(row["id"] for row in store.list_public_accounts() if row["account_name"] == "测试公众号"))

            selected_tasks = build_cache_tasks_for_articles(store, [second_id, first_id, other_id], storage_root=root / "storages")
            account_tasks = build_cache_tasks_for_account(store, account_id, storage_root=root / "storages")

        self.assertEqual([task.article_id for task in selected_tasks], [second_id, first_id, other_id])
        self.assertEqual(selected_tasks[0].short_link, "https://mp.weixin.qq.com/s/second")
        self.assertEqual(selected_tasks[0].account_name, "测试公众号")
        self.assertEqual(selected_tasks[0].storage_root, root / "storages")
        self.assertEqual([task.article_title for task in account_tasks], ["第二篇", "第一篇"])

    def test_archive_cache_job_runs_with_concurrency_limit_three_and_records_each_article(self) -> None:
        from src.modules.html_archive.archive_cache_service import ArchiveCacheJobRunner

        captured_workers: list[int] = []

        class FakeExecutor:
            def __init__(self, max_workers: int):
                captured_workers.append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def submit(self, func, task, config):
                future: Future = Future()
                future.set_result(func(task, config))
                return future

        def fake_archive(task: ArticleHtmlArchiveTask, config: ArticleHtmlArchiveConfig):
            self.assertEqual(config.concurrency, 3)
            return ArticleHtmlArchiveResult(
                ok=True,
                archive_dir=Path("storages") / task.account_name / task.article_title,
                index_html_path=Path("storages") / task.account_name / task.article_title / "index.html",
                resource_count=2,
                message="HTML 离线归档完成",
            )

        tasks = [
            ArticleHtmlArchiveTask(index, f"https://mp.weixin.qq.com/s/{index}", "账号", "2026-06-20 10:30", f"文章{index}", Path("storages"))
            for index in range(1, 6)
        ]
        runner = ArchiveCacheJobRunner(
            concurrency=3,
            archive_func=fake_archive,
            executor_factory=FakeExecutor,
        )

        job = runner.create_job(tasks)
        runner.run_job(job.job_id)
        snapshot = runner.get_job(job.job_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual(captured_workers, [3])
        self.assertEqual(snapshot.status, "done")
        self.assertEqual(snapshot.total, 5)
        self.assertEqual(snapshot.finished, 5)
        result_by_id = {item.article_id: item for item in snapshot.results}
        self.assertEqual(sorted(result_by_id), [1, 2, 3, 4, 5])
        self.assertEqual(result_by_id[1].article_title, "文章1")
        self.assertTrue(all(item.ok for item in snapshot.results))
        self.assertEqual(result_by_id[1].index_html_path, str(Path("storages") / "账号" / "文章1" / "index.html"))

    def test_archive_cache_job_records_results_as_each_article_finishes(self) -> None:
        from src.modules.html_archive.archive_cache_service import ArchiveCacheJobRunner

        submitted_futures: list[Future] = []

        def fake_archive(task: ArticleHtmlArchiveTask, config: ArticleHtmlArchiveConfig):
            return ArticleHtmlArchiveResult(
                ok=True,
                archive_dir=Path("storages") / task.account_name / task.article_title,
                index_html_path=Path("storages") / task.account_name / task.article_title / "index.html",
                resource_count=1,
                message="HTML 离线归档完成",
            )

        class FakeExecutor:
            def __init__(self, max_workers: int):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def submit(self, func, task, config):
                future: Future = Future()
                future.task = task
                future.func = func
                future.config = config
                submitted_futures.append(future)
                return future

        def fake_as_completed(futures):
            future_by_article_id = {future.task.article_id: future for future in futures}
            for article_id in (2, 1):
                future = future_by_article_id[article_id]
                future.set_result(future.func(future.task, future.config))
                yield future

        tasks = [
            ArticleHtmlArchiveTask(1, "https://mp.weixin.qq.com/s/slow", "账号", "2026-06-20 10:30", "慢文章", Path("storages")),
            ArticleHtmlArchiveTask(2, "https://mp.weixin.qq.com/s/fast", "账号", "2026-06-20 10:31", "快文章", Path("storages")),
        ]
        runner = ArchiveCacheJobRunner(
            concurrency=2,
            archive_func=fake_archive,
            executor_factory=FakeExecutor,
        )

        job = runner.create_job(tasks)
        with patch("src.modules.html_archive.archive_cache_service.as_completed", fake_as_completed):
            runner.run_job(job.job_id)
        snapshot = runner.get_job(job.job_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual([item.article_id for item in snapshot.results], [2, 1])


if __name__ == "__main__":
    unittest.main()
