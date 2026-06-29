from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TargetArchitectureLayoutTest(unittest.TestCase):
    def test_legacy_src_module_directories_are_removed(self) -> None:
        """旧的 src/db、src/proxy、src/details、src/utils 不再作为生产入口保留。"""
        legacy_dirs = ("db", "proxy", "details", "utils")

        for dirname in legacy_dirs:
            self.assertFalse((PROJECT_ROOT / "src" / dirname).exists(), f"legacy src/{dirname} should be removed")

    def test_source_code_no_longer_imports_legacy_src_modules(self) -> None:
        """迁移后生产代码和测试都应直接使用 src.modules 下的新模块。"""
        forbidden_roots = ("db", "proxy", "details", "utils")
        forbidden_fragments = tuple(
            f"{prefix} src.{root}"
            for root in forbidden_roots
            for prefix in ("from", "import")
        )
        scanned_roots = (PROJECT_ROOT / "src", PROJECT_ROOT / "tests")
        offenders: list[str] = []

        for root in scanned_roots:
            for path in root.rglob("*.py"):
                if "webview" in path.parts or "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for fragment in forbidden_fragments:
                    if fragment in text:
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)} contains {fragment!r}")

        self.assertEqual([], offenders)

    def test_article_capture_worker_delegates_specific_capabilities_to_modules(self) -> None:
        """article_capture 只做任务编排，窗口、详情、评论、存储等能力放到 modules 中。"""
        source = (PROJECT_ROOT / "src" / "workers" / "article_capture.py").read_text(encoding="utf-8", errors="ignore")
        forbidden_imports = (
            "from src.workers.home_article_clicker import",
            "from src.workers.wechat_detail_windows import",
            "from src.modules.detail.article_detail import",
            "from src.modules.detail.comment_detail import",
            "from src.modules.storage.sqlite_store import",
        )

        offenders = [item for item in forbidden_imports if item in source]

        self.assertEqual([], offenders)
        self.assertIn("open_home_article_for_capture", source)
        self.assertLessEqual(len(source.splitlines()), 260)

    def test_runtime_defaults_use_data_directory(self) -> None:
        from src.core.config import DATA_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, LOG_DIR, PROJECT_ROOT, TMP_DIR

        self.assertEqual(DATA_DIR, PROJECT_ROOT / "data")
        self.assertEqual(DEFAULT_CONFIG_PATH, DATA_DIR / "custom.yaml")
        self.assertEqual(DEFAULT_DB_PATH, DATA_DIR / "awa_public.sqlite3")
        self.assertEqual(LOG_DIR, DATA_DIR / "logs")
        self.assertEqual(TMP_DIR, DATA_DIR / "tmp")

    def test_runtime_config_loads_default_data_custom_yaml(self) -> None:
        from src.config.runtime_config import load_runtime_config
        from src.core.config import DEFAULT_CONFIG_PATH

        self.assertTrue(DEFAULT_CONFIG_PATH.exists())

        config = load_runtime_config()

        self.assertEqual(config.storage.db_path.name, "awa_public.sqlite3")
        self.assertIn("data", config.storage.db_path.parts)

    def test_runtime_config_payload_resolves_relative_storage_path_from_data_dir(self) -> None:
        from src.config.runtime_config import update_runtime_config_from_payload
        from src.core.config import DATA_DIR

        config = update_runtime_config_from_payload({"storage": {"db_path": "awa_public.sqlite3"}})

        self.assertEqual(config.storage.db_path, DATA_DIR / "awa_public.sqlite3")

    def test_new_module_entrypoints_are_importable(self) -> None:
        from src.core.task_context import TaskContext
        from src.modules.detail.article_detail import fetch_article_detail_from_keyed_url
        from src.modules.detail.comment_detail import fetch_comments_to_archive
        from src.modules.proxy.certificate import check_mitm_ca_certificate
        from src.modules.proxy.mitm_controller import run_mitm_worker
        from src.modules.proxy.system_proxy import WindowsSystemProxy
        from src.modules.storage.archive_store import write_json_file
        from src.modules.storage.mitm_probe_store import write_current_mitm_target_probe
        from src.modules.storage.path_builder import build_article_archive_dir
        from src.modules.storage.sqlite_store import SQLiteStore
        from src.modules.system.env_checker import get_system_status
        from src.modules.system.port_checker import is_tcp_port_open
        from src.modules.system.process_checker import get_process_command_line
        from src.modules.utils.file_utils import clean_path_part
        from src.modules.utils.text_utils import normalize_text
        from src.modules.utils.time_utils import format_datetime_for_dir
        from src.modules.window.article_clicker import trigger_home_article_open
        from src.modules.window.home_display_cache import HomeDisplayCache
        from src.modules.window.wechat_detector import detect_wechat_home_window
        from src.modules.window.window_activator import activate_wechat_window_for_uia
        from src.workers.body_worker import run_body_worker

        context = TaskContext(run_id="demo", record_limit=1)
        self.assertEqual(context.run_id, "demo")
        self.assertEqual(context.to_worker_payload()["record_limit"], 1)
        self.assertTrue(callable(fetch_article_detail_from_keyed_url))
        self.assertTrue(callable(fetch_comments_to_archive))
        self.assertTrue(callable(check_mitm_ca_certificate))
        self.assertTrue(callable(run_mitm_worker))
        self.assertTrue(callable(WindowsSystemProxy))
        self.assertTrue(callable(write_json_file))
        self.assertTrue(callable(write_current_mitm_target_probe))
        self.assertTrue(callable(build_article_archive_dir))
        self.assertTrue(callable(SQLiteStore))
        self.assertIn("pythonVersion", get_system_status())
        self.assertIsInstance(is_tcp_port_open("127.0.0.1", 1, timeout_seconds=0.01), bool)
        self.assertIsInstance(get_process_command_line(-1), str)
        self.assertEqual(clean_path_part(" a<b>c "), "a_b_c")
        self.assertEqual(normalize_text("  demo  "), "demo")
        self.assertEqual(format_datetime_for_dir("2026-06-20 14:30:00"), "2026-06-20 14-30")
        self.assertTrue(callable(trigger_home_article_open))
        self.assertTrue(callable(HomeDisplayCache))
        self.assertTrue(callable(detect_wechat_home_window))
        self.assertTrue(callable(activate_wechat_window_for_uia))
        self.assertTrue(callable(run_body_worker))

    def test_storage_path_builder_creates_unique_article_directory(self) -> None:
        from src.modules.storage.path_builder import build_article_archive_dir

        with tempfile.TemporaryDirectory() as temp_dir:
            first = build_article_archive_dir(
                storage_root=Path(temp_dir),
                account_name="测试公众号",
                published_time="2026-06-20 14:30",
                article_title="标题/非法字符",
            )
            first.mkdir(parents=True)

            second = build_article_archive_dir(
                storage_root=Path(temp_dir),
                account_name="测试公众号",
                published_time="2026-06-20 14:30",
                article_title="标题/非法字符",
            )

            self.assertEqual(first.name, "2026-06-20 14-30 标题_非法字符")
            self.assertEqual(second.name, "2026-06-20 14-30 标题_非法字符_1")


if __name__ == "__main__":
    unittest.main()
