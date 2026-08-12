from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.config.config_loader import load_app_config
from src.services.archive.offline_cache_job_service import has_complete_offline_cache
from src.storage.repositories.article_repository import ArticleRepository
from src.storage.sqlite.connection import sqlite_connection


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OfflineCacheFoundationTest(unittest.TestCase):
    def test_config_loads_offline_cache_process_concurrency(self) -> None:
        config = load_app_config(
            PROJECT_ROOT / "src" / "config" / "system.yaml",
            project_root=PROJECT_ROOT,
        )

        self.assertFalse(config.offline_cache.enabled_by_default)
        self.assertEqual(config.offline_cache.max_concurrent_processes, 3)

    def test_article_repository_preserves_selected_order_and_lists_account_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "archive.sqlite3"
            self._create_database(db_path)
            with sqlite_connection(db_path) as connection:
                account_id = connection.execute(
                    "INSERT INTO awa_public_accounts(account_name) VALUES (?)",
                    ("测试公众号",),
                ).lastrowid
                first_id = self._insert_article(connection, int(account_id), "文章一", "https://mp.weixin.qq.com/s/one")
                second_id = self._insert_article(connection, int(account_id), "文章二", "https://mp.weixin.qq.com/s/two")
                repository = ArticleRepository(connection)

                selected = repository.list_offline_cache_records_by_ids([second_id, first_id, second_id])
                account_records = repository.list_offline_cache_records_by_account(int(account_id))

            self.assertEqual([item.id for item in selected], [second_id, first_id])
            self.assertEqual([item.account_name for item in selected], ["测试公众号", "测试公众号"])
            self.assertEqual({item.id for item in account_records}, {first_id, second_id})

    def test_complete_cache_requires_index_file_and_assets_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_dir = Path(directory) / "article"
            archive_dir.mkdir()

            self.assertFalse(has_complete_offline_cache(archive_dir))
            (archive_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            self.assertFalse(has_complete_offline_cache(archive_dir))
            (archive_dir / "assets").mkdir()
            self.assertTrue(has_complete_offline_cache(archive_dir))

    @staticmethod
    def _create_database(db_path: Path) -> None:
        script = (PROJECT_ROOT / "data" / "sql" / "create_script" / "create_awa_v2_1.sql").read_text(
            encoding="utf-8"
        )
        import sqlite3

        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(script)
        finally:
            connection.close()

    @staticmethod
    def _insert_article(connection, account_id: int, title: str, link: str) -> int:
        cursor = connection.execute(
            """
            INSERT INTO awa_public_articles(
                account_id,
                article_title,
                published_article_time,
                article_link,
                archive_dir,
                resource_types_json
            ) VALUES (?, ?, ?, ?, ?, '[]')
            """,
            (account_id, title, "2026-08-10 12:00", link, f"测试公众号/{title}"),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
