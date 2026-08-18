from __future__ import annotations

import unittest
from inspect import signature
from pathlib import Path

from src.config.config_loader import build_app_config, load_config_mapping
from src.modules.window.wechat_home_window_finder import find_wechat_home_window


PROJECT_ROOT = Path(__file__).resolve().parents[1]


REMOVED_WINDOW_KEYS = {
    "home_find_use_article_probe",
    "screen_click_wait_seconds",
    "max_scroll_attempts",
    "scroll_probe_growth_factor",
    "scroll_settle_timeout_seconds",
    "visible_snapshot_max_age_seconds",
}


class WindowConfigCleanupTest(unittest.TestCase):
    def test_window_range_settings_are_loaded_from_latest_yaml_shape(self) -> None:
        mapping = load_config_mapping(PROJECT_ROOT / "src" / "config" / "system.yaml")
        windows_command = mapping["windows_command"]

        self.assertEqual(
            windows_command["single_article_tab"][
                "article_title_poll_interval_seconds_range"
            ],
            [0.05, 0.15],
        )
        self.assertEqual(
            windows_command["home_scroll"]["scroll_probe_interval_seconds_range"],
            [0.1, 0.4],
        )
        self.assertEqual(
            windows_command["home_scroll"]["date_seek_scroll_steps_range"],
            [3, 18],
        )

        config = build_app_config(mapping, project_root=PROJECT_ROOT)

        # YAML 用数组表达起止区间，运行时代码仍拿到拆分后的具体字段。
        self.assertEqual(config.window.article_title_poll_interval_seconds, 0.15)
        self.assertEqual(config.window.scroll_probe_interval_seconds, 0.1)
        self.assertEqual(config.window.scroll_probe_max_interval_seconds, 0.4)
        self.assertEqual(config.window.scroll_wheel_steps, 3)
        self.assertEqual(config.window.date_seek_max_steps, 18)

    def test_removed_window_command_keys_are_not_in_yaml_files(self) -> None:
        # 这些字段已从当前窗口点击流程移除，不能再出现在用户可编辑 YAML 中。
        for config_path in (
            PROJECT_ROOT / "src" / "config" / "system.yaml",
            PROJECT_ROOT / "data" / "custom.yaml",
        ):
            with self.subTest(config_path=str(config_path)):
                mapping = load_config_mapping(config_path)
                windows_command = mapping.get("windows_command", {})
                actual_keys: set[str] = set()
                for section in ("home_window", "home_scroll"):
                    section_mapping = windows_command.get(section, {})
                    actual_keys.update(section_mapping.keys())

                self.assertTrue(
                    REMOVED_WINDOW_KEYS.isdisjoint(actual_keys),
                    f"{config_path} still contains removed keys: "
                    f"{sorted(REMOVED_WINDOW_KEYS & actual_keys)}",
                )

    def test_removed_window_keys_do_not_enter_runtime_config(self) -> None:
        config = build_app_config(
            load_config_mapping(PROJECT_ROOT / "src" / "config" / "system.yaml"),
            project_root=PROJECT_ROOT,
        )

        for key in REMOVED_WINDOW_KEYS - {"scroll_probe_growth_factor"}:
            with self.subTest(key=key):
                self.assertFalse(hasattr(config.window, key), key)

    def test_home_window_finder_no_longer_exposes_article_probe_switch(self) -> None:
        parameters = signature(find_wechat_home_window).parameters

        self.assertNotIn("article_counter", parameters)
        self.assertNotIn("use_article_probe", parameters)


if __name__ == "__main__":
    unittest.main()
