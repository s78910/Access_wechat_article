from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape

from src.storage.sqlite.connection import sqlite_connection


EXPORT_HEADERS = [
    "序号",
    "收集时间",
    "公众号名",
    "标题",
    "发布时间",
    "文章链接",
    "文章短链",
    "发文IP",
    "听众量",
    "阅读量",
    "点赞量",
    "分享量",
    "推荐量",
    "评论量",
]

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True, slots=True)
class ArchiveAccount:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ArchiveArticle:
    id: int
    account_id: int
    title: str
    published_time: str
    article_link: str
    archive_dir: str
    last_collected_time: str


class ArchiveExcelExportService:
    """按公众号把本地文章详情汇总导出为 .xlsx 文件。"""

    def export_accounts(
        self,
        *,
        database_path: str | Path,
        storage_root: str | Path,
        account_ids: list[int],
        target_dir: str | Path,
    ) -> dict[str, Any]:
        selected_ids = self._normalize_account_ids(account_ids)
        if not selected_ids:
            return {
                "ok": False,
                "status": "failed",
                "exportedFileCount": 0,
                "totalRowCount": 0,
                "files": [],
                "missingAccountIds": [],
                "warnings": [],
                "message": "请先选择需要导出的公众号。",
            }

        output_root = Path(target_dir).expanduser().resolve()
        if output_root.exists() and not output_root.is_dir():
            return {
                "ok": False,
                "status": "failed",
                "exportedFileCount": 0,
                "totalRowCount": 0,
                "files": [],
                "missingAccountIds": [],
                "warnings": [],
                "message": f"导出目标不是目录：{output_root}",
            }
        output_root.mkdir(parents=True, exist_ok=True)

        storage_root_path = Path(storage_root).resolve()
        accounts, articles_by_account = self._load_export_source(database_path, selected_ids)
        missing_account_ids = [account_id for account_id in selected_ids if account_id not in accounts]

        files: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        used_file_names: set[str] = set()
        for account_id in selected_ids:
            account = accounts.get(account_id)
            if account is None:
                continue

            rows: list[list[Any]] = []
            for index, article in enumerate(articles_by_account.get(account_id, []), start=1):
                detail, detail_warning = self._read_article_detail(storage_root_path, article)
                if detail_warning:
                    warnings.append(
                        {
                            "accountId": account.id,
                            "articleId": article.id,
                            "title": article.title,
                            "message": detail_warning,
                        }
                    )
                rows.append(self._build_export_row(index, account, article, detail))

            file_name = self._unique_file_name(account, used_file_names)
            output_path = output_root / file_name
            self._write_xlsx_atomic(output_path, [EXPORT_HEADERS, *rows])
            files.append(
                {
                    "accountId": account.id,
                    "accountName": account.name,
                    "rowCount": len(rows),
                    "tempPath": "",
                    "outputPath": str(output_path),
                    "fileName": file_name,
                }
            )

        total_rows = sum(int(item["rowCount"]) for item in files)
        if not files:
            status = "failed"
            ok = False
            message = "未找到可导出的公众号。"
        elif missing_account_ids or warnings:
            status = "partial-failed"
            ok = True
            message = f"已导出 {len(files)} 个 Excel 文件，共 {total_rows} 条记录；部分文章详情文件缺失，已用数据库索引字段兜底。"
        else:
            status = "ok"
            ok = True
            message = f"已导出 {len(files)} 个 Excel 文件，共 {total_rows} 条记录。"

        return {
            "ok": ok,
            "status": status,
            "exportedFileCount": len(files),
            "totalRowCount": total_rows,
            "files": files,
            "missingAccountIds": missing_account_ids,
            "warnings": warnings,
            "message": message,
        }

    def _load_export_source(
        self,
        database_path: str | Path,
        account_ids: list[int],
    ) -> tuple[dict[int, ArchiveAccount], dict[int, list[ArchiveArticle]]]:
        placeholders = ",".join("?" for _ in account_ids)
        with sqlite_connection(database_path, write=False) as connection:
            account_rows = connection.execute(
                f"""
                SELECT id, account_name
                FROM awa_public_accounts
                WHERE id IN ({placeholders})
                """,
                tuple(account_ids),
            ).fetchall()
            accounts = {
                int(row["id"]): ArchiveAccount(id=int(row["id"]), name=str(row["account_name"]))
                for row in account_rows
            }

            articles_by_account: dict[int, list[ArchiveArticle]] = {
                account_id: [] for account_id in accounts
            }
            for account_id in accounts:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        account_id,
                        article_title,
                        published_article_time,
                        article_link,
                        archive_dir,
                        last_collected_time
                    FROM awa_public_articles
                    WHERE account_id = ?
                    ORDER BY published_article_time DESC, last_collected_time DESC, id DESC
                    """,
                    (account_id,),
                ).fetchall()
                articles_by_account[account_id] = [
                    ArchiveArticle(
                        id=int(row["id"]),
                        account_id=int(row["account_id"]),
                        title=str(row["article_title"] or ""),
                        published_time=str(row["published_article_time"] or ""),
                        article_link=str(row["article_link"] or ""),
                        archive_dir=str(row["archive_dir"] or ""),
                        last_collected_time=str(row["last_collected_time"] or ""),
                    )
                    for row in rows
                ]
        return accounts, articles_by_account

    def _read_article_detail(
        self,
        storage_root: Path,
        article: ArchiveArticle,
    ) -> tuple[dict[str, Any], str]:
        archive_dir = self._resolve_archive_dir(storage_root, article.archive_dir)
        if archive_dir is None:
            return {}, "文章归档目录无效，已使用数据库索引字段导出。"

        detail_path = archive_dir / "article_detail.json"
        if not detail_path.is_file():
            return {}, "article_detail.json 不存在，已使用数据库索引字段导出。"

        try:
            raw_detail = json.loads(detail_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {}, f"article_detail.json 读取失败：{exc}"
        if not isinstance(raw_detail, dict):
            return {}, "article_detail.json 不是 JSON 对象，已使用数据库索引字段导出。"
        return raw_detail, ""

    def _build_export_row(
        self,
        index: int,
        account: ArchiveAccount,
        article: ArchiveArticle,
        detail: dict[str, Any],
    ) -> list[Any]:
        # JSON 文件保存的是采集详情；缺失时只兜底数据库索引里已有的字段。
        return [
            index,
            self._first_text(detail, "collect_time", "collected_time")
            or article.last_collected_time,
            self._first_text(detail, "account_name") or account.name,
            self._first_text(detail, "article_title") or article.title,
            self._first_text(detail, "published_article_time") or article.published_time,
            self._first_text(detail, "article_link") or article.article_link,
            self._first_text(detail, "article_short_link", "short_link"),
            self._first_text(detail, "ip_location", "publish_ip", "article_ip"),
            self._number_or_blank(detail.get("audience_count")),
            self._number_or_blank(detail.get("read_count")),
            self._number_or_blank(detail.get("like_count")),
            self._number_or_blank(detail.get("share_count")),
            self._number_or_blank(detail.get("recommend_count")),
            self._number_or_blank(detail.get("comment_count")),
        ]

    def _resolve_archive_dir(self, storage_root: Path, archive_dir: str) -> Path | None:
        if not archive_dir.strip():
            return None
        raw_path = Path(archive_dir)
        resolved = raw_path if raw_path.is_absolute() else storage_root / raw_path
        try:
            resolved = resolved.resolve()
            resolved.relative_to(storage_root.resolve())
        except ValueError:
            return None
        return resolved

    def _write_xlsx_atomic(self, output_path: Path, rows: list[list[Any]]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.parent / f".{output_path.stem}.{uuid4().hex}.tmp.xlsx"
        try:
            self._write_xlsx(temp_path, rows)
            os.replace(temp_path, output_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_xlsx(self, path: Path, rows: list[list[Any]]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".xlsx",
            prefix=".awa-export-",
            dir=path.parent,
            delete=False,
        ) as temp_file:
            temp_zip_path = Path(temp_file.name)

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
                workbook.writestr("[Content_Types].xml", self._content_types_xml())
                workbook.writestr("_rels/.rels", self._root_rels_xml())
                workbook.writestr("xl/workbook.xml", self._workbook_xml())
                workbook.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels_xml())
                workbook.writestr("xl/styles.xml", self._styles_xml())
                workbook.writestr("xl/worksheets/sheet1.xml", self._sheet_xml(rows))
            os.replace(temp_zip_path, path)
        finally:
            temp_zip_path.unlink(missing_ok=True)

    def _sheet_xml(self, rows: list[list[Any]]) -> str:
        sheet_rows = []
        for row_number, row_values in enumerate(rows, start=1):
            cells = [
                self._cell_xml(row_number, column_index, value, is_header=row_number == 1)
                for column_index, value in enumerate(row_values, start=1)
            ]
            sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            "<cols>"
            '<col min="1" max="1" width="8" customWidth="1"/>'
            '<col min="2" max="6" width="24" customWidth="1"/>'
            '<col min="7" max="8" width="18" customWidth="1"/>'
            '<col min="9" max="14" width="12" customWidth="1"/>'
            "</cols>"
            f"<sheetData>{''.join(sheet_rows)}</sheetData>"
            "</worksheet>"
        )

    def _cell_xml(
        self,
        row_number: int,
        column_index: int,
        value: Any,
        *,
        is_header: bool,
    ) -> str:
        reference = f"{self._column_name(column_index)}{row_number}"
        style = ' s="1"' if is_header else ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{reference}"{style}><v>{value}</v></c>'
        text_value = "" if value is None else str(value)
        escaped = escape(text_value)
        preserve_space = ' xml:space="preserve"' if text_value != text_value.strip() else ""
        return f'<c r="{reference}" t="inlineStr"{style}><is><t{preserve_space}>{escaped}</t></is></c>'

    def _unique_file_name(self, account: ArchiveAccount, used_file_names: set[str]) -> str:
        base_name = _INVALID_FILENAME_CHARS.sub("_", account.name).strip(" ._")
        if not base_name:
            base_name = f"公众号_{account.id}"
        base_name = base_name[:120]
        file_name = f"{base_name}_数据档案.xlsx"
        if file_name not in used_file_names:
            used_file_names.add(file_name)
            return file_name

        file_name = f"{base_name}_{account.id}_数据档案.xlsx"
        used_file_names.add(file_name)
        return file_name

    def _normalize_account_ids(self, account_ids: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for raw_id in account_ids:
            try:
                account_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if account_id <= 0 or account_id in seen:
                continue
            normalized.append(account_id)
            seen.add(account_id)
        return normalized

    def _first_text(self, detail: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = detail.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _number_or_blank(self, value: Any) -> int | float | str:
        if value is None or value == "":
            return ""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip().replace(",", "")
        if not text:
            return ""
        try:
            number = float(text)
        except ValueError:
            return str(value)
        return int(number) if number.is_integer() else number

    def _column_name(self, index: int) -> str:
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def _content_types_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        )

    def _root_rels_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _workbook_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            '<sheet name="数据档案" sheetId="1" r:id="rId1"/>'
            "</sheets>"
            "</workbook>"
        )

    def _workbook_rels_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        )

    def _styles_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2">'
            '<font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font>'
            "</fonts>"
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
            "</cellXfs>"
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '<dxfs count="0"/>'
            '<tableStyles count="0" defaultTableStyle="TableStyleMedium9" defaultPivotStyle="PivotStyleLight16"/>'
            "</styleSheet>"
        )
