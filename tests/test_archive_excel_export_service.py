from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from src.modules.storage.archive_excel_export_service import ArchiveExcelExportService
from src.modules.storage.sqlite_store import SQLiteStore


SHEET_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    root = ElementTree.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row_node in root.findall(".//x:sheetData/x:row", SHEET_NS):
        row_values: list[str] = []
        for cell_node in row_node.findall("x:c", SHEET_NS):
            text_node = cell_node.find("x:is/x:t", SHEET_NS)
            row_values.append(text_node.text if text_node is not None and text_node.text is not None else "")
        rows.append(row_values)
    return rows


class ArchiveExcelExportServiceTest(unittest.TestCase):
    def test_export_account_writes_rows_from_sqlite_and_article_detail_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "awa_public.sqlite3"
            storage_root = root / "storages"
            target_dir = root / "exports"
            temp_root = root / "tmp"
            store = SQLiteStore(db_path)
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "较早文章",
                    "published_article_time": "2026-06-19 18:30",
                    "article_link": "https://mp.weixin.qq.com/s/older",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 11:00:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "较晚文章",
                    "published_article_time": "2026-06-20 08:00",
                    "article_link": "https://mp.weixin.qq.com/s/newer",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 12:00:00",
                    "collect_status": "saved",
                }
            )
            store.save_public_article(
                {
                    "account_name": "测试公众号",
                    "article_title": "失败文章",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 13:00:00",
                    "collect_status": "failed",
                }
            )
            detail_dir = storage_root / "测试公众号" / "2026-06-19 18-30 较早文章"
            detail_dir.mkdir(parents=True)
            (detail_dir / "article_detail.json").write_text(
                json.dumps(
                    {
                        "short_link": "https://mp.weixin.qq.com/s/older-from-json",
                        "audience_count": 1000,
                        "read_count": 2000,
                        "like_count": 30,
                        "share_count": 40,
                        "recommend_count": 50,
                        "comment_count": 6,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            account_id = int(store.list_public_accounts()[0]["id"])

            result = ArchiveExcelExportService(
                store=store,
                storage_root=storage_root,
                temp_root=temp_root,
            ).export_accounts([account_id], target_dir)

            self.assertTrue(result.ok)
            self.assertEqual(result.exported_file_count, 1)
            self.assertEqual(result.total_row_count, 3)
            exported_path = Path(result.files[0].output_path)
            self.assertTrue(exported_path.exists())
            self.assertIn("测试公众号_文章记录_3篇_", exported_path.name)
            self.assertEqual(result.files[0].temp_path.parent.parent, temp_root)

            rows = _read_xlsx_rows(exported_path)
            self.assertEqual(
                rows[0],
                [
                    "序号",
                    "记录状态",
                    "发布时间",
                    "文章标题",
                    "文章短链接",
                    "听众量",
                    "阅读量",
                    "点赞量",
                    "转发量",
                    "推荐量",
                    "评论量",
                    "记录获取时间",
                ],
            )
            self.assertEqual(rows[1][:5], ["1", "未找到本地归档目录", "2026-06-20 08:00", "较晚文章", "https://mp.weixin.qq.com/s/newer"])
            self.assertEqual(rows[1][5:11], ["", "", "", "", "", ""])
            self.assertEqual(rows[2], ["2", "保存成功", "2026-06-19 18:30", "较早文章", "https://mp.weixin.qq.com/s/older-from-json", "1000", "2000", "30", "40", "50", "6", "2026-06-21 11:00:00"])
            self.assertEqual(rows[3][:5], ["3", "采集失败", "", "失败文章", ""])

    def test_export_multiple_accounts_creates_one_workbook_per_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SQLiteStore(root / "data" / "awa_public.sqlite3")
            for account_name, article_title, link in (
                ("公众号A", "文章A", "https://mp.weixin.qq.com/s/a"),
                ("公众号B", "文章B", "https://mp.weixin.qq.com/s/b"),
            ):
                store.save_public_article(
                    {
                        "account_name": account_name,
                        "article_title": article_title,
                        "published_article_time": "2026-06-20 08:00",
                        "article_link": link,
                        "record_type": "文章详情",
                        "collect_time": "2026-06-21 11:00:00",
                        "collect_status": "saved",
                    }
                )
            account_ids = [int(row["id"]) for row in store.list_public_accounts()]

            result = ArchiveExcelExportService(
                store=store,
                storage_root=root / "storages",
                temp_root=root / "tmp",
            ).export_accounts(account_ids, root / "exports")

            self.assertTrue(result.ok)
            self.assertEqual(result.exported_file_count, 2)
            self.assertEqual({Path(file.output_path).name.split("_文章记录_", 1)[0] for file in result.files}, {"公众号A", "公众号B"})

    def test_export_requires_target_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SQLiteStore(root / "data" / "awa_public.sqlite3")
            store.save_public_article(
                {
                    "account_name": "公众号A",
                    "article_title": "文章A",
                    "published_article_time": "2026-06-20 08:00",
                    "article_link": "https://mp.weixin.qq.com/s/a",
                    "record_type": "文章详情",
                    "collect_time": "2026-06-21 11:00:00",
                    "collect_status": "saved",
                }
            )

            result = ArchiveExcelExportService(
                store=store,
                storage_root=root / "storages",
                temp_root=root / "tmp",
            ).export_accounts([1], "")

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "missing-target-dir")
            self.assertEqual(result.exported_file_count, 0)


if __name__ == "__main__":
    unittest.main()
