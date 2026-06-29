from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.config import AppFeatureConfig, AppRuntimeConfig
from src.modules.system.runtime_cleanup import run_startup_temp_cleanup


class RuntimeCleanupTest(unittest.TestCase):
    def test_startup_temp_cleanup_removes_tmp_contents_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_dir = Path(temp_dir) / "tmp"
            nested = tmp_dir / "old" / "capture.json"
            nested.parent.mkdir(parents=True)
            nested.write_text("stale", encoding="utf-8")

            result = run_startup_temp_cleanup(
                AppRuntimeConfig(app=AppFeatureConfig(auto_clean_temp_files=True)),
                temp_dir=tmp_dir,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "cleared")
            self.assertFalse(nested.exists())
            self.assertTrue(tmp_dir.exists())

    def test_startup_temp_cleanup_skips_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_dir = Path(temp_dir) / "tmp"
            target = tmp_dir / "keep.txt"
            tmp_dir.mkdir()
            target.write_text("keep", encoding="utf-8")

            result = run_startup_temp_cleanup(
                AppRuntimeConfig(app=AppFeatureConfig(auto_clean_temp_files=False)),
                temp_dir=tmp_dir,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "disabled")
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
