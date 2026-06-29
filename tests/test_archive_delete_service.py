from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.modules.storage.archive_delete_service import ArchiveDeleteService
from src.modules.storage.sqlite_store import SQLiteStore


class ArchiveDeleteServiceTest(unittest.TestCase):
    def test_delete_articles_removes_sqlite_rows_and_matching_duplicate_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            storage_root = Path(temp_dir) / "storages"
            store = SQLiteStore(db_path)
            article_id = store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "测试文章",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/right",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            keep_article_id = store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "保留文章",
                    "published_article_time": "2026-06-19 18:40",
                    "article_link": "https://mp.weixin.qq.com/s/keep",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:41:00",
                    "collect_status": "saved",
                }
            )
            first_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章"
            second_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章_1"
            other_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章_2"
            for directory, short_link in (
                (first_dir, "https://mp.weixin.qq.com/s/right"),
                (second_dir, "https://mp.weixin.qq.com/s/right"),
                (other_dir, "https://mp.weixin.qq.com/s/other"),
            ):
                directory.mkdir(parents=True)
                (directory / "article_detail.json").write_text(
                    json.dumps({"short_link": short_link}, ensure_ascii=False),
                    encoding="utf-8",
                )
                (directory / "original_main.html").write_text("html", encoding="utf-8")

            result = ArchiveDeleteService(store=store, storage_root=storage_root).delete_articles([article_id])

            self.assertTrue(result.ok)
            self.assertEqual(result.deleted_article_count, 1)
            self.assertEqual(result.deleted_account_count, 0)
            self.assertEqual(result.deleted_archive_dir_count, 2)
            self.assertFalse(first_dir.exists())
            self.assertFalse(second_dir.exists())
            self.assertTrue(other_dir.exists())
            self.assertEqual(store.count_public_articles(), 1)
            self.assertEqual(store.get_public_articles_by_ids([keep_article_id])[0]["article_title"], "保留文章")

    def test_delete_account_removes_all_article_dirs_then_account_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            storage_root = Path(temp_dir) / "storages"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "文章A1",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/a-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "文章A2",
                    "published_article_time": "2026-06-19 18:40",
                    "article_link": "https://mp.weixin.qq.com/s/a-2",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:41:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号B",
                    "article_title": "文章B1",
                    "published_article_time": "2026-06-19 18:50",
                    "article_link": "https://mp.weixin.qq.com/s/b-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:51:00",
                    "collect_status": "saved",
                }
            )
            account_a = next(row for row in store.list_public_accounts() if row["account_name"] == "账号A")
            account_b = next(row for row in store.list_public_accounts() if row["account_name"] == "账号B")
            a1_dir = storage_root / "账号A" / "2026-06-19 18-30 文章A1"
            a2_dir = storage_root / "账号A" / "2026-06-19 18-40 文章A2"
            b1_dir = storage_root / "账号B" / "2026-06-19 18-50 文章B1"
            for directory, short_link in (
                (a1_dir, "https://mp.weixin.qq.com/s/a-1"),
                (a2_dir, "https://mp.weixin.qq.com/s/a-2"),
                (b1_dir, "https://mp.weixin.qq.com/s/b-1"),
            ):
                directory.mkdir(parents=True)
                (directory / "article_detail.json").write_text(
                    json.dumps({"short_link": short_link}, ensure_ascii=False),
                    encoding="utf-8",
                )

            result = ArchiveDeleteService(store=store, storage_root=storage_root).delete_account(int(account_a["id"]))

            self.assertTrue(result.ok)
            self.assertEqual(result.deleted_article_count, 2)
            self.assertEqual(result.deleted_account_count, 1)
            self.assertEqual(result.deleted_archive_dir_count, 2)
            self.assertFalse(a1_dir.exists())
            self.assertFalse(a2_dir.exists())
            self.assertTrue(b1_dir.exists())
            self.assertEqual(store.count_public_accounts(), 1)
            self.assertEqual(store.list_public_accounts()[0]["id"], account_b["id"])

    def test_delete_all_removes_every_account_and_article_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            storage_root = Path(temp_dir) / "storages"
            store = SQLiteStore(db_path)
            for account_name, title, link in (
                ("账号A", "文章A", "https://mp.weixin.qq.com/s/a"),
                ("账号B", "文章B", "https://mp.weixin.qq.com/s/b"),
            ):
                store.save_public_article(
                    {
                        "account_name": account_name,
                        "article_title": title,
                        "published_article_time": "2026-06-19 18:30",
                        "article_link": link,
                        "record_type": "文章详情",
                        "collect_time": "2026-06-19 18:31:00",
                        "collect_status": "saved",
                    }
                )
                archive_dir = storage_root / account_name / f"2026-06-19 18-30 {title}"
                archive_dir.mkdir(parents=True)
                (archive_dir / "article_detail.json").write_text(
                    json.dumps({"short_link": link}, ensure_ascii=False),
                    encoding="utf-8",
                )

            result = ArchiveDeleteService(store=store, storage_root=storage_root).delete_all()

            self.assertTrue(result.ok)
            self.assertEqual(result.deleted_article_count, 2)
            self.assertEqual(result.deleted_account_count, 2)
            self.assertEqual(result.deleted_archive_dir_count, 2)
            self.assertEqual(store.count_public_accounts(), 0)
            self.assertEqual(store.count_public_articles(), 0)
            self.assertEqual([path for path in storage_root.rglob("*") if path.is_dir()], [])


if __name__ == "__main__":
    unittest.main()
