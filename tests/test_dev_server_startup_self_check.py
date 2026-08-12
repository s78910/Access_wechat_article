from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from dev_server import _startup_self_check_run_payload, _startup_self_check_status_payload
from tests.test_startup_self_check_service import _config, _create_config_files, _create_valid_database


class DevServerStartupSelfCheckTest(unittest.TestCase):
    def test_status_payload_uses_runtime_config_version_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            backend = SimpleNamespace(
                project_root=root,
                runtime=SimpleNamespace(config=config),
                startup_self_check_lock=Lock(),
            )

            payload = _startup_self_check_status_payload(backend)

            self.assertTrue(payload["ok"])
            self.assertTrue(payload["needsSelfCheck"])
            self.assertEqual(payload["currentVersion"], "2.1.0")
            self.assertEqual(payload["currentDataSchemaVersion"], "v2.1")
            self.assertEqual(payload["statePath"], "data\\runtime\\startup_self_check.json")

    def test_run_payload_returns_items_and_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _config(root)
            config.proxy.confdir.mkdir(parents=True, exist_ok=True)
            config.proxy.ca_cert_path.write_text("dummy cert", encoding="utf-8")
            _create_config_files(root)
            _create_valid_database(config.storage.database_path)
            backend = SimpleNamespace(
                project_root=root,
                runtime=SimpleNamespace(config=config),
                startup_self_check_lock=Lock(),
            )

            payload = _startup_self_check_run_payload(backend)

            self.assertIn(payload["status"], {"passed", "passed_with_warnings", "failed"})
            self.assertIn("items", payload)
            self.assertTrue((root / "data" / "runtime" / "startup_self_check.json").is_file())


if __name__ == "__main__":
    unittest.main()
