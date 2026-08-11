from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dev_server import _register_archive_cache_routes


class _FakeJob:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def to_payload(self):
        return {
            "ok": True,
            "jobId": self.job_id,
            "status": "pending",
            "total": 2,
            "finished": 0,
            "running": 0,
            "skipped": 0,
            "concurrency": 2,
            "results": [],
            "message": "",
        }


class _FakeCacheService:
    def __init__(self) -> None:
        self.article_ids: list[int] = []
        self.account_id = 0

    def create_articles_job(self, article_ids):
        self.article_ids = list(article_ids)
        return _FakeJob("selected-job")

    def create_account_job(self, account_id: int):
        self.account_id = account_id
        return _FakeJob("account-job")

    def get_job(self, job_id: str):
        if job_id == "missing":
            raise KeyError(job_id)
        return _FakeJob(job_id)


class OfflineCacheApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _FakeCacheService()
        app = FastAPI()
        _register_archive_cache_routes(
            app,
            SimpleNamespace(offline_cache_service=self.service),
        )
        self.client = TestClient(app)

    def test_selected_articles_endpoint_creates_refresh_job(self) -> None:
        response = self.client.post("/api/archive/cache/articles", json={"articleIds": [3, 8]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["jobId"], "selected-job")
        self.assertEqual(self.service.article_ids, [3, 8])

    def test_account_endpoint_creates_missing_only_job(self) -> None:
        response = self.client.post("/api/archive/accounts/5/cache")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["jobId"], "account-job")
        self.assertEqual(self.service.account_id, 5)

    def test_missing_job_returns_404_payload(self) -> None:
        response = self.client.get("/api/archive/cache/jobs/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["status"], "missing")


if __name__ == "__main__":
    unittest.main()
