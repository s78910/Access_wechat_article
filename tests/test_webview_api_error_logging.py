from __future__ import annotations

import json
import tempfile
import unittest

from src.app.pywebview_app.webview_api import WebviewApi
from pathlib import Path

from src.core.config import AppFeatureConfig, AppRuntimeConfig, LOG_DIR, PROJECT_ROOT, ProxyConfig, StorageConfig


class FailingTaskManager:
    def __init__(self) -> None:
        self.logged_errors: list[tuple[str, str]] = []

    def start_task(self, _payload):
        raise RuntimeError("模拟启动失败")

    def log_runtime_error(self, message: str, source: str = "runtime") -> None:
        self.logged_errors.append((source, message))


class StartupProxyTaskManager:
    def __init__(self, *, start_ok: bool = True, enable_ok: bool = True) -> None:
        self.start_ok = start_ok
        self.enable_ok = enable_ok
        self.calls: list[str] = []
        self.logged_errors: list[tuple[str, str]] = []

    def start_mitm_proxy(self) -> dict:
        self.calls.append("start_mitm_proxy")
        return {
            "ok": self.start_ok,
            "status": "idle",
            "message": "MITM 启动成功" if self.start_ok else "MITM 启动失败",
        }

    def enable_system_proxy(self) -> dict:
        self.calls.append("enable_system_proxy")
        return {
            "ok": self.enable_ok,
            "status": "idle",
            "message": "系统代理开启成功" if self.enable_ok else "系统代理开启失败",
        }

    def stop_mitm_proxy(self) -> dict:
        self.calls.append("stop_mitm_proxy")
        return {"ok": True, "status": "stopped"}

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def log_runtime_error(self, message: str, source: str = "runtime") -> None:
        self.logged_errors.append((source, message))


class WebviewApiErrorLoggingTest(unittest.TestCase):
    def test_start_task_exception_is_returned_and_logged(self) -> None:
        manager = FailingTaskManager()
        api = WebviewApi(task_manager=manager)

        payload = json.loads(api.start_task({"recordLimit": 1}))

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "error")
        self.assertIn("模拟启动失败", payload["message"])
        self.assertEqual(manager.logged_errors[0][0], "webview")
        self.assertIn("start_task 调用失败：模拟启动失败", manager.logged_errors[0][1])

    def test_auto_start_proxy_enables_system_proxy_when_configured(self) -> None:
        manager = StartupProxyTaskManager()
        runtime_config = AppRuntimeConfig(
            app=AppFeatureConfig(auto_start_proxy=True),
            proxy=ProxyConfig(enable_system_proxy=True),
        )

        WebviewApi(task_manager=manager, runtime_config=runtime_config, auto_start=True)

        self.assertEqual(manager.calls, ["start_mitm_proxy", "enable_system_proxy"])

    def test_auto_start_proxy_rolls_back_mitm_when_system_proxy_enable_fails(self) -> None:
        manager = StartupProxyTaskManager(enable_ok=False)
        runtime_config = AppRuntimeConfig(
            app=AppFeatureConfig(auto_start_proxy=True),
            proxy=ProxyConfig(enable_system_proxy=True),
        )

        WebviewApi(task_manager=manager, runtime_config=runtime_config, auto_start=True)

        self.assertEqual(
            manager.calls,
            ["start_mitm_proxy", "enable_system_proxy", "stop_mitm_proxy"],
        )
        self.assertEqual(manager.logged_errors[0][0], "webview")
        self.assertIn("系统代理开启失败", manager.logged_errors[0][1])

    def test_auto_clean_temp_files_cleans_cache_dir_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "tmp"
            stale_file = cache_dir / "old.txt"
            cache_dir.mkdir()
            stale_file.write_text("stale", encoding="utf-8")
            manager = StartupProxyTaskManager()
            runtime_config = AppRuntimeConfig(
                app=AppFeatureConfig(auto_clean_temp_files=True, auto_start_proxy=False),
            )

            WebviewApi(
                task_manager=manager,
                runtime_config=runtime_config,
                auto_start=True,
                auto_cleanup=True,
                cache_dir=cache_dir,
            )

            self.assertFalse(stale_file.exists())
            self.assertFalse(manager.logged_errors)

    def test_auto_clean_temp_files_does_not_clean_cache_dir_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "tmp"
            stale_file = cache_dir / "old.txt"
            cache_dir.mkdir()
            stale_file.write_text("stale", encoding="utf-8")
            manager = StartupProxyTaskManager()
            runtime_config = AppRuntimeConfig(
                app=AppFeatureConfig(auto_clean_temp_files=False, auto_start_proxy=False),
            )

            WebviewApi(
                task_manager=manager,
                runtime_config=runtime_config,
                auto_start=True,
                auto_cleanup=True,
                cache_dir=cache_dir,
            )

            self.assertTrue(stale_file.exists())

    def test_mitm_certificate_list_and_delete_api(self) -> None:
        listed_payload = {
            "ok": True,
            "status": "found",
            "count": 1,
            "certificates": [
                {
                    "storePath": "Cert:\\CurrentUser\\Root",
                    "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                    "subject": "O=mitmproxy, CN=mitmproxy",
                }
            ],
            "message": "已检索到 1 张 mitmproxy 相关证书。",
        }
        deleted_calls: list[list[str]] = []

        def delete_certificates(thumbprints: list[str]) -> dict:
            deleted_calls.append(thumbprints)
            return {
                "ok": True,
                "status": "deleted",
                "deletedCount": len(thumbprints),
                "skippedCount": 0,
                "deleted": [],
                "skipped": [],
                "message": f"已删除 {len(thumbprints)} 张 MITM 证书。",
            }

        api = WebviewApi(
            task_manager=FailingTaskManager(),
            ca_certificate_lister=lambda: listed_payload,
            ca_certificate_deleter=delete_certificates,
        )

        list_payload = json.loads(api.list_mitm_ca_certificates())
        delete_payload = json.loads(
            api.delete_mitm_ca_certificates(
                json.dumps({"thumbprints": ["ABCDEF1234567890ABCDEF1234567890ABCDEF12"]})
            )
        )

        self.assertEqual(list_payload["count"], 1)
        self.assertTrue(delete_payload["ok"])
        self.assertEqual(deleted_calls, [["ABCDEF1234567890ABCDEF1234567890ABCDEF12"]])

    def test_install_ca_certificate_api_uses_injected_installer(self) -> None:
        install_calls: list[str] = []

        def install_certificate() -> dict:
            install_calls.append("install")
            return {
                "ok": True,
                "status": "installed",
                "installed": True,
                "label": "已安装",
                "message": "当前项目 mitmproxy CA 已安装到当前用户根证书库。",
                "storePath": "Cert:\\CurrentUser\\Root",
                "thumbprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
            }

        api = WebviewApi(
            task_manager=FailingTaskManager(),
            ca_certificate_installer=install_certificate,
        )

        payload = json.loads(api.install_ca_certificate())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "installed")
        self.assertEqual(payload["storePath"], "Cert:\\CurrentUser\\Root")
        self.assertEqual(install_calls, ["install"])

    def test_runtime_paths_api_reads_actual_program_directories(self) -> None:
        runtime_config = AppRuntimeConfig(
            storage=StorageConfig(db_path=Path("D:/tmp/runtime/awa_public.sqlite3"))
        )
        api = WebviewApi(
            task_manager=FailingTaskManager(),
            runtime_config=runtime_config,
        )

        payload = json.loads(api.get_runtime_paths())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["paths"]["projectDir"], str(PROJECT_ROOT))
        self.assertEqual(payload["paths"]["outputDir"], str(LOG_DIR / "article_capture"))
        self.assertEqual(payload["paths"]["storageDir"], "D:\\tmp\\runtime\\storages")
        self.assertEqual(payload["paths"]["logDir"], str(LOG_DIR))

    def test_open_runtime_path_api_opens_selected_directory_key(self) -> None:
        runtime_config = AppRuntimeConfig(
            storage=StorageConfig(db_path=Path("D:/tmp/runtime/awa_public.sqlite3"))
        )
        opened_paths: list[Path] = []

        def open_directory(path: Path) -> bool:
            opened_paths.append(path)
            return True

        api = WebviewApi(
            task_manager=FailingTaskManager(),
            runtime_config=runtime_config,
            directory_opener=open_directory,
        )

        payload = json.loads(api.open_runtime_path(json.dumps({"key": "storageDir"})))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["path"], "D:\\tmp\\runtime\\storages")
        self.assertEqual(opened_paths, [Path("D:/tmp/runtime/storages")])

    def test_select_archive_export_directory_returns_user_selected_folder(self) -> None:
        api = WebviewApi(
            task_manager=FailingTaskManager(),
            export_directory_selector=lambda: Path("D:/exports/article-records"),
        )

        payload = json.loads(api.select_archive_export_directory())

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "selected")
        self.assertEqual(payload["path"], "D:\\exports\\article-records")

    def test_select_archive_export_directory_handles_cancel(self) -> None:
        api = WebviewApi(
            task_manager=FailingTaskManager(),
            export_directory_selector=lambda: None,
        )

        payload = json.loads(api.select_archive_export_directory())

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["path"], "")


if __name__ == "__main__":
    unittest.main()
