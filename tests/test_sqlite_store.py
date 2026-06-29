from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.modules.storage.sqlite_store import SQLiteStore


class SQLiteStoreTest(unittest.TestCase):
    def test_list_public_accounts_returns_article_summary_ordered_by_latest_collect_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)

            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "第一篇",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-a-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号B",
                    "article_title": "第二篇",
                    "published_article_time": "2026-06-19 19:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-b-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 19:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "失败记录",
                    "published_article_time": "2026-06-19 20:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-a-2",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 20:31:00",
                    "collect_status": "failed",
                }
            )

            rows = store.list_public_accounts()

            self.assertEqual([row["account_name"] for row in rows], ["账号A", "账号B"])
            self.assertEqual(rows[0]["article_count"], 2)
            self.assertEqual(rows[0]["saved_count"], 1)
            self.assertEqual(rows[0]["failed_count"], 1)
            self.assertEqual(rows[0]["latest_collect_time"], "2026-06-19 20:31:00")
            self.assertEqual(rows[1]["article_count"], 1)
            self.assertEqual(rows[1]["saved_count"], 1)
            self.assertEqual(rows[1]["failed_count"], 0)

    def test_list_public_articles_by_account_returns_latest_records_only_for_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)

            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "较早文章",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-a-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号A",
                    "article_title": "较新文章",
                    "published_article_time": "2026-06-19 20:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-a-2",
                    "record_type": "评论信息",
                    "collect_time": "2026-06-19 20:31:00",
                    "collect_status": "failed",
                }
            )
            store.save_public_article(
                {
                    "account_name": "账号B",
                    "article_title": "其他账号文章",
                    "published_article_time": "2026-06-19 19:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-b-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 19:31:00",
                    "collect_status": "saved",
                }
            )
            account_id = store.list_public_accounts()[0]["id"]

            rows = store.list_public_articles_by_account(int(account_id))

            self.assertEqual([row["article_title"] for row in rows], ["较新文章", "较早文章"])
            self.assertEqual(rows[0]["record_type"], "评论信息")
            self.assertEqual(rows[0]["collect_status"], "failed")
            self.assertEqual(rows[0]["collect_time"], "2026-06-19 20:31:00")
            self.assertEqual(rows[0]["article_link"], "")

    def test_article_detail_upsert_writes_and_updates_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            record = {
                "account_name": "测试公众号",
                "article_title": "测试文章",
                "published_article_time": "2026-06-19 18:30",
                "article_link": "https://mp.weixin.qq.com/s/test-short",
                "record_type": "文章详情",
                "collect_time": "2026-06-19 18:31:00",
                "duration_seconds": 12.5,
                "collect_status": "saved",
            }

            first_id = store.save_public_article(record)
            updated = {**record, "article_title": "测试文章更新", "duration_seconds": 88.8}
            second_id = store.save_public_article(updated)

            with store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, article_title, duration_seconds
                    FROM awa_public_articles
                    WHERE article_link = ?
                    """,
                    (record["article_link"],),
                ).fetchone()

            self.assertEqual(first_id, second_id)
            self.assertEqual(row[1], "测试文章更新")
            self.assertEqual(row[2], 88.8)

    def test_failed_article_allows_empty_link_and_updates_same_title_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            record = {
                "account_name": "测试公众号",
                "article_title": "超时文章",
                "published_article_time": "",
                "article_link": "",
                "record_type": "文章详情, 评论信息",
                "collect_time": "2026-06-21 10:00:00",
                "duration_seconds": 10.0,
                "collect_status": "failed",
            }

            first_id = store.save_public_article(record)
            second_id = store.save_public_article(
                {
                    **record,
                    "collect_time": "2026-06-21 10:01:00",
                    "duration_seconds": 9.5,
                }
            )

            with store._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, article_link, published_article_time, record_type, duration_seconds, collect_status
                    FROM awa_public_articles
                    """
                ).fetchall()

            self.assertEqual(first_id, second_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], "")
            self.assertEqual(rows[0][2], "")
            self.assertEqual(rows[0][3], "文章详情, 评论信息")
            self.assertEqual(rows[0][4], 9.5)
            self.assertEqual(rows[0][5], "failed")

    def test_save_public_article_rejects_placeholder_account_or_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            base = {
                "account_name": "测试公众号",
                "article_title": "正常标题",
                "published_article_time": "",
                "article_link": "",
                "record_type": "文章详情",
                "collect_time": "2026-06-21 10:00:00",
                "duration_seconds": 1.0,
                "collect_status": "failed",
            }

            with self.assertRaises(ValueError):
                store.save_public_article({**base, "account_name": "未知公众号"})
            with self.assertRaises(ValueError):
                store.save_public_article({**base, "account_name": "data-miniprogram-nickname"})
            with self.assertRaises(ValueError):
                store.save_public_article({**base, "article_title": "未识别标题"})
            self.assertEqual(store.count_public_accounts(), 0)
            self.assertEqual(store.count_public_articles(), 0)

    def test_schema_leaves_placeholder_text_validation_to_store_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)

            with store._connect() as conn:
                account_id = conn.execute(
                    "INSERT INTO awa_public_accounts (account_name) VALUES (?)",
                    ("未知公众号",),
                ).lastrowid
                conn.execute(
                    """
                    INSERT INTO awa_public_articles (
                        account_id,
                        article_title,
                        published_article_time,
                        article_link,
                        record_type,
                        collect_status
                    )
                    VALUES (?, ?, '', '', '文章详情', 'failed')
                    """,
                    (account_id, "未识别标题"),
                )

            self.assertEqual(store.count_public_accounts(), 1)
            self.assertEqual(store.count_public_articles(), 1)

    def test_saved_article_requires_non_empty_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)

            with self.assertRaises(ValueError):
                store.save_public_article(
                    {
                        "account_name": "测试公众号",
                        "article_title": "正常标题",
                        "published_article_time": "2026-06-21 10:00",
                        "article_link": "",
                        "record_type": "文章详情",
                        "collect_time": "2026-06-21 10:00:00",
                        "duration_seconds": 1.0,
                        "collect_status": "saved",
                    }
                )
            self.assertEqual(store.count_public_articles(), 0)

    def test_merge_public_account_moves_placeholder_records_to_real_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            dirty = "data-miniprogram-nickname"
            real = "新华社"

            with store._connect() as conn:
                dirty_id = conn.execute(
                    "INSERT INTO awa_public_accounts (account_name) VALUES (?)",
                    (dirty,),
                ).lastrowid
                real_id = conn.execute(
                    "INSERT INTO awa_public_accounts (account_name) VALUES (?)",
                    (real,),
                ).lastrowid
                conn.execute(
                    """
                    INSERT INTO awa_public_articles (
                        account_id,
                        article_title,
                        published_article_time,
                        article_link,
                        record_type,
                        collect_time,
                        collect_status
                    )
                    VALUES (?, '脏账号文章', '2026-06-20 10:00', 'https://mp.weixin.qq.com/s/dirty-only', '文章详情', '2026-06-21 10:00:00', 'saved')
                    """,
                    (dirty_id,),
                )
                conn.execute(
                    """
                    INSERT INTO awa_public_articles (
                        account_id,
                        article_title,
                        published_article_time,
                        article_link,
                        record_type,
                        collect_time,
                        collect_status
                    )
                    VALUES (?, '源账号重复文章', '2026-06-20 11:00', 'https://mp.weixin.qq.com/s/same-link', '文章详情', '2026-06-21 10:01:00', 'saved')
                    """,
                    (dirty_id,),
                )
                conn.execute(
                    """
                    INSERT INTO awa_public_articles (
                        account_id,
                        article_title,
                        published_article_time,
                        article_link,
                        record_type,
                        collect_time,
                        collect_status
                    )
                    VALUES (?, '目标账号已有文章', '2026-06-20 11:00', 'https://mp.weixin.qq.com/s/same-link', '文章详情', '2026-06-21 10:02:00', 'saved')
                    """,
                    (real_id,),
                )

            result = store.merge_public_account(dirty, real)

            self.assertEqual(result["moved"], 1)
            self.assertEqual(result["removed_duplicates"], 1)
            with store._connect() as conn:
                dirty_count = conn.execute(
                    "SELECT COUNT(*) FROM awa_public_accounts WHERE account_name = ?",
                    (dirty,),
                ).fetchone()[0]
                real_articles = conn.execute(
                    """
                    SELECT article_title, article_link
                    FROM awa_public_articles AS article
                    JOIN awa_public_accounts AS account ON account.id = article.account_id
                    WHERE account.account_name = ?
                    ORDER BY article_link
                    """,
                    (real,),
                ).fetchall()

            self.assertEqual(dirty_count, 0)
            self.assertEqual(len(real_articles), 2)
            self.assertEqual(real_articles[0][0], "脏账号文章")

    def test_has_saved_public_article_title_only_matches_same_account_saved_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            base_record = {
                "account_name": "account-a",
                "article_title": "  Existing   Title  ",
                "published_article_time": "2026-06-19 18:30",
                "article_link": "https://mp.weixin.qq.com/s/existing",
                "record_type": "article-detail",
                "collect_time": "2026-06-19 18:31:00",
                "collect_status": "saved",
            }
            failed_record = {
                **base_record,
                "article_title": "article-detail",
                "article_link": "https://mp.weixin.qq.com/s/failed",
                "collect_status": "failed",
            }
            other_account_record = {
                **base_record,
                "account_name": "account-b",
                "article_link": "https://mp.weixin.qq.com/s/other",
            }

            store.save_public_article(base_record)
            store.save_public_article(failed_record)
            store.save_public_article(other_account_record)

            self.assertTrue(store.has_saved_public_article_title("account-a", "Existing Title"))
            self.assertFalse(store.has_saved_public_article_title("account-a", "article-detail"))
            self.assertFalse(store.has_saved_public_article_title("account-a", "Other Account Only"))


if __name__ == "__main__":
    unittest.main()


