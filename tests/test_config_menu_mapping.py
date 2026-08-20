from __future__ import annotations

import unittest
from pathlib import Path

from src.config.config_loader import build_app_config


class ConfigMenuMappingTests(unittest.TestCase):
    def test_config_loader_no_longer_reads_removed_legacy_menu_paths(self) -> None:
        source = Path("src/config/config_loader.py").read_text(encoding="utf-8")

        for removed_key in (
            "windows_command",
            "data_acquisition",
            '"basic_info"',
            '"process_control"',
        ):
            self.assertNotIn(removed_key, source)

    def test_new_main_flow_and_single_article_task_menu_maps_to_runtime_config(self) -> None:
        """新 YAML 菜单结构应能映射到现有 AppConfig，避免业务代码大范围重写。"""
        config = build_app_config(
            {
                "software": {"version": "2.1.1"},
                "basic_settings": {
                    "runtime_maintenance": {
                        "log_level": "INFO",
                        "auto_clean_temp_files": True,
                        "temp_retention_days": 7,
                        "log_retention_days": 30,
                    },
                    "project_storage": {
                        "article_storage_root": "storages",
                        "temp_dir": "data/tmp",
                        "log_dir": "data/logs",
                    },
                    "database_settings": {
                        "data_schema_version": "v2.1",
                        "db_dir": "data/sql",
                    },
                    "proxy_settings": {
                        "host": "127.0.0.1",
                        "port": 18000,
                        "verification_url": "https://mitm.it/",
                        "confdir": ".mitmproxy",
                        "ca_cert_path": ".mitmproxy/mitmproxy-ca-cert.cer",
                        "startup_delay_seconds": 0.0,
                        "enable_system_proxy": True,
                        "ssl_insecure": True,
                    },
                },
                "main_flow": {
                    "home_window": {
                        "activation_wait_seconds": 0.05,
                        "home_find_timeout_seconds": 3.0,
                    },
                    "home_scroll": {
                        "date_seek_scroll_steps_range": [3, 18],
                        "scroll_initial_delay_seconds": 0.05,
                        "scroll_probe_interval_seconds_range": [0.1, 0.4],
                        "unchanged_before_bounce_seconds": 0.6,
                        "lazy_load_timeout_seconds": 3.0,
                        "bounce_enabled": True,
                        "bounce_attempts": 2,
                        "bounce_up_steps": 2,
                        "bounce_pause_seconds": 0.2,
                        "bounce_down_steps": 6,
                    },
                    "dispatch_control": {
                        "single_task_interval_seconds": 0.25,
                    },
                },
                "single_article_task": {
                    "article_tab": {
                        "restore_focus_after_close": True,
                        "article_open_timeout_seconds": 12.0,
                        "article_title_poll_interval_seconds_range": [0.05, 0.15],
                        "article_title_stable_delay_seconds": 0.1,
                        "article_close_confirm_timeout_seconds": 3.0,
                    },
                    "mitm_capture": {
                        "ready_timeout_seconds": 10.0,
                        "capture_timeout_seconds": 20.0,
                        "result_timeout_seconds": 11.0,
                        "listener_shutdown_timeout_seconds": 3.0,
                        "close_as_capture_deadline": True,
                    },
                    "html_storage": {
                        "request_timeout_seconds": 10.0,
                    },
                    "comment_collection": {
                        "enabled_by_default": True,
                        "request_timeout_seconds": 10.0,
                        "page_interval_seconds": 0.5,
                        "top_level_max_pages": 50,
                        "max_concurrent_processes": 3,
                    },
                    "offline_cache": {
                        "enabled_by_default": False,
                        "max_scroll_seconds": 30.0,
                        "resource_timeout_seconds": 10.0,
                        "max_concurrent_processes": 3,
                    },
                },
            },
            project_root=Path.cwd(),
        )

        self.assertEqual(config.proxy.port, 18000)
        self.assertEqual(config.request.request_interval_seconds, 0.25)
        self.assertEqual(config.request.request_timeout_seconds, 10.0)
        self.assertEqual(config.window.scroll_wheel_steps, 3)
        self.assertEqual(config.window.date_seek_max_steps, 18)
        self.assertEqual(config.window.scroll_probe_interval_seconds, 0.1)
        self.assertEqual(config.window.scroll_probe_max_interval_seconds, 0.4)
        self.assertTrue(config.window.restore_focus_after_close)
        self.assertEqual(config.window.article_title_poll_initial_interval_seconds, 0.05)
        self.assertEqual(config.window.article_title_poll_max_interval_seconds, 0.15)
        self.assertEqual(config.mitm_capture.ready_timeout_seconds, 10.0)
        self.assertTrue(config.comment.enabled_by_default)
        self.assertEqual(config.comment.max_pages, 50)
        self.assertEqual(config.offline_cache.max_concurrent_processes, 3)


if __name__ == "__main__":
    unittest.main()
