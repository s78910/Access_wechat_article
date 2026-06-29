from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app.fastapi_app import create_app
from src.app.fastapi_app.app import ArchiveCacheArticlesPayload, ArchiveExportPayload
from src.core.config import AppRuntimeConfig, StorageConfig
from src.modules.storage.sqlite_store import SQLiteStore


class FakeWebviewApi:
    def __init__(self) -> None:
        self.start_payload = None
        self.open_runtime_path_payload = None

    def get_status(self) -> str:
        return json.dumps({"ok": True, "status": "ready"}, ensure_ascii=False)

    def start_task(self, task_payload=None) -> str:
        self.start_payload = task_payload
        return json.dumps({"ok": True, "status": "running"}, ensure_ascii=False)

    def get_task_logs(self, limit: int = 100) -> str:
        return json.dumps({"ok": True, "items": [{"limit": limit}]}, ensure_ascii=False)

    def install_ca_certificate(self) -> str:
        return json.dumps(
            {
                "ok": True,
                "status": "installed",
                "installed": True,
                "label": "已安装",
                "storePath": "Cert:\\CurrentUser\\Root",
            },
            ensure_ascii=False,
        )

    def get_runtime_paths(self) -> str:
        return json.dumps(
            {
                "ok": True,
                "status": "ok",
                "paths": {
                    "projectDir": "D:\\project",
                    "outputDir": "D:\\project\\data\\logs\\article_capture",
                    "storageDir": "D:\\project\\storages",
                    "logDir": "D:\\project\\data\\logs",
                },
            },
            ensure_ascii=False,
        )

    def open_runtime_path(self, path_payload=None) -> str:
        self.open_runtime_path_payload = path_payload
        return json.dumps(
            {
                "ok": True,
                "status": "opened",
                "key": "storageDir",
                "path": "D:\\project\\storages",
            },
            ensure_ascii=False,
        )

    def shutdown(self) -> None:
        pass


class FakeArchiveCacheRunner:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self.started_job_ids: list[str] = []

    def create_job(self, tasks):
        job_id = f"fake-cache-job-{len(self.jobs) + 1}"
        snapshot = {
            "ok": True,
            "jobId": job_id,
            "status": "pending",
            "total": len(tasks),
            "finished": 0,
            "running": 0,
            "concurrency": 3,
            "results": [],
            "message": "",
        }
        self.jobs[job_id] = snapshot
        return snapshot

    def start_job(self, job_id: str) -> None:
        self.started_job_ids.append(job_id)

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)


def _find_route_endpoint(app, path: str, method: str):
    for route in app.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FastApiAppTest(unittest.TestCase):
    def test_fastapi_serves_webview_index_without_breaking_api_routes(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(create_app(FakeWebviewApi()))

        index_response = client.get("/index.html")
        api_response = client.get("/api/status")

        self.assertEqual(index_response.status_code, 200)
        self.assertIn("Access WeChat Article", index_response.text)
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["status"], "ready")

    def test_fastapi_serves_built_webview_assets(self) -> None:
        from fastapi.testclient import TestClient

        index_path = Path(__file__).resolve().parents[1] / "src" / "webview" / "index.html"
        html = index_path.read_text(encoding="utf-8")
        script_marker = 'src="./'
        script_start = html.find(script_marker)
        self.assertNotEqual(script_start, -1, "index.html 应包含 Vite 构建后的脚本资源")
        asset_start = script_start + len(script_marker) - 2
        asset_end = html.find('"', asset_start)
        asset_path = html[asset_start:asset_end]

        client = TestClient(create_app(FakeWebviewApi()))
        response = client.get(asset_path)

        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers.get("content-type", ""))

    def test_get_status_route_calls_existing_webview_api(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(create_app(FakeWebviewApi()))
        response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_start_task_route_passes_json_payload_to_existing_webview_api(self) -> None:
        from fastapi.testclient import TestClient

        api = FakeWebviewApi()
        client = TestClient(create_app(api))
        response = client.post("/api/task/start", json={"recordLimit": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(json.loads(api.start_payload)["recordLimit"], 1)

    def test_get_task_logs_route_reads_limit_query(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(create_app(FakeWebviewApi()))
        response = client.get("/api/task/logs?limit=12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["limit"], 12)

    def test_install_ca_certificate_route_calls_existing_webview_api(self) -> None:
        app = create_app(FakeWebviewApi())
        route_paths = {
            (next(iter(getattr(route, "methods", [])), ""), getattr(route, "path", ""))
            for route in app.routes
        }

        self.assertIn(("POST", "/api/ca/install"), route_paths)
        self.assertNotIn(("POST", "/api/ca/install/open"), route_paths)

    def test_runtime_paths_route_reads_existing_webview_api(self) -> None:
        app = create_app(FakeWebviewApi())
        endpoint = _find_route_endpoint(app, "/api/runtime/paths", "GET")

        response = endpoint()
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["paths"]["projectDir"], "D:\\project")
        self.assertEqual(payload["paths"]["storageDir"], "D:\\project\\storages")

    def test_open_runtime_path_route_passes_directory_key_to_existing_webview_api(self) -> None:
        api = FakeWebviewApi()
        app = create_app(api)
        endpoint = _find_route_endpoint(app, "/api/runtime/paths/open", "POST")

        response = endpoint({"key": "storageDir"})
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "opened")
        self.assertEqual(json.loads(api.open_runtime_path_payload)["key"], "storageDir")

    def test_history_records_route_reads_public_articles_with_filters(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "真实文章A",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/history-a",
                    "record_type": "文章详情, 评论信息",
                    "collect_time": "2026-06-21 11:00:00",
                    "duration_seconds": 3.456,
                    "collect_status": "saved",
                }
            )
            archive_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 18-30 真实文章A"
            archive_dir.mkdir(parents=True)
            (archive_dir / "article_detail.json").write_text(
                json.dumps(
                    {
                        "short_link": "https://mp.weixin.qq.com/s/history-a",
                        "read_count": 100001,
                        "like_count": 6006,
                        "share_count": 33513,
                        "recommend_count": 2450,
                        "comment_count": 11,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "失败文章",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 11:05:00",
                    "duration_seconds": 10.0,
                    "collect_status": "failed",
                }
            )
            store.save_public_article(
                {
                    "account_name": "其他公众号",
                    "article_title": "不应命中",
                    "published_article_time": "2026-06-20 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/history-b",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 11:00:00",
                    "duration_seconds": 2.0,
                    "collect_status": "saved",
                }
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get(
                "/api/history/records",
                params={
                    "page": 1,
                    "pageSize": 15,
                    "keyword": "测试公众号",
                    "collectType": "评论信息",
                    "status": "saved",
                    "collectDate": "2026-06-21",
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "真实文章A")
        self.assertEqual(payload["items"][0]["account"], "测试公众号")
        self.assertEqual(payload["items"][0]["collectType"], "文章详情, 评论信息")
        self.assertEqual(payload["items"][0]["collectTime"], "2026-06-21 11:00:00")
        self.assertEqual(payload["items"][0]["recordTime"], "2026-06-19 18:30")
        self.assertEqual(payload["items"][0]["duration"], "00:03.45")
        self.assertEqual(payload["items"][0]["status"], "成功")
        self.assertEqual(payload["items"][0]["articleLink"], "https://mp.weixin.qq.com/s/history-a")
        self.assertEqual(payload["items"][0]["recordSummary"]["kind"], "metrics")
        self.assertEqual(
            payload["items"][0]["recordSummary"]["items"],
            [
                {"key": "read_count", "label": "阅读数", "value": "100001"},
                {"key": "like_count", "label": "点赞数", "value": "6006"},
                {"key": "share_count", "label": "转发数", "value": "33513"},
                {"key": "recommend_count", "label": "推荐数", "value": "2450"},
                {"key": "comment_count", "label": "留言数", "value": "11"},
            ],
        )

    def test_history_records_route_returns_failed_status_summary(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "失败文章",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 11:05:00",
                    "duration_seconds": 10.0,
                    "collect_status": "failed",
                }
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get("/api/history/records", params={"status": "failed"})

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["status"], "失败")
        self.assertEqual(payload["items"][0]["recordSummary"]["kind"], "status")
        self.assertEqual(payload["items"][0]["recordSummary"]["items"], [])
        self.assertIn("failed", payload["items"][0]["recordSummary"]["message"])

    def test_history_summary_route_reads_public_article_statistics(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            for index, status in enumerate(("saved", "saved", "failed"), start=1):
                record = {
                    "account_name": "统计公众号",
                    "article_title": f"统计文章{index}",
                    "record_type": "文章详情",
                    "collect_time": f"2026-06-2{index} 10:00:00",
                    "duration_seconds": float(index),
                    "collect_status": status,
                }
                if status == "saved":
                    record["published_article_time"] = f"2026-06-2{index} 09:00"
                    record["article_link"] = f"https://mp.weixin.qq.com/s/summary-{index}"
                store.save_public_article(record)

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get("/api/history/summary")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["totalRecords"], 3)
        self.assertEqual(payload["savedRecords"], 2)
        self.assertEqual(payload["failedRecords"], 1)
        self.assertEqual(payload["successRate"], 66.7)
        self.assertEqual(payload["averageDuration"], "00:02.00")
        self.assertEqual(payload["latestCollectDate"], "2026-06-23")
        self.assertEqual([item["label"] for item in payload["trend"]], ["06-21", "06-22", "06-23"])

    def test_history_suggestions_route_reads_distinct_titles_and_accounts(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "人民日报",
                    "article_title": "人民坚持稳中求进",
                    "published_article_time": "2026-06-20 08:00",
                    "article_link": "https://mp.weixin.qq.com/s/history-suggestion-a",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 09:00:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "人民日报",
                    "article_title": "人民坚持稳中求进",
                    "record_type": "评论信息",
                    "collect_time": "2026-06-21 10:00:00",
                    "collect_status": "failed",
                }
            )
            store.save_public_article(
                {
                    "account_name": "新华社",
                    "article_title": "夏至观察",
                    "published_article_time": "2026-06-20 08:30",
                    "article_link": "https://mp.weixin.qq.com/s/history-suggestion-b",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 11:00:00",
                    "collect_status": "saved",
                }
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get("/api/history/suggestions", params={"keyword": "人", "limit": 5})

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["items"], ["人民日报", "人民坚持稳中求进"])

    def test_archive_accounts_route_reads_public_accounts_from_sqlite(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "测试文章",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/test-short",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get("/api/archive/accounts")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["accountName"], "测试公众号")
        self.assertEqual(payload["items"][0]["articleCount"], 1)
        self.assertEqual(payload["items"][0]["savedCount"], 1)
        self.assertEqual(payload["items"][0]["failedCount"], 0)
        self.assertEqual(payload["items"][0]["latestCollectTime"], "2026-06-19 18:31:00")
        self.assertEqual(payload["dbPath"], str(db_path))

    def test_archive_summary_route_reads_counts_and_storage_size(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "公众号A",
                    "article_title": "文章A",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/account-a",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "公众号B",
                    "article_title": "文章B",
                    "published_article_time": "2026-06-19 18:40",
                    "article_link": "https://mp.weixin.qq.com/s/account-b",
                    "record_type": "评论信息",
                    "collect_time": "2026-06-19 18:41:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "公众号B",
                    "article_title": "文章C",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:42:00",
                    "collect_status": "failed",
                }
            )
            archive_dir = Path(temp_dir) / "storages" / "公众号A" / "2026-06-19 18-30 文章A"
            archive_dir.mkdir(parents=True)
            (archive_dir / "article_detail.json").write_bytes(b"12345")
            (archive_dir / "original_main.html").write_bytes(b"abcdef")

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get("/api/archive/summary")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountCount"], 2)
        self.assertEqual(payload["articleCount"], 3)
        self.assertEqual(payload["detailCount"], 1)
        self.assertEqual(payload["dataType"], "JSON")
        self.assertEqual(payload["storageSizeBytes"], 11)
        self.assertEqual(payload["storageSizeLabel"], "11 B")
        self.assertEqual(payload["dbPath"], str(db_path))

    def test_archive_account_articles_route_reads_articles_for_selected_account(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            for index in range(11):
                article_number = index + 1
                store.save_public_article(
                    {
                        "account_name": "测试公众号",
                        "article_title": f"文章{article_number:02d}",
                        "published_article_time": f"2026-06-19 {article_number:02d}:30",
                        "article_link": f"https://mp.weixin.qq.com/s/test-{article_number:02d}",
                        "record_type": "评论信息" if article_number == 1 else "文章详情",
                        "collect_time": f"2026-06-19 {article_number:02d}:31:00",
                        "collect_status": "failed" if article_number == 1 else "saved",
                    }
                )
            store.save_public_article(
                {
                    "account_name": "其他公众号",
                    "article_title": "不应返回",
                    "published_article_time": "2026-06-19 19:30",
                    "article_link": "https://mp.weixin.qq.com/s/other",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 19:31:00",
                    "collect_status": "saved",
                }
            )
            account_id = int(
                next(
                    row["id"]
                    for row in store.list_public_accounts()
                    if row["account_name"] == "测试公众号"
                )
            )
            archive_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 01-30 文章01"
            duplicate_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 01-30 文章01_1"
            archive_dir.mkdir(parents=True)
            duplicate_dir.mkdir(parents=True)
            archive_detail = json.dumps({"short_link": "https://mp.weixin.qq.com/s/test-01"}, ensure_ascii=False)
            duplicate_detail = json.dumps({"short_link": "https://mp.weixin.qq.com/s/test-01"}, ensure_ascii=False)
            archive_html = b"<html>new</html>"
            duplicate_html = b"<html>duplicate</html>"
            (archive_dir / "article_detail.json").write_text(archive_detail, encoding="utf-8")
            (archive_dir / "original_main.html").write_bytes(archive_html)
            (duplicate_dir / "article_detail.json").write_text(duplicate_detail, encoding="utf-8")
            (duplicate_dir / "original_main.html").write_bytes(duplicate_html)
            expected_size = (
                len(archive_detail.encode("utf-8"))
                + len(archive_html)
                + len(duplicate_detail.encode("utf-8"))
                + len(duplicate_html)
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get(f"/api/archive/accounts/{account_id}/articles?page=2&pageSize=10")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountId"], account_id)
        self.assertEqual(payload["total"], 11)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["pageSize"], 10)
        self.assertEqual([item["title"] for item in payload["items"]], ["文章01"])
        self.assertEqual(payload["items"][0]["recordType"], "评论信息")
        self.assertEqual(payload["items"][0]["collectStatus"], "failed")
        self.assertEqual(payload["items"][0]["articleLink"], "")
        self.assertEqual(payload["items"][0]["sizeBytes"], 0)
        self.assertEqual(payload["items"][0]["archiveDir"], "")
        self.assertEqual(payload["items"][0]["archiveDirs"], [])
        self.assertEqual(payload["items"][0]["sizeLabel"], "0 B")

    def test_archive_account_articles_route_orders_by_published_article_time(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            for title, published_time, collect_time in [
                ("较早发布但较晚采集", "2026-06-19 08:00", "2026-06-21 12:00:00"),
                ("较晚发布但较早采集", "2026-06-20 08:00", "2026-06-20 12:00:00"),
            ]:
                store.save_public_article(
                    {
                        "account_name": "测试公众号",
                        "article_title": title,
                        "published_article_time": published_time,
                        "article_link": f"https://mp.weixin.qq.com/s/{title}",
                        "record_type": "文章详情",
                        "collect_time": collect_time,
                        "collect_status": "saved",
                    }
                )
            account_id = int(store.list_public_accounts()[0]["id"])

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.get(f"/api/archive/accounts/{account_id}/articles?page=1&pageSize=10")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["title"], item["publishedArticleTime"]) for item in payload["items"]],
            [
                ("较晚发布但较早采集", "2026-06-20 08:00"),
                ("较早发布但较晚采集", "2026-06-19 08:00"),
            ],
        )

    def test_delete_archive_articles_route_removes_rows_and_archive_dirs(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            article_id = store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "测试文章",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/delete-me",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            archive_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 18-30 测试文章"
            duplicate_dir = Path(temp_dir) / "storages" / "测试公众号" / "2026-06-19 18-30 测试文章_1"
            for directory in (archive_dir, duplicate_dir):
                directory.mkdir(parents=True)
                (directory / "article_detail.json").write_text(
                    json.dumps({"short_link": "https://mp.weixin.qq.com/s/delete-me"}, ensure_ascii=False),
                    encoding="utf-8",
                )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.request("DELETE", "/api/archive/articles", json={"articleIds": [article_id]})
            remaining_article_count = SQLiteStore(db_path).count_public_articles()
            archive_dir_exists = archive_dir.exists()
            duplicate_dir_exists = duplicate_dir.exists()

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deletedArticleCount"], 1)
        self.assertEqual(payload["deletedArchiveDirCount"], 2)
        self.assertFalse(archive_dir_exists)
        self.assertFalse(duplicate_dir_exists)
        self.assertEqual(remaining_article_count, 0)

    def test_delete_archive_account_route_removes_account_articles_and_account(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "待删公众号",
                    "article_title": "文章1",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/delete-account-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:31:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "保留公众号",
                    "article_title": "文章2",
                    "published_article_time": "2026-06-19 18:40",
                    "article_link": "https://mp.weixin.qq.com/s/keep-account-1",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-19 18:41:00",
                    "collect_status": "saved",
                }
            )
            account_id = int(next(row["id"] for row in store.list_public_accounts() if row["account_name"] == "待删公众号"))
            archive_dir = Path(temp_dir) / "storages" / "待删公众号" / "2026-06-19 18-30 文章1"
            archive_dir.mkdir(parents=True)
            (archive_dir / "article_detail.json").write_text(
                json.dumps({"short_link": "https://mp.weixin.qq.com/s/delete-account-1"}, ensure_ascii=False),
                encoding="utf-8",
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.request("DELETE", f"/api/archive/accounts/{account_id}")
            remaining_accounts = SQLiteStore(db_path).list_public_accounts()
            archive_dir_exists = archive_dir.exists()

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deletedArticleCount"], 1)
        self.assertEqual(payload["deletedAccountCount"], 1)
        self.assertFalse(archive_dir_exists)
        self.assertEqual(len(remaining_accounts), 1)
        self.assertEqual(remaining_accounts[0]["account_name"], "保留公众号")

    def test_delete_archive_all_route_removes_everything(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            for account_name, title, link in (
                ("账号A", "文章A", "https://mp.weixin.qq.com/s/all-a"),
                ("账号B", "文章B", "https://mp.weixin.qq.com/s/all-b"),
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
                archive_dir = Path(temp_dir) / "storages" / account_name / f"2026-06-19 18-30 {title}"
                archive_dir.mkdir(parents=True)
                (archive_dir / "article_detail.json").write_text(
                    json.dumps({"short_link": link}, ensure_ascii=False),
                    encoding="utf-8",
                )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            client = TestClient(create_app(FakeWebviewApi(), runtime_config=runtime_config))
            response = client.request("DELETE", "/api/archive")
            remaining_account_count = SQLiteStore(db_path).count_public_accounts()
            remaining_article_count = SQLiteStore(db_path).count_public_articles()

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deletedArticleCount"], 2)
        self.assertEqual(payload["deletedAccountCount"], 2)
        self.assertEqual(remaining_account_count, 0)
        self.assertEqual(remaining_article_count, 0)

    def test_archive_cache_routes_create_and_read_background_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            article_id = store.save_public_article(
                {
                    "account_name": "缓存公众号",
                    "article_title": "缓存文章",
                    "published_article_time": "2026-06-20 10:30",
                    "article_link": "https://mp.weixin.qq.com/s/cache-one",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 10:31:00",
                    "collect_status": "saved",
                }
            )

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            fake_runner = FakeArchiveCacheRunner()
            app = create_app(FakeWebviewApi(), runtime_config=runtime_config, archive_cache_runner=fake_runner)
            create_endpoint = _find_route_endpoint(app, "/api/archive/cache/articles", "POST")
            read_endpoint = _find_route_endpoint(app, "/api/archive/cache/jobs/{job_id}", "GET")

            response = create_endpoint(ArchiveCacheArticlesPayload(articleIds=[article_id]))
            payload = json.loads(response.body)
            job_response = read_endpoint(payload["jobId"])
            job_payload = json.loads(job_response.body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["concurrency"], 3)
        self.assertTrue(payload["jobId"])
        self.assertEqual(fake_runner.started_job_ids, [payload["jobId"]])
        self.assertEqual(job_response.status_code, 200)
        self.assertEqual(job_payload["jobId"], payload["jobId"])

    def test_archive_account_cache_route_queues_all_account_articles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            for index in range(2):
                store.save_public_article(
                    {
                        "account_name": "批量公众号",
                        "article_title": f"批量文章{index + 1}",
                        "published_article_time": f"2026-06-20 1{index}:30",
                        "article_link": f"https://mp.weixin.qq.com/s/cache-account-{index + 1}",
                        "record_type": "文章详情",
                        "collect_time": f"2026-06-20 1{index}:31:00",
                        "collect_status": "saved",
                    }
                )
            account_id = int(store.list_public_accounts()[0]["id"])

            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            fake_runner = FakeArchiveCacheRunner()
            app = create_app(FakeWebviewApi(), runtime_config=runtime_config, archive_cache_runner=fake_runner)
            endpoint = _find_route_endpoint(app, "/api/archive/accounts/{account_id}/cache", "POST")
            response = endpoint(account_id)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["concurrency"], 3)
        self.assertEqual(fake_runner.started_job_ids, [payload["jobId"]])

    def test_archive_export_route_writes_one_excel_file_per_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "awa_public.sqlite3"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "导出公众号",
                    "article_title": "导出文章",
                    "published_article_time": "2026-06-20 10:30",
                    "article_link": "https://mp.weixin.qq.com/s/export-one",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-20 10:31:00",
                    "collect_status": "saved",
                }
            )
            account_id = int(store.list_public_accounts()[0]["id"])
            runtime_config = AppRuntimeConfig(storage=StorageConfig(db_path=db_path))
            app = create_app(FakeWebviewApi(), runtime_config=runtime_config)
            endpoint = _find_route_endpoint(app, "/api/archive/export/accounts", "POST")

            response = endpoint(ArchiveExportPayload(accountIds=[account_id], targetDir=str(root / "exports")))
            payload = json.loads(response.body)
            exported_path_exists = Path(payload["files"][0]["outputPath"]).exists()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["exportedFileCount"], 1)
        self.assertEqual(payload["totalRowCount"], 1)
        self.assertTrue(exported_path_exists)

    def test_main_pywebview_uses_fastapi_index_url_without_static_server(self) -> None:
        import main

        events: list[tuple[str, str]] = []

        class FakeApi:
            def __init__(self, runtime_config=None, auto_start: bool = False) -> None:
                self.runtime_config = runtime_config
                self.auto_start = auto_start
                self.shutdown_called = False

            def set_window(self, window) -> None:
                events.append(("set_window", str(window)))

            def shutdown(self) -> None:
                self.shutdown_called = True
                events.append(("api.shutdown", ""))

        class FakeServer:
            def __init__(self, api=None) -> None:
                self.api = api
                self.webview_url = "http://127.0.0.1:8766/index.html"

            def start(self) -> None:
                events.append(("server.start", ""))

            def stop(self) -> None:
                events.append(("server.stop", ""))

        class FakeWebview:
            @staticmethod
            def create_window(title, url, js_api=None, width=0, height=0, min_size=None):
                events.append(("create_window", url))
                return "fake-window"

            @staticmethod
            def start(icon=None):
                events.append(("webview.start", str(icon)))

        class FakeRuntimeConfig:
            class app:
                auto_start_proxy = False

        with patch.dict("sys.modules", {"webview": FakeWebview}):
            with patch.object(main, "load_runtime_config", return_value=FakeRuntimeConfig()):
                with patch.object(main, "WebviewApi", FakeApi):
                    with patch.object(main, "FastApiServer", FakeServer):
                        with patch.object(main, "bind_aspect_ratio") as bind_aspect_ratio:
                            bind_aspect_ratio.side_effect = (
                                lambda window, ratio, min_size: events.append(
                                    ("bind_aspect_ratio", f"{window}:{ratio}:{min_size}")
                                )
                            )
                            self.assertFalse(hasattr(main, "WebviewStaticServer"))
                            main.main()

        self.assertIn(("create_window", "http://127.0.0.1:8766/index.html"), events)
        self.assertIn(("bind_aspect_ratio", "fake-window:1.7777777777777777:(960, 540)"), events)
        self.assertIn(("webview.start", str(main.WINDOW_ICON_PATH)), events)
        self.assertEqual(main.WINDOW_ICON_PATH.name, "favicon.ico")
        self.assertTrue(main.WINDOW_ICON_PATH.exists())
        self.assertEqual([event[0] for event in events], [
            "server.start",
            "create_window",
            "bind_aspect_ratio",
            "set_window",
            "webview.start",
            "server.stop",
            "api.shutdown",
        ])


if __name__ == "__main__":
    unittest.main()
