from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dev_server import create_backend_app


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
            VALUES (1, '文章一');
            INSERT INTO awa_public_accounts(id, account_name)
            VALUES (1, '测试公众号');
            INSERT INTO awa_public_articles(id, article_title)
            VALUES (1, '已归档文章');
            """
        )


class HistoryClearApiTest(unittest.TestCase):
    def test_delete_history_endpoint_returns_deleted_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "history.sqlite3"
            create_history_database(database_path)
            backend = SimpleNamespace(
                db_path=database_path,
                runtime=SimpleNamespace(config=SimpleNamespace(software=SimpleNamespace(version="test"))),
                append_log=lambda *args, **kwargs: None,
            )
            client = TestClient(create_backend_app(backend))
            response = client.delete("/api/history/records")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "deleted")
            self.assertEqual(response.json()["deletedCount"], 1)


if __name__ == "__main__":
    unittest.main()
