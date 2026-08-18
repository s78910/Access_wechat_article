from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.services.history.history_clear_service import HistoryClearService


def create_history_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE awa_fetch_history (
                id INTEGER PRIMARY KEY,
                target_title TEXT NOT NULL
            );
            CREATE TABLE awa_public_accounts (
                id INTEGER PRIMARY KEY,
                account_name TEXT NOT NULL
            );
            CREATE TABLE awa_public_articles (
                id INTEGER PRIMARY KEY,
                article_title TEXT NOT NULL
            );
            INSERT INTO awa_fetch_history(id, target_title)
            VALUES (1, '文章一'), (2, '文章二');
            INSERT INTO awa_public_accounts(id, account_name)
            VALUES (1, '测试公众号');
            INSERT INTO awa_public_articles(id, article_title)
            VALUES (1, '已归档文章');
            """
        )


class HistoryClearServiceTest(unittest.TestCase):
    def test_clear_all_only_deletes_fetch_history_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "history.sqlite3"
            create_history_database(database_path)

            result = HistoryClearService(database_path).clear_all()

            self.assertEqual(result["status"], "deleted")
            self.assertEqual(result["deletedCount"], 2)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM awa_fetch_history").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM awa_public_accounts").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM awa_public_articles").fetchone()[0],
                    1,
                )


if __name__ == "__main__":
    unittest.main()
