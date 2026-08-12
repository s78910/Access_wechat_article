from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.services.runtime.startup_self_check_service import StartupSelfCheckService


def _config(root: Path) -> SimpleNamespace:
    db_dir = root / "data" / "sql"
    db_path = db_dir / "awa-v2.1.sqlite3"
    storage = SimpleNamespace(
        article_storage_root=root / "storages",
        db_dir=db_dir,
        db_file_name=db_path.name,
        database_path=db_path,
        temp_dir=root / "data" / "tmp",
        log_dir=root / "data" / "logs",
    )
    return SimpleNamespace(
        software=SimpleNamespace(version="2.1.0", data_schema_version="v2.1"),
        storage=storage,
        proxy=SimpleNamespace(
            confdir=root / ".mitmproxy",
            ca_cert_path=root / ".mitmproxy" / "mitmproxy-ca-cert.cer",
        ),
    )


def _create_valid_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE awa_fetch_history(id INTEGER PRIMARY KEY);
            CREATE TABLE awa_public_accounts(id INTEGER PRIMARY KEY);
            CREATE TABLE awa_public_articles(id INTEGER PRIMARY KEY);
            """
        )
        connection.commit()
    finally:
        connection.close()


def _create_config_files(root: Path) -> None:
    (root / "src" / "config").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "src" / "config" / "system.yaml").write_text("software:\n  version: 2.1.0\n", encoding="utf-8")
    (root / "data" / "custom.yaml").write_text("software:\n  version: 2.1.0\n", encoding="utf-8")


class StartupSelfCheckServiceTest(unittest.TestCase):
    def test_missing_or_stale_state_requires_self_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = StartupSelfCheckService(project_root=root)
            config = _config(root)

            self.assertTrue(service.get_status(config)["needsSelfCheck"])

            state_path = root / "data" / "runtime" / "startup_self_check.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "file_schema_version": 1,
                        "checked_version": "2.1.0",
                        "checked_data_schema_version": "v2.1",
                        "checked_at": "2026-08-12 10:00:00",
                        "status": "passed",
                        "fatal_count": 0,
                        "warning_count": 0,
                        "duration_seconds": 0.1,
                        "items": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertFalse(service.get_status(config)["needsSelfCheck"])

            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["checked_version"] = "2.0.1"
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(service.get_status(config)["needsSelfCheck"])

            state["checked_version"] = "2.1.0"
            state["status"] = "failed"
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(service.get_status(config)["needsSelfCheck"])

    def test_run_writes_state_and_actionable_playwright_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config.proxy.confdir.mkdir(parents=True, exist_ok=True)
            config.proxy.ca_cert_path.write_text("dummy cert", encoding="utf-8")
            _create_config_files(root)
            _create_valid_database(config.storage.database_path)

            service = StartupSelfCheckService(
                project_root=root,
                dependency_checker=lambda _name: True,
                ca_status_checker=lambda _config: {
                    "ok": True,
                    "projectCertificateInstalled": False,
                    "caFileExists": True,
                },
                playwright_chromium_checker=lambda _root: False,
            )

            result = service.run(config)

            self.assertEqual(result["status"], "passed_with_warnings")
            self.assertEqual(result["fatalCount"], 0)
            self.assertGreaterEqual(result["warningCount"], 1)
            self.assertTrue(any(item["key"] == "playwright_chromium" for item in result["items"]))
            playwright_item = next(item for item in result["items"] if item["key"] == "playwright_chromium")
            self.assertIn(".playwright-browsers", playwright_item["action"])
            self.assertIn("uv run playwright install chromium", playwright_item["action"])

            state_path = root / "data" / "runtime" / "startup_self_check.json"
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["checked_version"], "2.1.0")
            self.assertEqual(saved["checked_data_schema_version"], "v2.1")
            self.assertEqual(saved["status"], "passed_with_warnings")


if __name__ == "__main__":
    unittest.main()
