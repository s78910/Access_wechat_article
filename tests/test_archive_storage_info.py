from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.modules.storage.archive_storage_info import format_size_label, resolve_article_archive_info


class ArchiveStorageInfoTest(unittest.TestCase):
    def test_resolve_article_archive_info_sums_duplicate_dirs_for_same_article(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storages"
            first_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章"
            second_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章_1"
            other_dir = storage_root / "测试公众号" / "2026-06-19 18-30 测试文章_2"
            first_dir.mkdir(parents=True)
            second_dir.mkdir(parents=True)
            other_dir.mkdir(parents=True)

            first_detail = json.dumps({"short_link": "https://mp.weixin.qq.com/s/right"}, ensure_ascii=False)
            second_detail = json.dumps({"short_link": "https://mp.weixin.qq.com/s/right"}, ensure_ascii=False)
            other_detail = json.dumps({"short_link": "https://mp.weixin.qq.com/s/other"}, ensure_ascii=False)
            first_payload = b"<html>first</html>"
            second_payload = b"<html>second</html>"
            other_payload = b"<html>other</html>"

            (first_dir / "article_detail.json").write_text(first_detail, encoding="utf-8")
            (first_dir / "original_main.html").write_bytes(first_payload)
            (second_dir / "article_detail.json").write_text(second_detail, encoding="utf-8")
            (second_dir / "original_main.html").write_bytes(second_payload)
            (other_dir / "article_detail.json").write_text(other_detail, encoding="utf-8")
            (other_dir / "original_main.html").write_bytes(other_payload)

            info = resolve_article_archive_info(
                storage_root=storage_root,
                account_name="测试公众号",
                published_article_time="2026-06-19 18:30",
                article_title="测试文章",
                article_link="https://mp.weixin.qq.com/s/right",
            )

            expected_size = (
                len(first_detail.encode("utf-8"))
                + len(first_payload)
                + len(second_detail.encode("utf-8"))
                + len(second_payload)
            )
            self.assertEqual(info.archive_dirs, [first_dir, second_dir])
            self.assertEqual(info.archive_dir, first_dir)
            self.assertEqual(info.size_bytes, expected_size)
            self.assertEqual(info.size_label, format_size_label(info.size_bytes))

    def test_resolve_article_archive_info_returns_zero_when_archive_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            info = resolve_article_archive_info(
                storage_root=Path(temp_dir) / "storages",
                account_name="测试公众号",
                published_article_time="2026-06-19 18:30",
                article_title="不存在",
                article_link="https://mp.weixin.qq.com/s/missing",
            )

            self.assertIsNone(info.archive_dir)
            self.assertEqual(info.size_bytes, 0)
            self.assertEqual(info.size_label, "0 B")


if __name__ == "__main__":
    unittest.main()
